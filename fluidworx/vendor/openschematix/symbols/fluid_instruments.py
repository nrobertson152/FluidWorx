"""Measuring instruments, sensing devices and switches (symbol-library expansion, batch F9).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Measuring Instruments & indicators"); Y32 = ANSI Y32.10
section 9. Instrument bodies follow the existing fl.*.gauge (circle r = 10, port below).
* Electrical outputs (transducers, pressure switches) are drawn as the sources draw them - a signal line with
  the electric mark - but carry no electrical terminals, as for the solenoids; the electrical side is drawn in
  the electrical diagram.
* Sensing taps (venturi, orifice plate, pitot tube, pressure switch) are pilot-type ports X / X1 / X2.
"""
from __future__ import annotations

import math

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arc, arrow, arrowhead, circle, line, poly, polyline, rect, zigzag

G = "Measurement"
MEDIA = (("hyd", "Hydraulic"), ("pneu", "Pneumatic"))
R = 10.0


def body(port="bottom"):
    p = [circle(0, 0, R)]
    if port == "bottom":
        p.append(line(0, R, 0, 20))
    elif port == "top":
        p.append(line(0, -R, 0, -20))
    elif port == "sides":
        p += [line(-20, 0, -R, 0), line(R, 0, 20, 0)]
    return p


def lens(side):
    """Inner arc of the flow symbols: a chord of radius 10 centred 15 units outside the body, on side -1 (top)
    or +1 (bottom)."""
    c = 15.0
    y = -c / 2                                    # intersection with the body circle (for side = -1)
    x = math.sqrt(R * R - y * y)
    a = math.degrees(math.atan2(c + y, x))        # angle of the intersection seen from the arc centre
    if side < 0:
        return arc(0, -c, R, 180 + a, 180 - 2 * a)
    return arc(0, c, R, a, 180 - 2 * a)


def signal_out():
    """Electrical signal line on the right with the electric mark (no terminal)."""
    return [line(R, 0, 22, 0), polyline([(19, -14), (14.5, -5), (19.5, -3), (15.5, 3)]),
            arrowhead((15.5, 3), (17.5, -1.5), length=4)]


def needle():
    """Y32 9.1.1: wedge-shaped pointer."""
    return [poly(-4, -6, -1, -8, 5, 7, fill=True)]


def bottom(name="P", ptype=""):
    return [T(name, 0, 20, "d", ptype=ptype)]


