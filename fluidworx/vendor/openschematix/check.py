"""Check Drawing: rule-based drawing validation.

The rules find drafting mistakes and inconsistencies. They do NOT certify
that a circuit is safe, correct or compliant with any standard; passing
every check only means none of these specific problems was found.
The rules are documented in docs/VALIDATION.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import symbols
from .connectivity import analyse
from .geometry import point_on_segment, same
from .netlist import (REF_BLANK_PIN, REF_MALFORMED, REF_MISSING_COMPONENT, REF_UNKNOWN_PIN, classify_pin_ref,
                      compute_nets, link_label, symbol_resolver_for)
from .project import is_terminal_symbol
from .symbols.general import OFFPAGE_IDS, UNKNOWN_ID

ERROR, WARNING, INFO = "error", "warning", "info"
SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

RULES = {
    "duplicate-id": "Duplicate component identifiers",
    "duplicate-terminal": "Duplicate terminal designations",
    "open-terminal": "Disconnected terminals",
    "dangling-wire": "Dangling wire ends",
    "port-domain": "Incompatible port domains",
    "fluid-rule": "Fluid-power port rules",
    "elec-rule": "Electrical port rules",
    "missing-prop": "Missing component properties",
    "device-parts": "Identifiers shared by several symbols",
    "xref": "Cross-sheet references",
    "junction": "Junction and overlap consistency",
    "symbol": "Unsupported or incomplete symbols",
    "wire-number": "Wire numbers",
    "invalid-wire-ref": "Invalid wire terminal references",
}


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    sheet_uid: str
    obj_id: int | None = None
    point: tuple | None = None
    suggestion: str = ""

    def sort_key(self):
        return (SEVERITY_ORDER[self.severity], self.code, self.message)


def _ports(c):
    """[(terminal, port type)] of a component."""
    sd = symbols.get(c.symbol)
    if sd is None:
        return []
    return [(t, sd.port_type(t)) for t in c.geometry().terminals]


@symbols.project_scoped
def check(project, rules=None, require_part_numbers: bool = False) -> list[Issue]:
    rules = set(rules or RULES)
    out: list[Issue] = []

    def issue(*a, **k):
        out.append(Issue(*a, **k))

    # ------------------------------------------------ identifiers
    if "duplicate-id" in rules:
        # Several components may share one identifier when they are parts of
        # the same device (a relay coil K1 and its contacts K1 13-14, 23-24).
        # They are duplicates when they are indistinguishable: same symbol,
        # same label and same terminal designations.
        seen = {}
        for doc in project.sheets:
            for c in doc.components.values():
                if c.designator and not is_terminal_symbol(c.symbol):
                    key = (c.designator, c.symbol, c.label.strip(), tuple(sorted(c.terminal_labels.items())))
                    seen.setdefault(key, []).append((doc, c))
        for key, lst in seen.items():
            if len(lst) > 1:
                where = ", ".join(sorted({d.name for d, _c in lst}))
                for doc, c in lst:
                    issue(ERROR, "duplicate-id", f"Identifier {key[0]} is used {len(lst)} times for identical "
                          f"components ({where}).", doc.uid, c.id, (c.x, c.y),
                          "Give each component a unique identifier. Parts of one device (e.g. a coil and its "
                          "contacts) may share an identifier if their labels or terminal numbers differ.")
    if "duplicate-terminal" in rules:
        seen = {}
        for doc in project.sheets:
            for c in doc.components.values():
                if is_terminal_symbol(c.symbol):
                    key = (c.designator, c.props.get("terminal", ""))
                    if not key[1]:
                        issue(WARNING, "duplicate-terminal", f"Terminal on strip {c.designator or '?'} has no "
                              f"terminal number.", doc.uid, c.id, (c.x, c.y), "Enter the terminal number.")
                        continue
                    seen.setdefault(key, []).append((doc, c))
                if c.terminal_labels:
                    labels = [c.terminal_label(n) for n in c.terminals()]
                    dups = {x for x in labels if labels.count(x) > 1}
                    if dups:
                        issue(ERROR, "duplicate-terminal", f"{c.tag()} has repeated terminal designations: "
                              f"{', '.join(sorted(dups))}.", doc.uid, c.id, (c.x, c.y),
                              "Each terminal of a component needs its own designation.")
        for (strip, num), lst in seen.items():
            if len(lst) > 1:
                for doc, c in lst:
                    issue(ERROR, "duplicate-terminal", f"Terminal {strip}:{num} exists {len(lst)} times.", doc.uid,
                          c.id, (c.x, c.y), "Renumber the terminal or move it to another strip.")

    # ------------------------------------------------ per-sheet connectivity
    for doc in project.sheets:
        conn = analyse(doc)
        if "open-terminal" in rules:
            for cid, name, p in conn.open_terminals:
                c = doc.components[cid]
                if c.symbol in OFFPAGE_IDS:
                    continue
                issue(WARNING, "open-terminal", f"Terminal {c.tag()}:{c.terminal_label(name)} is not connected.",
                      doc.uid, cid, p, "Connect it, or ignore if the terminal is intentionally unused "
                                       "(for example a plugged port or a spare contact).")
        if "dangling-wire" in rules:
            for wid, p in conn.open_wire_ends:
                issue(WARNING, "dangling-wire", "Wire end is not connected to a terminal or another wire.",
                      doc.uid, wid, p, "Extend the wire to a terminal or wire, or delete the loose piece.")
        if "invalid-wire-ref" in rules:
            _invalid_ref_rules(doc, issue)
        if "junction" in rules:
            _junction_rules(doc, issue)

    # ------------------------------------------------ nets: port compatibility
    if rules & {"port-domain", "fluid-rule", "elec-rule"}:
        for n in compute_nets(project):
            ports = []
            for uid, cid, name in n.terminals:
                doc = project.find_sheet(uid)
                c = doc.components[cid]
                for t, pt in _ports(c):
                    if t.name == name:
                        ports.append((doc, c, t, pt))
            doms = {pt.split(".")[0] for *_x, pt in ports} - {"any"}
            first = ports[0] if ports else None
            if "port-domain" in rules and len(doms) > 1 and first:
                desc = ", ".join(f"{c.tag()}:{c.terminal_label(t.name)} ({pt.split('.')[0]})" for _d, c, t, pt in ports
                                 if not pt.startswith("any"))
                issue(ERROR, "port-domain", f"A connection joins incompatible domains ({' / '.join(sorted(doms))}): "
                      f"{desc}.", first[0].uid, first[1].id, (first[1].x, first[1].y),
                      "Electrical, hydraulic and pneumatic ports cannot be joined directly; use a transducer, "
                      "valve solenoid or separate line.")
            if "fluid-rule" in rules:
                pump = [x for x in ports if x[3] == "hyd.pressure" and x[1].symbol.startswith("fl.hyd.pump")]
                tank = [x for x in ports if x[1].symbol == "fl.hyd.tank"]
                if pump and tank:
                    d, c = pump[0][0], pump[0][1]
                    issue(WARNING, "fluid-rule", f"Pump {c.tag()} delivery (P) is connected straight to the tank.",
                          d.uid, c.id, (c.x, c.y), "Check the circuit: pump delivery normally goes to the valves, "
                                                   "with a relief valve protecting it.")
                sup = [x for x in ports if x[3] == "pneu.supply"]
                exh = [x for x in ports if x[3] == "pneu.exhaust"]
                if sup and exh:
                    d, c = exh[0][0], exh[0][1]
                    issue(WARNING, "fluid-rule", f"Exhaust port {c.tag()}:{exh[0][2].name} is connected to a supply "
                          f"port.", d.uid, c.id, (c.x, c.y), "Exhaust ports (3, 5) should vent or go to a silencer.")
                ptank = [x for x in ports if x[3] == "hyd.tank"]
                ppress = [x for x in ports if x[3] == "hyd.pressure" and x not in pump]
                if ptank and ppress and not pump and len(ports) == 2:
                    d, c = ppress[0][0], ppress[0][1]
                    if ppress[0][1] is not ptank[0][1]:
                        issue(WARNING, "fluid-rule", f"Pressure port {c.tag()}:P is connected directly to a "
                              f"tank/return port.", d.uid, c.id, (c.x, c.y),
                              "Pressure and return lines are normally separate.")
            if "elec-rule" in rules:
                outs = [x for x in ports if x[3] == "elec.output"]
                if len(outs) > 1:
                    d, c = outs[0][0], outs[0][1]
                    issue(WARNING, "elec-rule", "Two or more outputs drive the same connection: " +
                          ", ".join(f"{x[1].tag()}:{x[1].terminal_label(x[2].name)}" for x in outs) + ".",
                          d.uid, c.id, (c.x, c.y), "Outputs should not be connected together.")
                pw = [x for x in ports if x[3] == "elec.power"]
                gn = [x for x in ports if x[3] == "elec.ground"]
                if pw and gn:
                    d, c = pw[0][0], pw[0][1]
                    issue(ERROR, "elec-rule", f"Supply terminal {c.tag()}:{c.terminal_label(pw[0][2].name)} is "
                          f"connected directly to earth/ground.", d.uid, c.id, (c.x, c.y),
                          "This is a short circuit unless intended; check the connection.")

    # ------------------------------------------------ cross references
    if "xref" in rules:
        labels = {}
        for doc in project.sheets:
            for c in doc.components.values():
                if c.symbol in OFFPAGE_IDS:
                    lab = link_label(c)
                    if not lab:
                        issue(ERROR, "xref", "Sheet connector has no label, so it cannot link to anything.",
                              doc.uid, c.id, (c.x, c.y), "Enter the signal name in the connector's label.")
                        continue
                    labels.setdefault(lab, []).append((doc, c))
        for lab, lst in labels.items():
            sheets = {d.uid for d, _c in lst}
            if len(lst) < 2:
                d, c = lst[0]
                issue(ERROR, "xref", f"Cross-sheet reference “{lab}” has no matching connector.", d.uid, c.id,
                      (c.x, c.y), "Add a sheet connector with the same label on the sheet the line continues on.")
            elif len(sheets) == 1:
                d, c = lst[0]
                issue(INFO, "xref", f"All connectors labelled “{lab}” are on the same sheet.", d.uid, c.id,
                      (c.x, c.y), "Draw a wire instead, or check the label.")

    # ------------------------------------------------ properties
    if "missing-prop" in rules:
        from .bom import purchasable
        for doc in project.sheets:
            for c in doc.components.values():
                sd = symbols.get(c.symbol)
                if sd and sd.prefix and not c.designator:
                    issue(WARNING, "missing-prop", f"A {sd.name} has no identifier.", doc.uid, c.id, (c.x, c.y),
                          "Give the component an identifier (for example " + sd.prefix + "1).")
                if require_part_numbers and purchasable(c) and not c.props.get("part_number"):
                    issue(INFO, "missing-prop", f"{c.tag()} has no part number.", doc.uid, c.id, (c.x, c.y),
                          "Enter manufacturer and part number for an accurate bill of materials.")

    # ------------------------------------------------ devices drawn with several symbols
    if "device-parts" in rules:
        # Components sharing an identifier are one physical device (see bom.py) if no two of them have the
        # same symbol, label and terminal designations. If they do, the bill of materials counts every
        # symbol separately. The duplicate-id rule reports such clashes; it compares terminal designation
        # overrides, so a clash it misses (an override equal to the symbol's own designation) is reported here.
        from .bom import designator_groups, devices, is_one_device, unit_slot
        for des, units in designator_groups(project):
            if len(units) < 2 or is_one_device(units):
                continue
            slots, dup = {}, {}
            for u in units:
                c = u.comp
                slots.setdefault(unit_slot(c), []).append(u)
                k = (c.symbol, c.label.strip(), tuple(sorted(c.terminal_labels.items())))
                dup[k] = dup.get(k, 0) + 1
            for same in slots.values():
                if len(same) < 2:
                    continue
                for u in same:
                    c = u.comp
                    if dup[(c.symbol, c.label.strip(), tuple(sorted(c.terminal_labels.items())))] > 1:
                        continue              # reported as "duplicate-id"
                    issue(WARNING, "device-parts", f"Identifier {des} is used for {len(same)} symbols of the same "
                          f"kind with the same label and terminal designations, so they cannot be parts of one "
                          f"device; the bill of materials counts each of them.", u.doc.uid, c.id, (c.x, c.y),
                          "Give separate devices different identifiers. If they are parts of one device, give "
                          "each part its own label or terminal designations (e.g. 13-14 and 23-24).")
        for dev in devices(project):
            parts = {}
            for u in dev:
                if u.has_part_number:
                    parts.setdefault(u.key, u)
            if len(parts) < 2:
                continue
            names = ", ".join(f"{u.manufacturer} {u.part_number}".strip() for u in parts.values())
            for u in dev:
                if u.has_part_number:
                    c = u.comp
                    issue(WARNING, "device-parts", f"{c.designator} is drawn with different part numbers ({names}); "
                          f"the bill of materials lists it once for each.", u.doc.uid, c.id, (c.x, c.y),
                          "Correct if these are separate parts of one device (e.g. a contactor and an auxiliary "
                          "contact block). Otherwise enter the same part number on every symbol of the device, "
                          "or on one symbol only.")

    # ------------------------------------------------ symbols
    if "symbol" in rules:
        for doc in project.sheets:
            for c in doc.components.values():
                sd = symbols.get(c.symbol)
                if sd is None or c.symbol == UNKNOWN_ID:
                    issue(ERROR, "symbol", f"{c.tag()} uses a symbol that is not available ({c.symbol}).", doc.uid,
                          c.id, (c.x, c.y), "Replace it with a library symbol or import the missing custom symbol.")
                elif sd.is_custom:
                    g = sd.build(None)
                    if not g.terminals:
                        issue(WARNING, "symbol", f"Custom symbol “{sd.name}” ({c.tag()}) has no connection points.",
                              doc.uid, c.id, (c.x, c.y), "Add connection points in the symbol editor.")
                    if not g.prims:
                        issue(ERROR, "symbol", f"Custom symbol “{sd.name}” has no geometry.", doc.uid, c.id,
                              (c.x, c.y), "Open it in the symbol editor and draw the symbol.")
                    untyped = [t.label or t.name for t in g.terminals if not t.ptype]
                    if untyped and sd.category in ("Hydraulic", "Pneumatic"):
                        issue(INFO, "symbol", f"Connection points of “{sd.name}” have no port type: "
                              f"{', '.join(untyped)}.", doc.uid, c.id, (c.x, c.y),
                              "Set port types in the symbol editor so the port rules can be applied.")

    # ------------------------------------------------ wire numbers
    if "wire-number" in rules:
        by_num = {}
        for n in compute_nets(project):
            manual = set()
            for uid, wid in n.wires:
                w = project.find_sheet(uid).wires[wid]
                if w.number_manual and w.number:
                    manual.add(w.number)
            if len(manual) > 1:
                uid, wid = n.wires[0]
                issue(WARNING, "wire-number", f"One connection has several manual wire numbers: "
                      f"{', '.join(sorted(manual))}.", uid, wid, None, "Use one number per connection.")
            if n.number:
                by_num.setdefault(n.number, []).append(n)
        for num, nets in by_num.items():
            if len(nets) > 1:
                uid, wid = nets[0].wires[0]
                issue(ERROR, "wire-number", f"Wire number {num} is used by {len(nets)} different connections.", uid,
                      wid, None, "Renumber one of them (Tools ▸ Wire numbers).")
    out.sort(key=Issue.sort_key)
    return out



def _invalid_ref_rules(doc, issue):
    """Wire ends attached to a terminal that does not exist (missing component, blank pin, or a pin the
    sheet's own project's symbol does not define). Such ends are not connected by the netlist, so a
    drawing that looks attached is reported instead of silently joined. References to a component
    whose symbol is temporarily unavailable are kept (the "symbol" rule reports the symbol)."""
    resolve, cache = symbol_resolver_for(doc), {}
    for w in doc.wires.values():
        for attr, idx in (("start", 0), ("end", -1)):
            ref = getattr(w, attr)
            if not ref:
                continue
            kind = classify_pin_ref(doc, ref, resolve, cache)
            where = w.points[idx]
            if kind == REF_MISSING_COMPONENT:
                issue(WARNING, "invalid-wire-ref", f"Wire {attr} references missing component #{ref[0]}.",
                      doc.uid, w.id, where, "Reattach the wire to a terminal, or restore the component.")
            elif kind in (REF_BLANK_PIN, REF_UNKNOWN_PIN):
                c = doc.components[ref[0]]
                what = "a blank terminal name" if kind == REF_BLANK_PIN else f"unknown terminal {str(ref[1])!r}"
                issue(WARNING, "invalid-wire-ref", f"Wire {attr} references {what} on {c.tag() if c.designator else c.symbol}.",
                      doc.uid, w.id, where, "Attach the wire to a real terminal, or update the terminal name.")
            elif kind == REF_MALFORMED:
                issue(WARNING, "invalid-wire-ref", f"Wire {attr} has a malformed terminal reference.",
                      doc.uid, w.id, where, "Reattach the wire to a terminal.")

def _junction_rules(doc, issue):
    wires = list(doc.wires.values())
    # collinear overlapping wires: look connected but the model is ambiguous
    reported = set()
    for i, a in enumerate(wires):
        for b in wires[i + 1:]:
            for p1, p2 in zip(a.points, a.points[1:]):
                for q1, q2 in zip(b.points, b.points[1:]):
                    if _overlap(p1, p2, q1, q2) and (a.id, b.id) not in reported:
                        reported.add((a.id, b.id))
                        mid = ((max(min(p1[0], p2[0]), min(q1[0], q2[0])) + min(max(p1[0], p2[0]), max(q1[0], q2[0]))) / 2,
                               (max(min(p1[1], p2[1]), min(q1[1], q2[1])) + min(max(p1[1], p2[1]), max(q1[1], q2[1]))) / 2)
                        issue(ERROR, "junction", "Two wires run on top of each other.", doc.uid, b.id, mid,
                              "Delete or move one of them; overlapping wires make the connection ambiguous.")
    # terminals lying on the middle of a wire (not connected, but look connected)
    for c in doc.components.values():
        for name, p in c.terminals().items():
            for w in wires:
                if same(p, w.points[0]) or same(p, w.points[-1]):
                    continue
                if any(point_on_segment(p, s, e) for s, e in zip(w.points, w.points[1:])):
                    issue(WARNING, "junction", f"Wire passes over terminal {c.tag()}:{c.terminal_label(name)} "
                          f"without connecting to it.", doc.uid, c.id, p,
                          "Wires connect to terminals only at their end points: end the wire on the terminal "
                          "or route it around.")
    # wire end landing exactly on a wire crossing: the dot would join all four
    from .editing import crossings
    for p, wa, wb in crossings(doc):
        for w in wires:
            if w.id in (wa, wb):
                continue
            if same(w.points[0], p) or same(w.points[-1], p):
                issue(WARNING, "junction", "A wire ends exactly on a crossing of two other wires; all three are "
                      "joined there.", doc.uid, w.id, p, "Check that this junction is intended.")


def _overlap(a, b, c, d) -> bool:
    from .editing import _overlap as ov
    return ov(a, b, c, d)


def summary(issues) -> dict:
    out = {ERROR: 0, WARNING: 0, INFO: 0}
    for i in issues:
        out[i.severity] += 1
    return out
