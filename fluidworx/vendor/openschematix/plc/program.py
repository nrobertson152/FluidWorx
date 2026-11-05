"""A PLC as a drawing stores it, and building it into something that runs.

A PLC block's parameters (Component.params):

    {"di": 8, "do": 6, "ai": 2, "ao": 1, "do_type": "source", "tags": {"I0": "Start", "Q0": "Extend"},
     "program": {"version": 1, "scan_ms": 10,
                 "io": {"AI0": {"signal": "4-20mA", "lo": 0, "hi": 250, "unit": "bar"}, "I0": {"note": "..."}},
                 "vars": [{"name": "Count", "type": "INT", "init": "0", "note": ""}],
                 "pous": [{"name": "Main", "lang": "ld", "source": {...}}]}}

Input and output names (I0, Q0, AI0, AO0) are valid identifiers in all six languages, and a tag is another name for
the same place. Nothing in a file is trusted: every field is checked, and a damaged program is an error message,
never a crash. See docs/PLC.md.
"""
from __future__ import annotations

import copy
import keyword
import math
import re

from . import clang, fbd, ladder, pylang, sfc, stlang
from .core import (FB_TYPES, MAX_ARRAY, SCAN_BUDGET, ArrayType, CompileError, Ctx, Diag, PlcError, PlcFault, Scope, Var,
                   new_value)
from .stlang import UserFbType, UserFunc

LANGUAGES = {"ld": "Ladder logic", "fbd": "Function block diagram", "sfc": "Sequential function chart",
             "st": "Structured text", "c": "C", "python": "Python"}
MAX_IO = 64
MAX_POUS = 32
MAX_SOURCE = 1_000_000
DO_TYPES = {"source": "Sourcing (switches L+ to the output)", "sink": "Sinking (switches the output to M)",
            "relay": "Relay (switches the output to C)"}
SIGNALS = {"0-10V": (0.0, 10.0, "V"), "4-20mA": (4.0, 20.0, "mA"), "0-20mA": (0.0, 20.0, "mA"),
           "+-10V": (-10.0, 10.0, "V"), "0-5V": (0.0, 5.0, "V")}
DEFAULT_SIGNAL = "0-10V"
SCAN_LIMITS = (1, 1000)
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ADDR = re.compile(r"^(?:I|Q|AI|AO)\d+$")


def default_params() -> dict:
    return {"di": 8, "do": 6, "ai": 2, "ao": 1, "do_type": "source", "tags": {}, "program": {}}


def _count(v, default):
    if isinstance(v, bool) or not isinstance(v, int):
        return default
    return max(0, min(v, MAX_IO))


def io_counts(params) -> tuple:
    """(digital in, digital out, analog in, analog out), always within limits, whatever a file says."""
    p = params if isinstance(params, dict) else {}
    d = default_params()
    return (_count(p.get("di"), d["di"]), _count(p.get("do"), d["do"]), _count(p.get("ai"), d["ai"]),
            _count(p.get("ao"), d["ao"]))


def do_type(params) -> str:
    t = params.get("do_type") if isinstance(params, dict) else None
    return t if isinstance(t, str) and t in DO_TYPES else "source"


def addresses(params) -> dict:
    di, do, ai, ao = io_counts(params)
    return {"di": [f"I{i}" for i in range(di)], "do": [f"Q{i}" for i in range(do)],
            "ai": [f"AI{i}" for i in range(ai)], "ao": [f"AO{i}" for i in range(ao)]}


