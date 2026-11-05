"""Main window. Laid out like OpenSchematix: menu, toolbar, three panes with a bottom dock, status bar."""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .. import APP_NAME, DONATE_URL, SCHEMATIC_EXTENSIONS, STUDY_EXTENSION, VERSION, catalog, circuit as circuit_mod
from .. import engine, report
from .. import study as study_mod
from ..flowpaths import FlowPaths
from ..integrations import caldera as cal
from ..integrations import revisionworx as rw
from ..integrations import tools
from ..settings import Settings
from ..units import Units
from ..vendor.openschematix.gui import theme as th
from ..vendor.openschematix.gui.widgets import IconButton, ToastHost, ToolbarSeparator, Tooltip, set_current_theme
from . import icons_extra  # noqa: F401  (registers FluidWorx's icons)
from .dialogs import AboutDialog, CalderaImportDialog, PreferencesDialog, RevisionDialog, ShortcutsDialog
from .panels import ChecksPanel, CircuitPanel, EventsPanel, FaultsPanel, Inspector, LinksPanel, TracePanel
from .simcanvas import SimCanvas

FILETYPES_ALL = [("FluidWorx and OpenSchematix files", "*.fluidworx *.schematix *.osch"),
                 ("FluidWorx study", "*" + STUDY_EXTENSION), ("OpenSchematix project", "*.schematix"),
                 ("OpenSchematix legacy drawing", "*.osch"), ("All files", "*.*")]
FILETYPES_SCHEMATIC = [("OpenSchematix files", "*.schematix *.osch"), ("All files", "*.*")]
SPEEDS = {"×0.1": 0.1, "×0.25": 0.25, "×0.5": 0.5, "×1": 1.0, "×2": 2.0, "×5": 5.0}
FRAME_MS = 33
STEP_BUDGET_S = 0.022


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "fluidworx", "resources", name)
        if os.path.exists(p):
            return p
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", name)


def examples_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base and os.path.isdir(os.path.join(base, "fluidworx", "examples")):
        return os.path.join(base, "fluidworx", "examples")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


