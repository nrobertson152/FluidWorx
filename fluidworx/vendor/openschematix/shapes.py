"""CAD geometry for free drafting shapes: bounding boxes, rendering
primitives, transforms (move/rotate/mirror/scale), hit testing, object
snap points, intersections, TRIM and EXTEND.

The same functions are used for shapes on a schematic sheet and for the
geometry of custom symbols in the symbol editor, so both behave
identically.

Angles are in degrees, counter-clockwise as seen on screen, 0 deg = +x.
Because world y points down, a point at angle a on a circle is
(cx + r cos a, cy - r sin a).
"""
from __future__ import annotations

import copy
import math
from typing import Iterable, Optional

from . import regions
from .geometry import Point, arc_points, bbox_of, bbox_union, clean, seg_distance
from .model import Shape, clean_bulge

EPS = 1e-7
LINE_W = {"thin": 1.0, "normal": 1.4, "thick": 2.2}


# ================================================================ basic helpers
def norm_angle(a: float) -> float:
    a = math.fmod(a, 360.0)
    return a + 360.0 if a < 0 else a


def angle_of(p: Point, c: Point) -> float:
    return norm_angle(math.degrees(math.atan2(-(p[1] - c[1]), p[0] - c[0])))


def point_at(c: Point, r: float, a: float) -> Point:
    t = math.radians(a)
    return (c[0] + r * math.cos(t), c[1] - r * math.sin(t))


def arc_norm(start: float, extent: float):
    """Return (start, extent) with extent > 0 (same arc)."""
    if extent < 0:
        start, extent = start + extent, -extent
    return norm_angle(start), min(extent, 360.0)


def angle_in_arc(a: float, start: float, extent: float, tol: float = 1e-6) -> bool:
    start, extent = arc_norm(start, extent)
    d = norm_angle(a - start)
    return d <= extent + tol or d >= 360 - tol


def arc_param(a: float, start: float, extent: float) -> float:
    """Position of angle a along the arc, 0..extent (extent > 0)."""
    return norm_angle(a - start)


def is_closed(s: Shape) -> bool:
    return s.kind in ("polygon", "rect", "circle")


def segments(s: Shape) -> list:
    """Straight segments of a segment-based shape (closing segment included)."""
    if s.kind in ("line", "polyline"):
        return list(zip(s.pts, s.pts[1:]))
    if s.kind in ("polygon", "rect"):
        return list(zip(s.pts, s.pts[1:] + s.pts[:1]))
    return []


# ================================================================ bbox / prims
def text_extent(s: Shape):
    w = s.size * 0.6 * max(1, len(s.s))
    h = s.size
    x, y = s.pts[0]
    a = s.anchor
    lx = x - w / 2 if a in ("c", "n", "s") else (x - w if "e" in a else x)
    ty = y - h / 2 if a in ("c", "e", "w") else (y - h if "s" in a else y)
    return (lx, ty, lx + w, ty + h)


def shape_bbox(s: Shape):
    if s.kind in ("line", "polyline", "polygon", "rect"):
        points = list(s.pts)
        if s.kind in ("line", "polyline") and len(points) >= 2:
            for start, enabled in ((True, s.arrow_start), (False, s.arrow_end)):
                if enabled:
                    neighbor = _endpoint_neighbor(s.pts, start)
                    if neighbor is not None:
                        tip = s.pts[0] if start else s.pts[-1]
                        points.extend(arrowhead_points(tip, neighbor, s.arrow_size))
        return bbox_of(points)
    if s.kind == "circle":
        return (s.c[0] - s.r, s.c[1] - s.r, s.c[0] + s.r, s.c[1] + s.r)
    if s.kind == "arc":
        st, ex = arc_norm(s.start, s.extent)
        pts = [point_at(s.c, s.r, st), point_at(s.c, s.r, st + ex)]
        for q in (0, 90, 180, 270):
            if angle_in_arc(q, st, ex):
                pts.append(point_at(s.c, s.r, q))
        return bbox_of(pts)
    if s.kind == "text":
        return text_extent(s)
    if s.kind == "hatch":
        return regions.rings_bbox(s.rings)
    return None


