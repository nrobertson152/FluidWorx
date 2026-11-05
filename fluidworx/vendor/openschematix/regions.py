"""Vector regions bounded by straight and circular edges ("bulge rings").

A region is a list of closed rings. Each ring is a list of vertices
``(x, y, bulge)``; the edge from vertex *i* to vertex *i + 1* (wrapping
around) is a straight segment when ``bulge == 0`` and a circular arc
otherwise. ``bulge = tan(sweep / 4)`` where ``sweep`` is the signed angle the
arc turns through, measured in the mathematical sense of the coordinate
frame the points are expressed in (positive = from +x towards +y). This is
the DXF polyline convention, so a region can be written to CAD formats
without approximation. OpenSchematix world coordinates have y pointing
down, therefore a positive bulge turns clockwise *on screen*; exporters that
flip the y axis must negate bulges.

Regions are filled with the even-odd rule: a point is inside when a ray
from it crosses the boundary an odd number of times. Rings produced by the
boundary-fill engine never cross each other; outer rings are oriented with
positive signed area and holes with negative signed area, so the non-zero
winding rule gives the same result.

This module is pure geometry (no model or GUI imports) and is shared by
the model, renderer, hit testing and the SVG/PDF/DXF exporters.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

TAU = 2 * math.pi
MAX_BULGE = 1.0 + 1e-9          # stored arcs never exceed a half turn
FLATTEN_TOL = 0.02              # default chord error in drawing units (0.005 mm)

Vertex = tuple  # (x, y, bulge)


# ================================================================ edges
def ring_edges(ring: Sequence[Vertex]):
    """Yield (p0, p1, bulge) for every edge of a closed ring."""
    n = len(ring)
    for i in range(n):
        x0, y0, b = ring[i]
        x1, y1, _ = ring[(i + 1) % n]
        yield (x0, y0), (x1, y1), b


def bulge_arc(p0, p1, b):
    """Centre, radius, start angle and signed sweep of a bulged edge."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    f = (1 - b * b) / (4 * b)
    cx = (p0[0] + p1[0]) / 2 - f * dy
    cy = (p0[1] + p1[1]) / 2 + f * dx
    r = math.hypot(p0[0] - cx, p0[1] - cy)
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    return (cx, cy), r, a0, 4 * math.atan(b)


def angle_in_sweep(a: float, a0: float, sweep: float, tol: float = 1e-12) -> bool:
    if sweep >= 0:
        d = (a - a0) % TAU
        return d <= sweep + tol or d >= TAU - tol
    d = (a0 - a) % TAU
    return d <= -sweep + tol or d >= TAU - tol


def arc_steps(r: float, sweep: float, tol: float) -> int:
    if r <= tol:
        return 1
    half = math.acos(max(-1.0, 1.0 - tol / r))
    return max(1, int(math.ceil(abs(sweep) / (2 * half))))


def edge_points(p0, p1, b, tol: float = FLATTEN_TOL) -> list:
    """Points of one edge, excluding the end point (flattened arcs)."""
    if not b:
        return [p0]
    (cx, cy), r, a0, sw = bulge_arc(p0, p1, b)
    n = arc_steps(r, sw, tol)
    out = [p0]
    for i in range(1, n):
        a = a0 + sw * i / n
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def flatten_ring(ring: Sequence[Vertex], tol: float = FLATTEN_TOL) -> list:
    """Polygon approximating a ring; chord error at most `tol`."""
    out = []
    for p0, p1, b in ring_edges(ring):
        out += edge_points(p0, p1, b, tol)
    return out


def split_arcs(ring: Sequence[Vertex], max_sweep: float = math.pi / 2) -> list:
    """Same ring with every arc split into pieces of at most `max_sweep`
    (exact: the new vertices lie on the arc)."""
    out = []
    for p0, p1, b in ring_edges(ring):
        if not b:
            out.append((p0[0], p0[1], 0.0))
            continue
        (cx, cy), r, a0, sw = bulge_arc(p0, p1, b)
        n = max(1, int(math.ceil(abs(sw) / max_sweep - 1e-9)))
        sb = math.tan(sw / n / 4)
        out.append((p0[0], p0[1], sb))
        for i in range(1, n):
            a = a0 + sw * i / n
            out.append((cx + r * math.cos(a), cy + r * math.sin(a), sb))
    return out


