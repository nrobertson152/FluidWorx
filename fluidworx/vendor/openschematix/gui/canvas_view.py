"""Drawing views.

DrawingView      - view transform (zoom/pan) and drawing of scene primitives
                   on a Tk canvas; used for previews and revision comparison.
SchematicCanvas  - the editor: selection, moving, wires, symbol placement,
                   template placement, interactive commands with grid snap,
                   object snap and ortho, crossing/junction editing.
"""
from __future__ import annotations

import math
import tkinter as tk

from .. import editing, symbols
from ..connectivity import analyse
from ..geometry import GRID, elbow, point_on_segment, same, simplify_orthogonal, snap
from ..model import Component, Document
from ..render import component_prims, scene
from . import interact as ia

ZOOM_MIN, ZOOM_MAX = 0.05, 20.0
PICK_PX = 6          # pick tolerance in screen pixels
TERM_SNAP_PX = 9     # snap-to-terminal radius in screen pixels
OSNAP_PX = 11        # object snap radius


def region_screen_points(rings, to_screen, zoom) -> list:
    """Flat screen coordinates of a boundary fill as ONE Tk polygon.

    Tk polygons have no holes, so every ring is joined to a common anchor
    by a zero-width "keyhole" cut that is walked in both directions. Holes
    are oriented opposite to their outer ring, so the result is the same
    under the even-odd rule (X11, Windows default) and the non-zero rule."""
    from ..regions import flatten_ring
    tol = 0.35 / max(zoom, 1e-9)          # chord error about a third of a pixel
    flat = [flatten_ring(r, tol) for r in rings]
    flat = [r for r in flat if len(r) >= 2]
    if not flat:
        return []
    anchor = flat[0][0]
    seq = []
    for r in flat:
        seq += r + [r[0], anchor]
    return [v for p in seq for v in to_screen(p)]


def draw_items(cv: tk.Canvas, items, to_screen, zoom, colors, font_family, selected=(), override=None,
               tag="scene", color_fn=None, hovered=None, width_scale=1.0, hover_index=None):
    """Draw scene primitives on a Tk canvas. `colors` is a Theme (or dict).

    `hover_index` (optional HoverIndex): records the canvas items whose color hover would change (not
    overridden, not selected), so the hover highlight can later be moved without redrawing."""
    sel_col = colors["select"]
    record = hover_index is not None
    if record:
        rec_item, rec_cid = hover_index.items.append, hover_index.cids.append
    for it in items:
        role = it.get("role", "ink")
        item = it.get("item")
        hoverable = False
        if override:
            color = override
        elif color_fn is not None:
            color = color_fn(it)
            if color is None:
                continue
        elif item is not None and item in selected:
            color = sel_col
        else:
            if it.get("color"):
                normal = it["color"]
            elif role == "designator":
                normal = colors["ink"]
            else:
                normal = colors.get(role, colors["ink"]) if hasattr(colors, "get") else colors["ink"]
            hoverable = item is not None
            color = colors["hover"] if hoverable and item == hovered else normal
        w = max(1.0, it.get("wpx", 1.4) * zoom * width_scale)
        if item is not None and item in selected and not override:
            w += 1
        dash = (max(2, int(6 * zoom)), max(2, int(3 * zoom))) if it.get("dash") else None
        k = it["k"]
        cid = None
        if k == "line":
            pts = [v for p in it["pts"] for v in to_screen(p)]
            if len(pts) >= 4:
                cid = cv.create_line(*pts, fill=color, width=w, dash=dash, capstyle="round", joinstyle="round",
                                     tags=tag)
        elif k == "poly":
            pts = [v for p in it["pts"] for v in to_screen(p)]
            cid = cv.create_polygon(*pts, outline=color, fill=color if it.get("fill") else "", width=w, dash=dash,
                                    joinstyle="round", tags=tag)
        elif k == "region":
            pts = region_screen_points(it["rings"], to_screen, zoom)
            if len(pts) >= 6:
                cid = cv.create_polygon(*pts, outline="", fill=color, width=0, tags=tag)
        elif k == "circle":
            x, y = to_screen(it["c"])
            r = it["r"] * zoom
            cid = cv.create_oval(x - r, y - r, x + r, y + r, outline=color, fill=color if it.get("fill") else "",
                                 width=w, dash=dash, tags=tag)
        elif k == "text":
            px = it.get("size", 10) * zoom
            if px < 3:
                continue
            x, y = to_screen(it["p"])
            anchor = {"c": "center"}.get(it.get("anchor", "c"), it.get("anchor", "c"))
            font = (font_family, -max(1, int(round(px))), "bold" if it.get("bold") else "normal")
            kw = {}
            if it.get("angle"):
                kw["angle"] = it["angle"]
            cid = cv.create_text(x, y, text=it["s"], fill=color, font=font, anchor=anchor, tags=tag, **kw)
        if record and hoverable and cid is not None:
            rec_item(item)
            rec_cid(cid)
            if item == hovered:
                hover_index.normal[cid] = normal


