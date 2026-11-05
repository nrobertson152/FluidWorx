"""Passive components, sources, grounds and connectors (symbol-library expansion, batches E1 and E2).

Source: ECL = "Electric Components Library" (ElCompLib2017.svg, Filip Dominec and contributors, CC0 1.0),
sections "Linear components" and "Sources, connectors". Every symbol is redrawn natively on the 10-unit grid,
following the existing electrical symbols: two-terminal parts horizontal with terminals at x = -20 / +20, body
between x = -12 and +12; grounds and supply terminals connect at the top or bottom like the existing earths.
* An arrow through a part means continuously variable; a line ending in a short perpendicular bar means preset
  (trimming) adjustment, as drawn in the source.
* Values and labels in the source ("5V", "100mA", "+5V", "VCC") are component labels, not part of the symbols.
"""
from __future__ import annotations

import math

from .base import IEC, IEEE, Geometry, SymbolDef, Terminal as T, arc, arrow, arrowhead, circle, line, poly, polyline, rect, text, zigzag

E = "Electrical"
EL = "Electronic"
IEC_IEEE = IEC + " / " + IEEE.split(" /")[0]


def two(prims, a="1", b="2"):
    return Geometry(prims, [T(a, -20, 0, "l"), T(b, 20, 0, "r")])


def leads(x1=-12, x2=12):
    return [line(-20, 0, x1, 0), line(x2, 0, 20, 0)]


def body_iec():
    return [rect(-12, -4.5, 12, 4.5)]


def body_ansi():
    return [zigzag(-12, 0, 12, 0, n=6, amp=5)]


def humps(x0=-12, n=4, r=3.0):
    return [arc(x0 + r + 2 * r * i, 0, r, 180, -180) for i in range(n)]


def preset(x1, y1, x2, y2, bar=3.0):
    """Preset adjustment: line ending in a short bar perpendicular to it."""
    d = math.hypot(x2 - x1, y2 - y1)
    px, py = -(y2 - y1) / d * bar, (x2 - x1) / d * bar
    return [line(x1, y1, x2, y2), line(x2 - px, y2 - py, x2 + px, y2 + py)]


def nonlinear():
    """Thermistor (non-linear, self-varying) mark: diagonal with a horizontal foot."""
    return [polyline([(-16, 10), (-9, 10), (10, -10)])]


def rheostat_wiper(end):
    """Wiper connected back to terminal 1 (rheostat connection), crossing the body diagonally."""
    p = [circle(-16, 0, 1.6, fill=True, w="thin"), polyline([(-16, 0), (-16, -9), (-8, -9)])]
    if end == "arrow":
        p += arrow(-8, -9, 12, 11, head=4)
    else:
        p += preset(-8, -9, 11, 10)
    return p


def light_in(x=-4, y=-10):
    """Two arrows of incident light."""
    return arrow(x - 7, y - 9, x - 1, y - 1, head=3.5) + arrow(x - 1, y - 9, x + 5, y - 1, head=3.5)


