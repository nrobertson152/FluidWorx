"""How the electrical side of a drawing is tied to the fluid side: **the same tag means the same device.**

A coil Y1 is the solenoid of the valve Y1, a contact S3 belongs to the pressure switch S3, an analog sensor PT1 reads
the transducer PT1. Drawings are already read this way. The rest is in a few properties (see vendor simlinks.py):
*Solenoid a*, *Solenoid b*, *Driven by* and *Senses*. Everything found here is listed in the Links panel, along with
anything that looks like it should have been tied to something but wasn't.
"""
from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass

from . import units
from .vendor.openschematix import simlinks

COILS = ("coil", "coil_on", "coil_off", "relay")
CONTACTS = ("contact", "button", "selector", "changeover", "limit", "pressure_contact", "prox", "switch_manual")
SENSING = ("limit", "prox", "sensor_analog", "sensor_loop", "pot")
FLUID_ACTUATORS = ("cylinder", "cylinder_single", "cylinder_equal", "motor", "rotary")
FLUID_PRESSURE = ("gauge", "pressure_switch")
_PUMPS = ("pump", "pump_pc", "compressor")
_END = {"extended": 1.0, "end": 1.0, "+": 1.0, "retracted": 0.0, "home": 0.0, "start": 0.0, "-": 0.0}


@dataclass
class Sense:
    """What a sensor reads, as parsed from "A1 100%", "A1 > 150 mm", "PT1 > 120 bar", or just "PT1"."""
    target: str
    mode: str = "value"     # value: all of its range | at: near a place | above | below
    frac: float | None = None
    si: float | None = None
    quantity: str = ""      # "length", "pressure", "rpm" when a value was given with a unit


def parse_senses(text: str):
    """A Sense, or None if it can't be read."""
    text = (text or "").strip()
    if not text:
        return None
    m = re.match(r"^([^\s<>=]+)\s*(.*)$", text)
    if not m:
        return None
    target, rest = m.group(1), m.group(2).strip().lower()
    if target.endswith(("+", "-")) and len(target) > 1 and not rest:
        target, rest = target[:-1], target[-1]
    rest = re.sub(r"^at\s+", "", rest)
    if not rest:
        return Sense(target)
    if rest in _END:
        return Sense(target, "at", _END[rest])
    mode = "at"
    c = re.match(r"^(>=|<=|>|<|=)\s*(.*)$", rest)
    if c:
        mode = {">": "above", ">=": "above", "<": "below", "<=": "below", "=": "at"}[c.group(1)]
        rest = c.group(2).strip()
    p = re.match(r"^(\d+(?:\.\d+)?)\s*%$", rest)
    if p:
        return Sense(target, mode, float(p.group(1)) / 100.0)
    for q in ("length", "pressure"):
        v = units.find_quantity(rest, q)
        if v is not None:
            return Sense(target, mode, None, v, q)
    r = re.match(r"^(\d+(?:\.\d+)?)\s*rpm$", rest)
    if r:
        return Sense(target, mode, None, float(r.group(1)) * 2 * 3.141592653589793 / 60, "rpm")
    return None


@dataclass
class Link:
    kind: str               # solenoid | contact | pressure | sense | motor | overload
    source: tuple           # the part that drives
    target: tuple           # the part that is driven
    text: str               # for the Links panel
    side: str = ""          # left | right, for a solenoid
    sense: Sense | None = None


def _fold(tag) -> str:
    return (tag or "").strip().casefold()


def _prop(comp, name) -> str:
    """A property, whatever case it was typed in."""
    wanted = name.casefold()
    for k, v in comp.props.items():
        if k.strip().casefold() == wanted:
            return v.strip()
    return ""


def resolve(parts: list, issues: list, issue_type) -> list:
    """Every link in a circuit. Problems go in `issues`. A link never changes a connection: it says what follows what."""
    by_kind: dict = {}
    for p in parts:
        by_kind.setdefault(p.kind, []).append(p)
    coils: dict = {}
    for k in COILS:
        for p in by_kind.get(k, []):
            if _fold(p.tag):
                coils.setdefault(_fold(p.tag), []).append(p)
    for group in coils.values():
        if len(group) > 1:
            issues.append(issue_type("warning", f"{len(group)} coils are tagged {group[0].tag}. Contacts with that tag follow the "
                                                "first one drawn.", group[1].key))
    out: list = []
    used_coils: set = set()
    if any(p.medium == "el" for p in parts):
        _solenoids(parts, coils, used_coils, out, issues, issue_type)
    _contacts(parts, by_kind, coils, used_coils, out, issues, issue_type)
    _motors(by_kind, parts, out, issues, issue_type)
    for tag, group in coils.items():
        for coil in group:
            if coil.key not in used_coils and coil.kind != "relay":
                issues.append(issue_type("info", f"{coil.tag}: nothing else has this tag, so this coil operates nothing.",
                                         coil.key))
    return out


