"""Cylinders and linear devices (symbol-library expansion, batch F6).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Energy Transformations"); Y32 = ANSI Y32.10 section 6.
ISO forms use the existing fl.*.cyl.double style (body -30..20 x -10..10, thick piston line, single-line rod,
ports A cap end at x = -20 and B rod end at x = 10 on top). ANSI forms draw the piston as a double line
(a thin rectangle), as Y32.10 does. Each symbol is defined for both media.
"""
from __future__ import annotations

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arrow, line, poly, rect

MEDIA = (("hyd", "Hydraulic", "Cylinders"), ("pneu", "Pneumatic", "Actuators"))


def body():
    return [rect(-30, -10, 20, 10)]


def ports(rod_end=True):
    p = [line(-20, -20, -20, -10)]
    if rod_end:
        p.append(line(10, -20, 10, -10))
    return p


def piston_iso(x=-10):
    return [line(x, -10, x, 10, w="thick")]


def piston_ansi(x=-12):
    """ANSI piston (double line) between the cap-end port A (x = -20) and the rod-end port B (x = 10), so
    each port enters its own chamber."""
    return [rect(x, -10, x + 4, 10)]


def rod(x0, x1=35):
    return [line(x0, 0, x1, 0)]


def terms(rod_end=True):
    t = [T("A", -20, -20, "u")]
    if rod_end:
        t.append(T("B", 10, -20, "u"))
    return t


def iso_damping(both):
    """HO: cushion boss at the piston, with an adjustment arrow (variable damping)."""
    p = [rect(-18, -5, -10, 5)]
    if both:
        p.append(rect(-10, -5, -2, 5))
    p += arrow(-22, 9, -4 if both else -12, -9, head=4)
    return p


def telescopic(double):
    """HO telescopic cylinder: nested stages leaving the body's rod end."""
    p = [line(-30, -10, -30, 10), line(-30, -10, 5, -10), line(-30, 10, 5, 10), line(5, -10, 5, -7),
         line(5, 10, 5, 7),
         line(-5, -7, 15, -7), line(-5, 7, 15, 7), line(15, -7, 15, -4), line(15, 7, 15, 4),
         line(5, -4, 30, -4), line(5, 4, 30, 4), line(30, -4, 30, 4)]
    if double:
        p += [line(-5, -7, -5, 7, w="thick"), line(5, -4, 5, 4, w="thick")]
        p += [line(-20, -20, -20, -10), line(0, -20, 0, -10)]
        return p, [T("A", -20, -20, "u"), T("B", 0, -20, "u")]
    p.append(line(-20, -20, -20, -10))
    return p, [T("A", -20, -20, "u")]


