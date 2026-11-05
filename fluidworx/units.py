"""Units. Everything inside FluidWorx is SI (Pa, m^3/s, m, N, kg); only the display changes.

The two unit systems match Caldera's "US customary or metric" setting.
"""
from __future__ import annotations

import ast
import math
import operator
import re

# quantity -> {system: (label, factor)}; display value = SI value / factor
QUANTITIES = {
    "pressure": {"metric": ("bar", 1e5), "us": ("psi", 6894.757)},
    "flow": {"metric": ("L/min", 1e-3 / 60), "us": ("gpm", 3.785412e-3 / 60)},
    "length": {"metric": ("mm", 1e-3), "us": ("in", 0.0254)},
    "speed": {"metric": ("mm/s", 1e-3), "us": ("in/s", 0.0254)},
    "force": {"metric": ("N", 1.0), "us": ("lbf", 4.448222)},
    "mass": {"metric": ("kg", 1.0), "us": ("lb", 0.4535924)},
    "volume": {"metric": ("L", 1e-3), "us": ("gal", 3.785412e-3)},
    "displacement": {"metric": ("cc/rev", 1e-6), "us": ("in³/rev", 1.638706e-5)},
    "torque": {"metric": ("N·m", 1.0), "us": ("lb·ft", 1.355818)},
    "inertia": {"metric": ("kg·m²", 1.0), "us": ("kg·m²", 1.0)},
    "rpm": {"metric": ("rpm", 2 * math.pi / 60), "us": ("rpm", 2 * math.pi / 60)},
    "angle": {"metric": ("°", math.pi / 180), "us": ("°", math.pi / 180)},
    "percent": {"metric": ("%", 1.0), "us": ("%", 1.0)},
    "ratio": {"metric": (":1", 1.0), "us": (":1", 1.0)},
    "time": {"metric": ("s", 1.0), "us": ("s", 1.0)},
}

# text units accepted when reading schematic labels and typed values, in SI per unit
TEXT_UNITS = {
    "pressure": {"bar": 1e5, "psi": 6894.757, "mpa": 1e6, "kpa": 1e3, "pa": 1.0, "psig": 6894.757, "barg": 1e5},
    "flow": {"l/min": 1e-3 / 60, "lpm": 1e-3 / 60, "gpm": 3.785412e-3 / 60, "cfm": 4.719474e-4,
             "nl/min": 1e-3 / 60 / 7.0, "m3/h": 1 / 3600},
    "length": {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "in": 0.0254, '"': 0.0254, "ft": 0.3048},
    "speed": {"mm/s": 1e-3, "m/s": 1.0, "in/s": 0.0254},
    "force": {"n": 1.0, "kn": 1e3, "lbf": 4.448222, "lb": 4.448222},
    "mass": {"kg": 1.0, "g": 1e-3, "t": 1e3, "lb": 0.4535924},
    "volume": {"l": 1e-3, "ml": 1e-6, "gal": 3.785412e-3, "cc": 1e-6},
    "displacement": {"cc/rev": 1e-6, "cc": 1e-6, "cm3/rev": 1e-6, "in3/rev": 1.638706e-5},
    "torque": {"nm": 1.0, "n·m": 1.0, "n.m": 1.0, "lbft": 1.355818, "lb·ft": 1.355818, "ft-lb": 1.355818},
}


class Units:
    def __init__(self, system: str = "metric"):
        self.system = system if system in ("metric", "us") else "metric"

    def label(self, q: str) -> str:
        return QUANTITIES[q][self.system][0]

    def from_si(self, q: str, v: float) -> float:
        return v / QUANTITIES[q][self.system][1]

    def to_si(self, q: str, v: float) -> float:
        return v * QUANTITIES[q][self.system][1]

    def number(self, q: str, v: float) -> str:
        """Value without its unit, with sensible precision for editing or reading."""
        return _trim(self.from_si(q, v))

    def fmt(self, q: str, v: float) -> str:
        unit = self.label(q)
        sep = "" if unit in ("%", "°", ":1") else " "
        return f"{self.number(q, v)}{sep}{unit}"


