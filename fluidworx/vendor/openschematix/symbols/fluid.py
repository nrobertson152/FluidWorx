"""Hydraulic and pneumatic (fluid power) symbols, drawn in ISO 1219-1 style.

Conventions used:
  * Energy-direction triangles are filled for hydraulic and hollow for
    pneumatic media.
  * Working lines are solid; pilot and drain lines are dashed (set per wire).
  * Hydraulic ports use letter codes P, T, A, B, X, Y.
  * Pneumatic valve ports use the numeric codes 1 (supply), 2/4 (outputs),
    3/5 (exhausts) and 10/12/14 (pilot), following ISO 11727 / ISO 5599 usage.

Directional control valves are parametric: the number of switching positions,
the flow path in each position and the operators on each side are stored in
the component's `params`, so a valve can be reconfigured after placement.
"""
from __future__ import annotations

import math

from .base import (
    ISO, Geometry, SymbolDef, Terminal as T, arc, arrow, arrowhead, circle, line, poly,
    polyline, rect, text, zigzag,
)

H = "Hydraulic"
P = "Pneumatic"


def _tri(fill):
    return fill  # hydraulic: filled, pneumatic: hollow


# ---------------------------------------------------------------- energy conversion
def pump(fill, variable=False):
    p = [circle(0, 0, 12), line(0, -20, 0, -12), line(0, 12, 0, 20),
         poly(0, -12, -4.5, -4.5, 4.5, -4.5, fill=fill),
         # drive shaft (two parallel lines) on the right
         line(12, -1.5, 19, -1.5, w="thin"), line(12, 1.5, 19, 1.5, w="thin")]
    if variable:
        p += arrow(-11, 11, 13, -13, head=4.5)
    return p


def motor(fill, variable=False):
    y = -math.sqrt(144 - 36)
    p = [circle(0, 0, 12), line(0, -20, 0, -12), line(0, 12, 0, 20),
         poly(-6, y, 6, y, 0, -4.5, fill=fill),
         line(12, -1.5, 19, -1.5, w="thin"), line(12, 1.5, 19, 1.5, w="thin")]
    if variable:
        p += arrow(-11, 11, 13, -13, head=4.5)
    return p


def cylinder_double(double_rod=False):
    p = [rect(-30, -10, 20, 10), line(-10, -10, -10, 10, w="thick"), line(-10, 0, 35, 0),
         line(-20, -20, -20, -10), line(10, -20, 10, -10)]
    if double_rod:
        p.append(line(-35, 0, -10, 0))
    return p


def cylinder_single_spring():
    return [rect(-30, -10, 20, 10), line(-10, -10, -10, 10, w="thick"), line(-10, 0, 35, 0),
            line(-20, -20, -20, -10), zigzag(-9, -6, 19, -6, n=6, amp=3)]


# ---------------------------------------------------------------- valves
def relief_valve(fill):
    """Pressure-relief valve, direct operated, adjustable (normally closed)."""
    p = [rect(-15, -15, 15, 15), line(0, 20, 0, 15), line(0, -15, 0, -20),
         # flow arrow offset from the port axis -> normally closed
         *arrow(6, 10, 6, -10, head=4),
         # adjustable spring on the right
         line(15, 0, 17, 0), zigzag(17, 0, 29, 0, n=6, amp=4), *arrow(17, 7, 30, -7, head=3.5),
         # pilot line from the inlet to the opposite (left) side
         polyline([(0, 17), (-22, 17), (-22, 0), (-15, 0)], dash=True, w="thin")]
    return Geometry(p, [T("P", 0, 20, "d"), T("T", 0, -20, "u")])


def reducing_valve(fill, ports=("P", "A")):
    """Pressure-reducing valve, direct operated (normally open), pilot from outlet."""
    p = [rect(-15, -15, 15, 15), line(0, 20, 0, 15), line(0, -15, 0, -20),
         *arrow(0, 10, 0, -10, head=4),
         line(15, 0, 17, 0), zigzag(17, 0, 29, 0, n=6, amp=4), *arrow(17, 7, 30, -7, head=3.5),
         polyline([(0, -17), (-22, -17), (-22, 0), (-15, 0)], dash=True, w="thin")]
    return Geometry(p, [T(ports[0], 0, 20, "d"), T(ports[1], 0, -20, "u")])


def check_valve_prims(x0=0.0, y0=0.0, spring=False):
    # Seat drawn as a V whose mouth holds the ball. Free flow from the seat
    # (vertex) side towards the ball side: left -> right.
    p = [polyline([(x0 + 4, y0 - 8), (x0 - 6, y0), (x0 + 4, y0 + 8)]), circle(x0 + 4, y0, 6)]
    if spring:
        p.append(zigzag(x0 + 10, y0, x0 + 18, y0, n=4, amp=3))
    return p


def check_valve(spring=False):
    p = [line(-20, 0, -6, 0)] + check_valve_prims(spring=spring)
    p.append(line(18 if spring else 10, 0, 20, 0))
    return Geometry(p, [T("1", -20, 0, "l"), T("2", 20, 0, "r")])


def throttle_prims(adjustable):
    p = [arc(0, -10, 8, 210, 120), arc(0, 10, 8, 30, 120)]
    if adjustable:
        p += arrow(-8, 9, 9, -10, head=3.5)
    return p