class HoverIndex:
    """Canvas items of each hoverable document item, as drawn by one full redraw (see draw_items).

    Recording is two list appends per canvas item; the item -> canvas ids map is built on first use.
    `normal` holds the un-hovered color of canvas items currently drawn in the hover color."""
    __slots__ = ("items", "cids", "normal", "_map")

    def __init__(self):
        self.items, self.cids, self.normal, self._map = [], [], {}, None

    def canvas_ids(self, item):
        if self._map is None:
            m = {}
            for it, cid in zip(self.items, self.cids):
                m.setdefault(it, []).append(cid)
            self._map = m
        return self._map.get(item, ())


def recolor(cv: tk.Canvas, cid, color):
    """Set the drawing color of one canvas item drawn by draw_items, exactly as draw_items would have
    drawn it in `color`: lines and text use `fill`; polygons and ovals use `outline`, and `fill` when they
    are filled (an empty option means "not drawn" and stays empty). Returns the previous color."""
    if cv.type(cid) in ("line", "text"):
        old = cv.itemcget(cid, "fill")
        cv.itemconfigure(cid, fill=color)
        return old
    outline, fill = cv.itemcget(cid, "outline"), cv.itemcget(cid, "fill")
    kw = {}
    if outline:
        kw["outline"] = color
    if fill:
        kw["fill"] = color
    cv.itemconfigure(cid, **kw)
    return outline or fill


# ================================================================ base view
class DrawingView(tk.Canvas):
    def __init__(self, master, **kw):
        super().__init__(master, highlightthickness=0, borderwidth=0, **kw)
        self.zoom = 1.0
        self.ox = self.oy = 0.0
        self.font_family = "Helvetica"
        self.pan_from = None
        self._redraw_pending = False
        self.bind("<ButtonPress-2>", self._pan_start)
        self.bind("<B2-Motion>", self._pan_move)
        self.bind("<ButtonRelease-2>", self._pan_end)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda e: self._wheel_steps(e, 1))
        self.bind("<Button-5>", lambda e: self._wheel_steps(e, -1))

    def to_screen(self, p):
        return ((p[0] - self.ox) * self.zoom, (p[1] - self.oy) * self.zoom)

    def to_world(self, x, y):
        return (x / self.zoom + self.ox, y / self.zoom + self.oy)

    def set_zoom(self, z, anchor=None):
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        if anchor is None:
            anchor = (self.winfo_width() / 2, self.winfo_height() / 2)
        wx, wy = self.to_world(*anchor)
        self.zoom = z
        self.ox, self.oy = wx - anchor[0] / z, wy - anchor[1] / z
        self.redraw()
        self.view_changed()

    def zoom_by(self, f, anchor=None):
        self.set_zoom(self.zoom * f, anchor)

    def fit_box(self, box, margin=30):
        w = max(self.winfo_width(), 200)
        h = max(self.winfo_height(), 200)
        bw, bh = max(box[2] - box[0], 20), max(box[3] - box[1], 20)
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, min((w - 2 * margin) / bw, (h - 2 * margin) / bh)))
        self.ox = (box[0] + box[2]) / 2 - w / 2 / self.zoom
        self.oy = (box[1] + box[3]) / 2 - h / 2 / self.zoom
        self.redraw()
        self.view_changed()

    def center_on(self, p, zoom=None):
        if zoom:
            self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        self.ox = p[0] - self.winfo_width() / 2 / self.zoom
        self.oy = p[1] - self.winfo_height() / 2 / self.zoom
        self.redraw()
        self.view_changed()

    def view_changed(self):
        pass

    def redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.after_idle(self._redraw_now)

    def _redraw_now(self):
        self._redraw_pending = False

    def _pan_start(self, e):
        self.pan_from = (e.x, e.y, self.ox, self.oy)
        self.configure(cursor="fleur")

    def _pan_move(self, e):
        if self.pan_from:
            x, y, ox, oy = self.pan_from
            self.ox = ox - (e.x - x) / self.zoom
            self.oy = oy - (e.y - y) / self.zoom
            self.redraw()

    def _pan_end(self, _e):
        self.pan_from = None
        self.configure(cursor=self.default_cursor())
        self.view_changed()

    def default_cursor(self):
        return ""

    def pan(self, dx_px, dy_px):
        self.ox += dx_px / self.zoom
        self.oy += dy_px / self.zoom
        self.redraw()
        self.view_changed()

    def _on_wheel(self, e):
        self._wheel_steps(e, 1 if e.delta > 0 else -1)

    def _wheel_steps(self, e, steps):
        if e.state & 0x0001:
            self.pan(-steps * 60, 0)
        elif e.state & 0x0004:
            self.pan(0, -steps * 60)
        else:
            self.zoom_by(1.2 if steps > 0 else 1 / 1.2, (e.x, e.y))

    def draw_paper(self, colors, W, H):
        x0, y0 = self.to_screen((0, 0))
        x1, y1 = self.to_screen((W, H))
        self.create_rectangle(x0 + 3, y0 + 3, x1 + 3, y1 + 3, fill=colors["paper_shadow"], outline="")
        self.create_rectangle(x0, y0, x1, y1, fill=colors["paper"], outline=colors["frame"])


