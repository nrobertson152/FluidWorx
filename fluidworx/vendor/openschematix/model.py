"""Schematic document model (no GUI dependencies).

Object identity
---------------
Every object on a sheet (component, wire, shape) has an integer id that is
unique within its sheet and never reused while the sheet exists; ids are
written to the file, so they persist across sessions. Each sheet has a
persistent ``uid`` (random hex) that is unique within the project, so the pair
``(sheet.uid, object.id)`` identifies any object in a project permanently.
Revision comparison, search navigation and cross-sheet references are all
based on these identifiers, never on screen coordinates.

A :class:`Document` is one schematic sheet. A :class:`~openschematix.project.Project`
holds an ordered list of sheets plus project-wide metadata.
"""
from __future__ import annotations

import copy
import json
import math
import uuid
from dataclasses import dataclass, field
from typing import Optional

from . import symbols
from .geometry import Point, bbox_of, bbox_union, clean, norm_rotation, simplify_orthogonal, xform

# ---------------------------------------------------------------- sheet sizes
# (width, height) in millimetres, landscape.
SHEET_SIZES_MM = {
    "A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210),
    "ANSI A": (279.4, 215.9), "ANSI B": (431.8, 279.4), "ANSI C": (558.8, 431.8),
    "ANSI D": (863.6, 558.8), "ANSI E": (1117.6, 863.6),
    "Letter": (279.4, 215.9), "Legal": (355.6, 215.9), "Tabloid": (431.8, 279.4),
}
SHEET_SIZE_GROUPS = (("ISO A-series", ("A0", "A1", "A2", "A3", "A4")),
                     ("ANSI", ("ANSI A", "ANSI B", "ANSI C", "ANSI D", "ANSI E")),
                     ("North American", ("Letter", "Legal", "Tabloid")))
CUSTOM_SIZE = "Custom"
WIRE_STYLES = ("solid", "dashed")
TEXT_SIDES = ("auto", "above", "below", "left", "right")
TITLE_BLOCKS = ("standard", "compact", "iso", "none")
TITLE_BLOCK_NAMES = {"standard": "Standard", "compact": "Compact", "iso": "ISO 7200 style", "none": "None"}

# Standard component property keys (anything else in Component.props is a
# user-defined custom property).
STANDARD_PROPS = ("description", "manufacturer", "part_number", "rating", "terminal")
PROP_LABELS = {"description": "Description", "manufacturer": "Manufacturer", "part_number": "Part number",
               "rating": "Rating", "terminal": "Terminal no."}

DEFAULT_LAYER_COMPONENTS = "Components"
DEFAULT_LAYER_WIRES = "Wires"
DEFAULT_LAYER_SHAPES = "Drafting"


def new_uid() -> str:
    return uuid.uuid4().hex[:16]


def _str_dict(d) -> dict:
    if not isinstance(d, dict):
        return {}
    return {str(k): str(v) for k, v in d.items() if v is not None}


# ---------------------------------------------------------------- reading helpers
# The from_dict readers below take data from files. For malformed input they
# raise ValueError with the location of the problem (never TypeError,
# AttributeError, IndexError or OverflowError), so file loaders can report
# every damaged file as such, and any other exception is a programming defect.
# Values the engine has always normalised (rotation, styles, page setup) are
# still normalised; wrong container types, missing required fields and
# non-finite numbers are errors.
def _obj(v, what: str) -> dict:
    if not isinstance(v, dict):
        raise ValueError(f"{what} must be an object, not {_kind(v)}")
    return v


def _seq(v, what: str, default=None) -> list:
    if v is None and default is not None:
        return default
    if not isinstance(v, list):
        raise ValueError(f"{what} must be a list, not {_kind(v)}")
    return v


def _req(d: dict, key: str, what: str):
    if key not in d:
        raise ValueError(f"{what} has no '{key}'")
    return d[key]


