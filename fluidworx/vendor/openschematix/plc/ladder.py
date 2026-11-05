"""Ladder logic. A rung is a series of elements; power enters on the left and each element passes it on.

    {"rungs": [{"comment": "Latch", "items": [
        {"t": "par", "branches": [[{"t": "no", "a": "Start"}], [{"t": "no", "a": "Run"}]]},
        {"t": "nc", "a": "Stop"},
        {"t": "coil", "a": "Run"}]}]}

Operands are ST expressions, so a contact can read a tag, ``T1.Q`` or a whole condition. A name that nobody
declared becomes an internal marker (a BOOL), as on most PLCs.
"""
from __future__ import annotations

import re

from .core import FB_TYPES, CompileError, PlcFault
from .stlang import Compiler, parse_expression, parse_statements

CONTACTS = ("no", "nc", "rise", "fall")
COILS = ("coil", "ncoil", "set", "reset")
TIMERS = ("ton", "tof", "tp")
COUNTERS = ("ctu", "ctd")
COMPARE_OPS = (">", ">=", "<", "<=", "=", "<>")
ELEMENT_TITLES = {"no": "Contact, normally open", "nc": "Contact, normally closed", "rise": "Contact, rising edge",
                  "fall": "Contact, falling edge", "cmp": "Compare", "coil": "Coil", "ncoil": "Coil, inverted",
                  "set": "Set coil", "reset": "Reset coil", "ton": "On-delay timer", "tof": "Off-delay timer",
                  "tp": "Pulse timer", "ctu": "Up counter", "ctd": "Down counter", "move": "Assign value",
                  "st": "Structured text"}
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_DEPTH = 24


def _walk(series, depth=0):
    if not isinstance(series, list):
        raise CompileError("a rung's elements must be a list")
    if depth > MAX_DEPTH:
        raise CompileError("branches are nested too deeply")
    for el in series:
        if not isinstance(el, dict):
            raise CompileError("a rung element is damaged")
        yield el
        if el.get("t") == "par":
            branches = el.get("branches")
            if not isinstance(branches, list):
                raise CompileError("a branch is damaged")
            for b in branches:
                yield from _walk(b, depth + 1)


def rungs_of(source) -> list:
    rungs = source.get("rungs") if isinstance(source, dict) else None
    if not isinstance(rungs, list):
        raise CompileError("this ladder program is damaged")
    return rungs


def collect(source, program):
    """Declare what the ladder implies: markers for unknown simple names and function block instances."""
    for i, rung in enumerate(rungs_of(source), 1):
        if not isinstance(rung, dict):
            raise CompileError(f"rung {i} is damaged")
        try:
            for el in _walk(rung.get("items", [])):
                t = el.get("t")
                name = str(el.get("a", "")).strip()
                if t in TIMERS or t in COUNTERS:
                    if not _NAME.match(name):
                        raise CompileError(f"a {t.upper()} needs an instance name, such as T1")
                    program.auto_fb(name, FB_TYPES[t.upper()])
                elif t in CONTACTS or t in COILS or t == "cmp":
                    if name and _NAME.match(name):
                        program.auto_bool(name)
        except CompileError as e:
            raise CompileError(f"rung {i}: {e.message}") from None


def compile_pou(source, ctx, program, pou):
    frame: dict = {}
    comp = Compiler(ctx, program, program.scope, pou)
    counter = [0]
    rungs = []
    for i, rung in enumerate(rungs_of(source), 1):
        try:
            rungs.append(_series(rung.get("items", []), comp, ctx, frame, counter))
        except CompileError as e:
            raise CompileError(f"rung {i}: {e.message}", 0, pou) from None
    if not rungs:
        return frame, lambda L: None

    def run(L):
        for r in rungs:
            r(L, True)
    return frame, run


def _operand(text, comp, what):
    text = str(text or "").strip()
    if not text:
        raise CompileError(f"{what} has no operand")
    return comp.expr(parse_expression(text))


def _target(text, comp, what):
    text = str(text or "").strip()
    if not text:
        raise CompileError(f"{what} has no operand")
    node = parse_expression(text)
    return comp.writer(node)


def _series(items, comp, ctx, frame, counter):
    fs = [_element(el, comp, ctx, frame, counter) for el in items]
    if not fs:
        return lambda L, p: p
    if len(fs) == 1:
        return fs[0]

    def run(L, p):
        for f in fs:
            p = f(L, p)
        return p
    return run


