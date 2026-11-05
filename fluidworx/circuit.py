"""Turn an OpenSchematix project into a circuit: parts, the nets joining them, and things to warn about.

Connectivity comes from OpenSchematix's own netlist, so a net here is exactly a net in the editor, including
sheet connectors. Nothing in a schematic is changed; a study keeps its own parameter values (see study.py).
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field

from . import catalog, units
from .vendor.openschematix import netlist, projectio, symbols
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
    sheets: list                    # sheet uids containing fluid parts, in project order
    skipped_sheets: list            # names of sheets with nothing to simulate

    def part(self, key) -> Part | None:
        return self._by_key.get(tuple(key))

    def __post_init__(self):
        self._by_key = {p.key: p for p in self.parts}

    @property
    def media(self) -> set:
        return {p.medium for p in self.parts}


_PROP_KEYS = {
    "bore": "bore", "rod": "rod", "stroke": "stroke", "load": "load", "force": "load", "mass": "mass",
    "flow": "flow", "setting": "setting", "pressure": "setting", "precharge": "precharge", "volume": "volume",
    "displacement": "displacement", "torque": "torque", "opening": "opening", "load mode": "load_mode",
    "rating": None,
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


def build(project, warnings=()) -> Circuit:
    """Analyse a project. Never raises for a merely odd drawing: problems become issues the user can read."""
    issues = [Issue("info", w) for w in warnings if "older drawing format" not in w]
    with symbols.project_scope(project):
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
                if medium is None and sd is not None and sd.category in ("Hydraulic", "Pneumatic"):
                    medium = "hyd" if sd.category == "Hydraulic" else "pneu"
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
        for p in parts:
            if p.kind == "tank":
                fixed.update(p.terms.values())
        for p in parts:
            open_ports = [n for n in p.names if (p.sheet, p.comp.id, n) not in connected]
            _vent_and_warn(p, open_ports, fixed, issues)

        for node, media in node_medium.items():
            if len(media) > 1:
                tags = sorted(p.tag for p in parts if node in p.terms.values())
                issues.append(Issue("warning", "Hydraulic and pneumatic parts share one line: " + ", ".join(tags)
                                    + ". It is simulated as one fluid."))
        _circuit_checks(parts, fixed, issues)
        node_medium = {n: ("hyd" if "hyd" in m else "pneu") for n, m in node_medium.items()}
    if skipped:
        issues.append(Issue("info", "Not simulated (no fluid parts): " + ", ".join(skipped) + ". Electrical sheets "
                                    "are not simulated; operate solenoids by clicking the valve."))
    return Circuit(project, parts, next_node, fixed, gnd, wire_nodes, term_nodes, node_medium, issues, sheets, skipped)


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
