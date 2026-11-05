"""Flow controls, dividers and special directional valves (symbol-library expansion, batch F8b).

Sources: HO = HydraulicsOnline.com ISO 1219 chart ("Energy Control"); Y32 = ANSI Y32.10 10.9.5.2, 10.10.1.3/4,
10.12 and 10.16.
* The chart draws several of these inside a dash-dot component enclosure; that centre-line style is not
  available (director decision D3), so the enclosure is not drawn.
* Lines the sources draw to a reservoir symbol end there (as in batch F7); they are not separate ports.
* Solenoids carry no electrical terminals, like the configurator's solenoids.
* Pressure-source triangles that Y32 draws at the inlet ports of 10.10.1.3/4 are markers, not part of the valve;
  the inlet is a port and the marker can be added with the energy-source markers of batch F2.
"""
from __future__ import annotations

from .base import ANSI, ISO, Geometry, SymbolDef, Terminal as T, arc, arrow, arrowhead, circle, line, poly, polyline, rect, zigzag
from .fluid_pressure import box as pbox, nc_arrow, no_arrow, spring as pspring

G = "Non-return & flow"
GD = "Directional valves"
H, PN = "Hydraulic", "Pneumatic"
MEDIA = (("hyd", H), ("pneu", PN))


# ---------------------------------------------------------------------------------------------- helpers
def dot(x, y):
    return circle(x, y, 1.6, fill=True, w="thin")


def reservoir(x, y):
    """Reservoir symbol whose open top is at height y; the line from above ends inside it."""
    return [polyline([(x - 4, y), (x - 4, y + 6), (x + 4, y + 6), (x + 4, y)])]


def vthrottle(cx=0.0, cy=0.0, r=8.0, off=10.0):
    """Throttle on a vertical line (the existing throttle_prims turned through 90 degrees)."""
    return [arc(cx - off, cy, r, 300, 120), arc(cx + off, cy, r, 120, 120)]


def vcheck(x, y):
    """Check valve on a vertical line, ball at (x, y): free flow upwards (seat vertex below the ball)."""
    return [polyline([(x - 8, y), (x, y + 10), (x + 8, y)]), circle(x, y, 6)]


def double_arrow(x1, y1, x2, y2):
    return [line(x1, y1, x2, y2), arrowhead((x2, y2), (x1, y1), length=4),
            arrowhead((x1, y1), (x2, y2), length=4)]


def tee_top(x, top=-15):
    """Blocked port drawn from the top edge of a valve box."""
    return [line(x, top, x, top + 6), line(x - 4, top + 6, x + 4, top + 6)]


def solenoid(x0, y0, x1, y1):
    return [rect(x0, y0, x1, y1), line(x0 + 4, y1, x1 - 4, y0)]


def compensated_core(adjustable):
    """HO pressure-compensated flow control: throttle in a box on the P (top) to A (bottom) line, with the
    compensation arrow on the flow line."""
    p = [rect(-10, -13, 10, 13), line(0, -20, 0, 20)] + vthrottle()
    if adjustable:
        p += arrow(-9, 8, 9, -9, head=3.5)
    p.append(arrowhead((0, 12), (0, 4), length=5, half_width=2.5))
    return p


def tank_branch(side):
    """Excess-flow line from the inlet side of the throttle to a reservoir symbol."""
    x = 25 * side
    return [dot(0, -10), polyline([(0, -10), (x, -10), (x, 4)])] + reservoir(x, 0)


def bypass_check(side):
    """Reverse-flow check on a bypass (free flow A -> P, upwards)."""
    x = 22 * side
    return [dot(0, -17), dot(0, 17), polyline([(0, -17), (x, -17), (x, -8)]), polyline([(x, 8), (x, 17), (0, 17)])] \
        + vcheck(x, -2)


def pa():
    return [T("P", 0, -20, "u"), T("A", 0, 20, "d")]


def ansi_flow_box(pc=False, temp=False):
    """Y32 10.16.2-10.16.4: controlled flow 1 -> 2 along the top line; flow 2 -> 1 bypasses through the check."""
    p = [rect(-25, -20, 25, 15), line(-30, -10, 30, -10), dot(-18, -10), dot(18, -10),
         polyline([(-18, -10), (-18, 5), (-8, 5)]), circle(-2, 5, 6), polyline([(-2, -3), (8, 5), (-2, 13)]),
         polyline([(8, 5), (18, 5), (18, -10)])]
    p += arrow(-10, -2, 2, -18, head=4)
    if pc:
        p.append(arrowhead((10, -18), (10, -10), length=8, half_width=3))
    if temp:
        p += [line(14, -10, 14, -5), circle(14, -4, 1.8, fill=True, w="thin")]
    return p


