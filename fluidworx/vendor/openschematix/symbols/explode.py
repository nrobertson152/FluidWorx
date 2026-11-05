"""Open an existing symbol for editing ("import and explode").

Converts any symbol - built-in, user library or project-embedded - into a
custom symbol document (see custom.py) whose primitives the symbol editor can
edit individually, keeping every connection point's identifier, position,
lead direction, port type and display name.

Built-in symbols are defined with arcs already sampled into polylines (see
base.arc), so a polyline whose points lie evenly on a circle is turned back
into a native arc (or circle) here; everything else is kept exactly as drawn.

Terminal identifiers are kept as pin ids, so a derived symbol connects the
same way as the original: wires reference terminals by id, and replacing a
placed symbol by its derivative keeps the wires on terminals that still exist.

Every conversion is checked against its source (conversion_losses): if the
custom-symbol format cannot hold a primitive, an attribute or a connection
point exactly - an unknown primitive kind, text longer or larger than the
format allows, an off-grid pin, an unknown port type - SymbolImportError is
raised naming what would be lost, instead of the copy silently dropping or
altering it.
"""
from __future__ import annotations

import copy
import json
import math

from .base import SymbolDef
from .custom import CATEGORIES, PRIM_KINDS, SymbolFormatError, blank_symbol, new_symbol_id, normalise

MAX_REPORTED = 8         # problems listed in an error message


class SymbolImportError(SymbolFormatError):
    """An existing symbol cannot be converted into an editable custom symbol
    without losing or changing part of it. The message says what and why."""

MAX_STEP_DEG = 15.0      # sampled arcs use <= 12.5 deg steps; regular polygons use far larger ones
MIN_POINTS = 5


