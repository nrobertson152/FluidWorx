"""A safe subset of Python for PLC programs.

Python's own ``exec`` can't be made safe: a drawing from someone else would run with all your rights. So a program
is parsed with ``ast`` and turned into closures here, and only what is listed in this file exists. There are no
imports (``import math`` gives the listed functions and nothing else), no classes, no attributes except the listed
methods and function block pins, no ``eval``, no files. Numbers and containers are size-checked, so a program can't
exhaust memory, and the scan budget stops endless loops.
"""
from __future__ import annotations

import ast
import math
import re

from .core import (FB_TYPES, MAX_ARRAY, MAX_CALL_DEPTH, MAX_NEST, CompileError, Fb, PlcFault, _checked, scale)

BREAK, CONTINUE, RETURN = 1, 2, 3
RET = "$ret"
INT_LIMIT = 1 << 64
COST_LIMIT = 100_000
SCALARS = (bool, int, float, str, type(None))
_SAFE_MATH = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
              "acos": math.acos, "atan": math.atan, "atan2": math.atan2, "exp": math.exp, "log": math.log,
              "log10": math.log10, "floor": math.floor, "ceil": math.ceil, "fabs": math.fabs, "hypot": math.hypot,
              "degrees": math.degrees, "radians": math.radians, "isnan": math.isnan, "isinf": math.isinf,
              "trunc": math.trunc, "copysign": math.copysign, "fmod": math.fmod}


class _MathModule:
    __slots__ = ()
    CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


MATH = _MathModule()


def _guard(*values):
    """Walk containers before an operation that visits everything in them, so its cost stays bounded."""
    budget = COST_LIMIT
    stack = list(values)
    while stack:
        v = stack.pop()
        t = type(v)
        if t in SCALARS or isinstance(v, Fb):
            continue
        if t in (list, tuple):
            budget -= len(v) + 1
            stack.extend(v)
        elif t is dict:
            budget -= len(v) * 2 + 1
            stack.extend(v.keys())
            stack.extend(v.values())
        else:
            budget -= 1
        if budget < 0:
            raise PlcFault("this list or dictionary is too large for that operation")


def _fit(v):
    t = type(v)
    if t is int:
        if not -INT_LIMIT <= v <= INT_LIMIT:
            raise PlcFault("a whole number grew past 64 bits")
    elif t in (list, str, tuple):
        if len(v) > MAX_ARRAY:
            raise PlcFault(f"a list or string grew past {MAX_ARRAY:,} items")
    return v


def _add(a, b):
    if type(a) in (list, str, tuple) and type(b) in (list, str, tuple):
        if len(a) + len(b) > MAX_ARRAY:
            raise PlcFault(f"a list or string grew past {MAX_ARRAY:,} items")
    return _fit(a + b)


def _mul(a, b):
    if type(a) in (list, str, tuple) or type(b) in (list, str, tuple):
        seq, n = (a, b) if type(a) in (list, str, tuple) else (b, a)
        if isinstance(n, int) and len(seq) * max(n, 0) > MAX_ARRAY:
            raise PlcFault(f"a list or string grew past {MAX_ARRAY:,} items")
    return _fit(a * b)


def _pow(a, b):
    if isinstance(a, int) and isinstance(b, int) and b > 0 and abs(a) > 1 and b * math.log2(abs(a)) > 64:
        raise PlcFault("a power grew past 64 bits")
    return a ** b


def _lshift(a, b):
    if b < 0 or b > 64:
        raise PlcFault("a shift must be between 0 and 64 bits")
    return _fit(a << b)


def _mod(a, b):
    if type(a) is str:
        raise PlcFault("% formatting isn't available; use str() and +")
    return a % b


_BIN = {ast.Add: _add, ast.Sub: lambda a, b: _fit(a - b), ast.Mult: _mul, ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b, ast.Mod: _mod, ast.Pow: _pow, ast.LShift: _lshift,
        ast.RShift: lambda a, b: a >> b, ast.BitAnd: lambda a, b: a & b, ast.BitOr: lambda a, b: a | b,
        ast.BitXor: lambda a, b: a ^ b}


def _eq(a, b):
    _guard(a, b)
    return a == b


def _ne(a, b):
    _guard(a, b)
    return a != b


