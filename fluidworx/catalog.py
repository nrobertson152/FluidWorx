"""What each OpenSchematix fluid symbol does in the simulation.

Every built-in `fl.*` symbol that has connection points is listed here; tests/test_catalog.py fails if a new
OpenSchematix symbol is not. "approx" marks parts modelled more simply than the real component, and the Checks
panel says so rather than presenting the result as if it were exact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Spec:
    kind: str
    options: dict = field(default_factory=dict)
    approx: str = ""


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    quantity: str           # a unit quantity (units.py), or "choice" with `choices` indexed by the value
    hyd: float
    pneu: float
    hint: str = ""
    minimum: float = 0.0
    maximum: float = float("inf")
    choices: tuple = ()


BAR, LPM, MM = 1e5, 1e-3 / 60, 1e-3

_LOAD_MODE = Param("load_mode", "Load acts", "choice", 0.0, 0.0,
                   "Against motion both ways (friction, a press) or always the same way (a hanging weight).",
                   choices=("Against motion", "Constant direction"))
_CYL = [Param("bore", "Bore", "length", 50 * MM, 32 * MM, minimum=1e-3),
        Param("rod", "Rod", "length", 28 * MM, 12 * MM),
        Param("stroke", "Stroke", "length", 200 * MM, 100 * MM, minimum=1e-3),
        Param("load", "Load", "force", 2000.0, 50.0, "For a constant-direction load, positive resists extending.",
              minimum=-1e9),
        _LOAD_MODE,
        Param("mass", "Moving mass", "mass", 50.0, 2.0, minimum=0.01),
        Param("start", "Start position", "percent", 0.0, 0.0, "Where the rod is at reset: 0 = retracted.",
              maximum=100.0)]
_SPRING = [Param("spring", "Return force", "force", 500.0, 60.0, "Spring force at full stroke, or the external force "
                 "that returns a cylinder with no spring.")]
_NO_LOAD = Param("load", "Load", "force", 0.0, 0.0, "For a constant-direction load, positive resists extending.",
                 minimum=-1e9)
_ROT = [Param("displacement", "Displacement", "displacement", 25e-6, 50e-6, minimum=1e-8),
        Param("torque", "Load torque", "torque", 10.0, 1.0, minimum=-1e7), _LOAD_MODE,
        Param("inertia", "Inertia", "inertia", 0.02, 0.002, minimum=1e-5)]
_SET = Param("setting", "Setting", "pressure", 160 * BAR, 6 * BAR, minimum=1e3)
_THROTTLE = Param("opening", "Opening", "percent", 10.0, 40.0, "How far the valve is open.", maximum=100.0)

PARAMS: dict[str, list[Param]] = {
    "pump": [Param("flow", "Flow", "flow", 10 * LPM, 200 * LPM, minimum=1e-7)],
    "pump_pc": [Param("flow", "Max flow", "flow", 20 * LPM, 200 * LPM, minimum=1e-7),
                Param("setting", "Compensator", "pressure", 160 * BAR, 6 * BAR, minimum=1e3)],
    "compressor": [Param("setting", "Supply pressure", "pressure", 7 * BAR, 7 * BAR, minimum=1e3),
                   Param("flow", "Max flow", "flow", 200 * LPM, 200 * LPM, minimum=1e-7)],
    "cylinder": _CYL,
    "cylinder_single": [_CYL[0], _CYL[2], _NO_LOAD, _LOAD_MODE, _CYL[5], _CYL[6]] + _SPRING,
    "cylinder_equal": _CYL,
    "motor": _ROT,
    "rotary": _ROT + [Param("angle", "Rotation", "angle", 3.1416, 3.1416, minimum=0.01)],
    "relief": [_SET],
    "sequence": [_SET],
    "unloading": [_SET],
    "reducer": [Param("setting", "Setting", "pressure", 50 * BAR, 4 * BAR, minimum=1e3)],
    "check": [Param("crack", "Cracking pressure", "pressure", 0.2 * BAR, 0.1 * BAR)],
    "pilot_check": [Param("crack", "Cracking pressure", "pressure", 0.2 * BAR, 0.1 * BAR),
                    Param("ratio", "Pilot ratio", "ratio", 3.0, 3.0, "Pilot pressure × ratio must exceed the "
                          "load-side pressure to open.", minimum=0.1)],
    "throttle": [_THROTTLE],
    "oneway": [_THROTTLE],
    "flow_pc": [Param("flow", "Flow setting", "flow", 5 * LPM, 50 * LPM, minimum=1e-8)],
    "prop": [Param("opening", "Opening", "percent", 50.0, 50.0, maximum=100.0)],
    "accumulator": [Param("volume", "Gas volume", "volume", 1e-3, 1e-3, minimum=1e-6),
                    Param("precharge", "Precharge", "pressure", 80 * BAR, 3 * BAR)],
    "receiver": [Param("volume", "Volume", "volume", 20e-3, 20e-3, minimum=1e-6)],
    "pressure_switch": [Param("setting", "Switching pressure", "pressure", 100 * BAR, 4 * BAR)],
    "dcv": [Param("pilot", "Pilot shift pressure", "pressure", 5 * BAR, 2 * BAR,
                  "Pressure at a pilot port that shifts the valve.")],
}

SYMBOL_APPROX_PAIRS = "Modelled as separate open passages; proportional splitting is not modelled."

# First match wins; the pattern is applied to the id without "fl.hyd." / "fl.pneu.".
_RULES: list[tuple[str, Spec]] = [
    # valve operators drawn on their own are drafting; a pilot port on one leads nowhere
    (r"op\.", Spec("plug")),
    (r"pump\.(pc)(\.full)?$", Spec("pump_pc")),
    (r"pump\.pc\.bidir(\.full)?$", Spec("pump_pc", {"bidir": True})),
    (r"pump(\.ansi)?$", Spec("pump")),
    (r"pump\.var(\.ansi|\.full)?$", Spec("pump")),
    (r"pump(\.var)?\.bidir(\.full|\.drain)?$", Spec("pump", {"bidir": True})),
    (r"pumpmotor\.bidir\.pc(\.full)?$", Spec("pump_pc", {"bidir": True},
                                             "Pump-motor is modelled as a pump only; it does not motor.")),
    (r"pumpmotor(\.rev)?(\.full)?$", Spec("pump", {"bidir": True},
                                          "Pump-motor is modelled as a pump only; it does not motor.")),
    (r"compressor(\.ansi)?$", Spec("compressor")),
    (r"vacuumpump$", Spec("pump", {}, "Vacuum is limited to about -1 bar; it is modelled as a small pump.")),
    (r"cyl\.(single|tele\.single)$", Spec("cylinder_single", {"spring": True})),
    (r"cyl\.single\.ret(\.ansi)?$", Spec("cylinder_single", {"spring": False})),
    (r"cyl\.doublerod(\.ansi)?$", Spec("cylinder_equal")),
    (r"cyl\.tele\.double$", Spec("cylinder", {}, "Telescopic stages are modelled as one equivalent bore.")),
    (r"cyl\.", Spec("cylinder")),
    (r"motor(\.|$)", Spec("motor")),
    (r"rotary(\.ansi)?$", Spec("rotary")),
    (r"relief", Spec("relief")),
    (r"unloading\.sol$", Spec("relief", {"vent": True})),
    (r"unloading$", Spec("unloading")),
    (r"sequence", Spec("sequence")),
    (r"reducing\.relieving$", Spec("reducer", {"relieving": True})),
    (r"regulator\.relieving$", Spec("reducer", {"relieving": True})),
    (r"reducing|regulator", Spec("reducer")),
    (r"check(\.spring)?$", Spec("check")),
    (r"check\.pilot(\.drain)?$", Spec("pilot_check")),
    (r"check\.pilotclose$", Spec("pilot_check", {"to_close": True})),
    (r"shuttle$|doublecheck", Spec("shuttle")),
    (r"valve\.3way\.twopressure$", Spec("shuttle")),
    (r"throttle", Spec("throttle")),
    (r"flow\.oneway", Spec("oneway")),
    (r"flow\.(pc|tpc)\.bypass$", Spec("flow_pc")),
    (r"flow\.3way$", Spec("flow_pc", {"no_bypass": True}, "The excess-flow path to tank is not modelled.")),
    (r"flow\.3way\.check", Spec("flow_pc", {}, "The excess-flow path to tank is not modelled.")),
    (r"lowering\.check$", Spec("oneway", {"free": "reverse"})),
    (r"dcv$", Spec("dcv")),
    (r"dcv\.seated$", Spec("switched", {"states": [[("A", "T", "line")], [("P", "A", "line")]],
                                        "labels": ["Spring: A→T", "Energised: P→A"]})),
    (r"sol\.check\.no$", Spec("switched", {"states": [[("1", "2", "line")], [("2", "1", "check")]],
                                           "labels": ["Open", "Check: 2→1 only"]})),
    (r"sol\.check\.nc$", Spec("switched", {"states": [[("2", "1", "check")], [("1", "2", "line")]],
                                           "labels": ["Check: 2→1 only", "Open"]})),
    (r"diverter6$", Spec("switched", {"states": [[("P", "A1", "line"), ("T", "B1", "line")],
                                                 [("P", "A2", "line"), ("T", "B2", "line")]],
                                      "labels": ["Circuit 1", "Circuit 2"]})),
    (r"logic$", Spec("switched", {"states": [[], [("A", "B", "line")]], "labels": ["Closed", "Open"]})),
    (r"shutoff", Spec("switched", {"states": [[("1", "2", "line")], []], "labels": ["Open", "Closed"]})),
    (r"valve\.2way\.prop\.nc$", Spec("prop", {"default": 0.0})),
    (r"valve\.2way\.prop\.no$", Spec("prop", {"default": 100.0})),
    (r"valve\.prop\.nc$", Spec("prop", {"default": 0.0})),
    (r"valve\.prop\.no$", Spec("prop", {"default": 100.0})),
    (r"valve\.3way\.distributor$", Spec("switched_ports", {"labels": ["Outlet 1", "Outlet 2"]})),
    (r"accumulator", Spec("accumulator")),
    (r"receiver\.ansi$", Spec("receiver", {"inline": True})),
    (r"receiver$", Spec("receiver")),
    (r"tank|manifold\.vented", Spec("tank")),
    (r"exhaust|silencer|breather", Spec("tank")),
    (r"qd\..*\.apart$", Spec("plug")),
    (r"port\.(closed|plugged)$", Spec("plug")),
    (r"pressure\.switch", Spec("pressure_switch")),
    (r"gauge\.diff$", Spec("gauge", {"differential": True})),
    (r"gauge$|pressure\.(indicator|transducer)", Spec("gauge")),
    (r"thermometer$|level\.|flow\.indicator$", Spec("gauge", {"no_reading": True})),
    (r"nozzle$", Spec("nozzle")),
    (r"divider\.spool$", Spec("passage", {"pairs": [(0, 1), (0, 2)]}, SYMBOL_APPROX_PAIRS)),
    (r"divider\.rotary$", Spec("passage", {"pairs": [(0, 2), (1, 3)]}, SYMBOL_APPROX_PAIRS)),
    (r"priority$", Spec("passage", {"pairs": [(0, 1), (0, 2)]}, SYMBOL_APPROX_PAIRS)),
    (r"rotaryunion\.ansi$", Spec("passage", {"pairs": [(0, 1), (2, 3), (4, 5)]})),
    (r"(heater|cooler\.lines|tempcontrol)\.(liquid|gas)$", Spec("passage", {"pairs": [(0, 1), (2, 3)]})),
    (r"flowmeter", Spec("passage", {"meter": True})),
    (r"hose|filter|heater|cooler|conditioner|tempcontrol|separator|filtersep|dryer|lubricator|frl|flowdir|"
     r"testpoint|rotaryunion|qd\.|venturi|orificeplate|pitot", Spec("passage")),
    (r"intensifier$|servopositioner$", Spec("unsupported")),
]
_COMPILED = [(re.compile(p), s) for p, s in _RULES]

UNSUPPORTED = Spec("unsupported")


def medium_of(symbol_id: str) -> str | None:
    if symbol_id.startswith("fl.hyd."):
        return "hyd"
    if symbol_id.startswith("fl.pneu."):
        return "pneu"
    return None


def classify(symbol_id: str) -> Spec:
    """Behaviour of a symbol. Unknown fluid symbols (custom symbols included) are unsupported, not guessed."""
    if medium_of(symbol_id) is None:
        return UNSUPPORTED
    key = symbol_id.split(".", 2)[2]
    for rx, spec in _COMPILED:
        if rx.match(key):
            return spec
    return UNSUPPORTED


def defaults(kind: str, medium: str) -> dict:
    return {p.key: (p.hyd if medium == "hyd" else p.pneu) for p in PARAMS.get(kind, [])}


KIND_NAMES = {
    "pump": "Pump", "pump_pc": "Pressure-compensated pump", "compressor": "Air supply", "cylinder": "Cylinder",
    "cylinder_single": "Single-acting cylinder", "cylinder_equal": "Double-rod cylinder", "motor": "Motor",
    "rotary": "Rotary actuator", "relief": "Relief valve", "sequence": "Sequence valve",
    "unloading": "Unloading valve", "reducer": "Pressure reducing valve", "check": "Check valve",
    "pilot_check": "Pilot-operated check valve", "shuttle": "Shuttle valve", "throttle": "Throttle",
    "oneway": "One-way flow control", "flow_pc": "Compensated flow control", "dcv": "Directional valve",
    "switched": "Two-state valve", "switched_ports": "Two-state valve", "prop": "Proportional valve",
    "accumulator": "Accumulator", "receiver": "Air receiver", "tank": "Tank / exhaust", "plug": "Closed port",
    "gauge": "Instrument", "pressure_switch": "Pressure switch", "passage": "Inline component",
    "nozzle": "Nozzle", "unsupported": "Not simulated",
}
