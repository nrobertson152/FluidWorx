"""What each OpenSchematix symbol does in the simulation.

Every built-in `fl.*` and `el.*` symbol that has connection points is listed here; tests/test_catalog.py fails if a
new OpenSchematix symbol is not. "approx" marks parts modelled more simply than the real component, and the Checks
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


# ---------------------------------------------------------------- electrical and electronic parts
def _E(key, label, quantity, value, hint="", minimum=0.0, maximum=float("inf"), choices=()):
    return Param(key, label, quantity, value, value, hint, minimum, maximum, choices)


_RATED_V = _E("rated", "Rated voltage", "voltage", 0.0, "0 = the voltage of the circuit it is in.")
_R_ON_DELAY = _E("delay", "Delay", "time", 5.0, "How long after the coil is energised its contacts change.", maximum=86400.0)
_COIL = [_RATED_V, _E("power", "Power", "power", 4.0, "Sets its resistance and so the current it draws.", minimum=1e-3)]
_LOAD = [_RATED_V, _E("power", "Power", "power", 2.0, minimum=1e-3)]
_SOURCE = [_E("voltage", "Voltage", "voltage", 24.0, "RMS for an AC source.", minimum=-1e6),
           _E("limit", "Current limit", "current", 0.0, "A supply folds back to this current. 0 = no limit."),
           _E("rint", "Internal resistance", "resistance", 0.02, minimum=1e-4)]
_MANUAL = _E("manual", "Reads, when nothing drives it", "percent", 0.0, "Where it sits with no link: try different values "
             "while the simulation runs.", maximum=100.0)
_SENSOR_RANGE = [_E("lo", "Range, low", "number", 0.0, "What the sensor's lowest output means: bar for pressure, mm for "
                    "position.", minimum=-1e9),
                 _E("hi", "Range, high", "number", 0.0, "What its highest output means. If both are 0: the whole stroke, or "
                    "the highest pressure setting in the circuit.", minimum=-1e9)]
SENSOR_SIGNALS = ("0-10V", "4-20mA", "0-5V", "0-20mA")
_POSITION = [_E("band", "Operating band", "percent", 1.0, "How near the position it operates, as a share of the stroke.",
                maximum=50.0)]

PARAMS.update({
    "source_v": _SOURCE,
    "source_i": [_E("current", "Current", "current", 0.02, minimum=-1e6)],
    "psu": [_E("voltage", "Output voltage", "voltage", 24.0, minimum=0.0),
            _E("limit", "Current limit", "current", 0.0, "0 = no limit."),
            _E("input_min", "Minimum input", "voltage", 18.0, "Below this at its input it switches off."),
            _E("efficiency", "Efficiency", "percent", 90.0, minimum=1.0, maximum=100.0)],
    "rectifier": [_E("factor", "Output / input", "ratio", 0.9, "0.9 for full-wave into a load, about 1.4 with a smoothing capacitor.",
                     minimum=0.01)],
    "rail": [_E("voltage", "Voltage", "voltage", 24.0, minimum=-1e6)],
    "resistor": [_E("ohms", "Resistance", "resistance", 1000.0, minimum=1e-3)],
    "pot": [_E("ohms", "Resistance", "resistance", 10000.0, minimum=1e-3),
            _E("wiper", "Wiper", "percent", 50.0, "Where the wiper is, from end 1 to end 2.", maximum=100.0)],
    "capacitor": [_E("farads", "Capacitance", "capacitance", 100e-6, minimum=1e-12)],
    "inductor": [_E("henries", "Inductance", "inductance", 10e-3, minimum=1e-9),
                 _E("rdc", "Winding resistance", "resistance", 1.0, minimum=1e-3)],
    "diode": [_E("vf", "Forward voltage", "voltage", 0.7, minimum=0.01),
              _E("rd", "Forward resistance", "resistance", 0.1, minimum=1e-4)],
    "zener": [_E("vz", "Zener voltage", "voltage", 5.1, minimum=0.1), _E("rd", "Resistance", "resistance", 1.0, minimum=1e-4)],
    "led": [_E("vf", "Forward voltage", "voltage", 2.0, minimum=0.1), _E("rd", "Forward resistance", "resistance", 10.0, minimum=1e-3)],
    "bjt": [_E("beta", "Current gain (hFE)", "ratio", 100.0, minimum=1.0), _E("vbe", "Vbe", "voltage", 0.7, minimum=0.1),
            _E("vcesat", "Vce, saturated", "voltage", 0.2, minimum=0.01)],
    "fet": [_E("vth", "Gate threshold", "voltage", 2.5, "The gate-source voltage at which it turns on.", minimum=-100.0),
            _E("rds", "On resistance", "resistance", 0.1, minimum=1e-4)],
    "scr": [_E("igt", "Gate trigger current", "current", 0.01, minimum=1e-6), _E("ih", "Holding current", "current", 0.02, minimum=1e-6)],
    "opamp": [_E("vsat", "Swing without supply pins", "voltage", 13.5, "Output limit when no supply pins are drawn.", minimum=0.1),
              _E("gain", "Open-loop gain", "ratio", 1e5, minimum=1.0)],
    "logic": [_E("vhigh", "Logic high", "voltage", 0.0, "0 = the voltage of the circuit it is in.")],
    "regulator": [_E("voltage", "Output voltage", "voltage", 5.0, minimum=0.0), _E("dropout", "Dropout", "voltage", 2.0)],
    "fuse": [_E("rating", "Rating", "current", 10.0, minimum=1e-3)],
    "breaker": [_E("rating", "Rating", "current", 10.0, minimum=1e-3)],
    "breaker3": [_E("rating", "Rating", "current", 16.0, minimum=1e-3)],
    "overload": [_E("rating", "Setting", "current", 2.5, "It trips on a sustained current above this.", minimum=1e-3)],
    "coil": _COIL,
    "coil_on": _COIL + [_R_ON_DELAY],
    "coil_off": _COIL + [_E("delay", "Delay", "time", 5.0, "How long its contacts hold after the coil drops out.", maximum=86400.0)],
    "relay": _COIL,
    "lamp": _LOAD,
    "buzzer": [_RATED_V, _E("power", "Power", "power", 1.0, minimum=1e-3)],
    "emotor": [_RATED_V, _E("power", "Power", "power", 100.0, "Sets the current it draws when running.", minimum=1e-3)],
    "emotor3": [_E("rated", "Rated line voltage", "voltage", 0.0, "0 = the supply's.", minimum=0.0),
                _E("power", "Power", "power", 3000.0, minimum=1.0)],
    "meter_v": [_E("ohms", "Input resistance", "resistance", 1e7, minimum=1.0)],
    "meter_a": [_E("ohms", "Resistance", "resistance", 0.001, minimum=1e-6)],
    "transformer": [_E("primary", "Primary voltage", "voltage", 230.0, minimum=1e-3), _E("secondary", "Secondary voltage", "voltage", 24.0, minimum=1e-3),
                    _E("rs", "Winding resistance", "resistance", 0.05, minimum=1e-4)],
    "autotransformer": [_E("ratio", "Tap, share of the winding", "percent", 50.0, minimum=0.1, maximum=99.9)],
    "prox": _POSITION,
    "limit": _POSITION,
    "sensor_analog": _SENSOR_RANGE + [_E("signal", "Output", "choice", 0.0, "What it puts out across its range.",
                                         choices=SENSOR_SIGNALS), _MANUAL],
    "sensor_loop": _SENSOR_RANGE + [_MANUAL],
    "plc": [_E("supply", "Rated supply", "voltage", 24.0, "It runs from 75% of this, and stops below 60%.", minimum=1.0),
            _E("power", "Own consumption", "power", 5.0, minimum=1e-3),
            _E("out_rating", "Output rating", "current", 0.5, "More than this on a digital output is reported in Events. 0 = don't check.")],
    "pressure_contact": [],
})

_ELECTRIC_RULES: list[tuple[str, Spec]] = [
    # ---- sources and connections
    (r"plc$", Spec("plc")),
    (r"source\.(dc|v)$|cell$|battery(\.long)?$", Spec("source_v", {"polar": True})),
    (r"source\.ac$", Spec("source_v", {"ac": True}, "An AC source is simulated at its RMS value, as if it were DC.")),
    (r"generator$", Spec("source_v", {"ac": True}, "A generator is simulated as a voltage source.")),
    (r"source\.i(\.dep)?$", Spec("source_i")),
    (r"psu$", Spec("psu", {"pins": ("L", "N", "+", "-")})),
    (r"converter\.acdc$", Spec("psu", {"pins": ("AC1", "AC2", "DC1", "DC2")})),
    (r"rectifier\.(bridge|block)$", Spec("rectifier", {}, "Modelled as a DC output proportional to the AC input.")),
    (r"regulator$", Spec("regulator")),
    (r"earth(\.pe)?$|chassis$|ground\.", Spec("ground")),
    (r"rail\.(pos|neg)$", Spec("rail")),
    (r"connector\.point$|antenna$|connector\.coax$", Spec("point")),
    (r"terminal$", Spec("feedthrough")),
    # ---- passive
    (r"resistor\.|thermistor\.|rheostat\.|trim\.rheostat\.", Spec("resistor")),
    (r"ldr\.", Spec("resistor", {}, "Set its resistance in Properties; light isn't modelled.")),
    (r"potentiometer\.", Spec("pot")),
    (r"capacitor(\.|$)", Spec("capacitor")),
    (r"inductor\.tap$", Spec("inductor", {}, "Modelled between its two ends; the sliding contact isn't.")),
    (r"inductor(\.|$)", Spec("inductor")),
    # ---- semiconductors
    (r"diode\.zener$", Spec("zener")),
    (r"tvs\.bidir$", Spec("zener", {"bidir": True})),
    (r"diac$", Spec("zener", {"bidir": True}, "Modelled as a bidirectional breakdown diode; it doesn't snap back.")),
    (r"led$", Spec("led")),
    (r"diode\.schottky$", Spec("diode", {"vf": 0.3})),
    (r"diode(\.varicap)?$", Spec("diode")),
    (r"photodiode$", Spec("diode", {}, "Modelled as a plain diode; light isn't modelled.")),
    (r"npn$", Spec("bjt", {"polarity": 1})),
    (r"pnp$", Spec("bjt", {"polarity": -1})),
    (r"(npn|pnp)\.photo$", Spec("switch_manual", {"pairs": [("C", "E")]}, "Modelled as a switch: click it to shine light on it.")),
    (r"nmos", Spec("fet", {"polarity": 1})),
    (r"pmos", Spec("fet", {"polarity": -1})),
    (r"jfet\.n$", Spec("fet", {"polarity": 1, "vth": -2.0}, "Modelled as a switch: on unless the gate is pinched off.")),
    (r"jfet\.p$", Spec("fet", {"polarity": -1, "vth": -2.0}, "Modelled as a switch: on unless the gate is pinched off.")),
    (r"scr$", Spec("scr", {"pins": ("A", "K", "G")})),
    (r"triac$", Spec("scr", {"pins": ("MT2", "MT1", "G"), "bidir": True})),
    # ---- integrated
    (r"opamp(\.supply(\.inv)?)?$", Spec("opamp")),
    (r"logic\.(and|nand|or|nor|xor|xnor)\d$", Spec("logic")),
    (r"logic\.(not|schmitt|schmitt\.not|dlatch|dff|jkff|fulladder)$", Spec("logic")),
    # ---- protection
    (r"fuse\.", Spec("fuse")),
    (r"breaker\.iec$", Spec("breaker")),
    (r"breaker\.3p$", Spec("breaker3")),
    (r"overload\.3p$", Spec("overload")),
    # ---- switching
    (r"contact\.3no$", Spec("contact", {"poles": [("1", "2"), ("3", "4"), ("5", "6")], "nc": False})),
    (r"contact\.no\.", Spec("contact", {"poles": [("1", "2")], "nc": False})),
    (r"contact\.nc\.", Spec("contact", {"poles": [("1", "2")], "nc": True})),
    (r"pushbutton\.no\.", Spec("button", {"poles": [("1", "2")], "nc": False})),
    (r"pushbutton\.nc\.", Spec("button", {"poles": [("1", "2")], "nc": True})),
    (r"switch\.selector\.no$", Spec("selector", {"poles": [("1", "2")], "nc": False})),
    (r"switch\.selector\.nc$", Spec("selector", {"poles": [("1", "2")], "nc": True})),
    (r"estop$", Spec("selector", {"poles": [("1", "2")], "nc": True, "estop": True})),
    (r"switch\.dpst$", Spec("selector", {"poles": [("1", "2"), ("3", "4")], "nc": False})),
    (r"switch\.spdt$", Spec("changeover")),
    (r"switch\.rotary4$", Spec("selector4")),
    (r"switch\.limit\.no$", Spec("limit", {"poles": [("1", "2")], "nc": False})),
    (r"switch\.limit\.nc$", Spec("limit", {"poles": [("1", "2")], "nc": True})),
    (r"switch\.pressure\.no$", Spec("pressure_contact", {"poles": [("1", "2")], "nc": False})),
    (r"switch\.pressure\.nc$", Spec("pressure_contact", {"poles": [("1", "2")], "nc": True})),
    (r"sensor\.prox\.pnp$", Spec("prox", {"pnp": True})),
    (r"sensor\.prox\.npn$", Spec("prox", {"pnp": False})),
    (r"sensor\.analog$", Spec("sensor_analog")),
    (r"sensor\.loop$", Spec("sensor_loop")),
    # ---- coils
    (r"coil\.ondelay$", Spec("coil_on")),
    (r"coil\.offdelay$", Spec("coil_off")),
    (r"coil\.", Spec("coil")),
    (r"relay\.(2?no)$", Spec("relay")),
    # ---- loads
    (r"lamp\.", Spec("lamp")),
    (r"buzzer\.", Spec("buzzer")),
    (r"speaker$", Spec("buzzer", {}, "A loudspeaker is a plain load here: sound isn't modelled.")),
    (r"microphone$", Spec("point", {}, "A microphone produces no signal here.")),
    (r"motor\.3ph$", Spec("emotor3")),
    (r"motor(\.dc)?$", Spec("emotor")),
    (r"meter\.v$", Spec("meter_v")),
    (r"meter\.(a|g)$", Spec("meter_a")),
    # ---- transformers
    (r"transformer\.ct(\.inv)?$", Spec("transformer", {"windings": [("S1", "CT", 0.5), ("CT", "S2", 0.5)]})),
    (r"transformer\.2sec$", Spec("transformer", {"windings": [("S1", "S2", 1.0), ("S3", "S4", 1.0)]})),
    (r"transformer\.inv(\.step)?$", Spec("transformer", {"windings": [("S2", "S1", 1.0)]})),
    (r"transformer(\.dot(\.step)?)?$", Spec("transformer", {"windings": [("S1", "S2", 1.0)]})),
    (r"autotransformer(\.core)?$", Spec("autotransformer")),
]
_E_COMPILED = [(re.compile(p), s) for p, s in _ELECTRIC_RULES]
NOT_SIMULATED_ELECTRIC = re.compile(r"tube\.")


def medium_of(symbol_id: str) -> str | None:
    if symbol_id.startswith("fl.hyd."):
        return "hyd"
    if symbol_id.startswith("fl.pneu."):
        return "pneu"
    if symbol_id.startswith("el."):
        return "el"
    return None


def classify(symbol_id: str) -> Spec:
    """Behaviour of a symbol. Unknown symbols (custom symbols included) are unsupported, not guessed."""
    medium = medium_of(symbol_id)
    if medium is None:
        return UNSUPPORTED
    if medium == "el":
        key = symbol_id[3:]
        for rx, spec in _E_COMPILED:
            if rx.match(key):
                return spec
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
    "plc": "PLC", "source_v": "Voltage source", "source_i": "Current source", "psu": "Power supply", "rectifier": "Rectifier",
    "regulator": "Voltage regulator", "ground": "Ground", "rail": "Supply rail", "point": "Connection point",
    "feedthrough": "Terminal", "resistor": "Resistor", "pot": "Potentiometer", "capacitor": "Capacitor", "inductor": "Inductor",
    "zener": "Breakdown diode", "led": "LED", "diode": "Diode", "bjt": "Bipolar transistor", "fet": "Field-effect transistor",
    "scr": "Thyristor", "opamp": "Operational amplifier", "logic": "Logic", "fuse": "Fuse", "breaker": "Circuit breaker",
    "breaker3": "Circuit breaker, three-pole", "overload": "Thermal overload", "contact": "Contact", "button": "Push-button",
    "selector": "Switch", "changeover": "Changeover switch", "selector4": "Selector switch", "limit": "Position switch",
    "pressure_contact": "Pressure switch contact", "switch_manual": "Switch", "prox": "Proximity sensor",
    "sensor_analog": "Analog sensor", "sensor_loop": "Analog sensor, 4-20 mA", "coil": "Coil", "coil_on": "Timer relay, on-delay",
    "coil_off": "Timer relay, off-delay", "relay": "Relay", "lamp": "Lamp", "buzzer": "Sounder", "emotor": "Electric motor",
    "emotor3": "Three-phase motor", "meter_v": "Voltmeter", "meter_a": "Ammeter", "transformer": "Transformer",
    "autotransformer": "Autotransformer",
}
