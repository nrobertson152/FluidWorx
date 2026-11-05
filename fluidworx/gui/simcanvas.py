"""The live circuit: the OpenSchematix sheet with wires coloured by pressure or voltage, beads along the real paths,
valves that shift, rods that move, contacts that close, coils and lamps that light up."""
from __future__ import annotations

import math
import tkinter as tk

from .. import electric, engine
from ..gui_support import cylinder_motion
from ..report import pressure_color, voltage_color
from ..vendor.openschematix.connectivity import analyse
from ..vendor.openschematix.geometry import point_on_segment
from ..vendor.openschematix.gui.canvas_view import DrawingView, draw_items
from ..vendor.openschematix.render import scene
from ..vendor.openschematix.symbols.base import LINE_WIDTHS
from ..vendor.openschematix.symbols.fluid import ENV, HALF, LEAD

BEAD_SPACING = 36.0      # drawing units between flow beads
PICK_PX = 7
GLOW = {"lamp": ("#ffe680", "#6b5a14"), "led": ("#ffd0d0", "#6b2a2a"), "emotor": ("#c9efcf", "#21502a"),
        "emotor3": ("#c9efcf", "#21502a"), "buzzer": ("#ffe680", "#6b5a14")}
LED_ON = "#22c55e"
ALARM = "#dc2626"


def _prim(p, comp, dx=0.0, color=None):
    """One symbol primitive placed in the world, with its local x shifted by dx."""
    q = {"k": p["k"], "role": "ink", "wpx": LINE_WIDTHS.get(p.get("w", "normal"), 1.4), "dash": p.get("dash", False)}
    if color:
        q["color"] = color
    if p["k"] in ("line", "poly"):
        q["pts"] = [comp.local_to_world(x + dx, y) for x, y in p["pts"]]
        q["fill"] = p.get("fill", False)
    elif p["k"] == "circle":
        q["c"] = comp.local_to_world(p["c"][0] + dx, p["c"][1])
        q["r"] = p["r"]
        q["fill"] = p.get("fill", False)
    elif p["k"] == "text":
        q.update(p=comp.local_to_world(p["p"][0] + dx, p["p"][1]), s=p["s"], size=p.get("size", 8),
                 anchor=p.get("anchor", "c"))
    else:
        return None
    return q


