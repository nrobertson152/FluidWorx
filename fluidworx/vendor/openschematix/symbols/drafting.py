"""Drafting marks: non-connectable elements drawn next to or inside other symbols (symbol-library expansion,
batch F2). No terminals, no designator prefix, group "Drafting" (see symbols.base.is_drafting_element).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Basic Symbols" and "Spool Controls" columns);
Y32 = ANSI Y32.10 clauses 2.9-2.13.
"""
from __future__ import annotations

from .base import ANSI, GENERIC, ISO, Geometry, SymbolDef, arc, arrow, arrowhead, circle, line, poly, polyline

G = "Drafting"


def _mark(sid, name, cat, conv, desc, prims, keywords=(), notes=""):
    return SymbolDef(sid, name, cat, G, conv, desc, "", Geometry(prims, []), keywords=keywords, notes=notes)


def symbols():
    s = [
        _mark("gen.arrow.move", "Direction of movement", "General", ISO,
              "Straight arrow: direction of linear movement.",
              arrow(0, 10, 0, -10, head=5), ("linear", "motion")),
        _mark("gen.arrow.move.both", "Direction of movement, both ways", "General", ISO,
              "Double-headed arrow: linear movement in both directions.",
              [line(0, 10, 0, -10), arrowhead((0, -10), (0, 0), length=5),
               arrowhead((0, 10), (0, 0), length=5)], ("linear", "motion", "reciprocating")),
        _mark("gen.arrow.rotation", "Direction of rotation", "General", ISO,
              "Curved arrow: direction of rotation (mirror the element for the other direction).",
              [arc(14, 0, 14, 145, 70), arrowhead((2.53, -8.03), (5.0, -10.6), length=4.5)],
              ("rotation", "turning")),
        _mark("gen.arrow.rotation.shaft", "Direction of rotation looking at shaft", "General", ISO,
              "Rotation arrow across a shaft (double line), seen looking at the shaft end.",
              [line(-12, -2, 12, -2), line(-12, 2, 12, 2), arc(14, 0, 14, 145, 70),
               arrowhead((2.53, -8.03), (5.0, -10.6), length=4.5)], ("shaft", "rotation")),
        _mark("gen.arrow.adjust", "Adjustable (regulation possible)", "General", ISO,
              "Arrow at about 45 degrees: the component can be adjusted or varied (also ANSI Y32.10 2.9).",
              arrow(-10, 8, 10, -8, head=5), ("variable", "adjustable")),
        _mark("gen.mark.compensated", "Pressure compensated (mark)", "General", ANSI,
              "Arrow parallel to the short side of a symbol: the component is pressure compensated.",
              arrow(0, 6, 0, -6, head=4), ("compensation",)),
        _mark("gen.mark.temperature", "Temperature cause or effect (mark)", "General", ANSI,
              "Line ending in a dot: temperature cause or effect (thermometer).",
              [line(0, -10, 0, 6), circle(0, 7.5, 2, fill=True, w="thin")], ("thermometer", "temperature")),
        _mark("gen.mark.electric", "Electric (energy type)", "General", ISO,
              "Electric energy / electrical actuation mark.",
              [polyline([(2, -10), (-2.5, -1), (2.5, 1), (-1.5, 9)]), arrowhead((-1.5, 9), (0.5, 4.5), length=4)],
              ("electrical", "lightning")),
        _mark("gen.mark.solenoids.opposed", "Solenoids working in opposite directions", "General", ISO,
              "Two windings acting in opposite directions.",
              [line(-6, -6, -2, 6), line(6, -6, 2, 6)], ("solenoid", "winding")),
        _mark("gen.mark.buswidth", "Bus width marker", "General", GENERIC,
              "Short slash drawn across a wire to show that it is a bus; write the number of lines beside it "
              "(source: ECL basic logic blocks). Place it over the wire; it does not connect.",
              [line(-4, 6, 4, -6)], ("bus", "width", "multi-line")),
        _mark("gen.coupling", "Shaft coupling", "General", ISO,
              "Mechanical coupling between two shafts.",
              [line(-10, -2, -2, -2), line(-10, 2, -2, 2), line(-2, -6, -2, 6),
               line(2, -6, 2, 6), line(2, -2, 10, -2), line(2, 2, 10, 2)], ("shaft", "mechanical")),
    ]
    for medium, cat, fill, word in (("hyd", "Hydraulic", True, "hydraulic"), ("pneu", "Pneumatic", False, "pneumatic")):
        s.append(_mark(f"fl.{medium}.mark.energy", f"Energy direction, {word}", cat, ISO,
                       f"{'Filled' if fill else 'Hollow'} triangle: {word} energy, pointing in the direction of flow.",
                       [poly(0, -6, 7, 6, -7, 6, fill=fill)], ("triangle", "medium")))
    return s


__all__ = ["symbols", "GENERIC"]
