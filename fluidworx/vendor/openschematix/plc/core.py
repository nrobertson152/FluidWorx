"""What every PLC language shares: errors, data types, variables and the standard function blocks.

A PLC program comes out of a drawing file, so it must never be able to touch the computer. None of the languages
here is executed by Python's ``exec``: each is parsed and turned into closures that can only read and write the
PLC's own memory. Loops and calls draw on a per-scan budget, the PLC's watchdog, so no program can hang the host.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MAX_ARRAY = 100_000         # elements in one array, list or string
MAX_NEST = 60               # nesting of statements and expressions in a source text
MAX_CALL_DEPTH = 40         # user function calls in progress
SCAN_BUDGET = 100_000       # loop iterations and calls allowed in one scan


class PlcError(Exception):
    pass


class CompileError(PlcError):
    """The program can't be built. `line` is 1-based, or 0 when it has no meaning for the language."""

    def __init__(self, message, line=0, where=""):
        super().__init__(message)
        self.message, self.line, self.where = message, line, where


class PlcFault(PlcError):
    """The program stopped while running: division by zero, a bad index, the watchdog. The PLC goes to STOP."""


@dataclass
class Diag:
    level: str          # "error" | "warning"
    pou: str
    line: int
    message: str

    def __str__(self):
        at = f"{self.pou}, line {self.line}" if self.line else self.pou
        return f"{at}: {self.message}" if at else self.message


class Ctx:
    """State shared by all the closures of one compiled PLC."""
    __slots__ = ("G", "budget", "dt_ms", "now_ms", "messages", "depth")

    def __init__(self):
        self.G: dict = {}
        self.budget = SCAN_BUDGET
        self.dt_ms = 10
        self.now_ms = 0
        self.messages: list = []
        self.depth = 0

    def tick(self):
        self.budget -= 1
        if self.budget < 0:
            raise PlcFault("watchdog: the scan took too long (an endless loop?)")

    def log(self, text):
        if len(self.messages) < 200:
            self.messages.append(str(text)[:200])


# ---------------------------------------------------------------- data types
INT_TYPES = {"SINT": (8, True), "INT": (16, True), "DINT": (32, True), "LINT": (64, True),
             "USINT": (8, False), "UINT": (16, False), "UDINT": (32, False), "ULINT": (64, False),
             "BYTE": (8, False), "WORD": (16, False), "DWORD": (32, False), "LWORD": (64, False)}
REAL_TYPES = ("REAL", "LREAL")
ELEMENTARY = ("BOOL", *INT_TYPES, *REAL_TYPES, "TIME", "STRING")
TYPE_NAMES_FOR_TABLE = ("BOOL", "INT", "DINT", "REAL", "TIME")


def wrap_int(bits, signed, truncate=False):
    """Fit a value to an integer type. ST rounds a real to an integer, as REAL_TO_INT does; C truncates."""
    mask = (1 << bits) - 1
    half = 1 << (bits - 1)
    to_int = _trunc_int if truncate else _as_int
    if signed:
        def to_signed(v):
            return ((to_int(v) + half) & mask) - half
        return to_signed

    def to_unsigned(v):
        return to_int(v) & mask
    return to_unsigned


def _as_int(v):
    if type(v) is float:
        if not math.isfinite(v):
            raise PlcFault("a number that is not finite can't be stored as an integer")
        return round(v)
    return int(v)


def _trunc_int(v):
    if type(v) is float and not math.isfinite(v):
        raise PlcFault("a number that is not finite can't be stored as an integer")
    return int(v)


def to_real(v):
    return float(v)


def to_str(v):
    s = str(v)
    return s if len(s) <= MAX_ARRAY else s[:MAX_ARRAY]


def coercer(type_name: str):
    """Function that makes a value fit a declared elementary type (integers wrap, as they do on the hardware)."""
    if type_name == "BOOL":
        return bool
    if type_name in INT_TYPES:
        return wrap_int(*INT_TYPES[type_name])
    if type_name in REAL_TYPES:
        return to_real
    if type_name == "TIME":
        return _as_int
    if type_name == "STRING":
        return to_str
    raise CompileError(f"unknown type {type_name}")


def zero(type_name: str):
    if type_name == "BOOL":
        return False
    if type_name in REAL_TYPES:
        return 0.0
    if type_name == "STRING":
        return ""
    return 0


