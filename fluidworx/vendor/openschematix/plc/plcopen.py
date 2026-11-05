"""Reading PLCopen XML (IEC 61131-10, the TC6 format), the one exchange format PLC programming tools have in common.

Programs in ladder, function blocks and charts stay graphical where this PLC block has the same things. Structured text comes
across as text. What the graphic languages here can't hold, such as a function block of your own used as a block, comes
across as structured text instead, which runs the same. Instruction list isn't read, and neither is a chart inside a
function block: `notes` says what was left out, and what's left to fix shows up as problems when the program is checked.

Nothing in a file is trusted. The file declares no entities or it isn't read, it's limited in size, and whatever is in it
ends up as ordinary program source, which has the same limits as a program typed in here. See docs/PLC.md.
"""
from __future__ import annotations

import copy
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .core import FB_TYPES, CompileError, parse_time
from .fbd import GATES, pins_of

MAX_FILE = 32 * 1024 * 1024
MAX_IO = 64
MAX_POUS = 32
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ADDRESS = re.compile(r"%([IQ])([XBWDL]?)(\d+(?:\.\d+)*)", re.IGNORECASE)
_SECTIONS = {"localVars": "VAR", "tempVars": "VAR_TEMP", "inputVars": "VAR_INPUT", "outputVars": "VAR_OUTPUT",
             "inOutVars": "VAR_IN_OUT", "externalVars": "", "globalVars": "", "accessVars": ""}
_INFIX = {"AND": " AND ", "OR": " OR ", "XOR": " XOR ", "ADD": " + ", "MUL": " * ", "SUB": " - ", "DIV": " / ", "MOD": " MOD ",
          "GT": " > ", "GE": " >= ", "EQ": " = ", "NE": " <> ", "LT": " < ", "LE": " <= "}
_COMPARE = {"GT": ">", "GE": ">=", "EQ": "=", "NE": "<>", "LT": "<", "LE": "<="}
_FB_OUTPUT = {"TON": "Q", "TOF": "Q", "TP": "Q", "CTU": "Q", "CTD": "Q", "CTUD": "QU", "R_TRIG": "Q", "F_TRIG": "Q", "SR": "Q1", "RS": "Q1", "PID": "OUT"}
_RUNG_BLOCKS = ("TON", "TOF", "TP", "CTU", "CTD")
_POWER_PIN = {"TON": "IN", "TOF": "IN", "TP": "IN", "CTU": "CU", "CTD": "CD"}
_QUALIFIERS = {"N": "N", "S": "S", "R": "R", "P": "P", "P1": "P", "P0": "P0", "L": "L", "D": "D"}


class PlcOpenError(ValueError):
    """The file can't be read at all. The message is written for the user."""


@dataclass
class Imported:
    scan_ms: int | None = None
    pous: list = field(default_factory=list)        # as a PLC block stores them
    vars: list = field(default_factory=list)        # rows of the variable table
    tags: dict = field(default_factory=dict)        # pin -> its name in the program
    counts: dict = field(default_factory=lambda: {"di": 0, "do": 0, "ai": 0, "ao": 0})      # the most of each it needs
    notes: list = field(default_factory=list)       # what the person needs to know about what happened


def _root(data: bytes):
    if len(data) > MAX_FILE:
        raise PlcOpenError("This file is too large to be a PLC program.")
    plain = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in plain or b"<!ENTITY" in plain:
        raise PlcOpenError("This file declares its own XML entities, which a PLCopen file has no need of, so it wasn't read.")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError, UnicodeError) as e:
        raise PlcOpenError(f"This isn't a readable XML file.\n\n{e}") from e
    for el in root.iter():
        if isinstance(el.tag, str):
            el.tag = el.tag.rsplit("}", 1)[-1]
    if root.tag != "project" or root.find("types") is None:
        raise PlcOpenError("This is an XML file, but not a PLCopen project.")
    return root


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _int(text, default=0):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- what's on the PLC's pins
class _Pins:
    """%IX0.3 and the like, as the block's pins. An address too high for the block takes the next free pin, and says so."""

    def __init__(self, notes):
        self.notes = notes
        self.found: dict = {}
        self.used: dict = {"I": set(), "Q": set(), "AI": set(), "AO": set()}

    def pin(self, text: str):
        m = _ADDRESS.fullmatch(text.strip())
        if m is None:
            return None
        key = text.strip().upper()
        if key in self.found:
            return self.found[key]
        area, size, numbers = m.group(1).upper(), m.group(2).upper(), m.group(3).split(".")
        wide = size in ("W", "D", "L", "B")
        kind = ("AI" if area == "I" else "AO") if wide else area
        wanted = None
        if len(numbers) == 1:
            wanted = int(numbers[0])
        elif len(numbers) == 2 and not wide:
            wanted = int(numbers[0]) * 8 + int(numbers[1])
        taken = self.used[kind]
        n = wanted
        if n is None or n >= MAX_IO or n in taken:
            n = next((i for i in range(MAX_IO) if i not in taken), None)
            if n is None:
                self.notes.append(f"{text} doesn't fit: a PLC block has at most {MAX_IO} of each kind of pin.")
                return None
            self.notes.append(f"{text} is on {kind}{n} here.")
        taken.add(n)
        self.found[key] = f"{kind}{n}"
        return self.found[key]

    def counts(self) -> dict:
        names = {"I": "di", "Q": "do", "AI": "ai", "AO": "ao"}
        return {names[k]: max(v) + 1 if v else 0 for k, v in self.used.items()}

    def swap(self, text: str) -> str:
        """Addresses in source text, as the block's pins."""
        def one(m):
            return self.pin(m.group(0)) or m.group(0)
        return _ADDRESS.sub(one, text)


