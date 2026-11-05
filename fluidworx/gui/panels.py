"""Sidebars and dock: circuit list, properties, trace chart, events, checks."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import catalog, engine, units as units_mod
from ..vendor.openschematix.gui import theme as th
from ..vendor.openschematix.gui.widgets import IconButton, PanelHeader, ScrollFrame, Section, Tooltip

GROUPS = [("Supply", ("pump", "pump_pc", "compressor")),
          ("Actuators", ("cylinder", "cylinder_single", "cylinder_equal", "motor", "rotary")),
          ("Directional", ("dcv", "switched", "switched_ports", "prop")),
          ("Control", ("relief", "sequence", "unloading", "reducer", "check", "pilot_check",
                       "shuttle", "throttle", "oneway", "flow_pc")),
          ("Storage", ("accumulator", "receiver")),
          ("Instruments", ("gauge", "pressure_switch")),
          ("Inline", None)]
HIDDEN_KINDS = ("tank", "plug")


def _scroll(parent, widget):
    sb = ttk.Scrollbar(parent, orient="vertical", command=widget.yview)
    widget.configure(yscrollcommand=sb.set)
    return sb


class CircuitPanel(ttk.Frame):
    """Every part in the circuit with its live state."""

    def __init__(self, master, app):
        super().__init__(master, style="Surface.TFrame")
        self.app = app
        PanelHeader(self, "Circuit").pack(fill="x")
        holder = ttk.Frame(self, style="Surface.TFrame")
        holder.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(holder, columns=("state",), selectmode="browse", show="tree headings")
        self.tree.heading("#0", text="Part", anchor="w")
        self.tree.heading("state", text="State", anchor="w")
        self.tree.column("#0", width=110, stretch=False)
        self.tree.column("state", width=170, stretch=True)
        self.tree.pack(side="left", fill="both", expand=True)
        _scroll(holder, self.tree).pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self._rows = {}
        self._guard = False

    def rebuild(self):
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        if self.app.circuit is None:
            return
        parts = [p for p in self.app.circuit.parts if p.kind not in HIDDEN_KINDS]
        placed = set()
        for title, kinds in GROUPS:
            members = [p for p in parts if p.key not in placed and (kinds is None or p.kind in kinds)]
            if not members:
                continue
            gid = self.tree.insert("", "end", text=title, open=True, tags=("group",))
            for p in members:
                placed.add(p.key)
                iid = self.tree.insert(gid, "end", text=p.tag, values=("",))
                self._rows[p.key] = iid
        self.tree.tag_configure("group", foreground=self.app.theme.ui["muted"])
        self.update_states()

    def update_states(self):
        sim = self.app.sim
        if sim is None:
            return
        for key, iid in self._rows.items():
            st = sim.status(key)
            if self.tree.set(iid, "state") != st:
                self.tree.set(iid, "state", st)

    def show_selection(self, key):
        self._guard = True
        iid = self._rows.get(key)
        self.tree.selection_set((iid,) if iid else ())
        if iid:
            self.tree.see(iid)
        self.after_idle(self._unguard)

    def _unguard(self):
        self._guard = False

    def _on_select(self, _e):
        if self._guard:
            return
        sel = self.tree.selection()
        for key, iid in self._rows.items():
            if sel and iid == sel[0]:
                self.app.select(key, reveal=True)
                return


class Inspector(ScrollFrame):
    """Selected part: live readings, the buttons that operate it, and its parameters."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.key = None
        self.read_vars = []
        self.action_buttons = {}
        self.status_var = tk.StringVar()
        self.show(None)

    def show(self, key):
        self.key = key
        self.clear()
        self.read_vars = []
        self.action_buttons = {}
        app = self.app
        part = app.circuit.part(key) if key is not None and app.circuit else None
        if part is None:
            self._empty()
            return
        head = ttk.Frame(self.inner, style="Surface.TFrame", padding=(12, 10, 12, 6))
        head.pack(fill="x")
        ttk.Label(head, text=part.title, style="Title.TLabel", wraplength=250).pack(anchor="w")
        ttk.Label(head, text=part.symbol_name, style="Muted.TLabel", wraplength=250, justify="left").pack(anchor="w")
        medium = {"hyd": "Hydraulic", "pneu": "Pneumatic"}[part.medium]
        ttk.Label(head, text=f"{medium} · {catalog.KIND_NAMES.get(part.kind, part.kind)}", style="Faint.TLabel").pack(anchor="w")
        b = app.sim.parts[key]
        sec = Section(self.inner, "State")
        sec.pack(fill="x")
        ttk.Label(sec.body, textvariable=self.status_var, style="Bold.TLabel", wraplength=250, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))
        sec.row = 1
        for label, q, _v in b.readings(app.sim.p):
            var = tk.StringVar()
            lab = ttk.Label(sec.body, textvariable=var, style="Surface.TLabel", anchor="e")
            sec.add_row(label, lab)
            self.read_vars.append((label, var))
        acts = b.actions()
        if acts:
            s2 = Section(self.inner, "Operate")
            s2.pack(fill="x")
            for name, label, _on in acts:
                btn = ttk.Button(s2.body, text=label, command=lambda n=name: app.command(key, n))
                s2.add_full(btn)
                self.action_buttons[name] = (btn, label)
        defs = catalog.PARAMS.get(part.kind, [])
        if defs:
            s3 = Section(self.inner, "Parameters")
            s3.pack(fill="x")
            for d in defs:
                self._param_row(s3, part, d)
            reset = ttk.Button(s3.body, text="Reset to drawing", style="Link.TButton",
                               command=lambda: app.reset_part_params(key))
            s3.add_full(reset, pady=(6, 0))
        note = part.spec.approx or ("Its ports are treated as blocked." if part.kind == "unsupported" else "")
        if note:
            s4 = Section(self.inner, "Note")
            s4.pack(fill="x")
            s4.add_full(ttk.Label(s4.body, text=note, style="Warning.TLabel", wraplength=250, justify="left"))
        self.refresh()

    def _empty(self):
        box = ttk.Frame(self.inner, style="Surface.TFrame", padding=16)
        box.pack(fill="x")
        ttk.Label(box, text="Nothing selected", style="Bold.TLabel").pack(anchor="w")
        ttk.Label(box, text="Click a part on the drawing to see its readings and change its values. Clicking a "
                            "valve's left or right side operates it.", style="Muted.TLabel", wraplength=250,
                  justify="left").pack(anchor="w", pady=(4, 0))

    def _param_row(self, sec, part, d):
        app = self.app
        un = app.units
        row = ttk.Frame(sec.body, style="Surface.TFrame")
        if d.quantity == "choice":
            var = tk.StringVar(value=d.choices[int(part.params[d.key] >= 0.5)])
            cb = ttk.Combobox(row, textvariable=var, values=d.choices, state="readonly", width=18)
            cb.pack(side="left", fill="x", expand=True)
            cb.bind("<<ComboboxSelected>>", lambda e: app.set_param(part.key, d.key, float(d.choices.index(var.get()))))
            sec.add_row(d.label, row, d.hint)
            return
        var = tk.StringVar(value=un.number(d.quantity, part.params[d.key]))
        ent = ttk.Entry(row, textvariable=var, width=9, justify="right")
        ent.pack(side="left", fill="x", expand=True)
        ttk.Label(row, text=un.label(d.quantity), style="Muted.TLabel", width=6).pack(side="left", padx=(4, 0))

        def commit(_e=None):
            if var.get().strip() == un.number(d.quantity, part.params[d.key]):
                return      # unchanged: leaving a field must not round the value or mark the study changed
            try:
                v = units_mod.parse_entry(var.get(), d.quantity, un)
            except ValueError:
                var.set(un.number(d.quantity, part.params[d.key]))
                app.toast(f"{d.label}: enter a number", "warning")
                return
            v = max(d.minimum, min(d.maximum, v))
            app.set_param(part.key, d.key, v)
            var.set(un.number(d.quantity, part.params[d.key]))
        ent.bind("<Return>", commit)
        ent.bind("<FocusOut>", commit)
        hint = d.hint
        if d.key in part.from_schematic:
            hint = (hint + " " if hint else "") + "Read from the drawing."
        sec.add_row(d.label, row, hint)
        if d.quantity == "percent" and d.key == "opening":
            sc = ttk.Scale(sec.body, from_=0, to=100, value=part.params[d.key], orient="horizontal")

            def slide(v):
                app.set_param(part.key, d.key, float(v))
                var.set(un.number(d.quantity, float(v)))
            sc.configure(command=slide)
            sec.add_full(sc)

    def refresh(self):
        if self.key is None or self.app.sim is None:
            return
        b = self.app.sim.parts.get(self.key)
        if b is None:
            return
        self.status_var.set(b.status(self.app.sim.p) or "—")
        rows = {label: (q, v) for label, q, v in b.readings(self.app.sim.p)}
        for label, var in self.read_vars:
            if label in rows:
                var.set(self.app.units.fmt(*rows[label]))
        for name, label, on in b.actions():
            pair = self.action_buttons.get(name)
            if pair:
                pair[0].configure(text=("● " if on else "") + label, style="Accent.TButton" if on else "TButton")