def throttle(adjustable):
    return Geometry([line(-20, 0, 20, 0)] + throttle_prims(adjustable), [T("1", -20, 0, "l"), T("2", 20, 0, "r")])


def one_way_flow_control():
    p = [line(-30, 0, 30, 0)] + throttle_prims(True)
    # bypass with check valve: free flow 1 -> 2 through the check
    p += [polyline([(-20, 0), (-20, -20), (-6, -20)]), polyline([(10, -20), (20, -20), (20, 0)])]
    p += check_valve_prims(0, -20)
    p += [circle(-20, 0, 1.6, fill=True, w="thin"), circle(20, 0, 1.6, fill=True, w="thin")]
    return Geometry(p, [T("1", -30, 0, "l"), T("2", 30, 0, "r")])


def shuttle_valve(names):
    p = [rect(-12, -7, 12, 7), line(-20, 0, -12, 0), line(12, 0, 20, 0), line(0, -7, 0, -20),
         circle(-5, 0, 4), line(-10, -5, -10, 5, w="thin"), line(10, -5, 10, 5, w="thin")]
    return Geometry(p, [T(names[0], -20, 0, "l"), T(names[1], 20, 0, "r"), T(names[2], 0, -20, "u")])


# ---------------------------------------------------------------- energy storage / conditioning
def reservoir():
    p = [polyline([(-15, -6), (-15, 8), (15, 8), (15, -6)]), line(0, -20, 0, 4)]
    return Geometry(p, [T("T", 0, -20, "u")])


def accumulator():
    p = [arc(0, -7, 8, 0, 180), arc(0, 7, 8, 180, 180), line(-8, -7, -8, 7), line(8, -7, 8, 7),
         line(-8, 0, 8, 0), line(0, 15, 0, 20)]
    return Geometry(p, [T("P", 0, 20, "d")])


def air_receiver():
    p = [arc(-12, 0, 8, 90, 180), arc(12, 0, 8, -90, 180), line(-12, -8, 12, -8), line(-12, 8, 12, 8),
         line(0, -8, 0, -20)]
    return Geometry(p, [T("1", 0, -20, "u")])


def filter_geo(names=("1", "2")):
    p = [line(-20, 0, -10, 0), line(10, 0, 20, 0), poly(-10, 0, 0, -10, 10, 0, 0, 10),
         line(0, -10, 0, 10, dash=True, w="thin")]
    return Geometry(p, [T(names[0], -20, 0, "l"), T(names[1], 20, 0, "r")])


def gauge(name):
    p = [circle(0, 0, 10), line(0, 10, 0, 20), *arrow(-6, 6, 6, -6, head=3.5)]
    return Geometry(p, [T(name, 0, 20, "d")])


# ================================================================ directional valves
ENV = 40          # envelope (switching position square) size, units
HALF = ENV / 2
LEAD = 10         # port lead length outside the envelope

# Port layouts relative to the centre of an envelope: (name, dx, side)
LAYOUTS = {
    ("hyd", 2): [("A", 0, "top"), ("P", 0, "bot")],
    ("hyd", 3): [("A", -10, "top"), ("P", -10, "bot"), ("T", 10, "bot")],
    ("hyd", 4): [("A", -10, "top"), ("B", 10, "top"), ("P", -10, "bot"), ("T", 10, "bot")],
    ("pneu", 2): [("2", 0, "top"), ("1", 0, "bot")],
    ("pneu", 3): [("2", -10, "top"), ("1", -10, "bot"), ("3", 10, "bot")],
    ("pneu", 5): [("4", -10, "top"), ("2", 10, "top"), ("5", -10, "bot"), ("1", 0, "bot"), ("3", 10, "bot")],
}

# Flow-path patterns: arrows (from, to), plain links (undirected), blocked ports.
PATTERNS = {
    2: {
        "open": {"label": "Open (P→A)", "arrows": [(1, 0)], "blocked": []},
        "closed": {"label": "Closed", "arrows": [], "blocked": [0, 1]},
        # ANSI Y32.10 10.9.1 on-off valve (added by the library expansion)
        "open.both": {"label": "Open, flow either way", "special": "both", "blocked": []},
    },
    3: {
        "P-A": {"label": "P→A, T blocked", "arrows": [(1, 0)], "blocked": [2]},
        "A-T": {"label": "A→T, P blocked", "arrows": [(0, 2)], "blocked": [1]},
        "closed": {"label": "All ports blocked", "arrows": [], "blocked": [0, 1, 2]},
    },
    4: {
        "parallel": {"label": "P→A, B→T (parallel)", "arrows": [(2, 0), (1, 3)], "blocked": []},
        "crossed": {"label": "P→B, A→T (crossed)", "arrows": [(2, 1), (0, 3)], "blocked": []},
        "closed": {"label": "Closed centre (all blocked)", "arrows": [], "blocked": [0, 1, 2, 3]},
        "tandem": {"label": "Tandem centre (P→T, A B blocked)", "special": "tandem", "blocked": [0, 1]},
        "float": {"label": "Float centre (A B T linked, P blocked)", "special": "float", "blocked": [2]},
        "open": {"label": "Open centre (all linked)", "special": "open", "blocked": []},
        # Y32 10.11.3 typical centre conditions (added by the library expansion)
        "b-t": {"label": "B→T linked, A P blocked", "special": "b-t", "blocked": [0, 2]},
        "apt": {"label": "A P T linked, B blocked", "special": "apt", "blocked": [1]},
        "ab": {"label": "A B linked, P T blocked", "special": "ab", "blocked": [2, 3]},
        "a-t": {"label": "A→T linked, B P blocked", "special": "a-t", "blocked": [1, 2]},
        "ab-pt": {"label": "A B linked and P T linked", "special": "ab-pt", "blocked": []},
    },
    5: {
        "1-2": {"label": "1→2, 4→5", "arrows": [(3, 1), (0, 2)], "blocked": []},
        "1-4": {"label": "1→4, 2→3", "arrows": [(3, 0), (1, 4)], "blocked": []},
        "closed": {"label": "Closed centre (all blocked)", "arrows": [], "blocked": [0, 1, 2, 3, 4]},
        "exhaust": {"label": "Exhausted centre (4→5, 2→3, 1 blocked)", "arrows": [(0, 2), (1, 4)], "blocked": [3]},
    },
}

