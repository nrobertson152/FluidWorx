"""Structured Text (IEC 61131-3): lexer, parser and a compiler to closures.

Ladder, function block diagrams and sequential function charts use the same expression compiler, so an operand
in any of them can be anything ST allows: a tag, ``T1.Q``, or ``Pressure > 120.0 AND NOT Stop``.
"""
from __future__ import annotations

import operator
import re

from .core import (FB_TYPES, FUNCTIONS, MAX_ARRAY, MAX_CALL_DEPTH, MAX_NEST, ArrayType, CompileError, Fb, PlcFault, Scope,
                   Var, coercer, conversion, int_div, int_mod, new_value, parse_time)
from .core import ELEMENTARY, _ipow

BREAK, CONTINUE, RETURN = 1, 2, 3

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<time>(?:T|TIME|LT|LTIME)\#[-+]?[0-9a-zA-Z_.]+)
  | (?P<based>(?:2|8|16)\#[0-9a-fA-F_]+)
  | (?P<typed>[A-Za-z_]+\#[-+0-9a-zA-Z_.]+)
  | (?P<real>\d[\d_]*\.\d[\d_]*(?:[eE][-+]?\d+)?|\d[\d_]*[eE][-+]?\d+)
  | (?P<int>\d[\d_]*)
  | (?P<addr>%[IQM][XBWDL]?\d+(?:\.\d+)?)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<str>'(?:[^'$\n]|\$.)*')
  | (?P<op>:=|=>|<>|<=|>=|\*\*|\.\.|[-+*/=<>()\[\],;:.&])
