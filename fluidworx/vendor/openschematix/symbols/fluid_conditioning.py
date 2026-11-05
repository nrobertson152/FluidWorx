"""Fluid conditioning: heat exchangers, separators, dryers, lubricators, breathers (library expansion, batch F4).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Fluid Treatment"); Y32 = ANSI Y32.10 section 5.
All are drawn with horizontal through-flow like the existing fl.*.filter (the chart draws its coolers with
vertical flow; Y32.10 2.3 allows rotation without change of meaning).
Ports: through-flow 1 and 2; drains L (hydraulic) / 3 (pneumatic); heating or cooling medium lines C1 (out) and
C2 (in) with port type "any", because the medium (water, air, steam) is not part of the fluid power circuit.
"""
from __future__ import annotations

import math

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arrow, arrowhead, circle, line, poly, polyline, rect

MEDIA = (("hyd", "Hydraulic", True), ("pneu", "Pneumatic", False))
G = "Fluid conditioning"


def diamond(h):
    return poly(-h, 0, 0, -h, h, 0, 0, h)


def leads(h, reach):
    return [line(-reach, 0, -h, 0), line(h, 0, reach, 0)]


def through(h=15, reach=30):
    return [T("1", -reach, 0, "l"), T("2", reach, 0, "r")]


# ---------------------------------------------------------------- heat exchangers (diamond half-size 15)
H15 = 15


def inner_arrows_out():
    """Heat dissipation (ISO cooler; Y32 5.1.2 first form): line with arrowheads at the corners."""
    return [line(0, -H15 + 4, 0, H15 - 4), arrowhead((0, -H15), (0, 0), length=5, half_width=2.5),
            arrowhead((0, H15), (0, 0), length=5, half_width=2.5)]


def inner_arrows_in_iso():
    """Introduction of heat (ISO heater): arrowheads meeting at the centre."""
    return [line(0, -H15, 0, H15), arrowhead((0, -1), (0, -H15), length=5, half_width=2.5),
            arrowhead((0, 1), (0, H15), length=5, half_width=2.5)]


def inner_triangles_in():
    """Introduction of heat (Y32 5.1.1): filled triangles pointing to the centre on a vertical line."""
    return [line(0, -H15, 0, H15), poly(-3.5, -8, 3.5, -8, 0, 0, fill=True, w="thin"),
            poly(-3.5, 8, 3.5, 8, 0, 0, fill=True, w="thin")]


def filled_corners():
    """Y32 5.1.2 second form: corners filled in to represent the heat-dissipation triangles."""
    return [poly(0, -H15, -5, -H15 + 5, 5, -H15 + 5, fill=True, w="thin"),
            poly(0, H15, -5, H15 - 5, 5, H15 - 5, fill=True, w="thin")]


def medium_lines(fill):
    """Y32 5.1.1b/c, 5.1.2b, 5.1.3b: medium lines leaving the lower edges, triangles show the medium
    (filled = liquid, hollow = gaseous); C1 out (left, pointing away), C2 in (right, pointing in)."""
    return [line(-10, 5, -10, 20), line(10, 5, 10, 20),
            poly(-13.5, 12, -6.5, 12, -10, 18, fill=fill, w="thin"),
            poly(6.5, 13, 13.5, 13, 10, 7, fill=fill, w="thin")]


def medium_ports():
    return [T("C1", -10, 20, "d", ptype="any"), T("C2", 10, 20, "d", ptype="any")]