def arc_polyline(c, r, start, extent):
    steps = max(6, int(abs(extent) / 6))
    return arc_points(c[0], c[1], r, start, extent, steps)


def arrowhead_points(tip, adjacent, size):
    """Three vertices for a filled arrow pointing from adjacent toward tip.

    A zero-length endpoint segment has no defined direction.
    """
    dx, dy = tip[0] - adjacent[0], tip[1] - adjacent[1]
    length = math.hypot(dx, dy)
    if length <= EPS or size <= 0:
        return []
    ux, uy = dx / length, dy / length
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    half = size * 0.35
    return [tuple(tip), (bx - uy * half, by + ux * half),
            (bx + uy * half, by - ux * half)]


def _endpoint_neighbor(pts, start):
    """Find the first non-coincident vertex inward from an endpoint."""
    ordered = pts if start else list(reversed(pts))
    tip = ordered[0]
    for point in ordered[1:]:
        if math.dist(tip, point) > EPS:
            return point
    return None


def shape_prims(s: Shape, item=None, role="shape") -> list:
    """Render primitives (same format as render.scene items)."""
    w = LINE_W.get(s.width, 1.4)
    base = {"role": role, "item": item, "wpx": w, "dash": s.dash, "layer": s.layer}
    if s.kind in ("line", "polyline"):
        result = [dict(base, k="line", pts=list(s.pts), fill=False)]
        for start, enabled in ((True, s.arrow_start), (False, s.arrow_end)):
            if not enabled or len(s.pts) < 2:
                continue
            tip = s.pts[0] if start else s.pts[-1]
            neighbor = _endpoint_neighbor(s.pts, start)
            if neighbor is None:
                continue
            triangle = arrowhead_points(tip, neighbor, s.arrow_size)
            if triangle:
                result.append(dict(base, k="poly", pts=triangle, fill=True, dash=False))
        return result
    if s.kind in ("polygon", "rect"):
        return [dict(base, k="poly", pts=list(s.pts), fill=s.fill)]
    if s.kind == "circle":
        return [dict(base, k="circle", c=s.c, r=s.r, fill=s.fill)]
    if s.kind == "arc":
        return [dict(base, k="line", pts=arc_polyline(s.c, s.r, s.start, s.extent), fill=False)]
    if s.kind == "text":
        return [dict(base, k="text", p=s.pts[0], s=s.s, size=s.size, anchor=s.anchor, angle=s.angle)]
    if s.kind == "hatch":
        # solid fill: no outline, no dash; exact rings (arcs as bulges)
        return [dict(base, k="region", rings=[list(r) for r in s.rings], fill=True, dash=False, wpx=0.0)]
    return []


# ================================================================ transforms
def _map_points(s: Shape, fn):
    if s.kind in ("line", "polyline", "polygon", "rect", "text"):
        s.pts = [tuple(clean(v) for v in fn(p)) for p in s.pts]
    if s.kind in ("circle", "arc"):
        s.c = tuple(clean(v) for v in fn(s.c))
    if s.kind == "hatch":
        s.rings = [[(clean(q[0]), clean(q[1]), b) for q, b in ((fn((x, y)), b) for x, y, b in ring)]
                   for ring in s.rings]


def move_shape(s: Shape, dx: float, dy: float):
    _map_points(s, lambda p: (p[0] + dx, p[1] + dy))


def rotate_point(p: Point, center: Point, deg_cw: float) -> Point:
    """Rotate clockwise as seen on screen (y down)."""
    t = math.radians(deg_cw)
    x, y = p[0] - center[0], p[1] - center[1]
    co, si = math.cos(t), math.sin(t)
    if abs(deg_cw % 90) < 1e-9:  # exact quarter turns
        co, si = round(co), round(si)
    return (center[0] + x * co - y * si, center[1] + x * si + y * co)