# Fixed categorical order, validated for colour-blind separation in both modes. Colour follows the channel, never
# its position in a filtered list; the legend and line-end labels keep identity readable without colour. A channel
# past the eighth gets no invented hue: it is drawn muted and dashed and relies on its label.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
LANE_ORDER = ("length", "angle", "speed", "rpm", "pressure")
LANE_TITLES = {"length": "Position", "angle": "Rotation", "speed": "Speed", "rpm": "Speed", "pressure": "Pressure"}
WINDOWS = {"Last 10 s": 10.0, "Last 30 s": 30.0, "Last 2 min": 120.0, "All": None}


class TracePanel(ttk.Frame):
    """Recorded signals. One lane per quantity (never two scales on one axis), crosshair readout on hover."""

    def __init__(self, master, app):
        super().__init__(master, style="Surface.TFrame")
        self.app = app
        self.enabled: set = set()
        left = ttk.Frame(self, style="Surface.TFrame", padding=(8, 6))
        left.pack(side="left", fill="y")
        self.window = tk.StringVar(value="Last 30 s")
        cb = ttk.Combobox(left, textvariable=self.window, values=list(WINDOWS), state="readonly", width=14)
        cb.pack(fill="x", pady=(0, 6))
        cb.bind("<<ComboboxSelected>>", lambda e: self.draw())
        self.list_host = ScrollFrame(left)
        self.list_host.configure(width=190)
        self.list_host.pack(fill="both", expand=True)
        self.list_host.canvas.configure(width=190)
        self.cv = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.cv.pack(side="left", fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<Motion>", self._hover)
        self.cv.bind("<Leave>", lambda e: self._clear_hover())
        self.hover_x = None
        self._geom = []
        th.subscribe(lambda t: self.draw())

    def rebuild(self):
        self.list_host.clear()
        self.enabled = set()
        sim = self.app.sim
        if sim is None:
            self.draw()
            return
        picked_pressure = 0
        for i, ch in enumerate(sim.trace.channels):
            cid, label, q = ch[0], ch[1], ch[2]
            on = False
            if cid[1] == "x":
                on = True
            elif q == "pressure" and picked_pressure < 3 and cid[1] == "p":
                on = True
                picked_pressure += 1
            if on:
                self.enabled.add(i)
            var = tk.BooleanVar(value=on)
            row = ttk.Frame(self.list_host.inner, style="Surface.TFrame")
            row.pack(fill="x")
            sw = tk.Canvas(row, width=12, height=12, highlightthickness=0, bg=self.app.theme.ui["surface"])
            sw.create_rectangle(1, 1, 11, 11, fill=self._color(i), outline="")
            sw.pack(side="left", padx=(0, 4))
            ttk.Checkbutton(row, text=f"{label}", variable=var,
                            command=lambda idx=i, v=var: self._toggle(idx, v.get())).pack(side="left", anchor="w")
        self.draw()

    def _toggle(self, idx, on):
        (self.enabled.add if on else self.enabled.discard)(idx)
        self.draw()

    def _color(self, i):
        pal = SERIES_DARK if self.app.theme.dark else SERIES_LIGHT
        return pal[i] if i < len(pal) else self.app.theme.ui["muted"]

    def draw(self):
        cv = self.cv
        cv.delete("all")
        t = self.app.theme
        u = t.ui
        cv.configure(bg=u["surface"])
        W, H = cv.winfo_width(), cv.winfo_height()
        self._geom = []
        sim = self.app.sim
        if sim is None or W < 60 or H < 40:
            return
        tr = sim.trace
        if len(tr.times) < 2 or not self.enabled:
            cv.create_text(W / 2, H / 2, text="Press Play, then operate a valve. Signals will be recorded here."
                           if len(tr.times) < 2 else "Tick a signal on the left to plot it.", fill=u["faint"],
                           font=t.fonts["ui"])
            return
        span = WINDOWS.get(self.window.get())
        t1 = tr.times[-1]
        t0 = max(tr.times[0], t1 - span) if span else tr.times[0]
        if span:
            t1 = max(t1, t0 + span)
        lanes = {}
        for i in sorted(self.enabled):
            lanes.setdefault(tr.channels[i][2], []).append(i)
        order = [q for q in LANE_ORDER if q in lanes]
        ml, mr, mt, mb = 62, 82, 8, 22
        lane_h = (H - mt - mb) / max(1, len(order))
        start = 0
        for k, x in enumerate(tr.times):
            if x >= t0:
                start = max(0, k - 1)
                break
        un = self.app.units
        titles = []
        for li, q in enumerate(order):
            y0 = mt + li * lane_h + 18
            y1 = mt + (li + 1) * lane_h - 6
            vals = [v for i in lanes[q] for v in tr.data[i][start:]]
            lo, hi = min(vals), max(vals)
            lo, hi = (min(lo, 0.0), max(hi, 0.0))
            if hi - lo < 1e-9:
                hi = lo + 1.0
            hi_d, lo_d = un.from_si(q, hi), un.from_si(q, lo)
            step = _nice((hi_d - lo_d) / 2.5)
            top = step * _ceil(hi_d / step)
            bot = step * _floor(lo_d / step)
            sx = lambda x: ml + (x - t0) / max(t1 - t0, 1e-6) * (W - ml - mr)  # noqa: E731
            sy = lambda v, b=bot, a=top, y0=y0, y1=y1: y1 - (un.from_si(q, v) - b) / max(a - b, 1e-12) * (y1 - y0)  # noqa: E731
            v = bot
            n = 0
            while v <= top + step * 0.01 and n < 12:
                yy = y1 - (v - bot) / max(top - bot, 1e-12) * (y1 - y0)
                cv.create_line(ml, yy, W - mr, yy, fill=u["border"], width=1)
                cv.create_text(ml - 6, yy, text=units_mod._trim(v), anchor="e", fill=u["muted"], font=t.fonts["small"])
                v += step
                n += 1
            title = cv.create_text(ml, y0 - 6, text=f"{LANE_TITLES.get(q, q)} ({un.label(q)})", anchor="sw",
                                   fill=u["muted"], font=t.fonts["heading"])
            titles.append(title)
            times = tr.times[start:]
            stride = max(1, len(times) // max(1, int(W - ml - mr)))
            ends = []
            for i in lanes[q]:
                col = self._color(i)
                data = tr.data[i][start:]
                pts = []
                for x, val in zip(times[::stride], data[::stride]):
                    pts += [sx(x), sy(val)]
                if len(pts) >= 4:
                    cv.create_line(*pts, fill=col, width=2, joinstyle="round", capstyle="round",
                                   dash=(5, 3) if i >= len(SERIES_LIGHT) else None)
                ends.append((sy(data[-1]), tr.channels[i][1], i))
            if len(ends) <= 4:      # direct labels, nudged apart so they stay readable
                ends.sort()
                last = -99
                for yy, label, i in ends:
                    yy = max(yy, last + 13)
                    last = yy
                    cv.create_text(W - mr + 6, yy, text=label, anchor="w", fill=u["text"], font=t.fonts["small"])
            self._geom.append((q, lanes[q], sy, y0, y1))
        # time axis
        step = _nice((t1 - t0) / 6)
        x = step * _ceil(t0 / step)
        while x <= t1:
            xx = ml + (x - t0) / max(t1 - t0, 1e-6) * (W - ml - mr)
            cv.create_line(xx, H - mb, xx, H - mb + 3, fill=u["border_strong"])
            cv.create_text(xx, H - mb + 12, text=f"{x:g}", fill=u["muted"], font=t.fonts["small"])
            x += step
        cv.create_text(W - mr + 22, H - mb + 12, text="time (s)", anchor="w", fill=u["muted"], font=t.fonts["small"])
        for title in titles:
            cv.tag_raise(title)
        self._xmap = (t0, t1, ml, W - mr, start)
        if self.hover_x is not None:
            self._draw_cursor()

    def _hover(self, e):
        self.hover_x = e.x
        self.cv.delete("cursor")
        if self.app.sim is not None and self._geom:
            self._draw_cursor()

    def _clear_hover(self):
        self.hover_x = None
        self.cv.delete("cursor")

    def _draw_cursor(self):
        t0, t1, xa, xb, start = self._xmap
        x = self.hover_x
        if x < xa or x > xb:
            return
        cv = self.cv
        tt = t0 + (x - xa) / max(xb - xa, 1) * (t1 - t0)
        tr = self.app.sim.trace
        import bisect
        k = min(bisect.bisect_left(tr.times, tt), len(tr.times) - 1)
        if tr.times[k] > tt + 0.5:
            return
        u = self.app.theme.ui
        f = self.app.theme.fonts["small"]
        cv.create_line(x, 8, x, cv.winfo_height() - 22, fill=u["border_strong"], tags="cursor")
        lines = [f"t = {tr.times[k]:.2f} s"]
        un = self.app.units
        for q, idxs, sy, _a, _b in self._geom:
            for i in idxs:
                lines.append(f"{tr.channels[i][1]}: {un.fmt(q, tr.data[i][k])}")
        txt = "\n".join(lines)
        tx = x + 10 if x < (xa + xb) / 2 else x - 10
        cid = cv.create_text(tx, 14, text=txt, anchor="nw" if x < (xa + xb) / 2 else "ne", fill=u["tooltip_fg"], font=f, tags="cursor")
        bb = cv.bbox(cid)
        rect = cv.create_rectangle(bb[0] - 6, bb[1] - 4, bb[2] + 6, bb[3] + 4, fill=u["tooltip_bg"], outline="", tags="cursor")
        cv.tag_lower(rect, cid)


def _nice(x):
    import math
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if x <= m * e:
            return m * e
    return 10 * e


def _ceil(x):
    import math
    return math.ceil(x - 1e-9)


def _floor(x):
    import math
    return math.floor(x + 1e-9)


class EventsPanel(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="Surface.TFrame")
        self.app = app
        self.tree = ttk.Treeview(self, columns=("time", "part", "event"), show="headings", selectmode="browse")
        for col, text, w, st in (("time", "Time (s)", 80, False), ("part", "Part", 90, False), ("event", "Event", 500, True)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=st)
        self.tree.pack(side="left", fill="both", expand=True)
        _scroll(self, self.tree).pack(side="right", fill="y")
        self.count = 0

    def update_events(self):
        sim = self.app.sim
        if sim is None:
            return
        ev = sim.events
        if len(ev) < self.count:
            self.clear()
        for t, tag, text in ev[self.count:]:
            self.tree.insert("", "end", values=(f"{t:.2f}", tag, text))
        if len(ev) > self.count:
            kids = self.tree.get_children()
            if kids:
                self.tree.see(kids[-1])
        self.count = len(ev)

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.count = 0


class ChecksPanel(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="Surface.TFrame")
        self.app = app
        self.tree = ttk.Treeview(self, columns=("level", "text"), show="headings", selectmode="browse")
        self.tree.heading("level", text="Level", anchor="w")
        self.tree.heading("text", text="What FluidWorx found", anchor="w")
        self.tree.column("level", width=80, stretch=False)
        self.tree.column("text", width=700, stretch=True)
        self.tree.pack(side="left", fill="both", expand=True)
        _scroll(self, self.tree).pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._pick)
        self._map = {}

    def rebuild(self):
        self.tree.delete(*self.tree.get_children())
        self._map = {}
        c = self.app.circuit
        if c is None:
            return
        rank = {"error": 0, "warning": 1, "info": 2}
        u = self.app.theme.ui
        self.tree.tag_configure("warning", foreground=u["warning"])
        self.tree.tag_configure("error", foreground=u["danger"])
        issues = sorted(c.issues, key=lambda i: rank.get(i.level, 3))
        for i in issues:
            iid = self.tree.insert("", "end", values=(i.level.capitalize(), i.text), tags=(i.level,))
            self._map[iid] = i.part
        if not issues:
            self.tree.insert("", "end", values=("OK", "Nothing to report."))

    def _pick(self, _e):
        sel = self.tree.selection()
        if sel and self._map.get(sel[0]):
            self.app.select(self._map[sel[0]], reveal=True)