def _kind(v) -> str:
    """Type of a JSON value in words (never the value: it may be private)."""
    return {dict: "an object", list: "a list", str: "text", bool: "true/false", type(None): "null"}.get(
        type(v), "a number" if isinstance(v, (int, float)) else type(v).__name__)


def _num(v, what: str) -> float:
    """Finite float from a number (or numeric text, as earlier versions accepted)."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ValueError(f"{what} must be a number, not {_kind(v)}")
    try:
        f = float(v)
    except (ValueError, OverflowError):
        raise ValueError(f"{what} must be a number") from None
    if not math.isfinite(f):
        raise ValueError(f"{what} must be a finite number")
    return f


def _int(v, what: str) -> int:
    f = _num(v, what)
    if f != int(f) or abs(f) > 2 ** 53:
        raise ValueError(f"{what} must be a whole number")
    return int(f)


def _point(v, what: str) -> Point:
    if not isinstance(v, (list, tuple)) or len(v) < 2:
        raise ValueError(f"{what} must be an [x, y] pair")
    return (_num(v[0], f"{what} x"), _num(v[1], f"{what} y"))


def _text(v, what: str, default: str = "") -> str:
    """Text field. Scalars are converted as before; containers are errors."""
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        raise ValueError(f"{what} must be text, not {_kind(v)}")
    return str(v)


def _rotation(v, what: str) -> int:
    """Any rotation snaps to a quarter turn; non-numbers mean 0 (as always).
    Non-finite values are damage and raise."""
    if isinstance(v, (int, float, str)) and not isinstance(v, bool):
        try:
            f = float(v)
        except (ValueError, OverflowError):
            return 0
        if not math.isfinite(f):
            raise ValueError(f"{what} must be a finite number")
        return norm_rotation(f)
    return 0


def _params(symbol_id: str, v, what: str) -> dict:
    """Parameters of a placed symbol. For built-in parametric symbols every
    known parameter must have the type of its default (text, or a list of
    text), because the symbol builders rely on it; unknown keys are kept and
    ignored, as before. Other symbols' parameters are kept as they are."""
    if v is None:
        return {}
    params = copy.deepcopy(_obj(v, f"{what} params"))
    sd = symbols.get(symbol_id) if symbols.is_builtin(symbol_id) else None
    for k, default in ((sd.default_params or {}) if sd is not None else {}).items():
        if k not in params:
            continue
        val = params[k]
        if isinstance(default, list):
            elem = type(default[0]) if default else str      # every list parameter is a list of text
            ok = isinstance(val, list) and all(type(x) is elem for x in val)
            expected = f"a list of {_kind(elem())}"
        else:
            ok = type(val) is type(default)
            expected = _kind(default)
        if not ok:
            raise ValueError(f"{what} parameter '{k}' must be {expected}, not {_kind(val)}")
    return params