def symbols():
    s = []
    add = s.append
    # ---------------------------------------------------------------- E1: passive (ECL "Linear components")
    add(SymbolDef("el.thermistor.iec", "Thermistor", EL, "Passive", IEC,
                  "Thermistor (temperature-dependent resistor), rectangle form.", "R",
                  two(leads() + body_iec() + nonlinear()), keywords=("ntc", "ptc", "temperature")))
    add(SymbolDef("el.thermistor.ansi", "Thermistor", EL, "Passive", IEEE,
                  "Thermistor (temperature-dependent resistor), zig-zag form.", "R",
                  two(leads() + body_ansi() + nonlinear()), keywords=("ntc", "ptc", "temperature")))
    add(SymbolDef("el.resistor.wave", "Resistor (rectangular-wave form)", EL, "Passive", IEEE,
                  "Resistor drawn as a rectangular wave, as in the source library.", "R",
                  two(leads() + [polyline([(-12, 0), (-12, -5), (-6, -5), (-6, 5), (0, 5), (0, -5), (6, -5), (6, 5),
                                           (12, 5), (12, 0)])]), keywords=("res",)))
    core = [line(-12, -6, 12, -6), line(-12, -9, 12, -9)]
    add(SymbolDef("el.inductor.core", "Inductor with magnetic core", EL, "Passive", IEC,
                  "Inductor with magnetic (iron or ferrite) core.", "L",
                  two(leads() + humps() + core), keywords=("choke", "coil", "ferrite")))
    add(SymbolDef("el.inductor.core.var", "Inductor with magnetic core, preset adjustment", EL, "Passive", IEC,
                  "Inductor with magnetic core, preset (trimming) adjustment.", "L",
                  two(leads() + humps() + core + preset(-8, 10, 10, -14)), keywords=("choke", "coil", "trimmer")))
    add(SymbolDef("el.inductor.var", "Inductor, preset adjustment", EL, "Passive", IEC,
                  "Inductor with preset (trimming) adjustment.", "L",
                  two(leads() + humps() + preset(-8, 10, 10, -12)), keywords=("coil", "trimmer")))
    add(SymbolDef("el.rheostat.iec", "Rheostat (potentiometer, rheostat connection)", EL, "Passive", IEC,
                  "Variable resistor: wiper connected to terminal 1.", "R",
                  two(leads() + body_iec() + rheostat_wiper("arrow")), keywords=("variable", "pot")))
    add(SymbolDef("el.rheostat.ansi", "Rheostat (potentiometer, rheostat connection)", EL, "Passive", IEEE,
                  "Variable resistor, zig-zag form: wiper connected to terminal 1.", "R",
                  two(leads() + body_ansi() + rheostat_wiper("arrow")), keywords=("variable", "pot")))
    add(SymbolDef("el.trim.rheostat.iec", "Trimmer resistor, rheostat connection", EL, "Passive", IEC,
                  "Preset (trimmer) resistor with the wiper connected to terminal 1.", "R",
                  two(leads() + body_iec() + rheostat_wiper("preset")), keywords=("trimmer", "trimpot")))
    add(SymbolDef("el.trim.rheostat.ansi", "Trimmer resistor, rheostat connection", EL, "Passive", IEEE,
                  "Preset (trimmer) resistor, zig-zag form, wiper connected to terminal 1.", "R",
                  two(leads() + body_ansi() + rheostat_wiper("preset")), keywords=("trimmer", "trimpot")))
    add(SymbolDef("el.resistor.preset.iec", "Resistor, preset adjustment", EL, "Passive", IEC,
                  "Resistor with preset (trimming) adjustment, rectangle form. (The existing el.resistor.var.iec, "
                  "with an arrow, is the continuously adjustable resistor.)", "R",
                  two(leads() + body_iec() + preset(-10, 11, 10, -10)), keywords=("trimmer",)))
    add(SymbolDef("el.resistor.preset.ansi", "Resistor, preset adjustment", EL, "Passive", IEEE,
                  "Resistor with preset (trimming) adjustment, zig-zag form.", "R",
                  two(leads() + body_ansi() + preset(-10, 11, 10, -10)), keywords=("trimmer",)))
    add(SymbolDef("el.ldr.iec", "Photoresistor (LDR)", EL, "Passive", IEC,
                  "Light-dependent resistor; arrows indicate incident light.", "R",
                  two(leads() + body_iec() + light_in(0, -6)), keywords=("ldr", "photocell", "light")))
    add(SymbolDef("el.ldr.ansi", "Photoresistor (LDR)", EL, "Passive", IEEE,
                  "Light-dependent resistor, zig-zag form; arrows indicate incident light.", "R",
                  two(leads() + body_ansi() + light_in(0, -6)), keywords=("ldr", "photocell", "light")))
    env = [line(-20, 0, -14, 0), line(14, 0, 20, 0), circle(0, 0, 14)]
    add(SymbolDef("el.ldr.iec.env", "Photoresistor (LDR) in envelope", EL, "Passive", IEC,
                  "Light-dependent resistor in an envelope.", "R",
                  two(env + [line(-14, 0, -9, 0), line(9, 0, 14, 0), rect(-9, -4, 9, 4)] + light_in(-14, -12)),
                  keywords=("ldr", "photocell", "light")))
    add(SymbolDef("el.ldr.ansi.env", "Photoresistor (LDR) in envelope", EL, "Passive", IEEE,
                  "Light-dependent resistor, zig-zag form, in an envelope.", "R",
                  two(env + [line(-14, 0, -9, 0), line(9, 0, 14, 0), zigzag(-9, 0, 9, 0, n=5, amp=4)]
                      + light_in(-14, -12)), keywords=("ldr", "photocell", "light")))
    cap = [line(-20, 0, -3, 0), line(3, 0, 20, 0), line(-3, -9, -3, 9), line(3, -9, 3, 9)]
    add(SymbolDef("el.capacitor.trim", "Capacitor, preset adjustment (trimmer)", EL, "Passive", IEC_IEEE,
                  "Trimmer capacitor (preset adjustment).", "C", two(cap + preset(-9, 10, 9, -10)),
                  keywords=("trimmer", "cap")))
    pot = leads() + [line(0, -20, 0, -9), arrowhead((0, -5), (0, -10), length=4.5, half_width=2.2)]
    add(SymbolDef("el.potentiometer.ansi", "Potentiometer", EL, "Passive", IEEE,
                  "Resistor with movable contact (wiper, terminal 3), zig-zag form.", "R",
                  Geometry(pot + body_ansi(), [T("1", -20, 0, "l"), T("2", 20, 0, "r"), T("3", 0, -20, "u")]),
                  keywords=("pot", "wiper")))
    add(SymbolDef("el.inductor.tap", "Inductor with sliding contact", EL, "Passive", IEC,
                  "Inductor with movable (sliding) contact, terminal 3.", "L",
                  Geometry(leads() + humps() + [line(0, -20, 0, -8), arrowhead((0, -3.5), (0, -8), length=4.5,
                                                                                half_width=2.2)],
                           [T("1", -20, 0, "l"), T("2", 20, 0, "r"), T("3", 0, -20, "u")]),
                  keywords=("variometer", "coil")))
    add(SymbolDef("el.capacitor.pol.rect", "Capacitor, polarised (rectangle plate)", EL, "Passive", IEC,
                  "Polarised capacitor; the open-rectangle plate and terminal + are positive.", "C",
                  Geometry([line(-20, 0, -5, 0), rect(-5, -9, -1, 9), line(3, -9, 3, 9), line(3, 0, 20, 0),
                            text(-10, -10, "+", size=8)], [T("+", -20, 0, "l"), T("-", 20, 0, "r")]),
                  keywords=("electrolytic", "cap")))
    # ---------------------------------------------------------------- E2: sources, grounds, connectors
    add(SymbolDef("el.source.dc", "DC voltage source", E, "Sources", IEEE,
                  "Direct-voltage source with polarity marks; terminal + is positive.", "G",
                  Geometry([line(-20, 0, -10, 0), line(10, 0, 20, 0), circle(0, 0, 10), line(-7, 0, -3, 0),
                            line(-5, -2, -5, 2), line(3, 0, 7, 0)], [T("+", -20, 0, "l"), T("-", 20, 0, "r")]),
                  keywords=("supply", "dc", "voltage")))
    add(SymbolDef("el.source.i", "Current source", E, "Sources", IEC,
                  "Ideal current source; the arrow gives the current direction (out of terminal 2).", "G",
                  two([line(-20, 0, -10, 0), line(10, 0, 20, 0), circle(0, 0, 10)] + arrow(-6, 0, 7, 0, head=4)),
                  keywords=("current",)))
    add(SymbolDef("el.source.i.dep", "Dependent (controlled) current source", E, "Sources", IEEE,
                  "Controlled current source (diamond); the arrow gives the current direction. The controlling "
                  "quantity is written as the value.", "G",
                  two([line(-20, 0, -12, 0), line(12, 0, 20, 0), poly(-12, 0, 0, -9, 12, 0, 0, 9)]
                      + arrow(-6, 0, 7, 0, head=4)), keywords=("controlled", "vccs", "cccs")))
    cells = []
    for i, x in enumerate((-10, -2, 6)):
        cells += [line(x, -10, x, 10), line(x + 4, -5, x + 4, 5, w="thick")]
    add(SymbolDef("el.battery", "Battery, multi-cell", E, "Sources", IEC_IEEE,
                  "Battery of cells; long line is the positive pole of each cell.", "G",
                  Geometry([line(-20, 0, -10, 0), line(10, 0, 20, 0), line(-6, 0, -2, 0), line(2, 0, 6, 0)] + cells
                           + [text(-15, -10, "+", size=8)], [T("+", -20, 0, "l"), T("-", 20, 0, "r")]),
                  keywords=("accumulator", "dc")))
    brk = [line(-20, 0, -14, 0), line(-14, -10, -14, 10), line(-10, -5, -10, 5, w="thick"), line(-10, 0, -6, 0),
           line(-6, -10, -6, 10), line(-2, -5, -2, 5, w="thick"), line(-2, 0, 10, 0, dash=True, w="thin"),
           line(10, -10, 10, 10), line(14, -5, 14, 5, w="thick"), line(14, 0, 20, 0), text(-18, -10, "+", size=8)]
    add(SymbolDef("el.battery.long", "Battery, multi-cell, with break", E, "Sources", IEC_IEEE,
                  "Battery of many cells, drawn with a break (dashed) for the cells not shown.", "G",
                  Geometry(brk, [T("+", -20, 0, "l"), T("-", 20, 0, "r")]), keywords=("accumulator", "dc")))
    coax = [arc(0, 0, 10, 40, 280), circle(0, 0, 2.5), line(2.5, 0, 20, 0), line(0, 10, 0, 20)]
    add(SymbolDef("el.connector.coax", "Coaxial connector", EL, "Connections", IEEE,
                  "Coaxial connector: centre conductor C, shield S.", "X",
                  Geometry(coax, [T("C", 20, 0, "r"), T("S", 0, 20, "d")]), keywords=("bnc", "rf", "coaxial")))
    add(SymbolDef("el.antenna", "Antenna", EL, "Connections", IEC_IEEE, "Antenna, general symbol.", "W",
                  Geometry([line(0, 20, 0, -16), line(0, -8, -8, -16), line(0, -8, 8, -16)], [T("1", 0, 20, "d")]),
                  keywords=("aerial", "ant")))
    add(SymbolDef("el.ground.bar", "Ground (bar)", E, "Connections", IEEE,
                  "Ground / reference, bar form.", "",
                  Geometry([line(0, -20, 0, 0), rect(-8, 0, 8, 4, fill=True)], [T("1", 0, -20, "u")]),
                  keywords=("gnd", "ground"), notes="The source shows it both ways up; rotate as needed."))
    add(SymbolDef("el.ground.signal.fill", "Ground, filled triangle", E, "Connections", IEEE,
                  "Ground / reference, filled-triangle form.", "",
                  Geometry([line(0, -20, 0, 0), poly(-9, 0, 9, 0, 0, 8, fill=True)], [T("1", 0, -20, "u")]),
                  keywords=("gnd", "ground"), notes="The source draws it point up below the connection; rotate as needed."))
    add(SymbolDef("el.rail.pos", "Supply terminal, positive", E, "Connections", IEEE,
                  "Supply rail / terminal (positive). Write the voltage or net name (+5V, VCC) as the value.", "",
                  Geometry([circle(0, 0, 3.5), line(0, 3.5, 0, 20), text(8, -4, "+", size=8)], [T("1", 0, 20, "d")]),
                  keywords=("vcc", "vdd", "supply", "rail")))
    add(SymbolDef("el.rail.neg", "Supply terminal, negative", E, "Connections", IEEE,
                  "Supply rail / terminal (negative). Write the voltage or net name (-5V, VEE) as the value.", "",
                  Geometry([circle(0, 0, 3.5), line(0, -3.5, 0, -20), text(8, 4, "-", size=8)], [T("1", 0, -20, "u")]),
                  keywords=("vee", "vss", "supply", "rail")))
    return s