""", re.X)

KEYWORDS = {
    "IF", "THEN", "ELSIF", "ELSE", "END_IF", "CASE", "OF", "END_CASE", "FOR", "TO", "BY", "DO", "END_FOR", "WHILE",
    "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT", "EXIT", "CONTINUE", "RETURN", "VAR", "VAR_INPUT", "VAR_OUTPUT",
    "VAR_IN_OUT", "VAR_GLOBAL", "VAR_TEMP", "END_VAR", "CONSTANT", "RETAIN", "AT", "ARRAY", "PROGRAM", "END_PROGRAM",
    "FUNCTION", "END_FUNCTION", "FUNCTION_BLOCK", "END_FUNCTION_BLOCK", "AND", "OR", "XOR", "NOT", "MOD", "TRUE",
    "FALSE",
}


class Tok:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind, self.value, self.line = kind, value, line

    def __repr__(self):
        return f"{self.kind}:{self.value}"


def tokenize(src: str) -> list:
    out, i, line, n = [], 0, 1, len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if two in ("(*", "/*"):
            depth, j = 1, i + 2
            while j < n and depth:
                pair = src[j:j + 2]
                if pair == two:
                    depth, j = depth + 1, j + 2
                elif pair == ("*)" if two == "(*" else "*/"):
                    depth, j = depth - 1, j + 2
                else:
                    line += src[j] == "\n"
                    j += 1
            if depth:
                raise CompileError("this comment is never closed", line)
            i = j
            continue
        m = _TOKEN.match(src, i)
        if not m:
            raise CompileError(f"unexpected character {c!r}", line)
        kind, text = m.lastgroup, m.group()
        i = m.end()
        if kind == "ws":
            line += text.count("\n")
            continue
        if kind == "id" and text.upper() in KEYWORDS:
            out.append(Tok(text.upper(), text, line))
        else:
            out.append(Tok(kind if kind != "op" else text, text, line))
    out.append(Tok("eof", "", line))
    return out


_ESC = {"$$": "$", "$'": "'", "$L": "\n", "$N": "\n", "$R": "\r", "$T": "\t", "$P": "\f"}


def _unquote(text):
    return re.sub(r"\$.", lambda m: _ESC.get(m.group().upper(), m.group()[1]), text[1:-1])


# ---------------------------------------------------------------- parser (AST = tuples; the last item is the line)
class Parser:
    def __init__(self, tokens):
        self.t, self.i, self.depth = tokens, 0, 0

    @property
    def cur(self):
        return self.t[self.i]

    def at(self, *kinds):
        return self.cur.kind in kinds

    def take(self, *kinds):
        if self.cur.kind in kinds:
            self.i += 1
            return self.t[self.i - 1]
        return None

    def need(self, kind, what=None):
        tok = self.take(kind)
        if tok is None:
            got = "the end of the program" if self.cur.kind == "eof" else f"“{self.cur.value}”"
            raise CompileError(f"expected {what or kind} but found {got}", self.cur.line)
        return tok

    def _enter(self):
        self.depth += 1
        if self.depth > MAX_NEST:
            raise CompileError("too deeply nested", self.cur.line)

    # ---- program structure
    def unit(self):
        """(decls, functions, statements). A POU may be bare statements, or wrapped in PROGRAM ... END_PROGRAM."""
        decls, funcs, body = [], [], []
        while not self.at("eof"):
            if self.at("VAR", "VAR_GLOBAL", "VAR_TEMP", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"):
                decls += self.var_block()
            elif self.at("FUNCTION", "FUNCTION_BLOCK"):
                funcs.append(self.function())
            elif self.at("PROGRAM"):
                self.i += 1
                self.need("id", "the program's name")
                while self.at("VAR", "VAR_GLOBAL", "VAR_TEMP", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"):
                    decls += self.var_block()
                body += self.statements("END_PROGRAM")
                self.need("END_PROGRAM")
                self.take(";")
            else:
                body += self.statements("eof", "VAR", "VAR_GLOBAL", "VAR_TEMP", "FUNCTION", "FUNCTION_BLOCK", "PROGRAM")
        return decls, funcs, body

    def function(self):
        is_fb = self.take("FUNCTION_BLOCK") is not None
        if not is_fb:
            self.need("FUNCTION")
        line = self.cur.line
        name = self.need("id", "a name").value
        ret = None
        if not is_fb:
            self.need(":", "“:” and the return type")
            ret = self.type_spec()
        decls = []
        while self.at("VAR", "VAR_TEMP", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"):
            decls += self.var_block()
        end = "END_FUNCTION_BLOCK" if is_fb else "END_FUNCTION"
        body = self.statements(end)
        self.need(end)
        self.take(";")
        return {"fb": is_fb, "name": name, "ret": ret, "decls": decls, "body": body, "line": line}

    def var_block(self):
        section = self.cur.kind
        self.i += 1
        const = False
        while self.at("CONSTANT", "RETAIN"):
            const = const or self.cur.kind == "CONSTANT"
            self.i += 1
        out = []
        while not self.at("END_VAR"):
            line = self.cur.line
            names = [self.need("id", "a variable name").value]
            while self.take(","):
                names.append(self.need("id", "a variable name").value)
            addr = None
            if self.take("AT"):
                addr = self.need("addr", "an address such as %IX0.0").value
            self.need(":", "“:” and a type")
            typ = self.type_spec()
            init = None
            if self.take(":="):
                init = self.array_init() if self.at("[") else self.expr()
            self.need(";", "“;”")
            for n in names:
                out.append({"section": section, "name": n, "type": typ, "init": init, "addr": addr, "const": const,
                            "line": line})
        self.need("END_VAR")
        return out

    def array_init(self):
        self.need("[")
        items = [self.expr()]
        while self.take(","):
            items.append(self.expr())
        self.need("]", "“]”")
        return ("list", items, self.cur.line)

    def type_spec(self):
        if self.take("ARRAY"):
            self.need("[", "“[”")
            ranges = []
            while True:
                lo = self._const_int()
                self.need("..", "“..”")
                hi = self._const_int()
                if hi < lo:
                    raise CompileError("an array's upper bound is below its lower bound", self.cur.line)
                ranges.append((lo, hi))
                if not self.take(","):
                    break
            self.need("]", "“]”")
            self.need("OF", "OF")
            elem = self.type_spec()
            for lo, hi in reversed(ranges):
                elem = ArrayType(lo, hi, elem)
            return elem
        tok = self.need("id", "a type")
        if self.take("("):               # STRING(80): the length isn't enforced
            self.need("int")
            self.need(")", "“)”")
        return tok.value.upper()

    def _const_int(self):
        neg = self.take("-") is not None
        v = _int_value(self.need("int", "a whole number").value)
        return -v if neg else v

    # ---- statements
    def statements(self, *until):
        out = []
        while not self.at(*until, "eof"):
            if self.take(";"):
                continue
            out.append(self.statement())
        return out

    def statement(self):
        self._enter()
        try:
            line = self.cur.line
            k = self.cur.kind
            if k == "IF":
                return self._if(line)
            if k == "CASE":
                return self._case(line)
            if k == "FOR":
                return self._for(line)
            if k == "WHILE":
                self.i += 1
                cond = self.expr()
                self.need("DO", "DO")
                body = self.statements("END_WHILE")
                self.need("END_WHILE", "END_WHILE")
                self.take(";")
                return ("while", cond, body, line)
            if k == "REPEAT":
                self.i += 1
                body = self.statements("UNTIL")
                self.need("UNTIL", "UNTIL")
                cond = self.expr()
                self.need("END_REPEAT", "END_REPEAT")
                self.take(";")
                return ("repeat", body, cond, line)
            if k in ("EXIT", "CONTINUE", "RETURN"):
                self.i += 1
                self.take(";")
                return (k.lower(), line)
            target = self.postfix()
            if self.take(":="):
                value = self.expr()
                self.need(";", "“;”")
                return ("assign", target, value, line)
            self.need(";", "“:=” or “;”")
            if target[0] != "call":
                raise CompileError("a statement must assign a value or call something", line)
            return ("do", target, line)
        finally:
            self.depth -= 1

    def _if(self, line):
        self.need("IF")
        arms = []
        cond = self.expr()
        self.need("THEN", "THEN")
        arms.append((cond, self.statements("ELSIF", "ELSE", "END_IF")))
        while self.take("ELSIF"):
            cond = self.expr()
            self.need("THEN", "THEN")
            arms.append((cond, self.statements("ELSIF", "ELSE", "END_IF")))
        other = self.statements("END_IF") if self.take("ELSE") else []
        self.need("END_IF", "END_IF")
        self.take(";")
        return ("if", arms, other, line)

    def _case(self, line):
        self.need("CASE")
        sel = self.expr()
        self.need("OF", "OF")
        arms, other = [], []
        while not self.at("END_CASE", "ELSE", "eof"):
            labels = []
            while True:
                a = self.expr()
                b = self.expr() if self.take("..") else None
                labels.append((a, b))
                if not self.take(","):
                    break
            self.need(":", "“:”")
            arms.append((labels, self._case_body()))
        if self.take("ELSE"):
            other = self.statements("END_CASE")
        self.need("END_CASE", "END_CASE")
        self.take(";")
        return ("case", sel, arms, other, line)

    def _case_body(self):
        """Statements up to the next label, which is told apart by the ":" or ".." or "," that follows it."""
        out = []
        while not self.at("END_CASE", "ELSE", "eof"):
            if self.take(";"):
                continue
            if self._looks_like_label():
                break
            out.append(self.statement())
        return out

    def _looks_like_label(self):
        i = self.i
        tok = self.t[i]
        if tok.kind == "-":
            i += 1
            tok = self.t[i]
        if tok.kind in ("int", "based", "typed", "TRUE", "FALSE", "id"):
            return self.t[i + 1].kind in (":", "..", ",")
        return False

    def _for(self, line):
        self.need("FOR")
        name = self.need("id", "the loop variable").value
        self.need(":=", "“:=”")
        start = self.expr()
        self.need("TO", "TO")
        stop = self.expr()
        step = self.expr() if self.take("BY") else None
        self.need("DO", "DO")
        body = self.statements("END_FOR")
        self.need("END_FOR", "END_FOR")
        self.take(";")
        return ("for", ("name", name, line), start, stop, step, body, line)

    # ---- expressions
    def expr(self):
        self._enter()
        try:
            return self._binary(0)
        finally:
            self.depth -= 1

    _LEVELS = (("OR",), ("XOR",), ("AND", "&"), ("=", "<>"), ("<", ">", "<=", ">="), ("+", "-"), ("*", "/", "MOD"))

    def _binary(self, level):
        if level == len(self._LEVELS):
            return self._power()
        left = self._binary(level + 1)
        while self.cur.kind in self._LEVELS[level]:
            tok = self.cur
            self.i += 1
            left = ("bin", "AND" if tok.kind == "&" else tok.kind, left, self._binary(level + 1), tok.line)
        return left

    def _power(self):
        left = self._unary()
        if self.at("**"):
            line = self.cur.line
            self.i += 1
            return ("bin", "**", left, self._power(), line)
        return left

    def _unary(self):
        tok = self.take("NOT", "-", "+")
        if tok is None:
            return self.postfix()
        self._enter()
        try:
            inner = self._unary()
        finally:
            self.depth -= 1
        return inner if tok.kind == "+" else ("un", tok.kind, inner, tok.line)

    def postfix(self):
        node = self.primary()
        while True:
            line = self.cur.line
            if self.take("["):
                idx = [self.expr()]
                while self.take(","):
                    idx.append(self.expr())
                self.need("]", "“]”")
                node = ("index", node, idx, line)
            elif self.take("."):
                node = ("member", node, self.need("id", "a member name").value, line)
            elif self.at("(") and node[0] in ("name", "member"):
                self.i += 1
                node = ("call", node, self._args(), line)
            else:
                return node

    def _args(self):
        args = []
        if self.take(")"):
            return args
        while True:
            if self.at("id") and self.t[self.i + 1].kind == ":=":
                name = self.take("id").value
                self.i += 1
                args.append(("in", name, self.expr()))
            elif self.at("id") and self.t[self.i + 1].kind == "=>":
                name = self.take("id").value
                self.i += 1
                args.append(("out", name, self.postfix()))
            else:
                args.append(("pos", None, self.expr()))
            if not self.take(","):
                break
        self.need(")", "“)”")
        return args

    def primary(self):
        tok = self.cur
        k = tok.kind
        line = tok.line
        if k == "(":
            self.i += 1
            inner = self.expr()
            self.need(")", "“)”")
            return inner
        self.i += 1
        if k == "TRUE":
            return ("lit", True, line)
        if k == "FALSE":
            return ("lit", False, line)
        if k == "int":
            return ("lit", _int_value(tok.value), line)
        if k == "real":
            return ("lit", float(tok.value.replace("_", "")), line)
        if k == "based":
            return ("lit", _based_value(tok.value), line)
        if k == "time":
            try:
                return ("lit", parse_time(tok.value), line)
            except (ValueError, OverflowError) as e:
                raise CompileError(str(e), line) from None
        if k == "typed":
            return ("lit", _typed_value(tok.value, line), line)
        if k == "str":
            return ("lit", _unquote(tok.value), line)
        if k == "addr":
            return ("addr", tok.value, line)
        if k == "id":
            return ("name", tok.value, line)
        self.i -= 1
        got = "the end of the program" if k == "eof" else f"“{tok.value}”"
        raise CompileError(f"expected a value but found {got}", line)


def _int_value(text):
    digits = text.replace("_", "")
    if len(digits) > 20:
        raise CompileError("this number is too long")
    return int(digits)


def _based_value(text):
    base, digits = text.split("#", 1)
    digits = digits.replace("_", "")
    if len(digits) > 64:
        raise CompileError("this number is too long")
    try:
        return int(digits, int(base))
    except ValueError:
        raise CompileError(f"bad number {text}") from None


def _typed_value(text, line):
    type_name, value = text.split("#", 1)
    type_name = type_name.upper()
    if type_name not in ELEMENTARY:
        raise CompileError(f"unknown type {type_name}", line)
    try:
        if value.upper() in ("TRUE", "FALSE"):
            return coercer(type_name)(value.upper() == "TRUE")
        if value[:3] in ("16#", "2#", "8#"):
            return coercer(type_name)(_based_value(value))
        return coercer(type_name)(float(value.replace("_", "")) if "." in value or "e" in value.lower()
                                  else int(value.replace("_", "")))
    except ValueError:
        raise CompileError(f"bad value {text}", line) from None


def parse_program(src: str):
    return Parser(tokenize(src)).unit()


def parse_expression(src: str):
    """AST of one expression; CompileError if there is anything after it."""
    p = Parser(tokenize(src))
    e = p.expr()
    if not p.at("eof"):
        raise CompileError(f"unexpected “{p.cur.value}” after the expression", p.cur.line)
    return e


def parse_statements(src: str):
    p = Parser(tokenize(src))
    return p.statements("eof")


# ---------------------------------------------------------------- user-defined functions and blocks
class UserFbType:
    """A FUNCTION_BLOCK declared in ST. An instance is a frame (a dict) with its variables in it."""

    def __init__(self, name):
        self.name = name
        self.vars: dict = {}            # upper name -> Var
        self.body = None
        self.inits = []

    def new(self):
        return UserFb(self)


class UserFb:
    __slots__ = ("type", "frame")

    def __init__(self, ftype):
        self.type = ftype
        self.frame = {}
        for key, make in ftype.inits:
            self.frame[key] = make(self.frame)


class UserFunc:
    def __init__(self, name, ret):
        self.name, self.ret = name, ret
        self.inputs = []                # Vars, in order
        self.body = None
        self.inits = []


# ---------------------------------------------------------------- compiler
_CMP = {"=": operator.eq, "<>": operator.ne, "<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge}


class Compiler:
    """Turns ST into closures taking one argument, the frame of the running POU. Globals come from ctx.G."""

    def __init__(self, ctx, program, scope: Scope, pou=""):
        self.ctx, self.program, self.scope, self.pou = ctx, program, scope, pou
        self.G = ctx.G
        self._uid = 0

    def err(self, msg, line=0):
        raise CompileError(msg, line, self.pou)

    # ---- names
    def _var(self, name, line):
        v = self.scope.find(name)
        if v is None:
            self.err(f"“{name}” is not declared. Add it to the variables, or name it in the I/O table.", line)
        return v

    def _resolve_addr(self, text, line):
        v = self.program.address(text)
        if v is None:
            self.err(f"this PLC has no address {text}", line)
        return v

    def read_var(self, v):
        key = v.key
        if v.local:
            return lambda L: L[key]
        G = self.G
        return lambda L: G[key]

    # ---- expressions
    def expr(self, node):
        k = node[0]
        if k == "lit":
            value = node[1]
            return lambda L: value
        if k == "name":
            return self._read_name(node)
        if k == "addr":
            return self.read_var(self._resolve_addr(node[1], node[2]))
        if k == "bin":
            return self._binary(node)
        if k == "un":
            return self._unary(node)
        if k == "index":
            return self._read_index(node)
        if k == "member":
            return self._read_member(node)
        if k == "call":
            return self._call_value(node)
        self.err("this can't be used as a value", node[-1])

    def _read_name(self, node):
        name, line = node[1], node[2]
        v = self.scope.find(name)
        if v is None:
            if name.upper() in FUNCTIONS or name.upper() in FB_TYPES:
                self.err(f"{name} needs its arguments in brackets", line)
            self._var(name, line)
        if v.kind == "step":
            step = self.read_var(v)
            return lambda L: step(L).active
        if not isinstance(v.type, (str, ArrayType)):
            self.err(f"{name} is a function block: read one of its outputs, such as {name}.Q", line)
        return self.read_var(v)

    def _binary(self, node):
        _, op, ln, rn, line = node
        a, b = self.expr(ln), self.expr(rn)
        if op == "AND":
            return lambda L: a(L) & b(L)
        if op == "OR":
            return lambda L: a(L) | b(L)
        if op == "XOR":
            return lambda L: a(L) ^ b(L)
        if op == "+":
            return lambda L: a(L) + b(L)
        if op == "-":
            return lambda L: a(L) - b(L)
        if op == "*":
            return lambda L: a(L) * b(L)
        if op == "/":
            return lambda L: int_div(a(L), b(L))
        if op == "MOD":
            return lambda L: int_mod(a(L), b(L))
        if op == "**":
            return lambda L: _ipow(a(L), b(L))
        f = _CMP[op]
        return lambda L: f(a(L), b(L))

    def _unary(self, node):
        _, op, inner, _line = node
        a = self.expr(inner)
        if op == "-":
            return lambda L: -a(L)

        def invert(L):
            v = a(L)
            return (not v) if type(v) is bool else ~v
        return invert

    def _index_key(self, node):
        """Closure giving the Python list and index for an array element. Returns (locate, element type)."""
        _, base, idx, line = node
        container, typ = self._container(base, line)
        locate = container
        for ix in idx:
            if not isinstance(typ, ArrayType):
                self.err("too many indexes for this array", line)
            ix_f = self.expr(ix)
            lo, hi = typ.lo, typ.hi
            locate = _element(locate, ix_f, lo, hi)
            typ = typ.elem
        return locate, typ

    def _container(self, base, line):
        if base[0] == "name":
            v = self._var(base[1], line)
            if not isinstance(v.type, ArrayType):
                self.err(f"{base[1]} is not an array", line)
            return self.read_var(v), v.type
        if base[0] == "index":
            locate, typ = self._index_key(base)
            if not isinstance(typ, ArrayType):
                self.err("too many indexes for this array", line)
            return locate, typ
        self.err("only arrays can be indexed", line)

    def _read_index(self, node):
        locate, typ = self._index_key(node)
        if isinstance(typ, ArrayType):
            self.err("this array needs more indexes", node[-1])
        return locate

    def _read_member(self, node):
        _, base, member, line = node
        obj, ftype = self._fb_object(base, line)
        if isinstance(ftype, UserFbType):
            v = ftype.vars.get(member.upper())
            if v is None:
                self.err(f"{ftype.name} has no member {member}", line)
            key = v.key
            return lambda L: obj(L).frame[key]
        if ftype == "step":
            attr = member.upper()
            if attr not in ("X", "T"):
                self.err("a step has .X (active) and .T (time active)", line)
            step = obj
            return (lambda L: step(L).active) if attr == "X" else (lambda L: step(L).elapsed)
        pin = _pin(ftype, member)
        if pin is None:
            self.err(f"{ftype.__name__} has no pin {member}; it has "
                     f"{', '.join(list(ftype.PINS) + list(ftype.OUTS))}", line)
        return lambda L: getattr(obj(L), pin)

    def _fb_object(self, base, line):
        """(closure giving the instance, its type) for an expression naming a function block or a step."""
        if base[0] == "name":
            v = self._var(base[1], line)
            if v.kind == "step":
                return self.read_var(v), "step"
            if isinstance(v.type, (str, ArrayType)):
                self.err(f"{base[1]} is not a function block", line)
            return self.read_var(v), v.type
        if base[0] == "index":
            locate, typ = self._index_key(base)
            if isinstance(typ, (str, ArrayType)):
                self.err("this is not a function block", line)
            return locate, typ
        self.err("this is not a function block", line)

    def _call_value(self, node):
        _, target, args, line = node
        if target[0] == "name":
            v = self.scope.find(target[1])
            if v is None:
                return self._function_call(target[1], args, line)
            if isinstance(v.type, (str, ArrayType)):
                self.err(f"{target[1]} is not a function or a function block", line)
        self.err("a function block call gives no value; call it, then read its outputs", line)

    def _function_call(self, name, args, line):
        upper = name.upper()
        user = self.program.st_functions.get(upper)
        if user is not None:
            return self._user_function_call(user, args, line)
        fn = None
        low = high = 1
        if upper in FUNCTIONS:
            fn, low, high = FUNCTIONS[upper]
        else:
            fn = conversion(upper)
        if fn is None:
            self.err(f"there is no function called {name}", line)
        if any(kind != "pos" for kind, _n, _e in args):
            self.err(f"{name} takes plain arguments, not named ones", line)
        if not low <= len(args) <= high:
            want = str(low) if low == high else f"{low} to {high}"
            self.err(f"{name} takes {want} argument{'s' if high != 1 else ''}", line)
        fs = [self.expr(e) for _k, _n, e in args]
        if len(fs) == 1:
            a = fs[0]
            return lambda L: fn(a(L))
        if len(fs) == 2:
            a, b = fs
            return lambda L: fn(a(L), b(L))
        return lambda L: fn(*[f(L) for f in fs])

    def _user_function_call(self, fn, args, line):
        values = []
        names = {v.name.upper(): v for v in fn.inputs}
        by_pos = list(fn.inputs)
        for i, (kind, name, e) in enumerate(args):
            if kind == "in":
                v = names.get(name.upper())
                if v is None:
                    self.err(f"{fn.name} has no input {name}", line)
            elif kind == "pos":
                if i >= len(by_pos):
                    self.err(f"too many arguments for {fn.name}", line)
                v = by_pos[i]
            else:
                self.err("a function has no output arguments", line)
            values.append((v.key, coercer(v.type) if isinstance(v.type, str) else (lambda x: x), self.expr(e)))
        ctx = self.ctx

        def call(L):
            ctx.tick()
            if ctx.depth >= MAX_CALL_DEPTH:
                raise PlcFault(f"{fn.name}: calls are nested too deeply")
            frame = {}
            for key, make in fn.inits:
                frame[key] = make(frame)
            for key, conv, f in values:
                frame[key] = conv(f(L))
            ctx.depth += 1
            try:
                fn.body(frame)
            finally:
                ctx.depth -= 1
            return frame.get("$ret")
        return call

    # ---- writing
    def writer(self, node, line=0):
        """Closure taking (frame, value) that stores into the place `node` names, fitted to its type."""
        k = node[0]
        if k == "addr":
            return self._write_var(self._resolve_addr(node[1], node[2]), node[2])
        if k == "name":
            return self._write_var(self._var(node[1], node[2]), node[2], node[1])
        if k == "index":
            return self._write_index(node)
        if k == "member":
            return self._write_member(node)
        self.err("this can't be assigned to", line or node[-1])

    def _write_var(self, v, line, name=""):
        if not v.writable:
            shown = name or v.name
            what = "an input" if v.kind == "input" else "read-only"
            self.err(f"{shown} is {what}, so a program can't write to it", line)
        if not isinstance(v.type, str):
            self.err(f"{v.name} can't be assigned as a whole", line)
        conv = coercer(v.type)
        key = v.key
        if v.local:
            def store_local(L, value):
                L[key] = conv(value)
            return store_local
        G = self.G

        def store_global(L, value):
            G[key] = conv(value)
        return store_global

    def _write_index(self, node):
        _, base, idx, line = node
        container, typ = self._container(base, line)
        locate = container
        for ix in idx[:-1]:
            if not isinstance(typ, ArrayType):
                self.err("too many indexes for this array", line)
            locate = _element(locate, self.expr(ix), typ.lo, typ.hi)
            typ = typ.elem
        if not isinstance(typ, ArrayType):
            self.err("too many indexes for this array", line)
        lo, hi = typ.lo, typ.hi
        if not isinstance(typ.elem, str):
            self.err("this array needs more indexes", line)
        conv = coercer(typ.elem)
        ix_f = self.expr(idx[-1])

        def store(L, value):
            i = int(ix_f(L))
            if not lo <= i <= hi:
                raise PlcFault(f"array index {i} is outside {lo}..{hi}")
            locate(L)[i - lo] = conv(value)
        return store

    def _write_member(self, node):
        _, base, member, line = node
        obj, ftype = self._fb_object(base, line)
        if ftype == "step":
            self.err("a step's .X and .T are read-only", line)
        if isinstance(ftype, UserFbType):
            v = ftype.vars.get(member.upper())
            if v is None:
                self.err(f"{ftype.name} has no member {member}", line)
            conv = coercer(v.type) if isinstance(v.type, str) else (lambda x: x)
            key = v.key

            def store_user(L, value):
                obj(L).frame[key] = conv(value)
            return store_user
        pin = _pin(ftype, member)
        if pin is None or pin in ftype.OUTS:
            self.err(f"{member} is not an input of {ftype.__name__}", line)

        def store_pin(L, value):
            setattr(obj(L), pin, value)
        return store_pin

    # ---- statements
    def block(self, nodes):
        fs = [self.statement(n) for n in nodes]
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
        k = n[0]
        if k == "assign":
            store = self.writer(n[1], n[3])
            value = self.expr(n[2])

            def assign(L):
                store(L, value(L))
            return assign
        if k == "do":
            return self._call_statement(n[1], n[2])
        if k == "if":
            return self._if(n)
        if k == "case":
            return self._case(n)
        if k == "for":
            return self._for(n)
        if k == "while":
            return self._while(n)
        if k == "repeat":
            return self._repeat(n)
        if k == "exit":
            return lambda L: BREAK
        if k == "continue":
            return lambda L: CONTINUE
        if k == "return":
            return lambda L: RETURN
        self.err("this can't be run as a statement", n[-1])

    def _if(self, n):
        arms = [(self.expr(c), self.block(b)) for c, b in n[1]]
        other = self.block(n[2])
        if len(arms) == 1:
            cond, body = arms[0]

            def run_one(L):
                return body(L) if cond(L) else other(L)
            return run_one

        def run(L):
            for cond, body in arms:
                if cond(L):
                    return body(L)
            return other(L)
        return run

    def _case(self, n):
        sel = self.expr(n[1])
        arms = []
        for labels, body in n[2]:
            ranges = [(self.expr(a), self.expr(b) if b is not None else None) for a, b in labels]
            arms.append((ranges, self.block(body)))
        other = self.block(n[3])

        def run(L):
            v = sel(L)
            for ranges, body in arms:
                for a, b in ranges:
                    if (a(L) == v) if b is None else (a(L) <= v <= b(L)):
                        return body(L)
            return other(L)
        return run

    def _for(self, n):
        _, var, start, stop, step, body, line = n
        v = self._var(var[1], line)
        store = self._write_var(v, line, var[1])
        read = self.read_var(v)
        a, b = self.expr(start), self.expr(stop)
        s = self.expr(step) if step is not None else (lambda L: 1)
        run_body = self.block(body)
        ctx = self.ctx

        def run(L):
            inc = s(L)
            if inc == 0:
                raise PlcFault("a FOR loop's step can't be zero")
            store(L, a(L))
            end = b(L)
            while (read(L) <= end) if inc > 0 else (read(L) >= end):
                ctx.tick()
                r = run_body(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
                store(L, read(L) + inc)
            return None
        return run

    def _while(self, n):
        cond, body = self.expr(n[1]), self.block(n[2])
        ctx = self.ctx

        def run(L):
            while cond(L):
                ctx.tick()
                r = body(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
            return None
        return run

    def _repeat(self, n):
        body, cond = self.block(n[1]), self.expr(n[2])
        ctx = self.ctx

        def run(L):
            while True:
                ctx.tick()
                r = body(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
                if cond(L):
                    return None
        return run

    def _call_statement(self, node, line):
        _, target, args, _ = node
        if target[0] == "name" and self.scope.find(target[1]) is None:
            f = self._function_call(target[1], args, line)

            def call_function(L):
                f(L)
            return call_function
        obj, ftype = self._fb_object(target, line)
        if ftype == "step":
            self.err("a step can't be called", line)
        return self.fb_call(obj, ftype, args, line)

    def fb_call(self, obj, ftype, args, line):
        ctx = self.ctx
        if isinstance(ftype, UserFbType):
            return self._user_fb_call(obj, ftype, args, line)
        inputs, outputs = [], []
        names = list(ftype.PINS)
        for i, (kind, name, e) in enumerate(args):
            if kind == "pos":
                if i >= len(names):
                    self.err(f"too many inputs for {ftype.__name__}", line)
                name = names[i]
                kind = "in"
            pin = _pin(ftype, name)
            if pin is None:
                self.err(f"{ftype.__name__} has no pin {name}; it has "
                         f"{', '.join(list(ftype.PINS) + list(ftype.OUTS))}", line)
            if kind == "in":
                if pin not in ftype.PINS:
                    self.err(f"{pin} is an output of {ftype.__name__}; use {pin} => variable", line)
                inputs.append((pin, self.expr(e)))
            else:
                if pin not in ftype.OUTS:
                    self.err(f"{pin} is an input of {ftype.__name__}; use {pin} := value", line)
                outputs.append((pin, self.writer(e, line)))

        def call(L):
            o = obj(L)
            for pin, f in inputs:
                setattr(o, pin, f(L))
            o.run(ctx.dt_ms)
            for pin, store in outputs:
                store(L, getattr(o, pin))
        return call

    def _user_fb_call(self, obj, ftype, args, line):
        ctx = self.ctx
        inputs, outputs = [], []
        order = [v for v in ftype.vars.values() if v.kind == "fb_in"]
        for i, (kind, name, e) in enumerate(args):
            if kind == "pos":
                if i >= len(order):
                    self.err(f"too many inputs for {ftype.name}", line)
                v = order[i]
                kind = "in"
            else:
                v = ftype.vars.get(name.upper())
                if v is None:
                    self.err(f"{ftype.name} has no member {name}", line)
            conv = coercer(v.type) if isinstance(v.type, str) else (lambda x: x)
            if kind == "in":
                inputs.append((v.key, conv, self.expr(e)))
            else:
                outputs.append((v.key, self.writer(e, line)))

        def call(L):
            ctx.tick()
            if ctx.depth >= MAX_CALL_DEPTH:
                raise PlcFault(f"{ftype.name}: calls are nested too deeply")
            o = obj(L)
            frame = o.frame
            for key, conv, f in inputs:
                frame[key] = conv(f(L))
            ctx.depth += 1
            try:
                ftype.body(frame)
            finally:
                ctx.depth -= 1
            for key, store in outputs:
                store(L, frame[key])
        return call

    # ---- declarations
    def resolve_type(self, t, line):
        if isinstance(t, ArrayType):
            elem = self.resolve_type(t.elem, line)
            at = ArrayType(t.lo, t.hi, elem)
            if at.total() > MAX_ARRAY:
                self.err(f"this array is too large (the limit is {MAX_ARRAY:,} elements)", line)
            return at
        if t in ELEMENTARY:
            return t
        if t in FB_TYPES:
            return FB_TYPES[t]
        user = self.program.st_blocks.get(t)
        if user is not None:
            return user
        self.err(f"unknown type {t}", line)

    def initial_maker(self, typ, init, line):
        """Closure taking a frame and giving a variable's starting value."""
        if init is None:
            return lambda L: new_value(typ)
        if init[0] == "list":
            if not isinstance(typ, ArrayType):
                self.err("only an array takes a list of starting values", line)
            items = [self.expr(e) for e in init[1]]
            if len(items) > typ.size():
                self.err("too many starting values for this array", line)
            conv = coercer(typ.elem) if isinstance(typ.elem, str) else (lambda x: x)

            def make_array(L):
                arr = new_value(typ)
                for i, f in enumerate(items):
                    arr[i] = conv(f(L))
                return arr
            return make_array
        if not isinstance(typ, str):
            self.err("this type takes no starting value", line)
        conv = coercer(typ)
        f = self.expr(init)
        return lambda L: conv(f(L))


def _pin(ftype, name):
    """Canonical pin of a standard function block, whatever the case it was written in."""
    upper = name.upper()
    return upper if upper in ftype.PINS or upper in ftype.OUTS else None


def _element(locate, index, lo, hi):
    def get(L):
        i = int(index(L))
        if not lo <= i <= hi:
            raise PlcFault(f"array index {i} is outside {lo}..{hi}")
        return locate(L)[i - lo]
    return get


def is_fb_value(v) -> bool:
    return isinstance(v, (Fb, UserFb))
