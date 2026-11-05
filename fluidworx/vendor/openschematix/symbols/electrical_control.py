"""Control-panel devices: the PLC block, position and pressure switches, sensors, timers and solenoid coils.

These are what tie an electrical sheet to a fluid sheet. A coil tagged Y1 is the solenoid of the valve tagged Y1, a
pressure-switch contact tagged S3 belongs to the pressure switch S3 on the hydraulic sheet, and so on: drawings
already work this way, and FluidWorx simulates them that way. See docs/PLC.md and FluidWorx's docs/ELECTRICAL.md.

Contacts follow el.contact.*.iec: terminals at x = -20 and +20, blade from (-8, 0). Devices with a supply pin have
+ and - on the left, the signal on the right.
"""
from __future__ import annotations

from ..plc.program import addresses, default_params, do_type, tags_of
from .base import IEC, Geometry, SymbolDef, Terminal as T, line, poly, polyline, rect, text

E = "Electrical"
EL = "Electronic"
PLC_ID = "el.plc"
PITCH = 20                  # grid units between neighbouring pins
HALF_W = 60                 # half the width of the block body
LEAD = 20
MAX_TAG_CHARS = 11


def _no():
    return [line(-20, 0, -8, 0), line(8, 0, 20, 0), line(-8, 0, 10, -8)]


def _nc():
    return [line(-20, 0, -8, 0), line(8, 0, 20, 0), line(8, 0, 8, 6), line(-8, 0, 11, 6.5)]


def _two(prims):
    return Geometry(prims, [T("1", -20, 0, "l"), T("2", 20, 0, "r")])


def _limit_mark(x, y):
    """The wedge of a position switch, resting on the blade."""
    return [line(x, y, x, y - 5, w="thin"), poly(x - 4, y - 5, x + 4, y - 5, x, y - 11)]


def _pressure_mark(x, y):
    return [line(x, y, x, y - 6, dash=True, w="thin"), rect(x - 6, y - 16, x + 6, y - 6), text(x, y - 11, "P", size=7)]


def _selector_mark(x, y):
    """A latching, hand-turned operator: the contact stays where it is put."""
    return [line(x, y, x, y - 8, dash=True, w="thin"), polyline([(x - 6, y - 13), (x - 2, y - 13), (x - 2, y - 8),
                                                                (x + 5, y - 8)])]


def _estop_mark(x, y):
    return [line(x, y, x, y - 12, dash=True, w="thin"),
            polyline([(x - 8, y - 12), (x + 8, y - 12), (x + 5, y - 17), (x - 5, y - 17), (x - 8, y - 12)])]


def _coil_body():
    return [line(0, -20, 0, -6), line(0, 6, 0, 20), rect(-10, -6, 10, 6)]


def _coil_terms():
    return [T("A1", 0, -20, "u"), T("A2", 0, 20, "d")]


def _pole(i):
    y = (i - 1) * 20
    return [line(-20, y, -8, y), line(8, y, 20, y), line(-8, y, 10, y - 8)]


def _poles_terms():
    return [T(str(2 * i + 1), -20, (i - 1) * 20, "l") for i in range(3)] + [T(str(2 * i + 2), 20, (i - 1) * 20, "r")
                                                                              for i in range(3)]


def _short(tag: str) -> str:
    return tag if len(tag) <= MAX_TAG_CHARS else tag[:MAX_TAG_CHARS - 1] + "…"


def build_plc(params) -> Geometry:
    """A block with its inputs down the left and outputs down the right, sized to its I/O and showing its tags. Pins
    keep their names (I0, Q0, AI0, AO0, L+, M) however the block is configured, so wires stay attached."""
    a = addresses(params)
    tags = tags_of(params)
    left = a["di"] + a["ai"]
    right = a["do"] + a["ao"]
    rows = max(len(left), len(right), 2)
    top = -(rows - 1) * PITCH // 2 - 20
    bottom = -top
    prims = [rect(-HALF_W, top, HALF_W, bottom), text(0, top + 8, "PLC", size=8)]
    terms = []
    y0 = -(rows - 1) * PITCH // 2
    x = HALF_W + LEAD
    for i, name in enumerate(left):
        y = y0 + i * PITCH
        prims.append(line(-x, y, -HALF_W, y))
        terms.append(T(name, -x, y, "l", ptype="elec.input"))
        prims.append(text(-HALF_W + 3, y, f"{name} {_short(tags[name])}" if name in tags else name, size=6, anchor="w"))
    for i, name in enumerate(right):
        y = y0 + i * PITCH
        prims.append(line(HALF_W, y, x, y))
        terms.append(T(name, x, y, "r", ptype="elec.output"))
        prims.append(text(HALF_W - 3, y, f"{_short(tags[name])} {name}" if name in tags else name, size=6, anchor="e"))
    power_y = top - LEAD
    prims += [line(-30, power_y, -30, top), text(-30, top + 7, "L+", size=6), line(0, bottom, 0, bottom + LEAD),
              text(0, bottom - 7, "M", size=6)]
    terms.append(T("L+", -30, power_y, "u", ptype="elec.power"))
    terms.append(T("M", 0, bottom + LEAD, "d", ptype="elec.ground"))
    if do_type(params) == "relay":
        prims += [line(30, power_y, 30, top), text(30, top + 7, "C", size=6)]
        terms.append(T("C", 30, power_y, "u", ptype="elec.passive"))
    return Geometry(prims, terms)