# ---------------------------------------------------------------- variables
@dataclass
class _Var:
    name: str
    type: str
    init: str = ""
    note: str = ""
    section: str = "VAR"
    address: str = ""
    constant: bool = False


def _type_text(el) -> str:
    kids = list(el) if el is not None else []
    if not kids:
        return "BOOL"
    t = kids[0]
    if t.tag == "derived":
        return t.get("name") or "BOOL"
    if t.tag == "array":
        dims = [f"{d.get('lower', '0')}..{d.get('upper', '0')}" for d in t.findall("dimension")]
        return f"ARRAY[{', '.join(dims)}] OF {_type_text(t.find('baseType'))}"
    if t.tag in ("string", "wstring"):
        return "STRING"
    return t.tag.upper()


def _variables(section) -> list:
    out = []
    kind = _SECTIONS.get(section.tag, "VAR")
    for v in section.findall("variable"):
        name = v.get("name") or ""
        if not _NAME.match(name):
            continue
        init = v.find("initialValue/simpleValue")
        out.append(_Var(name, _type_text(v.find("type")), init.get("value", "") if init is not None else "", _text(v.find("documentation"))[:200],
                        kind, v.get("address") or "", section.get("constant") in ("true", "1")))
    return out


def _interface(pou) -> list:
    out = []
    iface = pou.find("interface")
    if iface is None:
        return out
    for section in iface:
        if section.tag in _SECTIONS and section.tag not in ("externalVars", "accessVars"):
            out += _variables(section)
    return out


def _declarations(variables) -> str:
    """The VAR sections of an ST program or function block."""
    lines = []
    order = ("VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR", "VAR_TEMP")
    for kind in order:
        rows = [v for v in variables if v.section == kind]
        for constant in (False, True):
            group = [v for v in rows if v.constant == constant]
            if not group:
                continue
            lines.append(kind + (" CONSTANT" if constant else ""))
            for v in group:
                init = f" := {v.init}" if v.init else ""
                note = f"  (* {v.note.replace('*)', '* )')} *)" if v.note else ""
                lines.append(f"    {v.name} : {v.type}{init};{note}")
            lines.append("END_VAR")
    return "\n".join(lines)


# ---------------------------------------------------------------- the graphic networks
@dataclass
class _Conn:
    ref: int
    pin: str = ""
    negated: bool = False


def _conns(*points) -> list:
    """Every connection into these points. A convergence has one point for each thing that joins it."""
    out = []
    for point in points:
        if point is not None:
            out += [_Conn(_int(c.get("refLocalId"), -1), c.get("formalParameter") or "") for c in point.findall("connection")]
    return out


class _Element:
    def __init__(self, el):
        self.el = el
        self.tag = el.tag
        self.id = _int(el.get("localId"), -1)
        pos = el.find("position")
        self.x = _int(pos.get("x")) if pos is not None else 0
        self.y = _int(pos.get("y")) if pos is not None else 0
        self.order = _int(el.get("executionOrderId"))
        self.negated = el.get("negated") in ("true", "1")
        self.name = el.get("name") or ""
        self.expression = _text(el.find("expression"))
        self.variable = _text(el.find("variable"))
        self.into = _conns(*el.findall("connectionPointIn"))
        self.type = el.get("typeName") or ""
        self.instance = el.get("instanceName") or ""
        self.pins: list = []        # (pin, connections, negated)
        self.outs: list = []
        if el.tag == "block":
            for v in el.findall("inputVariables/variable"):
                self.pins.append((v.get("formalParameter") or "", _conns(v.find("connectionPointIn")), v.get("negated") in ("true", "1")))
            for v in el.findall("inOutVariables/variable"):
                self.pins.append((v.get("formalParameter") or "", _conns(v.find("connectionPointIn")), False))
            self.outs = [v.get("formalParameter") or "" for v in el.findall("outputVariables/variable")]

    def pin(self, name):
        return next((p for p in self.pins if p[0] == name), None)


