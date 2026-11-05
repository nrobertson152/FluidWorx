"""Geometry-level integrity checks (internal)."""
from __future__ import annotations

from .base import PORT_TYPES, Geometry, Terminal, validate_geometry
from ._integrity_base import Finding, SEVERITY_ERROR, SEVERITY_WARNING, _as_float, _check_coordinates, _safe_in


def _check_geometry(g: Geometry, sid: str, findings: list, source: str = ""):
    if g is None:
        findings.append(Finding(sid, "geometry is missing", SEVERITY_ERROR, source=source))
        return
    try:
        for msg in validate_geometry(g):
            findings.append(Finding(sid, msg, SEVERITY_ERROR, source=source))
    except Exception as e:  # noqa: BLE001
        findings.append(Finding(sid, f"geometry validation failed: {e}", SEVERITY_ERROR, source=source))
        return
    prims = getattr(g, "prims", None) or []
    if not isinstance(prims, (list, tuple)):
        findings.append(Finding(sid, "geometry prims is not a sequence", SEVERITY_ERROR, source=source))
        prims = []
    for i, p in enumerate(prims):
        loc = f"prim[{i}]"
        if not isinstance(p, dict):
            findings.append(Finding(sid, f"primitive {i}: not a mapping", SEVERITY_ERROR, loc, source))
            continue
        k = p.get("k")
        if not _safe_in(k, ("line", "poly", "circle", "text")):
            findings.append(Finding(sid, f"primitive {i}: unsupported or malformed kind {k!r}",
                                    SEVERITY_ERROR, loc, source))
        if k in ("line", "poly"):
            pts = p.get("pts") or []
            if not isinstance(pts, (list, tuple)):
                findings.append(Finding(sid, f"primitive {i}: pts is not a sequence",
                                        SEVERITY_ERROR, loc, source))
                continue
            for j, pt in enumerate(pts):
                if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
                    findings.append(Finding(sid, f"primitive {i}: point {j} malformed",
                                            SEVERITY_ERROR, loc, source))
                else:
                    _check_coordinates(f"primitive {i} point {j}", pt[0], pt[1], sid, findings,
                                       source=source)
        elif k == "circle":
            c = p.get("c")
            if not (isinstance(c, (list, tuple)) and len(c) == 2):
                findings.append(Finding(sid, f"primitive {i}: circle centre malformed",
                                        SEVERITY_ERROR, loc, source))
            else:
                _check_coordinates(f"primitive {i} centre", c[0], c[1], sid, findings, source=source)
            r = p.get("r")
            rf = _as_float(r)
            if rf is None or rf <= 0:
                findings.append(Finding(sid, f"primitive {i}: invalid radius {r!r}",
                                        SEVERITY_ERROR, loc, source))
        elif k == "text":
            pt = p.get("p")
            if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
                findings.append(Finding(sid, f"primitive {i}: text position malformed",
                                        SEVERITY_ERROR, loc, source))
            else:
                _check_coordinates(f"primitive {i} text", pt[0], pt[1], sid, findings, source=source)
    terminals = getattr(g, "terminals", None) or []
    if not isinstance(terminals, (list, tuple)):
        findings.append(Finding(sid, "geometry terminals is not a sequence", SEVERITY_ERROR, source=source))
        return
    for t in terminals:
        if not isinstance(t, Terminal):
            findings.append(Finding(sid, "terminal entry is not a Terminal", SEVERITY_ERROR, source=source))
            continue
        if not t.name:
            findings.append(Finding(sid, "terminal has empty name/id", SEVERITY_ERROR, "terminal", source))
        _check_coordinates(f"terminal {t.name}", t.x, t.y, sid, findings, require_grid=True, source=source)
        if t.dir not in ("l", "r", "u", "d"):
            findings.append(Finding(sid, f"terminal {t.name}: invalid direction {t.dir!r}",
                                    SEVERITY_ERROR, t.name or "terminal", source))
        if t.ptype and not _safe_in(t.ptype, PORT_TYPES) and t.ptype != "":
            findings.append(Finding(sid, f"terminal {t.name}: unknown port type {t.ptype!r}",
                                    SEVERITY_WARNING, t.name or "terminal", source))
