"""Function block diagrams: blocks joined by wires, run in signal-flow order.

    {"blocks": [{"id": 1, "type": "input", "expr": "Start", "x": 40, "y": 40},
                {"id": 2, "type": "TON", "name": "T1", "pins": {"PT": "T#2s"}, "x": 200, "y": 40},
                {"id": 3, "type": "output", "target": "Extend", "x": 380, "y": 40}],
     "wires": [{"from": [1, "OUT"], "to": [2, "IN"]}, {"from": [2, "Q"], "to": [3, "IN"]}]}

A pin with no wire uses the expression in "pins", or else zero. In a feedback loop the first block in the loop
reads last scan's value, as IEC 61131-3 lays down.
"""
from __future__ import annotations

import math
import re

from .core import FB_TYPES, FUNCTIONS, MAX_ARRAY, CompileError, int_div, int_mod
from .stlang import Compiler, parse_expression

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _nary(fn):
    def run(vals):
        r = vals[0]
        for v in vals[1:]:
            r = fn(r, v)
        return r
    return run


def _not(v):
    return not v


# type -> (input pins or None for numbered IN1..INn, default count, function of the input values, title)
GATES = {
    "AND": (None, 2, lambda v: all(v), "AND"), "OR": (None, 2, lambda v: any(v), "OR"),
    "XOR": (None, 2, lambda v: sum(bool(x) for x in v) % 2 == 1, "Exclusive OR"),
    "NAND": (None, 2, lambda v: not all(v), "NAND"), "NOR": (None, 2, lambda v: not any(v), "NOR"),
    "NOT": (("IN",), 1, lambda v: not v[0], "Invert"),
    "ADD": (None, 2, lambda v: sum(v), "Add"), "MUL": (None, 2, lambda v: math.prod(v), "Multiply"),
    "SUB": (("IN1", "IN2"), 2, lambda v: v[0] - v[1], "Subtract"), "DIV": (("IN1", "IN2"), 2, lambda v: int_div(*v), "Divide"),
    "MOD": (("IN1", "IN2"), 2, lambda v: int_mod(*v), "Remainder"), "ABS": (("IN",), 1, lambda v: abs(v[0]), "Absolute value"),
    "NEG": (("IN",), 1, lambda v: -v[0], "Negate"), "SQRT": (("IN",), 1, lambda v: FUNCTIONS["SQRT"][0](v[0]), "Square root"),
    "MIN": (None, 2, lambda v: min(v), "Minimum"), "MAX": (None, 2, lambda v: max(v), "Maximum"),
    "LIMIT": (("MN", "IN", "MX"), 3, lambda v: max(v[0], min(v[1], v[2])), "Limit"),
    "SCALE": (("IN", "IN_LO", "IN_HI", "OUT_LO", "OUT_HI"), 5, lambda v: FUNCTIONS["SCALE"][0](*v), "Scale"),
    "SEL": (("G", "IN0", "IN1"), 3, lambda v: v[2] if v[0] else v[1], "Select"),
    "MOVE": (("IN",), 1, lambda v: v[0], "Move"),
    "GT": (("IN1", "IN2"), 2, lambda v: v[0] > v[1], "Greater than"), "GE": (("IN1", "IN2"), 2, lambda v: v[0] >= v[1], "At least"),
    "LT": (("IN1", "IN2"), 2, lambda v: v[0] < v[1], "Less than"), "LE": (("IN1", "IN2"), 2, lambda v: v[0] <= v[1], "At most"),
    "EQ": (("IN1", "IN2"), 2, lambda v: v[0] == v[1], "Equal"), "NE": (("IN1", "IN2"), 2, lambda v: v[0] != v[1], "Not equal"),
}
DEFAULT_ZERO = {"AND": True, "NAND": True}      # an unwired input of AND doesn't defeat the gate