class _Network:
    """The elements of one body, with connectors resolved. Reads anything as an ST expression."""

    def __init__(self, body, pins, notes, where, fb_names=frozenset()):
        self.pins, self.notes, self.where, self.fb_names = pins, notes, where, fb_names
        self.made = {}
        self.elements = {}
        self.named = {}
        for el in body:
            e = _Element(el)
            if e.id >= 0:
                self.elements[e.id] = e
                if e.tag == "connector":
                    self.named[e.name] = e

    def source(self, conn, seen=()):
        """What a connection really comes from, past connectors: (element, pin), or None."""
        e = self.elements.get(conn.ref)
        if e is None or e.id in seen:
            return None
        if e.tag == "continuation":
            target = self.named.get(e.name)
            if target is None or not target.into:
                return None
            return self.source(target.into[0], (*seen, e.id))
        return e, conn.pin

    def operand(self, text: str) -> str:
        return self.pins.swap(text.strip())

    def expr(self, conns, seen=(), negated=False) -> str:
        parts = [self._one(c, seen) for c in conns]
        parts = [p for p in parts if p]
        if not parts:
            return ""
        text = parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
        return f"NOT {_wrap(text)}" if negated else text

    def _one(self, conn, seen) -> str:
        found = self.source(conn)
        if found is None:
            return ""
        e, pin = found
        if e.id in seen:
            return ""
        seen = (*seen, e.id)
        if e.tag in ("inVariable", "inOutVariable"):
            text = self.operand(e.expression)
            return f"NOT {_wrap(text)}" if e.negated else text
        if e.tag == "leftPowerRail":
            return "TRUE"
        if e.tag in ("contact", "coil"):
            before = self.expr(e.into, seen)
            if e.tag == "coil":
                return before
            mine = self.operand(e.variable)
            if e.el.get("edge") in ("rising", "falling"):
                mine = f"{self.edge_of(e)}.Q"
            elif e.negated:
                mine = f"NOT {_wrap(mine)}"
            else:
                mine = _wrap(mine)
            return mine if before in ("", "TRUE") else f"({before} AND {mine})"
        if e.tag == "block":
            return self._block_value(e, pin, seen)
        return ""

    def _block_value(self, e, pin, seen) -> str:
        if pin == "ENO":
            en = e.pin("EN")
            return self.expr(en[1], seen) if en is not None and en[1] else "TRUE"
        if _is_fb(e, self.fb_names):
            return f"{self.instance_of(e)}.{pin or (e.outs[0] if e.outs else 'Q')}"
        args = [self.expr(p[1], seen, p[2]) or "FALSE" for p in e.pins if p[0] != "EN"]
        name = e.type.upper()
        if name == "NOT":
            return f"NOT {_wrap(args[0])}" if args else "FALSE"
        if name == "MOVE" and args:
            return args[0]
        if name in _INFIX and args:
            return "(" + _INFIX[name].join(_wrap(a) for a in args) + ")"
        return f"{e.type}({', '.join(args)})"

    def instance_of(self, e) -> str:
        if e.instance:
            return self.operand(e.instance)
        if e.id not in self.made:
            self.made[e.id] = (f"_{e.type}{e.id}", e.type)
        return self.made[e.id][0]

    def edge_of(self, e) -> str:
        """An edge contact, written out, needs something to remember the last scan with."""
        if e.id not in self.made:
            self.made[e.id] = (f"_edge{e.id}", "R_TRIG" if e.el.get("edge") == "rising" else "F_TRIG")
        return self.made[e.id][0]


def _wrap(text: str) -> str:
    return text if _NAME.match(text) or text.startswith("(") and text.endswith(")") else f"({text})"


def _is_fb(e, fb_names) -> bool:
    return e.type.upper() in FB_TYPES or e.type in fb_names or e.type.casefold() in fb_names or bool(e.instance)


# ---------------------------------------------------------------- function block diagram
def _fbd_as_diagram(net) -> dict | None:
    """The diagram as it is, if everything in it is a block this PLC has. None if not."""
    blocks, wires = [], []
    outs = {}
    ids = set(net.elements)
    next_id = max(ids, default=0) + 1
    for e in sorted(net.elements.values(), key=lambda x: (x.y, x.x)):
        if e.tag == "inVariable":
            if e.negated:
                return None
            blocks.append({"id": e.id, "type": "input", "expr": net.operand(e.expression), "x": e.x, "y": e.y})
        elif e.tag == "outVariable":
            blocks.append({"id": e.id, "type": "output", "target": net.operand(e.expression), "x": e.x, "y": e.y})
        elif e.tag == "inOutVariable":
            blocks.append({"id": e.id, "type": "input", "expr": net.operand(e.expression), "x": e.x, "y": e.y})
            blocks.append({"id": next_id, "type": "output", "target": net.operand(e.expression), "x": e.x + 140, "y": e.y})
            outs[e.id] = next_id
            next_id += 1
        elif e.tag == "block":
            t = e.type.upper()
            if t not in GATES and t not in FB_TYPES:
                return None
            names = [p[0] for p in e.pins]
            if "EN" in names and e.pin("EN")[1]:
                return None
            block = {"id": e.id, "type": t, "x": e.x, "y": e.y}
            if t in FB_TYPES:
                block["name"] = e.instance
            elif GATES[t][0] is None:
                block["n"] = max(2, len([n for n in names if n != "EN"]))
            neg = [p[0] for p in e.pins if p[2]]
            if neg:
                block["neg"] = neg
            blocks.append(block)
        elif e.tag in ("connector", "continuation", "comment"):
            continue
        else:
            return None

    def wire_to(target, pin, conns):
        if len(conns) > 1:
            return False
        for c in conns:
            found = net.source(c)
            if found is None:
                return False
            src, src_pin = found
            if src.tag in ("inVariable", "inOutVariable"):
                src_pin = "OUT"
            elif src.tag == "block":
                src_pin = src_pin or (src.outs[0] if src.outs else "OUT")
                if src_pin == "ENO":
                    return False
            else:
                return False
            wires.append({"from": [src.id, src_pin], "to": [target, pin]})
        return True
    for e in net.elements.values():
        if e.tag in ("outVariable", "inOutVariable"):
            target = outs.get(e.id, e.id)
            if not wire_to(target, "IN", e.into):
                return None
        elif e.tag == "block":
            for pin, conns, _neg in e.pins:
                if pin != "EN" and not wire_to(e.id, pin, conns):
                    return None
    by_id = {b["id"]: b for b in blocks}
    try:
        for w in wires:
            if w["from"][1] not in pins_of(by_id[w["from"][0]])[1] or w["to"][1] not in pins_of(by_id[w["to"][0]])[0]:
                return None
    except (CompileError, KeyError):
        return None
    return {"blocks": blocks, "wires": wires}


