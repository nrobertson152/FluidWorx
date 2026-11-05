"""Symbol definition framework.

A symbol is described in *local* drawing units (see geometry.py) as a list of
primitives plus named terminals. Primitives are plain dicts so they serialise
trivially and every renderer (Tk canvas, SVG, PDF) consumes the same data:

    {"k": "line",   "pts": [(x, y), ...], "dash": bool, "w": "normal"|"thin"|"thick"}
    {"k": "poly",   "pts": [(x, y), ...], "fill": bool, ...}   closed polygon
    {"k": "circle", "c": (x, y), "r": r, "fill": bool, ...}
    {"k": "text",   "p": (x, y), "s": "M", "size": 8, "anchor": "c"}

Arcs are converted to polylines when the symbol is defined, so renderers never
need to transform arc angles under rotation/mirroring.

Terminals must lie on the 10-unit grid so that wires snap to them exactly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..geometry import GRID, arc_points, bbox_of, bbox_union

LINE_WIDTHS = {"thin": 1.0, "normal": 1.4, "thick": 2.2}  # units (0.25/0.35/0.55 mm)

# Conventions. Wording deliberately says "style": the drawings follow the
# published conventions as widely documented, but have not been verified
# against the official standard documents.
IEC = "IEC 60617 style"
IEEE = "IEEE 315 / ANSI Y32.2 style"
NEMA = "NEMA / JIC ladder style (IEEE 315)"
ISO = "ISO 1219-1 style"
ANSI = "ANSI Y32.10 style"
GENERIC = "Generic"


# Port types for connection points. The domain (the part before the first
# dot) is used by the drawing checker: ports of different domains must not be
# joined. See docs/VALIDATION.md.
PORT_TYPES = {
    "elec.passive": "Electrical, passive",
    "elec.input": "Electrical, input",
    "elec.output": "Electrical, output",
    "elec.bidir": "Electrical, bidirectional",
    "elec.power": "Electrical, power supply",
    "elec.ground": "Electrical, earth / ground",
    "hyd.pressure": "Hydraulic, pressure (P)",
    "hyd.tank": "Hydraulic, tank / return (T)",
    "hyd.work": "Hydraulic, work port (A, B)",
    "hyd.pilot": "Hydraulic, pilot (X, Y)",
    "hyd.drain": "Hydraulic, drain (L)",
    "pneu.supply": "Pneumatic, supply (1)",
    "pneu.work": "Pneumatic, work port (2, 4)",
    "pneu.exhaust": "Pneumatic, exhaust (3, 5)",
    "pneu.pilot": "Pneumatic, pilot (12, 14)",
    "any": "Any (no checking)",
}
CATEGORY_DOMAIN = {"Electrical": "elec", "Electronic": "elec", "Hydraulic": "hyd", "Pneumatic": "pneu"}


# Drafting elements: symbols that are drawn but carry no fluid/electrical function of their own (valve
# operators shown on their own, direction arrows, energy triangles, enclosure lines). They are the only
# built-in symbols allowed to have no terminals, and they never appear in the BOM (empty designator prefix).
DRAFTING_GROUPS = ("Valve operators", "Drafting")


def is_drafting_element(sd) -> bool:
    return sd.group in DRAFTING_GROUPS and not sd.prefix


def port_domain(ptype: str) -> str:
    return (ptype or "any").split(".", 1)[0]


# ---------------------------------------------------------------- primitives
def line(*coords, dash=False, w="normal"):
    pts = list(zip(coords[::2], coords[1::2]))
    return {"k": "line", "pts": pts, "dash": dash, "w": w}


def polyline(pts, dash=False, w="normal"):
    return {"k": "line", "pts": [tuple(p) for p in pts], "dash": dash, "w": w}


def poly(*coords, fill=False, w="normal"):
    pts = list(zip(coords[::2], coords[1::2]))
    return {"k": "poly", "pts": pts, "fill": fill, "dash": False, "w": w}


def rect(x1, y1, x2, y2, fill=False, dash=False, w="normal"):
    return {"k": "poly", "pts": [(x1, y1), (x2, y1), (x2, y2), (x1, y2)], "fill": fill, "dash": dash, "w": w}


def circle(cx, cy, r, fill=False, w="normal", dash=False):
    return {"k": "circle", "c": (cx, cy), "r": r, "fill": fill, "w": w, "dash": dash}


def arc(cx, cy, r, start, extent, w="normal", dash=False):
    return {"k": "line", "pts": arc_points(cx, cy, r, start, extent), "dash": dash, "w": w}


def text(x, y, s, size=8, anchor="c"):
    return {"k": "text", "p": (x, y), "s": s, "size": size, "anchor": anchor}


def arrowhead(tip, frm, length=4.0, half_width=1.8, fill=True):
    """Filled triangular arrow head with its tip at `tip`, pointing away from `frm`."""
    dx, dy = tip[0] - frm[0], tip[1] - frm[1]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    bx, by = tip[0] - ux * length, tip[1] - uy * length
    px, py = -uy * half_width, ux * half_width
    return poly(tip[0], tip[1], bx + px, by + py, bx - px, by - py, fill=fill, w="thin")


def arrow(x1, y1, x2, y2, head=4.0, w="normal", dash=False):
    """Line from (x1,y1) to (x2,y2) with an arrow head at the second point."""
    return [line(x1, y1, x2, y2, w=w, dash=dash), arrowhead((x2, y2), (x1, y1), length=head)]


def zigzag(x1, y1, x2, y2, n=6, amp=4.0):
    """Zig-zag between two points (used for springs and ANSI resistors)."""
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    px, py = -uy, ux
    pts = [(x1, y1)]
    for i in range(n):
        t = (i + 0.5) / n
        s = amp if i % 2 == 0 else -amp
        pts.append((x1 + dx * t + px * s, y1 + dy * t + py * s))
    pts.append((x2, y2))
    return polyline(pts)


# ---------------------------------------------------------------- definitions
@dataclass(frozen=True)
class Terminal:
    name: str
    x: float
    y: float
    # Outward direction of the lead: "l", "r", "u", "d" (used for routing hints).
    dir: str = "r"
    label: str = ""     # displayed identifier (defaults to name)
    ptype: str = ""     # port type, see PORT_TYPES ("" = derived from the symbol category)
    # Whether the designation is drawn when terminal designations are shown
    # (project setting). A user override on a placed component is always drawn.
    show: bool = True


@dataclass
class Geometry:
    prims: list
    terminals: list[Terminal]

    def bbox(self):
        b = None
        for p in self.prims:
            b = bbox_union(b, prim_bbox(p))
        for t in self.terminals:
            b = bbox_union(b, (t.x, t.y, t.x, t.y))
        return b or (-10, -10, 10, 10)


def prim_bbox(p):
    k = p["k"]
    if k in ("line", "poly"):
        return bbox_of(p["pts"])
    if k == "circle":
        (cx, cy), r = p["c"], p["r"]
        return (cx - r, cy - r, cx + r, cy + r)
    if k == "region":
        from ..regions import rings_bbox
        return rings_bbox(p["rings"])
    if k == "text":
        x, y = p["p"]
        h = p.get("size", 8)
        w = h * 0.6 * max(1, len(p["s"]))
        return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    return None


@dataclass
class SymbolDef:
    id: str
    name: str
    category: str          # top-level library category
    group: str             # sub-category
    convention: str        # drawing convention, e.g. IEC 60617 style
    description: str
    prefix: str            # default reference-designator prefix
    geometry: Optional[Geometry] = None
    builder: Optional[Callable[[dict], Geometry]] = None  # for parametric symbols
    default_params: dict = field(default_factory=dict)
    keywords: tuple = ()
    notes: str = ""        # limitations / simplifications, shown to the user
    custom: Optional[dict] = None   # source document of a user-defined symbol
    aliases: tuple = ()             # extra identifiers that resolve to this symbol (custom symbols)

    @property
    def is_custom(self) -> bool:
        return self.custom is not None

    def port_type(self, terminal) -> str:
        from .custom import default_ptype
        return terminal.ptype or default_ptype(self.category, terminal.name)

    @property
    def parametric(self) -> bool:
        return self.builder is not None

    def build(self, params: Optional[dict] = None) -> Geometry:
        if self.builder is not None:
            merged = dict(self.default_params)
            if params:
                merged.update(params)
            return self.builder(merged)
        return self.geometry

    def search_text(self) -> str:
        return " ".join([self.name, self.category, self.group, self.convention, self.description, self.prefix,
                         *self.keywords, *self.aliases]).lower()


def validate_geometry(g: Geometry) -> list[str]:
    """Return a list of problems (empty if OK). Used by tests and at load time."""
    problems = []
    names = [t.name for t in g.terminals]
    if len(set(names)) != len(names):
        problems.append(f"duplicate terminal names {names}")
    for t in g.terminals:
        if abs(t.x / GRID - round(t.x / GRID)) > 1e-6 or abs(t.y / GRID - round(t.y / GRID)) > 1e-6:
            problems.append(f"terminal {t.name} off grid at ({t.x}, {t.y})")
        if t.dir not in ("l", "r", "u", "d"):
            problems.append(f"terminal {t.name} has bad direction {t.dir}")
    for p in g.prims:
        if p["k"] not in ("line", "poly", "circle", "text"):
            problems.append(f"unknown primitive {p['k']}")
        if p["k"] in ("line", "poly") and len(p["pts"]) < 2:
            problems.append("primitive with fewer than 2 points")
    return problems


def flatten_prims(prims) -> list:
    """Convert native arcs ({"k": "arc", c, r, start, extent}) to polylines so
    renderers only see line/poly/circle/text."""
    out = []
    for p in prims:
        if p.get("k") == "arc":
            cx, cy = p["c"]
            out.append({"k": "line", "pts": arc_points(cx, cy, p["r"], p["start"], p["extent"],
                                                         max(6, int(abs(p["extent"]) / 6))),
                        "dash": p.get("dash", False), "w": p.get("w", "normal")})
        else:
            out.append(p)
    return out