def two_box_3way(paths1, paths2):
    """Y32 10.10.1 two-position three-way valve, spring left, ports on the left (normal) box."""
    p = [rect(-30, -15, 0, 15), rect(0, -15, 30, 15), line(-30, 0, -32, 0), zigzag(-32, 0, -44, 0, n=6, amp=4),
         line(-20, -20, -20, -15), line(-10, -20, -10, -15), line(-20, 15, -20, 20)]
    return p + paths1 + paths2


# ---------------------------------------------------------------------------------------------- symbols
def symbols():
    s = []
    add = s.append
    sd = lambda sid, name, cat, grp, conv, desc, prims, terms, **kw: SymbolDef(  # noqa: E731
        sid, name, cat, grp, conv, desc, kw.pop("prefix", "V"), Geometry(prims, terms), **kw)
    encl = "The chart's dash-dot component enclosure is not drawn (centre-line style deferred, director D3)."
    # ------------------------------------------------------------ HO chart, hydraulic
    add(sd("fl.hyd.flow.3way", "Flow control, 3-way, adjustable", H, G, ISO,
           "Adjustable pressure-compensated flow control P -> A; excess flow from the inlet to the reservoir.",
           compensated_core(True) + tank_branch(-1), pa(), keywords=("bypass flow control", "3-way")))
    add(sd("fl.hyd.flow.3way.check", "Flow control, 3-way, adjustable, with reverse-flow check", H, G, ISO,
           "Adjustable pressure-compensated flow control P -> A with a check for free reverse flow A -> P.",
           compensated_core(True) + bypass_check(-1), pa(), keywords=("speed control",),
           notes=encl + " Drawn as the chart draws it (no reservoir connection)."))
    add(sd("fl.hyd.flow.3way.check.t", "Flow control, 3-way, adjustable, with reverse-flow check and tank line",
           H, G, ISO,
           "Adjustable pressure-compensated flow control P -> A, excess flow to the reservoir, check for free "
           "reverse flow A -> P.", compensated_core(True) + tank_branch(-1) + bypass_check(1), pa(),
           keywords=("bypass flow control", "3-way"), notes=encl))
    add(sd("fl.hyd.lowering.check", "Lowering valve with reverse-flow check", H, G, ISO,
           "Pressure-compensated (non-adjustable) lowering valve: controlled flow P -> A, free reverse flow A -> P "
           "through the check.", compensated_core(False) + bypass_check(-1), pa(),
           keywords=("flow control", "load lowering")))
    sp = [line(0, 20, 0, 10), dot(0, 10), line(-20, 10, 20, 10), line(-20, 10, -20, -20), line(20, 10, 20, -20),
          rect(-25, -10, -15, 4), rect(15, -10, 25, 4), line(-20, -15, 20, -15, dash=True, w="thin")]
    sp += vthrottle(-20, -3, 5, 7) + vthrottle(20, -3, 5, 7)
    add(sd("fl.hyd.divider.spool", "Flow divider, spool type", H, G, ISO,
           "Spool-type flow divider: inlet P split into two equal flows A and B, the spools sensing the outlets.",
           sp, [T("P", 0, 20, "d"), T("A", -20, -20, "u"), T("B", 20, -20, "u")], keywords=("divider",),
           notes=encl))
    rot = [line(-8, 0, -4, 0), rect(-4, -3, 4, 3), line(4, 0, 8, 0)]
    for cx in (-20, 20):
        y = (12 * 12 - 36) ** 0.5
        rot += [circle(cx, 0, 12), line(cx, -20, cx, -12), line(cx, 12, cx, 20),
                poly(cx - 6, -y, cx + 6, -y, cx, -4.5, fill=True), poly(cx - 6, y, cx + 6, y, cx, 4.5, fill=True)]
    add(sd("fl.hyd.divider.rotary", "Flow divider, rotary (gear) type", H, G, ISO,
           "Rotary flow divider: two mechanically coupled reversible motor sections. Each section has its own "
           "ports (A1/B1, A2/B2); feeding both A ports divides the flow equally to B1 and B2.",
           rot, [T("A1", -20, -20, "u"), T("A2", 20, -20, "u"), T("B1", -20, 20, "d"), T("B2", 20, 20, "d")],
           keywords=("divider", "gear divider")))
    pr = [rect(-40, -15, 0, 15), rect(0, -15, 40, 15), line(-30, -20, -30, -15), line(-10, -20, -10, -15),
          line(-20, 15, -20, 20)]
    pr += arrow(-20, 15, -30, -15, head=4) + arrow(-20, 15, -10, -15, head=4)
    pr += arrow(20, 15, 10, -15, head=4) + tee_top(30)
    pr += [line(40, 0, 42, 0), zigzag(42, 0, 54, 0, n=6, amp=4), line(40, 10, 60, 10, dash=True, w="thin"),
           polyline([(-30, -18), (-46, -18), (-46, 8), (-40, 8)], dash=True, w="thin")]
    add(sd("fl.hyd.priority", "Priority valve", H, G, ISO,
           "Priority (load-sensing) valve: inlet P feeds the controlled (priority) flow CF first; the excess flow "
           "goes to EF. Load-sensing pilot LS acts with the spring; CF pressure acts against it.",
           pr, [T("P", -20, 20, "d"), T("CF", -30, -20, "u"), T("EF", -10, -20, "u"),
                T("LS", 60, 10, "r", ptype="hyd.pilot")], keywords=("load sensing", "steering", "lsp"),
           notes=encl))

    def sol_check(normally_open):
        p = [rect(-20, -15, 0, 15), rect(0, -15, 20, 15), line(-10, -20, -10, -15), line(-10, 15, -10, 20)]
        p += solenoid(20, -7, 38, 7)
        chk = lambda cx: [line(cx, -15, cx, -9), polyline([(cx - 6, -4), (cx, 4), (cx + 6, -4)]),  # noqa: E731
                          circle(cx, -4, 5), line(cx, 4, cx, 15)]
        opn = lambda cx: arrow(cx, -15, cx, 15, head=4)  # noqa: E731
        p += (opn(-10) + chk(10)) if normally_open else (chk(-10) + opn(10))
        return p
    for no in (True, False):
        tag, word = ("no", "open") if no else ("nc", "closed")
        add(sd(f"fl.hyd.sol.check.{tag}", f"Solenoid check valve, normally {word}", H, GD, ISO,
               f"Seated 2/2 solenoid valve, normally {word}: open position flow 1 -> 2 (either way); check position "
               "blocks 1 -> 2 and allows free flow 2 -> 1.", sol_check(no),
               [T("1", -10, -20, "u"), T("2", -10, 20, "d")], keywords=("poppet", "seat valve", "load holding")))
    dv = [rect(-50, -15, 0, 15), rect(0, -15, 50, 15)] + solenoid(-68, 0, -50, 15)
    dv += [line(50, 0, 52, 0), zigzag(52, 0, 64, 0, n=6, amp=4)]
    dv += tee_top(-40) + tee_top(-20) + arrow(-30, -15, -40, 15, head=4) + arrow(-10, -15, -20, 15, head=4)
    dv += double_arrow(10, -15, 10, 15) + double_arrow(30, -15, 30, 15) + tee_top(20) + tee_top(40)
    dv += [line(x, -20, x, -15) for x in (10, 20, 30, 40)] + [line(10, 15, 10, 20), line(30, 15, 30, 20)]
    add(sd("fl.hyd.diverter6", "Diverter (changeover) valve, 6-port, solenoid operated", H, GD, ISO,
           "Six-port diverter: P and T are switched between circuit 1 (A1, B1; spring position) and circuit 2 "
           "(A2, B2; solenoid energised); the circuit not selected is blocked.", dv,
           [T("P", 10, 20, "d"), T("T", 30, 20, "d"), T("A1", 10, -20, "u"), T("A2", 20, -20, "u"),
            T("B1", 30, -20, "u"), T("B2", 40, -20, "u")], keywords=("changeover", "selector", "6/2")))

    def seat(x):
        return [circle(x, 8, 2.5), line(x, 10.5, x, 15)]
    sv = [rect(-30, -15, 0, 15), rect(0, -15, 30, 15)] + solenoid(-48, 0, -30, 15)
    sv += [line(30, 0, 32, 0), zigzag(32, 0, 44, 0, n=6, amp=4)]
    sv += arrow(-20, 15, -20, -15, head=4) + seat(-10) + arrow(10, -15, 20, 15, head=4) + seat(10)
    sv += [line(10, -20, 10, -15), line(10, 15, 10, 20), line(20, 15, 20, 20)]
    add(sd("fl.hyd.dcv.seated", "Directional valve 3/2, seated, solenoid operated", H, GD, ISO,
           "Direct-acting seated (poppet) 3/2 solenoid valve: spring position A -> T with P sealed on a seat; "
           "energised P -> A with T sealed.", sv, [T("A", 10, -20, "u"), T("P", 10, 20, "d"), T("T", 20, 20, "d")],
           keywords=("poppet", "seat valve", "leak-free")))
    # ------------------------------------------------------------ Y32.10, hydraulic only (reservoir drawn)
    for no in (False, True):
        tag, word = ("no", "open") if no else ("nc", "closed")
        p = pbox()[:2] + pspring(True) + (no_arrow() if no else nc_arrow())
        p += [line(15, 0, 30, 0, dash=True, w="thin"), line(0, 15, 0, 24)] + reservoir(0, 20)
        add(sd(f"fl.hyd.valve.prop.{tag}", f"Valve, infinite positioning, normally {word} (ANSI)", H, GD, ANSI,
               f"Two-way valve with infinite positioning between open and closed, normally {word}; adjustable "
               "spring, pilot X; outlet to the reservoir as drawn in Y32.10 10.12.", p,
               [T("P", 0, -20, "u"), T("X", 30, 0, "r")], keywords=("throttling", "infinite position")))
    # ------------------------------------------------------------ Y32.10, both media
    for medium, cat in MEDIA:
        pre = f"fl.{medium}"
        hyd = medium == "hyd"
        add(sd(f"{pre}.throttle.adj.ansi", "Flow control, adjustable, non-compensated (ANSI)", cat, G, ANSI,
               "Adjustable restriction, flow controlled in each direction.",
               [line(-20, 0, 20, 0)] + arrow(-7, 10, 7, -10, head=4), [T("1", -20, 0, "l"), T("2", 20, 0, "r")],
               keywords=("needle", "throttle"),
               notes="Y32.10 draws the same symbol on a pilot line (dashed); draw it on a pilot line as required."))
        io = [T("1", -30, -10, "l"), T("2", 30, -10, "r")]
        add(sd(f"{pre}.flow.oneway.ansi", "Flow control, adjustable, with bypass (ANSI)", cat, G, ANSI,
               "Flow 1 -> 2 is controlled; flow 2 -> 1 bypasses the control through the check.",
               ansi_flow_box(), list(io), keywords=("speed control", "meter")))
        add(sd(f"{pre}.flow.pc.bypass", "Flow control, adjustable, pressure compensated, with bypass (ANSI)", cat, G,
               ANSI, "Pressure-compensated adjustable flow control 1 -> 2; flow 2 -> 1 bypasses through the check.",
               ansi_flow_box(pc=True), list(io), keywords=("speed control", "compensated")))
        add(sd(f"{pre}.flow.tpc.bypass",
               "Flow control, adjustable, temperature and pressure compensated, with bypass (ANSI)", cat, G, ANSI,
               "Temperature- and pressure-compensated adjustable flow control 1 -> 2; flow 2 -> 1 bypasses through "
               "the check.", ansi_flow_box(pc=True, temp=True), list(io), keywords=("speed control", "compensated"),
               notes="Y32.10 10.16.4 draws the bypass check although its title does not mention it."))
        for no in (False, True):
            tag, word = ("no", "open") if no else ("nc", "closed")
            add(sd(f"{pre}.valve.2way.prop.{tag}", f"Two-way valve, infinite position, normally {word} (ANSI)", cat,
                   GD, ANSI, f"Two-way valve, infinite positioning, normally {word}, spring offset.",
                   pbox() + pspring(False) + (no_arrow() if no else nc_arrow()),
                   [T("1", 0, -20, "u"), T("2", 0, 20, "d")], keywords=("throttling", "infinite position")))
        a, b, sup = ("A", "B", "P") if hyd else ("2", "4", "1")
        add(sd(f"{pre}.valve.3way.distributor", "Three-way valve, distributor (ANSI)", cat, GD, ANSI,
               f"Two-position three-way distributor: pressure at {sup} goes first to {b} (normal), then to {a} "
               "(actuated). The inlet pressure-source marker of the source is not part of the symbol.",
               two_box_3way(tee_top(-20) + arrow(-20, 15, -10, -15, head=4), arrow(10, 15, 10, -15, head=4)
                            + tee_top(20)),
               [T(a, -20, -20, "u"), T(b, -10, -20, "u"), T(sup, -20, 20, "d")], keywords=("3/2",)))
        p1, p2, out = ("P1", "P2", "A") if hyd else ("1a", "1b", "2")
        pt = "hyd.pressure" if hyd else "pneu.supply"
        add(sd(f"{pre}.valve.3way.twopressure", "Three-way valve, two-pressure (ANSI)", cat, GD, ANSI,
               f"Two-position three-way valve selecting between two pressure supplies: normal {p2} -> {out}, "
               f"actuated {p1} -> {out}. The pressure-source markers of the source are not part of the symbol.",
               two_box_3way(tee_top(-20) + arrow(-10, -15, -20, 15, head=4), arrow(10, -15, 10, 15, head=4)
                            + tee_top(20)),
               [T(p1, -20, -20, "u", ptype=pt), T(p2, -10, -20, "u", ptype=pt), T(out, -20, 20, "d")],
               keywords=("3/2", "pressure selector")))
    return s