# ================================================================ measures
def ring_area(ring: Sequence[Vertex]) -> float:
    """Signed area (positive = counter-clockwise in the math sense)."""
    a = 0.0
    for p0, p1, b in ring_edges(ring):
        a += (p0[0] * p1[1] - p1[0] * p0[1]) / 2
        if b:
            _c, r, _a0, sw = bulge_arc(p0, p1, b)
            a += r * r / 2 * (sw - math.sin(sw))
    return a


def region_area(rings) -> float:
    """Area of an even-odd region whose rings do not cross."""
    return sum(ring_area(r) for r in rings)


def edge_bbox(p0, p1, b):
    xs, ys = [p0[0], p1[0]], [p0[1], p1[1]]
    if b:
        (cx, cy), r, a0, sw = bulge_arc(p0, p1, b)
        for q in range(4):
            a = q * math.pi / 2
            if angle_in_sweep(a, a0, sw):
                xs.append(cx + r * math.cos(a))
                ys.append(cy + r * math.sin(a))
    return (min(xs), min(ys), max(xs), max(ys))


def rings_bbox(rings):
    box = None
    for ring in rings:
        for e in ring_edges(ring):
            b = edge_bbox(*e)
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    return box


def edge_distance(p, p0, p1, b) -> float:
    if not b:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - p0[0]) * dx + (p[1] - p0[1]) * dy) / L2))
        return math.hypot(p[0] - p0[0] - t * dx, p[1] - p0[1] - t * dy)
    (cx, cy), r, a0, sw = bulge_arc(p0, p1, b)
    if angle_in_sweep(math.atan2(p[1] - cy, p[0] - cx), a0, sw):
        return abs(math.hypot(p[0] - cx, p[1] - cy) - r)
    return min(math.dist(p, p0), math.dist(p, p1))


def boundary_distance(rings, p) -> float:
    return min((edge_distance(p, *e) for ring in rings for e in ring_edges(ring)), default=math.inf)


def _monotone_pieces(p0, p1, b):
    """Split an edge into y-monotone pieces: (start, end, x_at(y))."""
    if not b:
        def x_line(y, p0=p0, p1=p1):
            return p0[0] + (y - p0[1]) * (p1[0] - p0[0]) / (p1[1] - p0[1])
        return [(p0, p1, x_line)]
    (cx, cy), r, a0, sw = bulge_arc(p0, p1, b)
    # breakpoints where the arc reaches a vertical extreme (a = +-pi/2)
    cuts = []
    for a in (math.pi / 2, -math.pi / 2):
        d = (a - a0) % TAU if sw > 0 else (a0 - a) % TAU
        if 0 < d < abs(sw):
            cuts.append((d, a))
    cuts.sort()
    pts = [p0] + [(cx + r * math.cos(a), cy + r * math.sin(a)) for _d, a in cuts] + [p1]
    # unwrapped angles along the sweep (so the mid-angle of each piece is right)
    angs = [a0] + [a0 + (d if sw > 0 else -d) for d, _a in cuts] + [a0 + sw]
    out = []
    for i in range(len(pts) - 1):
        mid = (angs[i] + angs[i + 1]) / 2
        side = 1.0 if math.cos(mid) >= 0 else -1.0

        def x_arc(y, side=side):
            return cx + side * math.sqrt(max(0.0, r * r - (y - cy) ** 2))
        out.append((pts[i], pts[i + 1], x_arc))
    return out


def point_in_rings(rings, p) -> bool:
    """Even-odd containment test, exact for straight and circular edges."""
    px, py = p
    inside = False
    for ring in rings:
        for e in ring_edges(ring):
            for a, b, x_at in _monotone_pieces(*e):
                if (a[1] > py) != (b[1] > py):
                    if x_at(py) > px:
                        inside = not inside
    return inside


# ================================================================ transforms
def map_rings(rings, fn, mirror: bool = False) -> list:
    """Apply a similarity transform to every vertex. `mirror` must be True
    when fn reverses orientation (reflection): bulges change sign."""
    k = -1.0 if mirror else 1.0
    out = []
    for ring in rings:
        nr = []
        for x, y, b in ring:
            q = fn((x, y))
            nr.append((q[0], q[1], k * b))
        out.append(nr)
    return out


def reverse_ring(ring: Sequence[Vertex]) -> list:
    """Same ring traversed the other way (bulges move to the other end and flip)."""
    n = len(ring)
    return [(ring[i][0], ring[i][1], -ring[i - 1][2]) for i in range(n - 1, -1, -1)]