def _solenoids(parts, coils, used, out, issues, issue_type):
    for p in parts:
        if p.medium == "el":
            continue
        sides = simlinks.solenoid_sides(p.comp)
        if not sides:
            continue
        tag = _fold(p.tag)
        matched = 0
        for side in sides:
            named = _prop(p.comp, simlinks.SOLENOID_A if side == "a" else simlinks.SOLENOID_B)
            candidates = [_fold(named)] if named else _names_for(tag, side, len(sides))
            found = None
            for name in candidates:
                if name in coils:
                    found = coils[name]
                    break
            if not found:
                if named:
                    issues.append(issue_type("warning", f"{p.tag}: solenoid {side} is set to {named}, but no coil has that tag.",
                                             p.key))
                continue
            matched += 1
            where = "left" if side == "a" else "right"
            for coil in found:
                used.add(coil.key)
                out.append(Link("solenoid", coil.key, p.key, f"Coil {coil.tag} operates the {where}-hand solenoid of {p.tag}",
                                side=where))
        if tag in coils and len(sides) > 1 and not any(_prop(p.comp, k) for k in (simlinks.SOLENOID_A, simlinks.SOLENOID_B)):
            issues.append(issue_type("warning", f"{p.tag} has two solenoids and a coil with its own tag. Name the coils "
                                                f"{p.tag}a and {p.tag}b, so it's clear which is which.", p.key))
        if not matched and any(q.medium == "el" for q in parts):
            names = " and ".join(f"{p.tag}{s}" for s in sides) if len(sides) > 1 else p.tag
            issues.append(issue_type("info", f"{p.tag}: no coil named {names}, so operate its solenoid by clicking the valve.",
                                     p.key))


def _names_for(tag, side, count) -> list:
    if not tag:
        return []
    out = [f"{tag}{sep}{side}" for sep in ("", "-", ".", ":", "_", " ")]
    if count == 1:
        out.insert(0, tag)
    return out


def _contacts(parts, by_kind, coils, used_coils, out, issues, issue_type):
    sensors = [p for k in SENSING + CONTACTS for p in by_kind.get(k, [])]
    seen = set()
    actuators = {_fold(p.tag): p for k in FLUID_ACTUATORS for p in by_kind.get(k, []) if _fold(p.tag)}
    pressures = {_fold(p.tag): p for k in FLUID_PRESSURE for p in by_kind.get(k, []) if _fold(p.tag)}
    overloads = {_fold(p.tag): p for p in by_kind.get("overload", []) if _fold(p.tag)}
    for p in sensors:
        if p.key in seen:
            continue
        seen.add(p.key)
        tag = _fold(p.tag)
        senses = _prop(p.comp, simlinks.SENSES)
        if senses:
            sense = parse_senses(senses)
            if sense is None:
                issues.append(issue_type("warning", f"{p.tag}: can't read “{senses}”. Try A1 100%, A1 > 150 mm or PT1 > 120 bar.",
                                         p.key))
                continue
            target = actuators.get(_fold(sense.target)) or pressures.get(_fold(sense.target))
            if target is None:
                issues.append(issue_type("warning", f"{p.tag} senses {sense.target}, but no cylinder, motor, gauge or "
                                                    "transducer has that tag.", p.key))
                continue
            if sense.mode == "value" and p.kind not in ("sensor_analog", "sensor_loop", "pot"):
                issues.append(issue_type("warning", f"{p.tag} is a switch, so it needs to know where: try {sense.target} 100% or "
                                                    f"{sense.target} > 50%.", p.key))
                continue
            if target.kind == "motor" and sense.quantity != "rpm" and sense.mode != "value":
                issues.append(issue_type("warning", f"{sense.target} turns without end, so {p.tag} can only read its speed: try "
                                                    f"{sense.target} > 500 rpm.", p.key))
                continue
            out.append(Link("sense", target.key, p.key, f"{p.tag} senses {senses}", sense=sense))
            continue
        if p.kind in ("contact", "changeover"):
            if tag in coils:
                for coil in coils[tag]:
                    used_coils.add(coil.key)
                out.append(Link("contact", coils[tag][0].key, p.key, f"Contact {p.tag} follows coil {coils[tag][0].tag}"))
                continue
            if tag in overloads:
                out.append(Link("overload", overloads[tag].key, p.key, f"Contact {p.tag} follows overload {overloads[tag].tag}"))
                continue
        if tag in pressures and pressures[tag].kind == "pressure_switch" and p.kind in ("pressure_contact", "contact", "limit", "changeover"):
            out.append(Link("pressure", pressures[tag].key, p.key, f"Contact {p.tag} follows pressure switch {p.tag}"))
            continue
        if tag in pressures and p.kind in ("sensor_analog", "sensor_loop"):
            out.append(Link("sense", pressures[tag].key, p.key, f"{p.tag} reads the transducer {p.tag}", sense=Sense(p.tag)))
            continue
        if p.kind in ("limit", "prox"):
            issues.append(issue_type("info", f"{p.tag}: nothing operates it. Set Senses (A1 100%), or click it to operate it by hand.",
                                     p.key))
        elif p.kind == "pressure_contact":
            issues.append(issue_type("warning", f"{p.tag}: no pressure switch on a fluid sheet has this tag. Click it to operate it by hand.",
                                     p.key))
        elif p.kind in ("sensor_analog", "sensor_loop"):
            issues.append(issue_type("warning", f"{p.tag}: nothing to read. Give it the tag of a transducer, or set Senses. It sits at its low end.",
                                     p.key))
    for coil_tag, group in coils.items():
        for coil in group:
            if coil.kind == "relay":
                used_coils.add(coil.key)


