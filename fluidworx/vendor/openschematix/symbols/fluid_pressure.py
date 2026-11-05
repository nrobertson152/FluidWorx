"""Pressure control valves (symbol-library expansion, batch F7).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Energy Control"); Y32 = ANSI Y32.10 10.13.
Drawn as both sources draw them: inlet on top, outlet below, spring on the left, pilot sensing loop (dashed) on
the right. (The existing fl.*.relief is the same symbol mirrored; rotate a placed symbol to match.)
Normally closed valves show the flow arrow offset from the port axis; normally open valves show it on the axis.
Drains drawn to a reservoir symbol end there (as in the sources); an external drain or pilot is a port (L, X).
Solenoid operators are drawn without electrical terminals, like the configurator's solenoids.
"""
from __future__ import annotations

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arrow, arrowhead, circle, line, poly, polyline, rect, zigzag

G = "Pressure control"


def box():
    return [rect(-15, -15, 15, 15), line(0, -20, 0, -15), line(0, 15, 0, 20)]


def spring(adjustable):
    p = [line(-15, 0, -17, 0), zigzag(-17, 0, -29, 0, n=6, amp=4)]
    if adjustable:
        p += arrow(-30, 8, -17, -8, head=3.5)
    return p


def nc_arrow():
    return arrow(6, -10, 6, 10, head=4)


def no_arrow():
    return arrow(0, -10, 0, 10, head=4)


def double_arrow():
    return [line(0, -10, 0, 10), arrowhead((0, 10), (0, 0), length=4), arrowhead((0, -10), (0, 0), length=4)]


def pilot_from_inlet(dot=False, enter=0):
    p = [polyline([(0, -17), (22, -17), (22, enter), (15, enter)], dash=True, w="thin")]
    if dot:
        p.append(circle(0, -17, 1.6, fill=True, w="thin"))
    return p


def pilot_from_outlet(dot=False):
    p = [polyline([(0, 17), (22, 17), (22, 0), (15, 0)], dash=True, w="thin")]
    if dot:
        p.append(circle(0, 17, 1.6, fill=True, w="thin"))
    return p


def drain_to_tank():
    """Drain from the spring chamber to a reservoir symbol below the spring."""
    return [line(-23, 5, -23, 23, dash=True, w="thin"), polyline([(-27, 20), (-27, 26), (-19, 26), (-19, 20)])]


def solenoid(proportional):
    p = [rect(15, -2, 33, 10), line(15, 10, 33, -2)]
    if proportional:
        p += arrow(17, 14, 36, -8, head=3.5, w="thin")
    return p


def io(medium, outlet):
    """Inlet (top) and outlet (bottom) names."""
    if medium == "hyd":
        return [T("P", 0, -20, "u"), T(outlet, 0, 20, "d")]
    return [T("1", 0, -20, "u"), T("3" if outlet == "T" else "2", 0, 20, "d")]