def rotate_shape(s: Shape, center: Point, deg_cw: float):
    _map_points(s, lambda p: rotate_point(p, center, deg_cw))
    if s.kind == "arc":
        s.start = clean(norm_angle(s.start - deg_cw))
    if s.kind == "text":
        s.angle = clean(norm_angle(s.angle - deg_cw))
        if s.angle in (0.0, 360.0):
            s.angle = 0.0


def mirror_shape(s: Shape, axis_p: Point, axis_q: Point):
    """Mirror about the line through axis_p and axis_q."""
    dx, dy = axis_q[0] - axis_p[0], axis_q[1] - axis_p[1]
    d2 = dx * dx + dy * dy
    if d2 < EPS:
        return

    def m(p):
        t = ((p[0] - axis_p[0]) * dx + (p[1] - axis_p[1]) * dy) / d2
        fx, fy = axis_p[0] + t * dx, axis_p[1] + t * dy
        return (2 * fx - p[0], 2 * fy - p[1])
    _map_points(s, m)
    if s.kind == "hatch":      # a reflection reverses the turning direction of every arc
        s.rings = [[(x, y, clean_bulge(-b)) for x, y, b in ring] for ring in s.rings]
    axis_ang = angle_of(axis_q, axis_p)
    if s.kind == "arc":
        st, ex = arc_norm(s.start, s.extent)
        end = st + ex
        s.start = clean(norm_angle(2 * axis_ang - end))
        s.extent = clean(ex)
    if s.kind == "text":
        # Text stays readable: its position is mirrored, its glyphs are not.
        s.anchor = {"w": "e", "e": "w", "nw": "ne", "ne": "nw", "sw": "se", "se": "sw"}.get(s.anchor, s.anchor) \
            if abs(dx) < EPS else s.anchor


def scale_shape(s: Shape, center: Point, k: float):
    _map_points(s, lambda p: (center[0] + (p[0] - center[0]) * k, center[1] + (p[1] - center[1]) * k))
    if s.kind in ("circle", "arc"):
        s.r = clean(s.r * abs(k))
    if s.kind == "text":
        s.size = clean(s.size * abs(k))
    if s.kind in ("line", "polyline"):
        s.arrow_size = clean(s.arrow_size * abs(k))


# ================================================================ hit testing
def shape_distance(s: Shape, p: Point) -> float:
    if s.kind in ("line", "polyline", "polygon", "rect"):
        d = min((seg_distance(p, a, b) for a, b in segments(s)), default=1e9)
        if s.fill and s.kind in ("polygon", "rect") and point_in_polygon(p, s.pts):
            return 0.0
        return d
    if s.kind == "circle":
        d = abs(math.hypot(p[0] - s.c[0], p[1] - s.c[1]) - s.r)
        if s.fill and math.hypot(p[0] - s.c[0], p[1] - s.c[1]) <= s.r:
            return 0.0
        return d
    if s.kind == "arc":
        a = angle_of(p, s.c)
        if angle_in_arc(a, s.start, s.extent):
            return abs(math.hypot(p[0] - s.c[0], p[1] - s.c[1]) - s.r)
        st, ex = arc_norm(s.start, s.extent)
        e1, e2 = point_at(s.c, s.r, st), point_at(s.c, s.r, st + ex)
        return min(math.hypot(p[0] - e1[0], p[1] - e1[1]), math.hypot(p[0] - e2[0], p[1] - e2[1]))
    if s.kind == "hatch":
        if not s.rings:
            return 1e9
        if regions.point_in_rings(s.rings, p):
            return 0.0
        return regions.boundary_distance(s.rings, p)
    if s.kind == "text":
        b = text_extent(s)
        if b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]:
            return 0.0
        dx = max(b[0] - p[0], 0, p[0] - b[2])
        dy = max(b[1] - p[1], 0, p[1] - b[3])
        return math.hypot(dx, dy)
    return 1e9


def point_in_polygon(p, pts) -> bool:
    inside = False
    n = len(pts)
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        if (y1 > p[1]) != (y2 > p[1]):
            x = x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1)
            if x > p[0]:
                inside = not inside
    return inside