def _motors(by_kind, parts, out, issues, issue_type):
    motors = {_fold(p.tag): p for k in ("emotor", "emotor3") for p in by_kind.get(k, []) if _fold(p.tag)}
    if not motors:
        return
    for k in _PUMPS:
        for pump in by_kind.get(k, []):
            named = _prop(pump.comp, simlinks.DRIVEN_BY)
            motor = motors.get(_fold(named)) if named else motors.get(_fold(pump.tag))
            if motor is not None:
                out.append(Link("motor", motor.key, pump.key, f"Motor {motor.tag} drives {pump.tag}"))
            elif named:
                issues.append(issue_type("warning", f"{pump.tag} is driven by {named}, but no electric motor has that tag.", pump.key))


# ---------------------------------------------------------------- supply rails named by a label
_RAIL_ZERO = {"0v", "0 v", "gnd", "n", "pe", "m", "com", "vss", "l-", "0vdc", "dc-", "-"}
_RAIL_DEFAULT = {"l+": 24.0, "vcc": 5.0, "vdd": 5.0, "vee": -5.0, "dc+": 24.0, "+": 24.0, "l": 230.0, "h": 230.0}
_VOLT = re.compile(r"^([-+]?)\s*(\d+(?:\.\d+)?)\s*v(?:dc|ac)?$")
_PHASE = re.compile(r"^l([123])(?:\s+(\d+(?:\.\d+)?)\s*v)?$")
SQRT3 = 3 ** 0.5


def rail_key(label: str, value):
    """Lines with the same key are the same line, wherever they're drawn. +24V and 24 VDC are; N and 0V aren't."""
    text = (label or "").strip().casefold().replace(" ", "")
    if text in ("n", "pe"):
        return text
    if isinstance(value, complex):
        return text
    return round(value, 6)


def parse_rail(label: str):
    """What a label says about the voltage on a line: a number of volts, a phasor for L1/L2/L3 (RMS line to neutral),
    or None if it says nothing."""
    text = (label or "").strip().lower()
    if not text:
        return None
    if text in _RAIL_ZERO:
        return 0.0
    if text in _RAIL_DEFAULT:
        return _RAIL_DEFAULT[text]
    m = _VOLT.match(text)
    if m:
        v = float(m.group(2))
        return -v if m.group(1) == "-" else v
    m = _PHASE.match(text)
    if m:
        phase = int(m.group(1))
        line_neutral = float(m.group(2)) / SQRT3 if m.group(2) else 230.0
        return cmath.rect(line_neutral, math.radians(-120.0 * (phase - 1)))
    return None
