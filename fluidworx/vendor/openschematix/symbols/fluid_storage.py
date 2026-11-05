"""Reservoirs, accumulators and receivers (symbol-library expansion, batch F3).

Sources: HO = HydraulicsOnline.com ISO 1219 chart; Y32 = ANSI Y32.10 section 4. Proportions follow the
existing fl.hyd.tank / fl.hyd.accumulator / fl.pneu.receiver drawings so that ISO and ANSI forms match in size.
Reservoir connections enter from above (Y32 4.1 note); "above fluid level" lines end at the reservoir rim,
"below fluid level" lines continue into the reservoir.
"""
from __future__ import annotations

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arc, circle, line, poly, polyline, rect, zigzag

H, P = "Hydraulic", "Pneumatic"
G = "Reservoirs & accumulators"


def capsule(separator=True):
    """Accumulator body (as the existing fl.hyd.accumulator), optional separating element, port below."""
    p = [arc(0, -7, 8, 0, 180), arc(0, 7, 8, 180, 180), line(-8, -7, -8, 7), line(8, -7, 8, 7),
         line(0, 15, 0, 20)]
    if separator:
        p.append(line(-8, 0, 8, 0))
    return p


def small_tank(rim=-6):
    return polyline([(-15, rim), (-15, 8), (15, 8), (15, rim)])


def big_tank(closed=False):
    """Y32 4.1 complete reservoir: vented (open top) or pressurized (closed)."""
    if closed:
        return rect(-20, -10, 20, 10)
    return polyline([(-20, -10), (-20, 10), (20, 10), (20, -10)])


def symbols():
    s = []
    add = s.append
    tank_t = [T("T", 0, -20, "u")]
    add(SymbolDef("fl.hyd.tank.above", "Reservoir, return above fluid level", H, G, ISO,
                  "Reservoir open to atmosphere; the line ends above the fluid level.", "Z",
                  Geometry([small_tank(), line(0, -20, 0, -6)], tank_t), keywords=("tank",)))
    for closed, below in ((False, False), (False, True), (True, False), (True, True)):
        kind = "pressurized" if closed else "vented"
        level = "below" if below else "above"
        sid = f"fl.hyd.tank.{kind}" + (".below" if below else "") + (".ansi" if not closed else "")
        add(SymbolDef(sid, f"Reservoir, {kind}, line {level} fluid level (ANSI)", H, G, ANSI,
                      f"Reservoir, {'closed and pressurized' if closed else 'vented to atmosphere'} (complete "
                      f"symbol); the connection ends {level} the fluid level.", "Z",
                      Geometry([big_tank(closed), line(0, -20, 0, 6 if below else -10)], list(tank_t)),
                      keywords=("tank", "pressurized" if closed else "vented")))
    add(SymbolDef("fl.hyd.tank.bottom", "Reservoir, bottom connection (ANSI)", H, G, ANSI,
                  "Vented reservoir with a connection through the bottom (draw only where essential to the "
                  "circuit function, Y32 4.1.1).", "Z",
                  Geometry([big_tank(), line(0, 10, 0, 20)], [T("T", 0, 20, "d")]), keywords=("tank", "suction")))
    add(SymbolDef("fl.hyd.manifold.vented", "Vented manifold (ANSI)", H, G, ANSI,
                  "Return manifold vented to atmosphere and draining to the reservoir.", "",
                  Geometry([line(-20, 0, 0, 0), circle(0, 0, 1.8, fill=True, w="thin"), line(0, -10, 0, 12),
                            arc(0, -10, 4, 30, 120), polyline([(-6, 9), (-6, 15), (6, 15), (6, 9)])],
                           [T("T", -20, 0, "l")]), keywords=("vent", "drain", "return")))
    add(SymbolDef("fl.hyd.accumulator.gas", "Accumulator, gas charged", H, G, ISO,
                  "Accumulator with gas pre-charge (gas side above the separating element). ANSI Y32.10 4.2.2 "
                  "draws it the same way.", "Z",
                  Geometry(capsule() + [poly(-3.5, -7, 3.5, -7, 0, -1)], [T("P", 0, 20, "d")]),
                  keywords=("bladder", "piston", "nitrogen", "hydro-pneumatic")))
    add(SymbolDef("fl.hyd.accumulator.ansi", "Accumulator (ANSI)", H, G, ANSI,
                  "Accumulator, general symbol without loading indication.", "Z",
                  Geometry(capsule(separator=False), [T("P", 0, 20, "d")])))
    add(SymbolDef("fl.hyd.accumulator.spring", "Accumulator, spring loaded (ANSI)", H, G, ANSI,
                  "Accumulator loaded by a spring above the separating element.", "Z",
                  Geometry(capsule() + [zigzag(0, -12, 0, -1, n=5, amp=3)], [T("P", 0, 20, "d")])))
    add(SymbolDef("fl.hyd.accumulator.weight", "Accumulator, weighted (ANSI)", H, G, ANSI,
                  "Accumulator loaded by a weight resting on the separating element.", "Z",
                  Geometry(capsule() + [rect(-4, -6, 4, 0)], [T("P", 0, 20, "d")])))
    add(SymbolDef("fl.pneu.receiver.ansi", "Air receiver, inline (ANSI)", P, "Supply", ANSI,
                  "Receiver (pressure vessel) with inlet and outlet.", "Z",
                  Geometry([arc(-12, 0, 8, 90, 180), arc(12, 0, 8, -90, 180), line(-12, -8, 12, -8),
                            line(-12, 8, 12, 8), line(-30, 0, -20, 0), line(20, 0, 30, 0)],
                           [T("1", -30, 0, "l"), T("2", 30, 0, "r")]), keywords=("tank", "vessel")))
    return s