OPERATORS = {
    "spring": "Spring",
    "solenoid": "Solenoid",
    "pilot": "Pilot pressure",
    "lever": "Lever",
    "pushbutton": "Push-button",
    "manual": "Manual, general",
    # added by the symbol-library expansion (HO = HydraulicsOnline ISO 1219 chart, Y32 = ANSI Y32.10)
    "detent": "Detent",
    "pushpull": "Push-pull knob",
    "pedal": "Pedal, single acting",
    "pedal2": "Pedal, double acting",
    "plunger": "Plunger",
    "plunger.limited": "Plunger with stroke limitation",
    "roller": "Roller",
    "roller.lever": "Lever with roller",
    "cam": "Roller on cam (mechanical)",
    "solenoid.pushpull": "Solenoid, push/pull",
    "solenoid.prop": "Solenoid, proportional",
    "pilot.direct": "Pilot, direct (line only)",
    "pilot.applied": "Pilot, pressure applied (box)",
    "pilot.remote": "Pilot, remote supply",
    "pilot.internal": "Pilot, internal supply",
    "release.remote": "Released pressure, remote exhaust",
    "release.internal": "Released pressure, internal return",
    "solenoid.or.pilot.ext": "Solenoid or pilot, external supply",
    "solenoid.or.pilot.int": "Solenoid or pilot, internal supply",
    "solenoid.and.pilot.ext": "Solenoid-operated pilot, external supply",
    "solenoid.and.pilot.int": "Solenoid-operated pilot, internal supply",
    "motor": "Electric motor",
    "motor.other": "Other control unit (not electric motor)",
    "motor.reversing": "Reversing motor",
    "compensated": "Pressure compensated",
    "thermal": "Thermal, local sensing",
    "thermal.bulb": "Thermal, remote bulb",
    "servo": "Servo",
}

VALVE_TYPES = {
    "hyd": {"2/2": (2, 2), "3/2": (3, 2), "4/2": (4, 2), "4/3": (4, 3)},
    "pneu": {"2/2": (2, 2), "3/2": (3, 2), "5/2": (5, 2), "5/3": (5, 3)},
}


def default_valve_params(medium="hyd", vtype=None):
    if medium == "hyd":
        vtype = vtype or "4/3"
    else:
        vtype = vtype or "5/2"
    ports, npos = VALVE_TYPES[medium][vtype]
    defaults = {
        (2, 2): ["open", "closed"],
        (3, 2): ["P-A", "A-T"],
        (4, 2): ["parallel", "crossed"],
        (4, 3): ["parallel", "closed", "crossed"],
        (5, 2): ["1-4", "1-2"],
        (5, 3): ["1-4", "closed", "1-2"],
    }[(ports, npos)]
    if npos == 3:
        left, right = ["spring", "solenoid"], ["spring", "solenoid"]
    else:
        left, right = ["solenoid"], ["spring"]
    return {"medium": medium, "type": vtype, "positions": list(defaults), "left": left, "right": right}


def normal_position(npos, left, right):
    """Index of the position in which the ports are drawn (the rest position)."""
    if npos == 3:
        return 1
    if "spring" in right and "spring" not in left:
        return npos - 1
    if "spring" in left and "spring" not in right:
        return 0
    return npos - 1


def _pilot_name(medium, side, positions, nports):
    if medium == "hyd":
        return "X" if side < 0 else "Y"
    pos = positions[0] if side < 0 else positions[-1]
    if nports == 5:
        return "14" if pos == "1-4" else "12"
    if nports in (2, 3):
        return "12" if pos in ("open", "open.both", "P-A") else "10"   # ISO 5599: 12 opens 1→2, 10 closes
    return "X" if side < 0 else "Y"


def _operator(kind, x, s, fill, ctx=None):
    """Draw one operator starting at x (envelope side), extending in direction s.
    Returns (prims, width), or (prims, width, terminal) for operators with a pilot connection."""
    if kind in EXT_OPERATORS:
        return _operator_ext(kind, x, s, fill, ctx or {})
    p = []
    if kind == "spring":
        p.append(zigzag(x, 0, x + s * 10, 0, n=6, amp=5))
        return p, 10
    if kind == "solenoid":
        a, b = sorted((x, x + s * 10))
        p += [rect(a, -6, b, 6), line(a, 6, b, -6)]
        return p, 10
    if kind == "pilot":
        # triangle pointing at the valve, then the (dashed) pilot line to port
        p += [poly(x, 0, x + s * 8, -4.5, x + s * 8, 4.5, fill=fill),
              line(x + s * 8, 0, x + s * 20, 0, dash=True, w="thin")]
        return p, 20
    if kind == "lever":
        p += [line(x, 0, x + s * 5, 0), line(x + s * 5, 0, x + s * 10, -9)]
        return p, 10
    if kind == "pushbutton":
        p += [line(x, 0, x + s * 5, 0), arc(x + s * 5, 0, 4, 90, -180 if s > 0 else 180)]
        return p, 10
    if kind == "manual":
        p += [line(x, 0, x + s * 8, 0), line(x + s * 8, -5, x + s * 8, 5)]
        return p, 10
    return p, 0


