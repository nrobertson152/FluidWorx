"""The electrical side of a simulation: nets with voltages, the way the fluid side has nets with pressures.

Each net is a node. Parts are conductances and voltage sources, and each step is a linear system (linsolve.py). Parts
with more than one state (a diode conducting or not, a transistor saturated or not) are handled as the fluid side
handles seats: solve, see who disagrees, solve again. Discrete parts then follow, in a fixed order, so that a race has
one answer:

* logic gates and flip-flops all look at the same solution and change together, so a shift register shifts by one;
* relays change **one at a time**, re-solving in between, the first in drawing order winning. A relay changes at most
  once a step, so one that interrupts itself buzzes instead of hanging the program.

What this is: correct logic, and voltages and currents good enough for engineering checks (does the coil pick up, what
does the supply carry, does the fuse hold). What it isn't: a circuit simulator. AC is carried at its RMS value, with
L1, L2 and L3 as phasors, so there are no waveforms. Contacts don't bounce, relays have no operating time, diodes are
straight lines. docs/ELECTRICAL.md has the list.

The other side of each link is reached through the fluid parts' own small interface: set_energised, set_driven, and
the pressures and positions they already have.
"""
from __future__ import annotations

import cmath
import math
import re

from .linsolve import System, solve
from .vendor.openschematix import plc as plc_core

G_LEAK = 1e-9           # from every net to 0 V, so that nothing floats
G_CLOSED = 100.0        # a closed contact: 10 mΩ
G_RAIL = 100.0          # a line that is live because of its label
R_OUTPUT = 0.1          # a PLC's digital output
PICK_UP = 0.75          # of rated voltage: a relay pulls in here...
DROP_OUT = 0.40         # ...and lets go here
OVER_VOLTAGE = 1.25
EPS_V = 1e-4            # a change smaller than this isn't worth another solve
MAX_PIECEWISE = 30
MAX_SCANS_PER_STEP = 10
CHATTER_PER_SECOND = 20
FUSE_I2T = 10.0         # (I/In)^2 seconds: 10x in 0.1 s, 2x in about 3 s
BREAKER_I2T = 30.0      # 2x in 10 s; 5x and more at once
OVERLOAD_I2T = 400.0    # 7.2x in about 8 s, 2x in about 2 minutes


def mag(x) -> float:
    return abs(x)


def signed(x) -> float:
    """A voltage to show with its sign: a DC value as it is, a phasor by its size."""
    return x if not isinstance(x, complex) else abs(x)


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class Part:
    """What one electrical part does. `lines` are (from terminal, to terminal, conductance, emf)."""
    interactive = False
    quiet = False           # its status is shown but isn't worth a line in the event log

    def __init__(self, net: "Network", part):
        self.net, self.part = net, part
        self.t = part.terms
        self.names = part.names
        self.par = part.params
        self.lines = []

    def stamp(self, s):
        for ta, tb, g, e in self.current_lines():
            s.line(self.t[ta], self.t[tb], g, e)

    def current_lines(self):
        return self.lines

    def currents(self, v) -> dict:
        """Current into each terminal, in amps."""
        out = {}
        for ta, tb, g, e in self.current_lines():
            i = g * (v[self.t[ta]] - v[self.t[tb]] - e)
            out[ta] = out.get(ta, 0.0) + i
            out[tb] = out.get(tb, 0.0) - i
        return out

    def through(self) -> float:
        """The size of the current through a two-terminal part."""
        return max((mag(i) for i in self.currents(self.net.v).values()), default=0.0)

    def across(self, a=None, b=None):
        v = self.net.v
        return v[self.t[a or self.names[0]]] - v[self.t[b or self.names[1]]]

    def update(self, v) -> bool:
        return False

    def commit(self, v, dt):
        pass

    def reset(self):
        pass

    def status(self, p=None) -> str:
        return ""

    def readings(self, p=None) -> list:
        return []

    def actions(self) -> list:
        return []

    def command(self, name) -> bool:
        return False

    def command_text(self, name) -> str:
        return name

    def flows(self, p=None) -> dict:
        return {}

    def trace_channels(self) -> list:
        return []

    def is_on(self) -> bool:
        """Whether the part is doing what it does: the canvas draws it highlighted."""
        return False

    def _state_channel(self, label=""):
        return ((self.part.key, "state"), f"{self.part.tag} {label}".strip(), "state", lambda: 1.0 if self.is_on() else 0.0)


class Unsimulated(Part):
    quiet = True

    def status(self, p=None):
        return "Not simulated"


class Connection(Part):
    """Earth, a rail, a connection point, a terminal: all of it is decided when the nets are worked out."""
    quiet = True

    def readings(self, p=None):
        return [("Voltage", "voltage", signed(self.net.v[self.t[self.names[0]]]))] if self.names else []


class Resistor(Part):
    quiet = True

    def current_lines(self):
        return [(self.names[0], self.names[1], 1.0 / max(self.par["ohms"], 1e-3), 0.0)]

    def readings(self, p=None):
        return [("Voltage", "voltage", mag(self.across())), ("Current", "current", self.through()),
                ("Power", "power", mag(self.across()) * self.through())]


class Potentiometer(Part):
    """Ends 1 and 2, wiper 3. Set by hand, or by whatever its Senses property names."""
    quiet = True

    def __init__(self, net, part):
        super().__init__(net, part)
        self.reader = None
        self.driven = None

    def fraction(self):
        return self.driven if self.driven is not None else clamp(self.par["wiper"] / 100.0, 0.0, 1.0)

    def sense(self, dt):
        if self.reader is not None:
            f = self.reader.fraction(0.0, 0.0)
            if self.driven is None or abs(f - self.driven) > 5e-4:
                self.driven = f
                self.net.dirty = True

    def current_lines(self):
        r = max(self.par["ohms"], 1e-3)
        w = self.fraction()
        return [("1", "3", 1.0 / max(r * w, 1e-2), 0.0), ("3", "2", 1.0 / max(r * (1.0 - w), 1e-2), 0.0)]

    def readings(self, p=None):
        return [("Wiper", "percent", 100.0 * self.fraction()), ("Wiper voltage", "voltage", mag(self.net.v[self.t["3"]]))]


class Capacitor(Part):
    quiet = True

    def __init__(self, net, part):
        super().__init__(net, part)
        self.vc = 0.0

    def reset(self):
        self.vc = 0.0

    def current_lines(self):
        return [(self.names[0], self.names[1], self.par["farads"] / self.net.dt, self.vc)]

    def commit(self, v, dt):
        new = v[self.t[self.names[0]]] - v[self.t[self.names[1]]]
        if mag(new - self.vc) > EPS_V:
            self.net.dirty = True
        self.vc = new

    def readings(self, p=None):
        return [("Voltage", "voltage", signed(self.vc)), ("Current", "current", self.through())]


class Inductor(Part):
    quiet = True

    def __init__(self, net, part):
        super().__init__(net, part)
        self.i = 0.0

    def reset(self):
        self.i = 0.0

    def _g_e(self):
        l_dt = self.par["henries"] / self.net.dt
        return 1.0 / (self.par["rdc"] + l_dt), -l_dt * self.i

    def current_lines(self):
        g, e = self._g_e()
        return [(self.names[0], self.names[1], g, e)]

    def commit(self, v, dt):
        g, e = self._g_e()
        drop = v[self.t[self.names[0]]] - v[self.t[self.names[1]]]
        new = g * (drop - e)
        if mag(drop) > 1000.0:      # the current had nowhere to go: in real life, an arc takes the energy
            new = 0.0
            self.net.dirty = True
        if mag(new - self.i) > 1e-6:
            self.net.dirty = True
        self.i = new

    def readings(self, p=None):
        return [("Current", "current", mag(self.i)), ("Voltage", "voltage", mag(self.across()))]


# ---------------------------------------------------------------- sources
class Source(Part):
    """A voltage behind a small resistance, that folds back to its current limit if it has one."""

    def __init__(self, net, part):
        super().__init__(net, part)
        self.plus, self.minus = self.terminals()
        self.limited = False
        self.shorted = False

    def terminals(self):
        return self.names[0], self.names[1]

    def emf(self):
        return self.par["voltage"]

    def rint(self):
        return self.par.get("rint", 0.02)

    def live(self):
        return True

    def limit(self):
        return self.par.get("limit", 0.0)

    def current_out(self, v):
        if not self.live():
            return 0.0
        if self.limited:
            return self.limit()
        return (self.emf() - (v[self.t[self.plus]] - v[self.t[self.minus]])) / self.rint()

    def stamp(self, s):
        if not self.live():
            return
        if self.limited:
            s.source(self.t[self.minus], self.t[self.plus], self.limit())
        else:
            s.line(self.t[self.plus], self.t[self.minus], 1.0 / self.rint(), self.emf())

    def currents(self, v):
        i = self.current_out(v)
        return {self.plus: -i, self.minus: i}

    def update(self, v):
        lim = self.limit()
        if lim <= 0:
            if self.limited:
                self.limited = False
                return True
            return False
        if self.limited:
            if mag(v[self.t[self.plus]] - v[self.t[self.minus]]) > mag(self.emf()):
                self.limited = False
                return True
        elif mag(self.current_out(v)) > lim:
            self.limited = True
            return True
        return False

    def commit(self, v, dt):
        emf = mag(self.emf())
        out = mag(v[self.t[self.plus]] - v[self.t[self.minus]])
        short = self.live() and emf > 0 and out < 0.5 * emf and not self.limited
        if short and not self.shorted:
            self.net.sim.log(self.part.tag, f"Short circuit: it would supply {mag(self.current_out(v)):.0f} A")
        self.shorted = short

    def reset(self):
        self.limited = False
        self.shorted = False

    def status(self, p=None):
        if not self.live():
            return "Off"
        if self.limited:
            return "Overloaded: at its current limit"
        return "Short circuit" if self.shorted else "On"

    def is_on(self):
        return self.live()

    def readings(self, p=None):
        v = self.net.v
        volts = v[self.t[self.plus]] - v[self.t[self.minus]]
        amps = mag(self.current_out(v))
        return [("Voltage", "voltage", signed(volts)), ("Current", "current", amps), ("Power", "power", mag(volts) * amps)]

    def trace_channels(self):
        return [((self.part.key, "i"), f"{self.part.tag} current", "current", lambda: mag(self.current_out(self.net.v)))]


