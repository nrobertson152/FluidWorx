"""Logic gates, flip-flops and arithmetic blocks (symbol-library expansion, batch E7).

Source: ECL = "Electric Components Library" (ElCompLib2017.svg, CC0 1.0), sections "Basic logic blocks" and
"Semiconductor devices" (Schmitt triggers). Distinctive-shape (ANSI/IEEE Std 91) gates, redrawn natively:
* inputs A, B, C, D, E on the left at x = -30, output Y on the right; inputs are 10 units apart on the grid, so
  a four-input gate leaves the centre position free and the output stays on the centre line;
* the five-input forms use an extended input bar, as the source draws them;
* power pins are not shown (as for the existing el.opamp).
"""
from __future__ import annotations

import math

from .base import IEEE, Geometry, SymbolDef, Terminal as T, arc, circle, line, poly, polyline, rect, text

EL = "Electronic"
G = "Logic"
NAMES = "ABCDE"
LAYOUT = {2: (-10, 10), 3: (-10, 0, 10), 4: (-20, -10, 10, 20), 5: (-20, -10, 0, 10, 20)}
BACK = -15.0


def quad(p0, p1, p2, n=12):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]


def back_curve(h, shift=0.0, d=5.0):
    """Concave input side of OR-type gates: circular arc through (BACK, -h) and (BACK, h), bulging d to the right.
    Returns (polyline, x_of_y)."""
    r = (h * h + d * d) / (2 * d)
    cx = BACK + d - r + shift
    x_of = lambda y: cx + math.sqrt(max(r * r - y * y, 0.0))  # noqa: E731
    pts = [(x_of(y), y) for y in (h * (i / 8 - 1) * 1 for i in range(17))]
    return polyline(pts), x_of


def gate(kind, n):
    ins = LAYOUT[n]
    h = 15.0 if n in (2, 3, 5) else 25.0
    inv = kind.startswith("n") or kind == "xnor"
    base = {"and": "and", "nand": "and", "or": "or", "nor": "or", "xor": "xor", "xnor": "xor"}[kind]
    p = []
    if base == "and":
        tip = h
        p += [polyline([(0, -h), (BACK, -h), (BACK, h), (0, h)]), arc(0, 0, h, 90, -180)]
        end = lambda y: BACK  # noqa: E731
    else:
        tip = h + 8
        p += [polyline(quad((BACK, -h), (tip * 0.45, -h), (tip, 0))),
              polyline(quad((BACK, h), (tip * 0.45, h), (tip, 0)))]
        curve, x_of = back_curve(h)
        p.append(curve)
        end = (lambda y: x_of(y) if abs(y) < h else BACK)  # noqa: E731
        if base == "xor":
            extra, x2 = back_curve(h, -5.0)
            p.append(extra)
            end = (lambda y: x2(y) if abs(y) < h else BACK - 5)  # noqa: E731
    if n == 5:                                           # extended input bar
        bx = BACK if base == "and" else BACK - (5 if base == "xor" else 0)
        p.append(line(bx, -20, bx, 20))
        if base != "and":
            end = (lambda y, e=end: e(y) if abs(y) < h else bx)  # noqa: E731
    for y in ins:
        p.append(line(-30, y, end(y), y))
    x = tip
    if inv:
        p.append(circle(tip + 2.5, 0, 2.5))
        x = tip + 5
    out = math.ceil((x + 5) / 10) * 10
    p.append(line(x, 0, out, 0))
    terms = [T(NAMES[i], -30, y, "l", ptype="elec.input") for i, y in enumerate(ins)]
    terms.append(T("Y", out, 0, "r", ptype="elec.output"))
    return Geometry(p, terms)


def qbar(x, y):
    return [text(x, y, "Q", size=7), line(x - 2.5, y - 5, x + 2.5, y - 5, w="thin")]


def clock(y):
    return [polyline([(-15, y - 4), (-9, y), (-15, y + 4)], )]


def ff(prims, ins, outs=(("Q", -10), ("/Q", 10)), half=20):
    p = [rect(-15, -half, 15, half)] + prims
    terms = []
    for name, y in ins:
        p.append(line(-30, y, -15, y))
        terms.append(T(name, -30, y, "l", ptype="elec.input"))
    for name, y in outs:
        p.append(line(15, y, 30, y))
        terms.append(T(name, 30, y, "r", label="Q̅" if name == "/Q" else "", ptype="elec.output"))
    return Geometry(p, terms)