# ================================================================ validation
def clean_rings(raw) -> list:
    """Validate rings read from a file: list of lists of [x, y] / [x, y, b].
    Raises ValueError on malformed data."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("a fill needs at least one boundary ring")
    rings = []
    for r in raw:
        if not isinstance(r, list) or len(r) < 2:
            raise ValueError("a fill ring needs at least two vertices")
        ring = []
        for v in r:
            if not isinstance(v, (list, tuple)) or len(v) not in (2, 3):
                raise ValueError("fill vertices must be [x, y] or [x, y, bulge]")
            if any(isinstance(c, bool) for c in v):
                raise ValueError("fill vertex values must be numbers")
            try:
                x, y = float(v[0]), float(v[1])
                b = float(v[2]) if len(v) == 3 else 0.0
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("fill vertex values must be numbers") from exc
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(b)) or abs(b) > MAX_BULGE:
                raise ValueError("fill vertex values out of range")
            ring.append((x, y, b))
        if len(ring) == 2 and not (ring[0][2] or ring[1][2]):
            raise ValueError("a two-vertex fill ring must contain arcs")
        rings.append(ring)
    return rings


# ================================================================ decomposition
def trapezoids(polys: Iterable[Sequence], eps: float = 1e-9) -> list:
    """Decompose an even-odd polygon set (straight edges, rings that do not
    cross) into horizontal-slab trapezoids. Returns quads
    [(x, y), ...] (4 points; degenerate corners repeated) whose union is
    exactly the region. Used for DXF SOLID output."""
    edges = []
    for poly in polys:
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            if abs(a[1] - b[1]) <= eps:
                continue
            if a[1] > b[1]:
                a, b = b, a
            edges.append((a, b))
    if not edges:
        return []
    ys = sorted({p[1] for e in edges for p in e})
    # merge nearly equal y values
    merged = [ys[0]]
    for y in ys[1:]:
        if y - merged[-1] > eps:
            merged.append(y)
    ys = merged

    def x_at(e, y):
        (x0, y0), (x1, y1) = e
        t = (y - y0) / (y1 - y0)
        return x0 + t * (x1 - x0)

    out = []
    open_quads = {}          # (edge index a, edge index b) -> [top-left, top-right, y top]
    edges_sorted = sorted(range(len(edges)), key=lambda i: edges[i][0][1])
    active = []
    k = 0
    for j in range(len(ys) - 1):
        y0, y1 = ys[j], ys[j + 1]
        ym = (y0 + y1) / 2
        while k < len(edges_sorted) and edges[edges_sorted[k]][0][1] <= ym:
            active.append(edges_sorted[k])
            k += 1
        active = [i for i in active if edges[i][1][1] >= ym]
        cross = sorted(active, key=lambda i: x_at(edges[i], ym))
        pairs = [(cross[m], cross[m + 1]) for m in range(0, len(cross) - 1, 2)]
        still = {}
        for ea, eb in pairs:
            key = (ea, eb)
            if key in open_quads:
                still[key] = open_quads.pop(key)
            else:
                still[key] = (x_at(edges[ea], y0), x_at(edges[eb], y0), y0)
        for (ea, eb), (xa, xb, yt) in open_quads.items():   # closed at y0
            out.append(_quad(xa, xb, yt, x_at(edges[ea], y0), x_at(edges[eb], y0), y0))
        open_quads = still
    yl = ys[-1]
    for (ea, eb), (xa, xb, yt) in open_quads.items():
        out.append(_quad(xa, xb, yt, x_at(edges[ea], yl), x_at(edges[eb], yl), yl))
    return [q for q in out if q is not None]


def _quad(xa0, xb0, y0, xa1, xb1, y1):
    if xb0 - xa0 <= 1e-12 and xb1 - xa1 <= 1e-12:
        return None
    return [(xa0, y0), (xb0, y0), (xb1, y1), (xa1, y1)]


def quads_area(quads) -> float:
    return sum((q[1][0] - q[0][0] + q[2][0] - q[3][0]) / 2 * (q[2][1] - q[0][1]) for q in quads)


__all__ = ["ring_edges", "bulge_arc", "angle_in_sweep", "edge_points", "flatten_ring", "split_arcs", "ring_area",
           "region_area", "rings_bbox", "boundary_distance", "point_in_rings", "map_rings", "reverse_ring",
           "clean_rings", "trapezoids", "quads_area", "FLATTEN_TOL"]
