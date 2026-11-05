"""User-defined (custom) symbols.

A custom symbol is stored as a small JSON document (``.osym``):

    {
      "format": "OpenSchematix Symbol", "version": 1,
      "id": "user:3f2a9c1e5b7d4e10",
      "revision": 3,
      "name": "Proximity sensor, PNP", "description": "...",
      "category": "Electrical", "group": "Sensors", "tags": ["sensor", "pnp"],
      "prefix": "B", "convention": "Custom",
      "properties": {"manufacturer": "...", ...},
      "prims": [ {"k": "line", "pts": [[x, y], ...], "w": "normal", "dash": false},
                 {"k": "poly", ...}, {"k": "circle", "c": [x, y], "r": r, "fill": false},
                 {"k": "arc", "c": [x, y], "r": r, "start": deg, "extent": deg},
                 {"k": "text", "p": [x, y], "s": "M", "size": 8, "anchor": "c"} ],
      "pins": [ {"id": "p1", "name": "1", "x": -20, "y": 0, "dir": "l",
                 "type": "elec.passive", "show": true} ],
      "derived_from": {"id": "el.relay.coil", "name": "...", "revision": "2"},
      "aliases": ["PNP-PROX", "B.prox"]
    }

Coordinates are symbol-local drawing units (0.25 mm) relative to the
insertion point (the origin). Pins must lie on the 10-unit grid. A pin's
``id`` is its permanent key: wires reference pins by id, so renaming or
renumbering a pin never disconnects existing drawings.

``aliases`` are extra identifiers for the same symbol (letters, digits and
``. _ + - /``; case-insensitive). They are found by the library search and
INSERT and resolve to the symbol (``symbols.resolve``); drawings always
store the canonical ``id``. Aliases must not equal any symbol id, another
symbol's alias or another symbol's name (``alias_problems``). Older versions
ignore the field.
"""
from __future__ import annotations

import copy
import json
import math
import re
import uuid

from ..geometry import GRID
from .base import (CATEGORY_DOMAIN, GENERIC, PORT_TYPES, Geometry, SymbolDef, Terminal, flatten_prims,
                   validate_geometry)

SYMBOL_FORMAT = "OpenSchematix Symbol"
SYMBOL_VERSION = 1
USER_PREFIX = "user:"
CATEGORIES = ("Electrical", "Electronic", "Hydraulic", "Pneumatic", "General")
PRIM_KINDS = ("line", "poly", "circle", "arc", "text")
ALIAS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-/]{0,59}")
MAX_ALIASES = 20
MAX_SYMBOL_BYTES = 2 * 1024 * 1024  # ordinary .osym files are much smaller
MAX_SYMBOL_JSON_DEPTH = 64


class SymbolFormatError(ValueError):
    """Raised when a custom symbol document is malformed or unsupported."""
    pass


def parse_symbol_json(text: str, *, source: str = "") -> dict:
    """Decode bounded JSON with deterministic input errors and a nesting limit.

    This helper also validates the object shape. It does not normalise a symbol;
    package manifests use it before their own schema checks.
    """
    where = f" in {source}" if source else ""
    if text is None or not isinstance(text, str) or not text.strip():
        raise SymbolFormatError(f"symbol JSON is empty or truncated{where}")
    if len(text) > MAX_SYMBOL_BYTES or len(text.encode("utf-8")) > MAX_SYMBOL_BYTES:
        raise SymbolFormatError(f"symbol JSON exceeds {MAX_SYMBOL_BYTES} bytes{where}")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError, ValueError) as e:
        raise SymbolFormatError(f"invalid JSON{where}: {e}") from e
    if not isinstance(data, dict):
        raise SymbolFormatError(f"symbol document must be a JSON object{where}")
    pending = [(data, 1)]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_SYMBOL_JSON_DEPTH:
            raise SymbolFormatError(f"JSON nesting exceeds {MAX_SYMBOL_JSON_DEPTH} levels{where}")
        if isinstance(node, dict):
            pending.extend((v, depth + 1) for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            pending.extend((v, depth + 1) for v in node if isinstance(v, (dict, list)))
    return data


def load_symbol_json(text: str, *, source: str = "") -> dict:
    """Parse and normalise a bounded symbol document.

    Raises SymbolFormatError for malformed JSON, invalid containers or excessive
    nesting. Normalisation retains the established legacy symbol semantics.
    """
    return normalise(parse_symbol_json(text, source=source))


def _array(data: dict, name: str):
    """A symbol array field, accepting omitted/null values for legacy files."""
    value = data.get(name)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise SymbolFormatError(f"{name}: expected an array")
    return value


def new_symbol_id() -> str:
    return USER_PREFIX + uuid.uuid4().hex[:16]


def blank_symbol(name="New symbol", category="Electrical") -> dict:
    return {"format": SYMBOL_FORMAT, "version": SYMBOL_VERSION, "id": new_symbol_id(), "revision": 0,
            "name": name, "description": "", "category": category, "group": "Custom", "tags": [],
            "prefix": "U", "convention": "Custom", "properties": {}, "prims": [], "pins": []}


def _num(v, what):
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError) as e:
        raise SymbolFormatError(f"{what}: not a number") from e
    if f != f or abs(f) > 1e6:
        raise SymbolFormatError(f"{what}: out of range")
    return f


