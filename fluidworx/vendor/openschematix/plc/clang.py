"""A subset of C for PLC programs: a parser and a compiler to closures.

Covers what a control program needs: the integer and floating types, arrays, structs, pointers to variables and
array elements, functions (with recursion), and all the usual statements and operators. There is no preprocessor
beyond ``#include`` (ignored) and object-like ``#define``, no heap, no goto. ``float`` is computed in double
precision. Nothing here can reach anything outside the PLC's memory.
"""
from __future__ import annotations

import math
import re

from .core import (FB_TYPES, MAX_ARRAY, MAX_CALL_DEPTH, MAX_NEST, CompileError, Fb, PlcFault, Var, _checked, int_div,
                   int_mod, scale, wrap_int)

BREAK, CONTINUE, RETURN = 1, 2, 3
RET = "$ret"

_TOKEN = re.compile(r"""
    (?P<ws>[ \t\r\n\f\v]+)
  | (?P<fnum>(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?[fFlL]?|\d+[eE][-+]?\d+[fFlL]?)
  | (?P<inum>0[xX][0-9a-fA-F]+[uUlL]*|0[bB][01]+[uUlL]*|\d+[uUlL]*)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<char>'(?:[^'\\\n]|\\.)')
  | (?P<str>"(?:[^"\\\n]|\\.)*")
  | (?P<op><<=|>>=|\+\+|--|->|<<|>>|<=|>=|==|!=|&&|\|\||\+=|-=|\*=|/=|%=|&=|\|=|\^=|[-+*/%&|^~!<>=?:;,.(){}\[\]])
""", re.X)
_ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", "'": "'", '"': '"', "a": "\a", "b": "\b", "f": "\f",
        "v": "\v"}
KEYWORDS = {"if", "else", "while", "for", "do", "switch", "case", "default", "break", "continue", "return", "sizeof",
            "struct", "typedef", "static", "const", "volatile", "extern", "register", "signed", "unsigned", "void",
            "char", "short", "int", "long", "float", "double", "bool", "_Bool", "goto", "union", "enum", "true", "false",
            "NULL"}


class Tok:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind, self.value, self.line = kind, value, line


def _strip_comments(src):
    out, i, n = [], 0, len(src)
    while i < n:
        two = src[i:i + 2]
        c = src[i]
        if two == "//":
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif two == "/*":
            j = src.find("*/", i + 2)
            if j < 0:
                raise CompileError("this comment is never closed", src.count("\n", 0, i) + 1)
            out.append("\n" * src.count("\n", i, j) + " ")
            i = j + 2
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def tokenize(src: str) -> list:
    defines: dict = {}
    out = []
    for lineno, text in enumerate(_strip_comments(src).split("\n"), 1):
        stripped = text.strip()
        if stripped.startswith("#"):
            _directive(stripped, lineno, defines)
            continue
        i = 0
        while i < len(text):
            m = _TOKEN.match(text, i)
            if not m:
                raise CompileError(f"unexpected character {text[i]!r}", lineno)
            i = m.end()
            kind = m.lastgroup
            if kind == "ws":
                continue
            value = m.group()
            if kind == "id" and value in defines:
                out.extend(Tok(t.kind, t.value, lineno) for t in defines[value])
                continue
            if kind == "id" and value in KEYWORDS:
                kind = value
            elif kind == "op":
                kind = value
            out.append(Tok(kind, value, lineno))
    out.append(Tok("eof", "", src.count("\n") + 1))
    return out


def _directive(text, line, defines):
    m = re.match(r"#\s*(\w+)\s*(.*)$", text)
    word = m.group(1) if m else ""
    if word == "include" or word == "pragma":
        return
    if word == "define":
        d = re.match(r"([A-Za-z_]\w*)(\()?\s*(.*)$", m.group(2))
        if d is None:
            raise CompileError("bad #define", line)
        if d.group(2):
            raise CompileError("function-like macros aren't supported; write a function", line)
        body = tokenize(d.group(3))[:-1] if d.group(3) else []
        expanded = []
        for t in body:
            expanded += defines.get(t.value, [t]) if t.kind == "id" else [t]
        defines[d.group(1)] = expanded
        return
    raise CompileError(f"#{word} isn't supported; only #include and #define are", line)


# ---------------------------------------------------------------- types
class CType:
    name = "?"

    def conv(self, v):
        return v

    def new(self):
        return 0

    def size(self):
        return 4


class VoidT(CType):
    name = "void"


class IntT(CType):
    def __init__(self, name, bits, signed):
        self.name, self.bits, self.signed = name, bits, signed
        self.conv = wrap_int(bits, signed, truncate=True)

    def size(self):
        return self.bits // 8


class BoolT(CType):
    name = "bool"

    def conv(self, v):
        return 1 if v else 0

    def size(self):
        return 1


class TagBoolT(BoolT):
    """A BOOL shared with the other languages: it stays a real boolean in the PLC's memory."""

    def conv(self, v):
        return bool(v)


class RealT(CType):
    def __init__(self, name, bytes_):
        self.name, self._b = name, bytes_

    def conv(self, v):
        return float(v)

    def new(self):
        return 0.0

    def size(self):
        return self._b


class PtrT(CType):
    def __init__(self, to):
        self.to = to
        self.name = f"{to.name}*"

    def new(self):
        return None

    def size(self):
        return 4


class StrT(CType):
    name = "char*"

    def new(self):
        return ""


class ArrT(CType):
    def __init__(self, elem, n):
        self.elem, self.n = elem, n
        self.name = f"{elem.name}[{n}]"

    def new(self):
        return [self.elem.new() for _ in range(self.n)]

    def size(self):
        return self.elem.size() * self.n

    def count(self):
        return self.n * (self.elem.count() if isinstance(self.elem, ArrT) else 1)


class StructT(CType):
    def __init__(self, name):
        self.name = f"struct {name}"
        self.fields = {}

    def new(self):
        return {k: t.new() for k, t in self.fields.items()}

    def size(self):
        return sum(t.size() for t in self.fields.values())


class FbT(CType):
    def __init__(self, cls):
        self.cls = cls
        self.name = cls.__name__

    def new(self):
        return self.cls()

    def size(self):
        return 16


