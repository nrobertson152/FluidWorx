"""How a drawing says what is tied to what when it is simulated.

Mostly it already does: **the same tag means the same device**. A relay coil K1 operates contacts K1, a coil Y1 is
the solenoid of the valve Y1, a pressure-switch contact S3 belongs to the pressure switch S3 on the fluid sheet.
The few things a tag can't say are ordinary component properties, named here. FluidWorx reads them; nothing in the
drawing's connections depends on them. See docs/PLC.md.
"""
from __future__ import annotations

from . import symbols
from .symbols.electrical_control import PLC_ID

SENSES = "Senses"
SOLENOID_A = "Solenoid a"
SOLENOID_B = "Solenoid b"
DRIVEN_BY = "Driven by"
ALL_KEYS = (SENSES, SOLENOID_A, SOLENOID_B, DRIVEN_BY)

_SENSING = ("el.switch.limit.", "el.sensor.", "el.potentiometer.")
_PUMPS = ("pump", "compressor", "vacuumpump")
_BUILT_IN_SOLENOID = (".unloading.sol", ".dcv.seated", ".sol.check.no", ".sol.check.nc", ".diverter6")


def solenoid_sides(comp) -> list:
    """Which sides of a valve carry a solenoid: "a" is the left-hand position's, "b" the right-hand one's."""
    symbol = comp.symbol or ""
    if not symbol.startswith("fl."):
        return []
    if symbol.endswith(".dcv"):
        sd = symbols.get(symbol)
        params = dict(sd.default_params) if sd is not None else {}
        params.update(comp.params or {})
        sides = []
        for side, name in (("left", "a"), ("right", "b")):
            ops = params.get(side)
            if isinstance(ops, list) and any(isinstance(o, str) and o.startswith("solenoid") for o in ops):
                sides.append(name)
        return sides
    if symbol.endswith(_BUILT_IN_SOLENOID) or ".prop." in symbol:
        return ["a"]
    return []


def _is_pump(symbol: str) -> bool:
    parts = symbol.split(".")
    return symbol.startswith("fl.") and len(parts) > 2 and parts[2] in _PUMPS


def fields_for(comp) -> list:
    """(property name, label, tip) for the simulation links a component can have."""
    symbol = comp.symbol or ""
    if symbol.startswith(_SENSING):
        return [(SENSES, "Senses", "What operates it, by tag: A1 100% (extended), A1 0% (retracted), A1 150 mm, "
                                   "A1 > 50%, or just A1 for a position transducer; PT1 > 120 bar, or PT1 for a "
                                   "pressure transducer.")]
    if symbol == PLC_ID:
        return []
    sides = solenoid_sides(comp)
    if sides:
        out = []
        for side in sides:
            key = SOLENOID_A if side == "a" else SOLENOID_B
            where = "left" if side == "a" else "right"
            tag = comp.designator or "this valve's tag"
            out.append((key, f"Solenoid {side}", f"Tag of the coil that operates the {where}-hand solenoid. Leave empty "
                                                 f"to use {tag}{side if len(sides) > 1 else ''}."))
        return out
    if _is_pump(symbol):
        return [(DRIVEN_BY, "Driven by", "Tag of the electric motor that drives it, or leave empty if the motor has "
                                         "the pump's own tag. It only runs while that motor does.")]
    return []


def suggestions(project, key) -> list:
    """Tags worth offering for a link: the coils for a solenoid, cylinders and instruments for a sensor, motors for a
    pump."""
    out = set()
    for doc in project.sheets:
        for c in doc.components.values():
            tag = (c.designator or "").strip()
            sym = c.symbol or ""
            if not tag:
                continue
            if key == SENSES:
                if sym.startswith("fl.") and (".cyl." in sym or ".motor" in sym or ".rotary" in sym or ".pressure." in sym
                                              or ".gauge" in sym):
                    out.add(tag)
            elif key == DRIVEN_BY:
                if sym.startswith("el.motor"):
                    out.add(tag)
            elif sym.startswith("el.coil."):
                out.add(tag)
    return sorted(out)
