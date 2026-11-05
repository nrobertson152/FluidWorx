"""Scene builder: converts a sheet into a flat list of world-space drawing
primitives. The Tk canvas, SVG/PDF/DXF exporters all draw from this same
list, so what is printed matches what is on screen.

Scene item keys: as symbol primitives (see symbols/base.py) plus
    "role": ink | wire | frame | text | designator | junction | open_end |
            open_term | shape | wirenum | xref | pin
    "item": owning component/wire/shape id (or None)
    "wpx":  line width in drawing units
    "layer": layer name (optional), "color": explicit colour (optional)
"""
from __future__ import annotations

from .connectivity import Connectivity, analyse
from .geometry import arc_points, same
from .model import Component, Document
from .symbols import LINE_WIDTHS

TEXT_SIZE = 10        # 2.5 mm
SMALL_TEXT = 7
PIN_TEXT = 6
WIRE_WIDTH = LINE_WIDTHS["normal"]
JUNCTION_SIZES = {"small": 1.8, "medium": 2.2, "large": 3.0}   # radius in units
JUNCTION_R = JUNCTION_SIZES["medium"]
HOP_R = 4.0           # 1 mm bridge radius
CROSSING_STYLES = {"bridge": "Bridge (line jump)", "gap": "Gap in the crossing wire", "plain": "Plain crossing"}
SCREEN_ROLES = ("open_end", "open_term")


def _w(p):
    return LINE_WIDTHS.get(p.get("w", "normal"), LINE_WIDTHS["normal"])


def component_prims(c: Component, item=True, show_pins: bool = False):
    out = []
    g = c.geometry()
    cid = c.id if item else None
    for p in g.prims:
        k = p["k"]
        q = {"k": k, "role": "ink", "item": cid, "wpx": _w(p), "dash": p.get("dash", False), "layer": c.layer}
        if k in ("line", "poly"):
            q["pts"] = [c.local_to_world(x, y) for x, y in p["pts"]]
            q["fill"] = p.get("fill", False)
        elif k == "circle":
            q["c"] = c.local_to_world(*p["c"])
            q["r"] = p["r"]
            q["fill"] = p.get("fill", False)
        elif k == "text":
            # symbol text stays upright and readable under any transform
            anchor = p.get("anchor", "c")
            if anchor != "c":
                anchor = _xform_anchor(anchor, c.rotation, c.mirror)
            q.update(p=c.local_to_world(*p["p"]), s=p["s"], size=p.get("size", 8), anchor=anchor, role="ink")
        out.append(q)
    if item:
        if show_pins or c.terminal_labels:
            out += terminal_label_prims(c, only_overridden=not show_pins)
        out += component_text(c)
    return out


_ANCHOR_VEC = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0), "ne": (1, -1), "nw": (-1, -1),
               "se": (1, 1), "sw": (-1, 1)}


def _xform_anchor(anchor, rotation, mirror):
    """Transform a text anchor so text placed beside a pin stays beside it."""
    from .geometry import xform
    v = _ANCHOR_VEC.get(anchor)
    if not v:
        return anchor
    x, y = xform(v[0], v[1], rotation, mirror)
    x, y = round(x), round(y)
    for k, vv in _ANCHOR_VEC.items():
        if vv == (x, y):
            return k
    return anchor


def terminal_label_prims(c: Component, only_overridden=False):
    """Terminal designations of a placed component: the only place they are
    drawn, so each appears at most once. With `only_overridden` (project
    setting off) only user overrides are drawn; otherwise every terminal whose
    symbol definition allows it (custom pins can opt out) plus any override."""
    out = []
    dirs = c.terminal_dirs()
    shown = {t.name: t.show for t in c.terminal_defs()}
    for name, p in c.terminals().items():
        overridden = bool(c.terminal_labels.get(name))
        if not overridden and (only_overridden or not shown.get(name, True)):
            continue
        lab = c.terminal_label(name)
        if not lab:
            continue
        d = dirs.get(name, "r")
        # place the identifier beside the lead, just off the wire
        if d in ("l", "r"):
            pos, anchor = (p[0] + (6 if d == "l" else -6), p[1] - 2), ("sw" if d == "l" else "se")
        else:
            pos, anchor = (p[0] + 2, p[1] + (6 if d == "u" else -6)), ("nw" if d == "u" else "sw")
        out.append({"k": "text", "p": pos, "s": lab, "size": PIN_TEXT, "anchor": anchor, "role": "pin",
                    "item": c.id, "layer": c.layer})
    return out


def text_side(c: Component) -> str:
    if c.text_side != "auto":
        return c.text_side
    dirs = set(c.terminal_dirs().values())
    for side, d in (("right", "r"), ("above", "u"), ("left", "l"), ("below", "d")):
        if d not in dirs:
            return side
    return "right"