# ---------------------------------------------------------------- operators added by the library expansion
# Every width is a multiple of the 10-unit grid, so pilot terminals at the end of an operator chain stay on grid.
EXT_OPERATORS = {
    "detent", "pushpull", "pedal", "pedal2", "plunger", "plunger.limited", "roller", "roller.lever", "cam",
    "solenoid.pushpull", "solenoid.prop", "pilot.direct", "pilot.applied", "pilot.remote", "pilot.internal",
    "release.remote", "release.internal", "solenoid.or.pilot.ext", "solenoid.or.pilot.int",
    "solenoid.and.pilot.ext", "solenoid.and.pilot.int", "motor", "motor.other", "motor.reversing",
    "compensated", "thermal", "thermal.bulb", "servo",
}


def _box(x, s, d0, d1, y0, y1, dash=False):
    a, b = sorted((x + s * d0, x + s * d1))
    return rect(a, y0, b, y1, dash=dash)


def _pilot_triangle(x, s, d, fill, half=3.5, length=6.0, toward_valve=True):
    """Energy triangle centred at distance d from the envelope, pointing toward (or away from) the valve."""
    c = x + s * d
    k = -s if toward_valve else s          # direction the tip points along x
    tip, base = c + k * length / 2, c - k * length / 2
    return poly(tip, 0, base, -half, base, half, fill=fill)