def _trim(x: float) -> str:
    a = abs(x)
    if a < 5e-7:
        return "0"
    if a >= 1000:
        s = f"{x:,.0f}"
    elif a >= 100:
        s = f"{x:.0f}"
    elif a >= 10:
        s = f"{x:.1f}"
    elif a >= 1:
        s = f"{x:.2f}"
    else:
        s = f"{x:.3f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _ev(n):
    if isinstance(n, ast.Expression):
        return _ev(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return float(n.value)
    if isinstance(n, ast.Name) and n.id.lower() == "pi":
        return math.pi
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        if isinstance(n.op, ast.Pow) and abs(_ev(n.right)) > 16:
            raise ValueError("exponent too large")
        return _OPS[type(n.op)](_ev(n.left), _ev(n.right))
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_ev(n.operand))
    raise ValueError("not a number")


def parse_number(text: str) -> float:
    """A number or simple arithmetic ("30/2", "2*pi*1.5", "1,234.5"), as Caldera's inputs accept. No eval()."""
    s = str(text).strip().replace(",", "")
    if not s or len(s) > 64:
        raise ValueError("enter a number")
    try:
        v = _ev(ast.parse(s, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError, MemoryError) as e:
        raise ValueError("enter a number") from e
    if not math.isfinite(v):
        raise ValueError("enter a finite number")
    return v


_VALUE_UNIT = re.compile(r"^\s*(.*?)\s*([A-Za-zµ°/\"·.³²0-9-]*[A-Za-z\"³²])\s*$")


def parse_entry(text: str, quantity: str, units: Units) -> float:
    """SI value of what the user typed: a bare number is in the display unit; "160 bar" names its own."""
    s = str(text).strip()
    m = _VALUE_UNIT.match(s)
    if m and m.group(1) and quantity in TEXT_UNITS:
        factor = TEXT_UNITS[quantity].get(m.group(2).lower())
        if factor is not None:
            return parse_number(m.group(1)) * factor
    return units.to_si(quantity, parse_number(s))


_NUM = r"(\d+(?:[.,]\d+)?)"


def find_quantity(text: str, quantity: str) -> float | None:
    """First value of `quantity` with an explicit unit in free text such as a label ("10 L/min", "160 bar")."""
    if not text or quantity not in TEXT_UNITS:
        return None
    names = sorted(TEXT_UNITS[quantity], key=len, reverse=True)
    pat = _NUM + r"\s*(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z/])"
    m = re.search(pat, text, re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1).replace(",", ".")) * TEXT_UNITS[quantity][m.group(2).lower()]


_CYL = re.compile(r"(?:ø|Ø|dia\.?\s*)?(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*(?:[x×*/-]\s*(\d+(?:\.\d+)?))?\s*(mm|in|\")?",
                  re.IGNORECASE)


_BORE_STROKE = re.compile(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(mm|in|\")?", re.IGNORECASE)


def find_cylinder(text: str) -> dict:
    """Bore/rod[xstroke] from a label: "63/36x300", "2.5/1.25 x 12 in". Without a unit, mm is assumed."""
    if not text:
        return {}
    m = _CYL.search(text)
    if not m or re.search(r"\d\s*/\s*min", text, re.IGNORECASE):
        s = _BORE_STROKE.search(text)
        if s and not re.search(r"\d\s*/\s*min", text, re.IGNORECASE):     # "32x80": bore x stroke, no rod given
            f = 0.0254 if (s.group(3) or "").lower() in ("in", '"') else 1e-3
            return {"bore": float(s.group(1)) * f, "stroke": float(s.group(2)) * f}
        return {}
    f = 0.0254 if (m.group(4) or "").lower() in ("in", '"') else 1e-3
    bore, rod = float(m.group(1)) * f, float(m.group(2)) * f
    if rod >= bore:
        return {}
    out = {"bore": bore, "rod": rod}
    if m.group(3):
        out["stroke"] = float(m.group(3)) * f
    return out