def _pt(v, what):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise SymbolFormatError(f"{what}: expected [x, y]")
    return (_num(v[0], what), _num(v[1], what))


def normalise(data) -> dict:
    """Validate and clean a symbol document. Raises SymbolFormatError."""
    if not isinstance(data, dict):
        raise SymbolFormatError(
            "not an OpenSchematix symbol: document must be a JSON object with "
            f"format={SYMBOL_FORMAT!r}"
        )
    if data.get("format") != SYMBOL_FORMAT:
        got = data.get("format")
        raise SymbolFormatError(
            f"not an OpenSchematix symbol: expected format {SYMBOL_FORMAT!r}, got {got!r}"
        )
    ver = data.get("version", 1)
    if not isinstance(ver, int):
        raise SymbolFormatError(
            f"symbol format version must be an integer, got {type(ver).__name__}"
        )
    if ver < 1:
        raise SymbolFormatError(f"unsupported schema version {ver} (minimum is 1)")
    if ver > SYMBOL_VERSION:
        raise SymbolFormatError(
            f"symbol format version {ver} is newer than this program supports "
            f"(supports up to {SYMBOL_VERSION})"
        )
    sid = str(data.get("id", ""))
    if not sid.startswith(USER_PREFIX) or len(sid) <= len(USER_PREFIX):
        raise SymbolFormatError(
            "custom symbol ids must start with 'user:' followed by a unique suffix "
            f"(got {sid!r})"
        )
    rev_raw = data.get("revision", 0)
    if rev_raw is None or rev_raw == "":
        rev_raw = 0
    if isinstance(rev_raw, bool) or not isinstance(rev_raw, int):
        raise SymbolFormatError(
            f"revision must be a non-negative integer, got {type(rev_raw).__name__}"
        )
    if rev_raw < 0:
        raise SymbolFormatError(f"revision must be non-negative, got {rev_raw}")
    properties = data.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise SymbolFormatError("properties: expected an object")
    out = {"format": SYMBOL_FORMAT, "version": SYMBOL_VERSION, "id": sid,
           "revision": rev_raw,
           "name": str(data.get("name") or "Unnamed symbol")[:120],
           "description": str(data.get("description", ""))[:2000],
           "category": str(data.get("category") or "General"),
           "group": str(data.get("group") or "Custom")[:80],
           "tags": [str(t)[:40] for t in _array(data, "tags") if str(t).strip()][:30],
           "prefix": str(data.get("prefix", "U"))[:8],
           "convention": str(data.get("convention") or "Custom")[:60],
           "properties": {str(k): str(v) for k, v in properties.items()},
           "prims": [], "pins": []}
    src = data.get("derived_from")
    if isinstance(src, dict):
        src = {k: str(src[k])[:120] for k in ("id", "name", "revision") if src.get(k) not in (None, "")}
        if src.get("id"):
            out["derived_from"] = src
    aliases = clean_aliases(data.get("aliases"), sid)
    if aliases:
        out["aliases"] = aliases
    for i, p in enumerate(_array(data, "prims")):
        if not isinstance(p, dict) or p.get("k") not in PRIM_KINDS:
            raise SymbolFormatError(f"primitive {i}: unknown kind")
        k = p["k"]
        q = {"k": k}
        w = p.get("w", "normal")
        q["w"] = w if w in ("thin", "normal", "thick") else "normal"
        q["dash"] = bool(p.get("dash", False))
        if k in ("line", "poly"):
            pts = [_pt(v, f"primitive {i}") for v in _array(p, "pts")]
            if len(pts) < 2:
                raise SymbolFormatError(f"primitive {i}: needs at least two points")
            q["pts"] = pts
            if k == "line":
                start = p.get("arrow_start") is True
                end = p.get("arrow_end") is True
                if start or end:
                    q["arrow_start"] = start
                    q["arrow_end"] = end
                try:
                    size = float(p.get("arrow_size", 10.0))
                    if isinstance(p.get("arrow_size"), bool) or not math.isfinite(size) or not 0 < size <= 10000:
                        size = 10.0
                except (ValueError, TypeError, OverflowError):
                    size = 10.0
                if start or end:
                    q["arrow_size"] = size
            if k == "poly":
                q["fill"] = bool(p.get("fill", False))
        elif k in ("circle", "arc"):
            q["c"] = _pt(p.get("c"), f"primitive {i}")
            q["r"] = _num(p.get("r"), f"primitive {i}")
            if q["r"] <= 0:
                raise SymbolFormatError(f"primitive {i}: radius must be positive")
            if k == "circle":
                q["fill"] = bool(p.get("fill", False))
            else:
                q["start"] = _num(p.get("start", 0), f"primitive {i}")
                q["extent"] = _num(p.get("extent", 90), f"primitive {i}")
        else:
            q = {"k": "text", "p": _pt(p.get("p"), f"primitive {i}"), "s": str(p.get("s", ""))[:200],
                 "size": max(2.0, min(80.0, _num(p.get("size", 8), f"primitive {i}"))),
                 "anchor": p.get("anchor", "c") if p.get("anchor") in ("c", "n", "s", "e", "w", "nw", "ne", "sw", "se")
                 else "c"}
        out["prims"].append(q)
    seen = set()
    for i, p in enumerate(_array(data, "pins")):
        if not isinstance(p, dict):
            raise SymbolFormatError(f"pin {i}: invalid")
        pid = str(p.get("id") or f"p{i + 1}")
        if pid in seen:
            raise SymbolFormatError(f"pin {i}: duplicate id {pid}")
        seen.add(pid)
        x, y = _num(p.get("x"), f"pin {pid}"), _num(p.get("y"), f"pin {pid}")
        if abs(x / GRID - round(x / GRID)) > 1e-6 or abs(y / GRID - round(y / GRID)) > 1e-6:
            raise SymbolFormatError(f"pin {p.get('name') or pid} is not on the {GRID}-unit grid")
        d = p.get("dir", "r")
        ptype = p.get("type", "") or ""
        if not isinstance(ptype, str):
            raise SymbolFormatError(f"pin {pid}: port type must be a string")
        out["pins"].append({"id": pid, "name": str(p.get("name") or pid)[:20], "x": x, "y": y,
                            "dir": d if d in ("l", "r", "u", "d") else "r",
                            "type": ptype if ptype in PORT_TYPES else "",
                            "show": bool(p.get("show", True))})
    return out