def _operator_ext(kind, x, s, fill, ctx):
    X = lambda d: x + s * d  # noqa: E731 - distance d outward from the envelope side
    out = s                  # unit direction away from the valve
    p, term = [], None
    if kind == "detent":
        # Y32 7.4 / HO: a notch for each detent (= switching position); the short line marks the one in use
        # (the rest position as drawn).
        npos, k = ctx.get("npos", 2), ctx.get("normal", 0)
        span0, span1 = 4.0, 18.0
        step = (span1 - span0) / npos
        xs = sorted(X(span0 + step * (i + 0.5)) for i in range(npos))
        pts = [(x, 0.0)]
        for i in range(npos):                    # outward from the envelope
            cx = X(span0 + step * (i + 0.5))
            pts += [(cx - out * 2.5, 0.0), (cx, 4.0), (cx + out * 2.5, 0.0)]
        pts.append((X(20), 0.0))
        p.append(polyline(pts))
        mark = xs[min(k, npos - 1)]
        p.append(line(mark, -6, mark, 4))
        return p, 20, term
    if kind == "pushpull":
        p += [line(x, 0, X(10), 0), circle(X(15), 0, 5), line(X(15), -5, X(15), 5)]
        return p, 20, term
    if kind in ("pedal", "pedal2"):
        p += [line(x, 0, X(15), 0), line(X(10), -8, X(20), 8), line(X(10), -8, X(20), -8)]
        if kind == "pedal2":
            p.append(line(X(20), 8, X(28), 8))
            return p, 30, term
        return p, 20, term
    if kind in ("plunger", "plunger.limited"):
        p += [line(x, -3, X(6), -3), line(x, 3, X(6), 3), arc(X(6), 0, 3, 90, -180 if s > 0 else 180)]
        if kind == "plunger.limited":
            p += arrow(X(1), 8, X(9), -9, head=3.5, w="thin")
        return p, 10, term
    if kind in ("roller", "cam"):
        p += [line(x, 0, X(10), 0), circle(X(15), 0, 5), circle(X(15), 0, 1.2, fill=True, w="thin")]
        if kind == "cam":
            # cam surface touching the roller on the outer side, hatched on its far side (Y32 7.3, second form)
            a0, a1 = (X(20), -10), (X(23), 10)
            p.append(line(*a0, *a1))
            for i in range(5):
                t = (i + 0.5) / 5
                cx, cy = a0[0] + (a1[0] - a0[0]) * t, a0[1] + (a1[1] - a0[1]) * t
                p.append(line(cx, cy, cx + out * 3, cy + 2.5, w="thin"))
            return p, 30, term
        return p, 20, term
    if kind == "roller.lever":
        # HO "lever with roller": pivot at the stem, lever down to a roller, arrow = operating direction
        p += [line(x, 0, X(5), 0), circle(X(8), 0, 3), line(X(8), 0, X(17), 10),
              circle(X(20), 12, 4), circle(X(20), 12, 1.0, fill=True, w="thin")]
        p += arrow(X(24), -10, X(6), -10, head=3.5, w="thin")
        return p, 30, term
    if kind in ("solenoid.pushpull", "solenoid.prop"):
        p.append(_box(x, s, 0, 10, -6, 6))
        a, b = sorted((x, X(10)))
        if kind == "solenoid.pushpull":
            p.append(polyline([(a, 6), ((a + b) / 2, -6), (b, 6)]))   # HO: push/pull solenoid
        else:
            p.append(line(a, 6, b, -6))
            p += arrow(X(1) - out * 2, 9, X(9) + out * 2, -10, head=3.5, w="thin")
        return p, 10, term
    if kind == "pilot.direct":
        # HO "direct pilot operated": the pilot line runs straight to the envelope
        p.append(line(x, 0, X(20), 0, dash=True, w="thin"))
        return p, 20, (X(20), 0, "l" if s < 0 else "r")
    if kind in ("pilot.applied", "pilot.internal"):
        # HO "pneumatic / hydraulic operated", Y32 7.7.2 internal supply: box with energy triangle
        p += [_box(x, s, 0, 10, -6, 6), _pilot_triangle(x, s, 5, fill)]
        if kind == "pilot.applied":
            term = (X(10), 0, "l" if s < 0 else "r")
        return p, 10, term
    if kind == "pilot.remote":
        # Y32 7.7.1 remote supply: pilot line into an empty box
        p += [_box(x, s, 0, 10, -6, 6), line(X(10), 0, X(20), 0, dash=True, w="thin")]
        return p, 20, (X(20), 0, "l" if s < 0 else "r")
    if kind == "release.remote":
        # Y32 7.7.3 actuation by released pressure, by remote exhaust: hollow triangle pointing away
        p += [_box(x, s, 0, 10, -6, 6), _pilot_triangle(x, s, 5, False, toward_valve=False),
              line(X(10), 0, X(20), 0, dash=True, w="thin")]
        return p, 20, (X(20), 0, "l" if s < 0 else "r")
    if kind == "release.internal":
        p += [_box(x, s, 0, 10, -6, 6), _pilot_triangle(x, s, 5, True, toward_valve=False)]
        return p, 10, term
    if kind in ("solenoid.or.pilot.ext", "solenoid.or.pilot.int"):
        # Y32 7.8.1 solenoid OR pilot: solenoid box stacked above the pilot box
        a, b = sorted((x, X(10)))
        p += [_box(x, s, 0, 10, -5, 5), _pilot_triangle(x, s, 5, fill, half=3.0, length=5.0),
              rect(a, -15, b, -5), line(a, -5, b, -15)]
        if kind.endswith(".ext"):
            p.append(line(X(10), 0, X(20), 0, dash=True, w="thin"))
            return p, 20, (X(20), 0, "l" if s < 0 else "r")
        return p, 10, term
    if kind == "solenoid.and.pilot.ext":
        # Y32 7.8.2 solenoid AND pilot (solenoid-operated pilot stage); pilot supply enters from above
        a, b = sorted((X(20), X(30)))
        p += [_box(x, s, 0, 20, -6, 6), _pilot_triangle(x, s, 10, fill), rect(a, -6, b, 6), line(a, 6, b, -6),
              line(X(10), -6, X(10), -20, dash=True, w="thin")]
        return p, 30, (X(10), -20, "u")
    if kind == "solenoid.and.pilot.int":
        a, b = sorted((X(10), X(20)))
        p += [_box(x, s, 0, 10, -6, 6), _pilot_triangle(x, s, 5, fill), rect(a, -6, b, 6), line(a, 6, b, -6)]
        return p, 20, term
    if kind in ("motor", "motor.other"):
        # HO: drive unit coupled by a double-line stem
        p += [line(x, -2, X(6), -2), line(x, 2, X(6), 2)]
        if kind == "motor":
            p += [circle(X(13), 0, 7), text(X(13), 0, "M", size=7)]
        else:
            p += [_box(x, s, 6, 20, -7, 7), text(X(13), 0, "M", size=7)]
        return p, 20, term
    if kind == "motor.reversing":
        # Y32 7.6.2: motor with two opposed arrow heads on the stem
        p += [line(x, 0, X(16), 0), circle(X(23), 0, 7), text(X(23), 0, "M", size=7),
              arrowhead((X(6), -3), (X(14), -3)), arrowhead((X(14), 3), (X(6), 3))]
        return p, 30, term
    if kind == "compensated":
        # Y32 7.5 / 2.10: arrow parallel to the short side inside the control box
        p += [_box(x, s, 0, 10, -6, 6)] + arrow(X(5), 5, X(5), -5, head=3.0, w="thin")
        return p, 10, term
    if kind in ("thermal", "thermal.bulb"):
        # Y32 7.9: box with thermometer (line ending in a dot)
        p += [_box(x, s, 0, 20, -6, 6), line(X(10), -4, X(10), 2), circle(X(10), 3, 1.5, fill=True, w="thin")]
        if kind == "thermal.bulb":
            # capillary to a remote bulb; drawn outward (the source places the bulb below the valve)
            p += [polyline([(X(20), 0), (X(25), 0), (X(25), 14), (X(30), 14)])]
            p.append(_box(x, s, 30, 46, 11, 17))
            return p, 50, term
        return p, 20, term
    if kind == "servo":
        # Y32 7.10: energy input, command input (below) and resultant output toward the valve
        p += [_box(x, s, 0, 20, -7, 7), circle(X(10), 0, 3)]
        p.append(poly(X(13), 0, X(17), -2.5, X(17), 2.5, fill=True, w="thin"))     # input, from outside
        p.append(poly(X(3), 0, X(7), -2.5, X(7), 2.5, fill=True, w="thin"))       # output, toward the valve
        p.append(poly(X(10), 3, X(8), 6.5, X(12), 6.5, fill=True, w="thin"))       # command, from below
        return p, 20, term
    raise KeyError(kind)