class PreviewView(DrawingView):
    """Read-only view of a sheet (revision viewer / comparison)."""

    def __init__(self, master, theme, **kw):
        super().__init__(master, **kw)
        self.theme = theme
        self.doc = None
        self.project = None
        self.items_fn = None      # fn() -> list of (items, color_fn)
        self._fitted = False
        self.bind("<Configure>", lambda e: self.redraw() if self._fitted else self.after_idle(self.fit))

    def show(self, doc, project=None, items_fn=None, fit=True):
        self.doc, self.project, self.items_fn = doc, project, items_fn
        if fit:
            self.fit()
        else:
            self.redraw()

    def fit(self):
        if self.doc is None:
            return
        self._fitted = True
        W, H = self.doc.sheet.size_units()
        self.fit_box((0, 0, W, H))

    def _redraw_now(self):
        self._redraw_pending = False
        self.delete("all")
        c = self.theme
        self.configure(bg=c["desk"])
        if self.doc is None:
            return
        W, H = self.doc.sheet.size_units()
        self.draw_paper(c, W, H)
        if self.items_fn:
            for items, color_fn in self.items_fn():
                draw_items(self, items, self.to_screen, self.zoom, c, self.font_family, color_fn=color_fn)
        else:
            draw_items(self, scene(self.doc, screen=False, project=self.project), self.to_screen, self.zoom, c,
                       self.font_family)