def clean_aliases(values, own_id: str = "") -> list[str]:
    """Valid, distinct (case-insensitive) aliases in their given order."""
    if not isinstance(values, (list, tuple)):
        return []
    out, seen = [], {own_id.lower()} if own_id else set()
    for v in values:
        a = str(v).strip() if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
        if a and ALIAS_RE.fullmatch(a) and a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out[:MAX_ALIASES]


def alias_problems(aliases, own_id: str, others) -> list[str]:
    """Problems with assigning `aliases` to symbol `own_id` (empty list if none)."""
    problems, seen = [], set()
    ids, owners, names = {}, {}, {}
    for sid, als, *rest in others:
        if sid == own_id:
            continue
        ids[sid.lower()] = sid
        for a in als or ():
            owners.setdefault(str(a).lower(), sid)
        if rest and rest[0]:
            names.setdefault(str(rest[0]).strip().lower(), rest[0])
    if len(aliases) > MAX_ALIASES:
        problems.append(f"at most {MAX_ALIASES} aliases are allowed")
    for a in aliases:
        low = a.lower()
        if low in seen:
            problems.append(f"\u201c{a}\u201d is listed twice")
        elif low == own_id.lower():
            problems.append(f"\u201c{a}\u201d is this symbol's own identifier")
        elif low in ids:
            problems.append(f"\u201c{a}\u201d is the identifier of another symbol ({ids[low]})")
        elif low in owners:
            problems.append(f"\u201c{a}\u201d is already an alias of another symbol ({owners[low]})")
        elif low in names:
            problems.append(f"\u201c{a}\u201d is the name of another symbol (\u201c{names[low]}\u201d)")
        elif not ALIAS_RE.fullmatch(a):
            problems.append(f"\u201c{a}\u201d is not a valid alias (use letters, digits and . _ + - /, no spaces, "
                            f"at most 60 characters)")
        seen.add(low)
    return problems