def _say_what_was_left(net):
    """What a network has that became nothing."""
    for tag, what in (("jump", "a jump"), ("label", "a label"), ("return", "a return")):
        if any(e.tag == tag for e in net.elements.values()):
            net.notes.append(f"{net.where}: {what} wasn't imported, so what follows it always runs. Check it by hand.")
    used = {c.ref for e in net.elements.values() for c in e.into} | {c.ref for e in net.elements.values() for _p, conns, _n in e.pins for c in conns}
    for e in net.elements.values():
        if e.tag == "block" and not _is_fb(e, net.fb_names) and e.id not in used:
            net.notes.append(f"{net.where}: nothing uses the result of {e.type}, so it was left out.")


def _statements(net) -> list:
    """A network as statements: blocks with memory called in signal order, then what's written."""
    out = []
    done = set()
    _say_what_was_left(net)

    def needs(conns, seen=()):
        for c in conns:
            found = net.source(c)
            if found is None:
                continue
            e = found[0]
            if e.id in seen:
                continue
            if e.tag == "block":
                if _is_fb(e, net.fb_names):
                    call(e)
                else:
                    for p in e.pins:
                        needs(p[1], (*seen, e.id))
            elif e.tag in ("contact", "coil"):
                needs(e.into, (*seen, e.id))
                if e.tag == "contact" and e.el.get("edge") in ("rising", "falling") and e.id not in done:
                    done.add(e.id)
                    out.append(f"{net.edge_of(e)}(CLK := {net.operand(e.variable)});")

    def call(e):
        if e.id in done:
            return
        done.add(e.id)
        for p in e.pins:
            needs(p[1])
        args = [f"{p[0]} := {net.expr(p[1], (), p[2])}" for p in e.pins if p[0] != "EN" and p[1]]
        text = f"{net.instance_of(e)}({', '.join(args)});"
        en = e.pin("EN")
        if en is not None and en[1]:
            text = f"IF {net.expr(en[1])} THEN {text} END_IF;"
        out.append(text)
    work = sorted(net.elements.values(), key=lambda x: (x.order or 10 ** 9, x.y, x.x))
    for e in work:
        if e.tag == "block" and _is_fb(e, net.fb_names):
            call(e)
        elif e.tag in ("outVariable", "inOutVariable") and e.into:
            needs(e.into)
            value = net.expr(e.into)
            if value:
                out.append(f"{net.operand(e.expression)} := {'NOT ' + _wrap(value) if e.negated else value};")
        elif e.tag == "coil":
            needs(e.into)
            value = net.expr(e.into) or "FALSE"
            target = net.operand(e.variable)
            storage = e.el.get("storage")
            if storage in ("set", "reset"):
                out.append(f"IF {value} THEN {target} := {'TRUE' if storage == 'set' else 'FALSE'}; END_IF;")
            else:
                out.append(f"{target} := {'NOT ' + _wrap(value) if e.negated else value};")
    return out


# ---------------------------------------------------------------- ladder
class _NotARung(ValueError):
    pass


def _ladder(net) -> list:
    """Rungs from a power network. Power is worked out backwards from each coil, which is right for any network since it only flows
    left to right. An element with memory that more than one path passes through (an edge, a timer) gets a rung of its own and a
    marker, as it would run twice otherwise."""
    apart: set = set()
    for _attempt in range(len(net.elements) + 1):
        rungs, doubled = _try_ladder(net, apart)
        if not doubled:
            return rungs
        apart |= doubled
    return rungs


def _try_ladder(net, apart):
    rungs = []
    emitted = {}
    uses: dict = {}
    items: dict = {}     # one for each element, so that the same element on two paths can be seen to be the same

    def item(e) -> dict:
        if e.id not in items:
            items[e.id] = _ladder_item(e, net)
        return items[e.id]

    def path(conns, seen) -> list:
        branches = [one(c, seen) for c in conns]
        if not branches:
            return []
        if len(branches) == 1:
            return branches[0]
        prefix = []
        for group in zip(*branches):
            if all(x is group[0] for x in group):
                prefix.append(group[0])
            else:
                break
        rest = [b[len(prefix):] for b in branches]
        return prefix + [{"t": "par", "branches": rest}]

    def one(conn, seen) -> list:
        found = net.source(conn)
        if found is None:
            return [{"t": "no", "a": "FALSE"}]
        e = found[0]
        if e.tag == "leftPowerRail":
            return []
        if e.tag in ("inVariable", "inOutVariable"):
            return [{"t": "nc" if e.negated else "no", "a": net.operand(e.expression)}]
        if e.id in seen:
            raise _NotARung(f"its power runs in a circle at {e.variable or e.type or e.id}")
        seen = (*seen, e.id)
        if e.tag == "coil":
            return path(e.into, seen)
        if e.tag == "contact":
            before = path(e.into, seen)
            mine = item(e)
        elif e.tag == "block":
            mine = item(e)
            before = path(_power_in(e, net), seen)
        else:
            raise _NotARung(f"a {e.tag} can't carry power")
        if _has_memory(mine):
            if e.id in apart:
                return [{"t": "no", "a": rung_alone(e, before, mine)}]
            uses[e.id] = uses.get(e.id, 0) + 1
        return before + [mine]

    def rung_alone(e, before, mine):
        if e.id not in emitted:
            emitted[e.id] = f"_net{e.id}"
            rungs.append({"comment": "", "items": before + [mine, {"t": "coil", "a": emitted[e.id]}]})
        return emitted[e.id]
    sinks = _sinks(net)
    for _key, group in sinks:
        first = group[0]
        try:
            conns = _power_in(first, net) if first.tag == "block" else first.into
            series = list(path(conns, ()))
            for e in group:
                if e.tag == "coil":
                    series.append(_coil(e, net))
                elif e.tag == "outVariable":
                    series.append({"t": "coil", "a": net.operand(e.expression)})
                else:
                    series.append(item(e))
            rungs.append({"comment": "", "items": series})
            for e in group:
                if e.tag == "block":
                    rungs += _block_outputs(e, net)
        except _NotARung as why:
            net.notes.append(f"{net.where}: a rung wasn't imported, since {why}.")
    doubled = {i for i, n in uses.items() if n > 1}
    return rungs, doubled


