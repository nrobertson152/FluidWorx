"""Document primitive integrity checks (internal)."""
from __future__ import annotations

from .custom import PRIM_KINDS
from ._integrity_base import Finding, SEVERITY_ERROR, SEVERITY_WARNING, _as_float, _check_coordinates, _safe_in


def _validate_document_prims(doc: dict, sid: str, findings: list, source: str) -> None:
    prims = doc.get("prims")
    if prims is None:
        return
    if not isinstance(prims, list):
        findings.append(Finding(sid, "prims must be a list", SEVERITY_ERROR, source=source))
        return
    for i, p in enumerate(prims):
        loc = f"prim[{i}]"
        if not isinstance(p, dict):
            findings.append(Finding(sid, f"primitive {i}: not an object", SEVERITY_ERROR, loc, source))
            continue
        k = p.get("k")
        if not _safe_in(k, PRIM_KINDS):
            findings.append(Finding(sid, f"primitive {i}: unsupported kind {k!r}",
                                    SEVERITY_ERROR, loc, source))
            continue
        if k in ("line", "poly"):
            pts = p.get("pts")
            if not isinstance(pts, (list, tuple)) or len(pts) < 2:
                findings.append(Finding(sid, f"primitive {i}: needs at least two points",
                                        SEVERITY_ERROR, loc, source))
            else:
                for j, pt in enumerate(pts):
                    if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
                        findings.append(Finding(sid, f"primitive {i}: point {j} malformed",
                                                SEVERITY_ERROR, loc, source))
                    else:
                        _check_coordinates(f"primitive {i} pt {j}", pt[0], pt[1], sid, findings,
                                           source=source)
            if k == "line" and ("arrow_start" in p or "arrow_end" in p or "arrow_size" in p):
                if "arrow_size" in p:
                    af = _as_float(p.get("arrow_size"))
                    if af is None or not (0 < af <= 10000):
                        findings.append(Finding(sid, f"primitive {i}: invalid arrow_size "
                                                f"{p.get('arrow_size')!r} (normalise would use 10)",
                                                SEVERITY_WARNING, loc, source))
        elif k in ("circle", "arc"):
            c = p.get("c")
            if not (isinstance(c, (list, tuple)) and len(c) == 2):
                findings.append(Finding(sid, f"primitive {i}: centre malformed",
                                        SEVERITY_ERROR, loc, source))
            else:
                _check_coordinates(f"primitive {i} centre", c[0], c[1], sid, findings, source=source)
            r = p.get("r")
            rf = _as_float(r)
            if rf is None or rf <= 0:
                findings.append(Finding(sid, f"primitive {i}: invalid radius {r!r}",
                                        SEVERITY_ERROR, loc, source))
            if k == "arc":
                for field_name in ("start", "extent"):
                    if field_name in p and _as_float(p.get(field_name)) is None:
                        findings.append(Finding(sid, f"primitive {i}: invalid {field_name}",
                                                SEVERITY_ERROR, loc, source))
        elif k == "text":
            pt = p.get("p")
            if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
                findings.append(Finding(sid, f"primitive {i}: text position malformed",
                                        SEVERITY_ERROR, loc, source))
            else:
                _check_coordinates(f"primitive {i} text", pt[0], pt[1], sid, findings, source=source)
            if "size" in p:
                sf = _as_float(p.get("size"))
                if sf is None:
                    findings.append(Finding(sid, f"primitive {i}: invalid text size {p.get('size')!r}",
                                            SEVERITY_ERROR, loc, source))
                elif not (2.0 <= sf <= 80.0):
                    findings.append(Finding(sid, f"primitive {i}: text size {sf} outside 2..80 "
                                            "(normalise would clamp)",
                                            SEVERITY_WARNING, loc, source))
            if "anchor" in p:
                anc = p.get("anchor")
                if anc not in ("c", "n", "s", "e", "w", "nw", "ne", "sw", "se"):
                    findings.append(Finding(sid, f"primitive {i}: invalid text anchor {anc!r} "
                                            "(normalise would use 'c')",
                                            SEVERITY_WARNING, loc, source))