class CurrentSource(Part):
    """A current, as far as 100 V can push it."""
    quiet = True
    COMPLIANCE = 100.0

    def __init__(self, net, part):
        super().__init__(net, part)
        self.clamped = False

    def reset(self):
        self.clamped = False

    def stamp(self, s):
        a, b = self.t[self.names[0]], self.t[self.names[1]]
        if self.clamped:
            s.line(b, a, 1.0, self.COMPLIANCE * (1 if self.par["current"] >= 0 else -1))
        else:
            s.source(a, b, self.par["current"])

    def update(self, v):
        a, b = self.t[self.names[0]], self.t[self.names[1]]
        rise = (v[b] - v[a]) * (1 if self.par["current"] >= 0 else -1)
        want = rise.real > self.COMPLIANCE if not self.clamped else rise.real > self.COMPLIANCE - abs(self.par["current"])
        if want != self.clamped:
            self.clamped = want
            return True
        return False

    def currents(self, v):
        a, b = self.names[0], self.names[1]
        i = (self.COMPLIANCE * (1 if self.par["current"] >= 0 else -1) - (v[self.t[b]] - v[self.t[a]])) if self.clamped \
            else self.par["current"]
        return {a: i, b: -i}

    def readings(self, p=None):
        return [("Current", "current", abs(self.par["current"])), ("Voltage", "voltage", mag(self.across()))]


class PowerSupply(Source):
    """Mains in, DC out. It needs its input if the drawing connects one; drawn with the input left open, it's just on."""

    def __init__(self, net, part):
        self.input = part.spec.options["pins"][:2]
        super().__init__(net, part)
        self.always_on = all(n in part.open_terms for n in self.input)
        self.on = self.always_on
        self.g_in = 1e-6

    def terminals(self):
        return self.part.spec.options["pins"][2:]

    def rint(self):
        return 0.02

    def live(self):
        return self.on

    def stamp(self, s):
        super().stamp(s)
        s.line(self.t[self.input[0]], self.t[self.input[1]], self.g_in)

    def currents(self, v):
        out = super().currents(v)
        i = self.g_in * (v[self.t[self.input[0]]] - v[self.t[self.input[1]]])
        out[self.input[0]] = i
        out[self.input[1]] = -i
        return out

    def _vin(self, v):
        return mag(v[self.t[self.input[0]]] - v[self.t[self.input[1]]])

    def update(self, v):
        changed = False
        if not self.always_on:
            lo = self.par["input_min"]
            vin = self._vin(v)
            want = vin >= (lo * 0.9 if self.on else lo)
            if want != self.on:
                self.on = want
                changed = True
        return super().update(v) or changed

    def commit(self, v, dt):
        super().commit(v, dt)
        vin = self._vin(v)
        if vin > 1.0:
            drawn = mag(v[self.t[self.plus]] - v[self.t[self.minus]]) * mag(self.current_out(v))
            g = max(1e-6, drawn / max(self.par["efficiency"] / 100.0, 0.01) / vin ** 2)
            if abs(g - self.g_in) > 0.02 * self.g_in + 1e-7:
                self.g_in = g
                self.net.dirty = True

    def reset(self):
        super().reset()
        self.on = self.always_on
        self.g_in = 1e-6

    def status(self, p=None):
        return "No input" if not self.on else super().status(p)


class Rectifier(Part):
    """A DC output in proportion to the AC input, that can only source current."""

    def __init__(self, net, part):
        super().__init__(net, part)
        self.emf = 0.0
        self.on = False
        self.g_in = 1e-6

    def reset(self):
        self.emf = 0.0
        self.on = False
        self.g_in = 1e-6

    def current_lines(self):
        out = [("AC1", "AC2", self.g_in, 0.0)]
        if self.on:
            out.append(("+", "-", 10.0, self.emf))
        return out

    def update(self, v):
        changed = False
        emf = self.par["factor"] * mag(v[self.t["AC1"]] - v[self.t["AC2"]])
        if abs(emf - self.emf) > 1e-3:
            self.emf = emf
            changed = True
        out = (v[self.t["+"]] - v[self.t["-"]]).real
        want = out < self.emf - 1e-3 if not self.on else 10.0 * (self.emf - out) > -1e-3 and self.emf > 1e-3
        if want != self.on:
            self.on = want
            changed = True
        return changed

    def commit(self, v, dt):
        vin = mag(v[self.t["AC1"]] - v[self.t["AC2"]])
        if vin > 1.0:
            out = (v[self.t["+"]] - v[self.t["-"]]).real
            drawn = max(0.0, 10.0 * (self.emf - out)) * out if self.on else 0.0
            g = max(1e-6, drawn / vin ** 2)
            if abs(g - self.g_in) > 0.02 * self.g_in + 1e-7:
                self.g_in = g
                self.net.dirty = True

    def status(self, p=None):
        return "On" if self.emf > 1.0 else "No input"

    def is_on(self):
        return self.emf > 1.0

    def readings(self, p=None):
        return [("DC output", "voltage", (self.net.v[self.t["+"]] - self.net.v[self.t["-"]]).real)]


class Regulator(Part):
    """A linear regulator: the set voltage while the input allows it, then the input less its dropout."""
    G = 20.0

    def __init__(self, net, part):
        super().__init__(net, part)
        self.mode = "off"

    def reset(self):
        self.mode = "off"

    def stamp(self, s):
        i, o, g = self.t["IN"], self.t["OUT"], self.t["GND"]
        s.line(i, g, 2e-4)      # what it draws for itself
        if self.mode == "reg":
            s.vccs(i, o, g, o, self.G)
            s.source(i, o, self.G * self.par["voltage"])
        elif self.mode == "drop":
            s.line(i, o, self.G, self.par["dropout"])

    def _io(self, v):
        if self.mode == "reg":
            return self.G * (v[self.t["GND"]] + self.par["voltage"] - v[self.t["OUT"]])
        if self.mode == "drop":
            return self.G * (v[self.t["IN"]] - v[self.t["OUT"]] - self.par["dropout"])
        return 0.0

    def currents(self, v):
        i = self._io(v)
        q = 2e-4 * (v[self.t["IN"]] - v[self.t["GND"]])
        return {"IN": i + q, "OUT": -i, "GND": -q}

    def update(self, v):
        vin = (v[self.t["IN"]] - v[self.t["GND"]]).real
        vo = (v[self.t["OUT"]] - v[self.t["GND"]]).real
        need = self.par["voltage"] + self.par["dropout"]
        mode = self.mode
        if mode == "reg":
            if vin < need - 1e-3:
                mode = "drop"
        elif mode == "drop":
            if vin > need + 1e-3:
                mode = "reg"
            elif self._io(v).real < -1e-6:
                mode = "off"
        else:
            if vin > need + 1e-3:
                mode = "reg"
            elif vin - vo > self.par["dropout"] + 1e-3:
                mode = "drop"
        if mode != self.mode:
            self.mode = mode
            return True
        return False

    def status(self, p=None):
        return {"reg": "Regulating", "drop": "Dropped out: not enough input", "off": "Off"}[self.mode]

    def is_on(self):
        return self.mode != "off"

    def readings(self, p=None):
        return [("Output", "voltage", (self.net.v[self.t["OUT"]] - self.net.v[self.t["GND"]]).real),
                ("Current", "current", mag(self._io(self.net.v)))]


class Transformer(Part):
    """An ideal transformer with a little winding resistance. It passes whatever is on the primary, RMS or phasor."""
    quiet = True

    def _windings(self):
        ratio = self.par["secondary"] / max(self.par["primary"], 1e-6)
        return [(a, b, ratio * share) for a, b, share in self.part.spec.options["windings"]]

    def stamp(self, s):
        p1, p2 = self.t["P1"], self.t["P2"]
        s.line(p1, p2, 1e-6)
        g = 1.0 / self.par["rs"]
        for a, b, k in self._windings():
            sa, sb = self.t[a], self.t[b]
            s.line(sa, sb, g)
            s.vccs(sb, sa, p1, p2, g * k)
            s.line(p1, p2, g * k * k)
            s.vccs(p1, p2, sa, sb, -g * k)

    def currents(self, v):
        vp = v[self.t["P1"]] - v[self.t["P2"]]
        g = 1.0 / self.par["rs"]
        out = {"P1": 1e-6 * vp, "P2": -1e-6 * vp}
        for a, b, k in self._windings():
            i = g * (k * vp - (v[self.t[a]] - v[self.t[b]]))
            out[a] = out.get(a, 0.0) - i
            out[b] = out.get(b, 0.0) + i
            out["P1"] += k * i
            out["P2"] -= k * i
        return out

    def readings(self, p=None):
        v = self.net.v
        out = [("Primary", "voltage", mag(v[self.t["P1"]] - v[self.t["P2"]]))]
        for a, b, _k in self._windings():
            out.append((f"{a}-{b}", "voltage", mag(v[self.t[a]] - v[self.t[b]])))
        return out

    def status(self, p=None):
        return "Live" if mag(self.net.v[self.t["P1"]] - self.net.v[self.t["P2"]]) > 1.0 else "No supply"


class Autotransformer(Part):
    """One winding 1-2, tapped at 3. The tap follows the supply across the winding."""
    quiet = True

    def stamp(self, s):
        a, b, tap = self.t["1"], self.t["2"], self.t["3"]
        k = clamp(self.par["ratio"] / 100.0, 0.001, 0.999)
        g = 20.0
        s.line(a, b, 1e-6)
        # the tap's voltage above end 2 is k of the winding's
        s.line(tap, b, g)
        s.vccs(b, tap, a, b, g * k)
        s.line(a, b, g * k * k)
        s.vccs(a, b, tap, b, -g * k)

    def currents(self, v):
        k = clamp(self.par["ratio"] / 100.0, 0.001, 0.999)
        vw = v[self.t["1"]] - v[self.t["2"]]
        i = 20.0 * (k * vw - (v[self.t["3"]] - v[self.t["2"]]))
        return {"1": k * i + 1e-6 * vw, "3": -i, "2": i - k * i - 1e-6 * vw}

    def readings(self, p=None):
        return [("Tap", "voltage", mag(self.net.v[self.t["3"]] - self.net.v[self.t["2"]]))]


