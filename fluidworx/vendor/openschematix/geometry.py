"""Small geometry helpers shared by the model, renderer and editor.

Coordinate system: drawing units, x to the right, y DOWN (screen convention).
One drawing unit is 0.25 mm on paper; the snap grid is 10 units (2.5 mm),
which matches the 2.5 mm module grid commonly used for schematic drawings.

Symbol transforms are restricted to multiples of 90 degrees plus an optional
mirror, so terminals that sit on grid points stay on grid points.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

GRID = 10
UNIT_MM = 0.25
EPS = 1e-6

Point = tuple[float, float]


def snap(v: float, step: float = GRID) -> float:
    return float(round(v / step) * step)


def snap_pt(p: Point, step: float = GRID) -> Point:
    return (snap(p[0], step), snap(p[1], step))


def norm_rotation(r) -> int:
    """Normalise any numeric rotation to 0/90/180/270 (nearest quarter turn)."""
    try:
        r = float(r)
    except (TypeError, ValueError):
        return 0
    return int(round(r / 90.0)) % 4 * 90


def xform(x: float, y: float, rotation: int = 0, mirror: bool = False) -> Point:
    """Transform a local point: mirror about the local Y axis first, then rotate
    clockwise (as seen on screen) by `rotation` degrees."""
    if mirror:
        x = -x
    r = rotation % 360
    if r == 0:
        return (x, y)
    if r == 90:
        return (-y, x)
    if r == 180:
        return (-x, -y)
    if r == 270:
        return (y, -x)
    a = math.radians(r)
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))


def clean(v: float) -> float:
    """Remove floating point noise (e.g. -0.0, 9.999999)."""
    r = round(v, 6)
    return 0.0 if r == 0 else r


def dist2(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def same(a: Point, b: Point, tol: float = 0.01) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def point_on_segment(p: Point, a: Point, b: Point, tol: float = 0.01) -> bool:
    """True if p lies on segment a-b (inclusive of the end points)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs(ax - bx) <= tol:  # vertical
        return abs(px - ax) <= tol and min(ay, by) - tol <= py <= max(ay, by) + tol
    if abs(ay - by) <= tol:  # horizontal
        return abs(py - ay) <= tol and min(ax, bx) - tol <= px <= max(ax, bx) + tol
    # general segment
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    length = math.hypot(bx - ax, by - ay)
    if length < EPS or abs(cross) / length > tol:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    return -tol <= dot <= length * length + tol


def seg_distance(p: Point, a: Point, b: Point) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < EPS:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def bbox_of(points: Iterable[Point]):
    pts = list(points)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def bbox_contains(outer, inner) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def bbox_hit(b, p: Point, pad: float = 0.0) -> bool:
    return b[0] - pad <= p[0] <= b[2] + pad and b[1] - pad <= p[1] <= b[3] + pad


def simplify_orthogonal(points: Sequence[Point]) -> list[Point]:
    """Drop duplicate points and interior points that are collinear with their
    neighbours. Keeps at least two points (start and end)."""
    out: list[Point] = []
    for p in points:
        p = (clean(p[0]), clean(p[1]))
        if out and same(out[-1], p):
            continue
        out.append(p)
    changed = True
    while changed and len(out) > 2:
        changed = False
        for i in range(1, len(out) - 1):
            a, b, c = out[i - 1], out[i], out[i + 1]
            if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or (
                abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01
            ):
                del out[i]
                changed = True
                break
    if len(out) == 1:
        out.append(out[0])
    return out


def is_orthogonal(points: Sequence[Point]) -> bool:
    return all(abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01 for a, b in zip(points, points[1:]))


def elbow(a: Point, b: Point, horizontal_first: bool = True) -> list[Point]:
    """Orthogonal path a -> b with at most one bend."""
    if abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01:
        return [a, b]
    mid = (b[0], a[1]) if horizontal_first else (a[0], b[1])
    return [a, mid, b]


def arc_points(cx: float, cy: float, r: float, start: float, extent: float, steps: int | None = None) -> list[Point]:
    """Sample an arc. Angles in degrees, counter-clockwise as seen on screen,
    0 deg pointing to +x (Tk convention)."""
    if steps is None:
        steps = max(4, int(abs(extent) / 10))
    pts = []
    for i in range(steps + 1):
        a = math.radians(start + extent * i / steps)
        pts.append((cx + r * math.cos(a), cy - r * math.sin(a)))
    return pts