VALVE_OPTIONS = {
    "proportional": "Infinite positioning (proportional) - bars along the envelopes",
    "transition": "Transition position between the two positions (2-position valves)",
}


def build_valve(params):
    medium = params.get("medium", "hyd")
    vtype = params.get("type", "4/3")
    if medium not in VALVE_TYPES or vtype not in VALVE_TYPES[medium]:
        medium, vtype = "hyd", "4/3"
    nports, npos = VALVE_TYPES[medium][vtype]
    positions = list(params.get("positions") or [])
    patterns = PATTERNS[nports]
    fallback = default_valve_params(medium, vtype)["positions"]
    positions = [positions[i] if i < len(positions) and positions[i] in patterns else fallback[i] for i in range(npos)]
    left = [o for o in params.get("left", []) if o in OPERATORS]
    right = [o for o in params.get("right", []) if o in OPERATORS]
    fill = medium == "hyd"
    layout = LAYOUTS[(medium, nports)]

    transition = bool(params.get("transition")) and npos == 2
    gap = HALF if transition else 0          # width of the transition position (HO / Y32 10.11.4)

    def centre(i):
        return x0 + HALF + ENV * i + (gap if i >= 1 else 0)

    W = ENV * npos + gap
    x0 = -W / 2
    p = []
    if transition:
        p += [line(x0 + ENV, -HALF, x0 + ENV + gap, -HALF, dash=True),
              line(x0 + ENV, HALF, x0 + ENV + gap, HALF, dash=True)]
    if params.get("proportional"):
        # Y32 10.3 / HO proportional spool: bars parallel to the envelopes
        p += [line(x0, -HALF - 4, x0 + W, -HALF - 4), line(x0, HALF + 4, x0 + W, HALF + 4)]
    for i in range(npos):
        cx = centre(i)
        p.append(rect(cx - HALF, -HALF, cx + HALF, HALF))
        pat = patterns[positions[i]]

        def edge(idx, inset=3.0):
            name, dx, side = layout[idx]
            y = -HALF + inset if side == "top" else HALF - inset
            return (cx + dx, y)

        for a, b in pat.get("arrows", []):
            (ax, ay), (bx, by) = edge(a), edge(b)
            p += arrow(ax, ay, bx, by, head=4.5)
        for idx in pat.get("blocked", []):
            name, dx, side = layout[idx]
            sg = -1 if side == "top" else 1
            yb = sg * HALF
            p += [line(cx + dx, yb, cx + dx, yb - sg * 7), line(cx + dx - 4, yb - sg * 7, cx + dx + 4, yb - sg * 7)]
        sp = pat.get("special")
        if sp == "tandem":
            # P and T joined inside the envelope
            p.append(polyline([(cx - 10, HALF), (cx - 10, 6), (cx + 10, 6), (cx + 10, HALF)]))
        elif sp == "float":
            p.append(line(cx + 10, -HALF, cx + 10, HALF))                              # B - T
            p.append(polyline([(cx - 10, -HALF), (cx - 10, 4), (cx + 10, 4)]))        # A - T
            p.append(circle(cx + 10, 4, 1.6, fill=True, w="thin"))
        elif sp == "both":
            # one straight path, flow possible in either direction
            p += [line(cx, -HALF + 3, cx, HALF - 3), arrowhead((cx, -HALF + 3), (cx, 0), length=4.5),
                  arrowhead((cx, HALF - 3), (cx, 0), length=4.5)]
        elif sp == "b-t":
            p.append(line(cx + 10, -HALF, cx + 10, HALF))                              # B - T straight
        elif sp == "apt":
            p += [line(cx - 10, -HALF, cx - 10, HALF),                                  # A - P
                  polyline([(cx - 10, 4), (cx + 10, 4), (cx + 10, HALF)]),              # ... - T
                  circle(cx - 10, 4, 1.6, fill=True, w="thin")]
        elif sp == "ab":
            p.append(polyline([(cx - 10, -HALF), (cx - 10, -HALF + 8), (cx + 10, -HALF + 8), (cx + 10, -HALF)]))
        elif sp == "a-t":
            p.append(line(cx - 10, -HALF, cx + 10, HALF))                              # A - T diagonal
        elif sp == "ab-pt":
            p += [polyline([(cx - 10, -HALF), (cx - 10, -HALF + 8), (cx + 10, -HALF + 8), (cx + 10, -HALF)]),
                  polyline([(cx - 10, HALF), (cx - 10, HALF - 8), (cx + 10, HALF - 8), (cx + 10, HALF)])]
        elif sp == "open":
            p += [line(cx - 10, -HALF, cx - 10, HALF), line(cx + 10, -HALF, cx + 10, HALF), line(cx - 10, 0, cx + 10, 0),
                  circle(cx - 10, 0, 1.6, fill=True, w="thin"), circle(cx + 10, 0, 1.6, fill=True, w="thin")]

    k = normal_position(npos, left, right)
    cxn = centre(k)
    terms = []
    for name, dx, side in layout:
        x = cxn + dx
        if side == "top":
            p.append(line(x, -HALF, x, -HALF - LEAD))
            terms.append(T(name, x, -HALF - LEAD, "u"))
        else:
            p.append(line(x, HALF, x, HALF + LEAD))
            terms.append(T(name, x, HALF + LEAD, "d"))

    for s, ops in ((-1, left), (1, right)):
        x = s * W / 2
        for kind in ops:
            res = _operator(kind, x, s, fill, {"npos": npos, "normal": k})
            prims, width = res[0], res[1]
            p += prims
            x += s * width
            if kind == "pilot":
                terms.append(T(_pilot_name(medium, s, positions, nports), x, 0, "l" if s < 0 else "r"))
            elif len(res) > 2 and res[2] is not None:
                tx, ty, tdir = res[2]
                terms.append(T(_pilot_name(medium, s, positions, nports), tx, ty, tdir))
    # make pilot terminal names unique if both sides use the same code
    seen = {}
    uniq = []
    for t in terms:
        n = t.name
        if n in seen:
            seen[n] += 1
            n = f"{n}.{seen[n]}"
        else:
            seen[n] = 1
        uniq.append(T(n, t.x, t.y, t.dir))
    return Geometry(p, uniq)