def symbols():
    s = []
    add = s.append
    for medium, cat, grp in MEDIA:
        pre = f"fl.{medium}"
        sd = lambda sid, name, conv, desc, prims, t, **kw: SymbolDef(  # noqa: E731
            f"{pre}.{sid}", name, cat, grp, conv, desc, "A", Geometry(prims, t),
            keywords=kw.pop("keywords", ("ram", "actuator")), **kw)
        # ---------------------------------------------------------------- ISO (HydraulicsOnline chart)
        add(sd("cyl.single.ret", "Cylinder, single-acting (return by external force)", ISO,
               "Single-acting cylinder without spring: returned by load or external force. A = cap-end port; the "
               "rod-end stub is a vent, not a connection.",
               body() + piston_iso() + rod(-10) + [line(-20, -20, -20, -10), line(10, -14, 10, -10)], terms(False)))
        add(sd("cyl.double.damp1", "Cylinder, double-acting, adjustable damping one end", ISO,
               "Double-acting cylinder with adjustable cushioning (damping) at the cap end.",
               body() + piston_iso() + rod(-10) + ports() + iso_damping(False), terms(),
               keywords=("cushion", "ram")))
        add(sd("cyl.double.damp2", "Cylinder, double-acting, adjustable damping both ends", ISO,
               "Double-acting cylinder with adjustable cushioning at both ends.",
               body() + piston_iso() + rod(-10) + ports() + iso_damping(True), terms(),
               keywords=("cushion", "ram")))
        p, t = telescopic(True)
        add(sd("cyl.tele.double", "Cylinder, telescopic, double-acting", ISO,
               "Double-acting telescopic (multi-stage) cylinder.", p, t, keywords=("multi-stage", "ram")))
        p, t = telescopic(False)
        add(sd("cyl.tele.single", "Cylinder, telescopic, single-acting", ISO,
               "Single-acting telescopic (multi-stage) cylinder, returned by external force.", p, t,
               keywords=("multi-stage", "ram")))
        # ---------------------------------------------------------------- ANSI Y32.10 section 6
        add(sd("cyl.single.ret.ansi", "Cylinder, single-acting (ANSI)", ANSI,
               "Single-acting cylinder: body open at the rod end. A = cap-end port.",
               [line(-30, -10, -30, 10), line(-30, -10, 20, -10), line(-30, 10, 20, 10)] + piston_ansi()
               + rod(-8) + [line(-20, -20, -20, -10)], terms(False)))
        add(sd("cyl.double.ansi", "Cylinder, double-acting (ANSI)", ANSI,
               "Double-acting cylinder, single end rod.", body() + piston_ansi() + rod(-8) + ports(), terms()))
        add(sd("cyl.doublerod.ansi", "Cylinder, double-acting, double end rod (ANSI)", ANSI,
               "Double-acting cylinder with rod through both ends.",
               body() + [rect(-7, -10, -3, 10), line(-40, 0, -30, 0), line(-30, 0, -7, 0)] + rod(-3, 30)
               + ports(), terms()))
        add(sd("cyl.cushion2", "Cylinder, fixed cushion, advance and retract (ANSI)", ANSI,
               "Double-acting cylinder with fixed cushions at both ends of the stroke.",
               body() + piston_ansi() + [rect(-8, -4, -1, 4)] + rod(-1) + ports(), terms(),
               keywords=("cushion", "ram")))
        add(sd("cyl.cushion.adj1", "Cylinder, adjustable cushion, advance only (ANSI)", ANSI,
               "Double-acting cylinder with an adjustable cushion on the advance stroke.",
               body() + piston_ansi() + [rect(-8, -4, -1, 4)] + rod(-1) + ports()
               + arrow(-11, 8, 1, -7, head=4), terms(), keywords=("cushion", "ram")))
        add(sd("cyl.bigrod", "Cylinder, large rod, non-cushioned (ANSI)", ANSI,
               "Double-acting cylinder; rod drawn wide where the rod-to-bore ratio matters to the circuit.",
               body() + piston_ansi() + [line(-8, -6, 35, -6), line(-8, 6, 35, 6), line(35, -6, 35, 6)]
               + ports(), terms(), keywords=("differential", "ram")))
        add(sd("cyl.bigrod.cushion2", "Cylinder, large rod, cushioned advance and retract (ANSI)", ANSI,
               "Large-rod double-acting cylinder with cushions at both ends of the stroke.",
               body() + piston_ansi() + [rect(-8, -4, -1, 4), line(-1, -6, 35, -6), line(-1, 6, 35, 6),
                                         line(35, -6, 35, 6)] + ports(), terms(),
               keywords=("differential", "cushion", "ram")))
        add(sd("intensifier", "Pressure intensifier (ANSI)", ANSI,
               "Pressure intensifier (booster): large piston driving a small one; 1 = low-pressure inlet, "
               "2 = high-pressure outlet.",
               [rect(-40, -12, 0, 12), line(0, -6, 30, -6), line(0, 6, 30, 6), line(30, -6, 30, 6),
                line(-30, -12, -30, 12, w="thick"), line(-30, 0, 22, 0), rect(22, -6, 26, 6),
                line(-30, -20, -30, -12), line(30, 0, 40, 0)],
               [T("1", -30, -20, "u"), T("2", 40, 0, "r")], keywords=("booster",)))
        servo = body() + piston_ansi(-26) + rod(-22) + [rect(-15, -18, -5, -10)]   # ports on the valve, not the body
        if medium == "hyd":
            servo += [line(-15, -14, -40, -14), line(-40, -14, -40, 10), line(-44, 7, -44, 12),
                      line(-44, 12, -36, 12), line(-36, 12, -36, 7), line(-5, -14, 10, -14), line(10, -14, 10, -20)]
            st = [T("P", 10, -20, "u")]
        else:
            servo += [line(-15, -14, -32, -14), poly(-40, -14, -32, -18, -32, -10), line(-5, -14, 10, -14),
                      line(10, -14, 10, -20)]
            st = [T("1", 10, -20, "u")]
        add(sd("servopositioner", "Servo positioner, simplified (ANSI)", ANSI,
               "Cylinder with integral servo (positioning) valve; supply connection on top" +
               (", return to reservoir." if medium == "hyd" else ", exhaust to atmosphere."), servo, st,
               keywords=("positioner", "servo cylinder")))
    return s