# ================================================================ component
@dataclass
class Component:
    id: int
    symbol: str
    x: float
    y: float
    rotation: int = 0
    mirror: bool = False
    designator: str = ""
    label: str = ""
    params: dict = field(default_factory=dict)
    text_side: str = "auto"   # auto | above | below | left | right
    props: dict = field(default_factory=dict)            # str -> str (see STANDARD_PROPS)
    terminal_labels: dict = field(default_factory=dict)  # terminal name -> displayed identifier
    layer: str = DEFAULT_LAYER_COMPONENTS
    locked: bool = False
    group: str = ""
    in_bom: bool = True

    def geometry(self):
        return symbols.geometry(self.symbol, self.params or None)

    def symdef(self):
        return symbols.get(self.symbol)

    def local_to_world(self, x, y) -> Point:
        dx, dy = xform(x, y, self.rotation, self.mirror)
        return (clean(self.x + dx), clean(self.y + dy))

    def terminals(self) -> dict[str, Point]:
        return {t.name: self.local_to_world(t.x, t.y) for t in self.geometry().terminals}

    def terminal_defs(self):
        return list(self.geometry().terminals)

    def terminal_label(self, name: str) -> str:
        """Displayed identifier of a terminal (user override, symbol label, or key)."""
        if self.terminal_labels.get(name):
            return self.terminal_labels[name]
        for t in self.geometry().terminals:
            if t.name == name:
                return t.label or t.name
        return name

    def terminal_dirs(self) -> dict[str, str]:
        out = {}
        vec = {"l": (-1, 0), "r": (1, 0), "u": (0, -1), "d": (0, 1)}
        for t in self.geometry().terminals:
            dx, dy = xform(*vec[t.dir], self.rotation, self.mirror)
            out[t.name] = "l" if dx < -0.5 else "r" if dx > 0.5 else "u" if dy < -0.5 else "d"
        return out

    def bbox(self):
        b = self.geometry().bbox()
        pts = [self.local_to_world(x, y) for x, y in ((b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]))]
        return bbox_of(pts)

    def prop(self, key: str) -> str:
        return self.props.get(key, "")

    def tag(self) -> str:
        """Reference used in reports: designator, plus terminal number for terminal blocks."""
        t = self.props.get("terminal", "")
        if self.designator and t:
            return f"{self.designator}:{t}"
        return self.designator or "?"

    def to_dict(self):
        d = {"id": self.id, "symbol": self.symbol, "x": self.x, "y": self.y, "rotation": self.rotation,
             "mirror": self.mirror, "designator": self.designator, "label": self.label}
        if self.params:
            d["params"] = copy.deepcopy(self.params)
        if self.text_side != "auto":
            d["text_side"] = self.text_side
        if self.props:
            d["props"] = dict(self.props)
        if self.terminal_labels:
            d["terminal_labels"] = dict(self.terminal_labels)
        if self.layer != DEFAULT_LAYER_COMPONENTS:
            d["layer"] = self.layer
        if self.locked:
            d["locked"] = True
        if self.group:
            d["group"] = self.group
        if not self.in_bom:
            d["in_bom"] = False
        return d

    @classmethod
    def from_dict(cls, d):
        d = _obj(d, "a component")
        cid = _int(_req(d, "id", "a component"), "component id")
        what = f"component {cid}"
        symbol = _text(_req(d, "symbol", what), f"{what} symbol")
        return cls(id=cid, symbol=symbol, x=_num(_req(d, "x", what), f"{what} x"),
                   y=_num(_req(d, "y", what), f"{what} y"),
                   rotation=_rotation(d.get("rotation", 0), f"{what} rotation"), mirror=bool(d.get("mirror", False)),
                   designator=_text(d.get("designator"), f"{what} designator"),
                   label=_text(d.get("label"), f"{what} label"),
                   params=_params(symbol, d.get("params") or None, what),
                   text_side=d.get("text_side", "auto") if d.get("text_side") in TEXT_SIDES else "auto",
                   props=_str_dict(d.get("props")), terminal_labels=_str_dict(d.get("terminal_labels")),
                   layer=_text(d.get("layer"), f"{what} layer") or DEFAULT_LAYER_COMPONENTS,
                   locked=bool(d.get("locked", False)),
                   group=_text(d.get("group"), f"{what} group"), in_bom=bool(d.get("in_bom", True)))