def _in(a, b):
    _guard(a, b)
    return a in b


_CMP = {ast.Eq: _eq, ast.NotEq: _ne, ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b, ast.Is: lambda a, b: a is b,
        ast.IsNot: lambda a, b: a is not b, ast.In: _in, ast.NotIn: lambda a, b: not _in(a, b)}


# ---------------------------------------------------------------- what a program can call
def _str(v=""):
    if type(v) not in SCALARS:
        _guard(v)
    return _fit(str(v))


def _len(v):
    return len(v)


def _sized_iter(v):
    if type(v) is range and len(v) > MAX_ARRAY:
        raise PlcFault(f"this range is longer than {MAX_ARRAY:,} items; loop over it with for")
    if type(v) not in (list, tuple, dict, str, range):
        raise PlcFault("this needs a list, tuple, dict, string or range")
    return v


def _list(v=()):
    _guard(_sized_iter(v) if type(v) is not range else [])
    return list(_sized_iter(v))


def _tuple(v=()):
    _guard(_sized_iter(v) if type(v) is not range else [])
    return tuple(_sized_iter(v))


def _dict(v=()):
    _guard(v)
    return dict(v)


def _sorted(v, reverse=False):
    _guard(_sized_iter(v) if type(v) is not range else [])
    return sorted(_sized_iter(v), reverse=bool(reverse))


def _sum(v, start=0):
    _sized_iter(v)
    return _fit(sum(v, start))


def _minmax(fn):
    def run(*a):
        if len(a) == 1:
            _sized_iter(a[0])
            if type(a[0]) is not range:
                _guard(a[0])
            return fn(a[0])
        _guard(*a)
        return fn(*a)
    return run


def _any(v):
    _sized_iter(v)
    return any(v)


def _all(v):
    _sized_iter(v)
    return all(v)


def _enumerate(v, start=0):
    return [(i + start, x) for i, x in enumerate(_sized_iter(v))]


def _zip(*vs):
    return list(zip(*[_sized_iter(v) for v in vs]))


def _reversed(v):
    return list(reversed(_sized_iter(v)))


def _range(*a):
    for x in a:
        if not isinstance(x, int):
            raise PlcFault("range() takes whole numbers")
    return range(*a)


def _int(v=0):
    if type(v) is str and len(v) > 40:
        raise PlcFault("this text is too long to be a number")
    return _fit(int(v))


def _round(v, n=None):
    return round(v) if n is None else round(v, max(-20, min(int(n), 20)))


BUILTINS = {"abs": abs, "min": _minmax(min), "max": _minmax(max), "sum": _sum, "round": _round, "int": _int,
            "float": float, "bool": bool, "str": _str, "len": _len, "range": _range, "list": _list, "tuple": _tuple,
            "dict": _dict, "sorted": _sorted, "any": _any, "all": _all, "enumerate": _enumerate, "zip": _zip,
            "reversed": _reversed, "scale": scale,
            "limit": lambda lo, x, hi: max(lo, min(x, hi)), "True": True, "False": False, "None": None,
            "math": MATH}
for _name, _cls in FB_TYPES.items():
    BUILTINS[_name] = _cls


def _app(lst, x):
    if len(lst) >= MAX_ARRAY:
        raise PlcFault(f"a list grew past {MAX_ARRAY:,} items")
    lst.append(x)


def _extend(lst, other):
    _sized_iter(other)
    if len(lst) + len(other) > MAX_ARRAY:
        raise PlcFault(f"a list grew past {MAX_ARRAY:,} items")
    lst.extend(other)


def _insert(lst, i, x):
    if len(lst) >= MAX_ARRAY:
        raise PlcFault(f"a list grew past {MAX_ARRAY:,} items")
    lst.insert(i, x)


def _sort(lst, reverse=False):
    _guard(lst)
    lst.sort(reverse=bool(reverse))


def _join(s, items):
    _sized_iter(items)
    if type(items) is not range:
        _guard(items)
    total = sum(len(x) for x in items) + len(s) * len(items)
    if total > MAX_ARRAY:
        raise PlcFault(f"a string grew past {MAX_ARRAY:,} characters")
    return s.join(items)


