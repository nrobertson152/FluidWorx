"""Connection analysis: junction dots, unconnected wire ends and terminals.

Rules (common schematic practice):
  * Wires are connected where an end point of one wire lies on another wire
    (end, corner or anywhere along a segment).
  * Component terminals connect only to wire END points; a wire that merely
    passes over a terminal is not connected to it (same rule as KiCad).
  * Two wires that merely cross are NOT connected.
  * A junction dot is drawn where three or more branches meet.

Performance (spatial index)
---------------------------
For every wire end point and corner, the analysis counts the wires that end
at or pass through that point. Testing every wire for every point is
O(P * S) (P points, S segments), i.e. quadratic in drawing size. A
`_WireIndex` built once per call narrows the wires examined for each point:

  * The plane is divided into square cells of `_CELL` drawing units. Each
    wire is registered in every cell overlapped by the bounding box of any of
    its segments, padded by `_PAD`. A query looks at one cell only.
  * The exact per-wire tests (`same`, `point_on_segment`, default tolerance)
    are unchanged; the index only discards wires that cannot pass them, so
    results, tolerances and output order are identical to a full scan.
  * `_PAD` must cover every point `point_on_segment` accepts, not just the
    perpendicular tolerance: its general (non axis-aligned) branch accepts
    points up to tol/length beyond a segment end along the segment. That
    branch requires |dx| > tol and |dy| > tol, so length > sqrt(2)*tol and
    the overshoot is below 1/sqrt(2) units; `_PAD` = tol + 1 covers it.
  * Memory is linear in the number of segments: a segment whose padded box
    covers more than `_MAX_CELLS_PER_SEGMENT` cells (long diagonals, huge
    coordinates), a wire with non-finite coordinates or fewer than two
    points, and every wire once the total registrations would exceed
    `_ENTRY_BUDGET_PER_SEGMENT * S + _ENTRY_BUDGET_MIN`, goes to an
    "always examine" list instead of the grid. Those wires are tested for
    every point, exactly as before, so correctness never depends on the cap.

Complexity: building O(S * c) with c <= _MAX_CELLS_PER_SEGMENT cells per
segment (c is about length/_CELL + 2 for axis-aligned wires); memory
O(min(S * c, _ENTRY_BUDGET_PER_SEGMENT * S + _ENTRY_BUDGET_MIN)); each query
O(k + A) wire tests, k = wires registered in the cell, A = always-examined
wires. In the worst case (everything always-examined) it degrades to the
previous full scan plus a small constant. The index is local to one call:
nothing is cached between calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import symbols
from .geometry import point_on_segment, same
from .model import Document

_TOL = 0.01                       # default tolerance of same() / point_on_segment()
_PAD = _TOL + 1.0                 # see module docstring
_CELL = 50.0                      # grid cell size in drawing units (5 grid steps)
_MAX_CELLS_PER_SEGMENT = 256      # larger segments are always examined
_ENTRY_BUDGET_PER_SEGMENT = 32    # total grid registrations allowed per segment ...
_ENTRY_BUDGET_MIN = 4096          # ... plus this many


@dataclass
class Connectivity:
    junctions: list = field(default_factory=list)          # points needing a dot
    open_wire_ends: list = field(default_factory=list)     # (wire_id, point)
    open_terminals: list = field(default_factory=list)     # (comp_id, name, point)
    connected_terminals: set = field(default_factory=set)  # (comp_id, name)


def _key(p):
    return (round(p[0], 2), round(p[1], 2))


def _cell(v: float) -> int:
    return math.floor(v / _CELL)


class _WireIndex:
    """Uniform grid of wires by padded segment bounding box (see module docstring)."""

    def __init__(self, wires):
        self.cells: dict = {}
        self.always: list = []
        self.entries = 0
        nseg = sum(max(0, len(w.points) - 1) for w in wires)
        budget = _ENTRY_BUDGET_PER_SEGMENT * nseg + _ENTRY_BUDGET_MIN
        for w in wires:
            keys = self._cells_of(w.points)
            if keys is None or self.entries + len(keys) > budget:
                self.always.append(w)
                continue
            self.entries += len(keys)
            for k in keys:
                self.cells.setdefault(k, []).append(w)

    @staticmethod
    def _cells_of(pts):
        """Set of cells for a wire, or None if it must always be examined."""
        if len(pts) < 2:
            return None
        keys = set()
        for a, b in zip(pts, pts[1:]):
            x0, x1 = min(a[0], b[0]) - _PAD, max(a[0], b[0]) + _PAD
            y0, y1 = min(a[1], b[1]) - _PAD, max(a[1], b[1]) + _PAD
            if not (math.isfinite(x0) and math.isfinite(x1) and math.isfinite(y0) and math.isfinite(y1)):
                return None
            i0, i1, j0, j1 = _cell(x0), _cell(x1), _cell(y0), _cell(y1)
            if (i1 - i0 + 1) * (j1 - j0 + 1) > _MAX_CELLS_PER_SEGMENT:
                return None
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    keys.add((i, j))
        return keys

    def candidates(self, p, wires):
        """Wires that may end at or pass through p (a superset of the true ones)."""
        if not (math.isfinite(p[0]) and math.isfinite(p[1])):
            return wires
        near = self.cells.get((_cell(p[0]), _cell(p[1])))
        if not near:
            return self.always
        return near + self.always if self.always else near


def _unit_heading(p, q):
    """Normalized direction heading from p towards q, or None if p == q."""
    dx = q[0] - p[0]
    dy = q[1] - p[1]
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return None
    return (dx / dist, dy / dist)


def _add_distinct_direction(dirs: list[tuple[float, float]], d: tuple[float, float] | None, tol: float = 0.01):
    if d is None:
        return
    for existing in dirs:
        if math.hypot(d[0] - existing[0], d[1] - existing[1]) <= tol:
            return
    dirs.append(d)


@symbols.project_scoped
def analyse(doc: Document) -> Connectivity:
    res = Connectivity()
    wires = list(doc.wires.values())
    terminals = []  # (cid, name, point)
    for c in doc.components.values():
        for name, p in c.terminals().items():
            terminals.append((c.id, name, p))

    # candidate points: wire end points and wire corners
    candidates = {}
    for w in wires:
        for p in w.points:
            candidates[_key(p)] = p

    index = _WireIndex(wires)

    def counts_at(p, exclude_wire=None):
        ends = through = 0
        for w in index.candidates(p, wires):
            if w.id == exclude_wire:
                continue
            pts = w.points
            if same(pts[0], p) or same(pts[-1], p):
                ends += 1 + (1 if len(pts) == 2 and same(pts[0], pts[-1]) else 0)
            elif any(point_on_segment(p, a, b) for a, b in zip(pts, pts[1:])):
                through += 1  # passes through (corner or along a segment)
        return ends, through

    term_at = {}
    for cid, name, p in terminals:
        term_at.setdefault(_key(p), []).append((cid, name))

    for k, p in candidates.items():
        terms = len(term_at.get(k, []))
        # Find wires ending at or touching p
        ending_wires = []
        touching_wires = []
        for w in index.candidates(p, wires):
            pts = w.points
            is_end = same(pts[0], p) or same(pts[-1], p)
            is_touch = is_end or any(point_on_segment(p, a, b) for a, b in zip(pts, pts[1:]))
            if is_end:
                ending_wires.append(w)
            if is_touch:
                touching_wires.append(w)

        # An electrical connection at p exists when:
        # 1. At least one wire ends at p and at least one other wire touches p (ends or passes through); or
        # 2. At least two wires end at p; or
        # 3. A wire ends at p and connects to a terminal, or multiple terminals meet at p.
        # Wires that merely pass through without an endpoint ending there do NOT connect.
        has_wire_conn = len(ending_wires) >= 1 and len(touching_wires) >= 2
        has_term_conn = terms >= 1 and len(ending_wires) >= 1
        has_multi_term = terms >= 2

        if has_wire_conn or has_term_conn or has_multi_term:
            distinct_dirs = []
            for w in touching_wires:
                pts = w.points
                for a, b in zip(pts, pts[1:]):
                    if point_on_segment(p, a, b):
                        d1 = _unit_heading(p, a)
                        d2 = _unit_heading(p, b)
                        _add_distinct_direction(distinct_dirs, d1)
                        _add_distinct_direction(distinct_dirs, d2)
            n_branches = len(distinct_dirs) + terms
            if n_branches >= 3:
                res.junctions.append(p)

    for w in wires:
        for idx in (0, -1):
            p = w.points[idx]
            if _key(p) in term_at:
                continue
            ends, through = counts_at(p, exclude_wire=w.id)
            if ends == 0 and through == 0:
                res.open_wire_ends.append((w.id, p))

    end_points = {_key(w.points[i]) for w in wires for i in (0, -1)}
    for cid, name, p in terminals:
        k = _key(p)
        if k in end_points or len(term_at.get(k, [])) > 1:
            res.connected_terminals.add((cid, name))
        else:
            res.open_terminals.append((cid, name, p))
    return res