def ellipse(cx, cy, rx, ry, n=24):
    pts = [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
    return polyline(pts, w="thin")


def coolant_arrows(y0):
    """HO water/oil cooler: coolant flow arrows beside the exchanger (not connections)."""
    return [line(-6, y0, -6, y0 + 10), arrowhead((-6, y0 + 10), (-6, y0), length=4),
            line(6, y0 + 10, 6, y0), arrowhead((6, y0), (6, y0 + 10), length=4)]


def hx(*extra, h=H15):
    return [diamond(h)] + leads(h, 30) + [p for group in extra for p in group]


# ---------------------------------------------------------------- filters, separators (half-size 10, as fl.*.filter)
def small(*extra):
    return [diamond(10)] + leads(10, 20) + [p for group in extra for p in group]


def dashed_element(y0=-10, y1=10):
    return [line(0, y0, 0, y1, dash=True, w="thin")]


def separator_line():
    return [line(-5, 5, 5, 5)]


def drain():
    return [line(0, 10, 0, 20)]


def auto_drain():
    return [poly(-3.5, 6.5, 3.5, 6.5, 0, 9.5, w="thin")]


def symbols():
    s = []
    add = s.append
    for medium, cat, fill in MEDIA:
        pre = f"fl.{medium}"
        dname = "L" if medium == "hyd" else "3"
        drain_t = T(dname, 0, 20, "d")
        # ---- ISO (HO)
        add(SymbolDef(f"{pre}.heater", "Heater", cat, G, ISO, "Heater: heat introduced into the fluid.", "Z",
                      Geometry(hx(inner_arrows_in_iso()), through()), keywords=("heat exchanger",)))
        add(SymbolDef(f"{pre}.cooler", "Cooler", cat, G, ISO,
                      "Cooler: heat dissipated from the fluid (ANSI Y32.10 5.1.2 first form is drawn the same way).",
                      "Z", Geometry(hx(inner_arrows_out()), through()), keywords=("heat exchanger", "oil cooler")))
        add(SymbolDef(f"{pre}.filter.indicator", "Filter with clogging indicator", cat, G, ISO,
                      "Filter with visual contamination indicator.", "Z",
                      Geometry(small(dashed_element(), [line(0, -10, 0, -14), circle(0, -18, 4),
                                                         line(-2.83, -20.83, 2.83, -15.17),
                                                         line(-2.83, -15.17, 2.83, -20.83)]),
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r")]), keywords=("indicator", "differential")))
        # ---- ANSI Y32.10 section 5
        add(SymbolDef(f"{pre}.conditioner", "Fluid conditioner, general (ANSI)", cat, G, ANSI,
                      "Device controlling the physical characteristics of the fluid, general symbol.", "Z",
                      Geometry(small(), [T("1", -20, 0, "l"), T("2", 20, 0, "r")])))
        add(SymbolDef(f"{pre}.heater.ansi", "Heater (ANSI)", cat, G, ANSI,
                      "Heater; inside triangles indicate the introduction of heat.", "Z",
                      Geometry(hx(inner_triangles_in()), through())))
        for mfill, mword in ((True, "liquid"), (False, "gas")):
            label = "liquid" if mfill else "gaseous"
            add(SymbolDef(f"{pre}.heater.{mword}", f"Heater, {label} heating medium (ANSI)", cat, G, ANSI,
                          f"Heater with {label} heating-medium lines (C1 out, C2 in).", "Z",
                          Geometry(hx(inner_triangles_in(), medium_lines(mfill)), through() + medium_ports())))
            add(SymbolDef(f"{pre}.cooler.lines.{mword}", f"Cooler, {label} coolant (ANSI)", cat, G, ANSI,
                          f"Cooler with {label} coolant lines (C1 out, C2 in).", "Z",
                          Geometry(hx(inner_arrows_out(), medium_lines(mfill)), through() + medium_ports())))
            add(SymbolDef(f"{pre}.tempcontrol.{mword}", f"Temperature controller, {label} medium (ANSI)", cat, G,
                          ANSI, f"Temperature controller (heating and cooling) with {label} medium lines.", "Z",
                          Geometry(hx(inner_arrows_out(), inner_triangles_in()[1:], medium_lines(mfill)),
                                   through() + medium_ports())))
        add(SymbolDef(f"{pre}.cooler.ansi", "Cooler, filled corners (ANSI)", cat, G, ANSI,
                      "Cooler drawn with the corners filled in to represent heat dissipation.", "Z",
                      Geometry(hx([line(0, -H15 + 5, 0, H15 - 5)], filled_corners()), through())))
        add(SymbolDef(f"{pre}.tempcontrol", "Temperature controller (ANSI)", cat, G, ANSI,
                      "Temperature maintained between two predetermined limits (heating and cooling).", "Z",
                      Geometry(hx(inner_arrows_out(), inner_triangles_in()[1:]), through()),
                      keywords=("thermostat",)))
        add(SymbolDef(f"{pre}.separator", "Separator with manual drain (ANSI)", cat, G, ANSI,
                      "Separator (e.g. water separator) with manual drain.", "Z",
                      Geometry(small(separator_line(), drain()),
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r"), drain_t]), keywords=("water trap",)))
        add(SymbolDef(f"{pre}.separator.auto", "Separator with automatic drain (ANSI)", cat, G, ANSI,
                      "Separator with automatic drain.", "Z",
                      Geometry(small(separator_line(), auto_drain(), drain()),
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r"), drain_t]), keywords=("water trap",)))
        add(SymbolDef(f"{pre}.filtersep", "Filter-separator with manual drain (ANSI)", cat, G, ANSI,
                      "Filter and separator with manual drain.", "Z",
                      Geometry(small(dashed_element(-10, 5), separator_line(), drain()),
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r"), drain_t]), keywords=("coalescing",)))
        add(SymbolDef(f"{pre}.filtersep.auto", "Filter-separator with automatic drain (ANSI)", cat, G, ANSI,
                      "Filter and separator with automatic drain.", "Z",
                      Geometry(small(dashed_element(-10, 5), separator_line(), auto_drain(), drain()),
                               [T("1", -20, 0, "l"), T("2", 20, 0, "r"), drain_t]), keywords=("coalescing",)))
    # hydraulic only (HO)
    H = "Hydraulic"
    add(SymbolDef("fl.hyd.cooler.liquid", "Water / oil cooler", H, G, ISO,
                  "Oil cooler with liquid coolant; the arrows show the coolant flow (not connections).", "Z",
                  Geometry(hx(inner_arrows_out(), coolant_arrows(17)), through()), keywords=("heat exchanger",)))
    add(SymbolDef("fl.hyd.cooler.air", "Air / oil cooler", H, G, ISO,
                  "Oil cooler with air cooling by fan; arrows show the air flow (not connections).", "Z",
                  Geometry(hx(inner_arrows_out(), [line(-6, -27, -6, -17), arrowhead((-6, -17), (-6, -27), length=4),
                                                    line(6, -17, 6, -27), arrowhead((6, -27), (6, -17), length=4),
                                                    ellipse(-5, 21, 5, 2.5), ellipse(5, 21, 5, 2.5)]), through()),
                  keywords=("heat exchanger", "fan")))
    add(SymbolDef("fl.hyd.breather", "Breather with filter", H, G, ISO,
                  "Reservoir air breather with filter element.", "Z",
                  Geometry([poly(-10, 0, 0, -10, 10, 0, 0, 10), line(-10, 0, 10, 0, dash=True, w="thin"),
                            line(0, 10, 0, 20), line(0, -10, 0, -16), poly(0, -22, -4, -16, 4, -16)],
                           [T("1", 0, 20, "d")]),
                  keywords=("air breather", "vent", "filler"),
                  notes="A small element drawn between the vent and the filter in the source chart is not legible "
                        "and is not reproduced."))
    P = "Pneumatic"
    add(SymbolDef("fl.pneu.dryer", "Air dryer, desiccant (ANSI)", P, G, ANSI, "Desiccator (chemical dryer).", "Z",
                  Geometry(small([line(-5, -5, 5, -5), line(-5, 5, 5, 5)]),
                           [T("1", -20, 0, "l"), T("2", 20, 0, "r")]), keywords=("desiccator", "dryer")))
    add(SymbolDef("fl.pneu.lubricator", "Lubricator (ANSI)", P, G, ANSI, "Lubricator without drain.", "Z",
                  Geometry(small([line(0, -10, 0, -4)]), [T("1", -20, 0, "l"), T("2", 20, 0, "r")]),
                  keywords=("oiler", "frl")))
    add(SymbolDef("fl.pneu.lubricator.drain", "Lubricator with manual drain (ANSI)", P, G, ANSI,
                  "Lubricator with manual drain.", "Z",
                  Geometry(small([line(0, -10, 0, -4)], drain()),
                           [T("1", -20, 0, "l"), T("2", 20, 0, "r"), T("3", 0, 20, "d")]), keywords=("oiler", "frl")))
    # batch F10: Y32.10 11.2, simplified (a single defined symbol; the composite form stays excluded, Q3)
    add(SymbolDef("fl.pneu.frl", "Airline accessories (FRL), simplified (ANSI)", P, G, ANSI,
                  "Filter, regulator and lubricator unit, simplified symbol: adjustable regulator with gauge in one "
                  "body; flow 1 -> 2.", "Z",
                  Geometry([rect(-25, -12, 25, 12), line(-50, 0, -25, 0), poly(-42, -5, -42, 5, -34, 0),
                            line(25, 0, 40, 0), line(-17, -12, -17, -4), line(17, -15, 17, -6), circle(0, 0, 8),
                            poly(-3, -5, -0.5, -6.5, 3.5, 5.5, fill=True)] + arrow(-13, 15, 13, -14, head=4),
                           [T("1", -50, 0, "l"), T("2", 40, 0, "r")]),
                  keywords=("frl", "service unit", "filter regulator lubricator"),
                  notes="The open triangle on the inlet line is drawn as in Y32.10 11.2."))
    return s