def _fit_circle(pts):
    """Least-squares (Kasa) circle fit; None if the points are (nearly) collinear."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    suu = svv = suv = suuu = svvv = suvv = svuu = 0.0
    for x, y in pts:
        u, v = x - mx, y - my
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return None
    a = 0.5 * (suuu + suvv)
    b = 0.5 * (svvv + svuu)
    uc = (a * svv - b * suv) / det
    vc = (b * suu - a * suv) / det
    cx, cy = uc + mx, vc + my
    r = sum(math.hypot(x - cx, y - cy) for x, y in pts) / n
    return cx, cy, r


def _angle(cx, cy, p):
    """Angle in degrees, counter-clockwise as seen on screen (Y down), like geometry.arc_points."""
    return math.degrees(math.atan2(-(p[1] - cy), p[0] - cx))


def recognise_arc(prim: dict) -> dict | None:
    """Return an arc (or circle) primitive equivalent to a sampled-arc
    polyline, or None if `prim` is not one."""
    if prim.get("k") != "line":
        return None
    pts = [tuple(p) for p in prim["pts"]]
    if len(pts) < MIN_POINTS:
        return None
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    chord = math.hypot(x1 - x0, y1 - y0)
    if chord > 1e-9:       # reject straight runs: points must bulge away from the chord
        bulge = max(abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / chord for x, y in pts)
        if bulge < 0.2:
            return None
    fit = _fit_circle(pts)
    if fit is None:
        return None
    cx, cy, r = fit
    if not (0.5 <= r <= 10000):
        return None
    if max(abs(math.hypot(x - cx, y - cy) - r) for x, y in pts) > max(0.02, r * 1e-3):
        return None
    steps = []
    for a, b in zip(pts, pts[1:]):
        d = (_angle(cx, cy, b) - _angle(cx, cy, a) + 180.0) % 360.0 - 180.0
        steps.append(d)
    mean = sum(steps) / len(steps)
    if abs(mean) < 1e-6 or abs(mean) > MAX_STEP_DEG:
        return None
    if any((d > 0) != (mean > 0) or abs(d - mean) > max(0.05, abs(mean) * 0.01) for d in steps):
        return None
    extent = sum(steps)
    if abs(extent) > 360.0 + 1e-6:
        return None
    style = {"w": prim.get("w", "normal"), "dash": bool(prim.get("dash", False))}
    c = (round(cx, 4), round(cy, 4))
    r = round(r, 4)
    if abs(abs(extent) - 360.0) < 0.5:
        return {"k": "circle", "c": c, "r": r, "fill": False, **style}
    start = _angle(cx, cy, pts[0])
    if extent < 0:                       # same arc, counter-clockwise from its other end
        start, extent = start + extent, -extent
    return {"k": "arc", "c": c, "r": r, "start": round(start % 360.0, 4), "extent": round(extent, 4), **style}


def recognise_arcs(prims) -> list:
    out = []
    for p in prims:
        out.append(recognise_arc(p) or p)
    return out


def _plain(prim: dict) -> dict:
    """JSON-friendly copy (tuples -> lists) of a primitive."""
    q = copy.deepcopy(prim)
    if "pts" in q:
        q["pts"] = [[float(x), float(y)] for x, y in q["pts"]]
    for key in ("c", "p"):
        if key in q:
            q[key] = [float(q[key][0]), float(q[key][1])]
    return q


# ---------------------------------------------------------------- fidelity check
def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _same(a, b, tol=1e-6) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_num(a) and _is_num(b):
        return abs(float(a) - float(b)) <= tol
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a)
    return a == b


def _absent_ok(key, val, src) -> bool:
    """True if `key` may be missing from the converted primitive without loss:
    false/empty flags, and an arrow size on a line without arrow heads."""
    if val is False or val is None or val == "":
        return True
    return key == "arrow_size" and not (src.get("arrow_start") or src.get("arrow_end"))


def _arc_losses(what, src, dst, tol=0.05) -> list[str]:
    """A sampled-arc polyline replaced by a native arc/circle: every sampled
    point must lie on it, within the angular sweep, and the arc must end where
    the polyline ended."""
    out = []
    (cx, cy), r = dst["c"], dst["r"]
    if any(abs(math.hypot(x - cx, y - cy) - r) > tol for x, y in src["pts"]):
        out.append(f"{what}: the curve is not a circular arc and would change shape")
    if dst["k"] == "arc":
        start = dst["start"]
        extent = dst["extent"]
        def at(deg):
            a = math.radians(deg)
            return cx + r * math.cos(a), cy - r * math.sin(a)
        ends = [at(start), at(start + extent)]
        for p in (src["pts"][0], src["pts"][-1]):
            if min(math.dist(p, e) for e in ends) > tol:
                out.append(f"{what}: the arc would not end at ({p[0]:g}, {p[1]:g})")
                break
        for p in src["pts"]:
            ang = math.degrees(math.atan2(-(p[1] - cy), p[0] - cx))
            if extent >= 0:
                rel = (ang - start) % 360.0
                if rel > extent + 1.0 and (360.0 - rel) > 1.0:
                    out.append(f"{what}: point ({p[0]:g}, {p[1]:g}) does not lie on the arc sweep")
                    break
            else:
                rel = (start - ang) % 360.0
                if rel > (-extent) + 1.0 and (360.0 - rel) > 1.0:
                    out.append(f"{what}: point ({p[0]:g}, {p[1]:g}) does not lie on the arc sweep")
                    break
    for key in ("w", "dash"):
        if key in src and not _same(src[key], dst.get(key)):
            out.append(f"{what}: '{key}' would change from {src[key]!r} to {dst.get(key)!r}")
    return out


def _prim_losses(i, src, dst) -> list[str]:
    kind = src.get("k")
    what = f"primitive {i + 1} ({kind})"
    if kind == "line" and dst["k"] in ("arc", "circle"):
        return _arc_losses(what, src, dst)
    if dst["k"] != kind:
        return [f"{what} would become a {dst['k']}"]
    out = []
    for key, val in src.items():
        if key not in dst:
            if not _absent_ok(key, val, src):
                out.append(f"{what}: attribute '{key}' is not supported by custom symbols")
        elif not _same(val, dst[key]):
            out.append(f"{what}: '{key}' would change from {val!r} to {dst[key]!r}")
    return out


def _kind_problems(src_prims) -> list[str]:
    out = []
    for i, p in enumerate(src_prims):
        if not isinstance(p, dict) or p.get("k") not in PRIM_KINDS:
            kind = p.get("k") if isinstance(p, dict) else type(p).__name__
            out.append(f"primitive {i + 1} is a '{kind}', which custom symbols cannot store")
    return out


def conversion_losses(src_prims, src_pins, doc) -> list[str]:
    """What the custom-symbol document `doc` lost or changed compared with the
    intended primitives and pins (pin dicts in the custom-symbol layout).
    Empty if the conversion is faithful."""
    out = _kind_problems(src_prims)
    if out:
        return out
    if len(src_prims) != len(doc["prims"]):
        out.append(f"{len(src_prims)} primitives would become {len(doc['prims'])}")
    else:
        for i, (s, d) in enumerate(zip(src_prims, doc["prims"])):
            out += _prim_losses(i, s, d)
    if len(src_pins) != len(doc["pins"]):
        out.append(f"{len(src_pins)} connection points would become {len(doc['pins'])}")
        return out
    for s, d in zip(src_pins, doc["pins"]):
        label = s.get("name") or s.get("id") or d["id"]
        for key, val in s.items():
            if not _same(val, d.get(key)):
                out.append(f"connection point {label}: '{key}' would change from {val!r} to {d.get(key)!r}")
    return out


def _check(name, src_prims, src_pins, build):
    """Run `build()` (which normalises a document) and verify it against the
    source; raise SymbolImportError naming every loss."""
    try:
        doc = build()
    except SymbolImportError:
        raise
    except SymbolFormatError as e:
        problems = _kind_problems(src_prims) or [str(e)]
        raise SymbolImportError(_message(name, problems)) from e
    problems = conversion_losses(src_prims, src_pins, doc)
    if problems:
        raise SymbolImportError(_message(name, problems))
    return doc


def _message(name, problems) -> str:
    lines = [f"“{name}” cannot be converted into an editable symbol without losing part of it:"]
    lines += [f"• {p}" for p in problems[:MAX_REPORTED]]
    if len(problems) > MAX_REPORTED:
        lines.append(f"• … and {len(problems) - MAX_REPORTED} more")
    return "\n".join(lines)


# ---------------------------------------------------------------- conversion
def _as_copy(doc: dict) -> dict:
    src = {"id": doc["id"], "name": doc["name"], "revision": str(doc["revision"])}
    doc.update(id=new_symbol_id(), revision=0, name=f"{doc['name']} (copy)"[:120], derived_from=src)
    doc.pop("aliases", None)
    return doc


def symbol_to_doc(sd: SymbolDef, params: dict | None = None, as_copy: bool = True) -> dict:
    """Editable custom-symbol document for `sd`.

    `params` selects the variant of a parametric built-in (e.g. a configured
    valve). With `as_copy` (always the case for built-ins) the document gets a
    new id, revision 0, a "(copy)" name and a `derived_from` reference, so
    saving it can never overwrite the original. Without it a custom symbol is
    returned unchanged for in-place editing.

    The result shares no mutable data with `sd`. Raises SymbolImportError if
    the symbol cannot be converted faithfully."""
    if sd.is_custom:
        src = copy.deepcopy(sd.custom)
        doc = _check(sd.name, src.get("prims") or [], src.get("pins") or [], lambda: normalise(copy.deepcopy(src)))
        return normalise(_as_copy(doc)) if as_copy else doc
    g = sd.build(params)
    m = blank_symbol(f"{sd.name} (custom)", sd.category if sd.category in CATEGORIES else "General")
    m.update(description=sd.description, group=sd.group, prefix=sd.prefix,
             convention=f"Custom (based on {sd.convention})", tags=list(sd.keywords),
             derived_from={"id": sd.id, "name": sd.name})
    src_prims = [_plain(p) for p in g.prims]
    m["prims"] = [_plain(recognise_arc(p) or p) if p.get("k") == "line" else _plain(p) for p in g.prims]
    # Built-in designations preserve terminal show visibility (default True).
    m["pins"] = [{"id": t.name, "name": t.label or t.name, "x": float(t.x), "y": float(t.y), "dir": t.dir,
                  "type": sd.port_type(t), "show": bool(t.show)} for t in g.terminals]
    return _check(sd.name, src_prims, copy.deepcopy(m["pins"]), lambda: normalise(m))


def doc_from_data(data, as_copy: bool = True, name: str = "symbol") -> dict:
    """Editable custom-symbol document from a raw ``.osym`` document (parsed
    JSON). Like symbol_to_doc, a copy gets a new id and `derived_from`; raises
    SymbolFormatError for documents that are not symbols at all and
    SymbolImportError if anything in it would be lost."""
    if not isinstance(data, dict) or not isinstance(data.get("prims", []), list) \
            or not isinstance(data.get("pins", []), list):
        normalise(data)            # raises the format error
        raise SymbolFormatError("not an OpenSchematix symbol")
    src = copy.deepcopy(data)
    label = str(src.get("name") or name)
    for i, p in enumerate(src.get("pins") or []):
        if not isinstance(p, dict) or not str(p.get("id") or "").strip():
            raise SymbolImportError(f"“{label}” cannot be converted into an editable symbol without losing part of it:\n"
                                    f"• connection point {i + 1}: missing id")
    pins = copy.deepcopy(src.get("pins") or [])
    doc = _check(label, src.get("prims") or [], pins, lambda: normalise(copy.deepcopy(src)))
    return normalise(_as_copy(doc)) if as_copy else doc


def doc_from_file(path: str, as_copy: bool = True) -> dict:
    """Editable copy of the symbol in the ``.osym`` file at `path` (see
    doc_from_data). The file is only read. Raises OSError, SymbolFormatError
    (including invalid JSON) or SymbolImportError."""
    import os
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise SymbolFormatError(f"{os.path.basename(path)} is not a valid symbol file: {e}") from e
    return doc_from_data(data, as_copy, os.path.splitext(os.path.basename(path))[0])