class ArrayType:
    """ARRAY[lo..hi] OF elem. `elem` is a type name, a nested ArrayType or a function block type."""
    __slots__ = ("lo", "hi", "elem")

    def __init__(self, lo, hi, elem):
        self.lo, self.hi, self.elem = lo, hi, elem

    def size(self):
        return self.hi - self.lo + 1

    def total(self):
        inner = self.elem.total() if isinstance(self.elem, ArrayType) else 1
        return self.size() * inner


def new_value(t):
    """Fresh value of a declared type."""
    if isinstance(t, ArrayType):
        return [new_value(t.elem) for _ in range(t.size())]
    if isinstance(t, str):
        return zero(t)
    return t.new()


@dataclass
class Var:
    name: str
    key: str                # key in its frame
    type: object            # type name, ArrayType or FB type
    kind: str = "memory"    # input | output | memory | sys | fb | step | const
    local: bool = False     # lives in the POU's frame rather than the global memory
    init: object = None     # initial value (None = zero of the type)
    writable: bool = True
    alias: str = ""         # the tag it was reached by, for messages


class Scope:
    """Names known to a piece of source text. Case-insensitive by default, as IEC 61131-3 is."""

    def __init__(self, parent=None, fold=True):
        self.parent, self.fold = parent, fold
        self.names: dict = {}
        self.spelled: dict = {}

    def _k(self, name):
        return name.casefold() if self.fold else name

    def add(self, name, var):
        self.names[self._k(name)] = var
        self.spelled[self._k(name)] = name
        return var

    def find_exact(self, name):
        """As find(), for the languages where case matters: C and Python."""
        s = self
        while s is not None:
            k = s._k(name)
            v = s.names.get(k)
            if v is not None and s.spelled.get(k) == name:
                return v
            s = s.parent
        return None

    def find(self, name):
        s = self
        while s is not None:
            v = s.names.get(s._k(name))
            if v is not None:
                return v
            s = s.parent
        return None

    def own(self, name):
        return self.names.get(self._k(name))


# ---------------------------------------------------------------- standard function blocks
class Fb:
    """A standard function block. PINS: input name -> default; OUTS: output name -> default."""
    PINS: dict = {}
    OUTS: dict = {}
    TITLE = ""

    def __init__(self):
        for k, v in self.PINS.items():
            setattr(self, k, v)
        for k, v in self.OUTS.items():
            setattr(self, k, v)

    @classmethod
    def new(cls):
        return cls()

    def run(self, dt_ms):
        raise NotImplementedError

    def __call__(self, *a, **k):
        raise PlcFault("this function block can't be called this way")


class TON(Fb):
    TITLE = "On-delay timer"
    PINS = {"IN": False, "PT": 0}
    OUTS = {"Q": False, "ET": 0}

    def run(self, dt_ms):
        if self.IN:
            self.ET = min(self.ET + dt_ms, self.PT)
            self.Q = self.ET >= self.PT
        else:
            self.ET, self.Q = 0, False


class TOF(Fb):
    TITLE = "Off-delay timer"
    PINS = {"IN": False, "PT": 0}
    OUTS = {"Q": False, "ET": 0}

    def run(self, dt_ms):
        if self.IN:
            self.ET, self.Q = 0, True
        elif self.Q:
            self.ET = min(self.ET + dt_ms, self.PT)
            self.Q = self.ET < self.PT


class TP(Fb):
    TITLE = "Pulse timer"
    PINS = {"IN": False, "PT": 0}
    OUTS = {"Q": False, "ET": 0}

    def __init__(self):
        super().__init__()
        self._was = False

    def run(self, dt_ms):
        rising = self.IN and not self._was
        self._was = bool(self.IN)
        if self.Q:
            self.ET = min(self.ET + dt_ms, self.PT)
            self.Q = self.ET < self.PT
        elif rising:
            self.ET, self.Q = 0, self.PT > 0
        elif not self.IN:
            self.ET = 0


class CTU(Fb):
    TITLE = "Up counter"
    PINS = {"CU": False, "R": False, "PV": 0}
    OUTS = {"Q": False, "CV": 0}

    def __init__(self):
        super().__init__()
        self._was = False

    def run(self, dt_ms):
        if self.R:
            self.CV = 0
        elif self.CU and not self._was:
            self.CV = min(self.CV + 1, 2 ** 31 - 1)
        self._was = bool(self.CU)
        self.Q = self.CV >= self.PV