# ================================================================ object snap
def snap_points(s: Shape) -> list:
    """(kind, point) object-snap candidates: end, mid, center, quad, node."""
    out = []
    if s.kind in ("line", "polyline", "polygon", "rect"):
        for p in s.pts:
            out.append(("end", p))
        for a, b in segments(s):
            out.append(("mid", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)))
        if s.kind in ("polygon", "rect"):
            bb = bbox_of(s.pts)
            if s.kind == "rect":
                out.append(("center", ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)))
    elif s.kind == "circle":
        out.append(("center", s.c))
        for q in (0, 90, 180, 270):
            out.append(("quad", point_at(s.c, s.r, q)))
    elif s.kind == "arc":
        st, ex = arc_norm(s.start, s.extent)
        out.append(("center", s.c))
        out.append(("end", point_at(s.c, s.r, st)))
        out.append(("end", point_at(s.c, s.r, st + ex)))
        out.append(("mid", point_at(s.c, s.r, st + ex / 2)))
        for q in (0, 90, 180, 270):
            if angle_in_arc(q, st, ex):
                out.append(("quad", point_at(s.c, s.r, q)))
    elif s.kind == "text":
        out.append(("node", s.pts[0]))
    elif s.kind == "hatch":
        out += [("end", (x, y)) for ring in s.rings for x, y, _b in ring]
    return [(k, (clean(p[0]), clean(p[1]))) for k, p in out]


# ================================================================ intersections
# Elements: ("seg", a, b) or ("arc", c, r, start, extent) with extent 360 for circles.
def elements(s: Shape) -> list:
    if s.kind in ("line", "polyline", "polygon", "rect"):
        return [("seg", a, b) for a, b in segments(s)]
    if s.kind == "circle":
        return [("arc", s.c, s.r, 0.0, 360.0)]
    if s.kind == "arc":
        st, ex = arc_norm(s.start, s.extent)
        return [("arc", s.c, s.r, st, ex)]
    return []


def _seg_seg(a, b, c, d, infinite_first=False):
    """Intersection params (t on a-b, u on c-d)."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < EPS:
        return []
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    if -1e-9 <= u <= 1 + 1e-9 and (infinite_first or -1e-9 <= t <= 1 + 1e-9):
        return [(t, (a[0] + t * r[0], a[1] + t * r[1]))]
    return []


def _line_circle(a, b, c, r):
    """Params t (unbounded) where the infinite line a-b meets the circle."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    fx, fy = a[0] - c[0], a[1] - c[1]
    A = dx * dx + dy * dy
    if A < EPS:
        return []
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - r * r
    disc = B * B - 4 * A * C
    if disc < -1e-9:
        return []
    disc = math.sqrt(max(0.0, disc))
    ts = {(-B - disc) / (2 * A), (-B + disc) / (2 * A)}
    return [(t, (a[0] + t * dx, a[1] + t * dy)) for t in sorted(ts)]


def _circle_circle(c1, r1, c2, r2):
    d = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    if d < EPS or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    mx = c1[0] + a * (c2[0] - c1[0]) / d
    my = c1[1] + a * (c2[1] - c1[1]) / d
    pts = [(mx + h * (c2[1] - c1[1]) / d, my - h * (c2[0] - c1[0]) / d),
           (mx - h * (c2[1] - c1[1]) / d, my + h * (c2[0] - c1[0]) / d)]
    if h < 1e-9:
        pts = pts[:1]
    return pts


def element_intersections(e1, e2) -> list:
    """Intersection points of two bounded elements."""
    out = []
    if e1[0] == "seg" and e2[0] == "seg":
        out = [p for _t, p in _seg_seg(e1[1], e1[2], e2[1], e2[2])]
    elif e1[0] == "seg" or e2[0] == "seg":
        seg, arc = (e1, e2) if e1[0] == "seg" else (e2, e1)
        for t, p in _line_circle(seg[1], seg[2], arc[1], arc[2]):
            if -1e-9 <= t <= 1 + 1e-9 and angle_in_arc(angle_of(p, arc[1]), arc[3], arc[4]):
                out.append(p)
    else:
        for p in _circle_circle(e1[1], e1[2], e2[1], e2[2]):
            if angle_in_arc(angle_of(p, e1[1]), e1[3], e1[4]) and angle_in_arc(angle_of(p, e2[1]), e2[3], e2[4]):
                out.append(p)
    return out