def symbols():
    s = []
    add = s.append
    H = "Hydraulic"
    sd = lambda sid, name, cat, conv, desc, prims, terms, **kw: SymbolDef(  # noqa: E731
        sid, name, cat, G, conv, desc, "V", Geometry(prims, terms), **kw)
    # ---------------------------------------------------------------- ISO (HydraulicsOnline chart), hydraulic
    add(sd("fl.hyd.relief.pilot", "Pressure-relief valve, pilot operated", H, ISO,
           "Pressure-relief valve, pilot operated (normally closed), pilot from the inlet.",
           box() + spring(False) + nc_arrow() + pilot_from_inlet(), io("hyd", "T"), keywords=("rv", "safety")))
    add(sd("fl.hyd.sequence", "Sequence valve", H, ISO,
           "Sequence valve, adjustable, pilot from the inlet; drain to the reservoir.",
           box() + spring(True) + nc_arrow() + pilot_from_inlet() + drain_to_tank(), io("hyd", "A")))
    add(sd("fl.hyd.unloading", "Relief / unloading valve, external pilot", H, ISO,
           "Relief / unloading valve with external hydraulic pilot X and internal drain.",
           box() + spring(True) + nc_arrow() + pilot_from_inlet()
           + [polyline([(15, 10), (30, 10)], dash=True, w="thin")],
           io("hyd", "T") + [T("X", 30, 10, "r")], keywords=("unloader",)))
    add(sd("fl.hyd.reducing.drain", "Pressure-reducing valve with drain", H, ISO,
           "Pressure-reducing valve (normally open), pilot from the outlet, drain to the reservoir.",
           box() + spring(False) + no_arrow() + pilot_from_outlet() + drain_to_tank(), io("hyd", "A"),
           keywords=("prv",)))
    add(sd("fl.hyd.unloading.sol", "Unloading valve, solenoid operated", H, ISO,
           "Electrical unloading valve: pilot-operated relief vented by a solenoid.",
           box() + spring(False) + nc_arrow() + pilot_from_inlet(enter=-8) + solenoid(False), io("hyd", "T"),
           keywords=("solenoid", "vent")))
    add(sd("fl.hyd.relief.prop", "Pressure-relief valve, proportional solenoid", H, ISO,
           "Electrical proportional relief valve: relief setting by a proportional solenoid.",
           box() + spring(False) + nc_arrow() + pilot_from_inlet(enter=-8) + solenoid(True), io("hyd", "T"),
           keywords=("proportional", "solenoid")))
    # ---------------------------------------------------------------- ANSI Y32.10 10.13
    for medium, cat in (("hyd", H), ("pneu", "Pneumatic")):
        pre = f"fl.{medium}"
        add(sd(f"{pre}.relief.ansi", "Pressure-relief valve (ANSI)", cat, ANSI,
               "Pressure relief, normally closed, pilot from the inlet. The same drawing is used for a sequence "
               "valve with internal drain (10.13.2) - the outlet connection tells them apart.",
               box() + spring(True) + nc_arrow() + pilot_from_inlet(dot=True), io(medium, "T"),
               keywords=("rv", "sequence")))
        add(sd(f"{pre}.sequence.drain", "Sequence valve, external drain (ANSI)", cat, ANSI,
               "Sequence valve, pilot from the inlet, drain to the reservoir.",
               box() + spring(True) + nc_arrow() + pilot_from_inlet(dot=True) + drain_to_tank(), io(medium, "A")))
        add(sd(f"{pre}.reducing.ansi", "Pressure-reducing valve (ANSI)", cat, ANSI,
               "Pressure reducing, normally open, pilot from the outlet.",
               box() + spring(True) + no_arrow() + pilot_from_outlet(dot=True), io(medium, "A"),
               keywords=("prv", "regulator")))
    add(sd("fl.hyd.reducing.drain.ansi", "Pressure-reducing valve with drain (ANSI)", H, ANSI,
           "Pressure reducing, normally open, pilot from the outlet, drain to the reservoir.",
           box() + spring(True) + no_arrow() + pilot_from_outlet(dot=True) + drain_to_tank(), io("hyd", "A")))
    add(sd("fl.hyd.reducing.relieving", "Pressure-reducing and relieving valve (ANSI)", H, ANSI,
           "Pressure reducing and relieving: flow either way through the valve; relieving path from the inlet "
           "line to the reservoir; pilot from the outlet; drain to the reservoir.",
           box() + spring(True) + double_arrow() + pilot_from_outlet(dot=True) + drain_to_tank()
           + [polyline([(0, -18), (-35, -18), (-35, -10)]), polyline([(-39, -12), (-39, -6), (-31, -6), (-31, -12)])],
           io("hyd", "A")))
    add(sd("fl.pneu.regulator.relieving", "Pressure regulator, relieving (ANSI)", "Pneumatic", ANSI,
           "Airline pressure regulator, adjustable, relieving (vents to atmosphere).",
           box() + spring(True) + double_arrow() + pilot_from_outlet(dot=True)
           + [line(-8, -15, -8, -19), poly(-8, -25, -12, -19, -4, -19)], io("pneu", "A"),
           keywords=("regulator", "frl")))
    return s