def _dset(d, k, default=None):
    if k not in d and len(d) >= MAX_ARRAY:
        raise PlcFault(f"a dictionary grew past {MAX_ARRAY:,} items")
    return d.setdefault(k, default)


def _dupdate(d, other):
    _guard(other)
    if len(d) + len(other) > MAX_ARRAY:
        raise PlcFault(f"a dictionary grew past {MAX_ARRAY:,} items")
    d.update(other)


METHODS = {
    list: {"append": _app, "extend": _extend, "insert": _insert, "pop": list.pop, "remove": list.remove,
           "clear": list.clear, "index": list.index, "count": list.count, "reverse": list.reverse, "sort": _sort},
    dict: {"get": dict.get, "pop": dict.pop, "clear": dict.clear, "setdefault": _dset, "update": _dupdate,
           "keys": lambda d: list(d.keys()), "values": lambda d: list(d.values()), "items": lambda d: list(d.items())},
    str: {"upper": str.upper, "lower": str.lower, "strip": str.strip, "startswith": str.startswith,
          "endswith": str.endswith, "split": str.split, "join": _join, "find": str.find},
    tuple: {"index": tuple.index, "count": tuple.count},
}


class PyFunc:
    __slots__ = ("name", "params", "defaults", "body", "locals")

    def __init__(self, name):
        self.name = name
        self.params, self.defaults, self.body, self.locals = [], [], None, set()


class BoundFb:
    """Calling a function block: dwell(IN=x, PT=2000), which sets those pins and runs one scan of it."""
    __slots__ = ()


# ---------------------------------------------------------------- compiler
FORBIDDEN_HINT = {
    ast.ClassDef: "classes aren't available", ast.Lambda: "lambda isn't available", ast.Try: "try isn't available",
    ast.With: "with isn't available", ast.Yield: "generators aren't available", ast.YieldFrom: "generators aren't available",
    ast.AsyncFunctionDef: "async isn't available", ast.Await: "async isn't available",
    ast.GeneratorExp: "generators aren't available; use a list comprehension", ast.Raise: "raise isn't available",
    ast.Delete: "del isn't available", ast.Nonlocal: "nonlocal isn't available", ast.NamedExpr: ":= isn't available",
    ast.Set: "sets aren't available", ast.SetComp: "sets aren't available", ast.DictComp: "dict comprehensions aren't available",
    ast.Starred: "* unpacking isn't available",
}