def intersections(a: Shape, b: Shape) -> list:
    out = []
    for e1 in elements(a):
        for e2 in elements(b):
            out += element_intersections(e1, e2)
    return out


# ================================================================ path parametrisation
def _path_length_params(s: Shape):
    """For segment shapes: list of (seg_start_param, a, b, length)."""
    out = []
    acc = 0.0
    for a, b in segments(s):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        out.append((acc, a, b, L))
        acc += L
    return out, acc


def _param_of_point(s: Shape, p: Point) -> float:
    """Closest path parameter (length along a segment path, or degrees
    along an arc / circle) to point p."""
    if s.kind in ("circle", "arc"):
        a = angle_of(p, s.c)
        if s.kind == "circle":
            return a
        st, _ex = arc_norm(s.start, s.extent)
        return arc_param(a, st, _ex)
    best = (1e18, 0.0)
    segs, _total = _path_length_params(s)
    for acc, a, b, L in segs:
        if L < EPS:
            continue
        t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / (L * L)))
        q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if d < best[0]:
            best = (d, acc + t * L)
    return best[1]


def _point_at_param(s: Shape, u: float) -> Point:
    segs, total = _path_length_params(s)
    for acc, a, b, L in segs:
        if u <= acc + L + 1e-9 or (acc, a, b, L) == segs[-1]:
            t = 0.0 if L < EPS else (u - acc) / L
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return segs[-1][2]


def _sub_path(s: Shape, u0: float, u1: float) -> list:
    """Points of the segment path between params u0 < u1 (open path)."""
    segs, total = _path_length_params(s)
    pts = [_point_at_param(s, u0)]
    for acc, a, b, L in segs:
        if u0 + 1e-9 < acc < u1 - 1e-9:
            pts.append(a)
    pts.append(_point_at_param(s, u1))
    out = []
    for p in pts:
        p = (clean(p[0]), clean(p[1]))
        if not out or math.hypot(out[-1][0] - p[0], out[-1][1] - p[1]) > 1e-6:
            out.append(p)
    return out


def _closed_as_open(s: Shape) -> Shape:
    """A polygon/rect re-expressed as an open polyline that returns to its start."""
    o = copy.deepcopy(s)
    o.kind = "polyline"
    o.pts = list(s.pts) + [s.pts[0]]
    o.fill = False
    return o


def _cut_params(s: Shape, cutters: Iterable[Shape]) -> list:
    ps = []
    for c in cutters:
        if c is s:
            continue
        for p in intersections(s, c):
            ps.append(_param_of_point(s, p))
    return sorted(set(round(v, 9) for v in ps))


