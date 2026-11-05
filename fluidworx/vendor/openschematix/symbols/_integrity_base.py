"""Internal helpers for symbol integrity checks (not public API)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import GRID
from .base import PORT_TYPES, Geometry, Terminal, validate_geometry

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass(frozen=True)
class Finding:
    """One integrity problem (or informational note).

    ``location`` identifies the field or primitive (e.g. ``pin[0]``,
    ``prim[2]``). ``source`` is the originating file path when known
    (CLI multi-file mode); it is included in ``as_dict`` for machine-readable
    output.
    """

    symbol_id: str
    problem: str
    severity: str = SEVERITY_ERROR
    location: str = ""
    source: str = ""

    def as_dict(self) -> dict:
        d = {"symbol_id": self.symbol_id, "problem": self.problem, "severity": self.severity}
        if self.location:
            d["location"] = self.location
        if self.source:
            d["source"] = self.source
        return d


def _safe_in(value, container) -> bool:
    """Membership test that never raises on unhashable ``value``."""
    try:
        return value in container
    except TypeError:
        return False


def _finite_number(v) -> bool:
    """True if *v* converts to a finite float. Never raises."""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return False
    try:
        return math.isfinite(f)
    except (TypeError, ValueError, OverflowError):
        return False


def _as_float(v):
    """Return float(v) or None on any conversion failure / non-finite."""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        if not math.isfinite(f):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return f


def _check_coordinates(label: str, x, y, sid: str, findings: list, require_grid: bool = False,
                       source: str = ""):
    fx, fy = _as_float(x), _as_float(y)
    if fx is None or fy is None:
        findings.append(Finding(sid, f"{label}: invalid numeric coordinates ({x!r}, {y!r})",
                                SEVERITY_ERROR, label, source))
        return
    try:
        out_of_range = abs(fx) > 1e6 or abs(fy) > 1e6
    except (TypeError, OverflowError):
        out_of_range = True
    if out_of_range:
        findings.append(Finding(sid, f"{label}: coordinates out of range ({fx}, {fy})",
                                SEVERITY_ERROR, label, source))
        return
    if require_grid:
        try:
            off = (abs(fx / GRID - round(fx / GRID)) > 1e-6 or
                   abs(fy / GRID - round(fy / GRID)) > 1e-6)
        except (TypeError, OverflowError, ZeroDivisionError):
            off = True
        if off:
            findings.append(Finding(sid, f"{label}: not on the {GRID}-unit grid at ({fx}, {fy})",
                                    SEVERITY_ERROR, label, source))