def valve_summary(params) -> str:
    medium = params.get("medium", "hyd")
    vtype = params.get("type", "4/3")
    try:
        nports = VALVE_TYPES[medium][vtype][0]
    except KeyError:
        return "directional valve"
    pos = params.get("positions", [])
    centre = ""
    if len(pos) == 3:
        centre = ", " + PATTERNS[nports].get(pos[1], {}).get("label", pos[1]).split(" (")[0].lower()
    ops = lambda side: "+".join(params.get(side, [])) or "none"
    extra = "".join(f", {w}" for key, w in (("proportional", "proportional"), ("transition", "with transition"))
                    if params.get(key))
    return (f"{vtype} way {'hydraulic' if medium == 'hyd' else 'pneumatic'}{centre}{extra}; "
            f"left: {ops('left')}, right: {ops('right')}")


# ================================================================ standalone operator elements
def operator_element(medium, cat, fill, kind, label):
    """A valve operator on its own (group "Valve operators"), drawn as it attaches to the left side of a
    switching-position envelope whose edge is at x = 0, for valves drawn by hand or in the symbol editor.
    It is the same drawing the configurator uses. Operators with a pilot connection have one terminal."""
    res = _operator(kind, 0, -1, fill, {"npos": 2, "normal": 0})
    prims, width = list(res[0]), res[1]
    pin = "X" if medium == "hyd" else "12"
    terms = []
    if kind == "pilot":
        terms = [T(pin, -width, 0, "l")]
    elif len(res) > 2 and res[2] is not None:
        tx, ty, tdir = res[2]
        terms = [T(pin, tx, ty, tdir)]
    notes = "Drawn for the left side of a valve; mirror the component for the right side."
    if kind == "detent":
        notes += " Two notches (two positions), the right-hand notch in use."
    return SymbolDef(f"fl.{medium}.op.{kind}", f"Valve operator: {label}", cat, "Valve operators", ISO,
                     f"{label} - valve operator element (also available in the directional-valve configurator).",
                     "", Geometry(prims, terms), keywords=("operator", "actuator", "control", "spool"), notes=notes)