VOID = VoidT()
INT = IntT("int", 32, True)
LONGLONG = IntT("long long", 64, True)
DOUBLE = RealT("double", 8)
BOOL = BoolT()
BASE_TYPES = {"uint8_t": IntT("uint8_t", 8, False), "int8_t": IntT("int8_t", 8, True),
              "uint16_t": IntT("uint16_t", 16, False), "int16_t": IntT("int16_t", 16, True),
              "uint32_t": IntT("uint32_t", 32, False), "int32_t": IntT("int32_t", 32, True),
              "uint64_t": IntT("uint64_t", 64, False), "int64_t": IntT("int64_t", 64, True),
              "size_t": IntT("size_t", 32, False)}
for _name, _cls in FB_TYPES.items():
    BASE_TYPES[_name] = FbT(_cls)


class Ptr:
    """A pointer: a place in a list (an array, so it can move) or in a dict (a variable or a struct member)."""
    __slots__ = ("base", "key")

    def __init__(self, base, key):
        self.base, self.key = base, key

    def get(self):
        try:
            return self.base[self.key]
        except (IndexError, KeyError, TypeError):
            raise PlcFault("a pointer points outside its array") from None

    def set(self, v):
        if type(self.base) is list and not 0 <= self.key < len(self.base):
            raise PlcFault("a pointer points outside its array")
        self.base[self.key] = v

    def moved(self, n):
        if type(self.base) is not list:
            raise PlcFault("only a pointer into an array can be moved")
        return Ptr(self.base, self.key + int(n))

    def __eq__(self, other):
        return isinstance(other, Ptr) and self.base is other.base and self.key == other.key

    def __hash__(self):
        return id(self.base)

    def __bool__(self):
        return True


def _copy(v):
    if type(v) is dict:
        return {k: _copy(x) for k, x in v.items()}
    if type(v) is list:
        return [_copy(x) for x in v]
    return v


def _element(base, i):
    i = int(i)
    if type(base) is list:
        if not 0 <= i < len(base):
            raise PlcFault(f"array index {i} is outside 0..{len(base) - 1}")
        return base[i]
    if type(base) is Ptr:
        return base.moved(i).get()
    raise PlcFault("this is not an array or a pointer")


def _set_element(base, i, v):
    i = int(i)
    if type(base) is list:
        if not 0 <= i < len(base):
            raise PlcFault(f"array index {i} is outside 0..{len(base) - 1}")
        base[i] = v
    elif type(base) is Ptr:
        base.moved(i).set(v)
    else:
        raise PlcFault("this is not an array or a pointer")