class Compiler:
    def __init__(self, ctx, program, pou):
        self.ctx, self.program, self.pou = ctx, program, pou
        self.G = ctx.G
        self.module: dict = {}          # the program's own global variables
        self.funcs: dict = {}
        self.func = None                # function being compiled
        self.global_names: set = set()

    def err(self, msg, node=None):
        raise CompileError(msg, getattr(node, "lineno", 0) or 0, self.pou)

    # ---- names
    def _io(self, name):
        return self.program.scope.find_exact(name)

    def read_name(self, node):
        name = node.id
        if name.startswith("__"):
            self.err(f"{name} isn't available", node)
        if self.func is not None and name in self.func.locals:
            def read_local(L):
                try:
                    return L[name]
                except KeyError:
                    raise PlcFault(f"{name} is read before it has a value") from None
            return read_local
        v = self._io(name)
        if v is not None:
            G, key = self.G, v.key
            return lambda L: G[key]
        M = self.module
        if name in BUILTINS:
            builtin = BUILTINS[name]

            def read_shadowable(L):
                return M.get(name, builtin)
            return read_shadowable
        if name in self.funcs or name in self.global_names:
            def read_global(L):
                try:
                    return M[name]
                except KeyError:
                    raise PlcFault(f"{name} is read before it has a value") from None
            return read_global
        self.err(f"“{name}” is not defined. Tags and variables of this PLC, and names you assign, can be read here.",
                 node)

    def write_name(self, node, name=None):
        name = name or node.id
        if name.startswith("__"):
            self.err(f"{name} isn't available", node)
        if self.func is not None and name in self.func.locals:
            def write_local(L, v):
                L[name] = _fit(v)
            return write_local
        v = self._io(name)
        if v is not None:
            if not v.writable:
                what = "an input" if v.kind == "input" else "read-only"
                self.err(f"{name} is {what}, so a program can't write to it", node)
            if not isinstance(v.type, str):
                self.err(f"{name} can't be assigned as a whole", node)
            from .core import coercer
            conv = coercer(v.type)
            G, key = self.G, v.key

            def write_tag(L, value):
                G[key] = conv(value)
            return write_tag
        M = self.module

        def write_global(L, value):
            M[name] = _fit(value)
        return write_global

    # ---- expressions
    def expr(self, n):
        t = type(n)
        if t is ast.Constant:
            v = n.value
            if not isinstance(v, (bool, int, float, str, type(None))):
                self.err("this kind of constant isn't available", n)
            if isinstance(v, str) and len(v) > MAX_ARRAY:
                self.err("this string is too long", n)
            if type(v) is int and not -INT_LIMIT <= v <= INT_LIMIT:
                self.err("this number is larger than 64 bits", n)
            return lambda L: v
        if t is ast.Name:
            return self.read_name(n)
        if t is ast.BinOp:
            fn = _BIN.get(type(n.op))
            if fn is None:
                self.err("this operator isn't available", n)
            a, b = self.expr(n.left), self.expr(n.right)
            return lambda L: fn(a(L), b(L))
        if t is ast.UnaryOp:
            a = self.expr(n.operand)
            if isinstance(n.op, ast.Not):
                return lambda L: not a(L)
            if isinstance(n.op, ast.USub):
                return lambda L: -a(L)
            if isinstance(n.op, ast.UAdd):
                return lambda L: +a(L)
            if isinstance(n.op, ast.Invert):
                return lambda L: ~a(L)
        if t is ast.BoolOp:
            fs = [self.expr(v) for v in n.values]
            if isinstance(n.op, ast.And):
                def run_and(L):
                    r = True
                    for f in fs:
                        r = f(L)
                        if not r:
                            return r
                    return r
                return run_and

            def run_or(L):
                r = False
                for f in fs:
                    r = f(L)
                    if r:
                        return r
                return r
            return run_or
        if t is ast.Compare:
            return self._compare(n)
        if t is ast.IfExp:
            c, a, b = self.expr(n.test), self.expr(n.body), self.expr(n.orelse)
            return lambda L: a(L) if c(L) else b(L)
        if t is ast.List:
            fs = [self.expr(e) for e in n.elts]
            return lambda L: [f(L) for f in fs]
        if t is ast.Tuple:
            fs = [self.expr(e) for e in n.elts]
            return lambda L: tuple(f(L) for f in fs)
        if t is ast.Dict:
            if any(k is None for k in n.keys):
                self.err("** unpacking isn't available", n)
            ks = [self.expr(k) for k in n.keys]
            vs = [self.expr(v) for v in n.values]
            return lambda L: {k(L): v(L) for k, v in zip(ks, vs)}
        if t is ast.Subscript:
            return self._subscript(n)
        if t is ast.Attribute:
            return self._attribute(n)
        if t is ast.Call:
            return self._call(n)
        if t is ast.ListComp:
            return self._listcomp(n)
        if t is ast.JoinedStr:
            return self._fstring(n)
        self.err(FORBIDDEN_HINT.get(t, f"{t.__name__} isn't available in a PLC program"), n)

    def _compare(self, n):
        a0 = self.expr(n.left)
        pairs = [(_CMP[type(op)], self.expr(c)) for op, c in zip(n.ops, n.comparators)]
        if len(pairs) == 1:
            fn, b = pairs[0]
            return lambda L: fn(a0(L), b(L))

        def chain(L):
            x = a0(L)
            for fn, b in pairs:
                y = b(L)
                if not fn(x, y):
                    return False
                x = y
            return True
        return chain

    def _slice(self, s):
        if type(s) is ast.Slice:
            a = self.expr(s.lower) if s.lower is not None else (lambda L: None)
            b = self.expr(s.upper) if s.upper is not None else (lambda L: None)
            c = self.expr(s.step) if s.step is not None else (lambda L: None)
            return lambda L: slice(a(L), b(L), c(L))
        return self.expr(s)

    def _subscript(self, n):
        base, idx = self.expr(n.value), self._slice(n.slice)
        return lambda L: base(L)[idx(L)]

    def _attribute(self, n):
        name = n.attr
        if name.startswith("_"):
            self.err(f"{name} isn't available", n)
        if isinstance(n.value, ast.Name) and n.value.id == "math" and "math" not in self.global_names:
            if name in _SAFE_MATH:
                f = _checked(_SAFE_MATH[name])
                return lambda L: f
            if name in _MathModule.CONSTS:
                c = _MathModule.CONSTS[name]
                return lambda L: c
            self.err(f"math.{name} isn't available", n)
        base = self.expr(n.value)

        def read(L):
            o = base(L)
            if isinstance(o, Fb):
                pin = name.upper()
                if pin in o.PINS or pin in o.OUTS:
                    return getattr(o, pin)
            m = METHODS.get(type(o))
            if m is not None and name in m:
                fn = m[name]
                return lambda *a: fn(o, *a)
            raise PlcFault(f"{type(o).__name__} has no {name}")
        return read

    def _call(self, n):
        if any(isinstance(a, ast.Starred) for a in n.args) or any(k.arg is None for k in n.keywords):
            self.err("* and ** in a call aren't available", n)
        args = [self.expr(a) for a in n.args]
        kws = [(k.arg, self.expr(k.value)) for k in n.keywords]
        ctx = self.ctx
        if isinstance(n.func, ast.Name):
            name = n.func.id
            if name == "print":
                def do_print(L):
                    vals = [a(L) for a in args]
                    for v in vals:
                        if type(v) not in SCALARS:
                            _guard(v)
                    ctx.log(" ".join(str(v) for v in vals))
                return do_print
            if name in ("exec", "eval", "open", "compile", "getattr", "setattr", "globals", "locals", "vars", "dir",
                        "type", "object", "input", "__import__", "breakpoint", "memoryview", "classmethod", "super"):
                self.err(f"{name}() isn't available in a PLC program", n)
        f = self.expr(n.func)

        def call(L):
            target = f(L)
            vals = [a(L) for a in args]
            named = {k: v(L) for k, v in kws}
            return self._invoke(target, vals, named)
        return call

    def _invoke(self, target, vals, named):
        ctx = self.ctx
        if type(target) is PyFunc:
            return self._call_pyfunc(target, vals, named)
        if isinstance(target, Fb):
            if vals:
                raise PlcFault("pass a function block's inputs by name: dwell(IN=x, PT=2000)")
            for k, v in named.items():
                pin = k.upper()
                if pin not in target.PINS:
                    raise PlcFault(f"{type(target).__name__} has no input {k}")
                setattr(target, pin, v)
            target.run(ctx.dt_ms)
            return None
        if isinstance(target, type) and issubclass(target, Fb):
            if vals or named:
                raise PlcFault(f"{target.__name__}() takes no arguments; set the inputs when you call it")
            return target()
        if callable(target):
            ctx.budget -= 1
            return _fit(target(*vals, **named))
        raise PlcFault(f"{type(target).__name__} can't be called")

    def _call_pyfunc(self, fn, vals, named):
        ctx = self.ctx
        ctx.tick()
        if ctx.depth >= MAX_CALL_DEPTH:
            raise PlcFault(f"{fn.name}: calls are nested too deeply")
        frame = {}
        params = fn.params
        if len(vals) > len(params):
            raise PlcFault(f"{fn.name}() takes {len(params)} argument{'s' * (len(params) != 1)}")
        frame.update(zip(params, vals))
        for k, v in named.items():
            if k not in params:
                raise PlcFault(f"{fn.name}() has no argument {k}")
            frame[k] = v
        for p, d in fn.defaults:
            frame.setdefault(p, d)
        for p in params:
            if p not in frame:
                raise PlcFault(f"{fn.name}() is missing argument {p}")
        ctx.depth += 1
        try:
            fn.body(frame)
        finally:
            ctx.depth -= 1
        return frame.get(RET)

    def _listcomp(self, n):
        if len(n.generators) != 1 or n.generators[0].is_async:
            self.err("only a simple list comprehension is available", n)
        g = n.generators[0]
        if not isinstance(g.target, ast.Name):
            self.err("a list comprehension loops over one name", n)
        name = g.target.id
        if self.func is None:
            self.global_names.add(name)
        else:
            self.func.locals.add(name)
        store = self.write_name(g.target)
        it = self.expr(g.iter)
        conds = [self.expr(c) for c in g.ifs]
        elt = self.expr(n.elt)
        ctx = self.ctx

        def run(L):
            out = []
            for x in it(L):
                ctx.tick()
                store(L, x)
                if all(c(L) for c in conds):
                    if len(out) >= MAX_ARRAY:
                        raise PlcFault(f"a list grew past {MAX_ARRAY:,} items")
                    out.append(elt(L))
            return out
        return run

    def _fstring(self, n):
        parts = []
        for v in n.values:
            if isinstance(v, ast.FormattedValue):
                if v.format_spec is not None or v.conversion != -1:
                    self.err("f-strings here can't use format specifications; use round()", n)
                parts.append((True, self.expr(v.value)))
            else:
                parts.append((False, v.value))

        def run(L):
            return _fit("".join(_str(p(L)) if is_expr else p for is_expr, p in parts))
        return run

    # ---- statements
    def block(self, stmts):
        fs = [self.statement(s) for s in stmts]
        if not fs:
            return lambda L: None
        if len(fs) == 1:
            return fs[0]

        def run(L):
            for f in fs:
                r = f(L)
                if r is not None:
                    return r
            return None
        return run

    def statement(self, n):
        t = type(n)
        if t is ast.Expr:
            f = self.expr(n.value)

            def run(L):
                f(L)
            return run
        if t is ast.Assign:
            return self._assign(n)
        if t is ast.AugAssign:
            return self._augassign(n)
        if t is ast.AnnAssign:
            if n.value is None:
                return lambda L: None
            return self._assign(ast.Assign(targets=[n.target], value=n.value, lineno=n.lineno))
        if t is ast.If:
            c, a, b = self.expr(n.test), self.block(n.body), self.block(n.orelse)
            return lambda L: a(L) if c(L) else b(L)
        if t is ast.While:
            return self._while(n)
        if t is ast.For:
            return self._for(n)
        if t is ast.Break:
            return lambda L: BREAK
        if t is ast.Continue:
            return lambda L: CONTINUE
        if t is ast.Pass or t is ast.Global:
            return lambda L: None
        if t is ast.Return:
            if self.func is None:
                self.err("return can only be used in a function", n)
            if n.value is None:
                return lambda L: RETURN
            f = self.expr(n.value)

            def do_return(L):
                L[RET] = f(L)
                return RETURN
            return do_return
        if t is ast.FunctionDef:
            if self.func is not None:
                self.err("a function can't be defined inside a function", n)
            return self._def(n)
        if t is ast.Import:
            if any(a.name != "math" or a.asname for a in n.names):
                self.err("only “import math” is available", n)
            return lambda L: None
        if t is ast.ImportFrom:
            if n.module != "math" or n.level or any(a.asname or a.name == "*" for a in n.names):
                self.err("only “from math import ...” is available", n)
            return self._import_from(n)
        if t is ast.Assert:
            f = self.expr(n.test)

            def run_assert(L):
                if not f(L):
                    raise PlcFault("an assert failed")
            return run_assert
        self.err(FORBIDDEN_HINT.get(t, f"{t.__name__} isn't available in a PLC program"), n)

    def _import_from(self, n):
        pairs = []
        for a in n.names:
            if a.name in _SAFE_MATH:
                pairs.append((a.name, _checked(_SAFE_MATH[a.name])))
            elif a.name in _MathModule.CONSTS:
                pairs.append((a.name, _MathModule.CONSTS[a.name]))
            else:
                self.err(f"math.{a.name} isn't available", n)
        M = self.module

        def run(L):
            for k, v in pairs:
                M[k] = v
        return run

    def _target(self, t):
        if isinstance(t, ast.Name):
            return self.write_name(t)
        if isinstance(t, ast.Subscript):
            base, idx = self.expr(t.value), self._slice(t.slice)

            def write_item(L, v):
                o = base(L)
                i = idx(L)
                if type(o) is dict and i not in o and len(o) >= MAX_ARRAY:
                    raise PlcFault(f"a dictionary grew past {MAX_ARRAY:,} items")
                if type(i) is slice:
                    raise PlcFault("assigning to a slice isn't available")
                o[i] = v
            return write_item
        if isinstance(t, ast.Attribute):
            if t.attr.startswith("_"):
                self.err(f"{t.attr} isn't available", t)
            base = self.expr(t.value)
            pin = t.attr.upper()

            def write_pin(L, v):
                o = base(L)
                if not isinstance(o, Fb) or pin not in o.PINS:
                    raise PlcFault(f"{type(o).__name__} has no input {t.attr}")
                setattr(o, pin, v)
            return write_pin
        if isinstance(t, (ast.Tuple, ast.List)):
            stores = [self._target(e) for e in t.elts]

            def write_many(L, v):
                vals = list(_sized_iter(v))
                if len(vals) != len(stores):
                    raise PlcFault(f"expected {len(stores)} values, got {len(vals)}")
                for s, x in zip(stores, vals):
                    s(L, x)
            return write_many
        self.err("this can't be assigned to", t)

    def _assign(self, n):
        value = self.expr(n.value)
        stores = [self._target(t) for t in n.targets]
        if len(stores) == 1:
            store = stores[0]

            def assign(L):
                store(L, value(L))
            return assign

        def assign_many(L):
            v = value(L)
            for s in stores:
                s(L, v)
        return assign_many

    def _augassign(self, n):
        fn = _BIN.get(type(n.op))
        if fn is None:
            self.err("this operator isn't available", n)
        if isinstance(n.target, ast.Name):
            read = self.read_name(ast.Name(id=n.target.id, lineno=n.lineno))
        else:
            read = self.expr(_load(n.target))
        store = self._target(n.target)
        value = self.expr(n.value)

        def run(L):
            store(L, fn(read(L), value(L)))
        return run

    def _while(self, n):
        c, body = self.expr(n.test), self.block(n.body)
        other = self.block(n.orelse)
        ctx = self.ctx

        def run(L):
            while c(L):
                ctx.tick()
                r = body(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
            return other(L)
        return run

    def _for(self, n):
        it = self.expr(n.iter)
        store = self._target(n.target)
        body = self.block(n.body)
        other = self.block(n.orelse)
        ctx = self.ctx

        def run(L):
            seq = it(L)
            if type(seq) not in (list, tuple, dict, str, range):
                raise PlcFault(f"a for loop can't go over a {type(seq).__name__}")
            for x in (list(seq) if type(seq) is not range else seq):
                ctx.tick()
                store(L, x)
                r = body(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
            return other(L)
        return run

    def _def(self, n):
        a = n.args
        if a.vararg or a.kwarg or a.kwonlyargs or a.posonlyargs:
            self.err("a function here takes plain arguments only", n)
        if n.decorator_list:
            self.err("decorators aren't available", n)
        fn = PyFunc(n.name)
        fn.params = [p.arg for p in a.args]
        defaults = [self.expr(d) for d in a.defaults]
        names = fn.params[len(fn.params) - len(defaults):]
        declared_global = set()
        assigned = set(fn.params)
        for node in _own_nodes(n):
            if isinstance(node, ast.Global):
                declared_global |= set(node.names)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                assigned.add(node.id)
        for g in declared_global:
            self.global_names.add(g)
        # tags and PLC variables are always global, so writing to an output in a function just works
        fn.locals = {x for x in assigned - declared_global if self._io(x) is None}
        self.funcs[n.name] = fn
        self.func = fn
        try:
            fn.body = self.block(n.body)
        finally:
            self.func = None
        M = self.module
        name = n.name

        def define(L):
            fn.defaults = [(p, d(L)) for p, d in zip(names, defaults)]
            M[name] = fn
        return define


def _own_nodes(fn):
    """Walk a function's statements. A nested def is refused later, so it isn't special here."""
    stack = list(fn.body)
    while stack:
        n = stack.pop()
        yield n
        stack.extend(ast.iter_child_nodes(n))


def _load(target):
    """The same target as an expression to read."""
    if isinstance(target, ast.Subscript):
        return ast.Subscript(value=target.value, slice=target.slice, ctx=ast.Load(), lineno=target.lineno)
    if isinstance(target, ast.Attribute):
        return ast.Attribute(value=target.value, attr=target.attr, ctx=ast.Load(), lineno=target.lineno)
    raise CompileError("this can't be assigned to", getattr(target, "lineno", 0))


def _prescan_names(tree, comp):
    """Names assigned at module level and functions defined, so that use before definition inside a function
    compiles, and is reported when it really happens."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            comp.funcs[node.name] = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            comp.global_names |= set(node.names)
    stack = [n for n in tree.body if not isinstance(n, ast.FunctionDef)]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            comp.global_names.add(n.id)
        stack.extend(ast.iter_child_nodes(n))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if isinstance(node, ast.ImportFrom):
                    comp.global_names.add(a.name)


# Python's own parser builds a tree as deep as the source says, on the C stack, and in some versions nothing stops it:
# `x = 1 + 1 + 1 ...` fifty thousand terms long takes the whole program down, and no `except` can catch that. So a
# source that would build a very deep tree is turned down before it reaches the parser.
MAX_CHAIN = 1000        # operators in a row in one expression; the parser is safe to well over ten times this
MAX_ELIF = 1000
_CHAINS = frozenset(("not", "and", "or", "in", "is", "if", "else", "lambda", "await"))
_OPERATORS = r"\*\*|//|<<|>>|==|!=|<=|>=|[-+*/%@&|^~<>.]"
_OPERATOR = re.compile(_OPERATORS)
_SCAN = re.compile(r"""
    (?P<comment>\#[^\n]*)
  | (?P<string>(?P<prefix>[A-Za-z]{0,2})(?:\'\'\'(?:[^\\]|\\.)*?\'\'\'|\"\"\"(?:[^\\]|\\.)*?\"\"\"
                                         |'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"))
  | (?P<number>\.?\d[\w.]*)
  | (?P<word>[^\W\d]\w*)
  | (?P<open>[(\[{])
  | (?P<close>[)\]}])
  | (?P<comma>,)
  | (?P<joined>\\\r?\n)
  | (?P<end>[\n;])
  | (?P<op>""" + _OPERATORS + r""")
""", re.X | re.S)


def check_depth(src: str, pou: str = "") -> None:
    """Raises CompileError if parsing this source could overflow the stack. Costs nothing a real program would notice,
    and turns down nothing a real program would contain: a table of ten thousand numbers is not deep."""
    outer = []
    count = peak = elifs = 0
    for m in _SCAN.finditer(src):
        kind = m.lastgroup
        if kind == "op":
            count += 1
        elif kind == "word":
            word = m.group()
            if word in _CHAINS:
                count += 1
            elif word == "elif":
                elifs += 1
                if elifs > MAX_ELIF:
                    raise CompileError(f"more than {MAX_ELIF} elif branches: use a table or a function instead",
                                       src.count("\n", 0, m.start()) + 1, pou)
        elif kind == "string":
            if "f" in m.group("prefix").lower():
                count += len(_OPERATOR.findall(m.group()))
        elif kind == "open":
            if len(outer) >= MAX_NEST:
                raise CompileError("brackets are nested too deeply", src.count("\n", 0, m.start()) + 1, pou)
            outer.append((count, peak))
            count = peak = 0
        elif kind == "close":
            if outer:
                inner = max(peak, count) + 1
                count, peak = outer.pop()
                count += inner
        elif kind == "comma":
            peak = max(peak, count)
            count = 0
        elif kind == "end" and not outer:
            count = peak = 0
        if count > MAX_CHAIN:
            raise CompileError(f"this expression is too long: more than {MAX_CHAIN} operators one after another",
                               src.count("\n", 0, m.start()) + 1, pou)


def compile_unit(src: str, ctx, program, pou: str):
    """(module variables, run once at start, setup or None, run every scan)."""
    check_depth(src, pou)
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise CompileError(e.msg or "this isn't valid Python", e.lineno or 0, pou) from None
    except (ValueError, RecursionError, MemoryError) as e:
        raise CompileError(f"this program can't be read: {e}", 0, pou) from None
    comp = Compiler(ctx, program, pou)
    _prescan_names(tree, comp)
    has_loop = any(isinstance(n, ast.FunctionDef) and n.name == "loop" for n in tree.body)
    module_body = comp.block(tree.body)
    M = comp.module
    if not has_loop:
        return M, None, None, module_body

    def call_named(name):
        def run(L):
            fn = M.get(name)
            if type(fn) is PyFunc:
                comp._call_pyfunc(fn, [], {})
        return run
    return M, module_body, call_named("setup"), call_named("loop")
