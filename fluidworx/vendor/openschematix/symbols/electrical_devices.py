"""Transformers, switches and relays (symbol-library expansion, batches E5 and E6).

Source: ECL = "Electric Components Library" (ElCompLib2017.svg, CC0 1.0), sections "Transformers" and
"Mechanical switches"; batch E8 adds the "Other things", "Semiconductor devices" and "Vacuum tubes" items.
Redrawn natively:
* Transformers follow the existing el.transformer (windings of 3-unit humps facing the core, core lines at
  x = +-1.5, primary P1/P2 on the left, secondary S1/S2 on the right). Polarity dots mark the winding ends that
  are in phase.
* Switches are drawn as in the source, with open terminal circles. Relay contacts are numbered 13-14, 23-24
  (make contacts) and coils A1-A2, as in IEC 61810 / EN 50005; the mechanical link is drawn dashed.
"""
from __future__ import annotations

import math

from .base import IEC, IEEE, Geometry, SymbolDef, Terminal as T, arc, arrowhead, circle, line, poly, polyline, rect, text

E = "Electrical"
IEC_IEEE = IEC + " / " + IEEE.split(" /")[0]


# ---------------------------------------------------------------------------------------------- transformers
def winding(side, y0, n):
    """n humps between y0 and y0 + 6n; side -1 = primary (left, x = -6), +1 = secondary (right, x = +6)."""
    x = 6 * side
    return [arc(x, y0 + 3 + 6 * i, 3, 90, 180 * side) for i in range(n)]


def lead(side, y_term, y_wind):
    x = 6 * side
    return [polyline([(20 * side, y_term), (x, y_term), (x, y_wind)])]


def dot(x, y):
    return circle(x, y, 1.8, fill=True, w="thin")


def core(y0=-14, y1=14):
    return [line(-1.5, y0, -1.5, y1), line(1.5, y0, 1.5, y1)]


def primary(n=4):
    h = 3 * n
    return winding(-1, -h, n) + lead(-1, -20, -h) + lead(-1, 20, h)


def secondary(n=4, top=-20, bottom=20):
    h = 3 * n
    return winding(1, -h, n) + lead(1, top, -h) + lead(1, bottom, h)


PS = [T("P1", -20, -20, "l"), T("P2", -20, 20, "l"), T("S1", 20, -20, "r"), T("S2", 20, 20, "r")]


# ---------------------------------------------------------------------------------------------- switches
def tcircle(x, y):
    return circle(x, y, 3)


def make(y, left=-20, right=20):
    """Open make contact between terminal circles at x = -10 and +10 on height y."""
    return [line(left, y, -13, y), tcircle(-10, y), line(-7.4, y - 1.5, 10, y - 9), tcircle(10, y), line(13, y, right, y)]


def coil(y):
    return [rect(-6, y - 8, 6, y + 8), line(-20, y, -6, y), line(6, y, 20, y)]


def link(y0, y1):
    return [line(0, y0, 0, y1, dash=True, w="thin")]