def schmitt_mark():
    return [polyline([(-12, 3), (-6, 3), (-6, -3)], w="thin"), polyline([(-9, 3), (-9, -3), (-3, -3)], w="thin")]


def symbols():
    s = []
    add = s.append
    words = {"and": "AND", "nand": "NAND", "or": "OR", "nor": "NOR", "xor": "XOR", "xnor": "XNOR"}
    for n in (2, 3, 4, 5):
        for kind, word in words.items():
            add(SymbolDef(f"el.logic.{kind}{n}", f"{word} gate, {n} inputs", EL, G, IEEE,
                          f"{word} gate, {n} inputs ({', '.join(NAMES[:n])}), output Y; distinctive shape."
                          + (" Extended input bar." if n == 5 else ""), "U", gate(kind, n),
                          keywords=("logic", "gate", kind)))
    nt = [poly(-15, -10, 10, 0, -15, 10), circle(12.5, 0, 2.5), line(-30, 0, -15, 0), line(15, 0, 30, 0)]
    io = [T("A", -30, 0, "l", ptype="elec.input"), T("Y", 30, 0, "r", ptype="elec.output")]
    add(SymbolDef("el.logic.not", "NOT gate (inverter)", EL, G, IEEE, "Inverter: input A, output Y.", "U",
                  Geometry(nt, list(io)), keywords=("logic", "inverter", "not")))
    add(SymbolDef("el.logic.schmitt.not", "Schmitt-trigger inverter", EL, G, IEEE,
                  "Inverter with Schmitt-trigger (hysteresis) input: input A, output Y.", "U",
                  Geometry(nt + schmitt_mark(), list(io)), keywords=("logic", "hysteresis", "schmitt")))
    add(SymbolDef("el.logic.schmitt", "Schmitt-trigger buffer", EL, G, IEEE,
                  "Buffer with Schmitt-trigger (hysteresis) input: input A, output Y.", "U",
                  Geometry([poly(-15, -10, 10, 0, -15, 10), line(-30, 0, -15, 0), line(10, 0, 30, 0)] + schmitt_mark(),
                           list(io)), keywords=("logic", "hysteresis", "schmitt")))
    labels = [text(-9, -10, "D", size=7), text(9, -10, "Q", size=7)] + qbar(9, 10)
    add(SymbolDef("el.logic.dlatch", "D latch", EL, G, IEEE,
                  "Transparent D latch: data D, enable E, outputs Q and /Q.", "U",
                  ff(labels + [text(-9, 10, "E", size=7)], (("D", -10), ("E", 10))), keywords=("logic", "latch")))
    add(SymbolDef("el.logic.dff", "D flip-flop", EL, G, IEEE,
                  "Edge-triggered D flip-flop: data D, clock CLK, outputs Q and /Q.", "U",
                  ff(labels + clock(10), (("D", -10), ("CLK", 10))), keywords=("logic", "flip-flop", "register")))
    add(SymbolDef("el.logic.jkff", "JK flip-flop", EL, G, IEEE,
                  "Edge-triggered JK flip-flop: inputs J and K, clock CLK, outputs Q and /Q.", "U",
                  ff([text(-9, -10, "J", size=7), text(-9, 10, "K", size=7), text(9, -10, "Q", size=7)] + qbar(9, 10)
                     + clock(0), (("J", -10), ("CLK", 0), ("K", 10))), keywords=("logic", "flip-flop")))
    fa = [rect(-15, -25, 15, 25), line(0, -30, 0, -25), line(0, 25, 0, 30), line(-30, -10, -15, -10),
          line(-30, 10, -15, 10), line(15, 0, 30, 0), text(0, -18, "Cin", size=6), text(0, 18, "Cout", size=6),
          text(-9, -10, "A", size=7), text(-9, 10, "B", size=7), text(9, 0, "Y", size=7)]
    add(SymbolDef("el.logic.fulladder", "Full adder", EL, G, IEEE,
                  "One-bit full adder: inputs A, B and carry CIN, sum Y and carry COUT.", "U",
                  Geometry(fa, [T("CIN", 0, -30, "u", ptype="elec.input"), T("A", -30, -10, "l", ptype="elec.input"),
                                T("B", -30, 10, "l", ptype="elec.input"), T("Y", 30, 0, "r", ptype="elec.output"),
                                T("COUT", 0, 30, "d", ptype="elec.output")]), keywords=("logic", "adder", "arithmetic")))
    return s