# ================================================================ registry entries
def symbols():
    s = []
    add = s.append
    for medium, cat, fill in (("hyd", H, True), ("pneu", P, False)):
        pre = "fl." + medium
        if medium == "hyd":
            add(SymbolDef(f"{pre}.pump", "Pump, fixed displacement", cat, "Pumps & motors", ISO,
                          "Hydraulic pump, fixed displacement, one direction of flow. S = suction, P = pressure outlet.", "P",
                          Geometry(pump(True), [T("P", 0, -20, "u"), T("S", 0, 20, "d")]), keywords=("hpu",)))
            add(SymbolDef(f"{pre}.pump.var", "Pump, variable displacement", cat, "Pumps & motors", ISO,
                          "Hydraulic pump, variable displacement, one direction of flow.", "P",
                          Geometry(pump(True, True), [T("P", 0, -20, "u"), T("S", 0, 20, "d")])))
            add(SymbolDef(f"{pre}.motor", "Motor, fixed displacement", cat, "Pumps & motors", ISO,
                          "Hydraulic motor, fixed displacement, one direction of rotation. A = inlet, B = outlet.", "M",
                          Geometry(motor(True), [T("A", 0, -20, "u"), T("B", 0, 20, "d")])))
        else:
            add(SymbolDef(f"{pre}.compressor", "Compressor", cat, "Supply", ISO,
                          "Air compressor, fixed displacement.", "P",
                          Geometry(pump(False), [T("2", 0, -20, "u"), T("1", 0, 20, "d")])))
            add(SymbolDef(f"{pre}.motor", "Air motor, fixed displacement", cat, "Actuators", ISO,
                          "Pneumatic motor, fixed displacement, one direction of rotation.", "M",
                          Geometry(motor(False), [T("1", 0, -20, "u"), T("2", 0, 20, "d")])))
        act = "Cylinders" if medium == "hyd" else "Actuators"
        add(SymbolDef(f"{pre}.cyl.double", "Cylinder, double-acting", cat, act, ISO,
                      "Double-acting cylinder, single rod. A = cap-end port, B = rod-end port.", "A",
                      Geometry(cylinder_double(), [T("A", -20, -20, "u"), T("B", 10, -20, "u")]), keywords=("ram", "actuator")))
        add(SymbolDef(f"{pre}.cyl.doublerod", "Cylinder, double-acting, double rod", cat, act, ISO,
                      "Double-acting cylinder with through rod.", "A",
                      Geometry(cylinder_double(True), [T("A", -20, -20, "u"), T("B", 10, -20, "u")]), keywords=("actuator",)))
        add(SymbolDef(f"{pre}.cyl.single", "Cylinder, single-acting, spring return", cat, act, ISO,
                      "Single-acting cylinder, return by spring. A = cap-end port.", "A",
                      Geometry(cylinder_single_spring(), [T("A", -20, -20, "u")]), keywords=("ram", "actuator")))
        if medium == "hyd":
            add(SymbolDef(f"{pre}.relief", "Pressure-relief valve", cat, "Pressure control", ISO,
                          "Pressure-relief valve, direct operated, adjustable spring, internal pilot from P.", "V",
                          relief_valve(True), keywords=("safety", "rv")))
            add(SymbolDef(f"{pre}.reducing", "Pressure-reducing valve", cat, "Pressure control", ISO,
                          "Pressure-reducing valve, direct operated (normally open), pilot from outlet A.", "V",
                          reducing_valve(True), keywords=("prv",)))
        else:
            add(SymbolDef(f"{pre}.regulator", "Pressure regulator (non-relieving)", cat, "Pressure control", ISO,
                          "Pressure-reducing valve / regulator, direct operated, pilot from outlet. Relieving types are not shown.", "V",
                          reducing_valve(False, ("1", "2")), keywords=("prv",)))
        add(SymbolDef(f"{pre}.check", "Check valve", cat, "Non-return & flow", ISO,
                      "Non-return (check) valve, unloaded. Free flow from 1 to 2.", "V", check_valve(), keywords=("non-return", "nrv")))
        add(SymbolDef(f"{pre}.check.spring", "Check valve, spring loaded", cat, "Non-return & flow", ISO,
                      "Non-return valve with spring. Free flow from 1 to 2 when the cracking pressure is exceeded.", "V",
                      check_valve(True), keywords=("non-return",)))
        add(SymbolDef(f"{pre}.throttle", "Throttle (restrictor)", cat, "Non-return & flow", ISO,
                      "Fixed restriction (throttle / orifice), viscosity dependent.", "V", throttle(False), keywords=("orifice",)))
        add(SymbolDef(f"{pre}.throttle.adj", "Throttle, adjustable", cat, "Non-return & flow", ISO,
                      "Adjustable throttle (needle valve).", "V", throttle(True), keywords=("needle", "flow control")))
        add(SymbolDef(f"{pre}.flow.oneway", "One-way flow control valve", cat, "Non-return & flow", ISO,
                      "Adjustable throttle with bypass check valve: free flow 1→2, restricted flow 2→1.", "V",
                      one_way_flow_control(), keywords=("speed control", "meter")))
        names = ("X", "Y", "A") if medium == "hyd" else ("1", "1.1", "2")
        add(SymbolDef(f"{pre}.shuttle", "Shuttle valve", cat, "Non-return & flow", ISO,
                      "Shuttle valve (OR function): the higher-pressure inlet is connected to the outlet.", "V",
                      shuttle_valve(names), keywords=("or",), notes="Simplified seat representation."))
        add(SymbolDef(f"{pre}.dcv", "Directional control valve (configurable)", cat, "Directional valves", ISO,
                      "Directional control valve. Configure the way/position count, flow paths and operators in the properties panel.", "V",
                      builder=build_valve, default_params=default_valve_params(medium),
                      keywords=("spool", "solenoid valve", "4/3", "4/2", "5/2", "3/2", "2/2", "dcv")))
        for kind, label in OPERATORS.items():
            add(operator_element(medium, cat, fill, kind, label))
        if medium == "hyd":
            add(SymbolDef(f"{pre}.tank", "Reservoir (vented)", cat, "Fluid conditioning", ISO,
                          "Reservoir open to atmosphere; line ends below the fluid level.", "Z", reservoir(), keywords=("tank",)))
            add(SymbolDef(f"{pre}.accumulator", "Accumulator", cat, "Fluid conditioning", ISO,
                          "Accumulator, general symbol with separating element.", "Z", accumulator(),
                          notes="Gas-charge marking not shown."))
            add(SymbolDef(f"{pre}.filter", "Filter", cat, "Fluid conditioning", ISO,
                          "Filter or strainer, general symbol. Flow 1→2.", "Z", filter_geo(), keywords=("strainer",)))
        else:
            add(SymbolDef(f"{pre}.receiver", "Air receiver", cat, "Supply", ISO,
                          "Air receiver (pressure vessel).", "Z", air_receiver(), keywords=("tank", "vessel")))
            add(SymbolDef(f"{pre}.filter", "Filter", cat, "Supply", ISO,
                          "Air filter, general symbol (without water separator). Flow 1→2.", "Z", filter_geo(), keywords=("frl",)))
        add(SymbolDef(f"{pre}.gauge", "Pressure gauge", cat, "Measurement", ISO,
                      "Pressure indicator / gauge.", "S", gauge("P" if medium == "hyd" else "1"), keywords=("manometer",)))
    return s
