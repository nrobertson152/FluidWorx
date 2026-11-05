"""Pumps, motors, pump-motors and rotary actuators (symbol-library expansion, batch F5).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Energy Transformations"); Y32 = ANSI Y32.10 section 8.
Body as the existing fl.hyd.pump (circle r = 12, ports on the vertical axis). Energy triangles: a pump's point
out of the body at its outlet; a motor's point into the body at its inlet.
ISO forms (HO) carry the double-line drive shaft of the existing pump. ANSI "simplified" forms have no shaft;
ANSI "complete" forms add the control box (left), a single-line shaft with rotation arrow (right) and the case
drain to a reservoir symbol, all as drawn in Y32.10 8.1.2 / 8.2 / 8.4 - the drain ends in that reservoir
symbol, so it is not a separate port.
"""
from __future__ import annotations

import math

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arc, arrow, arrowhead, circle, line, poly, polyline

H, P = "Hydraulic", "Pneumatic"
G = "Pumps & motors"
R = 12.0
CHORD = math.sqrt(R * R - 36)                 # half-width of the body at y = +-6


def body():
    return [circle(0, 0, R), line(0, -20, 0, -R), line(0, R, 0, 20)]


def tri_out_top(fill=True):
    return poly(0, -R, -4.5, -4.5, 4.5, -4.5, fill=fill)


def tri_out_bottom(fill=True):
    return poly(0, R, -4.5, 4.5, 4.5, 4.5, fill=fill)


def tri_in_top(fill=True):
    y = -math.sqrt(R * R - 36)
    return poly(-6, y, 6, y, 0, -4.5, fill=fill)


def tri_in_bottom(fill=True):
    y = math.sqrt(R * R - 36)
    return poly(-6, y, 6, y, 0, 4.5, fill=fill)


def hourglass_top():
    """Y32 8.4.1 / 8.4.3: at the port, one triangle pointing out and one pointing in (pump or motor)."""
    return [poly(-3.5, -R + 1, 3.5, -R + 1, 0, -6.5, fill=True), poly(-3.5, -1.5, 3.5, -1.5, 0, -6.5, fill=True)]


def hourglass_bottom():
    return [poly(-3.5, R - 1, 3.5, R - 1, 0, 6.5, fill=True), poly(-3.5, 1.5, 3.5, 1.5, 0, 6.5, fill=True)]


def variable():
    return arrow(-11, 11, 13, -13, head=4.5)


def iso_shaft():
    return [line(R, -1.5, 19, -1.5, w="thin"), line(R, 1.5, 19, 1.5, w="thin")]


def ansi_shaft(both_ways=False):
    """Single-line shaft with a rotation arrow (on the near side of the shaft, Y32 2.13)."""
    cx, r = 35.0, 12.0
    pt = lambda a: (cx + r * math.cos(math.radians(a)), -r * math.sin(math.radians(a)))  # noqa: E731
    p = [line(R, 0, 38, 0), arc(cx, 0, r, 135, 90), arrowhead(pt(135), pt(147), length=5, half_width=2.2)]
    if both_ways:
        p.append(arrowhead(pt(225), pt(213), length=5, half_width=2.2))
    return p


def control_box(compensated=False):
    p = [line(-32, -6, -CHORD, -6), line(-32, 6, -CHORD, 6), line(-32, -6, -32, 6)]
    if compensated:
        p.append(poly(-28, 5, -20, 5, -24, -3, fill=True))
    return p


def pc_inside():
    """Y32 8.2.3 simplified: pressure-compensation triangle inside the body."""
    return [poly(-9.5, 6, -2.5, 6, -6, -1.5, fill=True)]


def case_drain():
    """Dashed case drain from the lower left of the body to a reservoir symbol (Y32.10 8.1.2)."""
    a = math.radians(235)
    x0, y0 = R * math.cos(a), -R * math.sin(a)
    return [polyline([(x0, y0), (-10, 14), (-10, 23)], dash=True, w="thin"),
            polyline([(-14, 20), (-14, 26), (-6, 26), (-6, 20)])]


def iso_drain():
    """HO: dashed drain from the body's left side to a reservoir symbol."""
    return [line(-R, 0, -18, 0, dash=True, w="thin"), line(-18, 0, -18, 13, dash=True, w="thin"),
            polyline([(-22, 10), (-22, 16), (-14, 16), (-14, 10)])]


def complete(*parts, compensated=False, both_ways=False):
    return body() + control_box(compensated) + ansi_shaft(both_ways) + case_drain() + \
        [p for group in parts for p in group]


def sd(sid, name, cat, conv, desc, prims, terms, prefix="P", **kw):
    return SymbolDef(sid, name, cat, G, conv, desc, prefix, Geometry(prims, terms), **kw)


