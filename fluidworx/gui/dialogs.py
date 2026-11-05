"""Dialogs: About, Preferences, RevisionWorx, Caldera, keyboard shortcuts."""
from __future__ import annotations

import platform
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .. import (APP_NAME, COPYRIGHT, DONATE_URL, LICENSE_NAME, LICENSE_URL, VERSION)
from ..integrations import caldera as cal
from ..integrations import revisionworx as rw
from ..integrations import tools
from ..vendor.openschematix.gui import theme as th


class Dialog(tk.Toplevel):
    """Same frame, buttons and placement as OpenSchematix's dialogs."""

    def __init__(self, app, title, resizable=False):
        self.parent = app.root
        super().__init__(self.parent)
        self.app = app
        self.title(title)
        self.configure(bg=app.theme.ui["surface"])
        self.transient(self.parent)
        self.resizable(resizable, resizable)
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.frame = ttk.Frame(self, style="Surface.TFrame", padding=18)
        self.frame.pack(fill="both", expand=True)
        self.result = None

    def buttons(self, ok_text="OK", ok=None, cancel_text="Cancel", extra=()):
        bar = ttk.Frame(self.frame, style="Surface.TFrame")
        bar.pack(fill="x", pady=(16, 0), side="bottom")
        if cancel_text:
            ttk.Button(bar, text=cancel_text, command=self.cancel).pack(side="right")
        if ok_text:
            ttk.Button(bar, text=ok_text, style="Accent.TButton", command=ok or self.ok).pack(side="right", padx=(0, 8))
            self.bind("<Return>", lambda e: (ok or self.ok)() if not isinstance(e.widget, tk.Text) else None)
        for text, cmd in extra:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 8))
        return bar

    def ok(self):
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()

    def show_modal(self, wait=False):
        self.update_idletasks()
        r = self.parent
        x = r.winfo_rootx() + (r.winfo_width() - self.winfo_reqwidth()) // 2
        y = r.winfo_rooty() + (r.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()
        if wait:
            self.wait_window()
        return self.result


class AboutDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, f"About {APP_NAME}")
        f = self.frame
        t = app.theme
        top = ttk.Frame(f, style="Surface.TFrame")
        top.pack(fill="x")
        if app.icon_image is not None:
            try:
                self._img = app.icon_image.subsample(1)
                tk.Label(top, image=self._img, bg=t.ui["surface"]).pack(side="left", padx=(0, 16))
            except tk.TclError:
                pass
        col = ttk.Frame(top, style="Surface.TFrame")
        col.pack(side="left", fill="x")
        ttk.Label(col, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(col, text=f"Version {VERSION}", style="Surface.TLabel").pack(anchor="w")
        ttk.Label(col, text="Hydraulic and pneumatic circuit simulator", style="Muted.TLabel").pack(anchor="w")
        body = (f"{COPYRIGHT}\n\n"
                f"Free and open-source software, licensed under the {LICENSE_NAME}. You may use, study, share and "
                f"modify it under the terms of that licence. It comes with ABSOLUTELY NO WARRANTY.\n\n"
                "FluidWorx simulates circuits drawn in OpenSchematix, using OpenSchematix's own symbols and "
                "connectivity. Its model is deliberately simple and shows how a circuit behaves; speeds and pressures "
                "are indicative. It is not a sizing tool and does not show that a circuit is safe. Always have "
                "safety-related designs reviewed by a qualified person.\n\n"
                "FluidWorx has no ads, no telemetry, no accounts and no feature limits. If it is useful to you, "
                "you can support its development voluntarily.")
        ttk.Label(f, text=body, style="Surface.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(16, 8))
        links = ttk.Frame(f, style="Surface.TFrame")
        links.pack(anchor="w")
        ttk.Button(links, text="Support development (Ko-fi)", style="Link.TButton",
                   command=lambda: webbrowser.open(DONATE_URL)).pack(side="left")
        ttk.Button(links, text="Licence text", style="Link.TButton",
                   command=lambda: webbrowser.open(LICENSE_URL)).pack(side="left", padx=8)
        ttk.Label(f, text=f"Python {platform.python_version()} · Tk {app.root.tk.call('info', 'patchlevel')} · "
                          f"{platform.system()} {platform.release()}", style="Faint.TLabel").pack(anchor="w", pady=(10, 0))
        self.buttons("Close", cancel_text="")
        self.show_modal()


class PreferencesDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Preferences")
        f = self.frame
        s = app.settings
        ttk.Label(f, text="Appearance", style="Bold.TLabel").pack(anchor="w")
        grid = ttk.Frame(f, style="Surface.TFrame")
        grid.pack(fill="x", pady=(4, 12))
        grid.columnconfigure(1, weight=1)
        self.theme_names = {v["label"]: k for k, v in th.THEMES.items()}
        self.canvas_names = {"Follow the theme": "auto", **{v[0]: k for k, v in th.CANVAS_THEMES.items()}}
        self.theme = tk.StringVar(value=th.THEMES[app.theme.name]["label"])
        cur_canvas = next((k for k, v in self.canvas_names.items() if v == s["canvas_theme"]), "Follow the theme")
        self.canvas = tk.StringVar(value=cur_canvas)
        self.units = tk.StringVar(value="US customary (psi, gpm, in)" if s["units"] == "us" else "Metric (bar, L/min, mm)")
        rows = [("Theme", self.theme, list(self.theme_names)), ("Canvas colours", self.canvas, list(self.canvas_names)),
                ("Units", self.units, ["Metric (bar, L/min, mm)", "US customary (psi, gpm, in)"])]
        for i, (label, var, vals) in enumerate(rows):
            ttk.Label(grid, text=label, style="Surface.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 12), pady=3)
            ttk.Combobox(grid, textvariable=var, values=vals, state="readonly", width=34).grid(row=i, column=1, sticky="ew", pady=3)
        ttk.Label(f, text="Other programs", style="Bold.TLabel").pack(anchor="w")
        ttk.Label(f, text="Leave blank to find them automatically.", style="Muted.TLabel").pack(anchor="w")
        paths = ttk.Frame(f, style="Surface.TFrame")
        paths.pack(fill="x", pady=(4, 0))
        paths.columnconfigure(1, weight=1)
        self.paths = {}
        for i, (key, label) in enumerate((("openschematix", "OpenSchematix"), ("revisionworx", "RevisionWorx command line"),
                                          ("caldera", "Caldera"))):
            setting = tools.TOOLS[key]["setting"]
            var = tk.StringVar(value=s[setting])
            self.paths[setting] = var
            ttk.Label(paths, text=label, style="Surface.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 12), pady=3)
            ttk.Entry(paths, textvariable=var, width=36).grid(row=i, column=1, sticky="ew", pady=3)
            ttk.Button(paths, text="Browse…", command=lambda v=var: self._browse(v)).grid(row=i, column=2, padx=(6, 0))
            found = tools.find(key, s)
            ttk.Label(paths, text="found" if found else "not found", style="Success.TLabel" if found else "Faint.TLabel").grid(
                row=i, column=3, padx=(8, 0))
        self.buttons("OK")
        self.show_modal()

    def _browse(self, var):
        p = filedialog.askopenfilename(parent=self, title="Find the program")
        if p:
            var.set(p)

    def ok(self):
        s = self.app.settings
        for setting, var in self.paths.items():
            s[setting] = var.get().strip()
        s["canvas_theme"] = self.canvas_names.get(self.canvas.get(), "auto")
        self.app.set_units("us" if self.units.get().startswith("US") else "metric")
        self.app.set_theme(self.theme_names.get(self.theme.get(), "modern_light"))
        s.save()
        self.destroy()


class ShortcutsDialog(Dialog):
    ROWS = [("Space", "Play / pause"), ("Ctrl+R", "Reset the simulation"), ("Period (.)", "Step 0.1 s"),
            ("Click a valve", "Operate its left or right side"), ("Double-click a pump", "Start or stop it"),
            ("Drag, or middle-drag", "Pan"), ("Wheel, + / -", "Zoom"), ("F", "Zoom to the circuit"),
            ("Ctrl+I", "Import a schematic"), ("Ctrl+O", "Open a study"), ("Ctrl+S", "Save the study"),
            ("Ctrl+E", "Edit in OpenSchematix")]

    def __init__(self, app):
        super().__init__(app, "Keyboard and mouse")
        g = ttk.Frame(self.frame, style="Surface.TFrame")
        g.pack()
        for i, (k, d) in enumerate(self.ROWS):
            ttk.Label(g, text=k, style="Bold.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 18), pady=2)
            ttk.Label(g, text=d, style="Surface.TLabel").grid(row=i, column=1, sticky="w", pady=2)
        self.buttons("Close", cancel_text="")
        self.show_modal()


class RevisionDialog(Dialog):
    """Revision status of the schematic and the study, with check-out, check-in and register for the study."""

    def __init__(self, app):
        super().__init__(app, "RevisionWorx")
        self.columnconfigure(0, weight=1)
        self.body = ttk.Frame(self.frame, style="Surface.TFrame")
        self.body.pack(fill="both", expand=True)
        self.buttons("Close", cancel_text="", extra=[("Open RevisionWorx", self.open_tool)])
        self.refresh()
        self.show_modal()

    def open_tool(self):
        ws = self._workspace()
        if not tools.launch("revisionworx-gui", [ws] if ws else [], self.app.settings):
            self.app.tool_missing("RevisionWorx")

    def _workspace(self):
        s = self.app.study
        for p in (self.app.study_path, s.source_path if s else None):
            if p:
                ws = rw.find_workspace(p)
                if ws:
                    return ws
        return None

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        ws = self._workspace()
        s = self.app.study
        if ws is None:
            ttk.Label(self.body, text="Neither the schematic nor this study is in a RevisionWorx workspace.",
                      style="Bold.TLabel", wraplength=480).pack(anchor="w")
            ttk.Label(self.body, text="Keep your schematic in a registered project folder and FluidWorx will show which "
                                      "revision you are simulating, and can put studies under revision control.",
                      style="Muted.TLabel", wraplength=480, justify="left").pack(anchor="w", pady=(4, 0))
            return
        client = rw.Client(ws, self.app.settings)
        ttk.Label(self.body, text=f"Workspace: {ws}", style="Muted.TLabel", wraplength=500).pack(anchor="w", pady=(0, 10))
        if not client.available:
            ttk.Label(self.body, text="FluidWorx can't find the RevisionWorx command line. Set its location in Preferences.",
                      style="Warning.TLabel", wraplength=480).pack(anchor="w")
            return
        try:
            src = client.status(s.source_path, s.source_sha256) if s and s.source_path else None
            study = client.status(self.app.study_path) if self.app.study_path else None
        except rw.RevisionWorxError as e:
            ttk.Label(self.body, text=str(e), style="Danger.TLabel", wraplength=480, justify="left").pack(anchor="w")
            return
        self._row("Schematic", s.source_name if s else "", src)
        if src is not None and src.managed:
            if src.matched_label:
                ttk.Label(self.body, text=f"Simulating exactly Rev {src.matched_label}.", style="Success.TLabel").pack(anchor="w", pady=(0, 10))
            else:
                ttk.Label(self.body, text="What is being simulated matches no checked-in revision.",
                          style="Warning.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Separator(self.body).pack(fill="x", pady=8)
        self._row("Study", self.app.study_path or "Not saved yet", study)
        bar = ttk.Frame(self.body, style="Surface.TFrame")
        bar.pack(anchor="w", pady=(10, 0))
        if not self.app.study_path:
            ttk.Label(self.body, text="Save the study first to put it under revision control.", style="Muted.TLabel").pack(anchor="w")
            return
        if study is None or not study.managed:
            project = src.project_id if src is not None and src.managed else ""
            b = ttk.Button(bar, text="Register study", style="Accent.TButton",
                           command=lambda: self._do(lambda: client.register(project, self.app.study_path,
                                                                            s.source_name + " simulation", "Created by FluidWorx")))
            b.pack(side="left")
            if not project:
                b.state(["disabled"])
                ttk.Label(self.body, text="Register the schematic first; the study joins its project.", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
            return
        if study.checked_out_by:
            ttk.Button(bar, text="Check in…", style="Accent.TButton", command=lambda: self._checkin(client, study)).pack(side="left", padx=(0, 8))
            ttk.Button(bar, text="Cancel check-out", command=lambda: self._do(lambda: client.cancel(study.doc_id))).pack(side="left")
        else:
            ttk.Button(bar, text="Check out", style="Accent.TButton", command=lambda: self._do(lambda: client.checkout(study.doc_id))).pack(side="left")

    def _row(self, title, name, st):
        ttk.Label(self.body, text=title, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(self.body, text=name, style="Surface.TLabel", wraplength=500).pack(anchor="w")
        if st is None or not st.managed:
            ttk.Label(self.body, text="Not registered.", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
            return
        bits = [f"{st.number or st.title}", f"Rev {st.latest_label or '—'}", st.latest_state or "", f"file {st.file_state}"]
        if st.checked_out_by:
            bits.append(f"checked out by {st.checked_out_by}")
        ttk.Label(self.body, text=" · ".join(b for b in bits if b), style="Muted.TLabel", wraplength=500).pack(anchor="w", pady=(0, 6))

    def _do(self, fn):
        try:
            fn()
        except rw.RevisionWorxError as e:
            messagebox.showerror("RevisionWorx", str(e), parent=self)
        self.refresh()
        self.app.refresh_revision_status()

    def _checkin(self, client, st):
        d = _AskText(self.app, "Check in", "Describe this revision:", parent=self)
        if d.result:
            self.app.save()
            self._do(lambda: client.checkin(st.doc_id, d.result))


class _AskText(Dialog):
    def __init__(self, app, title, prompt, parent=None):
        super().__init__(app, title)
        ttk.Label(self.frame, text=prompt, style="Surface.TLabel").pack(anchor="w")
        self.var = tk.StringVar()
        e = ttk.Entry(self.frame, textvariable=self.var, width=52)
        e.pack(fill="x", pady=(6, 0))
        self.buttons("OK")
        self.update_idletasks()
        e.focus_set()
        self.show_modal(wait=True)

    def ok(self):
        self.result = self.var.get().strip()
        self.destroy()


class CalderaImportDialog(Dialog):
    """Offer saved Caldera calculations for the selected part."""

    def __init__(self, app, project: dict):
        super().__init__(app, f"Use values from Caldera: {project['name']}", resizable=True)
        self.project = project
        part = app.circuit.part(app.selected) if app.selected else None
        self.part = part
        ttk.Label(self.frame, text=f"Apply to {part.title}" if part else "Apply to", style="Bold.TLabel").pack(anchor="w")
        self.rows = [r for r in project["history"] if part is not None and cal.applicable(r, part)]
        if not self.rows:
            ttk.Label(self.frame, text="This project has no saved calculation with values for this part.",
                      style="Muted.TLabel", wraplength=480).pack(anchor="w", pady=(6, 0))
            self.buttons("Close", cancel_text="")
            self.show_modal()
            return
        self.tree = ttk.Treeview(self.frame, columns=("tool", "date", "values"), show="headings", height=8, selectmode="browse")
        for c, t, w in (("tool", "Calculation", 170), ("date", "Saved", 120), ("values", "Values", 320)):
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=w, stretch=c == "values")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        un = app.units
        defs = {d.key: d for d in __import__("fluidworx.catalog", fromlist=["PARAMS"]).PARAMS.get(part.kind, [])}
        for i, r in enumerate(self.rows):
            vals = cal.applicable(r, part)
            shown = ", ".join(f"{defs[k].label} {un.fmt(defs[k].quantity, v)}" for k, v in vals.items() if k in defs)
            self.tree.insert("", "end", iid=str(i), values=(r.get("tool"), str(r.get("date", ""))[:16].replace("T", " "), shown))
        self.tree.selection_set("0")
        self.buttons("Apply")
        self.show_modal()

    def ok(self):
        sel = self.tree.selection()
        if sel:
            for k, v in cal.applicable(self.rows[int(sel[0])], self.part).items():
                self.app.set_param(self.part.key, k, v)
            self.app.inspector.show(self.part.key)
            self.app.toast(f"Applied Caldera values to {self.part.tag}", "success")
        self.destroy()