# ---------------------------------------------------------------- semiconductors
class Diode(Part):
    """Forward: a small voltage then a small resistance. Breakdown, if it has one, the same in reverse."""
    quiet = True
    TOL = 1e-3

    def __init__(self, net, part):
        super().__init__(net, part)
        self.mode = 0       # 0 off, 1 forward, -1 in breakdown
        self.a, self.k = self.names[0], self.names[1]

    def reset(self):
        self.mode = 0

    def forward_drop(self):
        return self.par.get("vf", 0.7)

    def breakdown(self):
        return None

    def current_lines(self):
        rd = self.par["rd"]
        if self.mode > 0:
            return [(self.a, self.k, 1.0 / rd, self.forward_drop())]
        if self.mode < 0:
            return [(self.k, self.a, 1.0 / rd, self.breakdown())]
        return []

    def update(self, v):
        d = (v[self.t[self.a]] - v[self.t[self.k]]).real
        fwd, rev = self.forward_drop(), self.breakdown()
        mode = self.mode
        if mode > 0:
            if d < fwd - self.TOL:
                mode = 0
        elif mode < 0:
            if -d < rev - self.TOL:
                mode = 0
        else:
            if d > fwd + self.TOL:
                mode = 1
            elif rev is not None and -d > rev + self.TOL:
                mode = -1
        if mode != self.mode:
            self.mode = mode
            return True
        return False

    def status(self, p=None):
        return {0: "Blocking", 1: "Conducting", -1: "In breakdown"}[self.mode]

    def is_on(self):
        return self.mode != 0

    def readings(self, p=None):
        return [("Voltage", "voltage", (self.net.v[self.t[self.a]] - self.net.v[self.t[self.k]]).real),
                ("Current", "current", self.through())]


class Zener(Diode):
    def forward_drop(self):
        return self.par["vz"] if self.part.spec.options.get("bidir") else 0.7

    def breakdown(self):
        return self.par["vz"]


class Led(Diode):
    quiet = False

    def status(self, p=None):
        return "Lit" if self.is_on() else "Off"

    def is_on(self):
        return self.mode > 0 and self.through() > 1e-4

    def trace_channels(self):
        return [self._state_channel("lit")]


class Bjt(Part):
    """Cut off, active (collector current is hFE times base current) or saturated."""
    quiet = True
    RB = 10.0
    RC = 0.1

    def __init__(self, net, part):
        super().__init__(net, part)
        self.sign = part.spec.options.get("polarity", 1)
        self.mode = "off"

    def reset(self):
        self.mode = "off"

    def _ends(self, a, b):
        return (a, b) if self.sign > 0 else (b, a)

    def stamp(self, s):
        if self.mode == "off":
            return
        b, c, e = self.t["B"], self.t["C"], self.t["E"]
        vbe, gb = self.par["vbe"], 1.0 / self.RB
        s.line(*self._ends(b, e), gb, vbe)
        if self.mode == "sat":
            s.line(*self._ends(c, e), 1.0 / self.RC, self.par["vcesat"])
        else:
            k = self.par["beta"] * gb
            x, y = self._ends(c, e)
            s.vccs(x, y, *self._ends(b, e), k)
            s.source(x, y, -k * vbe)

    def _state(self, v):
        vb = self.sign * (v[self.t["B"]] - v[self.t["E"]]).real
        vc = self.sign * (v[self.t["C"]] - v[self.t["E"]]).real
        ib = max(0.0, (vb - self.par["vbe"]) / self.RB) if self.mode != "off" else 0.0
        if self.mode == "sat":
            ic = (vc - self.par["vcesat"]) / self.RC
        elif self.mode == "active":
            ic = self.par["beta"] * ib
        else:
            ic = 0.0
        return vb, vc, ib, ic

    def currents(self, v):
        _vb, _vc, ib, ic = self._state(v)
        s = self.sign
        return {"B": s * ib, "C": s * ic, "E": -s * (ib + ic)}

    def update(self, v):
        vb, vc, ib, ic = self._state(v)
        mode = self.mode
        vbe = self.par["vbe"]
        if mode == "off":
            if vb > vbe + 1e-3:
                mode = "active"
        elif vb < vbe - 1e-3:
            mode = "off"
        elif mode == "active":
            if vc < self.par["vcesat"] - 1e-3:
                mode = "sat"
        elif ic > self.par["beta"] * ib + 1e-6:
            mode = "active"
        if mode != self.mode:
            self.mode = mode
            return True
        return False

    def status(self, p=None):
        return {"off": "Off", "active": "Active", "sat": "Saturated: fully on"}[self.mode]

    def is_on(self):
        return self.mode != "off"

    def readings(self, p=None):
        _vb, vc, ib, ic = self._state(self.net.v)
        return [("Vce", "voltage", vc), ("Base current", "current", ib), ("Collector current", "current", ic)]


class Fet(Part):
    """A switch, with its on resistance, that the gate-source voltage turns on."""
    quiet = True

    def __init__(self, net, part):
        super().__init__(net, part)
        self.sign = part.spec.options.get("polarity", 1)
        self.on = False

    def reset(self):
        self.on = False

    def current_lines(self):
        return [("D", "S", 1.0 / self.par["rds"], 0.0)] if self.on else []

    def update(self, v):
        vgs = self.sign * (v[self.t["G"]] - v[self.t["S"]]).real
        th = self.par["vth"]
        want = vgs > (th - 0.05 if self.on else th + 0.05)
        if want != self.on:
            self.on = want
            return True
        return False

    def status(self, p=None):
        return "On" if self.on else "Off"

    def is_on(self):
        return self.on

    def readings(self, p=None):
        return [("Vgs", "voltage", (self.net.v[self.t["G"]] - self.net.v[self.t["S"]]).real), ("Current", "current", self.through())]


class Thyristor(Part):
    """Off until its gate fires it, then on until the current falls below its holding current."""
    quiet = True
    R_GATE = 1000.0
    R_ON = 0.05
    V_ON = 1.0

    def __init__(self, net, part):
        super().__init__(net, part)
        self.a, self.k, self.g = part.spec.options["pins"]
        self.bidir = bool(part.spec.options.get("bidir"))
        self.on = False
        self.direction = 1

    def reset(self):
        self.on = False
        self.direction = 1

    def current_lines(self):
        out = [(self.g, self.k, 1.0 / self.R_GATE, 0.0)]
        if self.on:
            if self.direction > 0:
                out.append((self.a, self.k, 1.0 / self.R_ON, self.V_ON))
            else:
                out.append((self.k, self.a, 1.0 / self.R_ON, self.V_ON))
        return out

    def update(self, v):
        d = (v[self.t[self.a]] - v[self.t[self.k]]).real
        if self.on:
            drop = abs(d)
            if (drop - self.V_ON) / self.R_ON < self.par["ih"]:
                self.on = False
                return True
            return False
        ig = (v[self.t[self.g]] - v[self.t[self.k]]).real / self.R_GATE
        fires = (ig >= self.par["igt"] and d > self.V_ON) or (self.bidir and abs(ig) >= self.par["igt"] and abs(d) > self.V_ON)
        if fires:
            self.on = True
            self.direction = 1 if d > 0 else -1
            return True
        return False

    def status(self, p=None):
        return "Conducting" if self.on else "Off"

    def is_on(self):
        return self.on

    def readings(self, p=None):
        return [("Voltage", "voltage", (self.net.v[self.t[self.a]] - self.net.v[self.t[self.k]]).real), ("Current", "current", self.through())]


class OpAmp(Part):
    """High gain until the output reaches a supply pin less 1.5 V, or its set swing when no supply pins are drawn."""
    quiet = True
    G_OUT = 0.1

    def __init__(self, net, part):
        super().__init__(net, part)
        self.mode = 0       # 0 linear, 1 at the top, -1 at the bottom
        self.has_supply = "V+" in part.terms

    def reset(self):
        self.mode = 0

    def _limits(self, v):
        if self.has_supply:
            hi = v[self.t["V+"]].real - 1.5
            lo = v[self.t["V-"]].real + 1.5
            return (hi, lo) if hi > lo else (0.5 * (hi + lo), 0.5 * (hi + lo))
        return self.par["vsat"], -self.par["vsat"]

    def stamp(self, s):
        gnd = self.net.gnd
        out, plus, minus = self.t["OUT"], self.t["+"], self.t["-"]
        s.line(plus, gnd, 1e-7)
        s.line(minus, gnd, 1e-7)
        if self.has_supply:
            s.line(self.t["V+"], gnd, 1e-4)
            s.line(self.t["V-"], gnd, 1e-4)
        s.line(out, gnd, self.G_OUT)
        if self.mode == 0:
            s.vccs(gnd, out, plus, minus, self.G_OUT * self.par["gain"])
        else:
            hi, lo = self._limits(self.net.v)
            s.source(gnd, out, self.G_OUT * (hi if self.mode > 0 else lo))

    def currents(self, v):
        return {"OUT": self.G_OUT * (v[self.t["OUT"]] - self._target(v))}

    def _target(self, v):
        hi, lo = self._limits(v)
        if self.mode == 0:
            return self.par["gain"] * (v[self.t["+"]] - v[self.t["-"]])
        return hi if self.mode > 0 else lo

    def update(self, v):
        hi, lo = self._limits(v)
        ideal = (self.par["gain"] * (v[self.t["+"]] - v[self.t["-"]])).real
        mode = 1 if ideal > hi + 1e-3 else -1 if ideal < lo - 1e-3 else 0
        if mode != self.mode:
            self.mode = mode
            return True
        return False

    def status(self, p=None):
        return {0: "Linear", 1: "At its upper limit", -1: "At its lower limit"}[self.mode]

    def readings(self, p=None):
        v = self.net.v
        return [("Output", "voltage", v[self.t["OUT"]].real), ("+ minus -", "voltage", (v[self.t["+"]] - v[self.t["-"]]).real)]