# ================================================================ wire
@dataclass
class Wire:
    """An orthogonal polyline. `start`/`end` optionally reference a component
    terminal as [component_id, terminal_name]; the end point coordinates are
    kept in sync with that terminal when components move.

    Wire numbers belong to nets: every wire of a net carries the same
    ``number``. ``number_manual`` marks a number typed by the user; automatic
    numbering never changes it."""
    id: int
    points: list
    start: Optional[list] = None
    end: Optional[list] = None
    style: str = "solid"
    auto: bool = False   # path was generated by the router (re-route freely)
    number: str = ""
    number_manual: bool = False
    props: dict = field(default_factory=dict)   # e.g. colour, cross-section
    layer: str = DEFAULT_LAYER_WIRES
    locked: bool = False
    group: str = ""

    def bbox(self):
        return bbox_of(self.points)

    def to_dict(self):
        d = {"id": self.id, "points": [[p[0], p[1]] for p in self.points], "start": self.start,
             "end": self.end, "style": self.style}
        if self.auto:
            d["auto"] = True
        if self.number:
            d["number"] = self.number
        if self.number_manual:
            d["number_manual"] = True
        if self.props:
            d["props"] = dict(self.props)
        if self.layer != DEFAULT_LAYER_WIRES:
            d["layer"] = self.layer
        if self.locked:
            d["locked"] = True
        if self.group:
            d["group"] = self.group
        return d

    @classmethod
    def from_dict(cls, d):
        d = _obj(d, "a wire")
        wid = _int(_req(d, "id", "a wire"), "wire id")
        what = f"wire {wid}"
        pts = [_point(p, f"{what} point {i}") for i, p in enumerate(_seq(_req(d, "points", what), f"{what} points"))]
        if len(pts) < 2:
            raise ValueError(f"{what} has fewer than two points")

        def ref(r, end):
            if r is None:
                return None
            if not isinstance(r, list) or len(r) != 2:
                raise ValueError(f"{what} {end} must be [component id, terminal name]")
            return [_int(r[0], f"{what} {end} component"), _text(r[1], f"{what} {end} terminal")]
        style = d.get("style", "solid")
        return cls(id=wid, points=simplify_orthogonal(pts), start=ref(d.get("start"), "start"),
                   end=ref(d.get("end"), "end"),
                   style=style if style in WIRE_STYLES else "solid", auto=bool(d.get("auto", False)),
                   number=_text(d.get("number") or None, f"{what} number"),
                   number_manual=bool(d.get("number_manual", False)),
                   props=_str_dict(d.get("props")), layer=_text(d.get("layer"), f"{what} layer") or DEFAULT_LAYER_WIRES,
                   locked=bool(d.get("locked", False)), group=_text(d.get("group") or None, f"{what} group"))


# ================================================================ shape
def clean_bulge(b: float) -> float:
    """Bulges are stored with 9 decimals (sub-nanometre sagitta error)."""
    r = round(b, 9)
    return 0.0 if r == 0 else r


SHAPE_KINDS = ("line", "polyline", "polygon", "rect", "circle", "arc", "text", "hatch")
SHAPE_WIDTHS = ("thin", "normal", "thick")