class CTD(Fb):
    TITLE = "Down counter"
    PINS = {"CD": False, "LD": False, "PV": 0}
    OUTS = {"Q": False, "CV": 0}

    def __init__(self):
        super().__init__()
        self._was = False

    def run(self, dt_ms):
        if self.LD:
            self.CV = self.PV
        elif self.CD and not self._was:
            self.CV = max(self.CV - 1, -2 ** 31)
        self._was = bool(self.CD)
        self.Q = self.CV <= 0


class CTUD(Fb):
    TITLE = "Up-down counter"
    PINS = {"CU": False, "CD": False, "R": False, "LD": False, "PV": 0}
    OUTS = {"QU": False, "QD": False, "CV": 0}

    def __init__(self):
        super().__init__()
        self._wu = self._wd = False

    def run(self, dt_ms):
        if self.R:
            self.CV = 0
        elif self.LD:
            self.CV = self.PV
        else:
            if self.CU and not self._wu:
                self.CV = min(self.CV + 1, 2 ** 31 - 1)
            if self.CD and not self._wd:
                self.CV = max(self.CV - 1, -2 ** 31)
        self._wu, self._wd = bool(self.CU), bool(self.CD)
        self.QU, self.QD = self.CV >= self.PV, self.CV <= 0


class R_TRIG(Fb):
    TITLE = "Rising edge"
    PINS = {"CLK": False}
    OUTS = {"Q": False}

    def __init__(self):
        super().__init__()
        self._was = False

    def run(self, dt_ms):
        now = bool(self.CLK)
        self.Q, self._was = now and not self._was, now


class F_TRIG(Fb):
    TITLE = "Falling edge"
    PINS = {"CLK": False}
    OUTS = {"Q": False}

    def __init__(self):
        super().__init__()
        self._was = False

    def run(self, dt_ms):
        now = bool(self.CLK)
        self.Q, self._was = self._was and not now, now


class SR(Fb):
    TITLE = "Set-dominant latch"
    PINS = {"S1": False, "R": False}
    OUTS = {"Q1": False}

    def run(self, dt_ms):
        self.Q1 = bool(self.S1) or (self.Q1 and not self.R)


class RS(Fb):
    TITLE = "Reset-dominant latch"
    PINS = {"S": False, "R1": False}
    OUTS = {"Q1": False}

    def run(self, dt_ms):
        self.Q1 = not self.R1 and (bool(self.S) or self.Q1)


class PID(Fb):
    """Parallel-form PID with anti-windup, for a proportional valve or a pressure loop. KI and KD are per second."""
    TITLE = "PID controller"
    PINS = {"SP": 0.0, "PV": 0.0, "KP": 1.0, "KI": 0.0, "KD": 0.0, "LO": 0.0, "HI": 100.0, "EN": True}
    OUTS = {"OUT": 0.0, "ERR": 0.0}

    def __init__(self):
        super().__init__()
        self._i, self._last = 0.0, None

    def run(self, dt_ms):
        dt = dt_ms / 1000.0
        self.ERR = e = float(self.SP) - float(self.PV)
        if not self.EN or dt <= 0:
            self._i, self._last, self.OUT = 0.0, None, float(self.LO)
            return
        d = 0.0 if self._last is None else float(self.KD) * (e - self._last) / dt
        self._last = e
        p = float(self.KP) * e
        lo, hi = float(self.LO), float(self.HI)
        i = self._i + float(self.KI) * e * dt
        out = p + i + d
        if lo <= out <= hi:
            self._i = i             # hold the integral once the output is against a limit
        self.OUT = max(lo, min(hi, out))


FB_TYPES = {c.__name__: c for c in (TON, TOF, TP, CTU, CTD, CTUD, R_TRIG, F_TRIG, SR, RS, PID)}


# ---------------------------------------------------------------- standard functions
def _checked(f):
    def run(*a):
        try:
            return f(*a)
        except (ValueError, OverflowError, ZeroDivisionError) as e:
            raise PlcFault(f"{getattr(f, '__name__', 'function')}: {e}") from None
    run.__name__ = getattr(f, "__name__", "function")
    return run


def scale(x, in_lo, in_hi, out_lo, out_hi):
    """Straight-line scaling, as for a sensor signal: 4..20 mA to 0..250 bar. Not limited to the output range."""
    if in_hi == in_lo:
        raise PlcFault("SCALE: the input range is empty")
    return out_lo + (float(x) - in_lo) * (out_hi - out_lo) / (in_hi - in_lo)


