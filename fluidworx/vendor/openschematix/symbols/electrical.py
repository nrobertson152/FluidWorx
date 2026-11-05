"""Electrical and electronic symbols.

Drawn in local units (1 unit = 0.25 mm, grid = 10 units). Two-terminal
symbols are drawn horizontally with terminals at x = -20 and x = +20; rotate
them in the editor for vertical use.

Where IEC 60617 and IEEE 315 (ANSI) conventions differ, both are provided
and labelled. NEMA/JIC ladder-diagram forms are provided for relay logic.
"""
from __future__ import annotations

import math

from .base import (
    GENERIC, IEC, IEEE, NEMA, Geometry, SymbolDef, Terminal as T, arc, arrow, arrowhead,
    circle, line, poly, polyline, rect, text, zigzag,
)

E = "Electrical"
EL = "Electronic"


def two(prims, a="1", b="2"):
    return Geometry(prims, [T(a, -20, 0, "l"), T(b, 20, 0, "r")])


def _leads(x1=-12, x2=12):
    return [line(-20, 0, x1, 0), line(x2, 0, 20, 0)]


def _inductor_humps(x0=-12, n=4, r=3.0):
    return [arc(x0 + r + 2 * r * i, 0, r, 180, -180) for i in range(n)]


def _no_contact():
    # Make contact (IEC 60617-07-02-01 style): fixed lead on each side,
    # moving blade drawn open, pivoting at the left contact point.
    return [line(-20, 0, -8, 0), line(8, 0, 20, 0), line(-8, 0, 10, -8)]


def _nc_contact():
    # Break contact: blade rests against a perpendicular stop on the fixed contact.
    return [line(-20, 0, -8, 0), line(8, 0, 20, 0), line(8, 0, 8, 6), line(-8, 0, 11, 6.5)]