# ================================================================ TRIM
def trim(s: Shape, pick: Point, cutters: Iterable[Shape], next_id) -> Optional[list]:
    """Trim the part of `s` nearest `pick` that lies between cutting edges.
    Returns the replacement shapes (possibly empty = shape deleted), or None
    if nothing could be trimmed (no intersections). `next_id()` supplies ids
    for any extra pieces."""
    cutters = list(cutters)
    if s.kind in ("text", "hatch"):
        return None
    if s.kind == "circle":
        cuts = _cut_params(s, cutters)
        if len(cuts) < 2:
            return None
        a = angle_of(pick, s.c)
        lower = max((c for c in cuts if c <= a), default=cuts[-1])
        upper = min((c for c in cuts if c > a), default=cuts[0])
        # keep the arc from `upper` round to `lower`
        o = copy.deepcopy(s)
        o.kind = "arc"
        o.start = clean(upper)
        o.extent = clean(norm_angle(lower - upper) or 360.0)
        o.fill = False
        return [o]
    if s.kind == "arc":
        st, ex = arc_norm(s.start, s.extent)
        cuts = [c for c in _cut_params(s, cutters) if 1e-6 < c < ex - 1e-6]
        if not cuts:
            return None
        u = arc_param(angle_of(pick, s.c), st, ex)
        lower = max((c for c in cuts if c <= u), default=None)
        upper = min((c for c in cuts if c > u), default=None)
        out = []
        if lower is not None:
            o = copy.deepcopy(s)
            o.start, o.extent = clean(st), clean(lower)
            out.append(o)
        if upper is not None:
            o = copy.deepcopy(s)
            if out:
                o.id = next_id()
            o.start, o.extent = clean(norm_angle(st + upper)), clean(ex - upper)
            out.append(o)
        return out
    work = _closed_as_open(s) if s.kind in ("polygon", "rect") else s
    segs, total = _path_length_params(work)
    cuts = [c for c in _cut_params(work, cutters)]
    if s.kind in ("polygon", "rect"):
        cuts = sorted(set(c for c in cuts if c < total - 1e-6))
        if len(cuts) < 2:
            return None
        u = _param_of_point(work, pick)
        lower = max((c for c in cuts if c <= u), default=None)
        upper = min((c for c in cuts if c > u), default=None)
        # closed path: wrap around
        if lower is None:
            lower = cuts[-1] - total
        if upper is None:
            upper = cuts[0] + total
        # keep from upper round to lower (+ total)
        pts = _sub_path(work, upper, total) if upper < total else []
        lo = lower if lower >= 0 else lower + total
        tail = _sub_path(work, 0.0, lo)
        if upper >= total:
            pts = _sub_path(work, upper - total, lo)
        else:
            pts = pts + tail[1:]
        o = copy.deepcopy(s)
        o.kind, o.pts, o.fill = "polyline", pts, False
        return [o] if len(pts) >= 2 else []
    cuts = [c for c in cuts if 1e-6 < c < total - 1e-6]
    if not cuts:
        return None
    u = _param_of_point(work, pick)
    lower = max((c for c in cuts if c <= u), default=None)
    upper = min((c for c in cuts if c > u), default=None)
    out = []
    if lower is not None:
        o = copy.deepcopy(s)
        o.pts = _sub_path(work, 0.0, lower)
        o.kind = "line" if len(o.pts) == 2 else "polyline"
        o.arrow_end = False
        out.append(o)
    if upper is not None:
        o = copy.deepcopy(s)
        if out:
            o.id = next_id()
        o.pts = _sub_path(work, upper, total)
        o.kind = "line" if len(o.pts) == 2 else "polyline"
        o.arrow_start = False
        out.append(o)
    return [o for o in out if len(o.pts) >= 2]


# ================================================================ EXTEND
def extend(s: Shape, pick: Point, boundaries: Iterable[Shape]) -> bool:
    """Extend the end of an open line/polyline/arc nearest `pick` to the
    nearest boundary it would meet. Returns True if the shape changed."""
    bounds = [b for b in boundaries if b is not s]
    if s.kind in ("line", "polyline"):
        d0 = math.hypot(pick[0] - s.pts[0][0], pick[1] - s.pts[0][1])
        d1 = math.hypot(pick[0] - s.pts[-1][0], pick[1] - s.pts[-1][1])
        at_start = d0 < d1
        a, b = (s.pts[1], s.pts[0]) if at_start else (s.pts[-2], s.pts[-1])
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < EPS:
            return False
        best = None
        for bd in bounds:
            for e in elements(bd):
                cands = []
                if e[0] == "seg":
                    cands = _seg_seg(a, b, e[1], e[2], infinite_first=True)
                else:
                    cands = [(t, p) for t, p in _line_circle(a, b, e[1], e[2])
                             if angle_in_arc(angle_of(p, e[1]), e[3], e[4])]
                for t, p in cands:
                    if t > 1 + 1e-6 and (best is None or t < best[0]):
                        best = (t, p)
        if best is None:
            return False
        p = (clean(best[1][0]), clean(best[1][1]))
        if at_start:
            s.pts[0] = p
        else:
            s.pts[-1] = p
        return True
    if s.kind == "arc":
        st, ex = arc_norm(s.start, s.extent)
        e_start, e_end = point_at(s.c, s.r, st), point_at(s.c, s.r, st + ex)
        at_start = math.hypot(pick[0] - e_start[0], pick[1] - e_start[1]) < \
            math.hypot(pick[0] - e_end[0], pick[1] - e_end[1])
        full = Shape(id=-1, kind="circle", c=s.c, r=s.r)
        best = None
        for bd in bounds:
            for p in intersections(full, bd):
                a = angle_of(p, s.c)
                if at_start:
                    gap = norm_angle(st - a)          # going clockwise from the start
                else:
                    gap = norm_angle(a - (st + ex))   # going counter-clockwise from the end
                if 1e-6 < gap < 360 - ex - 1e-6 and (best is None or gap < best):
                    best = gap
        if best is None:
            return False
        if at_start:
            s.start, s.extent = clean(norm_angle(st - best)), clean(ex + best)
        else:
            s.start, s.extent = clean(st), clean(ex + best)
        return True
    return False