@dataclass
class Shape:
    """A free drafting primitive on a sheet (not part of the connectivity
    model). Geometry is stored in world drawing units:

      line/polyline/polygon/rect: pts  (rect = 4 corner points, kept rectangular)
      circle: c, r
      arc:    c, r, start, extent    (degrees, counter-clockwise on screen, 0 = +x)
      text:   p, s, size, anchor, angle
      hatch:  rings  (solid boundary fill: closed rings of (x, y, bulge)
              vertices filled with the even-odd rule, see regions.py)
    """
    id: int
    kind: str
    pts: list = field(default_factory=list)
    c: tuple = (0.0, 0.0)
    r: float = 0.0
    start: float = 0.0
    extent: float = 90.0
    s: str = ""
    size: float = 10.0
    anchor: str = "w"
    angle: float = 0.0
    width: str = "normal"
    dash: bool = False
    fill: bool = False
    layer: str = DEFAULT_LAYER_SHAPES
    locked: bool = False
    group: str = ""
    arrow_start: bool = False
    arrow_end: bool = False
    arrow_size: float = 10.0
    rings: list = field(default_factory=list)

    def bbox(self):
        from .shapes import shape_bbox
        return shape_bbox(self)

    def to_dict(self):
        d = {"id": self.id, "kind": self.kind}
        if self.kind in ("line", "polyline", "polygon", "rect"):
            d["pts"] = [[clean(x), clean(y)] for x, y in self.pts]
        elif self.kind == "circle":
            d.update(c=[clean(self.c[0]), clean(self.c[1])], r=clean(self.r))
        elif self.kind == "arc":
            d.update(c=[clean(self.c[0]), clean(self.c[1])], r=clean(self.r), start=clean(self.start),
                     extent=clean(self.extent))
        elif self.kind == "text":
            d.update(p=[clean(self.pts[0][0]), clean(self.pts[0][1])], s=self.s, size=self.size, anchor=self.anchor)
            if self.angle:
                d["angle"] = self.angle
        elif self.kind == "hatch":
            d["rings"] = [[[clean(x), clean(y)] + ([clean_bulge(b)] if clean_bulge(b) else []) for x, y, b in ring]
                          for ring in self.rings]
        if self.kind in ("line", "polyline"):
            if self.arrow_start:
                d["arrow_start"] = True
            if self.arrow_end:
                d["arrow_end"] = True
            if self.arrow_start or self.arrow_end:
                d["arrow_size"] = clean(self.arrow_size)
        if self.width != "normal":
            d["width"] = self.width
        if self.dash:
            d["dash"] = True
        if self.fill:
            d["fill"] = True
        if self.layer != DEFAULT_LAYER_SHAPES:
            d["layer"] = self.layer
        if self.locked:
            d["locked"] = True
        if self.group:
            d["group"] = self.group
        return d

    @classmethod
    def from_dict(cls, d):
        d = _obj(d, "a drafting shape")
        kind = d.get("kind")
        if not isinstance(kind, str) or kind not in SHAPE_KINDS:
            raise ValueError(f"unknown drafting shape kind ({_kind(kind)})")
        sid = _int(_req(d, "id", f"a {kind} shape"), "shape id")
        what = f"{kind} shape {sid}"
        s = cls(id=sid, kind=kind)
        if kind in ("line", "polyline", "polygon", "rect"):
            s.pts = [_point(p, f"{what} point {i}") for i, p in enumerate(_seq(_req(d, "pts", what), f"{what} pts"))]
            if len(s.pts) < 2:
                raise ValueError(f"{what} has fewer than two points")
        elif kind == "hatch":
            from .regions import clean_rings
            try:
                s.rings = clean_rings(d.get("rings"))
            except ValueError as e:
                raise ValueError(f"{what}: {e}") from None
        elif kind in ("circle", "arc"):
            s.c = _point(_req(d, "c", what), f"{what} centre")
            s.r = _num(_req(d, "r", what), f"{what} radius")
            if s.r < 0:
                raise ValueError(f"{what} radius must not be negative")
            if kind == "arc":
                s.start = _num(d.get("start", 0), f"{what} start")
                s.extent = _num(d.get("extent", 90), f"{what} extent")
        else:
            s.pts = [_point(_req(d, "p", what), f"{what} position")]
            s.s = _text(d.get("s"), f"{what} text")
            s.size = _num(d.get("size", 10), f"{what} size")
            if s.size <= 0:
                raise ValueError(f"{what} size must be positive")
            s.anchor = _text(d.get("anchor"), f"{what} anchor", "w")
            s.angle = _num(d.get("angle", 0), f"{what} angle")
        w = d.get("width", "normal")
        s.width = w if w in SHAPE_WIDTHS else "normal"
        s.dash, s.fill = bool(d.get("dash", False)), bool(d.get("fill", False))
        s.layer = _text(d.get("layer"), f"{what} layer") or DEFAULT_LAYER_SHAPES
        s.locked = bool(d.get("locked", False))
        s.group = _text(d.get("group") or None, f"{what} group")
        if kind in ("line", "polyline"):
            s.arrow_start = d.get("arrow_start") is True
            s.arrow_end = d.get("arrow_end") is True
            try:
                arrow_size = float(d.get("arrow_size", 10.0))
                if isinstance(d.get("arrow_size"), bool) or not math.isfinite(arrow_size) or not 0 < arrow_size <= 10000:
                    arrow_size = 10.0
            except (TypeError, ValueError, OverflowError):
                arrow_size = 10.0
            s.arrow_size = arrow_size
        return s