class Logic(Part):
    """A gate or flip-flop. Its power pins aren't drawn, so it's always live, and high is the circuit's own voltage.

    Inputs are high impedance, and read as low if nothing drives them. All logic parts look at the same solution and
    change together, which is what makes a flip-flop capture the value from before the clock edge."""
    quiet = True
    G_OUT = 1 / 50.0
    G_IN = 1e-6

    def __init__(self, net, part):
        super().__init__(net, part)
        self.op = part.comp.symbol.split(".", 2)[2]
        self.family = re.sub(r"\d$", "", self.op)
        self.outs = [n for n in part.names if n in ("Y", "Q", "/Q", "COUT")]
        self.ins = [n for n in part.names if n not in self.outs]
        self.level = {n: False for n in self.ins}
        self.q = {n: n == "/Q" for n in self.outs}
        self.clk = False

    def reset(self):
        self.level = {n: False for n in self.ins}
        self.q = {n: n == "/Q" for n in self.outs}
        self.clk = False

    def _vhigh(self):
        return self.par["vhigh"] or self.net.logic_voltage(self.t[self.names[0]])

    def stamp(self, s):
        gnd, high = self.net.gnd, self._vhigh()
        for n in self.ins:
            s.line(self.t[n], gnd, self.G_IN)
        for n in self.outs:
            s.line(self.t[n], gnd, self.G_OUT, high if self.q[n] else 0.0)

    def currents(self, v):
        high = self._vhigh()
        return {n: self.G_OUT * (v[self.t[n]] - (high if self.q[n] else 0.0)) for n in self.outs}

    def _read(self, v):
        high = max(self._vhigh(), 1e-6)
        schmitt = self.family.startswith("schmitt")
        for n in self.ins:
            x = v[self.t[n]].real / high
            if schmitt:
                self.level[n] = x > (1 / 3 if self.level[n] else 2 / 3)
            else:
                self.level[n] = x > 0.5

    def evaluate(self, v) -> bool:
        """Work out the outputs from this solution. True if any changed."""
        self._read(v)
        new = self._next()
        if new != self.q:
            self.q = new
            return True
        return False

    def _next(self):
        lv = self.level
        f = self.family
        vals = [lv[n] for n in self.ins]
        if f in ("and", "nand"):
            y = all(vals)
            return {"Y": y if f == "and" else not y}
        if f in ("or", "nor"):
            y = any(vals)
            return {"Y": y if f == "or" else not y}
        if f in ("xor", "xnor"):
            y = sum(vals) % 2 == 1
            return {"Y": y if f == "xor" else not y}
        if f in ("not", "schmitt.not"):
            return {"Y": not lv["A"]}
        if f == "schmitt":
            return {"Y": lv["A"]}
        if f == "fulladder":
            total = lv["A"] + lv["B"] + lv["CIN"]
            return {"Y": total % 2 == 1, "COUT": total >= 2}
        q = self.q["Q"]
        if f == "dlatch":
            q = lv["D"] if lv["E"] else q
        else:
            rising = lv["CLK"] and not self.clk
            self.clk = lv["CLK"]
            if rising:
                if f == "dff":
                    q = lv["D"]
                elif lv["J"] and lv["K"]:
                    q = not q
                elif lv["J"]:
                    q = True
                elif lv["K"]:
                    q = False
        return {"Q": q, "/Q": not q}

    def status(self, p=None):
        return ", ".join(f"{n} {'high' if self.q[n] else 'low'}" for n in self.outs)

    def is_on(self):
        return any(self.q.values())