def ps():
    return [T("P", 0, -20, "u"), T("S", 0, 20, "d")]


def ab():
    return [T("A", 0, -20, "u"), T("B", 0, 20, "d")]


def symbols():
    s = []
    add = s.append
    # ---------------------------------------------------------------- ISO (HydraulicsOnline chart)
    add(sd("fl.hyd.motor.bidir", "Motor, fixed displacement, reversible", H, ISO,
           "Hydraulic motor, fixed displacement, two directions of rotation, without drain.",
           body() + [tri_in_top(), tri_in_bottom()] + iso_shaft(), ab(), "M"))
    add(sd("fl.hyd.motor.bidir.drain", "Motor, fixed displacement, reversible, with drain", H, ISO,
           "Reversible fixed-displacement motor with case drain to the reservoir.",
           body() + [tri_in_top(), tri_in_bottom()] + iso_shaft() + iso_drain(), ab(), "M"))
    add(sd("fl.hyd.pump.bidir.drain", "Pump, fixed displacement, reversible, with drain", H, ISO,
           "Reversible fixed-displacement pump (flow in either direction) with case drain to the reservoir.",
           body() + [tri_out_top(), tri_out_bottom()] + iso_shaft() + iso_drain(), ab()))
    add(sd("fl.hyd.rotary", "Rotary actuator", H, ISO,
           "Rotary (limited-angle) actuator.",
           body() + iso_shaft() + [poly(-10, -7, -10, -1, -5, -4, fill=True), poly(-10, 1, -10, 7, -5, 4, fill=True)],
           ab(), "M", keywords=("semi-rotary", "oscillating"),
           notes="Port positions follow the chart's other rotary devices; the chart's figure does not show them."))
    # ---------------------------------------------------------------- ANSI Y32.10 hydraulic pumps
    add(sd("fl.hyd.pump.ansi", "Pump, fixed, unidirectional (ANSI)", H, ANSI,
           "Hydraulic pump, fixed displacement, one direction of flow (simplified, no shaft).",
           body() + [tri_out_top()], ps()))
    add(sd("fl.hyd.pump.bidir", "Pump, fixed, bidirectional (ANSI)", H, ANSI,
           "Hydraulic pump, fixed displacement, flow in either direction.",
           body() + [tri_out_top(), tri_out_bottom()], ab()))
    for comp, ctag, cword in ((False, "var", "non-compensated"), (True, "pc", "pressure compensated")):
        for bidir in (False, True):
            tris = [tri_out_top()] + ([tri_out_bottom()] if bidir else [])
            terms = ab() if bidir else ps()
            dirw = "bidirectional" if bidir else "unidirectional"
            base = f"fl.hyd.pump.{ctag}" + (".bidir" if bidir else "")
            simple_id = base + (".ansi" if base == "fl.hyd.pump.var" else "")
            add(sd(simple_id, f"Pump, variable, {cword}, {dirw} (ANSI)", H, ANSI,
                   f"Variable-displacement pump, {cword}, {dirw} (simplified).",
                   body() + tris + variable() + (pc_inside() if comp else []), list(terms)))
            add(sd(base + ".full", f"Pump, variable, {cword}, {dirw}, complete (ANSI)", H, ANSI,
                   f"Variable-displacement pump, {cword}, {dirw}: control, shaft with rotation and case drain.",
                   complete(tris, variable(), compensated=comp), list(terms)))
    # pump-motors (Y32 8.4)
    add(sd("fl.hyd.pumpmotor.rev", "Pump-motor: pump one way, motor the other (ANSI)", H, ANSI,
           "Operating in one direction as a pump, in the other as a motor (simplified).",
           body() + hourglass_top() + variable(), ab()))
    add(sd("fl.hyd.pumpmotor.rev.full", "Pump-motor: pump one way, motor the other, complete (ANSI)", H, ANSI,
           "Operating in one direction as a pump, in the other as a motor: control, shaft, rotation both ways.",
           complete(hourglass_top(), variable(), both_ways=True), ab()))
    add(sd("fl.hyd.pumpmotor", "Pump-motor, one flow direction (ANSI)", H, ANSI,
           "One direction of flow, operating as either a pump or a motor (simplified).",
           body() + [tri_out_top(), tri_in_bottom()] + variable(), ab()))
    add(sd("fl.hyd.pumpmotor.full", "Pump-motor, one flow direction, complete (ANSI)", H, ANSI,
           "One direction of flow as a pump or a motor: control, shaft with rotation.",
           complete([tri_out_top(), tri_in_bottom()], variable()), ab()))
    add(sd("fl.hyd.pumpmotor.bidir.pc", "Pump-motor, both flow directions, variable, compensated (ANSI)", H, ANSI,
           "Either flow direction as a pump or a motor; variable displacement, pressure compensated (simplified).",
           body() + hourglass_top() + hourglass_bottom() + variable() + pc_inside(), ab()))
    add(sd("fl.hyd.pumpmotor.bidir.pc.full",
           "Pump-motor, both flow directions, variable, compensated, complete (ANSI)", H, ANSI,
           "Either flow direction as a pump or a motor, variable, pressure compensated: control, shaft, rotation.",
           complete(hourglass_top(), hourglass_bottom(), variable(), compensated=True, both_ways=True), ab()))
    # oscillators (Y32 8.7)
    for medium, cat, fill in (("hyd", H, True), ("pneu", P, False)):
        dome = [arc(0, 4, R, 0, 180), line(-R, 4, R, 4), line(-10, 4, -10, 20), line(10, 4, 10, 20),
                poly(-13, 4, -7, 4, -10, -2, fill=fill), poly(7, 4, 13, 4, 10, -2, fill=fill)]
        names = ("A", "B") if medium == "hyd" else ("2", "4")
        add(sd(f"fl.{medium}.rotary" + (".ansi" if medium == "hyd" else ""),
               "Oscillator (rotary actuator, ANSI)", cat, ANSI,
               "Oscillating (limited-rotation) actuator.", dome,
               [T(names[0], -10, 20, "d"), T(names[1], 10, 20, "d")], "M", keywords=("rotary actuator",)))
    # pneumatic (Y32 8.5 / 8.6)
    add(sd("fl.pneu.compressor.ansi", "Compressor, fixed displacement (ANSI)", P, ANSI,
           "Compressor, fixed displacement (simplified, no shaft).",
           body() + [tri_out_top(False)], [T("2", 0, -20, "u"), T("1", 0, 20, "d")]))
    add(sd("fl.pneu.vacuumpump", "Vacuum pump, fixed displacement (ANSI)", P, ANSI,
           "Vacuum pump, fixed displacement.",
           body() + [tri_out_top(False), poly(0, -19, -3.5, -14, 3.5, -14)],
           [T("2", 0, -20, "u"), T("1", 0, 20, "d")], keywords=("vacuum",)))
    add(sd("fl.pneu.motor.ansi", "Air motor, unidirectional (ANSI)", P, ANSI,
           "Pneumatic motor, one direction of rotation (simplified, no shaft).",
           body() + [tri_in_top(False)], [T("1", 0, -20, "u"), T("2", 0, 20, "d")], "M"))
    # ---------------------------------------------------------------- batch F5b: ANSI motors (director decision D1)
    # Y32.10 8.3.x and 8.6.2 print these motors with the triangles pointing OUT of the body, exactly like the
    # pumps. They are drawn here with the triangles pointing IN (as Y32.10 8.6.1 and every other motor symbol),
    # so that a motor can be told from a pump. This is a deliberate departure from the printed figures.
    dep = ("Interpretation: Y32.10 prints this figure with outward (pump-like) triangles; drawn with inward motor "
           "triangles by director decision D1.")
    add(sd("fl.hyd.motor.ansi", "Motor, fixed, unidirectional (ANSI)", H, ANSI,
           "Hydraulic motor, fixed displacement, one direction of rotation (simplified, no shaft); inlet A.",
           body() + [tri_in_top()], ab(), "M", notes=dep + " Y32.10's second orientation is the same symbol rotated."))
    add(sd("fl.hyd.motor.bidir.ansi", "Motor, fixed, bidirectional (ANSI)", H, ANSI,
           "Hydraulic motor, fixed displacement, two directions of rotation (simplified, no shaft).",
           body() + [tri_in_top(), tri_in_bottom()], ab(), "M", notes=dep))
    add(sd("fl.hyd.motor.var", "Motor, variable, unidirectional (ANSI)", H, ANSI,
           "Hydraulic motor, variable displacement, one direction of rotation (simplified, no shaft); inlet A.",
           body() + [tri_in_top()] + variable(), ab(), "M", notes=dep))
    add(sd("fl.hyd.motor.var.bidir", "Motor, variable, bidirectional (ANSI)", H, ANSI,
           "Hydraulic motor, variable displacement, two directions of rotation (simplified, no shaft).",
           body() + [tri_in_top(), tri_in_bottom()] + variable(), ab(), "M", notes=dep))
    add(sd("fl.pneu.motor.bidir", "Air motor, bidirectional (ANSI)", P, ANSI,
           "Pneumatic motor, two directions of rotation (simplified, no shaft).",
           body() + [tri_in_top(False), tri_in_bottom(False)],
           [T("2", 0, -20, "u", ptype="pneu.work"), T("4", 0, 20, "d", ptype="pneu.work")], "M", notes=dep))
    return s