# ================================================================ sheet setup
@dataclass
class Sheet:
    """Page setup and title-block fields of one sheet. Empty title-block
    fields fall back to the project's metadata when rendered."""
    size: str = "A3"
    orientation: str = "landscape"
    title: str = ""
    drawing_number: str = ""
    revision: str = ""
    author: str = ""
    date: str = ""
    organisation: str = ""
    sheet: str = ""            # legacy free text "1 / 1"; empty = automatic numbering
    show_title_block: bool = True
    title_block: str = "standard"
    zones: bool = True         # grid reference zones (A,B,C… / 1,2,3…) on the frame
    scale: str = "1:1"         # presentation scale (paper : drawing)
    custom_w: float = 420.0    # mm, used when size == "Custom"
    custom_h: float = 297.0
    checked_by: str = ""
    approved_by: str = ""
    description: str = ""
    drawing_status: str = "Released"  # sheet-level status; legacy drawings default to Released

    def size_mm(self):
        if self.size == CUSTOM_SIZE:
            w, h = max(50.0, self.custom_w), max(50.0, self.custom_h)
            return (w, h)   # custom sizes are used exactly as entered
        w, h = SHEET_SIZES_MM.get(self.size, SHEET_SIZES_MM["A3"])
        if self.orientation == "portrait":
            return (min(w, h), max(w, h))
        return (max(w, h), min(w, h))

    def paper_units(self):
        """Paper size in drawing units at 1:1."""
        from .geometry import UNIT_MM
        w, h = self.size_mm()
        return (w / UNIT_MM, h / UNIT_MM)

    def scale_factor(self) -> float:
        """Paper length per model length (e.g. 0.5 for 1:2)."""
        return parse_scale(self.scale)

    def size_units(self):
        """Sheet extent in *model* units: the paper size divided by the
        presentation scale. At 1:2 the frame is twice as large around the
        drawing, so the drawing prints at half size."""
        w, h = self.paper_units()
        f = self.scale_factor()
        return (w / f, h / f)

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        s = cls()
        if d is not None and not isinstance(d, dict):
            raise ValueError(f"the page setup must be an object, not {_kind(d)}")
        # Page setup is lenient, as always: a value that cannot be used keeps
        # the default. Containers and non-finite numbers are never used.
        for k, v in (d or {}).items():
            if hasattr(s, k) and not isinstance(v, (dict, list)):
                cur = getattr(s, k)
                try:
                    if isinstance(cur, bool):
                        setattr(s, k, bool(v))
                    elif isinstance(cur, float):
                        f = float(v)
                        if math.isfinite(f) and not isinstance(v, bool):
                            setattr(s, k, f)
                    else:
                        setattr(s, k, type(cur)(v))
                except (TypeError, ValueError, OverflowError):
                    pass
        if s.size not in SHEET_SIZES_MM and s.size != CUSTOM_SIZE:
            s.size = "A3"
        if s.orientation not in ("landscape", "portrait"):
            s.orientation = "landscape"
        if s.drawing_status not in ("Preliminary", "Released"):
            s.drawing_status = "Released"
        if s.title_block not in TITLE_BLOCKS:
            s.title_block = "standard"
        if not s.show_title_block:
            s.title_block = "none"
        try:
            parse_scale(s.scale)
        except ValueError:
            s.scale = "1:1"
        return s


STANDARD_SCALES = ("10:1", "5:1", "2:1", "1:1", "1:2", "1:2.5", "1:5", "1:10", "1:20", "1:25", "1:50", "1:100")