def limit(lo, x, hi):
    return max(lo, min(x, hi))


def _sel(g, a, b):
    return b if g else a


def _mux(k, *vals):
    i = int(k)
    if not 0 <= i < len(vals):
        raise PlcFault(f"MUX: selector {i} is out of range")
    return vals[i]


def _shift(fn):
    def run(v, n):
        n = int(n)
        if not 0 <= n <= 64:
            raise PlcFault("a shift must be between 0 and 64 bits")
        return fn(int(v), n)
    return run


def _ipow(a, b):
    if isinstance(a, int) and isinstance(b, int) and b >= 0:
        if abs(a) > 1 and b * math.log2(abs(a)) > 64:
            raise PlcFault("a power is too large")
    try:
        return a ** b
    except (OverflowError, ZeroDivisionError, ValueError) as e:
        raise PlcFault(f"power: {e}") from None


FUNCTIONS = {       # name -> (function, least arguments, most arguments)
    "ABS": (abs, 1, 1), "SQRT": (_checked(math.sqrt), 1, 1), "LN": (_checked(math.log), 1, 1),
    "LOG": (_checked(math.log10), 1, 1), "EXP": (_checked(math.exp), 1, 1), "SIN": (_checked(math.sin), 1, 1),
    "COS": (_checked(math.cos), 1, 1), "TAN": (_checked(math.tan), 1, 1), "ASIN": (_checked(math.asin), 1, 1),
    "ACOS": (_checked(math.acos), 1, 1), "ATAN": (_checked(math.atan), 1, 1), "EXPT": (_ipow, 2, 2),
    "MIN": (min, 2, 16), "MAX": (max, 2, 16), "LIMIT": (limit, 3, 3), "SEL": (_sel, 3, 3), "MUX": (_mux, 2, 16),
    "MOVE": (lambda v: v, 1, 1), "SCALE": (scale, 5, 5), "TRUNC": (_checked(math.trunc), 1, 1),
    "ROUND": (_checked(round), 1, 1), "FLOOR": (_checked(math.floor), 1, 1), "CEIL": (_checked(math.ceil), 1, 1),
    "SHL": (_shift(lambda v, n: v << n), 2, 2), "SHR": (_shift(lambda v, n: v >> n), 2, 2),
}


def conversion(name: str):
    """REAL_TO_INT, TO_DINT, ... : the coercion to the type named after the last "TO_"."""
    upper = name.upper()
    if "TO_" not in upper:
        return None
    target = upper.rsplit("TO_", 1)[1]
    if target in ELEMENTARY:
        return coercer(target)
    return None


def int_div(x, y):
    """x / y as the languages here mean it: integers truncate toward zero, and zero is a fault."""
    if y == 0:
        raise PlcFault("division by zero")
    if isinstance(x, int) and isinstance(y, int):
        q = abs(x) // abs(y)
        return q if (x < 0) == (y < 0) else -q
    return x / y


def int_mod(x, y):
    """Remainder with the sign of x, as in ST and C."""
    if y == 0:
        raise PlcFault("division by zero")
    if isinstance(x, int) and isinstance(y, int):
        r = abs(x) % abs(y)
        return r if x >= 0 else -r
    return math.fmod(x, y)


def parse_time(text: str) -> int:
    """T#1h2m3.5s, TIME#250ms -> milliseconds. Raises ValueError."""
    t = text.split("#", 1)[-1].lower().replace("_", "")
    negative = t.startswith("-")
    t = t.lstrip("+-")
    if not t:
        raise ValueError("empty time")
    total, i, seen = 0.0, 0, False
    units = (("ms", 1.0), ("d", 86_400_000.0), ("h", 3_600_000.0), ("m", 60_000.0), ("s", 1000.0))
    while i < len(t):
        j = i
        while j < len(t) and (t[j].isdigit() or t[j] == "."):
            j += 1
        if j == i:
            raise ValueError(f"bad time {text!r}")
        value = float(t[i:j])
        for unit, factor in units:
            if t.startswith(unit, j):
                total += value * factor
                i = j + len(unit)
                seen = True
                break
        else:
            raise ValueError(f"bad time {text!r}")
    if not seen:
        raise ValueError(f"bad time {text!r}")
    return int(round(-total if negative else total))