def symbols():
    s = []
    add = s.append
    # ---------------------------------------------------------------- the PLC
    add(SymbolDef(PLC_ID, "PLC (programmable controller)", E, "Control", IEC,
                  "Programmable logic controller: set its inputs and outputs, then program it in ladder, function "
                  "blocks, sequential function chart, structured text, C or Python. L+ and M are its supply; inputs "
                  "are I0, I1, ..., outputs Q0, Q1, ..., analog AI0, ... and AO0, ...", "PLC",
                  builder=build_plc, default_params=default_params(),
                  keywords=("plc", "controller", "ladder", "structured text", "sfc", "fbd", "programmable", "cpu")))
    # ---------------------------------------------------------------- switches operated by the machine
    G = "Control"
    add(SymbolDef("el.switch.limit.no", "Position switch, make (NO)", E, G, IEC,
                  "Position (limit) switch, normally open: operated by the machine.", "S",
                  _two(_no() + _limit_mark(1, -4)), keywords=("limit switch", "position", "cam", "roller", "no")))
    add(SymbolDef("el.switch.limit.nc", "Position switch, break (NC)", E, G, IEC,
                  "Position (limit) switch, normally closed: operated by the machine.", "S",
                  _two(_nc() + _limit_mark(1, 3)), keywords=("limit switch", "position", "cam", "roller", "nc")))
    add(SymbolDef("el.switch.pressure.no", "Pressure switch contact, make (NO)", E, G, IEC,
                  "Contact of a pressure switch, normally open. Give it the tag of the pressure switch on the fluid "
                  "sheet.", "S", _two(_no() + _pressure_mark(1, -4)), keywords=("pressostat", "pressure", "no")))
    add(SymbolDef("el.switch.pressure.nc", "Pressure switch contact, break (NC)", E, G, IEC,
                  "Contact of a pressure switch, normally closed. Give it the tag of the pressure switch on the "
                  "fluid sheet.", "S", _two(_nc() + _pressure_mark(1, 3)), keywords=("pressostat", "pressure", "nc")))
    # ---------------------------------------------------------------- switches operated by hand
    add(SymbolDef("el.switch.selector.no", "Selector switch, make (NO)", E, G, IEC,
                  "Hand-operated switch that stays where it is put, normally open.", "S",
                  _two(_no() + _selector_mark(1, -4)), keywords=("selector", "toggle", "maintained", "latching", "no")))
    add(SymbolDef("el.switch.selector.nc", "Selector switch, break (NC)", E, G, IEC,
                  "Hand-operated switch that stays where it is put, normally closed.", "S",
                  _two(_nc() + _selector_mark(1, 3)), keywords=("selector", "toggle", "maintained", "latching", "nc")))
    add(SymbolDef("el.estop", "Emergency stop", E, G, IEC,
                  "Emergency stop, normally closed: stays open once pushed, until it is released.", "S",
                  _two(_nc() + _estop_mark(1, 3)), keywords=("e-stop", "estop", "emergency", "mushroom", "safety")))
    # ---------------------------------------------------------------- sensors
    sensor = [rect(-20, -20, 20, 20), line(-30, -10, -20, -10), line(-30, 10, -20, 10), line(20, 0, 30, 0),
              text(-14, -10, "+", size=7), text(-14, 10, "-", size=7)]
    pins = [T("+", -30, -10, "l", ptype="elec.power"), T("-", -30, 10, "l", ptype="elec.ground"),
            T("OUT", 30, 0, "r", ptype="elec.output")]
    diamond = [poly(2, -12, 12, -2, 2, 8, -8, -2)]
    add(SymbolDef("el.sensor.prox.pnp", "Proximity sensor, PNP", EL, "Sensors", IEC,
                  "Three-wire proximity sensor, PNP: OUT goes to + when it senses its target.", "B",
                  Geometry(sensor + diamond + [text(2, -2, "PNP", size=5)], list(pins)),
                  keywords=("proximity", "inductive", "reed", "position", "sensor")))
    add(SymbolDef("el.sensor.prox.npn", "Proximity sensor, NPN", EL, "Sensors", IEC,
                  "Three-wire proximity sensor, NPN: OUT goes to - when it senses its target.", "B",
                  Geometry(sensor + diamond + [text(2, -2, "NPN", size=5)], list(pins)),
                  keywords=("proximity", "inductive", "reed", "position", "sensor")))
    add(SymbolDef("el.sensor.analog", "Analog sensor, three-wire", EL, "Sensors", IEC,
                  "Sensor or transmitter with an analog output: 0-10 V unless its label says otherwise. Give it the "
                  "tag of the transducer on the fluid sheet.", "B",
                  Geometry(sensor + [text(2, -6, "A", size=8), text(2, 6, "V/mA", size=5)], list(pins)),
                  keywords=("transducer", "transmitter", "pressure", "position", "0-10", "4-20", "sensor")))
    add(SymbolDef("el.sensor.loop", "Analog sensor, two-wire (4-20 mA)", EL, "Sensors", IEC,
                  "Loop-powered transmitter: draws 4-20 mA from + to -, in line with the input that reads it. Give "
                  "it the tag of the transducer on the fluid sheet.", "B",
                  Geometry([rect(-14, -14, 14, 14), line(-20, 0, -14, 0), line(14, 0, 20, 0), text(0, -5, "4-20", size=5),
                            text(0, 4, "mA", size=5), text(-9, -9, "+", size=6)],
                           [T("+", -20, 0, "l", ptype="elec.passive"), T("-", 20, 0, "r", ptype="elec.passive")]),
                  keywords=("transducer", "transmitter", "loop powered", "4-20", "sensor")))
    # ---------------------------------------------------------------- coils
    add(SymbolDef("el.coil.valve", "Solenoid valve coil", E, G, IEC,
                  "Coil of a solenoid valve. Give it the tag of the valve on the fluid sheet: Y1, or Y1a and Y1b for "
                  "the two solenoids of a double-solenoid valve.", "Y",
                  Geometry(_coil_body() + [line(-10, 6, 10, -6)], _coil_terms()),
                  keywords=("solenoid", "valve", "coil", "actuator")))
    slow_op = [rect(-20, -6, -10, 6), line(-20, -6, -10, 6), line(-20, 6, -10, -6)]
    add(SymbolDef("el.coil.ondelay", "Timer relay coil, on-delay", E, G, IEC,
                  "Relay coil that operates its contacts after a delay. Write the time in its label, e.g. 5 s.", "KT",
                  Geometry(_coil_body() + slow_op, _coil_terms()), keywords=("timer", "ton", "delay", "relay", "time")))
    slow_rel = [rect(-20, -6, -10, 6, fill=True)]
    add(SymbolDef("el.coil.offdelay", "Timer relay coil, off-delay", E, G, IEC,
                  "Relay coil that holds its contacts for a delay after it drops out. Write the time in its label, "
                  "e.g. 5 s.", "KT", Geometry(_coil_body() + slow_rel, _coil_terms()),
                  keywords=("timer", "tof", "delay", "relay", "time")))
    # ---------------------------------------------------------------- three-phase power
    link3 = [line(1, -24, 1, 16, dash=True, w="thin")]
    add(SymbolDef("el.contact.3no", "Main contacts, three-pole", E, "Power", IEC,
                  "Three make contacts of a contactor (1-2, 3-4, 5-6). Give it the tag of the contactor's coil.", "K",
                  Geometry(_pole(0) + _pole(1) + _pole(2) + link3, _poles_terms()),
                  keywords=("contactor", "three phase", "3ph", "power", "starter")))
    cross = []
    for i in range(3):
        y = (i - 1) * 20
        cross += [line(5, y - 3, 11, y + 3), line(5, y + 3, 11, y - 3)]
    add(SymbolDef("el.breaker.3p", "Circuit breaker, three-pole", E, "Protection", IEC,
                  "Three-pole circuit breaker (1-2, 3-4, 5-6).", "Q",
                  Geometry(_pole(0) + _pole(1) + _pole(2) + cross + link3, _poles_terms()),
                  keywords=("mcb", "mccb", "breaker", "three phase", "3ph")))
    heaters = []
    for i in range(3):
        y = (i - 1) * 20
        heaters += [polyline([(-20, y), (-6, y), (-6, y - 5), (6, y - 5), (6, y), (20, y)])]
    add(SymbolDef("el.overload.3p", "Thermal overload relay, three-pole", E, "Protection", IEC,
                  "Thermal overload heaters (1-2, 3-4, 5-6). Its normally closed trip contact is an el.contact.nc.iec "
                  "with the same tag. Write the setting in its rating, e.g. 2.5 A.", "F",
                  Geometry(heaters + [rect(-10, -27, 10, 22, dash=True)], _poles_terms()),
                  keywords=("overload", "thermal", "heater", "motor protection", "three phase")))
    add(SymbolDef("el.psu", "Power supply, AC to DC", E, "Sources", IEC,
                  "Power supply unit: mains on L and N, DC out on + and -. Write the output in its label, e.g. 24 V.", "G",
                  Geometry([rect(-20, -20, 20, 20), line(-20, 20, 20, -20), line(-30, -10, -20, -10), line(-30, 10, -20, 10),
                            line(20, -10, 30, -10), line(20, 10, 30, 10), text(-11, -10, "~", size=8),
                            text(11, 10, "=", size=8)],
                           [T("L", -30, -10, "l", ptype="elec.power"), T("N", -30, 10, "l", ptype="elec.passive"),
                            T("+", 30, -10, "r", ptype="elec.output"), T("-", 30, 10, "r", ptype="elec.passive")]),
                  keywords=("psu", "power supply", "24v", "smps", "rectifier", "dc")))
    return s