def build_geometry(doc: dict) -> Geometry:
    prims = [copy.deepcopy(p) for p in doc["prims"]]
    for p in prims:
        if "pts" in p:
            p["pts"] = [tuple(v) for v in p["pts"]]
        for key in ("c", "p"):
            if key in p:
                p[key] = tuple(p[key])
    prims = flatten_prims(prims)
    from ..shapes import arrowhead_points
    arrows = []
    for p in prims:
        if p.get("k") != "line" or len(p.get("pts", [])) < 2:
            continue
        pts = p["pts"]
        for start, enabled in ((True, p.get("arrow_start")), (False, p.get("arrow_end"))):
            if not enabled:
                continue
            tip = pts[0] if start else pts[-1]
            for neighbor in (pts[1:] if start else reversed(pts[:-1])):
                if math.dist(tip, neighbor) > 1e-9:
                    triangle = arrowhead_points(tip, neighbor, p.get("arrow_size", 10.0))
                    if triangle:
                        arrows.append({"k": "poly", "pts": triangle, "fill": True, "w": p.get("w", "normal")})
                    break
    prims.extend(arrows)
    terms = [Terminal(p["id"], p["x"], p["y"], p["dir"], label=p["name"], ptype=p.get("type", ""),
                      show=bool(p.get("show", True)))
             for p in doc["pins"]]
    return Geometry(prims, terms)


def to_symdef(doc: dict) -> SymbolDef:
    doc = normalise(doc)
    g = build_geometry(doc)
    problems = validate_geometry(g)
    if problems:
        raise SymbolFormatError("; ".join(problems))
    sd = SymbolDef(doc["id"], doc["name"], doc["category"], doc["group"], doc["convention"] or GENERIC,
                   doc["description"], doc["prefix"], g, keywords=tuple(doc["tags"]),
                   aliases=tuple(doc.get("aliases", ())))
    sd.custom = doc
    return sd


def default_ptype(category: str, terminal_name: str) -> str:
    dom = CATEGORY_DOMAIN.get(category)
    n = terminal_name.upper()
    if dom == "hyd":
        if n == "P":
            return "hyd.pressure"
        if n == "T":
            return "hyd.tank"
        if n in ("X", "Y"):
            return "hyd.pilot"
        if n == "L":
            return "hyd.drain"
        return "hyd.work"
    if dom == "pneu":
        if n == "1":
            return "pneu.supply"
        if n in ("3", "5"):
            return "pneu.exhaust"
        if n in ("12", "14"):
            return "pneu.pilot"
        return "pneu.work"
    if dom == "elec":
        return "elec.passive"
    return "any"