def pins_of(block) -> tuple:
    """(input pin names, output pin names) of a block as it stands."""
    t = block.get("type")
    if t == "input":
        return (), ("OUT",)
    if t == "output":
        return ("IN",), ()
    if t in GATES:
        names = GATES[t][0]
        if names is None:
            n = block.get("n", GATES[t][1])
            n = n if isinstance(n, int) and not isinstance(n, bool) else GATES[t][1]
            names = tuple(f"IN{i + 1}" for i in range(max(2, min(n, 32))))
        return tuple(names), ("OUT",)
    if t in FB_TYPES:
        return tuple(FB_TYPES[t].PINS), tuple(FB_TYPES[t].OUTS)
    raise CompileError(f"unknown block “{t}”")


def block_title(t: str) -> str:
    if t in GATES:
        return GATES[t][3]
    if t in FB_TYPES:
        return FB_TYPES[t].TITLE
    return {"input": "Read a variable", "output": "Write a variable"}.get(t, t)


def _blocks(source):
    blocks = source.get("blocks") if isinstance(source, dict) else None
    wires = source.get("wires", []) if isinstance(source, dict) else None
    if not isinstance(blocks, list) or not isinstance(wires, list):
        raise CompileError("this function block diagram is damaged")
    if len(blocks) > MAX_ARRAY:
        raise CompileError("this function block diagram is too large")
    seen = set()
    for b in blocks:
        if not isinstance(b, dict) or isinstance(b.get("id"), bool) or not isinstance(b.get("id"), int):
            raise CompileError("a block is damaged")
        if b["id"] in seen:
            raise CompileError(f"two blocks have the number {b['id']}")
        seen.add(b["id"])
    return blocks, wires


def collect(source, program):
    blocks, _w = _blocks(source)
    for b in blocks:
        t = b.get("type")
        if t in FB_TYPES:
            name = str(b.get("name") or "").strip()
            if name:
                if not _NAME.match(name):
                    raise CompileError(f"“{name}” can't be the name of a function block")
                program.auto_fb(name, FB_TYPES[t])
        elif t == "input":
            name = str(b.get("expr") or "").strip()
            if _NAME.match(name):
                program.auto_bool(name)
        elif t == "output":
            name = str(b.get("target") or "").strip()
            if _NAME.match(name):
                program.auto_bool(name)


def _order(blocks, wires) -> list:
    """Signal-flow order; ties and loops go top to bottom, then left to right, as they are drawn."""
    index = {b["id"]: b for b in blocks}
    deps = {b["id"]: set() for b in blocks}
    for w in wires:
        src, dst = _end(w.get("from")), _end(w.get("to"))
        if src is not None and dst is not None and src[0] in index and dst[0] in index:
            deps[dst[0]].add(src[0])

    def pos(i):
        b = index[i]
        x, y = b.get("x", 0), b.get("y", 0)
        return (y if isinstance(y, (int, float)) else 0, x if isinstance(x, (int, float)) else 0, i)
    remaining = dict(deps)
    done = []
    finished = set()
    while remaining:
        ready = sorted((i for i, d in remaining.items() if d <= finished), key=pos)
        pick = ready[0] if ready else sorted(remaining, key=pos)[0]     # a loop: break it at the first block drawn
        done.append(pick)
        finished.add(pick)
        del remaining[pick]
    return [index[i] for i in done]


def _end(e):
    if isinstance(e, list) and len(e) == 2 and isinstance(e[0], int) and not isinstance(e[0], bool) and isinstance(e[1], str):
        return e[0], e[1]
    return None