# ---------------------------------------------------------------- parser
class Parser:
    def __init__(self, tokens):
        self.t, self.i, self.depth = tokens, 0, 0
        self.typedefs = dict(BASE_TYPES)
        self.structs = {}

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
            raise CompileError(f"expected {what or '“' + kind + '”'} but found {got}", self.cur.line)
        return tok

    def _enter(self):
        self.depth += 1
        if self.depth > MAX_NEST:
            raise CompileError("too deeply nested", self.cur.line)

    # ---- types
    def _is_type_start(self, tok=None):
        tok = tok or self.cur
        return tok.kind in ("void", "char", "short", "int", "long", "float", "double", "bool", "_Bool", "signed",
                            "unsigned", "struct", "const", "volatile", "static", "extern", "register") or \
            (tok.kind == "id" and tok.value in self.typedefs)

    def base_type(self):
        """(type, is static). Reads the specifiers before a declarator."""
        static = False
        words = []
        named = None
        while True:
            k = self.cur.kind
            if k in ("const", "volatile", "extern", "register"):
                self.i += 1
            elif k == "static":
                self.i += 1
                static = True
            elif k in ("void", "char", "short", "int", "long", "float", "double", "bool", "_Bool", "signed", "unsigned"):
                words.append(k)
                self.i += 1
            elif k == "struct":
                named = self._struct()
            elif k == "id" and self.cur.value in self.typedefs and not words and named is None:
                named = self.typedefs[self.cur.value]
                self.i += 1
            else:
                break
        if named is not None:
            return named, static
        if not words:
            raise CompileError(f"expected a type but found “{self.cur.value}”", self.cur.line)
        return _type_from_words(words, self.cur.line), static

    def _struct(self):
        self.need("struct")
        name_tok = self.take("id")
        name = name_tok.value if name_tok else f"anon{self.i}"
        st = self.structs.get(name)
        if st is None:
            st = self.structs[name] = StructT(name)
        if self.take("{"):
            while not self.take("}"):
                base, _ = self.base_type()
                while True:
                    fname, ftype, _params = self.declarator(base)
                    if isinstance(ftype, VoidT):
                        raise CompileError("a member can't be void", self.cur.line)
                    st.fields[fname] = ftype
                    if not self.take(","):
                        break
                self.need(";", "“;”")
        return st

    def declarator(self, base, abstract=False):
        """(name, type, params or None)."""
        typ = base
        while self.take("*"):
            typ = PtrT(typ)
            while self.take("const", "volatile"):
                pass
        name = ""
        if abstract == "maybe":
            tok = self.take("id")
            name = tok.value if tok else ""
        elif not abstract:
            name = self.need("id", "a name").value
        params = None
        if self.at("(") and not abstract:
            params = self._params()
        dims = []
        while self.take("["):
            if self.take("]"):
                dims.append(None)
            else:
                dims.append(self._const_expr())
                self.need("]", "“]”")
        for n in reversed(dims):
            if n is not None and not 0 < n <= MAX_ARRAY:
                raise CompileError(f"an array must have 1 to {MAX_ARRAY:,} elements", self.cur.line)
            typ = ArrT(typ, n if n is not None else 0)
        if isinstance(typ, ArrT) and typ.count() > MAX_ARRAY:
            raise CompileError(f"this array is too large (the limit is {MAX_ARRAY:,} elements)", self.cur.line)
        return name, typ, params

    def _const_expr(self):
        node = self.ternary()
        v = _fold(node)
        if not isinstance(v, int):
            raise CompileError("an array size must be a constant whole number", self.cur.line)
        return v

    def _params(self):
        self.need("(")
        out = []
        if self.take(")"):
            return out
        if self.at("void") and self.t[self.i + 1].kind == ")":
            self.i += 2
            return out
        while True:
            base, _ = self.base_type()
            name, typ, _p = self.declarator(base, abstract="maybe")
            if isinstance(typ, ArrT):
                typ = PtrT(typ.elem)        # an array parameter is a pointer
            out.append((name, typ))
            if not self.take(","):
                break
        self.need(")", "“)”")
        return out

    # ---- top level
    def unit(self):
        items = []
        while not self.at("eof"):
            if self.take(";"):
                continue
            line = self.cur.line
            if self.take("typedef"):
                base, _ = self.base_type()
                name, typ, _p = self.declarator(base)
                self.typedefs[name] = typ
                self.need(";", "“;”")
                continue
            base, static = self.base_type()
            if self.take(";"):
                continue
            while True:
                name, typ, params = self.declarator(base)
                if params is not None:
                    if self.at("{"):
                        items.append(("func", name, typ, params, self.compound(), line))
                        break
                    self.need(";", "“;” or a function body")
                    items.append(("proto", name, typ, params, line))
                    break
                init = self._init() if self.take("=") else None
                items.append(("global", name, typ, init, line))
                if self.take(","):
                    continue
                self.need(";", "“;”")
                break
        return items

    def _init(self):
        if self.at("{"):
            line = self.cur.line
            self.i += 1
            items = []
            while not self.take("}"):
                items.append(self._init())
                if not self.take(","):
                    self.need("}", "“}”")
                    break
            return ("list", items, line)
        return self.assignment()

    # ---- statements
    def compound(self):
        self.need("{")
        out = []
        while not self.take("}"):
            if self.at("eof"):
                raise CompileError("a “}” is missing", self.cur.line)
            out.append(self.statement())
        return ("block", out, self.cur.line)

    def statement(self):
        self._enter()
        try:
            return self._statement()
        finally:
            self.depth -= 1

    def _statement(self):
        tok = self.cur
        k = tok.kind
        line = tok.line
        if k == "{":
            return self.compound()
        if k == ";":
            self.i += 1
            return ("block", [], line)
        if k == "if":
            self.i += 1
            self.need("(", "“(”")
            cond = self.expression()
            self.need(")", "“)”")
            then = self.statement()
            other = self.statement() if self.take("else") else None
            return ("if", cond, then, other, line)
        if k == "while":
            self.i += 1
            self.need("(", "“(”")
            cond = self.expression()
            self.need(")", "“)”")
            return ("while", cond, self.statement(), line)
        if k == "do":
            self.i += 1
            body = self.statement()
            self.need("while", "while")
            self.need("(", "“(”")
            cond = self.expression()
            self.need(")", "“)”")
            self.need(";", "“;”")
            return ("dowhile", body, cond, line)
        if k == "for":
            return self._for(line)
        if k == "switch":
            return self._switch(line)
        if k == "break":
            self.i += 1
            self.need(";", "“;”")
            return ("break", line)
        if k == "continue":
            self.i += 1
            self.need(";", "“;”")
            return ("continue", line)
        if k == "return":
            self.i += 1
            value = None if self.at(";") else self.expression()
            self.need(";", "“;”")
            return ("return", value, line)
        if k in ("goto", "union", "enum"):
            raise CompileError(f"{k} isn't supported", line)
        if k in ("case", "default"):
            raise CompileError(f"“{k}” must be directly inside a switch", line)
        if self._is_type_start() and not (tok.kind == "id" and self.t[self.i + 1].kind in ("=", "(", "[", ".", "->")):
            return self._local_decl(line)
        e = self.expression()
        self.need(";", "“;”")
        return ("expr", e, line)

    def _local_decl(self, line):
        base, static = self.base_type()
        out = []
        if self.take(";"):
            return ("block", [], line)
        while True:
            name, typ, _p = self.declarator(base)
            if isinstance(typ, VoidT):
                raise CompileError("a variable can't be void", line)
            init = self._init() if self.take("=") else None
            out.append(("local", name, typ, init, static, line))
            if not self.take(","):
                break
        self.need(";", "“;”")
        return ("decls", out, line)

    def _for(self, line):
        self.need("for")
        self.need("(", "“(”")
        init = None
        if self.take(";"):
            pass
        elif self._is_type_start():
            init = self._local_decl(line)
        else:
            init = ("expr", self.expression(), line)
            self.need(";", "“;”")
        cond = None if self.at(";") else self.expression()
        self.need(";", "“;”")
        step = None if self.at(")") else self.expression()
        self.need(")", "“)”")
        return ("for", init, cond, step, self.statement(), line)

    def _switch(self, line):
        self.need("switch")
        self.need("(", "“(”")
        value = self.expression()
        self.need(")", "“)”")
        self.need("{", "“{”")
        labels, body = [], []
        while not self.take("}"):
            if self.at("eof"):
                raise CompileError("a “}” is missing", self.cur.line)
            if self.take("case"):
                v = _fold(self.ternary())
                if not isinstance(v, (int, float)):
                    raise CompileError("a case label must be a constant", self.cur.line)
                self.need(":", "“:”")
                labels.append((v, len(body)))
            elif self.take("default"):
                self.need(":", "“:”")
                labels.append((None, len(body)))
            else:
                body.append(self.statement())
        return ("switch", value, labels, body, line)

    # ---- expressions
    def expression(self):
        e = self.assignment()
        while self.at(","):
            line = self.cur.line
            self.i += 1
            e = ("comma", e, self.assignment(), line)
        return e

    def assignment(self):
        self._enter()
        try:
            left = self.ternary()
            if self.at("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
                tok = self.cur
                self.i += 1
                return ("assign", tok.kind, left, self.assignment(), tok.line)
            return left
        finally:
            self.depth -= 1

    def ternary(self):
        cond = self._binary(0)
        if self.at("?"):
            line = self.cur.line
            self.i += 1
            a = self.expression()
            self.need(":", "“:”")
            b = self.ternary()
            return ("cond", cond, a, b, line)
        return cond

    _LEVELS = (("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">="), ("<<", ">>"), ("+", "-"),
               ("*", "/", "%"))

    def _binary(self, level):
        if level == len(self._LEVELS):
            return self._unary()
        left = self._binary(level + 1)
        while self.cur.kind in self._LEVELS[level]:
            tok = self.cur
            self.i += 1
            left = ("bin", tok.kind, left, self._binary(level + 1), tok.line)
        return left

    def _unary(self):
        tok = self.cur
        k = tok.kind
        line = tok.line
        if k in ("-", "+", "!", "~", "*", "&"):
            self.i += 1
            self._enter()
            try:
                inner = self._unary()
            finally:
                self.depth -= 1
            return ("un", k, inner, line)
        if k in ("++", "--"):
            self.i += 1
            return ("incdec", k, self._unary(), True, line)
        if k == "sizeof":
            self.i += 1
            if self.at("(") and self._is_type_start(self.t[self.i + 1]):
                self.i += 1
                base, _ = self.base_type()
                _n, typ, _p = self.declarator(base, abstract=True)
                self.need(")", "“)”")
                return ("lit", typ.size(), line)
            return ("sizeof", self._unary(), line)
        if k == "(" and self._is_type_start(self.t[self.i + 1]):
            self.i += 1
            base, _ = self.base_type()
            _n, typ, _p = self.declarator(base, abstract=True)
            self.need(")", "“)”")
            return ("cast", typ, self._unary(), line)
        return self._postfix()

    def _postfix(self):
        node = self._primary()
        while True:
            line = self.cur.line
            if self.take("["):
                idx = self.expression()
                self.need("]", "“]”")
                node = ("index", node, idx, line)
            elif self.take("("):
                args = []
                if not self.take(")"):
                    while True:
                        args.append(self.assignment())
                        if not self.take(","):
                            break
                    self.need(")", "“)”")
                node = ("call", node, args, line)
            elif self.take("."):
                node = ("member", node, self.need("id", "a member name").value, line)
            elif self.take("->"):
                node = ("member", ("un", "*", node, line), self.need("id", "a member name").value, line)
            elif self.at("++", "--"):
                node = ("incdec", self.cur.kind, node, False, line)
                self.i += 1
            else:
                return node

    def _primary(self):
        tok = self.cur
        k = tok.kind
        line = tok.line
        self.i += 1
        if k == "(":
            e = self.expression()
            self.need(")", "“)”")
            return e
        if k == "inum":
            text = tok.value.rstrip("uUlL")
            if len(text) > 40:
                raise CompileError("this number is too long", line)
            if text[:2] in ("0x", "0X"):
                return ("lit", int(text, 16), line)
            if text[:2] in ("0b", "0B"):
                return ("lit", int(text, 2), line)
            if len(text) > 1 and text[0] == "0":
                try:
                    return ("lit", int(text, 8), line)
                except ValueError:
                    raise CompileError(f"bad octal number {text}", line) from None
            return ("lit", int(text), line)
        if k == "fnum":
            return ("lit", float(tok.value.rstrip("fFlL")), line)
        if k == "true":
            return ("lit", 1, line)
        if k == "false":
            return ("lit", 0, line)
        if k == "NULL":
            return ("lit", None, line)
        if k == "char":
            body = tok.value[1:-1]
            ch = _ESC.get(body[1], body[1]) if body[0] == "\\" else body
            return ("lit", ord(ch), line)
        if k == "str":
            text = re.sub(r"\\(.)", lambda m: _ESC.get(m.group(1), m.group(1)), tok.value[1:-1])
            while self.at("str"):
                more = self.cur.value
                self.i += 1
                text += re.sub(r"\\(.)", lambda m: _ESC.get(m.group(1), m.group(1)), more[1:-1])
            return ("str", text, line)
        if k == "id":
            return ("name", tok.value, line)
        self.i -= 1
        got = "the end of the program" if k == "eof" else f"“{tok.value}”"
        raise CompileError(f"expected a value but found {got}", line)


def _type_from_words(words, line):
    signed = "unsigned" not in words
    w = [x for x in words if x not in ("signed", "unsigned")]
    if "void" in w:
        return VOID
    if "bool" in w or "_Bool" in w:
        return BOOL
    if "float" in w:
        return RealT("float", 4)
    if "double" in w:
        return RealT("double", 8)
    if "char" in w:
        return IntT("char" if signed else "unsigned char", 8, signed)
    if "short" in w:
        return IntT("short" if signed else "unsigned short", 16, signed)
    longs = w.count("long")
    if longs >= 2:
        return IntT("long long" if signed else "unsigned long long", 64, signed)
    if longs == 1:
        return IntT("long" if signed else "unsigned long", 32, signed)
    return IntT("int" if signed else "unsigned int", 32, signed)


def _fold(node):
    """Value of a constant expression (array sizes, case labels), or None if it isn't constant."""
    if node[0] == "lit":
        return node[1]
    if node[0] == "un" and node[1] == "-":
        v = _fold(node[2])
        return -v if isinstance(v, (int, float)) else None
    if node[0] == "bin" and node[1] in ("+", "-", "*", "/", "<<"):
        a, b = _fold(node[2]), _fold(node[3])
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return None
        try:
            if node[1] == "<<":
                return a << b if 0 <= b <= 64 else None
            return {"+": a + b, "-": a - b, "*": a * b}.get(node[1], None) if node[1] != "/" else int_div(a, b)
        except (PlcFault, TypeError):
            return None
    return None


# ---------------------------------------------------------------- run-time library
def _fb_of(p, cls):
    obj = p.get() if type(p) is Ptr else p
    if not isinstance(obj, cls):
        raise PlcFault(f"{cls.__name__.lower()}() needs the address of a {cls.__name__} variable")
    return obj


def _timer(cls):
    def run(ctx, p, in_, pt_ms):
        o = _fb_of(p, cls)
        o.IN, o.PT = in_, pt_ms
        o.run(ctx.dt_ms)
        return 1 if o.Q else 0
    return run


def _ctu(ctx, p, cu, r, pv):
    o = _fb_of(p, FB_TYPES["CTU"])
    o.CU, o.R, o.PV = cu, r, pv
    o.run(ctx.dt_ms)
    return 1 if o.Q else 0


def _ctd(ctx, p, cd, ld, pv):
    o = _fb_of(p, FB_TYPES["CTD"])
    o.CD, o.LD, o.PV = cd, ld, pv
    o.run(ctx.dt_ms)
    return 1 if o.Q else 0


def _trig(cls):
    def run(ctx, p, clk):
        o = _fb_of(p, cls)
        o.CLK = clk
        o.run(ctx.dt_ms)
        return 1 if o.Q else 0
    return run


def _sr(ctx, p, s, r):
    o = _fb_of(p, FB_TYPES["SR"])
    o.S1, o.R = s, r
    o.run(ctx.dt_ms)
    return 1 if o.Q1 else 0


def _rs(ctx, p, s, r):
    o = _fb_of(p, FB_TYPES["RS"])
    o.S, o.R1 = s, r
    o.run(ctx.dt_ms)
    return 1 if o.Q1 else 0


def _pid(ctx, p, sp, pv, kp, ki, kd, lo, hi):
    o = _fb_of(p, FB_TYPES["PID"])
    o.SP, o.PV, o.KP, o.KI, o.KD, o.LO, o.HI = sp, pv, kp, ki, kd, lo, hi
    o.run(ctx.dt_ms)
    return o.OUT


def _log(ctx, text, *_args):
    ctx.log(text)
    return 0


_WITH_CTX = {"ton": (_timer(FB_TYPES["TON"]), 3), "tof": (_timer(FB_TYPES["TOF"]), 3), "tp": (_timer(FB_TYPES["TP"]), 3),
             "ctu": (_ctu, 4), "ctd": (_ctd, 4), "r_trig": (_trig(FB_TYPES["R_TRIG"]), 2),
             "f_trig": (_trig(FB_TYPES["F_TRIG"]), 2), "sr": (_sr, 3), "rs": (_rs, 3), "pid": (_pid, 8),
             "plc_log": (_log, 1)}
_PLAIN = {"fabs": (abs, 1), "abs": (abs, 1), "sqrt": (_checked(math.sqrt), 1), "sin": (_checked(math.sin), 1),
          "cos": (_checked(math.cos), 1), "tan": (_checked(math.tan), 1), "asin": (_checked(math.asin), 1),
          "acos": (_checked(math.acos), 1), "atan": (_checked(math.atan), 1), "atan2": (_checked(math.atan2), 2),
          "exp": (_checked(math.exp), 1), "log": (_checked(math.log), 1), "log10": (_checked(math.log10), 1),
          "pow": (_checked(math.pow), 2), "floor": (_checked(math.floor), 1), "ceil": (_checked(math.ceil), 1),
          "round": (_checked(round), 1), "fmod": (_checked(math.fmod), 2), "scale": (scale, 5),
          "limit": (lambda lo, x, hi: max(lo, min(x, hi)), 3), "min": (min, 2), "max": (max, 2)}


# ---------------------------------------------------------------- compiler
class Function:
    __slots__ = ("name", "ret", "params", "body", "statics")

    def __init__(self, name, ret, params):
        self.name, self.ret, self.params = name, ret, params
        self.body = None
        self.statics = {}


class Compiler:
    def __init__(self, ctx, program, pou):
        self.ctx, self.program, self.pou = ctx, program, pou
        self.G = ctx.G
        self.file: dict = {}            # file-scope variables of this C POU: name -> (key, type)
        self.frame: dict = {}           # their storage
        self.inits: list = []
        self.funcs: dict = {}
        self.scopes: list = []          # block scopes of the function being compiled
        self.current = None
        self._n = 0

    def err(self, msg, line=0):
        raise CompileError(msg, line, self.pou)

    # ---- whole unit
    def unit(self, items):
        for it in items:
            if it[0] in ("func", "proto"):
                name, typ, params = it[1], it[2], it[3]
                fn = self.funcs.get(name)
                if fn is None:
                    self.funcs[name] = Function(name, typ, params)
                elif len(fn.params) != len(params):
                    self.err(f"{name} is declared with different arguments", it[-1])
        for it in items:
            if it[0] == "global":
                self._global(it)
        for it in items:
            if it[0] == "func":
                self._function(it)
        for fn in self.funcs.values():
            if fn.body is None and fn.name not in ("setup", "loop"):
                self.err(f"{fn.name} is declared but has no body")

    def _global(self, it):
        _, name, typ, init, line = it
        if self.program.scope.find_exact(name) is not None:
            self.err(f"{name} is already a tag or a variable of this PLC", line)
        typ, init = self._sized(typ, init, line)
        key = f"{name}"
        self.file[name] = (key, typ)
        self.inits.append((key, self._maker(typ, init, line)))

    def _sized(self, typ, init, line):
        """Fill in the size of `int a[] = {...}`."""
        if isinstance(typ, ArrT) and typ.n == 0:
            if init is None or init[0] not in ("list", "str"):
                self.err("an array without a size needs starting values", line)
            n = len(init[1]) + (1 if init[0] == "str" else 0)
            if n > MAX_ARRAY:
                self.err("this array is too large", line)
            typ = ArrT(typ.elem, n)
        return typ, init

    def _maker(self, typ, init, line):
        """Closure giving a variable's starting value."""
        if init is None:
            return lambda L: typ.new()
        if init[0] == "list":
            return self._list_maker(typ, init, line)
        if init[0] == "str" and isinstance(typ, ArrT):
            codes = [ord(c) for c in init[1]][:typ.n]

            def make_chars(L):
                out = typ.new()
                out[:len(codes)] = codes
                return out
            return make_chars
        f, ft = self.expr(init)
        if isinstance(ft, ArrT):
            f = _decay(f)
        conv = typ.conv
        if isinstance(typ, StructT):
            return lambda L: _copy(f(L))
        return lambda L: conv(f(L))

    def _list_maker(self, typ, init, line):
        items = init[1]
        if isinstance(typ, ArrT):
            if len(items) > typ.n:
                self.err("too many starting values for this array", line)
            makers = [self._maker(typ.elem, e, line) for e in items]

            def make_array(L):
                out = typ.new()
                for i, m in enumerate(makers):
                    out[i] = m(L)
                return out
            return make_array
        if isinstance(typ, StructT):
            names = list(typ.fields)
            if len(items) > len(names):
                self.err("too many starting values for this struct", line)
            makers = [(names[i], self._maker(typ.fields[names[i]], e, line)) for i, e in enumerate(items)]

            def make_struct(L):
                out = typ.new()
                for k, m in makers:
                    out[k] = m(L)
                return out
            return make_struct
        if len(items) == 1:
            return self._maker(typ, items[0], line)
        self.err("this type takes a single starting value", line)

    def _function(self, it):
        _, name, ret, params, body, line = it
        fn = self.funcs[name]
        if fn.body is not None:
            self.err(f"{name} is defined twice", line)
        self.current = fn
        fn.params = params
        self.scopes = [{}]
        for pname, ptype in params:
            if pname:
                self.scopes[0][pname] = (pname, ptype)
        fn.body = self.statement(body)
        self.current = None

    # ---- names
    def _lookup_local(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    def _name_ref(self, name, line):
        """(read, write, address, type) of a variable."""
        local = self._lookup_local(name)
        if local is not None:
            key, typ = local
            if isinstance(local, _StaticRef):
                return self._ref_dict(local.store, key, typ)
            return self._ref_frame(key, typ)
        if name in self.file:
            key, typ = self.file[name]
            F = self.frame
            return self._ref_dict(F, key, typ)
        v = self.program.scope.find_exact(name)
        if v is None:
            other = self.program.scope.find(name)
            hint = f" Did you mean {other.alias or other.name}?" if other is not None else ""
            self.err(f"“{name}” is not declared.{hint}", line)
        return self._ref_program_var(v, name, line)

    @staticmethod
    def _ref_frame(key, typ):
        conv = typ.conv

        def write(L, val):
            L[key] = conv(val)
            return L[key]
        return (lambda L: L[key]), write, (lambda L: Ptr(L, key)), typ

    @staticmethod
    def _ref_dict(d, key, typ):
        conv = typ.conv

        def write(L, val):
            d[key] = conv(val)
            return d[key]
        return (lambda L: d[key]), write, (lambda L: Ptr(d, key)), typ

    def _ref_program_var(self, v, name, line):
        typ = _ctype_for_var(v)
        G = self.G
        key = v.key
        if v.writable:
            conv = typ.conv

            def write(L, val):
                G[key] = conv(val)
                return G[key]
        else:
            what = "an input" if v.kind == "input" else "read-only"

            def write(L, val):
                raise PlcFault(f"{name} is {what}")
            write.readonly = f"{name} is {what}, so a program can't write to it"
        return (lambda L: G[key]), write, (lambda L: Ptr(G, key)), typ

    # ---- expressions: expr() gives (closure, type or None)
    def expr(self, n):
        k = n[0]
        if k == "lit":
            v = n[1]
            typ = DOUBLE if isinstance(v, float) else INT
            return (lambda L: v), typ
        if k == "str":
            s = n[1]
            return (lambda L: s), StrT()
        if k == "name":
            read, _w, _a, typ = self._name_ref(n[1], n[2])
            return read, typ
        if k == "bin":
            return self._binary(n)
        if k == "un":
            return self._unary(n)
        if k == "assign":
            return self._assign(n)
        if k == "incdec":
            return self._incdec(n)
        if k == "cond":
            c, _ = self.expr(n[1])
            a, ta = self.expr(n[2])
            b, _tb = self.expr(n[3])
            return (lambda L: a(L) if c(L) else b(L)), ta
        if k == "comma":
            a, _ = self.expr(n[1])
            b, tb = self.expr(n[2])

            def both(L):
                a(L)
                return b(L)
            return both, tb
        if k == "index":
            read, _w, _a, typ = self._place(n)
            return read, typ
        if k == "member":
            read, _w, _a, typ = self._place(n)
            return read, typ
        if k == "call":
            return self._call(n)
        if k == "cast":
            f, _ = self.expr(n[2])
            conv = n[1].conv
            return (lambda L: conv(f(L))), n[1]
        if k == "sizeof":
            _f, typ = self.expr(n[1])
            size = typ.size() if typ is not None else 4
            return (lambda L: size), INT
        self.err("this can't be used as a value", n[-1])

    def _binary(self, n):
        _, op, ln, rn, line = n
        a, ta = self.expr(ln)
        b, tb = self.expr(rn)
        real = isinstance(ta, RealT) or isinstance(tb, RealT)
        typ = DOUBLE if real else (ta if isinstance(ta, (PtrT, ArrT)) else INT)
        if op == "&&":
            return (lambda L: 1 if a(L) and b(L) else 0), INT
        if op == "||":
            return (lambda L: 1 if a(L) or b(L) else 0), INT
        if op == "==":
            return (lambda L: 1 if a(L) == b(L) else 0), INT
        if op == "!=":
            return (lambda L: 1 if a(L) != b(L) else 0), INT
        if op == "<":
            return (lambda L: 1 if a(L) < b(L) else 0), INT
        if op == ">":
            return (lambda L: 1 if a(L) > b(L) else 0), INT
        if op == "<=":
            return (lambda L: 1 if a(L) <= b(L) else 0), INT
        if op == ">=":
            return (lambda L: 1 if a(L) >= b(L) else 0), INT
        if op in ("+", "-") and isinstance(ta, (PtrT, ArrT)):
            if isinstance(ta, ArrT):
                a = _decay(a)
                typ = PtrT(ta.elem)
            sign = 1 if op == "+" else -1
            return (lambda L: a(L).moved(sign * int(b(L)))), typ
        if op == "+":
            return (lambda L: _big(a(L) + b(L))), typ
        if op == "-":
            return (lambda L: _big(a(L) - b(L))), typ
        if op == "*":
            return (lambda L: _big(a(L) * b(L))), typ
        if op == "/":
            return (lambda L: int_div(a(L), b(L))), typ
        if op == "%":
            return (lambda L: int_mod(a(L), b(L))), typ
        if op == "&":
            return (lambda L: int(a(L)) & int(b(L))), INT
        if op == "|":
            return (lambda L: int(a(L)) | int(b(L))), INT
        if op == "^":
            return (lambda L: int(a(L)) ^ int(b(L))), INT
        if op == "<<":
            return (lambda L: _shift_left(a(L), b(L))), INT
        if op == ">>":
            return (lambda L: _shift_right(a(L), b(L))), INT
        self.err(f"unknown operator {op}", line)

    def _unary(self, n):
        _, op, inner, line = n
        if op == "&":
            _r, _w, addr, typ = self._place(inner)
            if isinstance(typ, ArrT):
                return addr, PtrT(typ.elem)
            return addr, PtrT(typ or INT)
        if op == "*":
            read, _w, _a, typ = self._place(n)
            return read, typ
        a, ta = self.expr(inner)
        if op == "-":
            return (lambda L: -a(L)), ta
        if op == "+":
            return a, ta
        if op == "!":
            return (lambda L: 0 if a(L) else 1), INT
        if op == "~":
            return (lambda L: ~int(a(L))), INT
        self.err(f"unknown operator {op}", line)

    def _place(self, n):
        """(read, write, address, type) of something that can be assigned to."""
        k = n[0]
        if k == "name":
            return self._name_ref(n[1], n[2])
        if k == "index":
            return self._place_index(n)
        if k == "member":
            return self._place_member(n)
        if k == "un" and n[1] == "*":
            return self._place_deref(n)
        self.err("this can't be assigned to", n[-1])

    def _place_index(self, n):
        _, base, idx, line = n
        b, tb = self.expr(base)
        i, _ = self.expr(idx)
        if isinstance(tb, ArrT):
            elem = tb.elem
        elif isinstance(tb, PtrT):
            elem = tb.to
        else:
            self.err("only arrays and pointers can be indexed", line)
        conv = elem.conv

        def write(L, v):
            v = conv(v)
            _set_element(b(L), i(L), v)
            return v

        def addr(L):
            base_v = b(L)
            pos = int(i(L))
            return Ptr(base_v, pos) if type(base_v) is list else base_v.moved(pos)
        return (lambda L: _element(b(L), i(L))), write, addr, elem

    def _place_member(self, n):
        _, base, member, line = n
        _r, _w, _a, tb = self._place(base)
        obj = _r
        if isinstance(tb, FbT):
            pin = member.upper()
            if pin not in tb.cls.PINS and pin not in tb.cls.OUTS:
                self.err(f"{tb.name} has no member {member}", line)

            def write_pin(L, v):
                setattr(obj(L), pin, v)
                return v
            return (lambda L: getattr(obj(L), pin)), write_pin, (lambda L: Ptr(obj(L).__dict__, pin)), None
        if not isinstance(tb, StructT):
            self.err("this is not a struct", line)
        if member not in tb.fields:
            self.err(f"{tb.name} has no member {member}", line)
        ft = tb.fields[member]
        conv = ft.conv

        def write(L, v):
            d = obj(L)
            d[member] = conv(v)
            return d[member]
        return (lambda L: obj(L)[member]), write, (lambda L: Ptr(obj(L), member)), ft

    def _place_deref(self, n):
        _, _op, inner, line = n
        p, tp = self.expr(inner)
        if isinstance(tp, ArrT):
            p = _decay(p)
            pointee = tp.elem
        elif isinstance(tp, PtrT):
            pointee = tp.to
        else:
            self.err("only a pointer can be dereferenced", line)
        conv = pointee.conv

        def read(L):
            q = p(L)
            if type(q) is not Ptr:
                raise PlcFault("a null pointer was dereferenced")
            return q.get()

        def write(L, v):
            q = p(L)
            if type(q) is not Ptr:
                raise PlcFault("a null pointer was dereferenced")
            v = conv(v)
            q.set(v)
            return v
        return read, write, p, pointee

    def _assign(self, n):
        _, op, target, value, line = n
        read, write, _a, typ = self._place(target)
        msg = getattr(write, "readonly", None)
        if msg:
            self.err(msg, line)
        if isinstance(typ, ArrT):
            self.err("an array can't be assigned as a whole", line)
        v, tv = self.expr(value)
        if isinstance(tv, ArrT):
            v = _decay(v)
        if isinstance(typ, StructT):
            base = v
            v = lambda L: _copy(base(L))
        if op == "=":
            return (lambda L: write(L, v(L))), typ
        fn = _COMPOUND[op[:-1]]
        return (lambda L: write(L, fn(read(L), v(L)))), typ

    def _incdec(self, n):
        _, op, target, prefix, line = n
        read, write, _a, typ = self._place(target)
        msg = getattr(write, "readonly", None)
        if msg:
            self.err(msg, line)
        d = 1 if op == "++" else -1
        ptr = isinstance(typ, PtrT)

        def step(L):
            old = read(L)
            new = write(L, old.moved(d) if ptr else old + d)
            return new if prefix else old
        return step, typ

    def _call(self, n):
        _, target, args, line = n
        if target[0] != "name":
            self.err("only a named function can be called", line)
        name = target[1]
        fn = self.funcs.get(name)
        if fn is not None:
            return self._user_call(fn, args, line)
        if name == "millis":
            if args:
                self.err("millis() takes no arguments", line)
            ctx = self.ctx
            return (lambda L: ctx.now_ms), LONGLONG
        if name in _WITH_CTX:
            f, count = _WITH_CTX[name]
            if name == "plc_log":
                if not args:
                    self.err("plc_log needs a message", line)
            elif len(args) != count:
                self.err(f"{name} takes {count} arguments", line)
            fs = [self._arg(a) for a in args]
            ctx = self.ctx
            return (lambda L: f(ctx, *[g(L) for g in fs])), (DOUBLE if name == "pid" else INT)
        if name in _PLAIN:
            f, count = _PLAIN[name]
            if len(args) != count:
                self.err(f"{name} takes {count} argument{'s' * (count != 1)}", line)
            fs = [self._arg(a) for a in args]
            if count == 1:
                a0 = fs[0]
                return (lambda L: f(a0(L))), DOUBLE if name not in ("abs", "min", "max") else None
            return (lambda L: f(*[g(L) for g in fs])), DOUBLE if name not in ("min", "max", "limit") else None
        self.err(f"there is no function called {name}", line)

    def _arg(self, a):
        f, t = self.expr(a)
        return _decay(f) if isinstance(t, ArrT) else f

    def _user_call(self, fn, args, line):
        if len(args) != len(fn.params):
            self.err(f"{fn.name} takes {len(fn.params)} argument{'s' * (len(fn.params) != 1)}", line)
        fs = []
        for a, (pname, ptype) in zip(args, fn.params):
            fs.append((pname or f"$a{len(fs)}", ptype.conv, self._arg(a), isinstance(ptype, StructT)))
        ctx = self.ctx
        conv = fn.ret.conv

        def call(L):
            ctx.tick()
            if ctx.depth >= MAX_CALL_DEPTH:
                raise PlcFault(f"{fn.name}: calls are nested too deeply")
            frame = {}
            for key, c, g, is_struct in fs:
                v = g(L)
                frame[key] = _copy(v) if is_struct else c(v)
            ctx.depth += 1
            try:
                fn.body(frame)
            finally:
                ctx.depth -= 1
            r = frame.get(RET)
            return None if r is None else conv(r)
        return call, fn.ret

    # ---- statements
    def statement(self, n):
        k = n[0]
        if k == "block":
            self.scopes.append({})
            try:
                return self._seq([self.statement(s) for s in n[1]])
            finally:
                self.scopes.pop()
        if k == "decls":
            return self._seq([self._local(d) for d in n[1]])
        if k == "expr":
            f, _ = self.expr(n[1])

            def run(L):
                f(L)
            return run
        if k == "if":
            c, _ = self.expr(n[1])
            a = self.statement(n[2])
            b = self.statement(n[3]) if n[3] is not None else (lambda L: None)
            return lambda L: a(L) if c(L) else b(L)
        if k == "while":
            return self._while(n)
        if k == "dowhile":
            return self._dowhile(n)
        if k == "for":
            return self._for(n)
        if k == "switch":
            return self._switch(n)
        if k == "break":
            return lambda L: BREAK
        if k == "continue":
            return lambda L: CONTINUE
        if k == "return":
            return self._return(n)
        self.err("this can't be run as a statement", n[-1])

    @staticmethod
    def _seq(fs):
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

    def _local(self, d):
        _, name, typ, init, static, line = d
        typ, init = self._sized(typ, init, line)
        self._n += 1
        key = f"{name}#{self._n}"
        scope = self.scopes[-1]
        if name in scope:
            self.err(f"{name} is declared twice", line)
        make = self._maker(typ, init, line)
        if static:
            mangled = f"{self.current.name}.{key}"
            self.inits.append((mangled, make))
            scope[name] = _StaticRef(self.frame, mangled, typ)
            return lambda L: None
        scope[name] = (key, typ)

        def declare(L):
            L[key] = make(L)
        return declare

    def _while(self, n):
        c, _ = self.expr(n[1])
        body = self.statement(n[2])
        ctx = self.ctx

        def run(L):
            while c(L):
                ctx.tick()
                r = body(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
            return None
        return run

    def _dowhile(self, n):
        body = self.statement(n[1])
        c, _ = self.expr(n[2])
        ctx = self.ctx

        def run(L):
            while True:
                ctx.tick()
                r = body(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
                if not c(L):
                    return None
        return run

    def _for(self, n):
        _, init, cond, step, body, _line = n
        self.scopes.append({})
        try:
            first = self.statement(init) if init is not None else (lambda L: None)
            c = self.expr(cond)[0] if cond is not None else (lambda L: 1)
            s = self.expr(step)[0] if step is not None else (lambda L: None)
            b = self.statement(body)
        finally:
            self.scopes.pop()
        ctx = self.ctx

        def run(L):
            first(L)
            while c(L):
                ctx.tick()
                r = b(L)
                if r == BREAK:
                    return None
                if r == RETURN:
                    return r
                s(L)
            return None
        return run

    def _switch(self, n):
        _, value, labels, body, _line = n
        v, _ = self.expr(value)
        self.scopes.append({})
        try:
            stmts = [self.statement(s) for s in body]
        finally:
            self.scopes.pop()
        table = {val: pos for val, pos in labels if val is not None}
        default = next((pos for val, pos in labels if val is None), None)

        def run(L):
            start = table.get(v(L), default)
            if start is None:
                return None
            for f in stmts[start:]:
                r = f(L)
                if r == BREAK:
                    return None
                if r is not None:
                    return r
            return None
        return run

    def _return(self, n):
        fn = self.current
        if n[1] is None:
            return lambda L: RETURN
        if isinstance(fn.ret, VoidT):
            self.err(f"{fn.name} is void, so it can't return a value", n[-1])
        f, _ = self.expr(n[1])

        def run(L):
            L[RET] = f(L)
            return RETURN
        return run


class _StaticRef(tuple):
    """A static local: found by _lookup_local like a frame variable, but it lives in the POU's file storage."""

    def __new__(cls, store, key, typ):
        self = super().__new__(cls, (key, typ))
        self.store = store
        return self


_COMPOUND = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b, "/": int_div, "%": int_mod,
             "&": lambda a, b: int(a) & int(b), "|": lambda a, b: int(a) | int(b), "^": lambda a, b: int(a) ^ int(b)}


def _big(v):
    if type(v) is int and not -(1 << 64) <= v <= (1 << 64):
        return v & ((1 << 64) - 1)
    return v


def _shift_left(a, b):
    b = int(b)
    if not 0 <= b <= 64:
        raise PlcFault("a shift must be between 0 and 64 bits")
    return (int(a) << b) & ((1 << 64) - 1)


def _shift_right(a, b):
    b = int(b)
    if not 0 <= b <= 64:
        raise PlcFault("a shift must be between 0 and 64 bits")
    return int(a) >> b


_COMPOUND["<<"] = _shift_left
_COMPOUND[">>"] = _shift_right


def _decay(f):
    def to_pointer(L):
        v = f(L)
        return Ptr(v, 0) if type(v) is list else v
    return to_pointer


def _ctype_for_var(v: Var):
    t = v.type
    if t == "BOOL":
        return TagBoolT()
    if t in ("REAL", "LREAL"):
        return DOUBLE
    if t == "TIME":
        return LONGLONG
    if isinstance(t, str):
        from .core import INT_TYPES
        if t in INT_TYPES:
            bits, signed = INT_TYPES[t]
            return IntT(t, bits, signed)
        return StrT()
    if isinstance(t, type) and issubclass(t, Fb):
        return FbT(t)
    from .core import ArrayType
    if isinstance(t, ArrayType):
        elem = _ctype_for_var(Var("", "", t.elem))
        return ArrT(elem, t.size())
    return INT


def compile_unit(src: str, ctx, program, pou: str):
    """(frame, inits, setup function or None, loop function)."""
    items = Parser(tokenize(src)).unit()
    comp = Compiler(ctx, program, pou)
    comp.unit(items)
    loop = comp.funcs.get("loop")
    if loop is None or loop.body is None:
        raise CompileError("a C program needs a function “void loop(void)”, which runs every scan", 0, pou)
    if loop.params:
        raise CompileError("loop() takes no arguments", 0, pou)
    setup = comp.funcs.get("setup")
    if setup is not None and setup.params:
        raise CompileError("setup() takes no arguments", 0, pou)
    return comp.frame, comp.inits, (setup.body if setup is not None and setup.body else None), loop.body