# ================================================================ editor
class SchematicCanvas(DrawingView):
    def __init__(self, master, app, **kw):
        super().__init__(master, takefocus=1, **kw)
        self.app = app
        self.tool = "select"
        self.place_symbol = None
        self.place_rot = 0
        self.place_mirror = False
        self.place_params = None
        self.place_template = None   # template dict while placing a template
        self.wire_pts = None
        self.wire_hfirst = True
        self.cursor = (0.0, 0.0)
        self.raw_cursor = (0.0, 0.0)
        self.snap_kind = None        # object-snap marker kind at the cursor
        self.drag = None
        self.hover = None
        self.request = None          # current interactive request
        self._fitted = False
        self._scene_cache = None
        # hover highlighting without redraws: canvas items per document item (rebuilt by every full
        # redraw) and the item currently drawn highlighted
        self._hover_index = HoverIndex()
        self._hover_shown = None
        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double)
        self.bind("<ButtonPress-3>", self._on_right)
        self.bind("<Leave>", self._on_leave)

    # ---------------------------------------------------------------- helpers
    @property
    def doc(self) -> Document:
        return self.app.doc

    @property
    def colors(self):
        return self.app.theme

    def default_cursor(self):
        return "crosshair" if self.tool != "select" or self.request is not None else ""

    def view_changed(self):
        self.app.update_zoom_label()

    def fit(self, box=None, margin=30):
        if box is None:
            W, H = self.doc.sheet.size_units()
            box = (0, 0, W, H)
        self.fit_box(box, margin)

    def fit_drawing(self):
        b = self.doc.bbox()
        if b is None:
            self.fit()
        else:
            self.fit((b[0] - 40, b[1] - 40, b[2] + 40, b[3] + 40))

    def _on_configure(self, e):
        if not self._fitted and e.width > 50:
            self._fitted = True
            self.fit()
        else:
            self.redraw()

    def selectable(self, o) -> bool:
        return self.app.is_selectable(o)

    # ---------------------------------------------------------------- drawing
    def invalidate(self):
        self._scene_cache = None
        self.redraw()

    def _redraw_now(self):
        self._redraw_pending = False
        c = self.colors
        doc = self.doc
        self.delete("all")
        self.configure(bg=c["desk"])
        W, H = doc.sheet.size_units()
        self.draw_paper(c, W, H)
        if self.app.settings["show_grid"]:
            self._draw_grid(W, H)
        conn = analyse(doc)
        self.app.update_connection_status(conn)
        items = scene(doc, screen=self.app.settings["show_markers"], conn=conn, project=self.app.project)
        hovered = self.hover if self.tool == "select" and self.request is None else None
        self._hover_index = HoverIndex()
        draw_items(self, items, self.to_screen, self.zoom, c, self.font_family, selected=self.app.selection,
                   hovered=hovered, hover_index=self._hover_index)
        self._hover_shown = hovered
        for i in self.app.selection:
            o = doc.item(i)
            if isinstance(o, Component):
                b = o.bbox()
                a, bb = self.to_screen((b[0] - 3, b[1] - 3)), self.to_screen((b[2] + 3, b[3] + 3))
                self.create_rectangle(*a, *bb, outline=c["select"], dash=(3, 3))
        self._draw_grips()
        self._draw_overlay()

    def _draw_grid(self, W, H):
        c = self.colors
        step = max(1, self.app.settings["grid_step"])
        while step * self.zoom < 8:
            step *= 5 if str(step)[0] in "12" else 2
        major = step * 5
        vw, vh = self.winfo_width(), self.winfo_height()
        wx0, wy0 = self.to_world(0, 0)
        wx1, wy1 = self.to_world(vw, vh)
        gx0, gy0 = max(0, snap(wx0, step) - step), max(0, snap(wy0, step) - step)
        gx1, gy1 = min(W, wx1 + step), min(H, wy1 + step)
        sy0, sy1 = self.to_screen((0, max(0, wy0)))[1], self.to_screen((0, min(H, wy1)))[1]
        sx0, sx1 = self.to_screen((max(0, wx0), 0))[0], self.to_screen((min(W, wx1), 0))[0]
        x = gx0
        while x <= gx1:
            sx = self.to_screen((x, 0))[0]
            self.create_line(sx, sy0, sx, sy1, fill=c["grid_major"] if abs(x % major) < 1e-6 else c["grid"])
            x += step
        y = gy0
        while y <= gy1:
            sy = self.to_screen((0, y))[1]
            self.create_line(sx0, sy, sx1, sy, fill=c["grid_major"] if abs(y % major) < 1e-6 else c["grid"])
            y += step

    def _draw_grips(self):
        from ..shapes import snap_points
        c = self.colors
        n = 0
        for i in self.app.selection:
            s = self.doc.shapes.get(i)
            if s is None:
                continue
            for kind, p in snap_points(s):
                if kind in ("end", "center", "node"):
                    x, y = self.to_screen(p)
                    self.create_rectangle(x - 3, y - 3, x + 3, y + 3, fill=c["paper"], outline=c["select"],
                                          tags="grip")
                    n += 1
                    if n > 400:
                        return

    def _draw_overlay(self):
        c = self.colors
        self.delete("overlay")
        t = "overlay"
        if self.tool == "place" and self.place_symbol:
            comp = Component(0, self.place_symbol, self.cursor[0], self.cursor[1], self.place_rot, self.place_mirror,
                             params=self.place_params or {})
            draw_items(self, [p for p in component_prims(comp, item=False)], self.to_screen, self.zoom, c,
                       self.font_family, override=c["ghost"], tag=t)
        if self.tool == "template" and self.place_template is not None:
            draw_items(self, self._template_items(), self.to_screen, self.zoom, c, self.font_family,
                       override=c["ghost"], tag=t)
        if self.tool == "wire":
            x, y = self.to_screen(self.cursor)
            self.create_line(x - 8, y, x + 8, y, fill=c["ghost"], tags=t)
            self.create_line(x, y - 8, x, y + 8, fill=c["ghost"], tags=t)
            if self.wire_pts:
                pts = self.wire_pts + elbow(self.wire_pts[-1], self.cursor, self.wire_hfirst)[1:]
                flat = [v for p in pts for v in self.to_screen(p)]
                if len(flat) >= 4:
                    self.create_line(*flat, fill=c["ghost"], width=max(1, 1.4 * self.zoom),
                                     dash=(6, 3) if self.app.wire_style == "dashed" else None, tags=t)
        r = self.request
        if r is not None:
            base = getattr(r, "base", None)
            if base is not None and isinstance(r, (ia.GetPoint, ia.GetDistance, ia.GetAngle)):
                a, b = self.to_screen(base), self.to_screen(self.cursor)
                self.create_line(*a, *b, fill=c["ghost"], dash=(4, 3), tags=t)
            prev = getattr(r, "preview", None)
            if prev is not None:
                try:
                    items = prev(self.cursor) or []
                except Exception:  # noqa: BLE001 - previews must never break the editor
                    items = []
                draw_items(self, items, self.to_screen, self.zoom, c, self.font_family, override=c["ghost"], tag=t)
            x, y = self.to_screen(self.cursor)
            if isinstance(r, (ia.GetPoint, ia.GetDistance, ia.GetAngle)):
                self.create_line(x - 12, y, x + 12, y, fill=c["crosshair"], tags=t)
                self.create_line(x, y - 12, x, y + 12, fill=c["crosshair"], tags=t)
            else:
                self.create_rectangle(x - 4, y - 4, x + 4, y + 4, outline=c["crosshair"], tags=t)
        if self.snap_kind and (r is not None and isinstance(r, (ia.GetPoint, ia.GetDistance, ia.GetAngle))):
            self._draw_snap_marker(self.snap_kind, self.cursor)
        hov = self._terminal_near(self.raw_cursor) if self.tool == "wire" else None
        if hov:
            x, y = self.to_screen(hov[2])
            self.create_oval(x - 5, y - 5, x + 5, y + 5, outline=c["hover"], width=2, tags=t)
        if self.drag and self.drag["kind"] == "band":
            a = self.to_screen(self.drag["start"])
            b = self.to_screen(self.raw_cursor)
            crossing = b[0] < a[0]
            col = c["band_cross"] if crossing else c["band"]
            self.create_rectangle(*a, *b, outline=col, dash=(4, 2) if crossing else None, tags=t)

    def _draw_snap_marker(self, kind, p):
        c = self.colors
        x, y = self.to_screen(p)
        s = 6
        col = c["snap"]
        if kind in ("end", "terminal", "node"):
            self.create_rectangle(x - s, y - s, x + s, y + s, outline=col, width=2, tags="overlay")
        elif kind == "mid":
            self.create_polygon(x, y - s, x + s, y + s, x - s, y + s, outline=col, fill="", width=2, tags="overlay")
        elif kind == "center":
            self.create_oval(x - s, y - s, x + s, y + s, outline=col, width=2, tags="overlay")
        elif kind == "quad":
            self.create_polygon(x, y - s, x + s, y, x, y + s, x - s, y, outline=col, fill="", width=2, tags="overlay")
        elif kind == "int":
            self.create_line(x - s, y - s, x + s, y + s, fill=col, width=2, tags="overlay")
            self.create_line(x - s, y + s, x + s, y - s, fill=col, width=2, tags="overlay")
        elif kind == "grid":
            pass

    def _template_items(self):
        from .. import templates
        d = templates.preview_document(self.place_template)
        from ..shapes import move_shape
        dx, dy = snap(self.cursor[0]), snap(self.cursor[1])
        editing.move_items(d, list(d.components), list(d.wires), dx, dy, list(d.shapes))
        _ = move_shape
        return scene(d, screen=False, frame=False)

    # ---------------------------------------------------------------- snapping
    def _terminal_near(self, p):
        tol = TERM_SNAP_PX / self.zoom
        best = None
        for comp in self.doc.components.values():
            for name, tp in comp.terminals().items():
                d = abs(tp[0] - p[0]) + abs(tp[1] - p[1])
                if d <= tol and (best is None or d < best[0]):
                    best = (d, (comp.id, name), tp)
        return (best[1][0], best[1][1], best[2]) if best else None

    def _snap(self, p, terminals=True):
        if terminals:
            t = self._terminal_near(p)
            if t:
                return t[2]
        return (snap(p[0]), snap(p[1]))

    def object_snap(self, p):
        """Nearest object-snap point within OSNAP_PX: (kind, point) or None."""
        from ..shapes import intersections, snap_points
        tol = OSNAP_PX / self.zoom
        best = None

        def consider(kind, q, prio=0):
            nonlocal best
            d = math.hypot(q[0] - p[0], q[1] - p[1])
            if d <= tol and (best is None or (d - prio) < best[0]):
                best = (d - prio, kind, q)
        for comp in self.doc.components.values():
            for _n, tp in comp.terminals().items():
                consider("terminal", tp, 0.5)
        for w in self.doc.wires.values():
            consider("end", w.points[0])
            consider("end", w.points[-1])
            for q in w.points[1:-1]:
                consider("end", q)
        near = []
        for s in self.doc.shapes.values():
            b = s.bbox()
            if b and b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol:
                near.append(s)
                for kind, q in snap_points(s):
                    consider(kind, q, 0.2 if kind == "end" else 0)
        if len(near) <= 30:
            for i, a in enumerate(near):
                for b in near[i + 1:]:
                    for q in intersections(a, b):
                        consider("int", q, 0.3)
        return (best[1], best[2]) if best else None

    def resolve_point(self, raw, base=None, snap_grid=None, osnap=None):
        """Apply object snap, ortho and grid snap to a raw world point."""
        st = self.app.settings
        self.snap_kind = None
        if st["osnap"] and osnap is not False:
            hit = self.object_snap(raw)
            if hit:
                self.snap_kind = hit[0]
                return hit[1]
        p = raw
        if base is not None and st["ortho"]:
            if abs(p[0] - base[0]) >= abs(p[1] - base[1]):
                p = (p[0], base[1])
            else:
                p = (base[0], p[1])
        use_grid = st["snap_grid"] if snap_grid is None else snap_grid
        if use_grid:
            step = max(1, st["grid_step"])
            if base is not None and st["ortho"]:
                if p[1] == base[1]:
                    p = (snap(p[0], step), p[1])
                else:
                    p = (p[0], snap(p[1], step))
            else:
                p = (snap(p[0], step), snap(p[1], step))
        return p

    def _event_world(self, e):
        return self.to_world(e.x, e.y)

    # ---------------------------------------------------------------- tools
    def set_tool(self, tool, symbol=None, params=None, template=None):
        if self.app.runner.active and tool != "command":
            self.app.runner.cancel()
        self.cancel_wire()
        self.tool = tool
        self.place_symbol = symbol if tool == "place" else None
        self.place_params = params
        self.place_template = template if tool == "template" else None
        if tool == "place":
            self.place_rot, self.place_mirror = 0, False
        self.configure(cursor=self.default_cursor())
        self.app.on_tool_changed(tool)
        self.redraw()

    def on_request(self, req):
        """Called by the command runner when the current request changes."""
        self.request = req
        if req is not None and self.tool != "command":
            self.cancel_wire()
            self.tool = "command"
            self.app.on_tool_changed("command")
        elif req is None and self.tool == "command":
            self.tool = "select"
            self.app.on_tool_changed("select")
        self.configure(cursor=self.default_cursor())
        self.redraw()

    def cancel_wire(self):
        self.wire_pts = None

    def escape(self):
        if self.app.runner.active:
            self.app.runner.cancel()
        elif self.tool == "wire" and self.wire_pts:
            self.cancel_wire()
            self.app.set_status("Wire cancelled.")
            self.redraw()
        elif self.tool != "select":
            self.set_tool("select")
        elif self.app.selection:
            self.app.set_selection(set())

    def rotate_ghost(self, cw=True):
        self.place_rot = (self.place_rot + (90 if cw else 270)) % 360
        self._draw_overlay()

    def mirror_ghost(self):
        self.place_mirror = not self.place_mirror
        self._draw_overlay()

    def toggle_bend(self):
        self.wire_hfirst = not self.wire_hfirst
        self._draw_overlay()

    def finish_wire(self):
        if self.wire_pts and len(self.wire_pts) >= 2:
            s = self.app.begin_change()
            w = editing.add_wire(self.doc, self.wire_pts, style=self.app.wire_style)
            if w:
                w.layer = self.app.layer_for("wire")
                self.app.commit_change(s, "Wire added.")
        self.wire_pts = None
        self.redraw()

    # ---------------------------------------------------------------- events
    def _set_hover(self, h):
        """Change the hovered item. Only the colors of the canvas items of the previously and newly
        hovered objects change, so no connectivity, scene or canvas rebuild is needed. If a full redraw is
        already pending it draws the new state itself."""
        if h == self.hover:
            return
        self.hover = h
        if self._redraw_pending:
            return
        shown = self._hover_shown
        if h == shown:
            return
        index = self._hover_index
        if shown is not None:
            for cid in index.canvas_ids(shown):
                normal = index.normal.pop(cid, None)
                if normal is not None:
                    recolor(self, cid, normal)
        if h is not None:
            hov = self.colors["hover"]
            for cid in index.canvas_ids(h):
                index.normal[cid] = recolor(self, cid, hov)
        self._hover_shown = h

    def _on_leave(self, _e):
        self.app.show_cursor(None)
        self._set_hover(None)

    def _on_motion(self, e):
        self.raw_cursor = self._event_world(e)
        r = self.request
        if r is not None:
            if isinstance(r, (ia.GetPoint, ia.GetDistance, ia.GetAngle)):
                self.cursor = self.resolve_point(self.raw_cursor, getattr(r, "base", None),
                                                 getattr(r, "snap_grid", None), getattr(r, "osnap", None))
            else:
                self.cursor = self.raw_cursor
                self.snap_kind = None
            self.app.show_cursor(self.cursor)
            self._draw_overlay()
            return
        self.cursor = self._snap(self.raw_cursor, terminals=self.tool == "wire")
        self.app.show_cursor(self.cursor)
        if self.tool in ("wire", "place", "template"):
            self._draw_overlay()
        elif self.tool == "select" and not self.drag:
            h = editing.hit_test(self.doc, self.raw_cursor, PICK_PX / self.zoom, self.selectable)
            self._set_hover(h)

    def _on_press(self, e):
        self.focus_set()
        p = self._event_world(e)
        self.raw_cursor = p
        doc = self.doc
        r = self.request
        if r is not None:
            self._request_click(e, p)
            return
        if self.tool == "place":
            if self.place_symbol:
                s = self.app.begin_change()
                comp = editing.place(doc, self.place_symbol, *self._snap(p, False), self.place_rot, self.place_mirror,
                                     params=self.place_params, layer=self.app.layer_for("component"))
                des = getattr(self.app, "_pending_designator", None)
                if des:
                    comp.designator = des
                    self.app._pending_designator = None
                sd = symbols.get(comp.symbol)
                self.app.note_symbol_used(comp.symbol)
                self.app.commit_change(s, f"Placed {comp.tag() if comp.designator else sd.name}. "
                                          "Click to place another, R rotate, M mirror, Esc to finish.")
            return
        if self.tool == "template":
            if self.place_template is not None:
                from .. import templates
                s = self.app.begin_change()
                ids = templates.insert(doc, self.place_template, *self._snap(p, False))
                self.app.selection = set(ids)
                self.app.commit_change(s, f"Inserted template “{self.place_template['name']}”.")
                self.set_tool("select")
            return
        if self.tool == "wire":
            pt = self._snap(p)
            if self.wire_pts is None:
                self.wire_pts = [pt]
                t = self._terminal_near(p)
                if t:
                    d = doc.components[t[0]].terminal_dirs().get(t[1], "r")
                    self.wire_hfirst = d in ("l", "r")
                self.app.set_status("Click to add bends; click a terminal or wire, double-click or Enter to "
                                    "finish. Space flips the bend.")
            else:
                last = self.wire_pts[-1]
                if same(last, pt):
                    return
                self.wire_pts += elbow(last, pt, self.wire_hfirst)[1:]
                self.wire_pts = simplify_orthogonal(self.wire_pts)
                if self._ends_on_something(pt):
                    self.finish_wire()
                    return
            self._draw_overlay()
            return
        # select tool
        tol = PICK_PX / self.zoom
        hit = editing.hit_test(doc, p, tol, self.selectable)
        shift = bool(e.state & 0x0001)
        ctrl = bool(e.state & 0x0004)
        sel = set(self.app.selection)
        if hit is None:
            if not (shift or ctrl):
                self.app.set_selection(set())
            self.drag = {"kind": "band", "start": p, "add": shift or ctrl}
            return
        group = editing.expand_groups(doc, {hit})
        if ctrl or shift:
            sel = sel - group if hit in sel else sel | group
            self.app.set_selection(sel)
            return
        if hit not in sel:
            sel = group
            self.app.set_selection(sel)
        snapshot = self.app.begin_change()
        w = doc.wires.get(hit)
        if w and len(sel) == 1:
            for which, idx in (("start", 0), ("end", -1)):
                if abs(w.points[idx][0] - p[0]) <= tol and abs(w.points[idx][1] - p[1]) <= tol:
                    self.drag = {"kind": "endpoint", "wire": hit, "which": which, "base": list(w.points),
                                 "snap": snapshot, "moved": False}
                    return
            seg = editing.segment_at(w, p, tol)
            if seg is not None:
                self.drag = {"kind": "segment", "wire": hit, "seg": seg, "base": list(w.points), "start": p,
                             "snap": snapshot, "moved": False}
                return
        self.drag = {"kind": "move", "start": (snap(p[0]), snap(p[1])), "applied": (0.0, 0.0), "snap": snapshot,
                     "moved": False}

    def _request_click(self, e, p):
        r = self.request
        runner = self.app.runner
        if isinstance(r, (ia.GetPoint, ia.GetDistance, ia.GetAngle)):
            q = self.resolve_point(p, getattr(r, "base", None), getattr(r, "snap_grid", None),
                                   getattr(r, "osnap", None))
            runner.answer(q)
        elif isinstance(r, ia.GetSelection):
            hit = editing.hit_test(self.doc, p, PICK_PX / self.zoom, self.selectable)
            if hit is None:
                self.drag = {"kind": "band", "start": p, "add": True}
                return
            sel = set(self.app.selection)
            group = editing.expand_groups(self.doc, {hit})
            sel = sel - group if (hit in sel and e.state & 0x0001) else sel | group
            self.app.set_selection(sel)
        elif isinstance(r, ia.GetObject):
            hit = editing.hit_test(self.doc, p, PICK_PX / self.zoom,
                                   lambda o: self.selectable(o) and (r.accept is None or r.accept(o)))
            runner.answer((hit, p) if r.want_point else hit)
        else:
            pass

    def _ends_on_something(self, pt):
        if self._terminal_near(pt):
            return True
        for w in self.doc.wires.values():
            if any(point_on_segment(pt, a, b) for a, b in zip(w.points, w.points[1:])):
                return True
        return len(self.wire_pts) > 2 and same(pt, self.wire_pts[0])

    def _on_drag(self, e):
        if self.pan_from:
            return
        p = self._event_world(e)
        self.raw_cursor = p
        self.app.show_cursor(self._snap(p, False))
        d = self.drag
        if not d:
            if self.tool == "wire" or self.request is not None:
                self._on_motion(e)
            return
        doc = self.doc
        if d["kind"] == "band":
            self._draw_overlay()
            return
        if d["kind"] == "move":
            sx, sy = snap(p[0]), snap(p[1])
            tx, ty = sx - d["start"][0], sy - d["start"][1]
            ax, ay = d["applied"]
            if (tx, ty) != (ax, ay):
                movable = [i for i in self.app.selection if not getattr(doc.item(i), "locked", False)]
                comps, wires, shapes = editing.split_ids(doc, movable)
                editing.move_items(doc, comps, wires, tx - ax, ty - ay, shapes)
                d["applied"] = (tx, ty)
                d["moved"] = True
                self.redraw()
        elif d["kind"] == "segment":
            w = doc.wires.get(d["wire"])
            if w is None or w.locked:
                return
            a, b = d["base"][d["seg"]], d["base"][d["seg"] + 1]
            horiz = abs(a[1] - b[1]) < 0.01
            delta = (snap(p[1]) - snap(d["start"][1])) if horiz else (snap(p[0]) - snap(d["start"][0]))
            pts, _ = editing.drag_segment(d["base"], d["seg"], delta)
            w.points = pts
            d["moved"] = delta != 0
            self.redraw()
        elif d["kind"] == "endpoint":
            w = doc.wires.get(d["wire"])
            if w is None or w.locked:
                return
            q = self._snap(p)
            w.points = editing.set_endpoint(d["base"], d["which"], q)
            d["moved"] = True
            self.redraw()

    def _on_release(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        doc = self.doc
        if d["kind"] == "band":
            a, b = d["start"], self._event_world(e)
            r = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            if r[2] - r[0] > 1 or r[3] - r[1] > 1:
                crossing = b[0] < a[0]
                found = editing.expand_groups(doc, editing.items_in_rect(doc, r, self.selectable, crossing))
                self.app.set_selection((set(self.app.selection) | found) if d["add"] else found)
            self.redraw()
            return
        if not d.get("moved"):
            self.app.cancel_change(d["snap"])
            return
        if d["kind"] in ("segment", "endpoint"):
            w = doc.wires.get(d["wire"])
            if w:
                w.points = simplify_orthogonal(w.points)
                w.auto = False
                if d["kind"] == "endpoint":
                    ref = editing.find_terminal_at(doc, w.points[0 if d["which"] == "start" else -1])
                    setattr(w, d["which"], ref)
                if len(w.points) == 2 and same(w.points[0], w.points[1]):
                    editing.delete_items(doc, [w.id])
                    self.app.selection.discard(w.id)
        self.app.commit_change(d["snap"], "Moved.")

    def _on_double(self, e):
        if self.request is not None:
            return
        if self.tool == "wire":
            self.finish_wire()
        elif self.tool == "select":
            hit = editing.hit_test(self.doc, self._event_world(e), PICK_PX / self.zoom, self.selectable)
            if hit in self.doc.components:
                c = self.doc.components[hit]
                sd = symbols.get(c.symbol)
                if sd is not None and sd.parametric:
                    self.app.configure_valve(hit)
                else:
                    self.app.focus_properties()
            elif hit in self.doc.shapes and self.doc.shapes[hit].kind == "text":
                self.app.edit_text_shape(hit)

    def _on_right(self, e):
        if self.request is not None:
            self.app.runner.enter()
            return
        if self.tool == "wire":
            if self.wire_pts:
                self.finish_wire()
            else:
                self.set_tool("select")
            return
        if self.tool in ("place", "template"):
            self.set_tool("select")
            return
        p = self._event_world(e)
        hit = editing.hit_test(self.doc, p, PICK_PX / self.zoom, self.selectable)
        if hit is not None and hit not in self.app.selection:
            self.app.set_selection(editing.expand_groups(self.doc, {hit}))
        self.app.show_context_menu(e.x_root, e.y_root, p, hit)
