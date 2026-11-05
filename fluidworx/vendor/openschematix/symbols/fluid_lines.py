"""Fluid lines, connections and fittings (symbol-library expansion, batch F2).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Basic Symbols" column); Y32 = ANSI Y32.10 clauses 3.5-3.11
and 9.3.2. Each symbol is defined once per medium (hydraulic / pneumatic) because the port domain drives the
drawing checker. Inline elements use ports 1 and 2 like the existing check valve and throttle; single-port
fittings use a work port (hydraulic "1", pneumatic "2"); pneumatic exhausts use "3".
"""
from __future__ import annotations

import math

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arc, arrowhead, circle, line, poly, polyline

MEDIA = (("hyd", "Hydraulic", True), ("pneu", "Pneumatic", False))
G_LINES = "Lines & connections"


def _work(medium):
    return "1" if medium == "hyd" else "2"


# ---------------------------------------------------------------- drawings
def hose_iso():
    """HO flexible hose: connection circles at both ends of a sagging hose."""
    return [line(-30, 0, -16.5, 0), circle(-15, 0, 1.5), arc(0, -9, math.hypot(15, 9), 180 + math.degrees(math.atan2(9, 15)), 180 - 2 * math.degrees(math.atan2(9, 15))), circle(15, 0, 1.5),
            line(16.5, 0, 30, 0)]


def hose_ansi():
    """Y32 3.8: a flexible line drawn as a curve with a dot at each end (the ends are the connections)."""
    return [arc(0, -12, math.hypot(20, 12), 180 + math.degrees(math.atan2(12, 20)), 180 - 2 * math.degrees(math.atan2(12, 20))), circle(-20, 0, 1.3, fill=True, w="thin"),
            circle(20, 0, 1.3, fill=True, w="thin")]


def closed_connection():
    """HO closed connection: line ending in a bar."""
    return [line(0, -20, 0, 0), line(-5, 0, 5, 0)]


def plugged_port():
    """HO / Y32 3.9.1 plugged port: line ending in a cross."""
    return [line(-20, 0, 0, 0), line(-3, -3, 3, 3), line(-3, 3, 3, -3)]


def test_point():
    """HO test point: connection on the line, check element (diamond) and closed end above."""
    return [line(-20, 0, 20, 0), circle(0, 0, 1.5), line(0, -1.5, 0, -6), poly(0, -6, 4, -10, 0, -14, -4, -10),
            line(0, -14, 0, -18), line(-4, -18, 4, -18)]


def rotary_union_iso():
    """HO rotary union: one passage through a rotating joint (circle with a rotation arrow head)."""
    return [line(-20, 0, -8, 0), circle(0, 0, 8), line(8, 0, 20, 0),
            arrowhead((-5.66, -5.66), (-7.6, -2.5), length=3.5, half_width=1.8)]


def rotary_union_ansi():
    """Y32 3.11 (figure printed under 3.9.4 on page 4): three passages through a rotating coupling."""
    p = [circle(0, 0, 12)]
    for y in (-10, 0, 10):
        p += [line(-30, y, 30, y)]
    p.append(arrowhead((3.5, 11.5), (-3.5, 11.5), length=4.0, half_width=2.0))
    return p


def flow_direction(fill, both):
    """Y32 3.5.1 / 3.5.2: flow direction on a line (hollow = pneumatic, filled = hydraulic)."""
    if not both:
        return [line(-20, 0, 20, 0), arrowhead((8, 0), (0, 0), length=7, half_width=4, fill=fill)]
    # both ways: a triangle at each end of the line, pointing outward (Y32 3.5)
    return [line(-20, 0, 20, 0), arrowhead((15, 0), (0, 0), length=7, half_width=4, fill=fill),
            arrowhead((-15, 0), (0, 0), length=7, half_width=4, fill=fill)]


def exhaust_plain():
    """Y32 3.6.1 outlet to atmosphere, plain orifice (not connectable): triangle at the port."""
    return [line(-10, 0, 0, 0), poly(8, 0, 0, -4.5, 0, 4.5)]


def exhaust_port():
    """Y32 3.6.2 outlet to atmosphere, connectable orifice (e.g. thread): marked port, then the triangle."""
    return [line(-10, 0, 4, 0), line(0, -4, 0, 4), poly(12, 0, 4, -4.5, 4, 4.5)]


def silencer():
    """Y32 9.3.2 muffler: box with baffles, exhaust triangle on the far side."""
    return [line(-20, 0, -12, 0), poly(-12, -8, 12, -8, 12, 8, -12, 8), line(-4, -8, -4, -1), line(6, -8, 6, -1),
            line(1, 8, 1, 1), poly(20, 0, 12, -4.5, 12, 4.5)]


def chevron(tip_x, s, half=6):
    """Open arrow (quick-disconnect half) with its tip at tip_x, arms opening toward -s."""
    return polyline([(tip_x - s * 6, -half), (tip_x, 0), (tip_x - s * 6, half)])


def quick_disconnect(checks, apart):
    """Y32 3.9.3-3.9.5 quick disconnect. checks: 0, 1 (right half) or 2. apart: drawn disconnected - the two
    halves are separate (ports 1 and 2 are then not joined by the coupling)."""
    p = []
    halves = ((-1, checks == 2), (1, checks >= 1))
    for s, check in halves:                   # s = -1 left half, +1 right half
        tip = s * (13 if apart else 5)
        p.append(chevron(tip, -s))
        outer = s * 30
        if check:
            c = tip + s * 7
            p += [circle(c, 0, 3.5), line(c + s * 3.5, 0, outer, 0), line(tip, 0, c - s * 3.5, 0)]
        else:
            p.append(line(tip, 0, outer, 0))
        if apart:
            p += [line(tip, 0, s * 4, 0), line(s * 4, -5, s * 4, 5)]
    if not apart:
        p.append(line(0, -3, 0, 3))
    return p