def component_text(c: Component, extra=()):
    from .project import is_terminal_symbol
    des = c.tag() if is_terminal_symbol(c.symbol) and c.designator else c.designator
    lines = [(t, role) for t, role in ((des, "designator"), (c.label, "text"), *extra) if t]
    if not lines:
        return []
    x1, y1, x2, y2 = c.bbox()
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = text_side(c)
    gap, lh = 4, TEXT_SIZE * 1.25
    out = []
    n = len(lines)
    for i, (t, role) in enumerate(lines):
        size = SMALL_TEXT if role == "xref" else TEXT_SIZE
        if side == "right":
            p, anchor = (x2 + gap, cy + (i - (n - 1) / 2) * lh), "w"
        elif side == "left":
            p, anchor = (x1 - gap, cy + (i - (n - 1) / 2) * lh), "e"
        elif side == "above":
            p, anchor = (cx, y1 - gap - (n - 1 - i) * lh), "s"
        else:
            p, anchor = (cx, y2 + gap + i * lh), "n"
        out.append({"k": "text", "p": p, "s": t, "size": size, "anchor": anchor, "role": role,
                    "item": c.id, "bold": role == "designator", "layer": c.layer})
    return out


def _hop_points(a, b, cross_ys, r):
    """Points for a vertical segment a->b with semicircular bridges at the
    given y values (bulging towards +x)."""
    down = b[1] > a[1]
    ys = sorted(cross_ys, reverse=not down)
    pts = [a]
    x = a[0]
    for y in ys:
        if down:
            pts.append((x, y - r))
            pts += arc_points(x, y, r, 90, -180, 10)[1:]
        else:
            pts.append((x, y + r))
            pts += arc_points(x, y, r, 270, 180, 10)[1:]
    pts.append(b)
    return pts


def wire_prims(doc: Document, crossing_style: str = "bridge", crossings=None):
    from .editing import crossings as find_crossings
    out = []
    bridges = {}
    if crossing_style in ("bridge", "gap"):
        for p, _wh, wv in (crossings if crossings is not None else find_crossings(doc)):
            bridges.setdefault(wv, []).append(p)
    for w in doc.wires.values():
        base = {"role": "wire", "item": w.id, "wpx": WIRE_WIDTH, "dash": w.style == "dashed", "fill": False,
                "layer": w.layer}
        hops = bridges.get(w.id)
        if not hops:
            out.append(dict(base, k="line", pts=list(w.points)))
            continue
        if crossing_style == "gap":
            pieces = [[w.points[0]]]
            for a, b in zip(w.points, w.points[1:]):
                ys = [p[1] for p in hops if abs(p[0] - a[0]) < 0.01 and abs(a[0] - b[0]) < 0.01
                      and min(a[1], b[1]) < p[1] < max(a[1], b[1])]
                down = b[1] > a[1]
                for y in sorted(ys, reverse=not down):
                    g = HOP_R if down else -HOP_R
                    pieces[-1].append((a[0], y - g))
                    pieces.append([(a[0], y + g)])
                pieces[-1].append(b)
            for pts in pieces:
                if len(pts) >= 2:
                    out.append(dict(base, k="line", pts=pts))
            continue
        pts = [w.points[0]]
        for a, b in zip(w.points, w.points[1:]):
            ys = [p[1] for p in hops if abs(a[0] - b[0]) < 0.01 and abs(p[0] - a[0]) < 0.01
                  and min(a[1], b[1]) < p[1] < max(a[1], b[1])]
            if ys:
                pts += _hop_points(a, b, ys, HOP_R)[1:]
            else:
                pts.append(b)
        out.append(dict(base, k="line", pts=pts))
    return out