def symbols():
    s = []
    add = s.append
    # ---------------------------------------------------------------- E5: transformers
    std = primary() + secondary() + core()
    add(SymbolDef("el.transformer.dot", "Transformer with polarity dots (in phase)", E, "Power", IEC_IEEE,
                  "Two-winding transformer, iron core; the dotted ends P1 and S1 are in phase.", "T",
                  Geometry(std + [dot(-11, -14), dot(11, -14)], list(PS)), keywords=("xfmr", "polarity")))
    add(SymbolDef("el.transformer.inv", "Transformer with polarity dots (inverting)", E, "Power", IEC_IEEE,
                  "Two-winding transformer, iron core; the dotted ends P1 and S2 are in phase (inverting).", "T",
                  Geometry(std + [dot(-11, -14), dot(11, 14)], list(PS)), keywords=("xfmr", "polarity")))
    step = primary() + secondary(2, -20, 20) + core()
    add(SymbolDef("el.transformer.dot.step", "Transformer, step-down, polarity dots (in phase)", E, "Power",
                  IEC_IEEE, "Transformer drawn with fewer secondary turns (step-down); P1 and S1 in phase.", "T",
                  Geometry(step + [dot(-11, -14), dot(11, -8)], list(PS)), keywords=("xfmr", "polarity")))
    add(SymbolDef("el.transformer.inv.step", "Transformer, step-down, polarity dots (inverting)", E, "Power",
                  IEC_IEEE, "Transformer drawn with fewer secondary turns (step-down); P1 and S2 in phase.", "T",
                  Geometry(step + [dot(-11, -14), dot(11, 8)], list(PS)), keywords=("xfmr", "polarity")))
    ct = primary() + winding(1, -18, 6) + lead(1, -20, -18) + lead(1, 20, 18) + [line(6, 0, 20, 0)] + core(-18, 18)
    cterms = [T("P1", -20, -20, "l"), T("P2", -20, 20, "l"), T("S1", 20, -20, "r"), T("CT", 20, 0, "r"),
              T("S2", 20, 20, "r")]
    add(SymbolDef("el.transformer.ct", "Transformer, centre-tapped secondary", E, "Power", IEC_IEEE,
                  "Transformer with centre-tapped secondary (tap CT); P1 and S1 in phase.", "T",
                  Geometry(ct + [dot(-11, -14), dot(11, -18)], list(cterms)), keywords=("xfmr", "centre tap")))
    add(SymbolDef("el.transformer.ct.inv", "Transformer, centre-tapped secondary, inverting dots", E, "Power",
                  IEC_IEEE, "Transformer with centre-tapped secondary (tap CT); P1 and S2 in phase.", "T",
                  Geometry(ct + [dot(-11, -14), dot(11, 18)], list(cterms)), keywords=("xfmr", "centre tap")))
    two = (winding(-1, -18, 6) + lead(-1, -30, -18) + lead(-1, 30, 18)
           + winding(1, -24, 2) + lead(1, -30, -24) + lead(1, -10, -12)
           + winding(1, 12, 2) + lead(1, 10, 12) + lead(1, 30, 24) + core(-26, 26)
           + [dot(-11, -18), dot(11, -24), dot(11, 12)])
    add(SymbolDef("el.transformer.2sec", "Transformer, two secondary windings", E, "Power", IEC_IEEE,
                  "Transformer with two separate secondary windings S1-S2 and S3-S4; dotted ends in phase.", "T",
                  Geometry(two, [T("P1", -20, -30, "l"), T("P2", -20, 30, "l"), T("S1", 20, -30, "r"),
                                 T("S2", 20, -10, "r"), T("S3", 20, 10, "r"), T("S4", 20, 30, "r")]),
                  keywords=("xfmr", "multi winding")))
    auto = [arc(0, -9 + 6 * i, 3, 90, 180) for i in range(4)] + [line(0, -20, 0, -12), line(0, 12, 0, 20),
                                                                  line(0, 0, 20, 0)]
    aterms = [T("1", 0, -20, "u"), T("2", 0, 20, "d"), T("3", 20, 0, "r")]
    add(SymbolDef("el.autotransformer", "Autotransformer", E, "Power", IEC_IEEE,
                  "Autotransformer: single winding 1-2 with tap 3.", "T", Geometry(auto, list(aterms)),
                  keywords=("auto transformer", "tapped winding")))
    add(SymbolDef("el.autotransformer.core", "Autotransformer with core", E, "Power", IEC_IEEE,
                  "Autotransformer with magnetic core: single winding 1-2 with tap 3.", "T",
                  Geometry(auto + [line(-8, -14, -8, 14), line(-5, -14, -5, 14)], list(aterms)),
                  keywords=("auto transformer", "tapped winding")))
    # ---------------------------------------------------------------- E6: switches and relays
    G = "Switching"
    spdt = [line(-20, 0, -13, 0), tcircle(-10, 0), line(-7.2, -1, 8, -7), tcircle(10, -10), line(13, -10, 20, -10),
            tcircle(10, 10), line(13, 10, 20, 10)]
    add(SymbolDef("el.switch.spdt", "Switch, changeover (SPDT)", E, G, IEEE,
                  "Single-pole double-throw switch: common C, contacts A (shown connected) and B.", "S",
                  Geometry(spdt, [T("C", -20, 0, "l"), T("A", 20, -10, "r"), T("B", 20, 10, "r")]),
                  keywords=("changeover", "toggle", "spdt")))
    add(SymbolDef("el.switch.dpst", "Switch, two-pole (DPST)", E, G, IEEE,
                  "Two-pole make switch, poles operated together (dashed link).", "S",
                  Geometry(make(-10) + make(10) + link(-14, 5),
                           [T("1", -20, -10, "l"), T("2", 20, -10, "r"), T("3", -20, 10, "l"), T("4", 20, 10, "r")]),
                  keywords=("double pole", "dpst")))
    add(SymbolDef("el.relay.no", "Relay, coil with one make contact", E, G, IEC_IEEE,
                  "Relay drawn as one unit: coil A1-A2 operating make contact 13-14 (dashed link).", "K",
                  Geometry(make(-20) + link(-24, 2) + coil(10),
                           [T("13", -20, -20, "l"), T("14", 20, -20, "r"), T("A1", -20, 10, "l"), T("A2", 20, 10, "r")]),
                  keywords=("relay", "contactor"),
                  notes="To spread coil and contacts over a diagram, use el.coil.iec and the contact symbols."))
    add(SymbolDef("el.relay.2no", "Relay, coil with two make contacts", E, G, IEC_IEEE,
                  "Relay drawn as one unit: coil A1-A2 operating make contacts 13-14 and 23-24.", "K",
                  Geometry(make(-30) + make(-10) + link(-34, 2) + coil(10),
                           [T("13", -20, -30, "l"), T("14", 20, -30, "r"), T("23", -20, -10, "l"),
                            T("24", 20, -10, "r"), T("A1", -20, 10, "l"), T("A2", 20, 10, "r")]),
                  keywords=("relay", "contactor")))
    rot = [line(-20, 0, -8, 0), circle(-8, 0, 1.8, fill=True, w="thin"), line(-8, 0, 6, -7),
           arrowhead((9.5, -8.6), (-8, 0), length=6, half_width=2.6)]
    for y, x in ((-30, 8), (-10, 12), (10, 12), (30, 8)):
        rot += [tcircle(x, y), line(x + 3, y, 20, y)]
    add(SymbolDef("el.switch.rotary4", "Selector switch, rotary, four positions", E, G, IEEE,
                  "Rotary selector: common C connected to one of the positions 1-4 (shown on 2).", "S",
                  Geometry(rot, [T("C", -20, 0, "l"), T("1", 20, -30, "r"), T("2", 20, -10, "r"), T("3", 20, 10, "r"),
                                 T("4", 20, 30, "r")]), keywords=("selector", "rotary", "wafer")))
    # ---------------------------------------------------------------- E8: other devices
    EL = "Electronic"
    sine = polyline([(-5 + 10 * i / 12, -3 - 2.5 * math.sin(2 * math.pi * i / 12)) for i in range(13)], w="thin")
    dome = [arc(0, 0, 12, 0, 180), line(-12, 0, 12, 0), line(-6, 0, -6, 10), line(6, 0, 6, 10),
            line(-20, 10, -6, 10), line(6, 10, 20, 10)]
    two_b = [T("1", -20, 10, "l"), T("2", 20, 10, "r")]
    add(SymbolDef("el.buzzer.ac", "Buzzer, AC", E, "Signalling", IEC_IEEE, "Buzzer for alternating current.", "H",
                  Geometry(dome + [sine], list(two_b)), keywords=("buzzer", "sounder", "bell")))
    add(SymbolDef("el.buzzer.dc", "Buzzer, DC", E, "Signalling", IEC_IEEE, "Buzzer for direct current.", "H",
                  Geometry(dome + [line(-5, -6, 5, -6, w="thin"), line(-5, -2.5, 5, -2.5, w="thin")], list(two_b)),
                  keywords=("buzzer", "sounder")))
    vert = [T("1", 0, -20, "u"), T("2", 0, 20, "d")]
    for letter, sid, name, desc in (("V", "el.meter.v", "Voltmeter", "Voltmeter."),
                                     ("A", "el.meter.a", "Ammeter", "Ammeter."),
                                     ("G", "el.meter.g", "Galvanometer", "Galvanometer (sensitive current detector).")):
        add(SymbolDef(sid, name, E, "Measuring", IEC_IEEE, desc, "P",
                      Geometry([circle(0, 0, 10), line(0, -20, 0, -10), line(0, 10, 0, 20), text(0, 0, letter, size=9)],
                               list(vert)), keywords=("meter", "measuring", name.lower())))
    add(SymbolDef("el.motor.dc", "Motor, DC, with brushes", E, "Machines", IEC_IEEE,
                  "Direct-current motor; the rectangles are the brushes on the commutator.", "M",
                  Geometry([circle(0, 0, 14), rect(-5, -20, 5, -14), rect(-5, 14, 5, 20), line(0, -30, 0, -20),
                            line(0, 20, 0, 30), text(0, 0, "M", size=11)], [T("1", 0, -30, "u"), T("2", 0, 30, "d")]),
                  keywords=("motor", "dc", "brushed")))
    add(SymbolDef("el.microphone", "Microphone", EL, "Signalling", IEC_IEEE, "Microphone, general symbol.", "B",
                  Geometry([circle(0, 0, 8), line(-9, -12, -9, 12, w="thick"), line(0, -20, 0, -8), line(0, 8, 0, 20)],
                           list(vert)), keywords=("mic", "audio")))
    add(SymbolDef("el.speaker", "Loudspeaker", EL, "Signalling", IEC_IEEE, "Loudspeaker, general symbol.", "B",
                  Geometry([rect(-5, -8, 5, 8), polyline([(5, -8), (14, -16), (14, 16), (5, 8)]), line(0, -20, 0, -8),
                            line(0, 8, 0, 20)], list(vert)), keywords=("speaker", "audio")))
    op = [line(-30, -10, -15, -10), line(-30, 10, -15, 10), line(25, 0, 40, 0), poly(-15, -20, 25, 0, -15, 20),
          line(0, -12.5, 0, -30), line(0, 12.5, 0, 30)]
    for plus_top, sid, nm in ((True, "el.opamp.supply", "+ input on top"), (False, "el.opamp.supply.inv", "- input on top")):
        a, b = ("+", "-") if plus_top else ("-", "+")
        add(SymbolDef(sid, f"Operational amplifier with supply pins ({nm})", EL, "Integrated", IEEE,
                      "Op-amp, triangle form, with supply pins V+ (top) and V- (bottom).", "U",
                      Geometry(op + [text(-10, -10, a, size=9), text(-10, 10, b, size=9)],
                               [T(a, -30, -10, "l", ptype="elec.input"), T(b, -30, 10, "l", ptype="elec.input"),
                                T("OUT", 40, 0, "r", ptype="elec.output"), T("V+", 0, -30, "u", ptype="elec.power"),
                                T("V-", 0, 30, "d", ptype="elec.power")]), keywords=("amplifier", "opamp")))
    add(SymbolDef("el.regulator", "Voltage regulator, three-terminal", EL, "Integrated", IEC_IEEE,
                  "Linear voltage regulator: input IN, output OUT, common GND. Write the type (e.g. 7805) as the "
                  "value.", "U",
                  Geometry([rect(-15, -8, 15, 8), line(-30, 0, -15, 0), line(15, 0, 30, 0), line(0, 8, 0, 20)],
                           [T("IN", -30, 0, "l", ptype="elec.power"), T("OUT", 30, 0, "r", ptype="elec.power"),
                            T("GND", 0, 20, "d", ptype="elec.ground")]), keywords=("ldo", "7805", "regulator")))
    # vacuum tubes
    fil = lambda y: [arc(0, y, 10, 0, 180), line(-10, y, -10, y + 20), line(10, y, 10, y + 20)]  # noqa: E731
    cath = lambda y: [arc(0, y, 14, 20, 160), line(-14, y, -30, y)]  # noqa: E731
    ff = lambda y: [T("F1", -10, y + 20, "d"), T("F2", 10, y + 20, "d")]  # noqa: E731
    bulb = [circle(0, 0, 20)]
    add(SymbolDef("el.tube.diode.direct", "Vacuum diode, directly heated", EL, "Vacuum tubes", IEC_IEEE,
                  "Vacuum diode with directly heated cathode (filament F1-F2) and anode A.", "V",
                  Geometry(bulb + [line(-8, -8, 8, -8), line(0, -8, 0, -30)] + fil(10),
                           [T("A", 0, -30, "u")] + ff(10)), keywords=("valve", "tube", "rectifier")))
    add(SymbolDef("el.tube.diode", "Vacuum diode, indirectly heated", EL, "Vacuum tubes", IEC_IEEE,
                  "Vacuum diode with indirectly heated cathode K, heater F1-F2, anode A.", "V",
                  Geometry(bulb + [line(-8, -8, 8, -8), line(0, -8, 0, -30)] + fil(10) + cath(10),
                           [T("A", 0, -30, "u"), T("K", -30, 10, "l")] + ff(10)), keywords=("valve", "tube")))

    def envelope(top, bottom):
        return [arc(0, top, 20, 0, 180), line(-20, top, -20, bottom), line(20, top, 20, bottom),
                arc(0, bottom, 20, 180, 180)]

    def grid(y):
        return [line(-14, y, 14, y, dash=True), line(-30, y, -14, y)]
    add(SymbolDef("el.tube.triode", "Triode", EL, "Vacuum tubes", IEC_IEEE,
                  "Triode: anode A, control grid G, indirectly heated cathode K, heater F1-F2.", "V",
                  Geometry(envelope(-10, 10) + [line(-10, -18, 10, -18), line(0, -18, 0, -40)] + grid(0) + fil(20)
                           + cath(20), [T("A", 0, -40, "u"), T("G", -30, 0, "l"), T("K", -30, 20, "l")] + ff(20)),
                  keywords=("valve", "tube", "amplifier")))
    add(SymbolDef("el.tube.tetrode", "Tetrode", EL, "Vacuum tubes", IEC_IEEE,
                  "Tetrode: anode A, screen grid G2, control grid G1, indirectly heated cathode K, heater F1-F2.", "V",
                  Geometry(envelope(-20, 10) + [line(-10, -28, 10, -28), line(0, -28, 0, -50)] + grid(-10) + grid(0)
                           + fil(20) + cath(20), [T("A", 0, -50, "u"), T("G2", -30, -10, "l"), T("G1", -30, 0, "l"),
                                                  T("K", -30, 20, "l")] + ff(20)), keywords=("valve", "tube")))
    return s