# ================================================================ conversions
def shape_to_symbol_prim(s: Shape) -> dict:
    """Shape (symbol-local coordinates) -> symbol primitive dict. Arcs are kept
    as native arcs ({"k": "arc"}); the symbol framework flattens them.
    Boundary fills are not part of the symbol format (they stay on sheets);
    a fill reaching this point becomes a filled polygon of its outer ring."""
    w = s.width
    if s.kind == "hatch":
        outer = regions.flatten_ring(s.rings[0]) if s.rings else []
        return {"k": "poly", "pts": [tuple(p) for p in outer], "fill": True, "dash": False, "w": w}
    if s.kind in ("line", "polyline"):
        return {"k": "line", "pts": [tuple(p) for p in s.pts], "dash": s.dash, "w": w,
                "arrow_start": s.arrow_start, "arrow_end": s.arrow_end, "arrow_size": s.arrow_size}
    if s.kind in ("polygon", "rect"):
        return {"k": "poly", "pts": [tuple(p) for p in s.pts], "fill": s.fill, "dash": s.dash, "w": w}
    if s.kind == "circle":
        return {"k": "circle", "c": tuple(s.c), "r": s.r, "fill": s.fill, "dash": s.dash, "w": w}
    if s.kind == "arc":
        st, ex = arc_norm(s.start, s.extent)
        return {"k": "arc", "c": tuple(s.c), "r": s.r, "start": st, "extent": ex, "dash": s.dash, "w": w}
    return {"k": "text", "p": tuple(s.pts[0]), "s": s.s, "size": s.size, "anchor": s.anchor}


def symbol_prim_to_shape(p: dict, ident: int) -> Shape:
    k = p["k"]
    w = p.get("w", "normal")
    if k == "line":
        pts = [tuple(q) for q in p["pts"]]
        return Shape(ident, "line" if len(pts) == 2 else "polyline", pts=pts, width=w, dash=p.get("dash", False),
                     arrow_start=p.get("arrow_start", False), arrow_end=p.get("arrow_end", False),
                     arrow_size=p.get("arrow_size", 10.0))
    if k == "poly":
        pts = [tuple(q) for q in p["pts"]]
        is_rect = len(pts) == 4 and all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6
                                         for a, b in zip(pts, pts[1:] + pts[:1]))
        return Shape(ident, "rect" if is_rect else "polygon", pts=pts, width=w, dash=p.get("dash", False),
                     fill=p.get("fill", False))
    if k == "circle":
        return Shape(ident, "circle", c=tuple(p["c"]), r=p["r"], width=w, dash=p.get("dash", False),
                     fill=p.get("fill", False))
    if k == "arc":
        return Shape(ident, "arc", c=tuple(p["c"]), r=p["r"], start=p["start"], extent=p["extent"], width=w,
                     dash=p.get("dash", False))
    return Shape(ident, "text", pts=[tuple(p["p"])], s=p.get("s", ""), size=p.get("size", 8),
                 anchor=p.get("anchor", "c"))


def shapes_bbox(shapes: Iterable[Shape]):
    b = None
    for s in shapes:
        b = bbox_union(b, shape_bbox(s))
    return b