def _has_memory(it) -> bool:
    return it.get("t") in ("rise", "fall", "ton", "tof", "tp", "ctu", "ctd", "st", "move")


def _power_in(e, net) -> list:
    """The pin of a block that power reaches it through. None has no power at all to wait for, and always runs."""
    for name in ("EN", _POWER_PIN.get(e.type.upper())):
        pin = e.pin(name)
        if pin is not None and pin[1]:
            return pin[1]
    return []


def _sinks(net) -> list:
    """What rungs end at, in drawing order. Coils that share all their power are one rung."""
    fed: set = set()
    for e in net.elements.values():
        for c in e.into:
            found = net.source(c)
            if found:
                fed.add(found[0].id)
        for _pin, conns, _neg in e.pins:
            for c in conns:
                found = net.source(c)
                if found:
                    fed.add(found[0].id)
    groups: dict = {}
    for e in sorted(net.elements.values(), key=lambda x: (x.order or 10 ** 9, x.y, x.x)):
        if e.tag == "coil" and not _feeds_more(e, net):
            key = ("power",) + tuple(sorted((c.ref, c.pin) for c in e.into))
        elif e.tag == "block" and not _block_powers_something(e, net):
            key = ("block", e.id)
        elif e.tag == "outVariable" and e.into and net.source(e.into[0]) and net.source(e.into[0])[0].tag in ("contact", "leftPowerRail", "coil"):
            key = ("power",) + tuple(sorted((c.ref, c.pin) for c in e.into))
        else:
            continue
        groups.setdefault(key, []).append(e)
    return list(groups.items())


def _feeds_more(e, net) -> bool:
    """A coil with more of the rung after it: it passes its power on, and is a part of that rung's path."""
    for other in net.elements.values():
        if other.tag in ("contact",) and any(c.ref == e.id for c in other.into):
            return True
        if other.tag == "block" and any(c.ref == e.id for _p, conns, _n in other.pins for c in conns):
            return True
    return False


def _block_powers_something(e, net) -> bool:
    for other in net.elements.values():
        if other.tag in ("contact", "coil") and any(c.ref == e.id for c in other.into):
            return True
        if other.tag == "block" and other is not e and any(c.ref == e.id for _p, conns, _n in other.pins for c in conns):
            return True
    return False


def _coil(e, net) -> dict:
    storage = e.el.get("storage")
    t = {"set": "set", "reset": "reset"}.get(storage, "ncoil" if e.negated else "coil")
    return {"t": t, "a": net.operand(e.variable)}


def _value(e, pin, net, default="") -> str:
    p = e.pin(pin)
    return net.expr(p[1], (e.id,), p[2]) if p is not None and p[1] else default


def _ladder_item(e, net) -> dict:
    if e.tag == "contact":
        edge = e.el.get("edge")
        if edge in ("rising", "falling"):
            return {"t": "rise" if edge == "rising" else "fall", "a": net.operand(e.variable)}
        return {"t": "nc" if e.negated else "no", "a": net.operand(e.variable)}
    t = e.type.upper()
    if t in ("TON", "TOF", "TP"):
        return {"t": t.lower(), "a": net.instance_of(e), "pt": _value(e, "PT", net, "T#1s")}
    if t == "CTU":
        return {"t": "ctu", "a": net.instance_of(e), "pv": _value(e, "PV", net, "1"), "r": _value(e, "R", net)}
    if t == "CTD":
        return {"t": "ctd", "a": net.instance_of(e), "pv": _value(e, "PV", net, "1"), "r": _value(e, "LD", net)}
    if t in _COMPARE:
        return {"t": "cmp", "a": _value(e, "IN1", net, "0"), "op": _COMPARE[t], "b": _value(e, "IN2", net, "0")}
    return {"t": "move", "a": _output_target(e, net), "b": _value(e, "IN", net, "0")}


def _output_target(e, net) -> str:
    for other in net.elements.values():
        if other.tag in ("outVariable", "inOutVariable") and any(c.ref == e.id for c in other.into):
            return net.operand(other.expression)
    return ""