def tags_of(params) -> dict:
    raw = params.get("tags") if isinstance(params, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {k: v.strip() for k, v in raw.items() if isinstance(k, str) and isinstance(v, str) and v.strip()}


def program_of(params) -> dict:
    """The stored program in its full form; missing or damaged parts come back as their defaults."""
    raw = params.get("program") if isinstance(params, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    scan = raw.get("scan_ms")
    if isinstance(scan, bool) or not isinstance(scan, (int, float)) or not math.isfinite(scan):
        scan = 10
    io = raw.get("io")
    variables = raw.get("vars")
    pous = raw.get("pous")
    if not isinstance(pous, list) or not pous:
        pous = [new_pou("Main", "ld")]
    return {"version": 1, "scan_ms": int(max(SCAN_LIMITS[0], min(scan, SCAN_LIMITS[1]))),
            "io": io if isinstance(io, dict) else {}, "vars": variables if isinstance(variables, list) else [],
            "pous": pous}


def new_pou(name: str, lang: str) -> dict:
    if lang == "ld":
        source = ladder.empty_program()
    elif lang == "fbd":
        source = fbd.empty_program()
    elif lang == "sfc":
        source = sfc.empty_program()
    else:
        source = TEMPLATES.get(lang, "")
    return {"name": name, "lang": lang, "source": source}


TEMPLATES = {
    "st": "(* Runs from top to bottom every scan. Inputs, outputs and tags are ordinary variables. *)\n\n"
          "VAR\n    (* your variables, e.g.  Count : INT := 0;  Dwell : TON; *)\nEND_VAR\n\n",
    "c": "// setup() runs once. loop() runs every scan. Inputs, outputs and tags are ordinary global variables.\n\n"
         "void setup(void) {\n}\n\nvoid loop(void) {\n}\n",
    "python": "# Runs from top to bottom every scan, or define loop() and it alone runs every scan.\n"
              "# Inputs, outputs and tags are ordinary variables. This is a safe subset of Python: see the help.\n\n",
}


def signal_of(program, addr) -> tuple:
    """(signal name, signal lo, signal hi, engineering lo, engineering hi) of an analog channel."""
    cfg = program["io"].get(addr) if isinstance(program.get("io"), dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}
    name = cfg.get("signal")
    if not isinstance(name, str) or name not in SIGNALS:
        name = DEFAULT_SIGNAL
    s_lo, s_hi, _unit = SIGNALS[name]
    lo, hi = cfg.get("lo"), cfg.get("hi")
    good = all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (lo, hi))
    if not good or lo == hi:
        lo, hi = s_lo, s_hi
    return name, s_lo, s_hi, float(lo), float(hi)


class Pou:
    __slots__ = ("name", "lang", "frame", "inits", "start", "setup", "run")

    def __init__(self, name, lang, frame, inits, start, setup, run):
        self.name, self.lang, self.frame, self.inits = name, lang, frame, inits
        self.start, self.setup, self.run = start, setup, run


class Program:
    """Everything known about one PLC after building it. Build it with build()."""

    def __init__(self, params):
        self.params = params
        self.data = program_of(params)
        self.ctx = Ctx()
        self.scope = Scope()
        self.diags: list = []
        self.pous: list = []
        self.st_functions: dict = {}
        self.st_blocks: dict = {}
        self.global_inits: list = []    # (key, maker)
        self.scan_ms = self.data["scan_ms"]
        self.addr = addresses(params)
        self.tags = tags_of(params)
        self._auto: list = []
        self._steps_by_pou: dict = {}

    @property
    def errors(self):
        return [d for d in self.diags if d.level == "error"]

    def err(self, pou, line, message):
        self.diags.append(Diag("error", pou, line, message))

    def warn(self, pou, message):
        self.diags.append(Diag("warning", pou, 0, message))

    # ---- declarations used by the languages
    def auto_bool(self, name):
        if self.scope.find(name) is None and name.upper() not in stlang.KEYWORDS:
            v = Var(name, f"m:{name.casefold()}", "BOOL")
            self.scope.add(name, v)
            self._auto.append(name)
            self.global_inits.append((v.key, lambda L: False))

    def auto_fb(self, name, cls):
        found = self.scope.find(name)
        if found is None:
            v = Var(name, f"m:{name.casefold()}", cls, "fb", writable=False)
            self.scope.add(name, v)
            self.global_inits.append((v.key, lambda L: cls()))
        elif found.type is not cls:
            shown = getattr(found.type, "__name__", found.type)
            raise CompileError(f"{name} is already declared as {shown}, not {cls.__name__}")

    def declare_step(self, name):
        if self.scope.find(name) is not None:
            raise CompileError(f"the step {name} has the same name as a tag or a variable")
        v = Var(name, f"s:{name.casefold()}", sfc.StepState, "step", writable=False)
        self.scope.add(name, v)
        self.global_inits.append((v.key, lambda L, n=name: sfc.StepState(n)))

    def sfc_steps(self, pou):
        return self._steps_by_pou.get(pou, [])

    def address(self, text):
        """Var for %IX0.3, %I3, %QX0.1, %Q1, %IW0, %QW0, %MX0.0, %M5, %MW2."""
        m = re.match(r"^%([IQM])([XBWDL]?)(\d+)(?:\.(\d+))?$", text.upper())
        if not m:
            return None
        area, size, a, b = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        if size in ("W", "D", "L", "B"):
            if area == "M":
                return self._memory_cell(f"M{size}{a}", "INT" if size != "D" else "DINT")
            return self.scope.find(("AI" if area == "I" else "AO") + str(a))
        n = a * 8 + int(b) if b is not None else a
        if area == "M":
            return self._memory_cell(f"M{n}", "BOOL")
        return self.scope.find(("I" if area == "I" else "Q") + str(n))

    def _memory_cell(self, name, typ):
        v = self.scope.find(name)
        if v is None:
            v = Var(name, f"m:{name.casefold()}", typ)
            self.scope.add(name, v)
            self.global_inits.append((v.key, lambda L: new_value(typ)))
            self.ctx.G[v.key] = new_value(typ)
        return v


def build(params) -> Program:
    """Compile a PLC. Problems end up in .diags, so that all of them can be shown at once. Never raises for a
    damaged program."""
    prog = Program(params)
    try:
        _declare_system(prog)
        _declare_io(prog)
        _declare_vars(prog)
        pous = _clean_pous(prog)
        parsed = _collect_all(prog, pous)
        _build_st_declarations(prog, parsed)
        for pou in pous:
            _compile_one(prog, pou, parsed)
    except CompileError as e:
        prog.err(e.where, e.line, e.message)
    except (RecursionError, MemoryError) as e:
        prog.err("", 0, f"this program is too large or too deeply nested to build ({type(e).__name__})")
    return prog


def _declare_system(prog):
    for name, typ in (("first_scan", "BOOL"), ("now_ms", "TIME"), ("scan_ms", "TIME")):
        prog.scope.add(name, Var(name, f"sys:{name}", typ, "sys", writable=False))
        prog.ctx.G[f"sys:{name}"] = new_value(typ)


def _declare_io(prog):
    for kind, typ, writable in (("di", "BOOL", False), ("do", "BOOL", True), ("ai", "REAL", False), ("ao", "REAL", True)):
        for addr in prog.addr[kind]:
            v = Var(addr, addr, typ, "input" if not writable else "output", writable=writable)
            prog.scope.add(addr, v)
            prog.global_inits.append((addr, lambda L, t=typ: new_value(t)))
    for addr, tag in prog.tags.items():
        if not _ADDR.match(addr):
            continue
        v = prog.scope.find(addr)
        if v is None or v.key != addr:
            prog.warn("I/O", f"the tag {tag} is on {addr}, which this PLC doesn't have")
            continue
        problem = _name_problem(tag)
        if problem:
            prog.err("I/O", 0, f"{addr}: {problem}")
            continue
        if prog.scope.find(tag) is not None:
            prog.err("I/O", 0, f"{addr}: the tag {tag} is already used")
            continue
        prog.scope.add(tag, v)


def _name_problem(name):
    if not _NAME.match(name):
        return f"“{name}” can't be a name: use letters, digits and _, starting with a letter"
    if name.upper() in stlang.KEYWORDS or name in clang.KEYWORDS or keyword.iskeyword(name):
        return f"“{name}” is a reserved word in one of the PLC languages"
    if name.upper() in FB_TYPES:
        return f"“{name}” is the name of a standard function block"
    return ""


def _declare_vars(prog):
    comp = stlang.Compiler(prog.ctx, prog, prog.scope, "Variables")
    for row in prog.data["vars"]:
        if not isinstance(row, dict):
            prog.err("Variables", 0, "a row in the variable table is damaged")
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        problem = _name_problem(name)
        if problem:
            prog.err("Variables", 0, problem)
            continue
        if prog.scope.find(name) is not None:
            prog.err("Variables", 0, f"{name} is declared twice, or is also a tag")
            continue
        try:
            typ = comp.resolve_type(stlang.Parser(stlang.tokenize(str(row.get("type") or "BOOL"))).type_spec(), 0)
            text = str(row.get("init") or "").strip()
            init = stlang.parse_expression(text) if text else None
            v = Var(name, f"m:{name.casefold()}", typ, "fb" if not isinstance(typ, (str, ArrayType)) else "memory",
                    writable=isinstance(typ, (str, ArrayType)))
            prog.scope.add(name, v)
            if init is not None:
                prog.global_inits.append((v.key, comp.initial_maker(typ, init, 0)))
            else:
                prog.global_inits.append((v.key, lambda L, t=typ: new_value(t)))
        except CompileError as e:
            prog.err("Variables", 0, f"{name}: {e.message}")


def _clean_pous(prog) -> list:
    out = []
    names = set()
    raw = prog.data["pous"]
    if len(raw) > MAX_POUS:
        prog.err("", 0, f"a PLC can have at most {MAX_POUS} programs")
        raw = raw[:MAX_POUS]
    for i, p in enumerate(raw, 1):
        if not isinstance(p, dict):
            prog.err(f"Program {i}", 0, "this program is damaged")
            continue
        name = str(p.get("name") or f"Program {i}")
        lang = p.get("lang")
        if lang not in LANGUAGES:
            prog.err(name, 0, f"unknown language {lang!r}")
            continue
        if name.casefold() in names:
            prog.err(name, 0, "two programs have this name")
            continue
        names.add(name.casefold())
        source = p.get("source")
        if lang in ("st", "c", "python"):
            if not isinstance(source, str):
                prog.err(name, 0, "this program is damaged")
                continue
            if len(source) > MAX_SOURCE:
                prog.err(name, 0, "this program is too long")
                continue
        elif not isinstance(source, dict):
            prog.err(name, 0, "this program is damaged")
            continue
        if p.get("disabled") is True:
            continue
        out.append({"name": name, "lang": lang, "source": source})
    return out


def _collect_all(prog, pous) -> dict:
    """What every program declares goes in first, so that programs can read each other's markers and steps."""
    parsed = {}
    for pou in pous:
        lang, name = pou["lang"], pou["name"]
        try:
            if lang == "ld":
                ladder.collect(pou["source"], prog)
            elif lang == "fbd":
                fbd.collect(pou["source"], prog)
            elif lang == "sfc":
                sfc.collect(pou["source"], prog)
                prog._steps_by_pou[name] = pou["source"]["steps"]
            elif lang == "st":
                decls, funcs, body = stlang.parse_program(pou["source"])
                parsed[name] = (decls, funcs, body)
                for d in decls:
                    if d["section"] == "VAR_GLOBAL":
                        _declare_st_global(prog, d, name)
        except CompileError as e:
            prog.err(name, e.line, e.message)
        except RecursionError:
            prog.err(name, 0, "this program is too deeply nested")
    return parsed


def _declare_st_global(prog, d, pou):
    comp = stlang.Compiler(prog.ctx, prog, prog.scope, pou)
    typ = comp.resolve_type(d["type"], d["line"])
    if prog.scope.find(d["name"]) is not None:
        raise CompileError(f"{d['name']} is declared twice", d["line"])
    v = Var(d["name"], f"m:{d['name'].casefold()}", typ, "memory" if isinstance(typ, (str, ArrayType)) else "fb",
            writable=isinstance(typ, (str, ArrayType)) and not d["const"])
    prog.scope.add(d["name"], v)
    prog.global_inits.append((v.key, comp.initial_maker(typ, d["init"], d["line"])))


def _build_st_declarations(prog, parsed):
    """FUNCTIONs and FUNCTION_BLOCKs are known to every ST program, whichever one defines them."""
    items = []
    for pou, (_d, funcs, _b) in parsed.items():
        for f in funcs:
            upper = f["name"].upper()
            if upper in prog.st_functions or upper in prog.st_blocks:
                prog.err(pou, f["line"], f"{f['name']} is defined twice")
                continue
            if f["fb"]:
                prog.st_blocks[upper] = UserFbType(f["name"])
            else:
                prog.st_functions[upper] = UserFunc(f["name"], f["ret"])
            items.append((pou, f))
    for pou, f in items:
        try:
            _define_st_item(prog, pou, f)
        except CompileError as e:
            prog.err(pou, e.line, e.message)


def _define_st_item(prog, pou, f):
    scope = Scope(prog.scope)
    comp = stlang.Compiler(prog.ctx, prog, scope, pou)
    upper = f["name"].upper()
    target = prog.st_blocks.get(upper) or prog.st_functions[upper]
    is_fb = f["fb"]
    if not is_fb and f["ret"] != "VOID":
        ret = comp.resolve_type(f["ret"], f["line"])
        scope.add(f["name"], Var(f["name"], "$ret", ret, "memory", local=True))
    for d in f["decls"]:
        typ = comp.resolve_type(d["type"], d["line"])
        kind = {"VAR_INPUT": "fb_in", "VAR_OUTPUT": "fb_out"}.get(d["section"], "memory")
        if kind == "memory" and not isinstance(typ, (str, ArrayType)):
            kind = "fb"
        key = d["name"].upper()
        v = Var(d["name"], key, typ, kind, local=True, writable=isinstance(typ, (str, ArrayType)))
        scope.add(d["name"], v)
        target.inits.append((key, comp.initial_maker(typ, d["init"], d["line"])))
        if is_fb:
            target.vars[key] = v
        elif d["section"] == "VAR_INPUT":
            target.inputs.append(v)
    target.body = comp.block(f["body"])


def _compile_one(prog, pou, parsed):
    name, lang = pou["name"], pou["lang"]
    if prog.errors and lang != "st" and any(d.pou == name for d in prog.errors):
        return
    try:
        if lang == "st":
            if name not in parsed:
                return
            _compile_st(prog, name, parsed[name])
        elif lang in ("ld", "fbd", "sfc"):
            mod = {"ld": ladder, "fbd": fbd, "sfc": sfc}[lang]
            frame, run = mod.compile_pou(pou["source"], prog.ctx, prog, name)
            prog.pous.append(Pou(name, lang, frame, _frame_inits(frame), None, None, run))
        elif lang == "c":
            frame, inits, setup, loop = clang.compile_unit(pou["source"], prog.ctx, prog, name)
            prog.pous.append(Pou(name, lang, frame, inits, None, setup, loop))
        else:
            module, start, setup, loop = pylang.compile_unit(pou["source"], prog.ctx, prog, name)
            prog.pous.append(Pou(name, lang, module, [], start, setup, loop))
    except CompileError as e:
        prog.err(name, e.line, e.message)
    except (RecursionError, MemoryError):
        prog.err(name, 0, "this program is too large or too deeply nested to build")


def _frame_inits(frame) -> list:
    """Frames of the graphic languages start with plain values, kept so that a reset can restore them."""
    start = dict(frame)
    out = []
    for k, v in start.items():
        if isinstance(v, type):
            out.append((k, lambda L, c=v: c()))
        elif isinstance(v, dict):
            out.append((k, lambda L, d=v: (d.clear(), d)[1]))
        else:
            out.append((k, lambda L, x=v: x))
    return out


def _compile_st(prog, name, parsed):
    decls, _funcs, body = parsed
    scope = Scope(prog.scope)
    comp = stlang.Compiler(prog.ctx, prog, scope, name)
    frame: dict = {}
    inits = []
    for d in decls:
        if d["section"] == "VAR_GLOBAL":
            continue
        line = d["line"]
        if d["addr"]:
            v = prog.address(d["addr"])
            if v is None:
                raise CompileError(f"this PLC has no address {d['addr']}", line)
            scope.add(d["name"], v)
            continue
        typ = comp.resolve_type(d["type"], line)
        if scope.own(d["name"]) is not None:
            raise CompileError(f"{d['name']} is declared twice", line)
        if prog.scope.find(d["name"]) is not None and prog.scope.find(d["name"]).kind in ("input", "output"):
            raise CompileError(f"{d['name']} is already an input or output of this PLC", line)
        key = d["name"].upper()
        v = Var(d["name"], key, typ, "memory" if isinstance(typ, (str, ArrayType)) else "fb", local=True,
                writable=isinstance(typ, (str, ArrayType)) and not d["const"])
        scope.add(d["name"], v)
        inits.append((key, comp.initial_maker(typ, d["init"], line)))
    run = comp.block(body)
    prog.pous.append(Pou(name, "st", frame, inits, None, None, run))


# ---------------------------------------------------------------- running it
class Runtime:
    """One PLC running. Each scan: inputs are copied in, every program runs in order, outputs are read out.

    A fault stops the PLC, as a real one goes to STOP: outputs drop and the reason is in `fault`."""

    def __init__(self, program: Program):
        self.program = program
        self.ctx = program.ctx
        self.fault = ""
        self.scans = 0
        self.running = False
        self._ai = {a: signal_of(program.data, a) for a in program.addr["ai"]}
        self._ao = {a: signal_of(program.data, a) for a in program.addr["ao"]}
        self.reset()

    @property
    def ok(self):
        return not self.program.errors

    def reset(self):
        """A cold start: every variable back to its starting value."""
        self.fault = ""
        self.scans = 0
        ctx = self.ctx
        ctx.now_ms = 0
        ctx.messages.clear()
        ctx.budget = SCAN_BUDGET
        ctx.depth = 0
        ctx.dt_ms = self.program.scan_ms
        self.running = self.ok
        if not self.ok:
            return
        G = ctx.G
        keep = {k: v for k, v in G.items() if k.startswith("sys:")}
        G.clear()
        G.update(keep)
        try:
            for key, make in self.program.global_inits:
                G[key] = make({})
            G["sys:first_scan"] = True
            G["sys:scan_ms"] = self.program.scan_ms
            G["sys:now_ms"] = 0
            for pou in self.program.pous:
                pou.frame.clear()
                for key, make in pou.inits:
                    pou.frame[key] = make(pou.frame)
                if pou.start is not None:
                    pou.start(pou.frame)
                if pou.setup is not None:
                    pou.setup({})
        except (PlcFault, RecursionError, MemoryError) as e:
            self._stop(e)
        except (TypeError, ValueError, ArithmeticError, LookupError, AttributeError) as e:
            self._stop(e)

    def _stop(self, e):
        text = str(e) if isinstance(e, PlcError) else f"{type(e).__name__}: {e}"
        self.fault = text[:300] or type(e).__name__
        self.running = False
        for addr in self.program.addr["do"]:
            self.ctx.G[addr] = False
        for addr in self.program.addr["ao"]:
            self.ctx.G[addr] = self._ao[addr][3] if addr in self._ao else 0.0

    def set_input(self, addr, value):
        self.ctx.G[addr] = value

    def set_analog_raw(self, addr, raw):
        """An analog input arrives in its signal's units (V or mA); the program sees engineering units."""
        _n, s_lo, s_hi, lo, hi = self._ai[addr]
        self.ctx.G[addr] = lo + (float(raw) - s_lo) * (hi - lo) / (s_hi - s_lo)

    def analog_output_raw(self, addr) -> float:
        _n, s_lo, s_hi, lo, hi = self._ao[addr]
        v = self.ctx.G.get(addr, lo)
        raw = s_lo + (float(v) - lo) * (s_hi - s_lo) / (hi - lo)
        return max(s_lo, min(raw, s_hi))

    def scan(self, dt_ms=None):
        """One scan. Returns True if the PLC is still running."""
        if not self.running:
            return False
        ctx = self.ctx
        ctx.budget = SCAN_BUDGET
        ctx.depth = 0
        ctx.dt_ms = self.program.scan_ms if dt_ms is None else dt_ms
        G = ctx.G
        try:
            for pou in self.program.pous:
                pou.run(pou.frame)
        except (PlcFault, RecursionError, MemoryError) as e:
            self._stop(e)
            return False
        except (TypeError, ValueError, ArithmeticError, LookupError, AttributeError) as e:
            self._stop(e)
            return False
        G["sys:first_scan"] = False
        ctx.now_ms += ctx.dt_ms
        G["sys:now_ms"] = ctx.now_ms
        self.scans += 1
        return True

    def read(self, name):
        """Value of an address, tag or global variable, for a display."""
        v = self.program.scope.find(name)
        if v is None or v.local:
            return None
        value = self.ctx.G.get(v.key)
        return value.active if v.kind == "step" and value is not None else value

    def watch(self) -> list:
        """(name, value) of everything simple worth showing live: tags or addresses first, then variables."""
        out = []
        seen = set()
        tag_of = {addr: tag for addr, tag in self.program.tags.items()}
        for kind in ("di", "do", "ai", "ao"):
            for addr in self.program.addr[kind]:
                seen.add(addr)
                out.append((addr, tag_of.get(addr, ""), self.ctx.G.get(addr)))
        for name, v in self.program.scope.names.items():
            if v.key in seen or v.kind in ("sys", "input", "output"):
                continue
            seen.add(v.key)
            val = self.ctx.G.get(v.key)
            if isinstance(v.type, str):
                out.append((v.name, "", val))
            elif v.kind == "step" and val is not None:
                out.append((v.name, "step", val.active))
            elif v.kind == "fb" and val is not None:
                state = getattr(val, "Q", getattr(val, "Q1", None))
                if state is not None:
                    out.append((v.name, v.type.__name__, state))
        return out


def check(params) -> list:
    """Every problem with a PLC's program, for the editor and for Check drawing."""
    return build(params).diags


def compile_params(params) -> Runtime:
    return Runtime(build(params))


def clone(params) -> dict:
    return copy.deepcopy(params)


__all__ = ["LANGUAGES", "MAX_IO", "build", "check", "compile_params", "default_params", "new_pou", "Program", "Runtime",
           "MAX_ARRAY", "PlcFault"]