def wire_number_prims(doc: Document):
    """Wire numbers, written once per wire beside its longest segment."""
    out = []
    for w in doc.wires.values():
        if not w.number:
            continue
        best = max(zip(w.points, w.points[1:]), key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
        (ax, ay), (bx, by) = best
        mx, my = (ax + bx) / 2, (ay + by) / 2
        if abs(ay - by) < 0.01:     # horizontal: text above the wire
            p, anchor = (mx, my - 2), "s"
        else:                       # vertical: text to the left
            p, anchor = (mx - 2, my), "e"
        out.append({"k": "text", "p": p, "s": w.number, "size": SMALL_TEXT, "anchor": anchor, "role": "wirenum",
                    "item": w.id, "layer": w.layer})
    return out


def frame_prims(doc: Document, project=None):
    from .titleblock import frame_prims as fp
    return fp(doc, project if project is not None else getattr(doc, "project", None))


def scene(doc: Document, screen: bool = True, conn: Connectivity | None = None, frame: bool = True,
          project=None, layer_filter=None):
    """Build the drawing primitives for one sheet.

    `project` supplies title-block metadata, layers, cross-references and
    display settings (defaults to the sheet's owning project). Hidden layers
    are always skipped; when printing (screen=False) non-printable layers are
    skipped too."""
    from .editing import crossings as find_crossings
    from .shapes import shape_prims
    project = project if project is not None else getattr(doc, "project", None)
    settings = project.settings if project is not None else {}
    conn = conn or analyse(doc)
    layers = {l.name: l for l in project.layers} if project is not None else {}

    def visible(layer):
        if layer_filter is not None and not layer_filter(layer):
            return False
        lay = layers.get(layer)
        if lay is None:
            return True
        return lay.visible and (screen or lay.printable)

    items = []
    if frame:
        items += frame_prims(doc, project)
    # boundary fills are drawn first so their boundary lines stay visible on top
    for s in sorted(doc.shapes.values(), key=lambda s: s.kind != "hatch"):
        if visible(s.layer):
            items += shape_prims(s, item=s.id)
    style = settings.get("crossing_style", "bridge")
    cross = find_crossings(doc)
    items += [it for it in wire_prims(doc, style, cross) if visible(it["layer"])]
    if settings.get("show_wire_numbers", True):
        items += [it for it in wire_number_prims(doc) if visible(it["layer"])]
    jr = JUNCTION_SIZES.get(settings.get("junction_size", "medium"), JUNCTION_R)
    for p in conn.junctions:
        items.append({"k": "circle", "c": p, "r": jr, "fill": True, "role": "junction", "item": None, "layer": "Wires",
                      "wpx": 0.5, "dash": False})
    show_pins = settings.get("show_terminal_labels", False)
    from .symbols.general import OFFPAGE_IDS
    for c in doc.components.values():
        if not visible(c.layer):
            continue
        prims = component_prims(c, show_pins=show_pins)
        if c.symbol in OFFPAGE_IDS and project is not None and doc in project.sheets:
            from .netlist import xref_targets
            fmt = settings.get("xref_format", "/{sheet}.{zone}")
            refs = [fmt.format(sheet=s, zone=z) for s, z in xref_targets(project, doc, c)]
            if refs:
                prims = [p for p in prims if p.get("role") not in ("designator", "text")] + \
                    component_text(c, extra=[(" ".join(refs), "xref")])
        items += prims
    for it in items:
        lay = layers.get(it.get("layer"))
        if lay is not None and lay.color and it.get("role") not in ("frame", "junction"):
            it["color"] = lay.color
    # Non-interactive drawing designation. Drawn after schematic geometry, before
    # screen-only connectivity markers; intentionally has no document item ID.
    if doc.sheet.drawing_status == "Preliminary" and frame:
        w, h = doc.sheet.size_units()
        items.extend([
            {"k": "text", "p": (w / 2, h * 0.46), "s": "PRELIMINARY",
             "size": min(w / 12, h / 5), "anchor": "c", "angle": 25,
             "bold": True, "role": "watermark", "item": None, "color": "#b8b8b8"},
            {"k": "text", "p": (w / 2, h * 0.59), "s": "NOT FOR PRODUCTION",
             "size": min(w / 36, h / 15), "anchor": "c", "angle": 25,
             "role": "watermark", "item": None, "color": "#b8b8b8"},
        ])
    if screen:
        for wid, p in conn.open_wire_ends:
            items.append({"k": "poly", "pts": [(p[0] - 2.5, p[1] - 2.5), (p[0] + 2.5, p[1] - 2.5),
                                                (p[0] + 2.5, p[1] + 2.5), (p[0] - 2.5, p[1] + 2.5)],
                          "fill": False, "role": "open_end", "item": None, "wpx": 1.0, "dash": False})
        for cid, name, p in conn.open_terminals:
            items.append({"k": "circle", "c": p, "r": 1.8, "fill": False, "role": "open_term", "item": None,
                          "wpx": 0.8, "dash": False})
    return items


def scene_bbox(items):
    from .geometry import bbox_union
    from .symbols.base import prim_bbox
    b = None
    for it in items:
        if it["k"] == "text":
            h = it.get("size", TEXT_SIZE)
            w = h * 0.6 * len(it["s"])
            x, y = it["p"]
            a = it.get("anchor", "c")
            lx = x - w / 2 if a in ("c", "n", "s") else (x - w if "e" in a else x)
            b = bbox_union(b, (lx, y - h, lx + w, y + h))
        else:
            b = bbox_union(b, prim_bbox(it))
    return b


__all__ = ["scene", "scene_bbox", "component_prims", "component_text", "wire_prims", "frame_prims", "same"]