def compile_pou(source, ctx, program, pou):
    blocks, wires = _blocks(source)
    comp = Compiler(ctx, program, program.scope, pou)
    frame: dict = {}
    drivers: dict = {}
    known = {b["id"]: b for b in blocks}
    for w in wires:
        src, dst = _end(w.get("from") if isinstance(w, dict) else None), _end(w.get("to") if isinstance(w, dict) else None)
        if src is None or dst is None or src[0] not in known or dst[0] not in known:
            raise CompileError("a wire in this diagram is damaged", 0, pou)
        if dst in drivers:
            raise CompileError(f"two wires drive input {dst[1]} of block {dst[0]}", 0, pou)
        drivers[dst] = src
    steps = []
    for b in _order(blocks, wires):
        try:
            steps.append(_block(b, comp, ctx, frame, drivers, known))
        except CompileError as e:
            raise CompileError(f"block {b['id']} ({b.get('type')}): {e.message}", 0, pou) from None

    def run(L):
        for s in steps:
            s(L)
    return frame, run


def _key(i, pin):
    return f"{i}.{pin}"


def _reader(block, pin, comp, frame, drivers, known, default=False):
    """Closure reading one input pin: its wire, else its "pins" expression, else a default."""
    bid = block["id"]
    src = drivers.get((bid, pin))
    negate = pin in (block.get("neg") or [])
    if src is not None:
        if pin_missing(known[src[0]], src[1]):
            raise CompileError(f"block {src[0]} has no output {src[1]}")
        key = _key(*src)
        f = lambda L: L[key]    # noqa: E731
    else:
        text = str((block.get("pins") or {}).get(pin) or "").strip()
        if text:
            f = comp.expr(parse_expression(text))
        else:
            f = lambda L: default  # noqa: E731
    if negate:
        inner = f
        return lambda L: not inner(L)
    return f


def pin_missing(block, pin) -> bool:
    return pin not in pins_of(block)[1]


def _block(b, comp, ctx, frame, drivers, known):
    t = b.get("type")
    bid = b["id"]
    if t == "input":
        text = str(b.get("expr") or "").strip()
        if not text:
            raise CompileError("nothing to read: give it a tag or an expression")
        f = comp.expr(parse_expression(text))
        out = _key(bid, "OUT")
        frame[out] = False

        def read(L):
            L[out] = f(L)
        return read
    if t == "output":
        text = str(b.get("target") or "").strip()
        if not text:
            raise CompileError("nowhere to write: give it a tag")
        store = comp.writer(parse_expression(text))
        f = _reader(b, "IN", comp, frame, drivers, known)

        def write(L):
            store(L, f(L))
        return write
    if t in GATES:
        names, _outs = pins_of(b)
        default = DEFAULT_ZERO.get(t, False) if t in ("AND", "NAND") else (False if t in ("OR", "NOR", "XOR", "NOT") else 0)
        readers = [_reader(b, n, comp, frame, drivers, known, default) for n in names]
        fn = GATES[t][2]
        out = _key(bid, "OUT")
        frame[out] = False

        def gate(L):
            L[out] = fn([r(L) for r in readers])
        return gate
    if t in FB_TYPES:
        return _fb_block(b, t, comp, ctx, frame, drivers, known)
    raise CompileError(f"unknown block “{t}”")


def _fb_block(b, t, comp, ctx, frame, drivers, known):
    cls = FB_TYPES[t]
    bid = b["id"]
    name = str(b.get("name") or "").strip()
    if name:
        v = comp.scope.find(name)
        if v is None or v.type is not cls:
            raise CompileError(f"{name} is already used for something else")
        inst = comp.read_var(v)
    else:
        hidden = f"fb{bid}"
        frame[hidden] = cls
        inst = lambda L: L[hidden]      # noqa: E731
    readers = []
    for pin, default in cls.PINS.items():
        readers.append((pin, _reader(b, pin, comp, frame, drivers, known, default)))
    outs = []
    for pin in cls.OUTS:
        key = _key(bid, pin)
        frame[key] = cls.OUTS[pin]
        outs.append((pin, key))

    def run(L):
        o = inst(L)
        for pin, r in readers:
            setattr(o, pin, r(L))
        o.run(ctx.dt_ms)
        for pin, key in outs:
            L[key] = getattr(o, pin)
    return run


def empty_program() -> dict:
    return {"blocks": [], "wires": []}
