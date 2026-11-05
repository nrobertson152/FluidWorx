"""Non-return valves, shut-off valves and cartridge logic elements (symbol-library expansion, batch F8a).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Basic Symbols", "Energy Control"); Y32 = ANSI Y32.10
10.9-10.10.2. The ball-and-seat proportions follow the existing fl.*.check (seat drawn as a V whose mouth holds
the ball). The chart draws its pilot-operated checks inside a dash-dot cartridge outline; that centre-line
style is not available (director decision D3), so the outline is not drawn.
"""
from __future__ import annotations

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arrowhead, circle, line, poly, polyline, rect, zigzag

G = "Non-return & flow"
MEDIA = (("hyd", "Hydraulic"), ("pneu", "Pneumatic"))


def ball_seat(cx, s, ball=True):
    """Seat V with its vertex 10 units from the ball centre, on side s (-1 left, +1 right)."""
    p = [polyline([(cx, -8), (cx + s * 10, 0), (cx, 8)])]
    if ball:
        p.append(circle(cx, 0, 6))
    return p


def check_in_box():
    """Existing check (free flow 1 -> 2) inside a valve body."""
    return [rect(-12, -12, 14, 12), line(-20, 0, -12, 0), line(-12, 0, -6, 0),
            polyline([(4, -8), (-6, 0), (4, 8)]), circle(4, 0, 6), line(10, 0, 14, 0), line(14, 0, 20, 0)]


def double_check(bleed):
    """Y32 10.10.2: two inlets, outlet from the middle. With cross bleed one side has a seat but no ball."""
    p = [rect(-24, -12, 24, 12), line(-30, 0, -20, 0), line(20, 0, 30, 0)]
    p += ball_seat(-10, -1, ball=not bleed) + ball_seat(10, 1)
    p += [line(-10 if bleed else -4, 0, 4, 0), circle(0, 0, 1.6, fill=True, w="thin"), line(0, 0, 0, 20)]
    p.append(arrowhead((0, 17), (0, 9), length=5, half_width=2.5))
    if bleed:
        p.append(arrowhead((0, 6), (0, 14), length=5, half_width=2.5))
    return p


def symbols():
    s = []
    add = s.append
    for medium, cat in MEDIA:
        pre = f"fl.{medium}"
        names = ("X", "Y", "A") if medium == "hyd" else ("1", "1.1", "2")
        pilot = "X" if medium == "hyd" else "12"
        add(SymbolDef(f"{pre}.shutoff", "Shut-off valve", cat, G, ISO, "Manual shut-off (isolating) valve.", "V",
                      Geometry([line(-20, 0, -10, 0), poly(-10, -6, -10, 6, 0, 0), poly(10, -6, 10, 6, 0, 0),
                                line(10, 0, 20, 0), line(0, 0, 0, -10), line(-5, -10, 5, -10)],
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r")]), keywords=("isolating", "ball valve", "tap")))
        add(SymbolDef(f"{pre}.shutoff.ansi", "On-off valve, simplified (ANSI)", cat, G, ANSI,
                      "Two-way on-off (manual shut-off) valve, simplified symbol.", "V",
                      Geometry([line(-20, 0, -10, 0), poly(-10, -6, -10, 6, 0, 0), poly(10, -6, 10, 6, 0, 0),
                                line(10, 0, 20, 0)], [T("1", -20, 0, "l"), T("2", 20, 0, "r")]),
                      keywords=("isolating", "shut-off")))
        add(SymbolDef(f"{pre}.check.pilot", "Check valve, pilot operated to open", cat, G, ISO,
                      f"Pilot-operated check valve: free flow 1 to 2; pilot pressure at {pilot} opens it for reverse "
                      "flow. ANSI Y32.10 10.9.3 draws it the same way.", "V",
                      Geometry(check_in_box() + [line(14, -10, 30, -10, dash=True, w="thin")],
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r"), T(pilot, 30, -10, "r")]),
                      keywords=("pilot check", "lock valve", "pocv"),
                      notes="The chart's dash-dot cartridge outline is not drawn (centre-line style not available)."))
        add(SymbolDef(f"{pre}.check.pilotclose", "Check valve, pilot operated to close (ANSI)", cat, G, ANSI,
                      f"Check valve held closed by pilot pressure at {pilot}.", "V",
                      Geometry(check_in_box() + [line(-30, -10, -12, -10, dash=True, w="thin")],
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r"), T(pilot, -30, -10, "l")])))
        three = [T(names[0], -30, 0, "l"), T(names[1], 30, 0, "r"), T(names[2], 0, 20, "d")]
        add(SymbolDef(f"{pre}.doublecheck", "Double check valve, without cross bleed (ANSI)", cat, G, ANSI,
                      "Two inlets, one outlet; one-way flow (no cross bleed during transition).", "V",
                      Geometry(double_check(False), list(three)), keywords=("shuttle", "or")))
        add(SymbolDef(f"{pre}.doublecheck.bleed", "Double check valve, with cross bleed (ANSI)", cat, G, ANSI,
                      "Two inlets, one outlet; single poppet, cross bleed (reverse flow) possible during transition.",
                      "V", Geometry(double_check(True), list(three)), keywords=("shuttle",)))
    add(SymbolDef("fl.hyd.check.pilot.drain", "Check valve, pilot operated, with drain", "Hydraulic", G, ISO,
                  "Pilot-operated check valve with external drain to the reservoir.", "V",
                  Geometry(check_in_box() + [line(14, -10, 30, -10, dash=True, w="thin"),
                                             polyline([(-12, -8), (-24, -8), (-24, 6)], dash=True, w="thin"),
                                             polyline([(-28, 3), (-28, 9), (-20, 9), (-20, 3)])],
                           [T("1", -20, 0, "l"), T("2", 20, 0, "r"), T("X", 30, -10, "r")]),
                  keywords=("pilot check", "pocv"),
                  notes="The chart's dash-dot cartridge outline is not drawn (centre-line style not available)."))
    add(SymbolDef("fl.hyd.logic", "Logic element (2-way cartridge)", "Hydraulic", "Cartridge valves", ISO,
                  "Two-way slip-in cartridge (logic element): spring-loaded poppet, ports A (side) and B (seat).", "V",
                  Geometry([rect(-12, -20, 12, -8), zigzag(6, -19, 6, -9, n=4, amp=3), rect(-12, -8, 12, 4),
                            line(-4, -8, -4, 4), line(4, -8, 4, 4), polyline([(-12, 4), (0, 16), (12, 4)]),
                            line(0, 16, 0, 20), line(-20, 0, -12, 0)],
                           [T("A", -20, 0, "l"), T("B", 0, 20, "d")]), keywords=("cartridge", "slip-in", "poppet"),
                  notes="No control (X) connection is drawn in the source chart."))
    return s