def _fits_on_rungs(net) -> bool:
    """Whether a ladder network has only what a rung here can hold. Anything else is written out, and runs the same."""
    for e in net.elements.values():
        if e.tag == "block":
            t = e.type.upper()
            if t == "MOVE":
                if not _output_target(e, net):
                    return False
            elif t not in _RUNG_BLOCKS and t not in _COMPARE:
                return False
            if not e.instance and t in _RUNG_BLOCKS:
                return False
        elif e.tag not in ("leftPowerRail", "rightPowerRail", "contact", "coil", "inVariable", "outVariable", "comment", "connector", "continuation"):
            return False
    return True


def _block_outputs(e, net) -> list:
    """Values a timer or counter hands on, such as ET: what its own rung can't say."""
    out = []
    if e.type.upper() in _RUNG_BLOCKS:
        for other in net.elements.values():
            if other.tag == "outVariable":
                for c in other.into:
                    if c.ref == e.id:
                        pin = c.pin or _FB_OUTPUT.get(e.type.upper())
                        code = f"{net.operand(other.expression)} := {net.instance_of(e)}.{pin};"
                        out.append({"comment": "", "items": [{"t": "st", "code": code}]})
    return out


# ---------------------------------------------------------------- charts
_SFC_PASS = ("selectionDivergence", "simultaneousDivergence")


def _chart(body, pou, net) -> dict:
    els = net.elements
    steps, trans = [], []
    by_name = {}
    for e in sorted(els.values(), key=lambda x: (x.y, x.x)):
        if e.tag == "step":
            if not _NAME.match(e.name):
                net.notes.append(f"{net.where}: the step “{e.name}” can't have that name here, so it wasn't imported.")
                continue
            steps.append({"id": e.id, "name": e.name, "initial": e.el.get("initialStep") in ("true", "1"), "actions": []})
            by_name[e.name] = e.id
        elif e.tag == "macroStep":
            net.notes.append(f"{net.where}: a macro step wasn't imported.")
    known = {s["id"]: s for s in steps}

    def before(e, seen=()) -> list:
        """The steps that lead to it, as alternatives: each a list of steps that must all be active."""
        if e.id in seen:
            return []
        seen = (*seen, e.id)
        if e.tag == "step":
            return [[e.id]] if e.id in known else []
        ins = [net.source(c) for c in e.into]
        ins = [x[0] for x in ins if x is not None]
        if e.tag == "simultaneousConvergence":
            combos = [[]]
            for x in ins:
                combos = [a + b for a in combos for b in before(x, seen)]
            return combos
        out = []
        for x in ins:
            out += before(x, seen)
        return out
    feeds: dict = {}
    for e in els.values():
        for c in e.into:
            found = net.source(c)
            if found is not None:
                feeds.setdefault(found[0].id, []).append(e)

    def after(e, seen=()) -> list:
        if e.id in seen:
            return []
        seen = (*seen, e.id)
        out = []
        for x in feeds.get(e.id, []):
            if x.tag == "step":
                if x.id in known:
                    out.append(x.id)
            elif x.tag == "jumpStep":
                target = by_name.get(x.el.get("targetName") or "")
                if target is not None:
                    out.append(target)
                else:
                    net.notes.append(f"{net.where}: a jump goes to a step that isn't there: {x.el.get('targetName')}.")
            elif x.tag != "actionBlock":
                out += after(x, seen)
        return out
    n = 0
    for e in sorted(els.values(), key=lambda x: (x.y, x.x)):
        if e.tag != "transition":
            continue
        cond = _condition(e, pou, net)
        for sources in before(e) or []:
            n += 1
            trans.append({"id": n, "from": sources, "to": after(e), "cond": cond or "FALSE"})
    for e in els.values():
        if e.tag == "actionBlock" and e.into:
            found = net.source(e.into[0])
            if found is None or found[0].id not in known:
                continue
            for a in e.el.findall("action"):
                act = _action(a, pou, net)
                if act is not None:
                    known[found[0].id]["actions"].append(act)
    return {"steps": steps, "transitions": trans}


def _condition(e, pou, net) -> str:
    cond = e.el.find("condition")
    if cond is None:
        return ""
    inline = cond.find("inline")
    if inline is not None:
        return _clean_condition(net.operand(_st_of(inline)))
    ref = cond.find("reference")
    if ref is not None:
        name = ref.get("name") or ""
        for t in pou.findall("transitions/transition"):
            if t.get("name") == name:
                st = t.find("body/ST")
                if st is not None:
                    return _clean_condition(net.operand(_text(st)), name)
                net.notes.append(f"{net.where}: the transition {name} is drawn, not written, so it needs writing by hand.")
                return ""
        return name
    conns = _conns(cond.find("connectionPointIn"))
    return net.expr(conns)