class SimCanvas(DrawingView):
    def __init__(self, master, app, **kw):
        super().__init__(master, takefocus=1, **kw)
        self.app = app
        self.doc = None
        self.node_items: dict = {}
        self.node_colors: dict = {}
        self.valves: dict = {}
        self.cylinders: dict = {}
        self.motors: dict = {}
        self.switches: dict = {}
        self.glows: dict = {}
        self.plcs: dict = {}
        self.el_items: dict = {}
        self.el_colors: dict = {}
        self.el_seg_view: list = []
        self.el_junctions: dict = {}
        self._held = None
        self.badges: dict = {}
        self.beads: list = []
        self.seg_view: list = []
        self.phase: dict = {}
        self.junction_nodes: dict = {}
        self.drag = None
        self._hover = None
        self._ready = False
        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double)
        self.bind("<ButtonPress-3>", self._on_right)
        self.bind("<Leave>", lambda e: self.app.hover_text(""))
        self._fitted = False

    # ---------------------------------------------------------------- setup
    @property
    def theme(self):
        return self.app.theme

    @property
    def sim(self):
        return self.app.sim

    @property
    def circuit(self):
        return self.app.circuit

    def set_doc(self, doc, fit=True):
        self.doc = doc
        self.phase.clear()
        self.valves, self.cylinders, self.motors = {}, {}, {}
        self.switches, self.glows, self.plcs = {}, {}, {}
        self.node_items, self.node_colors, self.badges = {}, {}, {}     # drawn items belong to the old circuit
        self.el_items, self.el_colors = {}, {}
        self.seg_view = []
        self.el_seg_view = []
        self._held = None
        self._ready = False
        if doc is None:
            self.redraw()
            return
        for part in self.circuit.parts:
            if part.sheet != doc.uid:
                continue
            b = self.sim.parts[part.key]
            if isinstance(b, engine.Valve):
                geom = part.comp.geometry()
                leads, moving = {}, []
                ports = {t.name: t for t in geom.terminals if t.name in b.layout}
                for i, p in enumerate(geom.prims):
                    hit = None
                    if p["k"] == "line" and len(p["pts"]) == 2:
                        for name, t in ports.items():
                            if (t.x, t.y) in p["pts"] and p["pts"][0][0] == p["pts"][1][0]:
                                hit = name
                    if hit:
                        leads[i] = hit
                    else:
                        moving.append(i)
                width = ENV * b.npos + (HALF if (part.comp.params or {}).get("transition") and b.npos == 2 else 0)
                self.valves[part.comp.id] = {"b": b, "leads": leads, "moving": moving, "dx": 0.0, "width": width,
                                             "gap": width - ENV * b.npos, "key": None}
            elif isinstance(b, engine.Actuator):
                if b.rotary:
                    self.motors[part.comp.id] = {"b": b}
                else:
                    self.cylinders[part.comp.id] = {"b": b, "motion": cylinder_motion(part.comp.geometry()), "key": None}
            elif isinstance(b, electric.Part):
                if b.poles_now():
                    self.switches[part.comp.id] = {"b": b, "key": None}
                if isinstance(b, electric.Plc):
                    self.plcs[part.comp.id] = {"b": b, "key": None}
                elif isinstance(b, (electric.Coil, electric.Load, electric.Led, electric.Motor3, electric.Prox)):
                    self.glows[part.comp.id] = {"b": b, "item": None, "on": None}
        self._index_segments()
        self.junction_nodes = {}
        self.el_junctions = {}
        for p in analyse(doc).junctions:
            for w in doc.wires.values():
                if any(point_on_segment(p, a, b) for a, b in zip(w.points, w.points[1:])):
                    node = self.circuit.wire_nodes.get((doc.uid, w.id))
                    if node is not None:
                        self.junction_nodes[(round(p[0], 2), round(p[1], 2))] = node
                        break
                    node = self.circuit.el_wire_nodes.get((doc.uid, w.id))
                    if node is not None:
                        self.el_junctions[(round(p[0], 2), round(p[1], 2))] = node
                        break
        self._fitted = False
        if fit and self.winfo_width() > 10:
            self.fit()
        else:
            self.redraw()

    def _index_segments(self):
        self.seg_view = []
        self.el_seg_view = []
        if self.doc is None:
            return
        for paths, view in ((self.app.flowpaths, self.seg_view), (self.app.currentpaths, self.el_seg_view)):
            if paths is None:
                continue
            for i, seg in enumerate(paths.segments):
                if seg[0] == self.doc.uid:
                    L = math.hypot(seg[3][0] - seg[2][0], seg[3][1] - seg[2][1])
                    if L > 0.5:
                        view.append((i, seg[2], seg[3], L))

    def fit(self, margin=26):
        if self.doc is None:
            return
        comps = list(self.doc.components.values())
        wires = list(self.doc.wires.values())
        xs, ys = [], []
        for c in comps:
            b = c.bbox()
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        for w in wires:
            xs += [p[0] for p in w.points]
            ys += [p[1] for p in w.points]
        if xs:
            pad = 40
            self.fit_box((min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad), margin)
        else:
            W, H = self.doc.sheet.size_units()
            self.fit_box((0, 0, W, H), margin)
        self._fitted = True

    def _on_configure(self, _e):
        if self.doc is not None and not self._fitted:
            self.fit()
        else:
            self.redraw()

    def view_changed(self):
        self.app.update_zoom_label()

    # ---------------------------------------------------------------- full redraw
    def _redraw_now(self):
        self._redraw_pending = False
        self.delete("all")
        c = self.theme
        self.configure(bg=c["desk"])
        self.node_items, self.node_colors, self.badges, self.beads = {}, {}, {}, []
        self.el_items, self.el_colors = {}, {}
        if self.doc is None or self.sim is None:
            return
        W, H = self.doc.sheet.size_units()
        x0, y0 = self.to_screen((0, 0))
        x1, y1 = self.to_screen((W, H))
        self.create_rectangle(x0 + 4, y0 + 4, x1 + 4, y1 + 4, fill=c["paper_shadow"], outline="")
        self.create_rectangle(x0, y0, x1, y1, fill=c["paper"], outline=c["frame"], tags="paper")
        items = scene(self.doc, screen=False, project=self.circuit.project)
        dynamic = set(self.valves) | set(self.cylinders)
        static, wires, junctions = [], [], []
        valve_text: dict = {}
        for it in items:
            role = it.get("role")
            if role == "wire":
                wires.append(it)
            elif role == "junction":
                junctions.append(it)
            elif role == "ink" and it.get("item") in dynamic:
                continue
            elif it.get("item") in dynamic and it.get("k") == "text":
                valve_text.setdefault(it["item"], []).append(it)    # a part's name keeps clear of what moves
            else:
                static.append(it)
        draw_items(self, static, self.to_screen, self.zoom, c, self.font_family)
        for it in wires:
            node = self.circuit.wire_nodes.get((self.doc.uid, it["item"]))
            width = max(1.5, it.get("wpx", 1.4) * self.zoom * 1.5)
            pts = [v for p in it["pts"] for v in self.to_screen(p)]
            dash = (max(2, int(6 * self.zoom)), max(2, int(3 * self.zoom))) if it.get("dash") else None
            cid = self.create_line(*pts, fill=c["wire"], width=width, dash=dash, capstyle="round", joinstyle="round",
                                   tags="wire")
            if node is not None:
                self.node_items.setdefault(node, []).append(cid)
            else:
                el = self.circuit.el_wire_nodes.get((self.doc.uid, it["item"]))
                if el is not None:
                    self.el_items.setdefault(el, []).append(cid)
        for it in junctions:
            x, y = self.to_screen(it["c"])
            r = max(2.0, it["r"] * self.zoom)
            cid = self.create_oval(x - r, y - r, x + r, y + r, fill=c["wire"], outline="", tags="wire")
            at = (round(it["c"][0], 2), round(it["c"][1], 2))
            node = self.junction_nodes.get(at)
            if node is not None:
                self.node_items.setdefault(node, []).append(cid)
            elif at in self.el_junctions:
                self.el_items.setdefault(self.el_junctions[at], []).append(cid)
        for v in self.switches.values():
            v["key"] = None
        for v in self.plcs.values():
            v["key"] = None
        for cid, v in self.glows.items():
            comp = self.doc.components.get(cid)
            b = comp.bbox()
            x0, y0 = self.to_screen((b[0] - 2, b[1] - 2))
            x1, y1 = self.to_screen((b[2] + 2, b[3] + 2))
            kind = v["b"].part.kind
            colors = GLOW.get(kind)
            fill = (colors[1] if self._dark() else colors[0]) if colors else self.theme.ui["accent_soft"]
            v["item"] = self.create_rectangle(x0, y0, x1, y1, fill=fill, outline="", state="hidden", tags="glow")
            self.tag_raise(v["item"], "paper")
            v["on"] = None
        for cid, v in self.valves.items():
            v["key"] = None
            v["text"] = valve_text.get(cid, [])
        for cid, v in self.cylinders.items():
            v["key"] = None
            v["text"] = valve_text.get(cid, [])
        self._make_badges()
        self._draw_selection()
        self._draw_legend()
        self._ready = True
        self.update_state(0.0, force=True)

    def _draw_selection(self):
        self.delete("selection")
        key = self.app.selected
        if key is None or self.doc is None or key[0] != self.doc.uid:
            return
        comp = self.doc.components.get(key[1])
        if comp is None:
            return
        b = comp.bbox()
        x0, y0 = self.to_screen((b[0] - 3, b[1] - 3))
        x1, y1 = self.to_screen((b[2] + 3, b[3] + 3))
        self.create_rectangle(x0, y0, x1, y1, outline=self.theme["select"], dash=(4, 3), width=1.5, tags="selection")

    def selection_changed(self):
        self._draw_selection()

    def _draw_legend(self):
        """Colour key in the corner of the view: what the wire colours mean, with real numbers."""
        self.delete("legend")
        sim = self.sim
        if sim is None:
            return
        u = self.theme.ui
        f = self.theme.fonts
        dark = self._dark()
        pmax = sim.max_pressure()
        x, y, w, h = 14, 14, 150, 8
        self.create_rectangle(x - 8, y - 7, x + w + 8, y + h + 25, fill=u["surface"], outline=u["border"], tags="legend")
        self._legend_max = pmax
        if not self.node_items and self.el_items:
            steps = 30
            for i in range(steps):
                col = pressure_color(((i + .5) / steps) ** 2, 1.0, dark)
                self.create_rectangle(x + w * i / steps, y, x + w * (i + 1) / steps + 1, y + h, fill=col, outline="", tags="legend")
            self.create_text(x, y + h + 11, text="0 V", anchor="w", fill=u["muted"], font=f["small"], tags="legend")
            self.create_text(x + w, y + h + 11, text="full voltage", anchor="e", fill=u["muted"], font=f["small"], tags="legend")
            return
        steps = 30
        for i in range(steps):
            col = pressure_color(pmax * ((i + .5) / steps) ** 2, pmax, dark)
            self.create_rectangle(x + w * i / steps, y, x + w * (i + 1) / steps + 1, y + h, fill=col, outline="",
                                  tags="legend")
        un = self.app.units
        self.create_text(x, y + h + 11, text="0", anchor="w", fill=u["muted"], font=f["small"], tags="legend")
        self.create_text(x + w, y + h + 11, text=un.fmt("pressure", pmax), anchor="e", fill=u["muted"],
                         font=f["small"], tags="legend")
        self._legend_max = pmax

    def _dark(self):
        return self.theme.canvas_name != "paper"

    # ---------------------------------------------------------------- per-frame updates
    def update_state(self, real_dt: float, force=False):
        sim = self.sim
        if sim is None or self.doc is None or not self._ready:
            return
        pmax = sim.max_pressure()
        if abs(pmax - getattr(self, "_legend_max", 0.0)) > 1:
            self._draw_legend()
        dark = self._dark()
        self._node_col = {}
        for node, cids in self.node_items.items():
            col = pressure_color(sim.p[node], pmax, dark)
            self._node_col[node] = col
            if self.node_colors.get(node) != col:
                self.node_colors[node] = col
                for cid in cids:
                    self.itemconfigure(cid, fill=col)
        self._update_valves(real_dt, pmax, dark)
        self._update_cylinders(pmax, dark)
        self._update_motors()
        self._update_electric(dark)
        self._update_beads(real_dt)
        self._update_badges()
        self.tag_raise("legend")

    def _update_valves(self, real_dt, pmax, dark):
        sim = self.sim
        for cid, v in self.valves.items():
            b = v["b"]
            target = ENV * (b.normal - b.position)
            if b.position > b.normal or b.normal > b.position:
                target -= (v["gap"] if b.position >= 1 and b.normal == 0 else 0)
                target += (v["gap"] if b.normal >= 1 and b.position == 0 else 0)
            if real_dt > 0:
                step = ENV * real_dt / 0.08      # spools shift visibly but quickly
                d = target - v["dx"]
                v["dx"] = target if abs(d) <= step else v["dx"] + math.copysign(step, d)
            else:
                v["dx"] = target
            key = (round(v["dx"], 1), tuple(pressure_color(sim.p[b.t[n]], pmax, dark) for n in b.layout if n in b.t),
                   b.position)
            if key == v["key"]:
                continue
            v["key"] = key
            self._draw_valve(cid, v)

    def _draw_valve(self, cid, v):
        tag = f"dyn{cid}"
        self.delete(tag)
        b = v["b"]
        comp = b.part.comp
        geom = comp.geometry()
        dx = v["dx"]
        # shade the position that is connected to the ports right now
        x0 = -v["width"] / 2 + ENV * b.position + (v["gap"] if b.position >= 1 else 0)
        corners = [comp.local_to_world(x0 + dx, -HALF), comp.local_to_world(x0 + ENV + dx, -HALF),
                   comp.local_to_world(x0 + ENV + dx, HALF), comp.local_to_world(x0 + dx, HALF)]
        self.create_polygon(*[n for p in corners for n in self.to_screen(p)], fill=self.theme.ui["accent_soft"],
                            outline="", tags=tag)
        prims = []
        for i in v["moving"]:
            q = _prim(geom.prims[i], comp, dx)
            if q:
                prims.append(q)
        for i, name in v["leads"].items():
            q = _prim(geom.prims[i], comp, 0.0, pressure_color(self.sim.p[b.t[name]], self.sim.max_pressure(),
                                                                 self._dark()) if name in b.t else None)
            if q:
                prims.append(q)
        ax, ay = comp.local_to_world(0, 0)
        bx, by = comp.local_to_world(dx, 0)
        for it in v.get("text", []):
            prims.append(dict(it, p=(it["p"][0] + bx - ax, it["p"][1] + by - ay), item=None))
        draw_items(self, prims, self.to_screen, self.zoom, self.theme, self.font_family, tag=tag)

    def _update_cylinders(self, pmax, dark):
        for cid, v in self.cylinders.items():
            b = v["b"]
            key = round(b.fraction, 3)
            if key == v["key"]:
                continue
            v["key"] = key
            tag = f"dyn{cid}"
            self.delete(tag)
            comp = b.part.comp
            geom = comp.geometry()
            motion = v["motion"]
            prims = []
            dx = 0.0
            if motion:
                moving, dx0, dx1 = motion
                dx = dx0 + (dx1 - dx0) * b.fraction
                for i, p in enumerate(geom.prims):
                    q = _prim(p, comp, dx if i in moving else 0.0)
                    if q:
                        prims.append(q)
            else:
                prims = [q for q in (_prim(p, comp) for p in geom.prims) if q]
            ax, ay = comp.local_to_world(0, 0)
            bx, by = comp.local_to_world(max(dx, 0.0), 0)
            for it in v.get("text", []):
                prims.append(dict(it, p=(it["p"][0] + bx - ax, it["p"][1] + by - ay), item=None))
            draw_items(self, prims, self.to_screen, self.zoom, self.theme, self.font_family, tag=tag)

    # ---------------------------------------------------------------- the electrical side
    def _update_electric(self, dark):
        net = self.sim.net
        for node, cids in self.el_items.items():
            col = voltage_color(net, node, dark)
            if self.el_colors.get(node) != col:
                self.el_colors[node] = col
                for cid in cids:
                    self.itemconfigure(cid, fill=col)
        for cid, v in self.glows.items():
            on = bool(v["b"].is_on())
            if on != v["on"] and v["item"] is not None:
                v["on"] = on
                self.itemconfigure(v["item"], state="normal" if on else "hidden")
        for cid, v in self.switches.items():
            b = v["b"]
            poles = b.poles_now()
            key = tuple((a, z, closed, voltage_color(net, b.t[a], dark) if closed else "") for a, z, closed, _drawn in poles)
            if key != v["key"]:
                v["key"] = key
                self._draw_poles(cid, b, poles, dark)
        for cid, v in self.plcs.items():
            b = v["b"]
            key = tuple(sorted((n, s) for n, s in ((n, b.pin_state(n)) for n in b.names) if s is not None))
            if key != v["key"]:
                v["key"] = key
                self._draw_pins(cid, b)

    def _draw_poles(self, cid, b, poles, dark):
        """A contact as it is now. A closed pole is a line in the colour of what it carries; a pole drawn closed that
        has opened gets a gap and a raised blade, so a symbol never looks closed when it isn't."""
        tag = f"pole{cid}"
        self.delete(tag)
        ends = b.part.comp.terminals()
        width = max(2.0, 2.2 * self.zoom)
        paper = self.theme["paper"]
        net = self.sim.net
        for a, z, closed, drawn_closed in poles:
            p, q = ends[a], ends[z]
            x0, y0 = self.to_screen(p)
            x1, y1 = self.to_screen(q)
            if closed:
                self.create_line(x0, y0, x1, y1, fill=voltage_color(net, b.t[a], dark), width=width, capstyle="round", tags=tag)
            elif drawn_closed:
                mx0, my0 = x0 + (x1 - x0) * 0.3, y0 + (y1 - y0) * 0.3
                mx1, my1 = x0 + (x1 - x0) * 0.7, y0 + (y1 - y0) * 0.7
                self.create_line(mx0, my0, mx1, my1, fill=paper, width=width * 3.5, tags=tag)
                length = math.hypot(x1 - x0, y1 - y0) or 1.0
                nx, ny = (y1 - y0) / length, -(x1 - x0) / length
                lift = 0.25 * length
                self.create_line(mx0, my0, mx1 + nx * lift, my1 + ny * lift, fill=ALARM, width=width, capstyle="round", tags=tag)

    def _draw_pins(self, cid, b):
        tag = f"pins{cid}"
        self.delete(tag)
        comp = b.part.comp
        r = max(2.0, 2.4 * self.zoom)
        inset = {"l": 9, "r": -9}
        for t in comp.geometry().terminals:
            state = b.pin_state(t.name)
            if state is None or t.dir not in inset:
                continue
            x, y = self.to_screen(comp.local_to_world(t.x + inset[t.dir], t.y))
            self.create_oval(x - r, y - r, x + r, y + r, fill=LED_ON if state else self.theme["paper"],
                             outline=self.theme.ui["border_strong"], tags=tag)

    def _update_motors(self):
        self.delete("motordot")
        for v in self.motors.values():
            b = v["b"]
            if abs(b.v) < 1e-4:
                continue
            a = b.x
            x, y = self.to_screen(b.part.comp.local_to_world(8 * math.cos(a), 8 * math.sin(a)))
            r = max(2.0, 2.2 * self.zoom)
            self.create_oval(x - r, y - r, x + r, y + r, fill=self.theme["select"], outline="", tags="motordot")

    def _update_beads(self, real_dt):
        if not self.app.settings["show_flow"]:
            self.delete("bead")
            self.beads = []
            return
        r = max(1.6, 1.9 * self.zoom)
        speed_factor = self.app.speed if self.app.running else 0.0
        paper = self.theme["paper"]
        used = 0
        beads = self.beads
        lines = []
        if self.app.flowpaths is not None and self.seg_view:
            lines.append(("q", self.seg_view, self.app.flowpaths.compute(self.sim.terminal_flows()), 3e-7))
        if self.app.currentpaths is not None and self.el_seg_view:
            lines.append(("i", self.el_seg_view, self.app.currentpaths.compute(self.sim.net.terminal_currents()), 1e-3))
        for family, view, flows, least in lines:
            for i, a, b, L in view:
                q = flows[i]
                aq = abs(q)
                if aq < least:
                    continue
                ph = self.phase.get((family, i), 0.0)
                # bead speed grows with the logarithm of flow, so slow and fast lines can both be read
                v = (30 + 50 * max(0.0, math.log10(aq / least))) * speed_factor ** 0.5
                ph = (ph + (v * real_dt if q.real > 0 else -v * real_dt)) % BEAD_SPACING
                self.phase[(family, i)] = ph
                n = int(L / BEAD_SPACING) + 1
                for k in range(n):
                    s = ph + k * BEAD_SPACING
                    if s > L:
                        break
                    t = s / L
                    x, y = self.to_screen((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                    if used < len(beads):
                        self.coords(beads[used], x - r, y - r, x + r, y + r)
                        self.itemconfigure(beads[used], state="normal", fill=paper)
                    else:
                        beads.append(self.create_oval(x - r, y - r, x + r, y + r, fill=paper, outline="", tags="bead"))
                    used += 1
        for cid in beads[used:]:
            self.itemconfigure(cid, state="hidden")
        self.tag_raise("bead")

    # ---------------------------------------------------------------- value badges
    def _make_badges(self):
        if not self.app.settings["show_values"]:
            return
        f = (self.font_family, -max(9, int(10 * min(self.zoom, 1.6))), "bold")
        u = self.theme.ui
        for part in self.circuit.parts:
            if part.sheet != self.doc.uid:
                continue
            b = self.sim.parts[part.key]
            live_text = isinstance(b, electric.Part) and type(b).badge is not electric.Part.badge
            if not self._badge_text(b) and not live_text:
                if part.kind not in ("relief", "pressure_switch"):
                    continue
            box = part.comp.bbox()
            if part.kind == "gauge":
                pos, anchor = self.to_screen((box[2] + 5, box[3] - 2)), "w"     # the part's name is at its upper right
            elif isinstance(b, engine.Actuator) or isinstance(b, electric.Plc):
                pos, anchor = self.to_screen(((box[0] + box[2]) / 2, box[1] - 4)), "s"
            else:
                pos, anchor = self.to_screen((box[0] - 5, (box[1] + box[3]) / 2)), "e"
            rect = self.create_rectangle(0, 0, 0, 0, fill=u["surface"], outline=u["border"], tags="badge", state="hidden")
            txt = self.create_text(pos[0], pos[1], text="", anchor=anchor, font=f, fill=u["text"], tags="badge")
            self.badges[part.key] = (b, rect, txt, "")

    def _badge_text(self, b) -> str:
        un = self.app.units
        p = self.sim.p
        if isinstance(b, electric.Part):
            return b.badge(un)
        if isinstance(b, engine.Actuator):
            if b.rotary:
                return un.fmt("rpm", abs(b.v))
            s = f"{un.fmt('length', b.x)}"
            if abs(b.v) > engine.MOVE_EPS:
                s += f" · {un.fmt('speed', abs(b.v))}"
            return s
        if isinstance(b, engine.PressureSwitch):
            return "ON" if b.on else ""
        if isinstance(b, engine.Gauge):
            return "" if b.silent else un.fmt("pressure", b.value(p))
        if isinstance(b, engine.Pump):
            return un.fmt("pressure", b._dp(p)) if b.running else "stopped"
        if isinstance(b, engine.Relief):
            return un.fmt("flow", b.seat.q(p)) if b.seat.q(p) > engine.FLOW_EPS else ""
        return ""

    def _update_badges(self):
        for key, (b, rect, txt, last) in list(self.badges.items()):
            s = self._badge_text(b)
            if s == last:
                continue
            self.badges[key] = (b, rect, txt, s)
            self.itemconfigure(txt, text=s)
            if not s:
                self.itemconfigure(rect, state="hidden")
                continue
            box = self.bbox(txt)
            if box:
                self.coords(rect, box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2)
                self.itemconfigure(rect, state="normal")
        self.tag_raise("badge")

    # ---------------------------------------------------------------- picking and interaction
    def part_at(self, x, y):
        """The part under a screen point (smallest bounding box wins)."""
        if self.doc is None or self.circuit is None:
            return None
        wx, wy = self.to_world(x, y)
        m = PICK_PX / self.zoom
        best, area = None, None
        for part in self.circuit.parts:
            if part.sheet != self.doc.uid:
                continue
            b = part.comp.bbox()
            if b[0] - m <= wx <= b[2] + m and b[1] - m <= wy <= b[3] + m:
                a = (b[2] - b[0]) * (b[3] - b[1])
                if area is None or a < area:
                    best, area = part, a
        return best

    def wire_at(self, x, y):
        if self.doc is None:
            return None
        wx, wy = self.to_world(x, y)
        tol = PICK_PX / self.zoom
        for w in self.doc.wires.values():
            for a, b in zip(w.points, w.points[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                L2 = dx * dx + dy * dy
                t = max(0.0, min(1.0, ((wx - a[0]) * dx + (wy - a[1]) * dy) / L2)) if L2 else 0.0
                if math.hypot(wx - a[0] - t * dx, wy - a[1] - t * dy) <= tol:
                    return w
        return None

    def _side_of(self, comp, x, y):
        wx, wy = self.to_world(x, y)
        cx, cy = comp.local_to_world(0, 0)
        lx, ly = comp.local_to_world(-10, 0)
        return "left" if (wx - cx) * (lx - cx) + (wy - cy) * (ly - cy) > 0 else "right"

    def valve_click_action(self, part, x, y):
        """Which operator a click on a valve means."""
        b = self.sim.parts[part.key]
        can = [s for s in ("left", "right") if b.side_can_actuate(s)]
        if not can:
            return None
        if len(can) == 1:
            return can[0]
        return self._side_of(part.comp, x, y)

    def _on_motion(self, e):
        if self.sim is None or self.doc is None:
            return
        part = self.part_at(e.x, e.y)
        if part is not None:
            b = self.sim.parts[part.key]
            st = b.status(self.sim.p)
            text = f"{part.title}: {part.symbol_name}" + (f" — {st}" if st else "")
            action = isinstance(b, (engine.Valve, engine.Switched)) and (
                not isinstance(b, engine.Valve) or self.valve_click_action(part, e.x, e.y))
            if isinstance(b, engine.Valve) and action:
                text += f". Click: {action} operator"
            elif isinstance(b, engine.Switched):
                text += ". Click to switch"
            elif isinstance(b, electric.Button):
                action = True
                text += ". Hold the mouse down to press it"
            elif isinstance(b, electric.Part) and b.click_command():
                action = True
                text += ". Click to operate"
            self.configure(cursor="hand2" if action else "")
            self.app.hover_text(text)
            return
        self.configure(cursor="")
        w = self.wire_at(e.x, e.y)
        if w is not None:
            el = self.circuit.el_wire_nodes.get((self.doc.uid, w.id))
            if el is not None:
                un = self.app.units
                amps = 0.0
                cp = self.app.currentpaths
                if cp is not None:
                    flows = cp.compute(self.sim.net.terminal_currents())
                    for i, seg in enumerate(cp.segments):
                        if seg[0] == self.doc.uid and seg[1] == w.id:
                            amps = max(amps, abs(flows[i]))
                self.app.hover_text(f"Line: {un.fmt('voltage', electric.signed(self.sim.net.v[el]))}, {un.fmt('current', amps)}")
                return
            node = self.circuit.wire_nodes.get((self.doc.uid, w.id))
            if node is not None:
                un = self.app.units
                fp = self.app.flowpaths
                q = 0.0
                if fp is not None:
                    flows = fp.compute(self.sim.terminal_flows())
                    for i, seg in enumerate(fp.segments):
                        if seg[0] == self.doc.uid and seg[1] == w.id:
                            q = max(q, abs(flows[i]))
                self.app.hover_text(f"Line: {un.fmt('pressure', self.sim.p[node])}, {un.fmt('flow', q)}")
                return
        self.app.hover_text("")

    def _on_press(self, e):
        self.focus_set()
        part = self.part_at(e.x, e.y) if self.sim is not None else None
        if part is not None and isinstance(self.sim.parts[part.key], electric.Button):
            self._held = part.key       # a push-button stays pressed for as long as the mouse is down on it
            self.drag = None
            self.app.select(part.key)
            self.app.command(part.key, "press")
            return
        self.drag = (e.x, e.y, self.ox, self.oy, False)

    def _on_drag(self, e):
        if not self.drag:
            return
        x, y, ox, oy, moved = self.drag
        if not moved and abs(e.x - x) + abs(e.y - y) < 4:
            return
        self.drag = (x, y, ox, oy, True)
        self.ox = ox - (e.x - x) / self.zoom
        self.oy = oy - (e.y - y) / self.zoom
        self.configure(cursor="fleur")
        self.redraw()

    def _on_release(self, e):
        drag, self.drag = self.drag, None
        self.configure(cursor="")
        if self._held is not None:
            key, self._held = self._held, None
            if self.sim is not None and key in self.sim.parts:
                self.app.command(key, "release")
            return
        if drag and drag[4]:
            self.view_changed()
            return
        if self.sim is None:
            return
        part = self.part_at(e.x, e.y)
        self.app.select(part.key if part else None)
        if part is None:
            return
        b = self.sim.parts[part.key]
        if isinstance(b, engine.Valve):
            act = self.valve_click_action(part, e.x, e.y)
            if act:
                self.app.command(part.key, act)
        elif isinstance(b, engine.Switched):
            self.app.command(part.key, "toggle")
        elif isinstance(b, electric.Part) and b.click_command():
            self.app.command(part.key, b.click_command())

    def _on_double(self, e):
        part = self.part_at(e.x, e.y)
        if part is not None and isinstance(self.sim.parts[part.key], engine.Pump):
            self.app.command(part.key, "toggle")

    def _on_right(self, e):
        part = self.part_at(e.x, e.y)
        if part is None:
            return
        self.app.select(part.key)
        b = self.sim.parts[part.key]
        acts = b.actions()
        m = tk.Menu(self, tearoff=0)
        from ..vendor.openschematix.gui import theme as th
        for name, label, on in acts:
            m.add_command(label=("✓ " if on else "") + label, command=lambda n=name: self.app.command(part.key, n))
        if acts:
            m.add_separator()
        m.add_command(label="Reset this part's values to the drawing", command=lambda: self.app.reset_part_params(part.key))
        th.recolor_menu(m, self.theme)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