def symbols():
    s = []
    add = s.append

    # ---------------------------------------------------------------- passive
    add(SymbolDef("el.resistor.iec", "Resistor", EL, "Passive", IEC,
                  "Resistor, general symbol (rectangle).", "R",
                  two(_leads() + [rect(-12, -4.5, 12, 4.5)]), keywords=("res",)))
    add(SymbolDef("el.resistor.ansi", "Resistor", EL, "Passive", IEEE,
                  "Resistor, zig-zag form.", "R",
                  two(_leads() + [zigzag(-12, 0, 12, 0, n=6, amp=5)]), keywords=("res",)))
    add(SymbolDef("el.resistor.var.iec", "Resistor, adjustable", EL, "Passive", IEC,
                  "Resistor with adjustability arrow drawn through it.", "R",
                  two(_leads() + [rect(-12, -4.5, 12, 4.5)] + arrow(-10, 9, 11, -10)), keywords=("variable", "rheostat")))
    pot = _leads() + [rect(-12, -4.5, 12, 4.5), line(0, -20, 0, -9)] + [arrowhead((0, -4.5), (0, -10), length=4.5, half_width=2.2)]
    add(SymbolDef("el.potentiometer.iec", "Potentiometer", EL, "Passive", IEC,
                  "Resistor with movable contact (wiper, terminal 3).", "R",
                  Geometry(pot, [T("1", -20, 0, "l"), T("2", 20, 0, "r"), T("3", 0, -20, "u")]), keywords=("pot", "wiper")))
    add(SymbolDef("el.capacitor", "Capacitor", EL, "Passive", IEC + " / " + IEEE.split(" /")[0],
                  "Capacitor, general symbol (non-polarised).", "C",
                  two([line(-20, 0, -3, 0), line(3, 0, 20, 0), line(-3, -9, -3, 9), line(3, -9, 3, 9)]), keywords=("cap",)))
    pol = [line(-20, 0, -3, 0), line(-3, -9, -3, 9), arc(20, 0, 16, 145, 70), line(4, 0, 20, 0), text(-8, -9, "+", size=8)]
    add(SymbolDef("el.capacitor.pol", "Capacitor, polarised", EL, "Passive", IEEE,
                  "Polarised (e.g. electrolytic) capacitor; straight plate and terminal + are positive.", "C",
                  Geometry(pol, [T("+", -20, 0, "l"), T("-", 20, 0, "r")]), keywords=("electrolytic", "cap")))
    add(SymbolDef("el.inductor", "Inductor / winding", EL, "Passive", IEC,
                  "Inductor, coil or winding (semicircle form, used by IEC 60617 and IEEE 315).", "L",
                  two([line(-20, 0, -12, 0), line(12, 0, 20, 0)] + _inductor_humps()), keywords=("coil", "choke")))
    tr = [line(-20, -20, -6, -20), line(-6, -20, -6, -12), line(-20, 20, -6, 20), line(-6, 20, -6, 12),
          line(20, -20, 6, -20), line(6, -20, 6, -12), line(20, 20, 6, 20), line(6, 20, 6, 12),
          line(-1.5, -14, -1.5, 14), line(1.5, -14, 1.5, 14)]
    for i in range(4):
        tr.append(arc(-6, -9 + 6 * i, 3, 90, -180))
        tr.append(arc(6, -9 + 6 * i, 3, 90, 180))
    add(SymbolDef("el.transformer", "Transformer, two windings, iron core", E, "Power", IEC,
                  "Two-winding transformer in winding (coil) form with magnetic core.", "T",
                  Geometry(tr, [T("P1", -20, -20, "l"), T("P2", -20, 20, "l"), T("S1", 20, -20, "r"), T("S2", 20, 20, "r")]),
                  keywords=("xfmr",)))

    # ---------------------------------------------------------------- semiconductors
    diode = [line(-20, 0, -6, 0), poly(-6, -6, 6, 0, -6, 6), line(6, -6, 6, 6), line(6, 0, 20, 0)]
    add(SymbolDef("el.diode", "Diode", EL, "Semiconductors", IEC + " / " + IEEE.split(" /")[0],
                  "Semiconductor diode. Terminal A = anode, K = cathode.", "D",
                  Geometry(diode, [T("A", -20, 0, "l"), T("K", 20, 0, "r")]), keywords=("rectifier",)))
    zen = [line(-20, 0, -6, 0), poly(-6, -6, 6, 0, -6, 6), polyline([(3, -8), (6, -6), (6, 6), (9, 8)]), line(6, 0, 20, 0)]
    add(SymbolDef("el.diode.zener", "Zener diode", EL, "Semiconductors", IEC + " / " + IEEE.split(" /")[0],
                  "Voltage-reference (Zener / breakdown) diode.", "D",
                  Geometry(zen, [T("A", -20, 0, "l"), T("K", 20, 0, "r")]), keywords=("reference",)))
    led = diode + arrow(0, -8, 6, -14, head=3.5) + arrow(5, -6, 11, -12, head=3.5)
    add(SymbolDef("el.led", "Light-emitting diode (LED)", EL, "Semiconductors", IEC + " / " + IEEE.split(" /")[0],
                  "LED; arrows indicate emitted light.", "D",
                  Geometry(led, [T("A", -20, 0, "l"), T("K", 20, 0, "r")]), keywords=("light",)))

    def bjt(npn):
        p = [circle(2, 0, 14, w="thin"), line(-20, 0, -6, 0), line(-6, -9, -6, 9),
             polyline([(-6, -4), (10, -12), (10, -20)]), polyline([(-6, 4), (10, 12), (10, 20)])]
        if npn:
            p.append(arrowhead((8, 11), (-6, 4), length=5, half_width=2.2))
        else:
            p.append(arrowhead((-4, 5), (10, 12), length=5, half_width=2.2))
        return Geometry(p, [T("B", -20, 0, "l"), T("C", 10, -20, "u"), T("E", 10, 20, "d")])

    add(SymbolDef("el.npn", "Transistor, NPN", EL, "Semiconductors", IEEE,
                  "Bipolar junction transistor, NPN (envelope shown). B base, C collector, E emitter.", "Q", bjt(True), keywords=("bjt",)))
    add(SymbolDef("el.pnp", "Transistor, PNP", EL, "Semiconductors", IEEE,
                  "Bipolar junction transistor, PNP (envelope shown). B base, C collector, E emitter.", "Q", bjt(False), keywords=("bjt",)))
    op = [poly(-15, -20, 25, 0, -15, 20), line(-30, -10, -15, -10), line(-30, 10, -15, 10), line(25, 0, 40, 0),
          text(-10, -10, "-", size=9), text(-10, 10, "+", size=9)]
    add(SymbolDef("el.opamp", "Operational amplifier", EL, "Integrated", IEEE,
                  "Op-amp, triangle form. Supply pins are not shown.", "U",
                  Geometry(op, [T("-", -30, -10, "l"), T("+", -30, 10, "l"), T("OUT", 40, 0, "r")]), keywords=("amplifier",),
                  notes="Supply terminals omitted; IEC 60617 uses a rectangular amplifier symbol instead."))

    # ---------------------------------------------------------------- sources
    cell = [line(-20, 0, -3, 0), line(-3, -10, -3, 10), line(3, -5, 3, 5, w="thick"), line(3, 0, 20, 0), text(-9, -10, "+", size=8)]
    add(SymbolDef("el.cell", "Cell / battery", E, "Sources", IEC + " / " + IEEE.split(" /")[0],
                  "Primary or secondary cell. Long line is the positive pole.", "G",
                  Geometry(cell, [T("+", -20, 0, "l"), T("-", 20, 0, "r")]), keywords=("battery", "dc")))
    sine = polyline([(-6 + 12 * i / 16, -4 * math.sin(2 * math.pi * i / 16)) for i in range(17)], w="thin")
    add(SymbolDef("el.source.ac", "AC voltage source", E, "Sources", IEC,
                  "Alternating-current source / generator, general.", "G",
                  two([line(-20, 0, -10, 0), line(10, 0, 20, 0), circle(0, 0, 10), sine]), keywords=("supply",)))
    dcsrc = [line(-20, 0, -10, 0), line(10, 0, 20, 0), circle(0, 0, 10), line(-10, 0, 10, 0),
             text(-15, -10, "+", size=8)]
    add(SymbolDef("el.source.v", "Voltage source, ideal", E, "Sources", IEC,
                  "Ideal voltage source (circle with line along the conductor).", "G",
                  Geometry(dcsrc, [T("+", -20, 0, "l"), T("-", 20, 0, "r")]), keywords=("supply", "dc")))

    # ---------------------------------------------------------------- earth / connection
    add(SymbolDef("el.earth", "Earth (ground)", E, "Connections", IEC,
                  "Earth, general symbol.", "",
                  Geometry([line(0, -20, 0, 0), line(-10, 0, 10, 0), line(-6, 4, 6, 4), line(-2, 8, 2, 8)], [T("1", 0, -20, "u")]),
                  keywords=("gnd", "ground")))
    add(SymbolDef("el.earth.pe", "Protective earth", E, "Connections", IEC,
                  "Protective earth (PE): earth symbol enclosed in a circle.", "",
                  Geometry([line(0, -20, 0, -2), line(-6, -2, 6, -2), line(-4, 1.5, 4, 1.5), line(-1.5, 5, 1.5, 5), circle(0, 1, 9)],
                           [T("1", 0, -20, "u")]), keywords=("pe", "ground")))
    add(SymbolDef("el.chassis", "Frame / chassis", E, "Connections", IEC,
                  "Frame or chassis connection.", "",
                  Geometry([line(0, -20, 0, 0), line(-10, 0, 10, 0), line(-10, 0, -14, 6), line(0, 0, -4, 6), line(10, 0, 6, 6)],
                           [T("1", 0, -20, "u")]), keywords=("ground",)))
    add(SymbolDef("el.ground.signal", "Signal ground", EL, "Connections", IEEE,
                  "Signal / common ground (triangle).", "",
                  Geometry([line(0, -20, 0, 0), poly(-8, 0, 8, 0, 0, 8)], [T("1", 0, -20, "u")]), keywords=("gnd", "common")))
    add(SymbolDef("el.terminal", "Terminal", E, "Connections", IEC,
                  "Terminal (connection point), feed-through form.", "X",
                  two([line(-20, 0, -3, 0), line(3, 0, 20, 0), circle(0, 0, 3)]), keywords=("terminal block",)))
    add(SymbolDef("el.connector.point", "Signal end / off-page", E, "Connections", GENERIC,
                  "Single connection point for labelling a signal or off-page reference.", "",
                  Geometry([line(0, 0, 10, 0), circle(13, 0, 3)], [T("1", 0, 0, "l")]), keywords=("net", "label")))

    # ---------------------------------------------------------------- protection
    add(SymbolDef("el.fuse.iec", "Fuse", E, "Protection", IEC,
                  "Fuse, general symbol.", "F",
                  two([line(-20, 0, 20, 0), rect(-12, -4.5, 12, 4.5)])))
    cb = _no_contact() + [line(5, -3, 11, 3), line(5, 3, 11, -3)]
    add(SymbolDef("el.breaker.iec", "Circuit breaker", E, "Protection", IEC,
                  "Circuit breaker: make contact with breaker function mark (x) at the fixed contact.", "Q",
                  two(cb), keywords=("mcb", "cb")))

    # ---------------------------------------------------------------- switching (IEC)
    add(SymbolDef("el.contact.no.iec", "Contact, make (NO)", E, "Switching (IEC)", IEC,
                  "Make contact, normally open. Also used as general switch symbol.", "S",
                  two(_no_contact()), keywords=("switch", "no", "normally open")))
    add(SymbolDef("el.contact.nc.iec", "Contact, break (NC)", E, "Switching (IEC)", IEC,
                  "Break contact, normally closed.", "S",
                  two(_nc_contact()), keywords=("switch", "nc", "normally closed")))
    pb = _no_contact() + [line(1, -4, 1, -15, dash=True, w="thin"), polyline([(-4, -12), (-4, -16), (6, -16), (6, -12)])]
    add(SymbolDef("el.pushbutton.no.iec", "Push-button, make (NO)", E, "Switching (IEC)", IEC,
                  "Push-button switch, normally open (push operator linked to the contact).", "S",
                  two(pb), keywords=("button", "momentary")))
    pbc = _nc_contact() + [line(1.5, 2.5, 1.5, -15, dash=True, w="thin"), polyline([(-3.5, -12), (-3.5, -16), (6.5, -16), (6.5, -12)])]
    add(SymbolDef("el.pushbutton.nc.iec", "Push-button, break (NC)", E, "Switching (IEC)", IEC,
                  "Push-button switch, normally closed.", "S",
                  two(pbc), keywords=("button", "stop", "momentary")))
    coil = [line(0, -20, 0, -6), line(0, 6, 0, 20), rect(-10, -6, 10, 6)]
    add(SymbolDef("el.coil.iec", "Coil (relay / contactor / solenoid)", E, "Switching (IEC)", IEC,
                  "Operating device (coil) of a relay, contactor or solenoid. Terminals A1/A2.", "K",
                  Geometry(coil, [T("A1", 0, -20, "u"), T("A2", 0, 20, "d")]), keywords=("relay", "contactor", "solenoid")))
    lamp = [line(-20, 0, -8, 0), line(8, 0, 20, 0), circle(0, 0, 8)]
    r = 8 * math.sqrt(0.5)
    lamp += [line(-r, -r, r, r), line(-r, r, r, -r)]
    add(SymbolDef("el.lamp.iec", "Lamp / indicator", E, "Signalling", IEC,
                  "Lamp, general symbol (signal or lighting lamp).", "H",
                  two(lamp), keywords=("light", "pilot light", "indicator")))

    # ---------------------------------------------------------------- ladder (NEMA)
    add(SymbolDef("el.contact.no.nema", "Relay contact, NO", E, "Ladder (NEMA)", NEMA,
                  "Normally open relay contact as used on ladder diagrams. Note: resembles the capacitor symbol; use the IEC set if ambiguity matters.", "CR",
                  two([line(-20, 0, -4, 0), line(-4, -8, -4, 8), line(4, -8, 4, 8), line(4, 0, 20, 0)]), keywords=("ladder", "no")))
    add(SymbolDef("el.contact.nc.nema", "Relay contact, NC", E, "Ladder (NEMA)", NEMA,
                  "Normally closed relay contact as used on ladder diagrams.", "CR",
                  two([line(-20, 0, -4, 0), line(-4, -8, -4, 8), line(4, -8, 4, 8), line(4, 0, 20, 0), line(-9, 9, 9, -9)]),
                  keywords=("ladder", "nc")))
    add(SymbolDef("el.coil.nema", "Relay coil", E, "Ladder (NEMA)", NEMA,
                  "Relay / contactor coil as used on ladder diagrams.", "CR",
                  two([line(-20, 0, -8, 0), line(8, 0, 20, 0), circle(0, 0, 8)]), keywords=("ladder", "relay")))
    pbn = [line(-20, 0, -10, 0), circle(-8, 0, 2), line(10, 0, 20, 0), circle(8, 0, 2),
           line(-12, -7, 12, -7), line(0, -7, 0, -15)]
    add(SymbolDef("el.pushbutton.no.nema", "Push-button, NO", E, "Ladder (NEMA)", NEMA,
                  "Normally open momentary push-button (bar above the contacts).", "PB",
                  two(pbn), keywords=("ladder", "button")))
    pbcn = [line(-20, 0, -10, 0), circle(-8, 0, 2), line(10, 0, 20, 0), circle(8, 0, 2),
            line(-12, 2, 12, 2), line(0, 2, 0, -10)]
    add(SymbolDef("el.pushbutton.nc.nema", "Push-button, NC", E, "Ladder (NEMA)", NEMA,
                  "Normally closed momentary push-button (bar below the contacts).", "PB",
                  two(pbcn), keywords=("ladder", "button", "stop")))

    # ---------------------------------------------------------------- machines
    m = [circle(0, 0, 12), line(0, -20, 0, -12), line(0, 12, 0, 20), text(0, 0, "M", size=10)]
    add(SymbolDef("el.motor", "Motor", E, "Machines", IEC,
                  "Motor, general symbol (add DC / AC marking with the label if needed).", "M",
                  Geometry(m, [T("1", 0, -20, "u"), T("2", 0, 20, "d")]), keywords=("motor",)))
    m3 = [circle(0, 0, 12)]
    for x in (-10, 0, 10):
        y = -math.sqrt(144 - x * x)
        m3.append(line(x, -20, x, y))
    m3 += [text(0, -2, "M", size=9), text(0, 7, "3~", size=6)]
    add(SymbolDef("el.motor.3ph", "Motor, three-phase", E, "Machines", IEC,
                  "Three-phase AC motor. Terminals U1, V1, W1.", "M",
                  Geometry(m3, [T("U1", -10, -20, "u"), T("V1", 0, -20, "u"), T("W1", 10, -20, "u")]), keywords=("induction", "3ph")))
    g = [circle(0, 0, 12), line(0, -20, 0, -12), line(0, 12, 0, 20), text(0, 0, "G", size=10)]
    add(SymbolDef("el.generator", "Generator", E, "Machines", IEC,
                  "Generator, general symbol.", "G",
                  Geometry(g, [T("1", 0, -20, "u"), T("2", 0, 20, "d")]), keywords=("alternator",)))
    return s