class App:
    def __init__(self, root: tk.Tk, path: str | None = None, settings: Settings | None = None):
        self.root = root
        self.settings = settings or Settings()
        th.set_ui_scale(root, self.settings["ui_scale"])
        self.theme = th.Theme(self.settings["theme"], self.settings["canvas_theme"])
        set_current_theme(self.theme)
        th.apply(root, self.theme)
        self.units = Units(self.settings["units"])
        self.icon_image = None
        self.circuit = None
        self.sim = None
        self.flowpaths = None
        self.currentpaths = None
        self.study: study_mod.Study | None = None
        self.study_path: str | None = None
        self.dirty = False
        self.selected = None
        self.doc = None
        self.running = False
        self.speed = 1.0
        self.rev_status = None
        self.source_mtime = None
        self._last_tick = time.monotonic()
        self._frame = 0
        self._rt_factor = 1.0
        self._races_said = 0
        self._results: queue.Queue = queue.Queue()
        self._load_icon()
        root.title(APP_NAME)
        root.minsize(1000, 620)
        root.geometry(self.settings["geometry"] or "1500x900")
        self._build()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.report_callback_exception = self._report_exception
        self._update_title()
        self._show_welcome()
        if path:
            root.after(50, lambda: self.open_path(path))
        root.after(FRAME_MS, self._tick)
        root.after(2000, self._watch_source)

    def _load_icon(self):
        try:
            self.icon_image = tk.PhotoImage(file=resource_path("fluidworx-64.png"))
            self.root.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

    def _report_exception(self, exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        print(text, file=sys.stderr)
        self.running = False
        try:
            messagebox.showerror(APP_NAME, f"Something went wrong and the simulation was paused. "
                                           f"Your files are not affected.\n\n{val}", parent=self.root)
        except tk.TclError:
            pass

    # ================================================================ layout
    def _build(self):
        self._build_menu()
        self.toolbar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(8, 4))
        self.toolbar.pack(fill="x")
        self._build_toolbar()
        ttk.Separator(self.root).pack(fill="x")
        self.status_bar = ttk.Frame(self.root, style="Status.TFrame", padding=(10, 3))
        self.status_bar.pack(fill="x", side="bottom")
        self._build_status()
        self.hpane = ttk.PanedWindow(self.root, orient="horizontal")
        self.hpane.pack(fill="both", expand=True)
        self.left = ttk.Notebook(self.hpane, padding=0)
        self.circuit_panel = CircuitPanel(self.left, self)
        self.left.add(self.circuit_panel, text="Circuit")
        self.center = ttk.Frame(self.hpane, style="Surface.TFrame")
        self.vpane = ttk.PanedWindow(self.center, orient="vertical")
        self.vpane.pack(fill="both", expand=True)
        self.doc_area = ttk.Frame(self.vpane, style="Surface.TFrame")
        self.banner = tk.Frame(self.doc_area, bd=0)
        self.tabs = ttk.Frame(self.doc_area, style="Raised.TFrame")
        self.tabs.pack(fill="x")
        self.canvas_holder = ttk.Frame(self.doc_area, style="Surface.TFrame")
        self.canvas_holder.pack(fill="both", expand=True)
        self.canvas = SimCanvas(self.canvas_holder, self)
        self.canvas.font_family = th.canvas_font_family(self.root)
        self.canvas.pack(fill="both", expand=True)
        self.toasts = ToastHost(self.canvas_holder)
        self.welcome = None
        self.vpane.add(self.doc_area, weight=5)
        self.dock = ttk.Notebook(self.vpane)
        self.trace_panel = TracePanel(self.dock, self)
        self.events_panel = EventsPanel(self.dock, self)
        self.checks_panel = ChecksPanel(self.dock, self)
        self.links_panel = LinksPanel(self.dock, self)
        self.faults_panel = FaultsPanel(self.dock, self)
        self.dock.add(self.trace_panel, text="Trace")
        self.dock.add(self.events_panel, text="Events")
        self.dock.add(self.checks_panel, text="Checks")
        self.dock.add(self.links_panel, text="Links")
        self.dock.add(self.faults_panel, text="Faults")
        self.vpane.add(self.dock, weight=2)
        self.right = ttk.Notebook(self.hpane)
        self.inspector = Inspector(self.right, self)
        self.right.add(self.inspector, text="Properties")
        self.hpane.add(self.left, weight=0)
        self.hpane.add(self.center, weight=1)
        self.hpane.add(self.right, weight=0)
        self.panel_visible = {"left": True, "right": True, "bottom": True}
        self.root.after(80, self._restore_layout)
        th.subscribe(lambda t: self._on_theme())

    def _restore_layout(self, attempts=0):
        w, h = self.root.winfo_width(), self.vpane.winfo_height()
        if (w < 400 or h < 200) and attempts < 40:
            self.root.after(50, lambda: self._restore_layout(attempts + 1))
            return
        lay = self.settings["layout"]
        try:
            self.hpane.sashpos(0, int(lay.get("left_w", 290)))
            self.hpane.sashpos(1, w - int(lay.get("right_w", 290)))
            self.vpane.sashpos(0, h - int(lay.get("dock_h", 230)))
        except tk.TclError:
            pass

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Import OpenSchematix circuit…", accelerator="Ctrl+I", command=self.import_schematic)
        f.add_command(label="Open study…", accelerator="Ctrl+O", command=self.open_dialog)
        self.recent_menu = tk.Menu(f, tearoff=0)
        f.add_cascade(label="Open recent", menu=self.recent_menu)
        ex = tk.Menu(f, tearoff=0)
        for name, label in self._examples():
            ex.add_command(label=label, command=lambda n=name: self.open_path(os.path.join(examples_dir(), n)))
        f.add_cascade(label="Open example", menu=ex)
        f.add_separator()
        f.add_command(label="Save study", accelerator="Ctrl+S", command=self.save)
        f.add_command(label="Save study as…", accelerator="Ctrl+Shift+S", command=self.save_as)
        f.add_command(label="Reload schematic from disk", command=self.reload_source)
        f.add_separator()
        e = tk.Menu(f, tearoff=0)
        e.add_command(label="Report (HTML)…", command=self.export_report)
        e.add_command(label="Trace (CSV)…", command=self.export_trace)
        e.add_command(label="Events (CSV)…", command=self.export_events)
        e.add_command(label="Calculations for Caldera (.caldera)…", command=self.export_caldera)
        f.add_cascade(label="Export", menu=e)
        f.add_separator()
        f.add_command(label="Preferences…", command=lambda: PreferencesDialog(self))
        f.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit)
        m.add_cascade(label="File", menu=f)
        v = tk.Menu(m, tearoff=0)
        v.add_command(label="Zoom in", accelerator="+", command=lambda: self.canvas.zoom_by(1.25))
        v.add_command(label="Zoom out", accelerator="-", command=lambda: self.canvas.zoom_by(0.8))
        v.add_command(label="Zoom to the circuit", accelerator="F", command=lambda: self.canvas.fit())
        v.add_separator()
        self.flow_var = tk.BooleanVar(value=self.settings["show_flow"])
        self.values_var = tk.BooleanVar(value=self.settings["show_values"])
        v.add_checkbutton(label="Flow animation", variable=self.flow_var, command=lambda: self._set_show("show_flow", self.flow_var.get()))
        v.add_checkbutton(label="Values on the drawing", variable=self.values_var, command=lambda: self._set_show("show_values", self.values_var.get()))
        v.add_separator()
        self.panel_vars = {}
        for side, label in (("left", "Circuit sidebar"), ("right", "Properties sidebar"), ("bottom", "Bottom panel")):
            var = tk.BooleanVar(value=True)
            v.add_checkbutton(label=label, variable=var, command=lambda s=side: self.toggle_panel(s))
            self.panel_vars[side] = var
        v.add_separator()
        tm = tk.Menu(v, tearoff=0)
        self.theme_var = tk.StringVar(value=self.theme.name)
        for key, t in th.THEMES.items():
            tm.add_radiobutton(label=t["label"], value=key, variable=self.theme_var, command=lambda k=key: self.set_theme(k))
        v.add_cascade(label="Theme", menu=tm)
        self.units_var = tk.StringVar(value=self.units.system)
        um = tk.Menu(v, tearoff=0)
        um.add_radiobutton(label="Metric (bar, L/min, mm)", value="metric", variable=self.units_var, command=lambda: self.set_units("metric"))
        um.add_radiobutton(label="US customary (psi, gpm, in)", value="us", variable=self.units_var, command=lambda: self.set_units("us"))
        v.add_cascade(label="Units", menu=um)
        m.add_cascade(label="View", menu=v)
        s = tk.Menu(m, tearoff=0)
        s.add_command(label="Play / pause", accelerator="Space", command=self.toggle_run)
        s.add_command(label="Step 0.1 s", accelerator=".", command=self.step_once)
        s.add_command(label="Reset", accelerator="Ctrl+R", command=self.reset)
        s.add_separator()
        self.speed_var = tk.StringVar(value="×1")
        sp = tk.Menu(s, tearoff=0)
        for label in SPEEDS:
            sp.add_radiobutton(label=label, value=label, variable=self.speed_var, command=self._speed_changed)
        s.add_cascade(label="Speed", menu=sp)
        s.add_separator()
        s.add_command(label="Show checks", command=lambda: self.dock.select(self.checks_panel))
        m.add_cascade(label="Simulate", menu=s)
        t = tk.Menu(m, tearoff=0)
        t.add_command(label="Edit schematic in OpenSchematix", accelerator="Ctrl+E", command=self.edit_in_openschematix)
        t.add_separator()
        t.add_command(label="RevisionWorx…", command=lambda: RevisionDialog(self))
        t.add_separator()
        t.add_command(label="Open Caldera", command=self.open_caldera)
        t.add_command(label="Use values from a Caldera project…", command=self.import_caldera)
        t.add_command(label="Send calculations to Caldera…", command=self.export_caldera)
        m.add_cascade(label="Connect", menu=t)
        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Keyboard and mouse…", command=lambda: ShortcutsDialog(self))
        h.add_separator()
        h.add_command(label="Support development…", command=lambda: webbrowser.open(DONATE_URL))
        h.add_command(label=f"About {APP_NAME}", command=lambda: AboutDialog(self))
        m.add_cascade(label="Help", menu=h)
        self.root.config(menu=m)
        th.recolor_menu(m, self.theme)
        self._rebuild_recent()

    @staticmethod
    def _examples():
        return [("lift_cylinder.schematix", "Lift cylinder, 4/3 tandem centre valve"),
                ("sequence_clamp_press.schematix", "Clamp then press, sequence valve"),
                ("load_holding.schematix", "Load holding, pilot-operated checks"),
                ("hydraulic_motor.schematix", "Hydraulic motor with meter-out speed control"),
                ("accumulator_circuit.schematix", "Accumulator charging and unloading"),
                ("pneumatic_cylinder.schematix", "Pneumatic cylinder, 5/2 valve with speed control"),
                ("pneumatic_single_acting.schematix", "Pneumatic single-acting cylinder, 3/2 valve"),
                ("plc_cylinder.schematix", "PLC running a cylinder, with position and pressure feedback"),
                ("relay_latch.schematix", "Relay logic: start, stop and automatic return"),
                ("motor_starter_pump.schematix", "Three-phase starter driving a hydraulic pump"),
                ("electronics_threshold.schematix", "Electronics: a comparator and a transistor switch a relay")]

    def _rebuild_recent(self):
        try:
            self.recent_menu.delete(0, "end")
        except tk.TclError:
            pass        # an empty menu has no "end" index on Tk 9
        for p in self.settings["recent_files"]:
            self.recent_menu.add_command(label=p, command=lambda x=p: self.open_path(x))
        if not self.settings["recent_files"]:
            self.recent_menu.add_command(label="(none)", state="disabled")

    def _build_toolbar(self):
        tb = self.toolbar

        def btn(icon, cmd, tip, side="left", checkable=False):
            b = IconButton(tb, icon, cmd, tip, checkable=checkable)
            b.pack(side=side, padx=1)
            return b

        def sep():
            ToolbarSeparator(tb).pack(side="left", padx=7, pady=3)
        btn("import", self.import_schematic, "Import an OpenSchematix circuit (Ctrl+I)")
        btn("open", self.open_dialog, "Open a study (Ctrl+O)")
        btn("save", self.save, "Save the study (Ctrl+S)")
        sep()
        self.play_btn = btn("play", self.toggle_run, "Play / pause (Space)")
        btn("step", self.step_once, "Step 0.1 s (.)")
        btn("reset", self.reset, "Reset to the start (Ctrl+R)")
        ttk.Label(tb, text="Speed", style="Toolbar.TLabel").pack(side="left", padx=(8, 3))
        speed = ttk.Combobox(tb, textvariable=self.speed_var, values=list(SPEEDS), state="readonly", width=5)
        speed.pack(side="left")
        speed.bind("<<ComboboxSelected>>", lambda e: (self._speed_changed(), self.canvas.focus_set()))
        self.time_label = tk.Label(tb, text="0.00 s", width=10, anchor="e")
        self.time_label._theme_bg = "toolbar"
        self.time_label.pack(side="left", padx=(10, 0))
        sep()
        btn("zoom_in", lambda: self.canvas.zoom_by(1.25), "Zoom in (+)")
        btn("zoom_out", lambda: self.canvas.zoom_by(0.8), "Zoom out (-)")
        btn("zoom_fit", lambda: self.canvas.fit(), "Zoom to the circuit (F)")
        sep()
        btn("schematic", self.edit_in_openschematix, "Edit the schematic in OpenSchematix (Ctrl+E)")
        btn("revision", lambda: RevisionDialog(self), "RevisionWorx: revision status and check-in")
        btn("calc", self.export_caldera, "Send cylinder calculations to Caldera")
        sep()
        btn("pdf", self.export_report, "Export a simulation report (HTML)")
        btn("csv", self.export_trace, "Export the recorded trace (CSV)")
        self.panel_buttons = {}
        for side, icon, tip in (("right", "properties", "Show / hide the properties sidebar"),
                                ("bottom", "trace", "Show / hide the bottom panel"),
                                ("left", "library", "Show / hide the circuit sidebar")):
            b = btn(icon, lambda s=side: self.toggle_panel(s), tip, side="right", checkable=True)
            b.set_checked(True)
            self.panel_buttons[side] = b
        ToolbarSeparator(tb).pack(side="right", padx=7, pady=3)
        btn("settings", lambda: PreferencesDialog(self), "Preferences", side="right")
        btn("theme", self.cycle_theme, "Switch to the next colour theme", side="right")
        self._style_time()

    def _style_time(self):
        u = self.theme.ui
        self.time_label.configure(bg=u["toolbar"], fg=u["text"], font=self.theme.fonts["mono"])

    def _build_status(self):
        sb = self.status_bar
        self.status = tk.StringVar(value="Ready.")
        self._status_base = "Ready."
        ttk.Label(sb, textvariable=self.status, style="Status.TLabel").pack(side="left", fill="x", expand=True)
        self.zoom_label = ttk.Label(sb, text="100%", style="Status.TLabel", width=6, anchor="e")
        self.zoom_label.pack(side="right")
        self.rt_label = ttk.Label(sb, text="", style="Status.TLabel")
        self.rt_label.pack(side="right", padx=8)
        Tooltip(self.rt_label, "Simulated seconds per real second")
        self.toggle_labels = {}
        for key, text, tip in (("show_values", "VALUES", "Show values on the drawing"),
                               ("show_flow", "FLOW", "Animate flow along the lines")):
            lab = tk.Label(sb, text=text, padx=6, pady=1, cursor="hand2")
            lab._theme_bg = "status"
            lab.pack(side="right", padx=1)
            lab.bind("<Button-1>", lambda e, k=key: self._set_show(k, not self.settings[k]))
            Tooltip(lab, tip)
            self.toggle_labels[key] = lab
        self.units_label = tk.Label(sb, text="", padx=6, pady=1, cursor="hand2")
        self.units_label._theme_bg = "status"
        self.units_label.pack(side="right", padx=1)
        self.units_label.bind("<Button-1>", lambda e: self.set_units("us" if self.units.system == "metric" else "metric"))
        Tooltip(self.units_label, "Switch between metric and US customary")
        self.fault_label = tk.Label(sb, text="", padx=6, pady=1, cursor="hand2")
        self.fault_label._theme_bg = "status"
        self.fault_label.bind("<Button-1>", lambda e: self.dock.select(self.faults_panel))
        Tooltip(self.fault_label, "Parts and lines failed on purpose: click to see them")
        self.check_label = ttk.Label(sb, text="", style="Status.TLabel", cursor="hand2")
        self.check_label.pack(side="right", padx=(8, 8))
        self.check_label.bind("<Button-1>", lambda e: self.dock.select(self.checks_panel))
        Tooltip(self.check_label, "What FluidWorx noticed about this circuit — click to read")
        self.rev_label = ttk.Label(sb, text="", style="Status.TLabel", cursor="hand2")
        self.rev_label.pack(side="right", padx=8)
        self.rev_label.bind("<Button-1>", lambda e: RevisionDialog(self))
        Tooltip(self.rev_label, "RevisionWorx status of this schematic — click for details")
        self._update_toggles()

    def _update_toggles(self):
        u = self.theme.ui
        f = self.theme.fonts["heading"]
        for key, lab in self.toggle_labels.items():
            on = self.settings[key]
            lab.configure(bg=u["accent_soft"] if on else u["status"], fg=u["accent"] if on else u["faint"], font=f)
        self.units_label.configure(text="US" if self.units.system == "us" else "METRIC", bg=u["accent_soft"], fg=u["accent"], font=f)

    def _bind_keys(self):
        r = self.root

        def simple(fn):
            def h(e):
                if isinstance(e.widget, (ttk.Entry, tk.Entry, ttk.Combobox, tk.Text)):
                    return None
                fn()
                return "break"
            return h
        r.bind("<space>", simple(self.toggle_run))
        r.bind("<period>", simple(self.step_once))
        r.bind("<plus>", simple(lambda: self.canvas.zoom_by(1.25)))
        r.bind("<equal>", simple(lambda: self.canvas.zoom_by(1.25)))
        r.bind("<minus>", simple(lambda: self.canvas.zoom_by(0.8)))
        r.bind("<f>", simple(lambda: self.canvas.fit()))
        for seq, fn in (("<Control-i>", self.import_schematic), ("<Control-o>", self.open_dialog), ("<Control-s>", self.save),
                        ("<Control-S>", self.save_as), ("<Control-r>", self.reset), ("<Control-q>", self.quit),
                        ("<Control-e>", self.edit_in_openschematix)):
            r.bind(seq, lambda e, f=fn: (f(), "break")[1])

    # ================================================================ welcome and tabs
    def _show_welcome(self):
        if self.welcome is not None:
            return
        u = self.theme.ui
        w = tk.Frame(self.canvas_holder, bg=u["surface"], bd=0, highlightthickness=1, highlightbackground=u["border"])
        self.welcome = w
        pad = ttk.Frame(w, style="Surface.TFrame", padding=28)
        pad.pack()
        if self.icon_image is not None:
            tk.Label(pad, image=self.icon_image, bg=u["surface"]).pack()
        ttk.Label(pad, text=APP_NAME, style="Title.TLabel").pack(pady=(10, 0))
        ttk.Label(pad, text="Simulate hydraulic, pneumatic and electrical circuits drawn in OpenSchematix.", style="Muted.TLabel").pack(pady=(2, 16))
        ttk.Button(pad, text="Import an OpenSchematix circuit…", style="Accent.TButton", command=self.import_schematic).pack(fill="x")
        ttk.Button(pad, text="Open a study…", command=self.open_dialog).pack(fill="x", pady=(6, 0))
        ttk.Button(pad, text="Try an example", command=lambda: self.open_path(os.path.join(examples_dir(), "lift_cylinder.schematix"))).pack(fill="x", pady=(6, 0))
        rec = [p for p in self.settings["recent_files"] if os.path.exists(p)][:4]
        if rec:
            ttk.Label(pad, text="RECENT", style="Heading.TLabel").pack(anchor="w", pady=(16, 2))
            for p in rec:
                ttk.Button(pad, text=os.path.basename(p), style="Link.TButton", command=lambda x=p: self.open_path(x)).pack(anchor="w")
        w.place(relx=0.5, rely=0.46, anchor="center")

    def _hide_welcome(self):
        if self.welcome is not None:
            self.welcome.destroy()
            self.welcome = None

    def _rebuild_tabs(self):
        for w in self.tabs.winfo_children():
            w.destroy()
        if self.circuit is None:
            return
        u = self.theme.ui
        project = self.circuit.project
        for uid in self.circuit.sheets:
            d = project.find_sheet(uid)
            active = d is self.doc
            lab = tk.Label(self.tabs, text=d.name or "Sheet", padx=14, pady=5, cursor="hand2",
                           bg=u["tab_active"] if active else u["tab_inactive"], fg=u["text"] if active else u["muted"],
                           font=self.theme.fonts["ui"])
            lab.pack(side="left", padx=(0, 1))
            lab.bind("<Button-1>", lambda e, x=uid: self.show_sheet(x))

    def show_sheet(self, uid, fit=True):
        d = self.circuit.project.find_sheet(uid)
        if d is None:
            return
        self.doc = d
        self.canvas.set_doc(d, fit=fit)
        self._rebuild_tabs()

    # ================================================================ files
    def import_schematic(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(parent=self.root, title="Import an OpenSchematix circuit",
                                       filetypes=FILETYPES_SCHEMATIC, initialdir=self.settings["last_dir"] or None)
        if p:
            self.open_path(p, confirm=False)

    def open_dialog(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(parent=self.root, title="Open", filetypes=FILETYPES_ALL,
                                       initialdir=self.settings["last_dir"] or None)
        if p:
            self.open_path(p, confirm=False)

    def open_path(self, path: str, confirm=True) -> bool:
        if confirm and not self._confirm_discard():
            return False
        try:
            if path.lower().endswith(STUDY_EXTENSION):
                st = study_mod.load(path)
                st_path = path
            else:
                ext = os.path.splitext(path)[1].lower()
                if ext not in SCHEMATIC_EXTENSIONS:
                    raise circuit_mod.CircuitError("FluidWorx opens .schematix, .osch and .fluidworx files.")
                st = study_mod.from_source(path)
                st.units = self.units.system
                st_path = None
            self._activate(st, st_path)
        except (study_mod.StudyError, circuit_mod.CircuitError, OSError) as e:
            messagebox.showerror(APP_NAME, str(e), parent=self.root)
            return False
        self.settings["last_dir"] = os.path.dirname(os.path.abspath(path))
        self.settings.add_recent(path)
        self.settings.save()
        self._rebuild_recent()
        return True

    def _activate(self, st, st_path, keep_view=False):
        project, warnings = circuit_mod.load_project_bytes(st.source_bytes, st.source_ext)
        c = circuit_mod.build(project, warnings, st.links)
        if not c.parts:
            raise circuit_mod.CircuitError("This file has no hydraulic, pneumatic or electrical parts to simulate.")
        circuit_mod.apply_study_params(c, st.params)
        was_sheet = self.doc.uid if keep_view and self.doc is not None else None
        failed = self.sim.fault_rows() if keep_view and self.sim is not None else []
        faults = dict(self.sim.faults) if failed else {}
        self.running = False
        self.canvas.doc = None      # nothing may draw the old circuit with the new simulator's arrays
        self.study, self.study_path = st, st_path
        self.circuit = c
        self.sim = engine.Simulator(c)
        for ref, _what, _fault in failed:   # the same question still stands, for whatever is still in the drawing
            if ref in faults:
                self.sim.set_fault(ref, faults[ref])
            else:
                self.sim.set_line_fault(ref, True)
        self.flowpaths = FlowPaths(c)
        self.currentpaths = FlowPaths(c, electric=True) if c.electrical_parts else None
        self.selected = None
        self.dirty = False
        self._races_said = 0
        if st.units != self.units.system and st_path:
            self.set_units(st.units, mark_dirty=False)
        self._hide_welcome()
        self._hide_banner()
        self.circuit_panel.rebuild()
        self.inspector.show(None)
        self.events_panel.clear()
        self.trace_panel.rebuild()
        self.checks_panel.rebuild()
        self.links_panel.rebuild()
        self.faults_panel.rebuild()
        self.show_sheet(was_sheet if was_sheet in c.sheets else c.sheets[0])
        self._update_check_label()
        self._update_fault_label()
        self._update_title()
        self._update_play()
        self.source_mtime = self._mtime(st.source_path)
        if st_path and study_mod.source_changed(st):
            self._show_banner()
        self.refresh_revision_status()
        self.set_status(f"{len(c.parts)} parts ready. Press Space to run, then click a valve or a switch to operate it.")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel(APP_NAME, "Save the changes to this study first?", parent=self.root)
        if ans is None:
            return False
        return self.save() if ans else True

    def save(self) -> bool:
        if self.study is None:
            return False
        if not self.study_path:
            return self.save_as()
        return self._write(self.study_path)

    def save_as(self) -> bool:
        if self.study is None:
            return False
        base = os.path.splitext(self.study.source_name)[0] + STUDY_EXTENSION
        d = os.path.dirname(self.study_path or self.study.source_path or "") or self.settings["last_dir"] or None
        p = filedialog.asksaveasfilename(parent=self.root, title="Save study", defaultextension=STUDY_EXTENSION,
                                         initialfile=os.path.basename(self.study_path) if self.study_path else base,
                                         initialdir=d, filetypes=[("FluidWorx study", "*" + STUDY_EXTENSION)])
        if not p:
            return False
        ok = self._write(p)
        if ok:
            self.settings.add_recent(p)
            self.settings.save()
            self._rebuild_recent()
        return ok

    def _write(self, path) -> bool:
        self.study.units = self.units.system
        try:
            study_mod.save(self.study, path)
        except (study_mod.StudyError, OSError) as e:
            messagebox.showerror(APP_NAME, f"The study could not be saved. The previous file is unchanged.\n\n{e}", parent=self.root)
            return False
        self.study_path = path
        self.dirty = False
        self._update_title()
        self.toast("Study saved", "success")
        self.refresh_revision_status()
        return True

    def _update_title(self):
        if self.study is None:
            self.root.title(APP_NAME)
            return
        name = os.path.basename(self.study_path) if self.study_path else self.study.source_name
        self.root.title(f"{'*' if self.dirty else ''}{name} — {APP_NAME}")

    def _mark_dirty(self):
        self.dirty = True
        self._update_title()

    def quit(self):
        if not self._confirm_discard():
            return
        self.settings["geometry"] = self.root.geometry()
        try:
            w = self.root.winfo_width()
            self.settings["layout"] = {"left_w": self.hpane.sashpos(0), "right_w": w - self.hpane.sashpos(1),
                                       "dock_h": self.vpane.winfo_height() - self.vpane.sashpos(0)}
        except tk.TclError:
            pass
        self.settings.save()
        self.root.destroy()

    # ---- following the schematic on disk
    @staticmethod
    def _mtime(path):
        try:
            return os.path.getmtime(path) if path else None
        except OSError:
            return None

    def _watch_source(self):
        try:
            if self.study is not None and self.study.source_path:
                m = self._mtime(self.study.source_path)
                if m is not None and m != self.source_mtime:
                    self.source_mtime = m
                    if study_mod.source_changed(self.study):
                        self._show_banner()
        finally:
            self.root.after(2000, self._watch_source)

    def _show_banner(self):
        u = self.theme.ui
        for w in self.banner.winfo_children():
            w.destroy()
        self.banner.configure(bg=u["accent_soft"])
        tk.Label(self.banner, text="The schematic has changed on disk since it was imported.", bg=u["accent_soft"], fg=u["text"],
                 font=self.theme.fonts["ui"], padx=10, pady=5).pack(side="left")
        ttk.Button(self.banner, text="Reload", style="Accent.TButton", command=self.reload_source).pack(side="left", padx=4, pady=3)
        ttk.Button(self.banner, text="Keep this version", command=self._hide_banner).pack(side="left", padx=4, pady=3)
        self.banner.pack(fill="x", before=self.tabs)

    def _hide_banner(self):
        self.banner.pack_forget()

    def reload_source(self):
        s = self.study
        if s is None:
            return
        if not s.source_path or not os.path.isfile(s.source_path):
            messagebox.showinfo(APP_NAME, "The original schematic can't be found. The study keeps working from its own copy.", parent=self.root)
            return
        try:
            with open(s.source_path, "rb") as f:
                data = f.read()
            changed = study_mod.sha256(data) != s.source_sha256
            old = (s.source_bytes, s.source_sha256)
            s.source_bytes, s.source_sha256 = data, study_mod.sha256(data)
            try:
                self._activate(s, self.study_path, keep_view=True)
            except (circuit_mod.CircuitError, study_mod.StudyError):
                s.source_bytes, s.source_sha256 = old
                self._activate(s, self.study_path, keep_view=True)
                raise
        except (OSError, circuit_mod.CircuitError, study_mod.StudyError) as e:
            messagebox.showerror(APP_NAME, f"The schematic could not be reloaded; this study still uses the previous version.\n\n{e}", parent=self.root)
            return
        if changed:
            self._mark_dirty()
        self.toast("Schematic reloaded", "success")

    # ================================================================ simulation control
    def toggle_run(self):
        if self.sim is None:
            return
        self.running = not self.running
        self._last_tick = time.monotonic()
        self._update_play()

    def _update_play(self):
        self.play_btn.icon = "pause" if self.running else "play"
        self.play_btn.draw()

    def step_once(self):
        if self.sim is None:
            return
        self.running = False
        self._update_play()
        self.sim.run(0.1)
        self._after_run(0.1)
        self._refresh_views(force=True)

    def reset(self):
        if self.sim is None:
            return
        self.running = False
        self._update_play()
        self.sim.reset()
        self.events_panel.clear()
        self.canvas.redraw()
        self._refresh_views(force=True)
        self.trace_panel.draw()
        self.set_status("Reset.")

    def _speed_changed(self):
        self.speed = SPEEDS.get(self.speed_var.get(), 1.0)

    def command(self, key, name):
        if self.sim is None:
            return
        if self.sim.command(key, name):
            if not self.running:
                # solve once so a click while paused still shows its effect
                self.sim.step()
                self.sim.trace.maybe_record()
            self._refresh_views(force=True)

    def set_param(self, key, name, value):
        part = self.circuit.part(key)
        if part is None or part.params.get(name) == value:
            return
        part.params[name] = value
        pid = study_mod.part_id(key)
        vals = self.study.params.setdefault(pid, {})
        if value == part.base_params.get(name):
            vals.pop(name, None)
            if not vals:
                self.study.params.pop(pid, None)
        else:
            vals[name] = value
        self.sim.touch()
        if name in ("start", "stroke", "angle"):
            b = self.sim.parts[key]
            if isinstance(b, engine.Actuator) and (name == "start" and self.sim.time == 0.0):
                b.reset()
            elif isinstance(b, engine.Actuator):
                b.x = min(b.x, b.travel())
        self._mark_dirty()
        self._refresh_views(force=True)
        self.canvas._draw_legend()

    def set_link(self, key, prop, text):
        """Tie this part to something, in this study only: the schematic stays as it is. Links decide what the
        simulation is made of, so it starts again."""
        pid = study_mod.part_id(key)
        drawn = self._drawn_prop(key, prop)
        vals = self.study.links.setdefault(pid, {})
        if text == drawn:
            vals.pop(prop, None)
            if not vals:
                self.study.links.pop(pid, None)
        else:
            vals[prop] = text
        self._activate(self.study, self.study_path, keep_view=True)
        self._mark_dirty()
        self.select(key, reveal=True)
        self.toast("Link changed. The simulation has started again.")

    # ---- failing things on purpose
    def set_fault(self, key, name):
        if self.sim is not None and self.sim.set_fault(key, name):
            self._faults_changed()

    def set_line_fault(self, ref, failed):
        if self.sim is not None and self.sim.set_line_fault(ref, failed):
            self._lines_changed()
            self._faults_changed()

    def put_right(self, ref):
        if self.sim is None:
            return
        if ref in self.sim.faults:
            self.set_fault(ref, None)
        else:
            self.set_line_fault(ref, False)

    def put_everything_right(self):
        if self.sim is not None:
            self.sim.clear_faults()
            self._lines_changed()
            self._faults_changed()

    def _lines_changed(self):
        """A broken wire changes which wires are joined: the view works that out when it's given the sheet."""
        if self.currentpaths is not None:
            self.currentpaths = FlowPaths(self.circuit, electric=True)
        if self.doc is not None:
            self.canvas.set_doc(self.doc, fit=False)

    def _faults_changed(self):
        if not self.running:
            self.sim.step()     # so that it shows while paused, like a click
            self.sim.trace.maybe_record()
        self.faults_panel.rebuild()
        self._update_fault_label()
        self.inspector.show(self.selected)
        self.canvas.redraw()
        self._refresh_views(force=True)

    def _update_fault_label(self):
        n = len(self.sim.fault_rows()) if self.sim is not None else 0
        if n:
            u = self.theme.ui
            self.fault_label.configure(text=f"{n} FAILED ON PURPOSE", bg=u["status"], fg=u["danger"], font=self.theme.fonts["heading"])
            self.fault_label.pack(side="right", padx=8, before=self.check_label)
        else:
            self.fault_label.pack_forget()

    def _drawn_prop(self, key, prop) -> str:
        """What the schematic itself says, without this study's overlay."""
        project, _warn = circuit_mod.load_project_bytes(self.study.source_bytes, self.study.source_ext)
        doc = project.find_sheet(key[0])
        comp = doc.components.get(key[1]) if doc is not None else None
        return comp.props.get(prop, "").strip() if comp is not None else ""

    def reset_part_params(self, key):
        part = self.circuit.part(key)
        if part is None:
            return
        part.params.update(part.base_params)
        self.study.params.pop(study_mod.part_id(key), None)
        self.sim.touch()
        self._mark_dirty()
        self.inspector.show(key)
        self._refresh_views(force=True)

    def select(self, key, reveal=False):
        self.selected = key
        if key is not None and reveal and self.doc is not None and key[0] != self.doc.uid:
            self.show_sheet(key[0])
        self.canvas.selection_changed()
        self.inspector.show(key)
        self.circuit_panel.show_selection(key)

    # ---- frame loop
    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.25)
        self._last_tick = now
        try:
            if self.sim is not None:
                if self.running:
                    self._advance(dt)
                self.canvas.update_state(dt if self.running else 0.0)
                self._frame += 1
                if self._frame % 6 == 0:
                    self._refresh_views()
            self._drain_results()
        finally:
            self.root.after(FRAME_MS, self._tick)

    def _advance(self, dt):
        target = dt * self.speed
        steps = int(target / self.sim.dt + self._carry())
        start = time.monotonic()
        done = 0
        for _ in range(steps):
            self.sim.step()
            self.sim.trace.maybe_record()
            done += 1
            if time.monotonic() - start > STEP_BUDGET_S:
                break
        self._carry_val = (target / self.sim.dt + getattr(self, "_carry_val", 0.0)) - steps
        if dt > 0:
            rate = done * self.sim.dt / dt
            self._rt_factor += (rate - self._rt_factor) * 0.1
        self._after_run(done * self.sim.dt)

    def _carry(self):
        return getattr(self, "_carry_val", 0.0)

    def _after_run(self, _sim_dt):
        self.time_label.configure(text=f"{self.sim.time:.2f} s")

    def _refresh_views(self, force=False):
        if self.sim is None:
            return
        self.time_label.configure(text=f"{self.sim.time:.2f} s")
        self.circuit_panel.update_states()
        self.inspector.refresh()
        self.events_panel.update_events()
        self._say_races()
        if self.running:
            self.rt_label.configure(text=f"{self._rt_factor:.2f}× real time")
        else:
            self.rt_label.configure(text="Paused" if self.sim.time > 0 else "Ready")
        if force or (self.running and self._frame % 12 == 0):
            self.trace_panel.draw()
        if force:
            self.canvas.update_state(0.0)

    def _say_races(self):
        """A race changes how far a result can be trusted, so it doesn't wait to be found in a list."""
        races = self.sim.net.races
        if len(races) < self._races_said:
            self._races_said = 0
        if len(races) > self._races_said:
            _t, first, other = races[-1]
            self.toast(f"{first} and {other} raced: see Events. A real machine could go either way.", "warning")
            self._races_said = len(races)
        self._update_check_label()

    # ================================================================ small helpers
    def set_status(self, text):
        self._status_base = text
        self.status.set(text)

    def hover_text(self, text):
        self.status.set(text or self._status_base)

    def toast(self, text, kind="info"):
        self.toasts.show(text, kind)

    def update_zoom_label(self):
        self.zoom_label.configure(text=f"{self.canvas.zoom * 100:.0f}%")

    def _update_check_label(self):
        c = self.circuit
        if c is None:
            self.check_label.configure(text="")
            return
        warns = sum(1 for i in c.issues if i.level in ("warning", "error"))
        notes = sum(1 for i in c.issues if i.level == "info")
        bits = []
        races = len(self.sim.net.races) if self.sim is not None else 0
        if races:
            bits.append(f"{races} race{'s' * (races != 1)}")
        if warns:
            bits.append(f"{warns} warning{'s' * (warns != 1)}")
        if notes:
            bits.append(f"{notes} note{'s' * (notes != 1)}")
        text = "Checks: " + (", ".join(bits) if bits else "OK")
        if self.check_label.cget("text") != text:
            self.check_label.configure(text=text)

    def _set_show(self, key, value):
        self.settings[key] = bool(value)
        self.flow_var.set(self.settings["show_flow"])
        self.values_var.set(self.settings["show_values"])
        self._update_toggles()
        self.canvas.redraw()

    def toggle_panel(self, side):
        vis = not self.panel_visible[side]
        self.panel_visible[side] = vis
        self.panel_vars[side].set(vis)
        self.panel_buttons[side].set_checked(vis)
        if side == "left":
            (self.hpane.insert(0, self.left, weight=0) if vis else self.hpane.forget(self.left))
        elif side == "right":
            (self.hpane.add(self.right, weight=0) if vis else self.hpane.forget(self.right))
        else:
            (self.vpane.add(self.dock, weight=2) if vis else self.vpane.forget(self.dock))

    def set_theme(self, name):
        self.settings["theme"] = name
        self.theme = th.Theme(name, self.settings["canvas_theme"])
        self.theme_var.set(name)
        set_current_theme(self.theme)
        th.apply(self.root, self.theme)
        self.settings.save()

    def cycle_theme(self):
        names = list(th.THEMES)
        self.set_theme(names[(names.index(self.theme.name) + 1) % len(names)])

    def _on_theme(self):
        self._update_toggles()
        self._update_fault_label()
        self._style_time()
        self._rebuild_tabs()
        self.checks_panel.rebuild()
        self.links_panel.rebuild()
        self.circuit_panel.rebuild()
        self.trace_panel.rebuild()
        self.inspector.show(self.selected)
        if self.welcome is not None:
            self._hide_welcome()
            self._show_welcome()
        self.canvas.redraw()

    def set_units(self, system, mark_dirty=True):
        if system == self.units.system:
            return
        self.units = Units(system)
        self.settings["units"] = system
        self.units_var.set(system)
        self._update_toggles()
        self.inspector.show(self.selected)
        self.canvas.redraw()
        self.trace_panel.draw()
        if self.study is not None and mark_dirty:
            self.study.units = system

    def tool_missing(self, label):
        messagebox.showinfo(APP_NAME, f"FluidWorx can't find {label}. If it is installed, set its location in "
                                      "File ▸ Preferences.", parent=self.root)

    # ================================================================ other programs
    def edit_in_openschematix(self):
        s = self.study
        if s is None:
            if not tools.launch("openschematix", settings=self.settings):
                self.tool_missing("OpenSchematix")
            return
        if not s.source_path or not os.path.isfile(s.source_path):
            messagebox.showinfo(APP_NAME, "The original schematic can't be found on this computer.", parent=self.root)
            return
        if tools.launch("openschematix", [s.source_path], self.settings):
            self.toast("Opened in OpenSchematix. Save there and FluidWorx will offer to reload.")
        else:
            self.tool_missing("OpenSchematix")

    def refresh_revision_status(self):
        """Ask RevisionWorx about the schematic in the background; the window never waits for it."""
        s = self.study
        self.rev_label.configure(text="")
        if s is None or not s.source_path:
            return
        ws = rw.find_workspace(s.source_path)
        if ws is None:
            return
        sha = s.source_sha256
        path = s.source_path
        settings = self.settings
        client = rw.Client(ws, settings)

        def work():
            try:
                st = client.status(path, sha) if client.available else None
                self._results.put(("rev", path, sha, st, None))
            except rw.RevisionWorxError as e:
                self._results.put(("rev", path, sha, None, str(e)))
        threading.Thread(target=work, daemon=True).start()
        self.rev_label.configure(text="RevisionWorx…")

    def _drain_results(self):
        try:
            while True:
                _kind, path, sha, st, err = self._results.get_nowait()
                s = self.study
                if s is None or s.source_path != path or s.source_sha256 != sha:
                    continue
                self.rev_status = st
                if err:
                    self.rev_label.configure(text="RevisionWorx: unavailable")
                elif st is None:
                    self.rev_label.configure(text="RevisionWorx workspace")
                else:
                    self.rev_label.configure(text=st.summary())
                    summary = st.summary()
                    rec = {"summary": summary, "document": st.number, "revision": st.matched_label}
                    if s.source_rev != rec:
                        s.source_rev = rec
        except queue.Empty:
            pass

    def open_caldera(self):
        if not tools.launch("caldera", settings=self.settings):
            self.tool_missing("Caldera")

    def import_caldera(self):
        if self.circuit is None:
            return
        if self.selected is None:
            messagebox.showinfo(APP_NAME, "Select the part to apply the values to first: a cylinder, pump, motor or relief valve.", parent=self.root)
            return
        p = filedialog.askopenfilename(parent=self.root, title="Open a Caldera project", filetypes=[("Caldera project", "*.caldera"), ("All files", "*.*")])
        if not p:
            return
        try:
            proj = cal.read_project(p)
        except cal.CalderaError as e:
            messagebox.showerror(APP_NAME, str(e), parent=self.root)
            return
        CalderaImportDialog(self, proj)

    def _ask_save(self, title, ext, kind, suffix=""):
        s = self.study
        base = os.path.splitext(s.source_name)[0] + suffix + ext
        d = os.path.dirname(self.study_path or s.source_path or "") or None
        return filedialog.asksaveasfilename(parent=self.root, title=title, defaultextension=ext, initialfile=base, initialdir=d,
                                            filetypes=[(kind, "*" + ext)])

    def export_caldera(self):
        if self.sim is None:
            messagebox.showinfo(APP_NAME, "Open a circuit first.", parent=self.root)
            return
        recs = cal.cylinder_records(self.sim, os.path.splitext(self.study.source_name)[0], report.cycle_times(self.sim))
        if not recs:
            messagebox.showinfo(APP_NAME, "This circuit has no cylinders to calculate.", parent=self.root)
            return
        p = self._ask_save("Send calculations to Caldera", ".caldera", "Caldera project")
        if not p:
            return
        try:
            cal.write_project(p, os.path.splitext(self.study.source_name)[0], recs, f"Exported from {APP_NAME} {VERSION}.")
        except OSError as e:
            messagebox.showerror(APP_NAME, f"The file could not be written.\n\n{e}", parent=self.root)
            return
        self.toast(f"Wrote {len(recs)} calculation{'s' * (len(recs) != 1)}. In Caldera: Projects ▸ Import project.", "success")

    def export_report(self):
        if self.sim is None:
            messagebox.showinfo(APP_NAME, "Open a circuit first.", parent=self.root)
            return
        p = self._ask_save("Export report", ".html", "Web page", " simulation")
        if not p:
            return
        self._write_text(p, report.html_report(self.study, self.circuit, self.sim, self.units, self.doc))

    def export_trace(self):
        if self.sim is None:
            messagebox.showinfo(APP_NAME, "Open a circuit first.", parent=self.root)
            return
        p = self._ask_save("Export trace", ".csv", "CSV file", " trace")
        if p:
            self._write_text(p, report.trace_csv(self.sim, self.units))

    def export_events(self):
        if self.sim is None:
            messagebox.showinfo(APP_NAME, "Open a circuit first.", parent=self.root)
            return
        p = self._ask_save("Export events", ".csv", "CSV file", " events")
        if p:
            self._write_text(p, report.events_csv(self.sim))

    def _write_text(self, path, text):
        try:
            report.write_text(path, text)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"The file could not be written.\n\n{e}", parent=self.root)
            return
        self.toast(f"Saved {os.path.basename(path)}", "success")


def main(path=None) -> int:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - older Windows versions
            pass
    root = tk.Tk(className="FluidWorx")
    App(root, path)
    root.mainloop()
    return 0