def symbols():
    s = []
    add = s.append
    sd = lambda sid, name, cat, conv, desc, prims, terms, **kw: SymbolDef(  # noqa: E731
        sid, name, cat, G, conv, desc, kw.pop("prefix", "S"), Geometry(prims, terms), **kw)
    for medium, cat in MEDIA:
        pre = f"fl.{medium}"
        hyd = medium == "hyd"
        port = "P" if hyd else "1"
        pil = "hyd.pilot" if hyd else "pneu.pilot"
        io = [T("1", -20, 0, "l"), T("2", 20, 0, "r")]
        # ------------------------------------------------------------ HO chart
        cross = [line(-7.07, -7.07, 7.07, 7.07), line(-7.07, 7.07, 7.07, -7.07)]
        add(sd(f"{pre}.pressure.indicator", "Pressure indicator", cat, ISO,
               "Pressure indicator (optical, e.g. pop-up or lamp type), connected at the bottom.",
               body() + cross + [line(R, 0, 20, 0)], bottom(port),
               notes="The short line on the right is drawn as in the chart; it is not a connection."))
        add(sd(f"{pre}.pressure.transducer", "Pressure transducer", cat, ISO,
               "Pressure transducer: pressure in at the bottom, electrical signal out (drawn, no electrical terminal).",
               body() + cross + signal_out(), bottom(port), keywords=("sensor", "pressure sensor")))
        add(sd(f"{pre}.gauge.diff", "Differential pressure gauge", cat, ISO,
               "Differential pressure gauge with two connections.",
               [circle(0, 0, R), polyline([(-3, 9.5), (-3, 14), (-10, 14), (-10, 20)]),
                polyline([(3, 9.5), (3, 14), (10, 14), (10, 20)])] + arrow(-6, 6, 6, -6, head=3.5),
               [T(f"{port}1", -10, 20, "d", ptype="hyd.work" if hyd else "pneu.work"),
                T(f"{port}2", 10, 20, "d", ptype="hyd.work" if hyd else "pneu.work")],
               keywords=("manometer", "dp")))
        add(sd(f"{pre}.thermometer", "Thermometer", cat, ISO,
               "Thermometer (temperature indicator). ANSI Y32.10 9.1.2 draws it the same way.",
               body() + [line(0, -R, 0, 4), circle(0, 5.5, 2, fill=True, w="thin")], bottom(port),
               keywords=("temperature",)))
        add(sd(f"{pre}.flow.indicator", "Flow indicator", cat, ISO, "Flow indicator, connected at the bottom.",
               body() + [lens(-1)], bottom(port), keywords=("flow",)))
        add(sd(f"{pre}.flowmeter", "Flow meter", cat, ISO,
               "Flow meter (flow rate), in line. ANSI Y32.10 9.1.3.1 draws it the same way.",
               body("sides") + [lens(-1), lens(1)], list(io), keywords=("flow",)))
        # ------------------------------------------------------------ Y32.10 section 9
        add(sd(f"{pre}.pressure.indicator.ansi", "Pressure indicator / recorder (ANSI)", cat, ANSI,
               "Pressure indicating or recording instrument; connection at the top (Y32.10 also shows it from "
               "the side - rotate the symbol).", body("top") + needle(), [T(port, 0, -20, "u")],
               keywords=("gauge", "manometer")))
        add(sd(f"{pre}.flowmeter.total", "Flow meter, totalizing (ANSI)", cat, ANSI,
               "Totalizing flow meter, in line.",
               body("sides") + [lens(-1), lens(1), polyline([(4, -5), (-3, -5), (2, 0), (-3, 5), (4, 5)])], list(io),
               keywords=("flow", "totaliser", "volume")))
        add(sd(f"{pre}.venturi", "Venturi (ANSI)", cat, ANSI,
               "Venturi: flow 1 - 2 through a converging-diverging section, sensing tap X at the throat.",
               [rect(-20, -10, 20, 10), line(-30, 0, -20, 0), line(20, 0, 30, 0),
                polyline([(-14, -7), (0, -2), (14, -6)]), polyline([(-14, 7), (0, 2), (14, 6)]), line(0, -20, 0, -2)],
               [T("1", -30, 0, "l"), T("2", 30, 0, "r"), T("X", 0, -20, "u", ptype=pil)], keywords=("sensing",)))
        plate = [line(-20, 0, -4, 0), line(4, 0, 20, 0), line(-4, -6, -4, 6), line(4, -6, 4, 6),
                 line(0, -8, 0, -2), line(0, 2, 0, 8)]
        add(sd(f"{pre}.orificeplate", "Orifice plate (ANSI)", cat, ANSI, "Orifice plate between flanges, in line.",
               plate, [T("1", -20, 0, "l"), T("2", 20, 0, "r")], keywords=("orifice", "sensing")))
        add(sd(f"{pre}.orificeplate.taps", "Orifice plate with pressure taps (ANSI)", cat, ANSI,
               "Orifice plate with upstream and downstream pressure taps X1 and X2.",
               [line(-30, 0, -4, 0), line(4, 0, 30, 0), line(-4, -6, -4, 6), line(4, -6, 4, 6),
                line(0, -8, 0, -2), line(0, 2, 0, 8), line(-10, 0, -10, -20), line(10, 0, 10, -20)],
               [T("1", -30, 0, "l"), T("2", 30, 0, "r"), T("X1", -10, -20, "u", ptype=pil),
                T("X2", 10, -20, "u", ptype=pil)], keywords=("orifice", "differential", "sensing")))
        add(sd(f"{pre}.pitot", "Pitot tube (ANSI)", cat, ANSI,
               "Pitot tube in a line 1 - 2; taps X1 and X2 (static and total pressure) below. Drawn as in "
               "Y32.10 9.2.3.",
               [rect(-15, -15, 15, 15), line(-30, 0, -15, 0), poly(15, 0, 22, -4, 22, 4), line(22, 0, 30, 0),
                line(-10, 0, -10, 20), line(10, 0, 10, 20)],
               [T("1", -30, 0, "l"), T("2", 30, 0, "r"), T("X1", -10, 20, "d", ptype=pil),
                T("X2", 10, 20, "d", ptype=pil)], keywords=("sensing", "velocity")))
        add(sd(f"{pre}.nozzle", "Nozzle (ANSI)", cat, ANSI,
               "Nozzle discharging in the direction of the arrow; inlet 1.",
               [line(-20, 0, 14, 0), arrowhead((20, 0), (14, 0), length=7, half_width=3.5, fill=hyd),
                polyline([(-14, -7), (-4, -5), (6, -4)]), polyline([(-14, 7), (-4, 5), (6, 4)])],
               [T("1", -20, 0, "l")], keywords=("jet",)))
        sw = [rect(-10, -10, 10, 10), circle(-5, 6, 1.6, fill=True, w="thin"), circle(5, 6, 1.6, fill=True, w="thin"),
              circle(1, -6, 1.6, fill=True, w="thin"), line(-5, 6, 1, -6), line(10, 0, 12, 0),
              zigzag(12, 0, 22, 0, n=4, amp=5)]
        add(sd(f"{pre}.pressure.switch.ansi", "Pressure switch (ANSI)", cat, ANSI,
               "Pressure switch: pilot pressure at X operates the contact against the spring (electrical contacts "
               "drawn, no electrical terminals).",
               sw + [line(-30, 0, -24, 0, dash=True, w="thin"), line(-20, 0, -10, 0, dash=True, w="thin")],
               [T("X", -30, 0, "l", ptype=pil)], keywords=("pressostat",),
               notes="Y32.10 draws the pilot line as two dashes."))
        hsw = [rect(-7, -12, 7, 12), circle(-3, -7, 1.4), circle(-3, 7, 1.4), line(-2, 6, 5, 1), circle(5, 1, 1.4),
               line(0, -12, 0, -14), zigzag(0, -14, 0, -26, n=5, amp=4)] + arrow(-6, -16, 6, -28, head=3)
        hsw += [line(7, 0, 22, 0), polyline([(19, -14), (14.5, -5), (19.5, -3), (15.5, 3)]),
                arrowhead((15.5, 3), (17.5, -1.5), length=4), line(0, 12, 0, 20, dash=True, w="thin")]
        add(sd(f"{pre}.pressure.switch", "Pressure switch", cat, ISO,
               "Pressure switch, adjustable: pilot pressure at X (below) operates the contact against the spring; "
               "electrical output drawn, no electrical terminals.", hsw, [T("X", 0, 20, "d", ptype=pil)],
               keywords=("pressostat",)))
    level = [line(-R, -1.5, R, -1.5), line(-R, 1.5, R, 1.5)]
    add(sd("fl.hyd.level.gauge", "Fluid level gauge", "Hydraulic", ISO, "Fluid level gauge (sight glass).",
           body() + level, bottom("1"), keywords=("sight glass", "level")))
    add(sd("fl.hyd.level.transducer", "Fluid level transducer", "Hydraulic", ISO,
           "Fluid level transducer: electrical signal out (drawn, no electrical terminal).",
           body() + level + signal_out(), bottom("1"), keywords=("level", "sensor")))
    return s
