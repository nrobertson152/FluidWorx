"""Turn an OpenSchematix project into a circuit: parts, the nets joining them, and things to warn about.

Connectivity comes from OpenSchematix's own netlist, so a net here is exactly a net in the editor, including
sheet connectors. Nothing in a schematic is changed; a study keeps its own parameter values (see study.py).
Fluid and electrical nets are numbered separately: they are two networks, tied together by links (links.py).
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field

from . import catalog, links as links_mod, units
from .vendor.openschematix import netlist, plc, projectio, symbols
from .vendor.openschematix.symbols.base import is_drafting_element
from .vendor.openschematix.symbols.general import OFFPAGE_IDS


class CircuitError(ValueError):
    """The file cannot be simulated. The message is written for the user."""


@dataclass
class Issue:
    level: str          # "error" | "warning" | "info"
    text: str
    part: tuple | None = None


@dataclass
class Part:
    key: tuple                      # (sheet uid, component id): stable across reloads of the schematic
    sheet: str
    comp: object
    tag: str
    kind: str
    medium: str
    spec: catalog.Spec
    symbol_name: str
    terms: dict = field(default_factory=dict)       # terminal name -> node
    names: list = field(default_factory=list)       # terminal names in symbol order
    params: dict = field(default_factory=dict)      # SI values
    from_schematic: set = field(default_factory=set)    # params read from the schematic's label or properties
    base_params: dict = field(default_factory=dict)     # values before any edits made in the study
    open_terms: set = field(default_factory=set)        # electrical terminals with nothing connected to them

    @property
    def title(self) -> str:
        return f"{self.tag} {self.comp.label}".strip() if self.comp.label else self.tag


@dataclass
class Circuit:
    project: object
    parts: list
    node_count: int
    fixed: set                      # nodes held at atmosphere / tank
    gnd: int                        # always-fixed node for parts that vent directly
    wire_nodes: dict                # (sheet uid, wire id) -> node
    term_nodes: dict                # (sheet uid, comp id, terminal) -> node
    node_medium: dict
    issues: list
    sheets: list                    # sheet uids containing parts to simulate, in project order
    skipped_sheets: list            # names of sheets with nothing to simulate
    el_node_count: int = 0
    el_fixed: set = field(default_factory=set)      # nodes at 0 V: earth, and one reference in each floating circuit
    el_gnd: int = 0
    el_wire_nodes: dict = field(default_factory=dict)
    el_term_nodes: dict = field(default_factory=dict)
    el_rails: list = field(default_factory=list)    # (node, volts, label, part key) from a label such as +24V or L1
    el_vnom: float = 24.0                           # the drawing's main supply, for a part in a circuit with none
    el_circuit_of: dict = field(default_factory=dict)   # node -> which circuit it's in: isolated ones differ
    links: list = field(default_factory=list)

    def part(self, key) -> Part | None:
        return self._by_key.get(tuple(key))

    def __post_init__(self):
        self._by_key = {p.key: p for p in self.parts}

    @property
    def media(self) -> set:
        return {p.medium for p in self.parts}

    @property
    def fluid_parts(self) -> list:
        return [p for p in self.parts if p.medium != "el"]

    @property
    def electrical_parts(self) -> list:
        return [p for p in self.parts if p.medium == "el"]


_PROP_KEYS = {
    "bore": "bore", "rod": "rod", "stroke": "stroke", "load": "load", "force": "load", "mass": "mass",
    "flow": "flow", "setting": "setting", "pressure": "setting", "precharge": "precharge", "volume": "volume",
    "displacement": "displacement", "torque": "torque", "opening": "opening", "load mode": "load_mode",
    "rating": None,
    "voltage": "voltage", "rated voltage": "rated", "rated": "rated", "power": "power", "resistance": "ohms",
    "capacitance": "farads", "inductance": "henries", "delay": "delay", "time": "delay", "limit": "limit",
    "current limit": "limit", "wiper": "wiper", "gain": "gain", "beta": "beta", "hfe": "beta", "vf": "vf", "vz": "vz",
    "vth": "vth", "current": "current", "primary": "primary", "secondary": "secondary",
}


def _params_from_schematic(part: Part) -> None:
    """Fill parameters from what the drawing already says: "160 bar", "10 L/min", "63/36x300", or properties."""
    defs = {p.key: p for p in catalog.PARAMS.get(part.kind, [])}
    comp = part.comp
    text = " ".join(x for x in (comp.label, comp.props.get("rating", ""), comp.props.get("description", "")) if x)
    if "setting" in defs:
        v = units.find_quantity(text, "pressure")
        if v:
            part.params["setting"] = v
            part.from_schematic.add("setting")
    if "flow" in defs:
        v = units.find_quantity(text, "flow")
        if v:
            part.params["flow"] = v
            part.from_schematic.add("flow")
    if "displacement" in defs:
        v = units.find_quantity(text, "displacement")
        if v:
            part.params["displacement"] = v
            part.from_schematic.add("displacement")
    if "bore" in defs:
        for k, v in units.find_cylinder(text).items():
            if k in defs:
                part.params[k] = v
                part.from_schematic.add(k)
    for name, value in comp.props.items():
        key = _PROP_KEYS.get(name.strip().lower())
        if key in defs:
            q = defs[key].quantity
            if q == "choice":
                part.params[key] = 1.0 if value.strip().lower().startswith("const") else 0.0
                part.from_schematic.add(key)
                continue
            v = units.find_quantity(value, q)
            if v is None:
                try:
                    v = units.Units("metric").to_si(q, units.parse_number(value))
                except ValueError:
                    continue
            part.params[key] = v
            part.from_schematic.add(key)


def _electric_params(part: Part) -> None:
    """The same for electrical parts: "24 V 5 W", "4k7", "100 uF", "5 s", "230/24 V", "7805"."""
    defs = {p.key: p for p in catalog.PARAMS.get(part.kind, [])}
    comp = part.comp
    text = " ".join(x for x in (comp.label, comp.props.get("rating", ""), comp.props.get("description", "")) if x)
    opts = part.spec.options

    def found(key, quantity):
        if key in defs:
            v = units.find_quantity(text, quantity)
            if v is not None:
                part.params[key] = v
                part.from_schematic.add(key)
                return True
        return False
    for key, value in opts.items():
        if key in defs and isinstance(value, (int, float)):
            part.params[key] = float(value)
    if part.kind == "transformer":
        m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*V?", text, re.IGNORECASE)
        if m:
            part.params["primary"], part.params["secondary"] = float(m.group(1)), float(m.group(2))
            part.from_schematic |= {"primary", "secondary"}
    elif part.kind in ("resistor", "pot"):
        for source in (comp.label, comp.props.get("rating", "")):
            v = units.find_resistance(source)
            if v:
                part.params["ohms"] = v
                part.from_schematic.add("ohms")
                break
    elif part.kind == "regulator":
        m = re.search(r"\b78(?:L|M|S)?(\d\d)\b", text)
        if m:
            part.params["voltage"] = float(m.group(1))
            part.from_schematic.add("voltage")
    for key, quantity in (("voltage", "voltage"), ("rated", "voltage"), ("vz", "voltage"), ("power", "power"),
                          ("farads", "capacitance"), ("henries", "inductance"), ("delay", "time"), ("limit", "current"),
                          ("current", "current"), ("rating", "current")):
        found(key, quantity)
    if part.kind in ("sensor_analog", "sensor_loop"):
        _sensor_range(part, text)
    for name, value in comp.props.items():
        key = _PROP_KEYS.get(name.strip().lower())
        if key in defs:
            q = defs[key].quantity
            v = units.find_quantity(value, q)
            if v is None and q == "resistance":
                v = units.find_resistance(value)
            if v is None:
                try:
                    v = units.parse_number(value)
                except ValueError:
                    continue
            part.params[key] = v
            part.from_schematic.add(key)


def _sensor_range(part: Part, text: str) -> None:
    for quantity, factor in (("pressure", 1e-5), ("length", 1e3)):
        span = units.find_range(text, quantity)
        if span:
            part.params["lo"], part.params["hi"] = span[0] * factor, span[1] * factor
            part.params["range_unit"] = 1.0 if quantity == "pressure" else 2.0
            part.from_schematic |= {"lo", "hi"}
            break
    amps = units.find_range(text, "current")
    volts = units.find_range(text, "voltage")
    if part.kind == "sensor_analog" and (amps or volts):
        choices = dict(zip(((4e-3, 20e-3), (0.0, 20e-3), (0.0, 10.0), (0.0, 5.0)), ("4-20mA", "0-20mA", "0-10V", "0-5V")))
        name = choices.get(tuple(round(x, 6) for x in (amps or volts)))
        if name:
            part.params["signal"] = float(catalog.SENSOR_SIGNALS.index(name))
            part.from_schematic.add("signal")


def apply_study_params(circuit: "Circuit", params: dict) -> None:
    """Overlay a study's edited values (keyed "sheet uid/component id"); values for missing parts are kept unused."""
    for p in circuit.parts:
        for k, v in params.get(f"{p.key[0]}/{p.key[1]}", {}).items():
            if k in p.params:
                p.params[k] = v