def parse_scale(text: str) -> float:
    """'1:2' -> 0.5, '2:1' -> 2.0, '0.75' -> 0.75. Raises ValueError."""
    t = str(text).strip().replace(" ", "")
    if ":" in t:
        a, b = t.split(":", 1)
        a, b = float(a), float(b)
    else:
        a, b = float(t), 1.0
    if a <= 0 or b <= 0:
        raise ValueError("scale must be positive")
    f = a / b
    if not (0.001 <= f <= 1000):
        raise ValueError("scale out of range")
    return f


def format_scale(f: float) -> str:
    for s in STANDARD_SCALES:
        if abs(parse_scale(s) - f) < 1e-9:
            return s
    if f >= 1:
        return f"{f:g}:1"
    return f"1:{1 / f:.4g}"


# ================================================================ document (one sheet)
class Document:
    """One schematic sheet."""

    def __init__(self, name: str = "Sheet 1", uid: str | None = None):
        self.uid = uid or new_uid()
        self.name = name
        self.components: dict[int, Component] = {}
        self.wires: dict[int, Wire] = {}
        self.shapes: dict[int, Shape] = {}
        self.sheet = Sheet()
        self.next_id = 1
        self.project = None    # owning Project (set by Project), for project-wide designators

    # ---------------------------------------------------------------- ids
    def new_id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i

    def _taken(self, i) -> bool:
        return i in self.components or i in self.wires or i in self.shapes

    def add_component(self, comp: Component) -> Component:
        if self._taken(comp.id):
            comp.id = self.new_id()
        self.next_id = max(self.next_id, comp.id + 1)
        self.components[comp.id] = comp
        return comp

    def add_wire(self, wire: Wire) -> Wire:
        if self._taken(wire.id):
            wire.id = self.new_id()
        self.next_id = max(self.next_id, wire.id + 1)
        self.wires[wire.id] = wire
        return wire

    def add_shape(self, shape: Shape) -> Shape:
        if self._taken(shape.id):
            shape.id = self.new_id()
        self.next_id = max(self.next_id, shape.id + 1)
        self.shapes[shape.id] = shape
        return shape

    # ---------------------------------------------------------------- queries
    def item(self, ident):
        return self.components.get(ident) or self.wires.get(ident) or self.shapes.get(ident)

    def all_ids(self):
        return set(self.components) | set(self.wires) | set(self.shapes)

    def bbox(self):
        b = None
        for c in self.components.values():
            b = bbox_union(b, c.bbox())
        for w in self.wires.values():
            b = bbox_union(b, w.bbox())
        for s in self.shapes.values():
            b = bbox_union(b, s.bbox())
        return b

    def terminal_pos(self, ref):
        if not ref:
            return None
        c = self.components.get(ref[0])
        if not c:
            return None
        return c.terminals().get(ref[1])

    def used_designators(self) -> set[str]:
        own = {c.designator for c in self.components.values() if c.designator}
        if self.project is not None:
            from .project import is_terminal_symbol
            own = {c.designator for c in self.components.values()
                   if c.designator and not is_terminal_symbol(c.symbol)}
            return own | self.project.used_designators(exclude_sheet=self.uid)
        return own

    def next_designator(self, prefix: str, taken: Optional[set] = None) -> str:
        if not prefix:
            return ""
        taken = self.used_designators() if taken is None else taken
        n = 1
        while f"{prefix}{n}" in taken:
            n += 1
        return f"{prefix}{n}"

    # ---------------------------------------------------------------- serialisation
    def required_schema(self) -> int:
        """Lowest sheet schema able to represent this sheet: files without
        boundary fills stay readable by OpenSchematix 1.0.x (schema 2)."""
        return SHEET_SCHEMA if any(s.kind == "hatch" for s in self.shapes.values()) else 2

    def to_dict(self, standalone: bool = True):
        from . import FILE_FORMAT, VERSION
        d = {}
        if standalone:
            d.update(format=FILE_FORMAT, schema=self.required_schema(), app_version=VERSION)
        d.update({
            "uid": self.uid,
            "name": self.name,
            "next_id": self.next_id,
            "sheet": self.sheet.to_dict(),
            "components": [c.to_dict() for c in self.components.values()],
            "wires": [w.to_dict() for w in self.wires.values()],
        })
        if self.shapes:
            d["shapes"] = [s.to_dict() for s in self.shapes.values()]
        return d

    @classmethod
    def from_dict(cls, d, resolve=None) -> "Document":
        """Build a sheet from its dict.

        `resolve(symbol_id) -> SymbolDef | None` supplies the symbol definitions used to validate wire
        terminal references; Project.from_dict passes one that sees the project's own embedded symbols.
        The default (symbols.lookup) uses built-in and user-library symbols only, never the active
        project's, so a sheet is never validated against another project's symbols."""
        d = _obj(d, "a sheet")
        doc = cls(name=_text(d.get("name") or None, "sheet name", "Sheet 1"),
                  uid=_text(d.get("uid") or None, "sheet uid") or new_uid())
        where = f"sheet '{doc.name}'"
        try:
            doc.sheet = Sheet.from_dict(d.get("sheet"))
            for cd in _seq(d.get("components"), "components", []):
                c = Component.from_dict(cd)
                if doc._taken(c.id):
                    raise ValueError(f"duplicate object id {c.id}")
                doc.components[c.id] = c
            for wd in _seq(d.get("wires"), "wires", []):
                w = Wire.from_dict(wd)
                if doc._taken(w.id):
                    raise ValueError(f"duplicate object id {w.id}")
                doc.wires[w.id] = w
            for sd in _seq(d.get("shapes"), "shapes", []):
                s = Shape.from_dict(sd)
                if doc._taken(s.id):
                    raise ValueError(f"duplicate object id {s.id}")
                doc.shapes[s.id] = s
            ids = doc.all_ids()
            doc.next_id = max(max(ids, default=0) + 1, _int(d.get("next_id") or 1, "next_id"))
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
        # Drop terminal references that are certainly dangling (no such component, or a symbol that is
        # known and has no such terminal) instead of failing. A reference to a component whose symbol is
        # not available is kept: its pins are unknown here, and the reference becomes valid again as soon
        # as the symbol is (dropping it would lose the connection for good on the next save).
        resolve = resolve or symbols.lookup
        names_cache: dict = {}

        def terminal_names(c):
            key = (c.symbol, json.dumps(c.params, sort_keys=True) if c.params else "")
            if key not in names_cache:
                sd = resolve(c.symbol)
                try:
                    names_cache[key] = None if sd is None else {t.name for t in sd.build(c.params or None).terminals}
                except Exception:  # noqa: BLE001 - a symbol that cannot be built cannot validate anything
                    names_cache[key] = None
            return names_cache[key]

        for w in doc.wires.values():
            for attr in ("start", "end"):
                ref = getattr(w, attr)
                if not ref:
                    continue
                c = doc.components.get(ref[0])
                names = terminal_names(c) if c is not None else set()
                if names is not None and ref[1] not in names:
                    setattr(w, attr, None)
        return doc

    def copy(self) -> "Document":
        resolve = self.project.symbol_resolver() if self.project is not None else None
        return Document.from_dict(self.to_dict(), resolve=resolve)


# Schema of one sheet's JSON (the .osch "schema" number). 1 = OpenSchematix
# legacy single-drawing files; 2 = 1.0 sheets (shapes, props, layers, uid);
# 3 = adds "hatch" shapes (boundary fills). Sheets without fills are still
# written as schema 2 so older releases can open them (Document.required_schema).
SHEET_SCHEMA = 3


def sheet_dict_schema(d) -> int:
    """Schema needed by a serialised sheet (as stored in revision snapshots)."""
    shapes = d.get("shapes") if isinstance(d, dict) else None
    if isinstance(shapes, list) and any(isinstance(s, dict) and s.get("kind") == "hatch" for s in shapes):
        return 3
    return 2