def _clean_condition(text, name="") -> str:
    """A transition's ST is its expression, or TRANSITION := expression;"""
    text = text.strip().rstrip(";").strip()
    m = re.match(r"^(?:\w+)\s*:=\s*(.*)$", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def _st_of(el) -> str:
    st = el.find("ST")
    return _text(st) if st is not None else _text(el)


def _action(a, pou, net):
    q = a.get("qualifier") or "N"
    if q not in _QUALIFIERS:
        net.notes.append(f"{net.where}: the action qualifier {q} isn't one this PLC has, so that action wasn't imported.")
        return None
    out = {"q": _QUALIFIERS[q]}
    if a.get("duration"):
        out["time"] = a.get("duration")
    ref = a.find("reference")
    inline = a.find("inline")
    if ref is not None:
        name = ref.get("name") or ""
        for act in pou.findall("actions/action"):
            if act.get("name") == name:
                st = act.find("body/ST")
                if st is None:
                    net.notes.append(f"{net.where}: the action {name} is drawn, not written, so it needs writing by hand.")
                    return None
                out["code"] = net.operand(_text(st))
                return out
        out["target"] = net.operand(name)
        return out
    if inline is not None:
        out["code"] = net.operand(_st_of(inline))
        return out
    return None


# ---------------------------------------------------------------- a whole file
def parse(data: bytes) -> Imported:
    """Everything in a PLCopen file that this PLC block can hold. PlcOpenError if it can't be read at all."""
    root = _root(data)
    out = Imported()
    pins = _Pins(out.notes)
    for dt in root.findall("types/dataTypes/dataType"):
        out.notes.append(f"The data type {dt.get('name')} wasn't imported: a PLC block has no types of its own. What uses it will show as a problem.")
    active = _configuration(root, out, pins)
    fb_names = set()
    for pou in root.findall("types/pous/pou"):
        if pou.get("pouType") == "functionBlock" and pou.get("name"):
            fb_names.add(pou.get("name"))
            fb_names.add(pou.get("name").casefold())
    frozen = frozenset(fb_names)
    for pou in root.findall("types/pous/pou"):
        name = pou.get("name") or "Program"
        try:
            _pou(pou, name, out, pins, frozen, active)
        except (KeyError, ValueError, AttributeError, TypeError, IndexError, RecursionError) as e:
            out.notes.append(f"{name} wasn't imported: it couldn't be read ({type(e).__name__}: {e}).")
    if len(out.pous) > MAX_POUS:
        out.notes.append(f"Only the first {MAX_POUS} programs were kept: that's as many as a PLC block has.")
        out.pous = out.pous[:MAX_POUS]
    out.pous = json.loads(json.dumps(out.pous))     # nothing shared between rungs, for whoever edits them next
    out.counts = pins.counts()
    if not out.pous:
        out.notes.append("There are no programs in this file that a PLC block can run.")
    return out


def _configuration(root, out, pins):
    """Which programs a task runs, in what order, and how often. None if the file doesn't say."""
    active = []
    intervals = []
    said = False
    for resource in root.findall("instances/configurations/configuration/resource"):
        for task in resource.findall("task"):
            ms = _time_ms(task.get("interval") or "")
            if ms:
                intervals.append(ms)
            for inst in task.findall("pouInstance"):
                said = True
                active.append(inst.get("typeName") or "")
        for inst in resource.findall("pouInstance"):
            said = True
            active.append(inst.get("typeName") or "")
    for section in root.findall("instances/configurations/configuration/globalVars") + \
            root.findall("instances/configurations/configuration/resource/globalVars"):
        for v in _variables(section):
            _global(v, out, pins, "")
    if intervals:
        out.scan_ms = max(1, min(1000, min(intervals)))
        if len(set(intervals)) > 1:
            out.notes.append(f"Its tasks run at different rates. Here everything runs every scan: {out.scan_ms} ms.")
    return active if said else None


def _time_ms(text) -> int:
    try:
        return int(parse_time(text))
    except (ValueError, OverflowError, TypeError):
        return 0


def _global(v, out, pins, pou):
    """A variable shared by the whole program: a tag if it's on a pin, a row of the variable table if not."""
    pin = pins.pin(v.address) if v.address else None
    if pin is not None:
        if pin in out.tags and out.tags[pin] != v.name:
            out.notes.append(f"{v.name} and {out.tags[pin]} are both {v.address}. A pin has one tag, so only {out.tags[pin]} is known to the program.")
        else:
            out.tags[pin] = v.name
        return
    same = next((r for r in out.vars if r["name"].casefold() == v.name.casefold()), None)
    if same is not None:
        if same["type"].upper() != v.type.upper():
            out.notes.append(f"{v.name} is used with two types: {same['type']} and {v.type}. It's {same['type']} here.")
        elif pou:
            out.notes.append(f"{v.name} is declared in more than one program. It's one variable here.")
        return
    out.vars.append({"name": v.name, "type": v.type, "init": v.init, "note": v.note})


def _pou(pou, name, out, pins, fb_names, active):
    kind = pou.get("pouType") or "program"
    body = pou.find("body")
    lang = list(body)[0] if body is not None and len(body) else None
    if lang is None:
        if kind == "program":
            out.notes.append(f"{name} has nothing in it.")
        return
    tag = lang.tag
    where = name
    if tag == "IL":
        out.notes.append(f"{name} wasn't imported: it's in instruction list, which this PLC block doesn't have.")
        return
    if tag not in ("ST", "LD", "FBD", "SFC"):
        out.notes.append(f"{name} wasn't imported: it's in {tag}.")
        return
    variables = _interface(pou)
    enabled = active is None or name in active
    if kind == "program":
        _program(pou, name, lang, variables, out, pins, fb_names, enabled, where)
    else:
        _callable(pou, name, kind, lang, variables, out, pins, fb_names, where)


def _keep_pins(variables, out, pins) -> list:
    """A variable on a pin is that pin's tag, in every language. The rest stay with their program."""
    rest = []
    for v in variables:
        if v.address and _ADDRESS.fullmatch(v.address.strip()):
            _global(v, out, pins, "")
        else:
            rest.append(v)
    return rest


def _program(pou, name, lang, variables, out, pins, fb_names, enabled, where):
    tag = lang.tag
    variables = _keep_pins(variables, out, pins)
    if tag == "ST":
        source, graphic = _st_program(variables, pins.swap(_text(lang))), None
    else:
        net = _Network(lang, pins, out.notes, where, fb_names)
        source, graphic = None, None
        if tag == "SFC":
            source, graphic = _chart(lang, pou, net), "sfc"
        elif tag == "FBD":
            diagram = _fbd_as_diagram(net)
            if diagram is not None and not _uses_user_type(variables, fb_names):
                _say_what_was_left(net)
                source, graphic = diagram, "fbd"
            else:
                out.notes.append(f"{name} uses blocks that have no place in a diagram here, so it's come across as structured text. It runs the same.")
                lines = _statements(net)
                source = _st_program(variables + _made_instances(net), "\n".join(lines))
        elif _fits_on_rungs(net) and not _uses_user_type(variables, fb_names):
            _say_what_was_left(net)
            source, graphic = {"rungs": _ladder(net) or [{"comment": "", "items": []}]}, "ld"
        else:
            out.notes.append(f"{name} has blocks that a rung here can't hold, so it's come across as structured text. It runs the same.")
            lines = _statements(net)
            source = _st_program(variables + _made_instances(net), "\n".join(lines))
        if graphic is not None:
            for v in variables:     # a graphic program here has no variables of its own
                _global(v, out, pins, name)
    stored = {"name": name, "lang": graphic or "st", "source": source}
    if not enabled:
        stored["disabled"] = True
        out.notes.append(f"{name} isn't run by any task in this file, so it's here but switched off.")
    out.pous.append(stored)


def _uses_user_type(variables, fb_names) -> bool:
    return any(v.type in fb_names or v.type.casefold() in fb_names for v in variables)


def _made_instances(net) -> list:
    """Instances the network needs that nothing declares."""
    return [_Var(name, kind) for name, kind in net.made.values()]


def _st_program(variables, body) -> str:
    head = _declarations(variables)
    return (head + "\n\n" if head else "") + body + "\n"


def _callable(pou, name, kind, lang, variables, out, pins, fb_names, where):
    """A function or a function block: as ST, the one language here that can define them."""
    tag = lang.tag
    extras = []
    if tag == "ST":
        body = pins.swap(_text(lang))
    elif tag == "SFC":
        out.notes.append(f"{name} wasn't imported: a chart inside a function block isn't something this PLC block has.")
        return
    else:
        net = _Network(lang, pins, out.notes, where, fb_names)
        body = "\n".join(_statements(net))
        extras = _made_instances(net)
        out.notes.append(f"{name} is drawn, and a function block here is written, so it's come across as structured text. It runs the same.")
    head = _declarations([v for v in variables if not v.address] + extras)
    if kind == "functionBlock":
        text = f"FUNCTION_BLOCK {name}\n{head}\n{body}\nEND_FUNCTION_BLOCK\n"
    else:
        ret = _type_text(pou.find("interface/returnType"))
        text = f"FUNCTION {name} : {ret}\n{head}\n{body}\nEND_FUNCTION\n"
    out.pous.insert(0, {"name": name, "lang": "st", "source": text})


# ---------------------------------------------------------------- into a block
def merge(params, imported: Imported, replace=False) -> list:
    """Put what was imported into a PLC block's parameters. Returns the names of the programs added. Nothing is lost that
    wasn't asked to be: with replace off it's added to what's there, and a clash of names takes a new name."""
    from .program import io_counts, program_of
    program = program_of(params)
    if replace:
        program["pous"] = []
        program["vars"] = []
    taken = {str(p.get("name")).casefold() for p in program["pous"] if isinstance(p, dict)}
    added = []
    for p in copy.deepcopy(imported.pous):
        base = str(p.get("name") or "Program")
        name, n = base, 1
        while name.casefold() in taken:
            n += 1
            name = f"{base}{n}"
        if name != base:
            imported.notes.append(f"There's already a program called {base}, so this one is {name}.")
        taken.add(name.casefold())
        p["name"] = name
        program["pous"].append(p)
        added.append(name)
    known = {str(r.get("name")).casefold() for r in program["vars"] if isinstance(r, dict)}
    for row in imported.vars:
        if row["name"].casefold() not in known:
            program["vars"].append(dict(row))
    tags = params.get("tags") if isinstance(params.get("tags"), dict) else {}
    for pin, tag in imported.tags.items():
        if tags.get(pin) and tags[pin] != tag:
            imported.notes.append(f"{pin} is already tagged {tags[pin]}, so {tag} wasn't put on it.")
        else:
            tags[pin] = tag
    params["tags"] = tags
    have = dict(zip(("di", "do", "ai", "ao"), io_counts(params)))
    for key, need in imported.counts.items():
        if need > have[key]:
            imported.notes.append(f"The block now has {need} {_COUNT_NAMES[key]}, for this program.")
            params[key] = need
    if imported.scan_ms and (replace or len(added) == len(program["pous"])):
        program["scan_ms"] = imported.scan_ms
    params["program"] = program
    return added


_COUNT_NAMES = {"di": "digital inputs", "do": "digital outputs", "ai": "analog inputs", "ao": "analog outputs"}

__all__ = ["Imported", "PlcOpenError", "merge", "parse"]