# ---------------------------------------------------------------- registry
def symbols():
    s = []
    add = s.append
    for medium, cat, fill in MEDIA:
        pre = f"fl.{medium}"
        w = _work(medium)
        inline = [T("1", -30, 0, "l"), T("2", 30, 0, "r")]
        add(SymbolDef(f"{pre}.hose", "Flexible hose", cat, G_LINES, ISO,
                      "Flexible hose line between two connections.", "", Geometry(hose_iso(), inline),
                      keywords=("flexible line", "hose")))
        add(SymbolDef(f"{pre}.hose.ansi", "Flexible line (ANSI)", cat, G_LINES, ANSI,
                      "Flexible line; the dots are its connections.", "",
                      Geometry(hose_ansi(), [T("1", -20, 0, "l"), T("2", 20, 0, "r")]), keywords=("hose",)))
        add(SymbolDef(f"{pre}.port.closed", "Closed connection", cat, G_LINES, ISO,
                      "Connection closed off (blanked) at this point.", "", Geometry(closed_connection(),
                                                                                 [T(w, 0, -20, "u")]),
                      keywords=("blanked", "blind", "cap")))
        add(SymbolDef(f"{pre}.port.plugged", "Plugged port", cat, G_LINES, ISO,
                      "Port closed by a plug (ISO 1219 and ANSI Y32.10 3.9.1 draw it the same way).", "",
                      Geometry(plugged_port(), [T(w, -20, 0, "l")]), keywords=("plug", "blanked")))
        add(SymbolDef(f"{pre}.testpoint", "Test point", cat, G_LINES, ISO,
                      "Test / measuring connection on a line, with check and closed end.", "",
                      Geometry(test_point(), [T("1", -20, 0, "l"), T("2", 20, 0, "r")]),
                      keywords=("measuring point", "minimess", "gauge port")))
        add(SymbolDef(f"{pre}.rotaryunion", "Rotary union, one passage", cat, G_LINES, ISO,
                      "Rotating joint passing one line between a fixed and a rotating part.", "",
                      Geometry(rotary_union_iso(), [T("1", -20, 0, "l"), T("2", 20, 0, "r")]),
                      keywords=("rotating coupling", "swivel")))
        add(SymbolDef(f"{pre}.rotaryunion.ansi", "Rotating coupling, three passages (ANSI)", cat, G_LINES, ANSI,
                      "Rotating coupling with three passages (1a-1b, 2a-2b, 3a-3b).", "",
                      Geometry(rotary_union_ansi(), [T(f"{n}{e}", x, y, d) for n, y in (("1", -10), ("2", 0), ("3", 10))
                                                     for e, x, d in (("a", -30, "l"), ("b", 30, "r"))]),
                      keywords=("rotary union", "swivel")))
        names = {0: "without checks", 1: "with one check", 2: "with two checks"}
        for checks, tag in ((0, "open"), (2, "2check"), (1, "1check")):
            for apart in (False, True):
                state = "disconnected" if apart else "connected"
                add(SymbolDef(f"{pre}.qd.{tag}{'.apart' if apart else ''}",
                              f"Quick disconnect {names[checks]}, {state} (ANSI)", cat, G_LINES, ANSI,
                              f"Quick-disconnect coupling {names[checks]}, shown {state}"
                              + (" (the check is in the right-hand half)." if checks == 1 else "."), "",
                              Geometry(quick_disconnect(checks, apart), list(inline)),
                              keywords=("quick coupling", "qd", "coupler")))
        word = "hydraulic" if medium == "hyd" else "pneumatic"
        add(SymbolDef(f"{pre}.flowdir", "Flow direction", cat, G_LINES, ANSI,
                      f"Direction of {word} flow in a line (also used to mark an energy source, Y32 4.4).", "",
                      Geometry(flow_direction(fill, False), [T("1", -20, 0, "l"), T("2", 20, 0, "r")]),
                      keywords=("arrow", "energy source")))
        add(SymbolDef(f"{pre}.flowdir.both", "Flow direction, both ways", cat, G_LINES, ANSI,
                      f"{word.title()} flow in either direction.", "",
                      Geometry(flow_direction(fill, True), [T("1", -20, 0, "l"), T("2", 20, 0, "r")]),
                      keywords=("arrow",)))
        if medium == "pneu":
            add(SymbolDef(f"{pre}.exhaust", "Exhaust to atmosphere, plain (not connectable)", cat, G_LINES, ANSI,
                          "Outlet to atmosphere through a plain orifice that cannot be connected.", "",
                          Geometry(exhaust_plain(), [T("3", -10, 0, "l")]), keywords=("vent", "outlet")))
            add(SymbolDef(f"{pre}.exhaust.port", "Exhaust to atmosphere, connectable", cat, G_LINES, ANSI,
                          "Outlet to atmosphere through a connectable orifice (e.g. threaded).", "",
                          Geometry(exhaust_port(), [T("3", -10, 0, "l")]), keywords=("vent", "outlet")))
            add(SymbolDef(f"{pre}.silencer", "Silencer (muffler)", cat, G_LINES, ANSI,
                          "Exhaust silencer / muffler.", "Z", Geometry(silencer(), [T("3", -20, 0, "l")]),
                          keywords=("muffler", "exhaust")))
    return s