# ---------------------------------------------------------------- protection
class Protection(Part):
    """Conducts until the heat of an overcurrent, as (I/In)^2 seconds, opens it. All its poles together."""
    interactive = True
    I2T = FUSE_I2T
    INSTANT = 0.0       # trips at once at this many times its rating

    def __init__(self, net, part):
        super().__init__(net, part)
        n = part.names
        self.poles = list(zip(n[:len(n) // 2], n[len(n) // 2:]))
        self.reset()

    def reset(self):
        self.heat = 0.0
        self.tripped = False
        self.is_open = False

    def current_lines(self):
        return [] if self.is_open else [(a, b, G_CLOSED, 0.0) for a, b in self.poles]

    def _rating(self):
        return max(self.par["rating"], 1e-6)

    def _trip(self, why):
        self.tripped = self.is_open = True
        self.net.dirty = True
        self.net.sim.log(self.part.tag, why)

    def commit(self, v, dt):
        if self.is_open:
            return
        i = max((mag(G_CLOSED * (v[self.t[a]] - v[self.t[b]])) for a, b in self.poles), default=0.0)
        r = i / self._rating()
        if self.INSTANT and r >= self.INSTANT:
            self._trip(f"Tripped at once on {i:.1f} A")
            return
        self.heat = max(0.0, self.heat + (r * r - 1.0) * dt) if r > 1.0 else self.heat * (1.0 - dt / 30.0)
        if self.heat >= self.I2T:
            self._trip(f"Blew on {i:.1f} A" if type(self) is Fuse else f"Tripped on {i:.1f} A")

    def readings(self, p=None):
        amps = 0.0 if self.is_open else max((mag(G_CLOSED * self.across(a, b)) for a, b in self.poles), default=0.0)
        return [("Current", "current", amps), ("Load", "percent", 100.0 * amps / self._rating())]

    def is_on(self):
        return not self.is_open

    def trace_channels(self):
        return [self._state_channel("closed")]


class Fuse(Protection):
    def status(self, p=None):
        return "Blown" if self.is_open else "OK"

    def actions(self):
        return [("reset", "Replace the fuse", False)] if self.is_open else []

    def command(self, name):
        if name == "reset" and self.is_open:
            self.reset()
            self.net.dirty = True
            return True
        return False

    def command_text(self, name):
        return "Replaced"


class Breaker(Protection):
    I2T = BREAKER_I2T
    INSTANT = 5.0

    def status(self, p=None):
        return "Tripped" if self.tripped else ("Off" if self.is_open else "On")

    def actions(self):
        return [("toggle", "Switch on" if self.is_open else "Switch off", not self.is_open)]

    def command(self, name):
        if name == "toggle":
            self.is_open = not self.is_open
            self.tripped = False
            self.heat = 0.0
            self.net.dirty = True
            return True
        return False

    def command_text(self, name):
        return "Switched off" if self.is_open else "Switched on"


class Overload(Protection):
    """A thermal overload never opens the power circuit: it changes its auxiliary contacts, those with the same tag."""
    I2T = OVERLOAD_I2T

    def current_lines(self):
        return [(a, b, G_CLOSED, 0.0) for a, b in self.poles]

    def commit(self, v, dt):
        if self.tripped:
            return
        i = max((mag(G_CLOSED * (v[self.t[a]] - v[self.t[b]])) for a, b in self.poles), default=0.0)
        r = i / self._rating()
        self.heat = max(0.0, self.heat + (r * r - 1.1) * dt) if r > 1.05 else self.heat * (1.0 - dt / 120.0)
        if self.heat >= self.I2T:
            self.tripped = True
            self.net.dirty = True
            self.net.sim.log(self.part.tag, f"Tripped on {i:.1f} A")

    def status(self, p=None):
        return "Tripped" if self.tripped else "OK"

    def is_on(self):
        return not self.tripped

    def actions(self):
        return [("reset", "Reset the overload", False)] if self.tripped else []

    def command(self, name):
        if name == "reset" and self.tripped:
            self.tripped = False
            self.heat = 0.0
            self.net.dirty = True
            return True
        return False

    def command_text(self, name):
        return "Reset"

    def readings(self, p=None):
        amps = max((mag(G_CLOSED * self.across(a, b)) for a, b in self.poles), default=0.0)
        return [("Current", "current", amps), ("Load", "percent", 100.0 * amps / self._rating())]


# ---------------------------------------------------------------- what reads the fluid side
class Reader:
    """A sensor's view of the fluid part its link names. `on` keeps a switch's state between looks."""

    def __init__(self, net, link):
        self.sim = net.sim
        self.b = net.sim.fluid[link.source]
        self.sense = link.sense
        self.is_pressure = hasattr(self.b, "value")
        self.on = False
        self.last_x = None

    def reset(self):
        self.on = False
        self.last_x = None

    def _x(self):
        """Where the actuator is, in its own SI unit, and its whole travel."""
        b = self.b
        if self.sense.quantity == "rpm":
            return abs(b.v), 0.0
        return b.x, b.travel()

    def tripped(self, band) -> bool:
        s = self.sense
        if self.is_pressure:
            p = self.b.value(self.sim.p)
            target = s.si if s.si is not None else (s.frac or 0.0) * self.sim.max_pressure()
            hyst = max(0.02 * abs(target), 0.1e5)
            if s.mode == "below":
                self.on = p < (target + hyst if self.on else target)
            elif s.mode == "at":
                self.on = abs(p - target) <= hyst
            else:
                self.on = p > (target - hyst if self.on else target)
            return self.on
        x, travel = self._x()
        target = s.si if s.si is not None else (s.frac or 0.0) * travel
        previous = x if self.last_x is None else self.last_x
        self.last_x = x
        if s.mode == "above":
            self.on = x > (target - 0.002 * travel if self.on else target)
        elif s.mode == "below":
            self.on = x < (target + 0.002 * travel if self.on else target)
        else:
            # it may have passed the whole band within one step
            width = max(band * travel, 1e-6)
            self.on = min(previous, x) <= target + width and max(previous, x) >= target - width
        return self.on

    def fraction(self, lo, hi) -> float:
        """How far along the sensor's range the value is. lo and hi are in bar, mm, degrees or rpm; 0, 0 is the whole
        stroke, or everything up to the highest pressure in the circuit."""
        b = self.b
        if self.is_pressure:
            value = b.value(self.sim.p) / 1e5
            if lo == hi:
                lo, hi = 0.0, self.sim.max_pressure() / 1e5
        elif b.part.kind == "motor" or self.sense.quantity == "rpm":
            value = abs(b.v) * 60.0 / (2.0 * math.pi)
            if lo == hi:
                lo, hi = 0.0, 3000.0
        elif b.rotary:
            value = math.degrees(b.x)
            if lo == hi:
                lo, hi = 0.0, math.degrees(b.travel())
        else:
            value = b.x * 1e3
            if lo == hi:
                lo, hi = 0.0, b.travel() * 1e3
        return clamp((value - lo) / (hi - lo), 0.0, 1.0) if hi != lo else 0.0


# ---------------------------------------------------------------- what switches
class Contact(Part):
    """One or more poles that follow something: a coil, a fluid part, a position, or a click."""
    interactive = True
    quiet = True

    def __init__(self, net, part):
        super().__init__(net, part)
        opts = part.spec.options
        self.poles = opts.get("poles") or opts.get("pairs") or []
        self.nc = bool(opts.get("nc"))
        self.manual = False
        self.follows = None     # returns True when actuated
        self.reader = None
        self.last = False

    def actuated(self) -> bool:
        return self.follows() if self.follows is not None else self.manual

    def reset(self):
        self.manual = False
        self.last = False
        if self.reader is not None:
            self.reader.reset()

    def sense(self, dt):
        """Called each step for those that follow the fluid side: the rest are told."""
        if self.reader is not None:
            self.manual = self.reader.tripped(self.par.get("band", 1.0) / 100.0)
        now = self.actuated()
        if now != self.last:
            self.last = now
            self.net.dirty = True

    def closed(self) -> bool:
        return self.actuated() != self.nc

    def current_lines(self):
        return [(a, b, G_CLOSED, 0.0) for a, b in self.poles] if self.closed() else []

    def status(self, p=None):
        return "Closed" if self.closed() else "Open"

    def is_on(self):
        return self.closed()

    def actions(self):
        if self.follows is not None or self.reader is not None:
            return []
        return [("toggle", "Operate", self.manual)]

    def command(self, name):
        if name == "toggle" and self.follows is None and self.reader is None:
            self.manual = not self.manual
            self.net.dirty = True
            return True
        return False

    def command_text(self, name):
        return "Closed" if self.closed() else "Opened"

    def readings(self, p=None):
        return [("Current", "current", self.through() if self.closed() else 0.0)]

    def trace_channels(self):
        return [self._state_channel("closed")]


class Button(Contact):
    """Held while the mouse is down on it; the Operate button latches it, for keeping it held while looking elsewhere."""
    momentary = True

    def actions(self):
        return [("toggle", "Release" if self.manual else "Hold", self.manual)]

    def command(self, name):
        if name == "press" or name == "release":
            want = name == "press"
            if self.manual != want:
                self.manual = want
                self.net.dirty = True
            return True
        return super().command(name)

    def status(self, p=None):
        return "Pressed" if self.manual else "Released"

    def is_on(self):
        return self.manual

    def command_text(self, name):
        return "Pressed" if self.manual else "Released"


class Selector(Contact):
    def status(self, p=None):
        if self.part.spec.options.get("estop"):
            return "Pressed: stop" if self.manual else "Released"
        return "Closed" if self.closed() else "Open"

    def actions(self):
        if self.part.spec.options.get("estop"):
            return [("toggle", "Release" if self.manual else "Press", self.manual)]
        return [("toggle", "Turn", self.manual)]

    def command_text(self, name):
        if self.part.spec.options.get("estop"):
            return "Pressed" if self.manual else "Released"
        return "Closed" if self.closed() else "Opened"


class Changeover(Contact):
    """Common C to A, or when operated to B."""

    def current_lines(self):
        return [("C", "B" if self.actuated() else "A", G_CLOSED, 0.0)]

    def closed(self):
        return self.actuated()

    def status(self, p=None):
        return "C to B" if self.actuated() else "C to A"

    def readings(self, p=None):
        return [("Current", "current", self.through())]

    def command_text(self, name):
        return self.status()


class Rotary(Part):
    """Common C to one of positions 1 to 4. It starts where the symbol shows it: on 2."""
    interactive = True
    quiet = True
    START = 1

    def __init__(self, net, part):
        super().__init__(net, part)
        self.position = self.START

    def reset(self):
        self.position = self.START

    def current_lines(self):
        return [("C", str(self.position + 1), G_CLOSED, 0.0)]

    def status(self, p=None):
        return f"Position {self.position + 1}"

    def actions(self):
        return [(f"pos{i}", f"Position {i + 1}", self.position == i) for i in range(4)]

    def command(self, name):
        if name.startswith("pos") and name[3:].isdigit() and 0 <= int(name[3:]) <= 3:
            self.position = int(name[3:])
            self.net.dirty = True
            return True
        if name == "toggle":
            self.position = (self.position + 1) % 4
            self.net.dirty = True
            return True
        return False

    def command_text(self, name):
        return self.status()


class Prox(Part):
    """Three wires. On, its output is tied to + (PNP) or to - (NPN). It needs its own supply, like a real one."""
    interactive = True
    R_OUT = 1.0

    def __init__(self, net, part):
        super().__init__(net, part)
        self.pnp = bool(part.spec.options.get("pnp"))
        self.reader = None
        self.manual = False
        self.detected = False
        self.powered = False
        self.last = False

    def reset(self):
        self.manual = False
        self.detected = False
        self.powered = False
        self.last = False
        if self.reader is not None:
            self.reader.reset()

    def sense(self, dt):
        if self.reader is not None:
            self.manual = self.reader.tripped(self.par.get("band", 1.0) / 100.0)
        if self.manual != self.last:
            self.last = self.manual
            self.detected = self.manual
            self.net.dirty = True

    def current_lines(self):
        if not self.powered:
            return []
        out = [("+", "-", 1.0 / 2400.0, 0.0)]
        if self.detected:
            out.append(("+", "OUT", 1.0 / self.R_OUT, 0.0) if self.pnp else ("OUT", "-", 1.0 / self.R_OUT, 0.0))
        return out

    def update(self, v):
        supply = (v[self.t["+"]] - v[self.t["-"]]).real
        want = supply > (6.0 if self.powered else 10.0)
        if want != self.powered:
            self.powered = want
            return True
        return False

    def status(self, p=None):
        if not self.powered:
            return "No supply"
        return "Detecting" if self.detected else "Clear"

    def is_on(self):
        return self.powered and self.detected

    def actions(self):
        return [] if self.reader is not None else [("toggle", "Target present", self.manual)]

    def command(self, name):
        if name == "toggle" and self.reader is None:
            self.manual = not self.manual
            self.detected = self.manual
            self.last = self.manual
            self.net.dirty = True
            return True
        return False

    def command_text(self, name):
        return "Target present" if self.manual else "Target gone"

    def readings(self, p=None):
        return [("Output", "voltage", (self.net.v[self.t["OUT"]] - self.net.v[self.t["-"]]).real)]

    def trace_channels(self):
        return [self._state_channel()]


SIGNALS = {"0-10V": ("V", 0.0, 10.0), "0-5V": ("V", 0.0, 5.0), "4-20mA": ("A", 0.004, 0.020), "0-20mA": ("A", 0.0, 0.020)}


def _signal_name(par):
    from .catalog import SENSOR_SIGNALS
    return SENSOR_SIGNALS[int(clamp(par.get("signal", 0.0), 0, len(SENSOR_SIGNALS) - 1))]


class AnalogSensor(Part):
    """Three wires, and a voltage or current out in proportion to what it reads."""
    quiet = True
    R_OUT = 10.0
    HEADROOM = 2.0

    def __init__(self, net, part):
        super().__init__(net, part)
        self.reader = None
        self.frac = 0.0
        self.powered = False
        self.clamped = False

    def reset(self):
        self.frac = 0.0
        self.powered = False
        self.clamped = False

    def _read(self):
        if self.reader is not None:
            return self.reader.fraction(self.par["lo"], self.par["hi"])
        return clamp(self.par.get("manual", 0.0) / 100.0, 0.0, 1.0)

    def sense(self, dt):
        f = self._read()
        if abs(f - self.frac) > 2e-4:
            self.frac = f
            self.net.dirty = True

    def _output(self):
        unit, lo, hi = SIGNALS[_signal_name(self.par)]
        return unit, lo + self.frac * (hi - lo)

    def stamp(self, s):
        if not self.powered:
            return
        plus, minus, out = self.t["+"], self.t["-"], self.t["OUT"]
        s.line(plus, minus, 1e-3)
        unit, value = self._output()
        if unit == "V":
            s.line(out, minus, 1.0 / self.R_OUT, value)
        elif self.clamped:
            s.line(out, minus, 1.0, self.net.v[plus] - self.net.v[minus] - self.HEADROOM)
        else:
            s.source(minus, out, value)

    def update(self, v):
        supply = (v[self.t["+"]] - v[self.t["-"]]).real
        changed = False
        want = supply > (6.0 if self.powered else 10.0)
        if want != self.powered:
            self.powered = want
            changed = True
        unit, value = self._output()
        if self.powered and unit == "A":
            room = (v[self.t["OUT"]] - v[self.t["-"]]).real
            top = supply - self.HEADROOM
            clamped = room > top + 1e-3 if not self.clamped else (top - room) < value
            if clamped != self.clamped:
                self.clamped = clamped
                changed = True
        return changed

    def currents(self, v):
        if not self.powered:
            return {}
        plus, minus, out = self.t["+"], self.t["-"], self.t["OUT"]
        own = 1e-3 * (v[plus] - v[minus])
        unit, value = self._output()
        if unit == "V":
            i = (value - (v[out] - v[minus])) / self.R_OUT
        elif self.clamped:
            i = v[plus] - v[minus] - self.HEADROOM - (v[out] - v[minus])
        else:
            i = value
        return {"+": own, "-": -own + i, "OUT": -i}

    def status(self, p=None):
        return "On" if self.powered else "No supply"

    def is_on(self):
        return self.powered

    def readings(self, p=None):
        unit, value = self._output()
        out = [("Reads", "percent", 100.0 * self.frac)]
        if self.powered:
            out.append(("Output", "voltage" if unit == "V" else "current", value))
        return out

    def trace_channels(self):
        return [((self.part.key, "out"), f"{self.part.tag} reading", "percent", lambda: 100.0 * self.frac)]


class LoopSensor(Part):
    """Two wires, 4 to 20 mA. It takes its current from the loop, so it needs about 9 V across it to work."""
    quiet = True
    V_MIN = 9.0
    V_MAX = 40.0

    def __init__(self, net, part):
        super().__init__(net, part)
        self.reader = None
        self.frac = 0.0
        self.region = 0     # -1 starved, 0 working, 1 open: nothing else in the loop

    def reset(self):
        self.frac = 0.0
        self.region = -1

    def sense(self, dt):
        f = self.reader.fraction(self.par["lo"], self.par["hi"]) if self.reader is not None else \
            clamp(self.par.get("manual", 0.0) / 100.0, 0.0, 1.0)
        if abs(f - self.frac) > 2e-4:
            self.frac = f
            self.net.dirty = True

    def amps(self):
        return 0.004 + 0.016 * self.frac

    def stamp(self, s):
        a, b = self.t["+"], self.t["-"]
        if self.region == 0:
            s.source(a, b, self.amps())
        else:
            s.line(a, b, self.amps() / (self.V_MIN if self.region < 0 else self.V_MAX))

    def currents(self, v):
        d = v[self.t["+"]] - v[self.t["-"]]
        if self.region == 0:
            i = self.amps()
        else:
            i = d * self.amps() / (self.V_MIN if self.region < 0 else self.V_MAX)
        return {"+": i, "-": -i}

    def update(self, v):
        d = (v[self.t["+"]] - v[self.t["-"]]).real
        region = -1 if d < self.V_MIN else 1 if d > self.V_MAX else 0
        if region != self.region:
            self.region = region
            return True
        return False

    def status(self, p=None):
        return "On" if self.region == 0 else ("No supply" if self.region < 0 else "Loop open")

    def is_on(self):
        return self.region == 0

    def readings(self, p=None):
        return [("Reads", "percent", 100.0 * self.frac), ("Loop current", "current", self.through())]

    def trace_channels(self):
        return [((self.part.key, "out"), f"{self.part.tag} reading", "percent", lambda: 100.0 * self.frac)]


# ---------------------------------------------------------------- what consumes
class Load(Part):
    """A resistance set by its rated voltage and power."""
    quiet = False
    ON_WORD = "On"
    OFF_WORD = "Off"
    ON_AT = 0.5

    def rated(self):
        return self.par.get("rated") or self.net.nominal(self.t[self.names[0]])

    def g(self):
        r = max(self.rated(), 1e-3)
        return self.par["power"] / (r * r)

    def current_lines(self):
        return [(self.names[0], self.names[1], self.g(), 0.0)]

    def is_on(self):
        return mag(self.across()) >= self.ON_AT * self.rated()

    def status(self, p=None):
        return self.ON_WORD if self.is_on() else self.OFF_WORD

    def readings(self, p=None):
        volts = mag(self.across())
        return [("Voltage", "voltage", volts), ("Current", "current", volts * self.g()), ("Power", "power", volts * volts * self.g())]

    def trace_channels(self):
        return [self._state_channel()]


class Lamp(Load):
    ON_WORD = "Lit"


class Sounder(Load):
    ON_WORD = "Sounding"


class ElectricMotor(Load):
    """Runs from 70% of its voltage. Its current is what its power says at that voltage, whatever the fluid side asks."""
    ON_WORD = "Running"
    ON_AT = 0.7

    def __init__(self, net, part):
        super().__init__(net, part)
        self.running = False

    def reset(self):
        self.running = False

    def commit(self, v, dt):
        volts = mag(v[self.t[self.names[0]]] - v[self.t[self.names[1]]])
        r = self.rated()
        self.running = volts >= (0.5 * r if self.running else 0.7 * r)

    def is_on(self):
        return self.running

    def reversed_now(self):
        return (self.across()).real < 0

    def status(self, p=None):
        return ("Running, reversed" if self.reversed_now() else "Running") if self.running else "Off"


class Motor3(Part):
    """Three windings in star. Lose a phase while running and it hums on, drawing more, until something protects it;
    lose one while stopped and it won't start. Swap two phases and it runs the other way."""
    quiet = False

    def __init__(self, net, part):
        super().__init__(net, part)
        self.star = net.new_node()
        self.running = False
        self.lost_phase = False
        self.rev = False

    def reset(self):
        self.running = False
        self.lost_phase = False
        self.rev = False

    def _rated(self):
        given = self.par.get("rated")
        if given:
            return given
        n = self.net.nominal(self.t[self.names[0]])
        return n * math.sqrt(3.0) if self.net.has_phasors else n

    def _g(self):
        r = max(self._rated(), 1e-3)
        g = self.par["power"] / (r * r)
        return 2.0 * g if self.lost_phase else g

    def stamp(self, s):
        g = self._g()
        for n in self.names:
            s.line(self.t[n], self.star, g)

    def currents(self, v):
        g = self._g()
        return {n: g * (v[self.t[n]] - v[self.star]) for n in self.names}

    def _phases(self, v):
        return [v[self.t[n]] - v[self.star] for n in self.names]

    def update(self, v):
        ph = [mag(x) for x in self._phases(v)]
        top = max(ph)
        lost = top > 1.0 and sum(1 for x in ph if x < 0.2 * top) == 1
        if lost != self.lost_phase:
            self.lost_phase = lost
            return True
        return False

    def commit(self, v, dt):
        ph = self._phases(v)
        sizes = [mag(x) for x in ph]
        lo = 0.7 * self._rated() / math.sqrt(3.0)
        if self.lost_phase:
            if self.running and max(sizes) < 0.3 * self._rated():
                self.running = False
        elif self.running:
            self.running = min(sizes) >= 0.7 * lo
        else:
            self.running = min(sizes) >= lo
        if self.running and not self.lost_phase and sizes[0] > 1.0 and sizes[1] > 1.0:
            self.rev = cmath.phase(complex(ph[0]) / complex(ph[1])) < 0 if isinstance(ph[0], complex) else False

    def status(self, p=None):
        if self.lost_phase:
            return "Running on two phases: overheating" if self.running else "Won't start: a phase is missing"
        if self.running:
            return "Running, reversed" if self.rev else "Running"
        return "Off"

    def is_on(self):
        return self.running

    def reversed_now(self):
        return self.rev

    def readings(self, p=None):
        v = self.net.v
        amps = max(mag(i) for i in self.currents(v).values())
        line = mag(v[self.t[self.names[0]]] - v[self.t[self.names[1]]])
        return [("Line voltage", "voltage", line), ("Line current", "current", amps), ("Power", "power", self.par["power"] if self.running else 0.0)]

    def trace_channels(self):
        return [self._state_channel("running"),
                ((self.part.key, "i"), f"{self.part.tag} current", "current", lambda: max(mag(i) for i in self.currents(self.net.v).values()))]


class MeterV(Part):
    quiet = True

    def current_lines(self):
        return [(self.names[0], self.names[1], 1.0 / self.par["ohms"], 0.0)]

    def value(self):
        return signed(self.across())

    def readings(self, p=None):
        return [("Voltage", "voltage", self.value())]

    def trace_channels(self):
        return [((self.part.key, "v"), f"{self.part.tag} voltage", "voltage", self.value)]


class MeterA(Part):
    quiet = True

    def current_lines(self):
        return [(self.names[0], self.names[1], 1.0 / self.par["ohms"], 0.0)]

    def value(self):
        return signed(self.across() / self.par["ohms"])

    def readings(self, p=None):
        return [("Current", "current", self.value())]

    def trace_channels(self):
        return [((self.part.key, "i"), f"{self.part.tag} current", "current", self.value)]


class Coil(Load):
    """A relay or solenoid coil: pulls in at 75% of rated voltage, lets go at 40%.

    Contacts with its tag follow `actuated`, which timers delay. A coil on a proportional valve has no pull-in: its
    voltage is the valve's command, and it's an amplifier's input rather than a winding."""
    quiet = False
    PROPORTIONAL_DEFAULT = 10.0

    def __init__(self, net, part):
        super().__init__(net, part)
        self.proportional = False
        self.reset()

    def reset(self):
        self.energised = False
        self.is_actuated = False
        self.timer = 0.0
        self.flip_times = []
        self.chatter_said = False
        self.over_said = False

    def rated(self):
        given = self.par.get("rated")
        if given:
            return given
        if self.proportional:
            return self.PROPORTIONAL_DEFAULT
        return self.net.nominal(self.t[self.names[0]])

    def g(self):
        if self.proportional:
            return 1e-4
        return super().g()

    def _ends(self):
        return ("A1", "A2") if "A1" in self.t else (self.names[0], self.names[1])

    def current_lines(self):
        a, b = self._ends()
        return [(a, b, self.g(), 0.0)]

    def volts(self, v) -> float:
        a, b = self._ends()
        return mag(v[self.t[a]] - v[self.t[b]])

    def wants_flip(self, v) -> bool:
        x = self.volts(v)
        r = self.rated()
        if self.proportional:
            return (x > 0.02 * r) != self.energised
        return x <= DROP_OUT * r if self.energised else x >= PICK_UP * r

    def flip(self):
        self.energised = not self.energised
        self._contacts_now()
        sim = self.net.sim
        self.flip_times.append(sim.time)
        while self.flip_times and self.flip_times[0] < sim.time - 1.0:
            self.flip_times.pop(0)
        if len(self.flip_times) > CHATTER_PER_SECOND and not self.chatter_said:
            self.chatter_said = True
            sim.log(self.part.tag, "Chattering: it keeps dropping out. Its own contact may be interrupting it.")

    def _contacts_now(self):
        self.is_actuated = self.energised
        self.timer = 0.0

    def fraction(self) -> float:
        return clamp(self.volts(self.net.v) / max(self.rated(), 1e-6), 0.0, 1.0)

    def commit(self, v, dt):
        if self.chatter_said and self.flip_times and self.flip_times[-1] < self.net.sim.time - 1.0:
            self.chatter_said = False
        if not self.over_said and self.volts(v) > OVER_VOLTAGE * self.rated():
            self.over_said = True
            self.net.sim.log(self.part.tag, f"Over-voltage: {self.volts(v):.0f} V on a {self.rated():.0f} V coil")

    def is_on(self):
        return self.energised

    def status(self, p=None):
        if self.chatter_said:
            return "Chattering"
        return "Energised" if self.energised else "Off"

    def readings(self, p=None):
        volts = self.volts(self.net.v)
        return [("Voltage", "voltage", volts), ("Current", "current", volts * self.g()),
                ("Pull-in at", "voltage", (0.02 if self.proportional else PICK_UP) * self.rated())]

    def trace_channels(self):
        return [self._state_channel()]


class OnDelayCoil(Coil):
    """Contacts change `delay` after the coil is energised, and go back at once when it drops out."""

    def _contacts_now(self):
        if not self.energised:
            self.is_actuated = False
        self.timer = 0.0

    def commit(self, v, dt):
        super().commit(v, dt)
        if self.energised and not self.is_actuated:
            self.timer += dt
            if self.timer >= self.par["delay"] - 1e-9:
                self.is_actuated = True
                self.net.dirty = True

    def status(self, p=None):
        if self.energised and not self.is_actuated:
            return "Timing"
        return "Timed out" if self.is_actuated else "Off"

    def readings(self, p=None):
        return super().readings(p) + [("Elapsed", "time", self.timer)]


class OffDelayCoil(Coil):
    """Contacts change at once when the coil is energised, and go back `delay` after it drops out."""

    def _contacts_now(self):
        if self.energised:
            self.is_actuated = True
        self.timer = 0.0

    def commit(self, v, dt):
        super().commit(v, dt)
        if not self.energised and self.is_actuated:
            self.timer += dt
            if self.timer >= self.par["delay"] - 1e-9:
                self.is_actuated = False
                self.net.dirty = True

    def status(self, p=None):
        if self.is_actuated and not self.energised:
            return "Timing"
        return "Energised" if self.energised else "Off"

    def readings(self, p=None):
        return super().readings(p) + [("Elapsed", "time", self.timer)]


class Relay(Coil):
    """A coil with its contacts drawn in one symbol."""

    def __init__(self, net, part):
        super().__init__(net, part)
        self.poles = [(a, b) for a, b in (("13", "14"), ("23", "24")) if a in part.terms]

    def current_lines(self):
        out = super().current_lines()
        if self.is_actuated:
            out = out + [(a, b, G_CLOSED, 0.0) for a, b in self.poles]
        return out


# ---------------------------------------------------------------- the PLC
INPUT_ON = 0.625        # of its rated supply: 15 V on 24 V
INPUT_OFF = 0.21        # 5 V on 24 V
R_DI = 3300.0
R_AI_VOLTS = 100e3
R_AI_MA = 250.0
R_AO_VOLTS = 1.0


class Plc(Part):
    """An ordinary electrical part whose outputs come from a program. Its program runs on the supply at L+ and M: it
    starts cold when that comes up, and stops with its outputs off when it goes. A fault does the same, and says why."""
    interactive = True

    def __init__(self, net, part):
        super().__init__(net, part)
        self.rt = plc_core.compile_params(part.comp.params or {})
        self.addr = self.rt.program.addr
        self.do_type = plc_core.do_type(part.comp.params or {})
        self.ai_ma = {a: self.rt._ai[a][0].endswith("mA") for a in self.addr["ai"]}
        self.ao_ma = {a: self.rt._ao[a][0].endswith("mA") for a in self.addr["ao"]}
        self.has_supply = not ("L+" in part.open_terms and "M" in part.open_terms)
        self.switch_run = True
        self.reset()

    def reset(self):
        self.powered = False
        self.acc = 0.0
        self.inputs = {a: False for a in self.addr["di"]}
        self.outs = {a: False for a in self.addr["do"]}
        self.ao_value = {a: 0.0 for a in self.addr["ao"]}
        self.fault_said = ""
        self.rt.reset()
        self.rt.ctx.messages.clear()
        self.rt.running = False

    def _rated(self):
        return max(self.par["supply"], 1.0)

    def _supply(self, v):
        """L+ above M. The wrong way round is no supply at all, as it is for a real PLC."""
        d = v[self.t["L+"]] - v[self.t["M"]]
        return abs(d) if isinstance(d, complex) else d

    def running(self) -> bool:
        return self.powered and self.switch_run and self.rt.running

    def current_lines(self):
        m = "M"
        out = [(a, m, 1.0 / R_DI, 0.0) for a in self.addr["di"]]
        out += [(a, m, 1.0 / (R_AI_MA if self.ai_ma[a] else R_AI_VOLTS), 0.0) for a in self.addr["ai"]]
        if self.powered:
            out.append(("L+", m, self.par["power"] / self._rated() ** 2, 0.0))
            for a, on in self.outs.items():
                if on:
                    if self.do_type == "source":
                        out.append(("L+", a, 1.0 / R_OUTPUT, 0.0))
                    elif self.do_type == "sink":
                        out.append((a, m, 1.0 / R_OUTPUT, 0.0))
                    else:
                        out.append(("C", a, G_CLOSED, 0.0))
            for a in self.addr["ao"]:
                if not self.ao_ma[a]:
                    out.append((a, m, 1.0 / R_AO_VOLTS, self.ao_value[a]))
        return out

    def stamp(self, s):
        super().stamp(s)
        if self.powered:
            for a in self.addr["ao"]:
                if self.ao_ma[a]:
                    # a current out, as far as the supply can push it
                    s.line(self.t[a], self.t["M"], 1e-5)
                    s.source(self.t["M"], self.t[a], self.ao_value[a] / 1000.0)

    def currents(self, v):
        out = super().currents(v)
        if self.powered:
            for a in self.addr["ao"]:
                if self.ao_ma[a]:
                    i = self.ao_value[a] / 1000.0
                    out[a] = out.get(a, 0.0) - i
                    out["M"] = out.get("M", 0.0) + i
        return out

    def _read_inputs(self, v):
        rated = self._rated()
        on, off = INPUT_ON * rated, INPUT_OFF * rated
        for a in self.addr["di"]:
            x = (v[self.t[a]] - v[self.t["M"]]).real
            if x >= on:
                self.inputs[a] = True
            elif x <= off:
                self.inputs[a] = False
            self.rt.set_input(a, self.inputs[a])
        for a in self.addr["ai"]:
            x = (v[self.t[a]] - v[self.t["M"]]).real
            self.rt.set_analog_raw(a, x / R_AI_MA * 1000.0 if self.ai_ma[a] else x)

    def _write_outputs(self):
        rt = self.rt
        run = self.running()
        G = rt.ctx.G
        for a in self.addr["do"]:
            want = run and bool(G.get(a))
            if want != self.outs[a]:
                self.outs[a] = want
                self.net.dirty = True
        for a in self.addr["ao"]:
            want = rt.analog_output_raw(a) if run else 0.0
            if abs(want - self.ao_value[a]) > 1e-4:
                self.ao_value[a] = want
                self.net.dirty = True

    def tick(self, dt):
        """What it does between solutions: its power, then its scans."""
        v = self.net.v
        sim = self.net.sim
        supply = self._supply(v)
        rt = self.rt
        if self.powered:
            if supply < 0.6 * self._rated():
                self.powered = False
                rt.running = False
                self.net.dirty = True
                self._write_outputs()
                sim.log(self.part.tag, "Lost its supply: stopped, outputs off")
        elif supply >= PICK_UP * self._rated():
            self.powered = True
            self.acc = 0.0
            rt.reset()
            self.fault_said = ""
            self.net.dirty = True
        if not self.running():
            self._after_scans()
            return
        self._read_inputs(v)
        scan_ms = max(rt.program.scan_ms, 1)
        self.acc += dt * 1000.0
        count = 0
        while self.acc >= scan_ms - 1e-6 and count < MAX_SCANS_PER_STEP:
            self.acc -= scan_ms
            count += 1
            if not rt.scan(scan_ms):
                break
        if self.acc > scan_ms:
            self.acc = 0.0
        self._after_scans()

    def _after_scans(self):
        rt = self.rt
        sim = self.net.sim
        for text in rt.ctx.messages:
            sim.log(self.part.tag, text)
        rt.ctx.messages.clear()
        if rt.fault and rt.fault != self.fault_said:
            self.fault_said = rt.fault
            sim.log(self.part.tag, f"Fault: {rt.fault}")
        self._write_outputs()

    def status(self, p=None):
        if not self.rt.ok:
            return "Program has errors: it can't run"
        if not self.powered:
            if not self.has_supply:
                return "No supply: nothing is wired to L+ and M"
            return "Supply the wrong way round" if self._supply(self.net.v) < -1.0 else "No supply"
        if self.rt.fault:
            return "Fault: " + self.rt.fault[:60]
        return "Run" if self.switch_run else "Stop"

    def is_on(self):
        return self.running()

    def actions(self):
        if not self.rt.ok:
            return []
        return [("toggle", "Stop" if self.switch_run else "Run", self.switch_run), ("restart", "Restart", False)]

    def command(self, name):
        if name == "toggle":
            self.switch_run = not self.switch_run
            self.net.dirty = True
            self._write_outputs()
            return True
        if name == "restart":
            if self.rt.ok:
                self.rt.reset()
                self.fault_said = ""
                self.acc = 0.0
                self.switch_run = True
                self.net.dirty = True
            return True
        return False

    def command_text(self, name):
        return "Restarted" if name == "restart" else ("Set to run" if self.switch_run else "Set to stop")

    def readings(self, p=None):
        return [("Supply", "voltage", self._supply(self.net.v)), ("Scans", "number", float(self.rt.scans))]

    def watch(self) -> list:
        """(address or name, tag, value) of its I/O and variables, for the inspector."""
        return self.rt.watch()

    def pin_state(self, name):
        """What a pin is doing, for the LEDs on the block: True, False, or None for pins with nothing to show."""
        if name in self.inputs:
            return self.inputs[name]
        if name in self.outs:
            return self.outs[name]
        return None

    def trace_channels(self):
        out = []
        tag = self.part.tag
        tags = self.rt.program.tags
        for a in self.addr["di"] + self.addr["do"]:
            if a not in self.part.open_terms:
                state = self.inputs if a in self.addr["di"] else None
                reader = (lambda s=state, x=a: 1.0 if s[x] else 0.0) if state is not None else (lambda x=a: 1.0 if self.outs[x] else 0.0)
                out.append(((self.part.key, a), f"{tag} {a} {tags.get(a, '')}".strip(), "state", reader))
        for a in self.addr["ai"] + self.addr["ao"]:
            if a not in self.part.open_terms:
                out.append(((self.part.key, a), f"{tag} {a} {tags.get(a, '')}".strip(), "voltage",
                            lambda x=a: (self.net.v[self.t[x]] - self.net.v[self.t["M"]]).real))
        return out


BEHAVIOURS = {
    "plc": Plc, "source_v": Source, "source_i": CurrentSource, "psu": PowerSupply, "rectifier": Rectifier,
    "regulator": Regulator, "ground": Connection, "rail": Connection, "point": Connection, "feedthrough": Connection,
    "resistor": Resistor, "pot": Potentiometer, "capacitor": Capacitor, "inductor": Inductor, "zener": Zener, "led": Led,
    "diode": Diode, "bjt": Bjt, "fet": Fet, "scr": Thyristor, "opamp": OpAmp, "logic": Logic, "fuse": Fuse,
    "breaker": Breaker, "breaker3": Breaker, "overload": Overload, "contact": Contact, "button": Button,
    "selector": Selector, "changeover": Changeover, "selector4": Rotary, "limit": Contact, "pressure_contact": Contact,
    "switch_manual": Contact, "prox": Prox, "sensor_analog": AnalogSensor, "sensor_loop": LoopSensor, "coil": Coil,
    "coil_on": OnDelayCoil, "coil_off": OffDelayCoil, "relay": Relay, "lamp": Lamp, "buzzer": Sounder,
    "emotor": ElectricMotor, "emotor3": Motor3, "meter_v": MeterV, "meter_a": MeterA, "transformer": Transformer,
    "autotransformer": Autotransformer,
}


# ---------------------------------------------------------------- the network
class Network:
    def __init__(self, sim, circuit):
        self.sim = sim
        self.circuit = circuit
        self.node_count = circuit.el_node_count
        self.gnd = circuit.el_gnd
        self.dt = getattr(sim, "dt", 0.01)
        self.has_phasors = any(isinstance(r[1], complex) for r in circuit.el_rails)
        self.by_key = {}
        for p in circuit.electrical_parts:
            self.by_key[p.key] = BEHAVIOURS.get(p.kind, Unsimulated)(self, p)
        self.free = [n for n in range(self.node_count) if n not in circuit.el_fixed]
        self.idx = [None] * self.node_count
        for i, n in enumerate(self.free):
            self.idx[n] = i
        self.n_free = len(self.free)
        self.v = [0.0] * self.node_count
        self.dirty = True
        self.changed = False
        self._nominal = None
        self._solves = 0
        self.parts = list(self.by_key.values())
        self.nonlinear = [b for b in self.parts if type(b).update is not Part.update]
        self.committing = [b for b in self.parts if type(b).commit is not Part.commit]
        self.logic = [b for b in self.parts if isinstance(b, Logic)]
        self.coils = [b for b in self.parts if isinstance(b, Coil)]
        self.plcs = [b for b in self.parts if isinstance(b, Plc)]
        self.sensing = []
        self.outputs = []       # (coil or motor, fluid part, side or None)
        self._pushed = {}
        self._link_up(circuit.links)
        # odd, so that logic oscillating every round is seen to oscillate rather than looking still at every step's end
        self._rounds = 2 * len(self.coils) + 2 * len(self.logic) + 9
        self._oscillation_said = False

    # ---- construction
    def new_node(self) -> int:
        n = self.node_count
        self.node_count += 1
        return n

    def _link_up(self, links):
        fluid = self.sim.fluid
        for link in links:
            src = self.by_key.get(link.source)
            dst = self.by_key.get(link.target)
            if link.kind == "solenoid":
                valve = fluid.get(link.target)
                if src is None or valve is None or not hasattr(valve, "set_energised"):
                    continue
                if valve.part.kind == "prop":
                    src.proportional = True
                if hasattr(valve, "wired"):
                    valve.wired.add(link.side)
                self.outputs.append((src, valve, link.side))
            elif link.kind == "contact" and dst is not None:
                dst.follows = (lambda c=src: c.is_actuated)
            elif link.kind == "overload" and dst is not None:
                dst.follows = (lambda c=src: c.tripped)
                self.sensing.append(dst)
            elif link.kind == "pressure" and dst is not None:
                dst.follows = (lambda c=fluid[link.source]: c.on)
                self.sensing.append(dst)
            elif link.kind == "sense" and dst is not None:
                dst.reader = Reader(self, link)
                self.sensing.append(dst)
            elif link.kind == "motor":
                pump = fluid.get(link.target)
                if src is not None and pump is not None:
                    pump.driven_by = src.part.tag
                    pump.running = False
                    self.outputs.append((src, pump, None))
        for b in self.parts:
            if isinstance(b, (AnalogSensor, LoopSensor)) and b not in self.sensing:
                self.sensing.append(b)

    # ---- voltages the parts ask about
    def _source_nominals(self) -> dict:
        """The highest source in each circuit: what a part rated at "the circuit's voltage" runs on."""
        c = self.circuit.el_circuit_of
        out: dict = {}

        def note(node, volts):
            if node in c and volts:
                out[c[node]] = max(out.get(c[node], 0.0), abs(volts))
        for node, value, _label, key in self.circuit.el_rails:
            note(node, self._rail_value(value, key))
        for _round in range(3):         # a supply fed from another supply's circuit
            for b in self.parts:
                kind = b.part.kind
                if kind in ("source_v", "psu"):
                    note(b.t[b.plus], b.emf())
                elif kind == "transformer":
                    for a, _b, k in b._windings():
                        note(b.t[a], b.par["secondary"] * abs(k) / max(b.par["secondary"] / max(b.par["primary"], 1e-6), 1e-9))
                elif kind == "rectifier":
                    primary = out.get(c.get(b.t["AC1"]), 0.0)
                    note(b.t["+"], b.par["factor"] * primary)
        return out

    def nominal(self, node) -> float:
        if self._nominal is None:
            self._nominal = self._source_nominals()
        volts = self._nominal.get(self.circuit.el_circuit_of.get(node))
        return volts or self.circuit.el_vnom

    def logic_voltage(self, node) -> float:
        """Logic runs on the regulator in its circuit if it has one, and on the circuit's voltage if not."""
        c = self.circuit.el_circuit_of
        here = c.get(node)
        regs = [b.par["voltage"] for b in self.parts if b.part.kind == "regulator" and c.get(b.t["OUT"]) == here]
        return min(regs) if regs else self.nominal(node)

    def _rail_value(self, value, key):
        b = self.by_key.get(key) if key is not None else None
        if b is None:
            return value
        set_to = b.par.get("voltage")
        if set_to is None:
            return value
        if isinstance(value, complex):
            return value / abs(value) * set_to if abs(value) else value
        return set_to

    def touch(self):
        self.dirty = True
        self._nominal = None

    # ---- solving
    def _solve_once(self):
        s = System(self)
        for row in range(self.n_free):
            s.rows[row][row] = G_LEAK
        for node, value, _label, key in self.circuit.el_rails:
            s.line(node, self.gnd, G_RAIL, self._rail_value(value, key))
        for b in self.parts:
            b.stamp(s)
        x = solve(s.rows, s.rhs, [1.0] * len(s.rows))
        self._solves += 1
        v = [0.0] * self.node_count
        for node in self.free:
            v[node] = x[self.idx[node]]
        return v

    def _solve_piecewise(self) -> bool:
        """Until every part with more than one state agrees with the voltages it sees. False if they never did."""
        for _ in range(MAX_PIECEWISE):
            self.v = self._solve_once()
            changed = False
            for b in self.nonlinear:
                changed |= bool(b.update(self.v))
            if not changed:
                return True
        return False

    def _settle(self):
        """One step's worth of the discrete parts following the voltages, and the voltages following them."""
        if not self.free:
            return
        flipped = set()
        calm = True
        for _ in range(self._rounds):
            calm = self._solve_piecewise()
            logic_moved = False
            for b in self.logic:
                logic_moved |= b.evaluate(self.v)
            if logic_moved:
                calm = False
                continue
            coil = next((c for c in self.coils if id(c) not in flipped and c.wants_flip(self.v)), None)
            if coil is None:
                break
            coil.flip()
            flipped.add(id(coil))
            calm = False
        else:
            calm = False
            if self.logic and not self._oscillation_said:
                self._oscillation_said = True
                self.sim.log(self.logic[0].part.tag, "Logic oscillating: the gates keep changing each other")
        waiting = any(c.wants_flip(self.v) for c in self.coils)
        self.dirty = self.dirty or not calm or waiting

    def _push(self):
        """Tell the fluid side, only when something has changed: a click on the valve stays until the coil moves."""
        by_side: dict = {}
        for src, target, side in self.outputs:
            if side is None:
                state = (src.running, src.reversed_now())
                if self._pushed.get(id(target)) != state:
                    self._pushed[id(target)] = state
                    target.set_driven(src.running)
                    if target.part.spec.options.get("bidir") and target.reversed != state[1]:
                        target.reversed = state[1]
                        self.sim.touch()
            else:
                key = (id(target), side)
                was = by_side.get(key, (target, side, False, 0.0))
                on = was[2] or src.energised
                frac = max(was[3], src.fraction() if src.proportional else 1.0 if src.energised else 0.0)
                by_side[key] = (target, side, on, frac)
        for key, (target, side, on, frac) in by_side.items():
            state = (on, round(frac, 4))
            if self._pushed.get(key) != state:
                self._pushed[key] = state
                target.set_energised(side, on, frac)

    # ---- running
    def restart(self):
        self.v = [0.0] * self.node_count
        self._pushed = {}
        self._oscillation_said = False
        self._nominal = None
        self.dirty = False
        self._settle()
        self.dirty = True
        for b in self.committing:
            b.commit(self.v, self.sim.dt)
        self._push()
        self.dirty = True
        self.changed = True

    def step(self, dt):
        self.changed = False
        if not self.parts:
            return
        self.dt = dt
        for b in self.sensing:
            b.sense(dt)
        for b in self.plcs:
            b.tick(dt)
        if self.dirty:
            self.dirty = False
            self.changed = True
            self._settle()
        for b in self.committing:
            b.commit(self.v, dt)
        self._push()
        self.changed = self.changed or self.dirty

    # ---- reading it
    def node_voltage(self, node):
        return self.v[node]

    def terminal_currents(self) -> dict:
        """(sheet uid, comp id, terminal) -> current into the part."""
        out = {}
        for b in self.parts:
            for t, i in b.currents(self.v).items():
                out[(b.part.sheet, b.part.comp.id, t)] = mag(i) if isinstance(i, complex) else i
        return out