def load_project(path: str):
    """(project, warnings) for a .schematix or .osch file; CircuitError if it cannot be read."""
    try:
        res = projectio.open_any(path, activate=True)
    except (projectio.ProjectFormatError, ValueError, OSError, KeyError) as e:
        raise CircuitError(f"This file could not be opened as an OpenSchematix circuit.\n\n{e}") from e
    return res.project, list(res.warnings)


def load_project_bytes(data: bytes, ext: str):
    """Same as load_project, from the copy of a schematic embedded in a study."""
    fd, tmp = tempfile.mkstemp(suffix=ext if ext in (".schematix", ".osch") else ".schematix")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return load_project(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def build(project, warnings=(), overrides=None) -> Circuit:
    """Analyse a project. Never raises for a merely odd drawing: problems become issues the user can read.

    `overrides` are a study's own link settings ("uid/id" -> {property: text}), laid over this copy of the project.
    The schematic on disk is never touched."""
    issues = [Issue("info", w) for w in warnings if "older drawing format" not in w]
    with symbols.project_scope(project):
        for doc in project.sheets:
            for c in doc.components.values():
                for prop, text in (overrides or {}).get(f"{doc.uid}/{c.id}", {}).items():
                    if text:
                        c.props[prop] = text
                    else:
                        c.props.pop(prop, None)
        nets = netlist.compute_nets(project)
        term_net = {}
        wire_net = {}
        for i, n in enumerate(nets):
            for t in n.terminals:
                term_net[tuple(t)] = i
            for w in n.wires:
                wire_net[tuple(w)] = i

        parts: list[Part] = []
        sheets, skipped = [], []
        unsupported_seen = set()
        for doc in project.sheets:
            count = 0
            for c in doc.components.values():
                sd = symbols.get(c.symbol)
                medium = catalog.medium_of(c.symbol)
                if medium is None and sd is not None:
                    medium = {"Hydraulic": "hyd", "Pneumatic": "pneu", "Electrical": "el", "Electronic": "el"}.get(sd.category)
                if medium is None or c.symbol in OFFPAGE_IDS:
                    continue
                if sd is not None and is_drafting_element(sd) and not c.terminal_defs():
                    continue
                count += 1
                spec = catalog.classify(c.symbol)
                names = [t.name for t in c.terminal_defs()]
                if not names and spec.kind == "unsupported":
                    continue
                tag = c.designator or (sd.name if sd else c.symbol)
                part = Part((doc.uid, c.id), doc.uid, c, tag, spec.kind, medium, spec, sd.name if sd else c.symbol,
                            names=names, params=catalog.defaults(spec.kind, medium))
                if spec.kind == "prop" and "default" in spec.options:
                    part.params["opening"] = spec.options["default"]
                if medium == "el":
                    _electric_params(part)
                else:
                    _params_from_schematic(part)
                part.base_params = dict(part.params)
                parts.append(part)
                if spec.kind == "unsupported" and part.key not in unsupported_seen:
                    unsupported_seen.add(part.key)
                    issues.append(Issue("warning", f"{tag}: “{part.symbol_name}” is not simulated yet; its ports "
                                                   "are treated as blocked.", part.key))
                elif spec.approx:
                    issues.append(Issue("info", f"{tag}: {spec.approx}", part.key))
            (sheets if count else skipped).append(doc.uid if count else doc.name)

        # one node per net that touches a fluid part; every unconnected terminal gets a private node
        net_node: dict[int, int] = {}
        term_nodes: dict = {}
        node_medium: dict = {}
        next_node = 0
        for p in parts:
            if p.medium == "el":
                continue
            for name in p.names:
                ref = (p.sheet, p.comp.id, name)
                ni = term_net.get(ref)
                if ni is None:
                    node = next_node
                    next_node += 1
                else:
                    if ni not in net_node:
                        net_node[ni] = next_node
                        next_node += 1
                    node = net_node[ni]
                p.terms[name] = node
                term_nodes[ref] = node
                node_medium.setdefault(node, set()).add(p.medium)
        wire_nodes = {w: net_node[n] for w, n in wire_net.items() if n in net_node}
        gnd = next_node
        next_node += 1
        node_medium[gnd] = set()

        fixed = {gnd}
        connected = {r for r in term_net}
        fluid = [p for p in parts if p.medium != "el"]
        for p in fluid:
            if p.kind == "tank":
                fixed.update(p.terms.values())
        for p in fluid:
            open_ports = [n for n in p.names if (p.sheet, p.comp.id, n) not in connected]
            _vent_and_warn(p, open_ports, fixed, issues)

        for node, media in node_medium.items():
            if len(media) > 1:
                tags = sorted(p.tag for p in fluid if node in p.terms.values())
                issues.append(Issue("warning", "Hydraulic and pneumatic parts share one line: " + ", ".join(tags)
                                    + ". It is simulated as one fluid."))
        _circuit_checks(fluid, fixed, issues)
        node_medium = {n: ("hyd" if "hyd" in m else "pneu") for n, m in node_medium.items()}
        electric = _electric_nodes(project, parts, nets, term_net, wire_net, issues)
        _electrical_checks(parts, issues, electric)
        found = links_mod.resolve(parts, issues, Issue)
    if skipped:
        issues.append(Issue("info", "Nothing to simulate on: " + ", ".join(skipped) + "."))
    return Circuit(project, parts, next_node, fixed, gnd, wire_nodes, term_nodes, node_medium, issues, sheets, skipped,
                   links=found, **electric)


# ---------------------------------------------------------------- the electrical network
# Which of a part's terminals are joined inside it, for finding which circuits hang together. Isolated windings and
# the two sides of a supply are separate circuits, each with its own reference.
_ISOLATED = {"rectifier": (("AC1", "AC2"), ("+", "-")), "relay": (("A1", "A2"), ("13", "14"), ("23", "24"))}
_REFERENCE_TERMINALS = ("-", "M", "DC2", "2", "S2", "S4", "CT", "A2", "E", "K", "GND", "V-")
_SOURCES = ("source_v", "source_i", "psu", "rectifier", "transformer", "autotransformer")


def _groups(p: Part) -> list:
    if p.kind == "transformer":
        return [("P1", "P2")] + [(a, b) for a, b, _k in p.spec.options.get("windings", [])]
    if p.kind == "psu":
        pins = p.spec.options["pins"]
        return [pins[:2], pins[2:]]
    if p.kind in _ISOLATED:
        return _ISOLATED[p.kind]
    if p.kind == "plc":
        if plc.do_type(p.comp.params) == "relay":
            outputs = tuple(n for n in p.names if n.startswith("Q") or n == "C")
            return [tuple(n for n in p.names if n not in outputs), outputs]
    return [tuple(p.names)]


def _output_side(p: Part) -> list:
    """The groups of terminals that a source drives."""
    if p.kind in ("psu", "rectifier", "transformer"):
        return _groups(p)[1:]
    return _groups(p)


class _Sets:
    def __init__(self):
        self.up = {}

    def find(self, a):
        self.up.setdefault(a, a)
        while self.up[a] != a:
            self.up[a] = self.up[self.up[a]]
            a = self.up[a]
        return a

    def union(self, a, b):
        self.up[self.find(a)] = self.find(b)


def _electric_nodes(project, parts, nets, term_net, wire_net, issues) -> dict:
    """One node per electrical net, with terminals and earths merged, and a 0 V reference in every circuit.

    The nets are the editor's own. The one thing added is what any reader of a drawing does: supply lines with the same
    name are one line, so a +24V rail here and a +24V rail on the next rung (or the next sheet) carry the same current
    and lose power together. A label says what a line is only if nothing real feeds it: then the drawing is a control
    circuit with its supply left out, and the named lines are live."""
    el = [p for p in parts if p.medium == "el"]
    if not el:
        return {}
    nodes = _Sets()
    GND = "gnd"
    nodes.find(GND)

    def key_of(p, name):
        ref = (p.sheet, p.comp.id, name)
        ni = term_net.get(ref)
        return ("net", ni) if ni is not None else ("pin", ref)
    named = []          # (node key, volts, label, part key)
    for p in el:
        for name in p.names:
            nodes.find(key_of(p, name))
            if (p.sheet, p.comp.id, name) not in term_net:
                p.open_terms.add(name)
        if p.kind == "feedthrough" and len(p.names) >= 2:
            nodes.union(key_of(p, p.names[0]), key_of(p, p.names[1]))
        elif p.kind == "ground":
            nodes.union(key_of(p, p.names[0]), GND)
        elif p.kind in ("rail", "point") and len(p.names) == 1:
            label = (p.comp.label or p.comp.designator or "").strip()
            value = links_mod.parse_rail(label)
            if value is None and p.kind == "rail":
                value = 24.0 if p.comp.symbol.endswith(".pos") else 0.0
                label = label or ("+24V" if value else "0V")
            if value is not None:
                named.append((key_of(p, p.names[0]), value, label, p.key))
                if p.kind == "rail":
                    set_to = abs(value) if isinstance(value, complex) else value
                    p.params["voltage"] = p.base_params["voltage"] = set_to
    for doc in project.sheets:
        for c in doc.components.values():
            if c.symbol in OFFPAGE_IDS and netlist.link_label(c):
                for name in c.terminals():
                    ni = term_net.get((doc.uid, c.id, name))
                    if ni is not None and ("net", ni) in nodes.up:
                        value = links_mod.parse_rail(netlist.link_label(c))
                        if value is not None:
                            named.append((("net", ni), value, netlist.link_label(c), None))
    same_line = {}
    for key, value, label, _part in named:
        line = links_mod.rail_key(label, value)
        if line in same_line:
            nodes.union(key, same_line[line])
        else:
            same_line[line] = key

    def circuits() -> _Sets:
        sets = _Sets()
        for p in el:
            for group in _groups(p):
                present = [n for n in group if n in p.terms or n in p.names]
                for a, b in zip(present, present[1:]):
                    sets.union(nodes.find(key_of(p, a)), nodes.find(key_of(p, b)))
        return sets

    def fed(sets) -> set:
        out = set()
        for p in el:
            if p.kind in _SOURCES:
                for group in _output_side(p):
                    for n in group:
                        if n in p.names:
                            out.add(sets.find(nodes.find(key_of(p, n))))
        return out
    sets = circuits()
    has_source = fed(sets)
    rails = {}
    for key, value, label, part_key in named:
        if sets.find(nodes.find(key)) in has_source:
            continue
        if value == 0.0:
            nodes.union(key, GND)
        else:
            rails.setdefault(links_mod.rail_key(label, value), (key, value, label, part_key))
    sets = circuits()
    has_source = fed(sets)
    # number the nodes
    numbers: dict = {}

    def number(k):
        r = nodes.find(k)
        if r not in numbers:
            numbers[r] = len(numbers)
        return numbers[r]
    gnd = number(GND)
    term_nodes = {}
    circuit_of = {}
    for p in el:
        for name in p.names:
            node = number(key_of(p, name))
            p.terms[name] = node
            term_nodes[(p.sheet, p.comp.id, name)] = node
            circuit_of[node] = sets.find(nodes.find(key_of(p, name)))
    wire_nodes = {}
    for w, ni in wire_net.items():
        if ("net", ni) in nodes.up:
            wire_nodes[w] = number(("net", ni))
    rail_entries = [(number(key), value, label, part_key) for key, value, label, part_key in rails.values()]
    # a circuit fed by something real needs a reference. An earth gives it one; otherwise pick a sensible terminal.
    fixed = {gnd}
    earthed = sets.find(nodes.find(GND))
    members: dict = {}
    for p in el:
        for group in _groups(p):
            for n in group:
                if n in p.names:
                    members.setdefault(sets.find(nodes.find(key_of(p, n))), []).append((p, n))
    for circ, there in members.items():
        if circ == earthed or circ not in has_source:
            continue
        best = None
        for preferred in _REFERENCE_TERMINALS:
            best = next(((p, n) for p, n in there if n == preferred and p.kind in _SOURCES + ("plc",)), None)
            if best:
                break
        if best is None:
            best = next(((p, n) for p, n in there if n in _REFERENCE_TERMINALS), there[0])
        fixed.add(best[0].terms[best[1]])
    voltages = [abs(p.params.get("voltage", 0.0)) for p in el if p.kind in ("source_v", "psu")]
    voltages += [abs(value) for _n, value, _l, _k in rail_entries]
    vnom = max([x for x in voltages if x > 0], default=24.0)
    return dict(el_node_count=len(numbers), el_fixed=fixed, el_gnd=gnd, el_wire_nodes=wire_nodes, el_term_nodes=term_nodes,
                el_rails=rail_entries, el_vnom=vnom, el_circuit_of=circuit_of)


def _electrical_checks(parts: list, issues: list, electric: dict) -> None:
    el = [p for p in parts if p.medium == "el"]
    if not el:
        return
    for p in el:
        if p.kind == "unsupported":
            continue
        if p.kind == "plc":
            for d in plc.check(p.comp.params or {}):
                issues.append(Issue("error" if d.level == "error" else "warning", f"{p.tag} program: {d}", p.key))
            if "L+" in p.open_terms and "M" in p.open_terms:
                issues.append(Issue("warning", f"{p.tag}: nothing is wired to L+ and M, so it has no supply and won't run.", p.key))
    if not electric.get("el_rails") and not any(p.kind in _SOURCES for p in el):
        needs = [p for p in el if p.kind not in ("point", "ground", "feedthrough", "rail")]
        if needs:
            issues.append(Issue("info", "No electrical source was found. Add one, or label a connection +24V and 0V "
                                        "(or L1, L2, L3, N), and those lines are live."))
    if any(p.spec.options.get("ac") or p.kind in ("transformer", "emotor3") for p in el):
        issues.append(Issue("info", "AC is simulated at its RMS value, so phase and waveforms aren't modelled, except "
                                    "that L1, L2 and L3 are 120° apart."))


_PNEU_VENTS = {"3", "5"}


def _vent_and_warn(p: Part, open_ports: list, fixed: set, issues: list) -> None:
    if p.kind in ("tank", "gauge", "plug", "unsupported"):
        return
    if p.kind == "dcv" and p.medium == "pneu":
        for n in open_ports:
            if n in _PNEU_VENTS:      # an open exhaust port vents; it is normal not to pipe it
                fixed.add(p.terms[n])
        open_ports = [n for n in open_ports if n not in _PNEU_VENTS]
    if p.kind == "compressor" and p.names[1] in open_ports:
        fixed.add(p.terms[p.names[1]])
        open_ports.remove(p.names[1])
    if p.kind == "reducer" or p.kind == "relief":
        if p.medium == "pneu" and p.kind == "relief" and p.names[1] in open_ports:
            fixed.add(p.terms[p.names[1]])
            open_ports.remove(p.names[1])
    if p.kind in ("pump", "pump_pc") and not p.spec.options.get("bidir") and p.names[1] in open_ports:
        fixed.add(p.terms[p.names[1]])
        issues.append(Issue("warning", f"{p.tag}: suction port is not connected; it is treated as drawing from tank.",
                            p.key))
        open_ports.remove(p.names[1])
    if p.kind == "relief" and p.medium == "hyd" and len(p.names) > 1 and p.names[1] in open_ports:
        fixed.add(p.terms[p.names[1]])
        issues.append(Issue("warning", f"{p.tag}: outlet is not connected; it is treated as returning to tank.",
                            p.key))
        open_ports.remove(p.names[1])
    if p.kind == "dcv":
        open_ports = [n for n in open_ports if not _is_pilot(p, n)]
    if p.kind in ("cylinder_single",) or p.kind == "passage":
        open_ports = [n for n in open_ports if n not in ("L", "3", "C1", "C2")]
    if p.kind in ("pilot_check", "unloading"):
        open_ports = [n for n in open_ports if n not in ("X", "12")]
    if p.kind == "passage" and ("venturi" in p.comp.symbol or "orificeplate" in p.comp.symbol
                                or "pitot" in p.comp.symbol):
        open_ports = [n for n in open_ports if not n.startswith("X")]
    for n in open_ports:
        issues.append(Issue("info", f"{p.tag}: port {p.comp.terminal_label(n)} is not connected, so it is blocked.",
                            p.key))


def _is_pilot(p: Part, name: str) -> bool:
    from .vendor.openschematix.symbols.fluid import LAYOUTS
    return all(name != lay[0] for key, ports in LAYOUTS.items() for lay in ports if key[0] == p.medium)


def _circuit_checks(parts: list, fixed: set, issues: list) -> None:
    has = {k: [p for p in parts if p.kind == k] for k in {p.kind for p in parts}}
    sources = has.get("pump", []) + has.get("pump_pc", []) + has.get("compressor", [])
    if parts and not sources:
        issues.append(Issue("warning", "There is no pump or air supply, so nothing will move."))
    actuators = [p for k in ("cylinder", "cylinder_single", "cylinder_equal", "motor", "rotary")
                 for p in has.get(k, [])]
    if parts and not actuators:
        issues.append(Issue("info", "There is no cylinder or motor in this circuit."))
    for p in has.get("pump", []):
        if p.medium == "hyd" and "vacuum" not in p.comp.symbol and not (has.get("relief") or has.get("unloading")):
            issues.append(Issue("warning", f"{p.tag}: fixed pump with no relief valve anywhere in the circuit. "
                                           "Pressure will climb without limit if the flow is blocked.", p.key))
    if any(p.medium == "hyd" for p in parts) and not fixed - {max(fixed)} and sources:
        issues.append(Issue("warning", "No hydraulic line reaches a tank, so return flow has nowhere to go."))