def _element(el, comp, ctx, frame, counter):
    t = el.get("t")
    if t == "par":
        branches = [_series(b, comp, ctx, frame, counter) for b in el["branches"]]

        def run_par(L, p):
            out = False
            for b in branches:
                if b(L, p):
                    out = True
            return out
        return run_par
    if t == "no":
        a = _operand(el.get("a"), comp, "a contact")
        return lambda L, p: bool(p and a(L))
    if t == "nc":
        a = _operand(el.get("a"), comp, "a contact")
        return lambda L, p: bool(p and not a(L))
    if t in ("rise", "fall"):
        return _edge(t, el, comp, frame, counter)
    if t == "cmp":
        op = el.get("op", ">")
        if op not in COMPARE_OPS:
            raise CompileError(f"unknown comparison {op}")
        test = comp.expr(parse_expression(f"({el.get('a') or '0'}) {op} ({el.get('b') or '0'})"))
        return lambda L, p: bool(p and test(L))
    if t in COILS:
        store = _target(el.get("a"), comp, "a coil")
        if t == "coil":
            def coil(L, p):
                store(L, p)
                return p
            return coil
        if t == "ncoil":
            def ncoil(L, p):
                store(L, not p)
                return p
            return ncoil
        value = t == "set"

        def latch(L, p):
            if p:
                store(L, value)
            return p
        return latch
    if t in TIMERS:
        return _timer(el, comp, ctx)
    if t in COUNTERS:
        return _counter(t, el, comp, ctx)
    if t == "move":
        store = _target(el.get("a"), comp, "an assignment")
        value = _operand(el.get("b"), comp, "an assignment")

        def move(L, p):
            if p:
                store(L, value(L))
            return p
        return move
    if t == "st":
        body = comp.block(parse_statements(str(el.get("code", ""))))

        def st_box(L, p):
            if p:
                body(L)
            return p
        return st_box
    raise CompileError(f"unknown element “{t}”")


def _edge(t, el, comp, frame, counter):
    a = _operand(el.get("a"), comp, "a contact")
    counter[0] += 1
    key = f"edge{counter[0]}"
    frame[key] = False
    rising = t == "rise"

    def edge(L, p):
        now = bool(a(L))
        was = L[key]
        L[key] = now
        return bool(p and (now and not was if rising else was and not now))
    return edge


def _instance(el, comp):
    name = str(el.get("a", "")).strip()
    v = comp.scope.find(name)
    if v is None or isinstance(v.type, str):
        raise CompileError(f"{name} is not a function block")
    return comp.read_var(v), v.type


def _timer(el, comp, ctx):
    inst, ftype = _instance(el, comp)
    if ftype is not FB_TYPES[el["t"].upper()]:
        raise CompileError(f"{el.get('a')} is already used for a {getattr(ftype, '__name__', 'different block')}")
    pt = _operand(el.get("pt") or "T#1s", comp, "a timer")

    def timer(L, p):
        o = inst(L)
        o.IN, o.PT = p, pt(L)
        o.run(ctx.dt_ms)
        return o.Q
    return timer


def _counter(t, el, comp, ctx):
    inst, ftype = _instance(el, comp)
    if ftype is not FB_TYPES[t.upper()]:
        raise CompileError(f"{el.get('a')} is already used for a {getattr(ftype, '__name__', 'different block')}")
    pv = _operand(el.get("pv") or "1", comp, "a counter")
    aux_text = str(el.get("r") or "").strip()
    aux = comp.expr(parse_expression(aux_text)) if aux_text else (lambda L: False)
    if t == "ctu":
        def ctu(L, p):
            o = inst(L)
            o.CU, o.R, o.PV = p, aux(L), pv(L)
            o.run(ctx.dt_ms)
            return o.Q
        return ctu

    def ctd(L, p):
        o = inst(L)
        o.CD, o.LD, o.PV = p, aux(L), pv(L)
        o.run(ctx.dt_ms)
        return o.Q
    return ctd


def empty_program() -> dict:
    return {"rungs": [{"comment": "", "items": []}]}


__all__ = ["collect", "compile_pou", "empty_program", "PlcFault"]
