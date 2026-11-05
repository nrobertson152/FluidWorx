"""The simulation: a lumped pressure/flow network solved step by step, alongside the electrical one (electric.py).

Each net is one node with a pressure and a small compliance. Valves are conductances that open and close,
actuators add a velocity unknown and a force balance, and each time step (backward Euler) is a linear system
solved here with no third-party code. Non-linear behaviour (seats opening, relief valves, end stops, friction)
is handled by re-solving until every part's state agrees with the pressures it sees.

The model is deliberately simple, and exists to show how a circuit behaves: what shifts, where pressure goes,
what moves, in what order and at about what speed. Flow is linear in pressure drop and air is treated as a
compressible liquid. It is not a sizing tool: use Caldera for that.
"""
from __future__ import annotations

import math

from .circuit import Circuit, Part
from .electric import BEHAVIOURS as ELECTRIC_BEHAVIOURS, Network
from .linsolve import System, solve
from .vendor.openschematix.symbols.fluid import LAYOUTS, PATTERNS, VALVE_TYPES, normal_position

ATM = 101325.0
DT = 0.01               # time step, s
TOL = 50.0              # Pa: pressure hysteresis of seats
FLOW_EPS = 1e-8         # m^3/s (0.0006 L/min): below this nothing is flowing
MOVE_EPS = 1e-5         # m/s: below this an actuator reads as stopped

# Constants of the model, per medium. G = conductance (m^3/s per Pa).
MEDIUM = {
    "hyd": {"g_pass": 5e-9,             # open valve path: about 0.33 bar at 10 L/min
            "g_seat": 2e-8,             # check valve once open
            "g_relief": 5e-9,           # relief override: about 0.33 bar per 10 L/min above the setting
            "c_line": 6.7e-13,          # 1 L of oil at 1.5 GPa
            "breakaway": 1.5e5,         # pressure to start an actuator moving, Pa
            "viscous": 40e5,            # viscous drag: Pa on the bore per m/s
            "viscous_rot": 6e3,         # the same for a motor, per rad/s: about 20 bar at 3000 rpm
            "ceiling": 700e5,           # a blocked fixed pump with no relief stalls here
            "vacuum": 0.9e5},
    "pneu": {"g_pass": 2e-9,            # roughly a 300 Nl/min valve around mid pressure
             "g_seat": 2e-9,
             "g_relief": 2e-9,
             "c_line": 2e-10,           # about 0.2 L of air at 7 bar
             "breakaway": 0.2e5,
             "viscous": 2e5,
             "viscous_rot": 1e3,
             "ceiling": 40e5,
             "vacuum": 0.9e5},
}


def throttle_g(g_pass: float, opening_pct: float) -> float:
    """Cubic so the useful range is spread across the control: 100% = an open valve."""
    return g_pass * (max(0.0, min(100.0, opening_pct)) / 100.0) ** 3


# ---------------------------------------------------------------- building blocks
class Seat:
    """Opens when pa - pb exceeds `crack`, closes when flow would reverse: check valves and relief valves."""
    __slots__ = ("a", "b", "ta", "tb", "g", "crack", "open")

    def __init__(self, a, b, ta, tb, g, crack=0.0):
        self.a, self.b, self.ta, self.tb, self.g, self.crack = a, b, ta, tb, g, crack
        self.open = False

    def stamp(self, s):
        if self.open:
            s.line(self.a, self.b, self.g, self.crack)

    def update(self, p) -> bool:
        d = p[self.a] - p[self.b] - self.crack
        want = d > -TOL if self.open else d > TOL
        if want != self.open:
            self.open = want
            return True
        return False

    def q(self, p):
        return self.g * (p[self.a] - p[self.b] - self.crack) if self.open else 0.0


class Behaviour:
    """What one part does. Subclasses provide stamp/update; flows() reports signed flow into each terminal."""
    interactive = False

    def __init__(self, sim: "Simulator", part: Part):
        self.sim, self.part = sim, part
        self.m = MEDIUM[part.medium]
        self.t = part.terms
        self.names = part.names
        self.lines = []             # (ta, tb, g) open passages
        self.seats = []

    def node(self, i):
        return self.t[self.names[i]]

    def stamp(self, s):
        for ta, tb, g in self.lines:
            s.line(self.t[ta], self.t[tb], g)
        for seat in self.seats:
            seat.stamp(s)

    def update(self, p) -> bool:
        changed = False
        for seat in self.seats:
            changed |= seat.update(p)
        return changed

    def flows(self, p) -> dict:
        out = {}

        def add(t, q):
            out[t] = out.get(t, 0.0) + q
        for ta, tb, g in self.lines:
            q = g * (p[self.t[ta]] - p[self.t[tb]])
            add(ta, q)
            add(tb, -q)
        for seat in self.seats:
            q = seat.q(p)
            add(seat.ta, q)
            add(seat.tb, -q)
        return out

    def status(self, p) -> str:
        return ""

    def readings(self, p) -> list:
        """(label, quantity, SI value) rows for the inspector."""
        return []

    def commit(self, p, dt):
        pass

    def reset(self):
        for seat in self.seats:
            seat.open = False

    def extra_capacitance(self, p) -> dict:
        return {}

    # ---- commands
    def actions(self) -> list:
        """(command id, label, is_on) buttons offered for this part."""
        return []

    def command(self, name) -> bool:
        return False


class Inert(Behaviour):
    def status(self, p):
        return "Blocked" if self.part.kind in ("plug", "unsupported") else ""


class Passage(Behaviour):
    def __init__(self, sim, part):
        super().__init__(sim, part)
        pairs = part.spec.options.get("pairs") or ([(0, 1)] if len(part.names) >= 2 else [])
        self.pairs = [(part.names[a], part.names[b]) for a, b in pairs if max(a, b) < len(part.names)]
        self.lines = [(a, b, self.m["g_pass"]) for a, b in self.pairs]

    def _q(self, p):
        return sum(abs(g * (p[self.t[a]] - p[self.t[b]])) for a, b, g in self.lines)

    def status(self, p):
        return "Flowing" if self._q(p) > FLOW_EPS else "No flow"

    def readings(self, p):
        return [("Flow", "flow", self._q(p))]


class Nozzle(Behaviour):
    def stamp(self, s):
        s.line(self.node(0), self.sim.circuit.gnd, self.m["g_pass"] * 0.01)

    def flows(self, p):
        return {self.names[0]: self.m["g_pass"] * 0.01 * p[self.node(0)]}

    def status(self, p):
        return "Venting" if p[self.node(0)] > 1000 else ""


class Pump(Behaviour):
    """Flow source. Stalls at a pressure limit: the compensator, or the ceiling of a blocked fixed pump."""
    interactive = True

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.running = True
        self.driven_by = None           # the electric motor that turns it, if the drawing says so
        self.reversed = False
        self.mode = "full"
        self.compensated = part.kind in ("pump_pc", "compressor")
        self.fault = False

    @property
    def ends(self):
        out, inn = self.names[0], self.names[1]
        return (inn, out) if self.reversed else (out, inn)

    def _lim(self):
        pl = self.part.params["setting"] if self.compensated else self.m["ceiling"]
        return pl, max(pl * 0.04, 1e3)

    def stamp(self, s):
        if not self.running:
            return
        out, inn = self.ends
        qn = self.part.params["flow"]
        pl, droop = self._lim()
        if self.mode == "full":
            s.source(self.t[inn], self.t[out], qn)
        elif self.mode == "limit":
            s.line(self.t[inn], self.t[out], qn / droop, -pl)

    def _dp(self, p):
        out, inn = self.ends
        return p[self.t[out]] - p[self.t[inn]]

    def update(self, p):
        pl, droop = self._lim()
        dp = self._dp(p)
        new = "full" if dp < pl - droop else ("zero" if dp > pl else "limit")
        if new != self.mode:
            self.mode = new
            return True
        return False

    def q(self, p):
        if not self.running or self.mode == "zero":
            return 0.0
        qn = self.part.params["flow"]
        if self.mode == "full":
            return qn
        pl, droop = self._lim()
        return max(0.0, qn * (pl - self._dp(p)) / droop)

    def flows(self, p):
        q = self.q(p)
        out, inn = self.ends
        return {inn: q, out: -q}

    def commit(self, p, dt):
        self.fault = self.running and not self.compensated and self.mode != "full"

    def reset(self):
        self.mode = "full"
        self.fault = False
        if self.driven_by is not None:
            self.running = False

    def set_driven(self, running):
        """Its motor started or stopped."""
        if running != self.running:
            self.running = running
            self.sim.touch()

    def status(self, p):
        if not self.running:
            return "Stopped" if self.driven_by is None else f"Stopped: {self.driven_by} is off"
        if self.fault:
            return "Blocked: pressure limit reached"
        if self.compensated and self.mode != "full":
            return "Compensating" if self.part.kind == "pump_pc" else "At set pressure"
        return "Running"

    def readings(self, p):
        return [("Delivery", "flow", self.q(p)), ("Pressure", "pressure", self._dp(p))]

    def actions(self):
        acts = [] if self.driven_by is not None else [("toggle", "Stop" if self.running else "Start", self.running)]
        if self.part.spec.options.get("bidir"):
            acts.append(("reverse", "Reverse direction", self.reversed))
        return acts

    def command(self, name):
        if name == "toggle" and self.driven_by is None:
            self.running = not self.running
            return True
        if name == "reverse":
            self.reversed = not self.reversed
            return True
        return False


class Relief(Behaviour):
    interactive = False

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.seat = Seat(self.node(0), self.node(1), self.names[0], self.names[1], self.m["g_relief"])
        self.seats = [self.seat]
        self.vented = False
        self.signal = None              # a proportional solenoid's share of the setting, when it has a coil
        self.interactive = bool(part.spec.options.get("vent"))

    def _crack(self):
        if self.vented:
            return 0.0
        setting = self.part.params["setting"]
        return setting if self.signal is None else setting * self.signal

    def stamp(self, s):
        self.seat.crack = self._crack()
        super().stamp(s)

    def update(self, p):
        self.seat.crack = self._crack()
        return super().update(p)

    def set_energised(self, side, on, fraction=1.0):
        if self.part.spec.options.get("vent"):
            if self.vented != on:
                self.vented = on
                self.sim.touch()
        elif self.signal != fraction:
            self.signal = fraction
            self.sim.touch()

    def status(self, p):
        if self.seat.q(p) > FLOW_EPS:
            return "Unloading" if self.vented else "Relieving"
        return "Closed"

    def readings(self, p):
        return [("Flow", "flow", max(0.0, self.seat.q(p))), ("Inlet", "pressure", p[self.node(0)])]

    def actions(self):
        return [("toggle", "De-energise" if self.vented else "Energise (unload)", self.vented)] if self.interactive else []

    def command(self, name):
        if name == "toggle" and self.interactive:
            self.vented = not self.vented
            return True
        return False

    def reset(self):
        super().reset()


class Unloading(Behaviour):
    """Opens fully while the pressure at X is above the setting."""

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.sense = self.node(2) if len(part.names) > 2 else self.node(0)
        self.open = False

    def stamp(self, s):
        if self.open:
            s.line(self.node(0), self.node(1), self.m["g_pass"])

    def update(self, p):
        st = self.part.params["setting"]
        want = p[self.sense] > (st * 0.9 if self.open else st)
        if want != self.open:
            self.open = want
            return True
        return False

    def _q(self, p):
        return self.m["g_pass"] * (p[self.node(0)] - p[self.node(1)]) if self.open else 0.0

    def flows(self, p):
        q = self._q(p)
        return {self.names[0]: q, self.names[1]: -q}

    def reset(self):
        self.open = False

    def status(self, p):
        return "Open" if self.open else "Closed"

    def readings(self, p):
        return [("Flow", "flow", self._q(p)), ("Sensing", "pressure", p[self.sense])]


class Sequence(Behaviour):
    """Holds its inlet at the setting while passing flow on, so the first actuator keeps its pressure while the
    second moves. Once the outlet needs more than the setting, it is simply open."""

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.mode = "closed"

    def stamp(self, s):
        g = self.m["g_relief"]
        if self.mode == "hold":
            s.inlet_held(self.node(0), self.node(1), g, self.part.params["setting"])
        elif self.mode == "open":
            s.line(self.node(0), self.node(1), g)

    def update(self, p):
        pin, pout, st = p[self.node(0)], p[self.node(1)], self.part.params["setting"]
        if pin <= st + TOL * (self.mode == "closed") or pin <= pout:
            new = "closed"
        elif pout >= st:
            new = "open"
        else:
            new = "hold"
        if new != self.mode:
            self.mode = new
            return True
        return False

    def _q(self, p):
        g = self.m["g_relief"]
        if self.mode == "hold":
            return g * (p[self.node(0)] - self.part.params["setting"])
        return g * (p[self.node(0)] - p[self.node(1)]) if self.mode == "open" else 0.0

    def flows(self, p):
        q = self._q(p)
        return {self.names[0]: q, self.names[1]: -q}

    def reset(self):
        self.mode = "closed"

    def status(self, p):
        return "Closed" if self.mode == "closed" else "Open"

    def readings(self, p):
        return [("Flow", "flow", self._q(p)), ("Inlet", "pressure", p[self.node(0)])]


class Reducer(Behaviour):
    """Fully open below the setting, then holds the outlet at the setting; closed if the outlet is above it."""

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.mode = "open"
        self.relief = None
        if part.spec.options.get("relieving"):
            self.relief = Seat(self.node(1), sim.circuit.gnd, self.names[1], "_vent", self.m["g_relief"])
            self.seats = [self.relief]

    def _terms(self, p):
        g = self.m["g_pass"]
        return g * (p[self.node(0)] - p[self.node(1)]), g * (self.part.params["setting"] - p[self.node(1)])

    def stamp(self, s):
        g = self.m["g_pass"]
        if self.relief:
            self.relief.crack = self.part.params["setting"] * 1.02
        super().stamp(s)
        if self.mode == "open":
            s.line(self.node(0), self.node(1), g)
        elif self.mode == "reg":
            s.regulated(self.node(0), self.node(1), g, self.part.params["setting"])

    def update(self, p):
        changed = super().update(p)
        q_open, q_reg = self._terms(p)
        new = "closed" if min(q_open, q_reg) < -g_tol(self.m) else ("open" if q_open <= q_reg else "reg")
        if new != self.mode:
            self.mode = new
            changed = True
        return changed

    def _q(self, p):
        q_open, q_reg = self._terms(p)
        return {"open": q_open, "reg": q_reg}.get(self.mode, 0.0)

    def flows(self, p):
        q = self._q(p)
        out = {self.names[0]: q, self.names[1]: -q}
        if self.relief:
            out[self.names[1]] += self.relief.q(p)
        return out

    def reset(self):
        super().reset()
        self.mode = "open"

    def status(self, p):
        if self.relief and self.relief.open:
            return "Relieving"
        return {"open": "Open", "reg": "Regulating", "closed": "Closed"}[self.mode]

    def readings(self, p):
        return [("Outlet", "pressure", p[self.node(1)]), ("Flow", "flow", self._q(p))]


def g_tol(m):
    return m["g_pass"] * TOL


class Check(Behaviour):
    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.seat = Seat(self.node(0), self.node(1), self.names[0], self.names[1], self.m["g_seat"])
        self.seats = [self.seat]

    def update(self, p):
        self.seat.crack = self.part.params["crack"]
        return super().update(p)

    def stamp(self, s):
        self.seat.crack = self.part.params["crack"]
        super().stamp(s)

    def status(self, p):
        return "Open" if self.seat.open else "Closed"

    def readings(self, p):
        return [("Flow", "flow", self.seat.q(p))]


class PilotCheck(Check):
    """Free 1->2. To open: pilot x ratio > load pressure lets 2->1 flow. To close: pilot blocks 1->2."""

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.to_close = bool(part.spec.options.get("to_close"))
        self.pilot = part.names[2] if len(part.names) > 2 else None
        self.piloted = False

    def _pilot_state(self, p):
        if self.pilot is None:
            return False
        px = p[self.t[self.pilot]]
        r = self.part.params["ratio"]
        if self.to_close:
            return px * r > p[self.node(0)] and px > TOL
        margin = 0.9 if self.piloted else 1.0
        return px * r > p[self.node(1)] * margin + 0.0 and px > 1e4

    def stamp(self, s):
        if self.to_close:
            if not self.piloted:
                super().stamp(s)
            return
        super().stamp(s)
        if self.piloted:
            s.line(self.node(0), self.node(1), self.m["g_pass"])

    def update(self, p):
        changed = super().update(p)
        want = self._pilot_state(p)
        if want != self.piloted:
            self.piloted = want
            changed = True
        return changed

    def _rev(self, p):
        return self.m["g_pass"] * (p[self.node(0)] - p[self.node(1)]) if self.piloted and not self.to_close else 0.0

    def flows(self, p):
        q = self._rev(p) + (0.0 if self.to_close and self.piloted else self.seat.q(p))
        return {self.names[0]: q, self.names[1]: -q}

    def reset(self):
        super().reset()
        self.piloted = False

    def status(self, p):
        if self.to_close:
            return "Pilot closed" if self.piloted else ("Open" if self.seat.open else "Closed")
        if self.piloted:
            return "Pilot open"
        return "Open" if self.seat.open else "Closed"

    def readings(self, p):
        return [("Flow", "flow", self._rev(p) + self.seat.q(p))]


class Shuttle(Behaviour):
    def __init__(self, sim, part):
        super().__init__(sim, part)
        g = self.m["g_seat"]
        self.seats = [Seat(self.node(0), self.node(2), self.names[0], self.names[2], g),
                      Seat(self.node(1), self.node(2), self.names[1], self.names[2], g)]

    def status(self, p):
        return "From " + self.part.comp.terminal_label(self.names[0 if p[self.node(0)] >= p[self.node(1)] else 1])


class Throttle(Behaviour):
    def opening(self):
        return self.part.params["opening"]

    def stamp(self, s):
        self.lines = [(self.names[0], self.names[1], throttle_g(self.m["g_pass"], self.opening()))]
        super().stamp(s)

    def flows(self, p):
        self.lines = [(self.names[0], self.names[1], throttle_g(self.m["g_pass"], self.opening()))]
        return super().flows(p)

    def status(self, p):
        return "Closed" if self.opening() <= 0 else "Throttling"

    def readings(self, p):
        q = abs(self.flows(p).get(self.names[0], 0.0))
        return [("Flow", "flow", q), ("Pressure drop", "pressure", abs(p[self.node(0)] - p[self.node(1)]))]


class OneWay(Throttle):
    """Throttled 1->2, free 2->1 through its bypass check (check drawn pointing the free way).

    The check in the OpenSchematix symbol gives free flow 1->2 and meters 2->1; `free: reverse` swaps that."""

    def __init__(self, sim, part):
        super().__init__(sim, part)
        a, b = (1, 0) if part.spec.options.get("free") == "reverse" else (0, 1)
        self.seats = [Seat(self.node(a), self.node(b), self.names[a], self.names[b], self.m["g_seat"], 0.1e5)]

    def status(self, p):
        return "Free flow" if self.seats[0].open else "Throttling"


class FlowPC(Behaviour):
    """Holds a set flow 1->2 however large the pressure drop; free 2->1 through a bypass unless it has none."""

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.limited = False
        if not part.spec.options.get("no_bypass"):
            self.seats = [Seat(self.node(1), self.node(0), self.names[1], self.names[0], self.m["g_seat"], 0.1e5)]

    def stamp(self, s):
        super().stamp(s)
        a, b = self.node(0), self.node(1)
        if self.limited:
            s.source(a, b, self.part.params["flow"])
        else:
            s.line(a, b, self.m["g_pass"])

    def update(self, p):
        changed = super().update(p)
        q = self.m["g_pass"] * (p[self.node(0)] - p[self.node(1)])
        lim = self.part.params["flow"]
        if self.seats and self.seats[0].open:
            want = False
            q = 0
        else:
            want = q > lim * (0.98 if self.limited else 1.0)
        if self.limited and p[self.node(0)] <= p[self.node(1)]:
            want = False
        if want != self.limited:
            self.limited = want
            changed = True
        return changed

    def _q(self, p):
        if self.limited:
            return self.part.params["flow"]
        return self.m["g_pass"] * (p[self.node(0)] - p[self.node(1)])

    def flows(self, p):
        q = self._q(p)
        out = {self.names[0]: q, self.names[1]: -q}
        if self.seats:
            qs = self.seats[0].q(p)
            out[self.names[1]] += qs
            out[self.names[0]] -= qs
        return out

    def reset(self):
        super().reset()
        self.limited = False

    def status(self, p):
        if self.seats and self.seats[0].open:
            return "Free flow"
        return "Regulating" if self.limited else "Open"

    def readings(self, p):
        return [("Flow", "flow", abs(self._q(p)))]


class Switched(Behaviour):
    """Two-state valves toggled by the user. Each state is a list of (from, to, "line" | "check")."""
    interactive = True

    def __init__(self, sim, part):
        super().__init__(sim, part)
        opts = part.spec.options
        n = part.names
        if part.kind == "switched_ports":      # outlet, outlet, inlet
            self.states = [[(n[2], n[0], "line")], [(n[2], n[1], "line")]]
        else:
            self.states = opts["states"]
        self.labels = opts["labels"]
        self.initial = 1 if part.comp.label.strip().lower() in ("closed", "nc", "n.c.", "normally closed") and \
            self.labels[1] == "Closed" else 0
        self.state = self.initial
        self._seat_bank = {}
        self._configure()

    def _configure(self):
        self.lines, self.seats = [], []
        for ta, tb, how in self.states[self.state]:
            if ta not in self.t or tb not in self.t:
                continue
            if how == "line":
                self.lines.append((ta, tb, self.m["g_pass"]))
            else:
                seat = self._seat_bank.setdefault((ta, tb), Seat(self.t[ta], self.t[tb], ta, tb, self.m["g_seat"]))
                self.seats.append(seat)

    def status(self, p):
        return self.labels[self.state]

    def actions(self):
        return [("toggle", "Switch to: " + self.labels[1 - self.state], self.state == 1)]

    def command(self, name):
        if name == "toggle":
            self.state = 1 - self.state
            self._configure()
            return True
        return False

    def set_energised(self, side, on, fraction=1.0):
        want = 1 if on else 0
        if want != self.state:
            self.state = want
            self._configure()
            self.sim.touch()

    def reset(self):
        self.state = self.initial
        self._configure()
        for seat in self._seat_bank.values():
            seat.open = False


class Prop(Throttle):
    interactive = True
    signal = None           # opening from its coil, 0..100, when it has one

    def opening(self):
        return self.part.params["opening"] if self.signal is None else self.signal

    def set_energised(self, side, on, fraction=1.0):
        value = 100.0 * fraction if on else 0.0
        if self.signal != value:
            self.signal = value
            self.sim.touch()

    def status(self, p):
        return "Closed" if self.opening() <= 0 else f"Open {self.opening():.0f}%"


_SPECIALS = {"both": [(0, 1)], "tandem": [(2, 3)], "float": [(0, 3), (1, 3)], "open": [(0, 2), (1, 2), (2, 3)],
             "b-t": [(1, 3)], "apt": [(0, 2), (2, 3)], "ab": [(0, 1)], "a-t": [(0, 3)], "ab-pt": [(0, 1), (2, 3)]}
_MANUAL_OPS_EXCLUDED = ("spring", "detent", "compensated")


class Valve(Behaviour):
    """Parametric directional control valve. Position order is left to right, as drawn; an operator on the
    left pushes the left-hand envelope over the ports."""
    interactive = True

    def __init__(self, sim, part):
        super().__init__(sim, part)
        sd_params = dict(part.comp.symdef().default_params) if part.comp.symdef() else {}
        sd_params.update(part.comp.params or {})
        medium = sd_params.get("medium", part.medium)
        vtype = sd_params.get("type", "4/3")
        if medium not in VALVE_TYPES or vtype not in VALVE_TYPES[medium]:
            medium, vtype = ("hyd", "4/3")
        nports, self.npos = VALVE_TYPES[medium][vtype]
        self.pattern_table = PATTERNS[nports]
        self.layout = [x[0] for x in LAYOUTS[(medium, nports)]]
        given = list(sd_params.get("positions") or [])
        from .vendor.openschematix.symbols.fluid import default_valve_params
        fallback = default_valve_params(medium, vtype)["positions"]
        self.positions = [given[i] if i < len(given) and given[i] in self.pattern_table else fallback[i]
                          for i in range(self.npos)]
        self.left = list(sd_params.get("left", []))
        self.right = list(sd_params.get("right", []))
        self.normal = normal_position(self.npos, self.left, self.right)
        self.position = self.normal
        self.cmd = {"left": False, "right": False}
        self.sol = {"left": False, "right": False}      # energised by a coil on the electrical sheet
        self.wired = set()                              # sides that have such a coil
        geom = part.comp.geometry()
        ports = set(self.layout)
        self.pilot_terms = {"left": [], "right": []}
        for t in geom.terminals:
            if t.name not in ports:
                self.pilot_terms["left" if t.x < 0 else "right"].append(t.name)
        self.detent = "detent" in self.left + self.right
        self.spring = "spring" in self.left + self.right
        self.pilot_active = {"left": False, "right": False}
        self._links_cache = [self._links(i) for i in range(self.npos)]
        self._configure()

    def _links(self, i):
        pat = self.pattern_table[self.positions[i]]
        pairs = [(a, b) for a, b in pat.get("arrows", [])]
        pairs += _SPECIALS.get(pat.get("special"), [])
        return [(self.layout[a], self.layout[b]) for a, b in pairs]

    def _configure(self):
        self.lines = [(a, b, self.m["g_pass"]) for a, b in self._links_cache[self.position]
                      if a in self.t and b in self.t]

    def side_can_actuate(self, side) -> bool:
        ops = self.left if side == "left" else self.right
        return any(o not in _MANUAL_OPS_EXCLUDED for o in ops)

    def set_energised(self, side, on, fraction=1.0):
        if self.sol.get(side) != on:
            self.sol[side] = on
            self._apply()
            self.sim.touch()

    def target_position(self):
        left = self.cmd["left"] or self.pilot_active["left"] or self.sol["left"]
        right = self.cmd["right"] or self.pilot_active["right"] or self.sol["right"]
        if self.npos == 3:
            if left and not right:
                return 0
            if right and not left:
                return 2
            return 1 if self.spring and not self.detent else self.position
        if left and not right:
            return 0
        if right and not left:
            return 1
        return self.normal if self.spring and not self.detent else self.position

    def update(self, p):
        for side, terms in self.pilot_terms.items():
            thr = self.part.params["pilot"]
            was = self.pilot_active[side]
            self.pilot_active[side] = any(p[self.t[t]] > (thr * 0.8 if was else thr) for t in terms)
        return self._apply()

    def _apply(self):
        pos = self.target_position()
        if pos != self.position:
            self.position = pos
            self._configure()
            return True
        return False

    def reset(self):
        self.position = self.normal
        self.cmd = {"left": False, "right": False}
        self.sol = {"left": False, "right": False}
        self.pilot_active = {"left": False, "right": False}
        self._configure()

    def position_label(self) -> str:
        return self.pattern_table[self.positions[self.position]]["label"]

    def status(self, p):
        return self.position_label()

    def readings(self, p):
        return [("Port " + self.part.comp.terminal_label(n), "pressure", p[self.t[n]])
                for n in self.layout if n in self.t]

    def actions(self):
        out = []
        for side, word in (("left", "Left"), ("right", "Right")):
            if self.side_can_actuate(side):
                ops = self.left if side == "left" else self.right
                op = next((o for o in ops if o not in _MANUAL_OPS_EXCLUDED), "")
                label = {"solenoid": "solenoid", "lever": "lever", "pilot": "pilot"}.get(op, "operator")
                if side in self.wired:
                    label += ", manual override"
                out.append((side, f"{word} {label}", self.cmd[side]))
        return out

    def command(self, name):
        if name not in self.cmd:
            return False
        self.cmd[name] = not self.cmd[name]
        if self.cmd[name]:
            other = "right" if name == "left" else "left"
            self.cmd[other] = False
        self._apply()
        return True


class Actuator(Behaviour):
    """Linear or rotary: one velocity unknown. Positive velocity = fluid into the first port."""
    interactive = False

    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.rotary = part.kind in ("motor", "rotary")
        self.limited = part.kind != "motor"
        self.a_node = self.node(0)
        self.b_node = self.node(1) if len(part.names) > 1 else None
        self.b_term = part.names[1] if len(part.names) > 1 else None
        self.x = 0.0
        self.v = 0.0
        self.v_old = 0.0
        self.dir = 0            # 0 = stopped, +1 / -1 = moving
        self.var = None
        self.reset()

    # ---- geometry
    def areas(self):
        pa = self.part.params
        if self.rotary:
            d = pa["displacement"] / (2 * math.pi)
            return d, d
        aa = math.pi / 4 * pa["bore"] ** 2
        if self.part.kind == "cylinder_single":
            return aa, 0.0
        if self.part.kind == "cylinder_equal":
            rod = math.pi / 4 * pa["rod"] ** 2
            return max(aa - rod, aa * 0.01), max(aa - rod, aa * 0.01)
        rod = math.pi / 4 * min(pa["rod"], pa["bore"] * 0.99) ** 2
        return aa, aa - rod

    def travel(self):
        if self.rotary:
            return self.part.params.get("angle", 0.0)
        return self.part.params["stroke"]

    def load(self):
        pa = self.part.params
        if self.rotary:
            return pa["torque"] if pa.get("load_mode", 0.0) >= 0.5 else 0.0
        # a "resists motion" load acts through friction(); only a constant-direction load pushes on its own
        f = pa["load"] if pa.get("load_mode", 0.0) >= 0.5 else 0.0
        if self.part.kind == "cylinder_single":
            spring = self.part.spec.options.get("spring")
            f += pa["spring"] * ((0.4 + 0.6 * self.x / max(self.travel(), 1e-6)) if spring else 1.0)
        return f

    def mass(self):
        pa = self.part.params
        return pa["inertia"] if self.rotary else pa["mass"]

    def friction(self):
        fc = self.m["breakaway"] * self.areas()[0]
        pa = self.part.params
        if pa.get("load_mode", 0.0) < 0.5:
            fc += abs(pa.get("torque" if self.rotary else "load", 0.0))
        return fc

    def viscous(self):
        """Drag coefficient: the pressure that drag costs per unit speed, times the area or displacement."""
        k = self.m["viscous_rot"] if self.rotary else self.m["viscous"]
        return k * self.areas()[0]

    def p_b(self, p):
        return p[self.b_node] if self.b_node is not None else 0.0

    # ---- solve
    def stamp(self, s):
        self.var = None
        if self.dir == 0:
            return
        self.var = s.add_var()
        aa, ab = self.areas()
        ia = s.idx[self.a_node]
        ib = s.idx[self.b_node] if self.b_node is not None else None
        v = self.var
        if ia is not None:
            s._a(ia, v, aa)
        if ib is not None and ab:
            s._a(ib, v, -ab)
        m_dt = self.mass() / self.sim.dt
        # aa pa - ab pb - (b + m/dt) v = load + friction*dir - m v_old / dt
        if ia is not None:
            s._a(v, ia, aa)
        if ib is not None and ab:
            s._a(v, ib, -ab)
        s._a(v, v, -(self.viscous() + m_dt))
        s.rhs[v] = self.load() + self.friction() * self.dir - m_dt * self.v_old

    def update(self, p):
        v = self.sim.x_vars[self.var] if self.var is not None else 0.0
        aa, ab = self.areas()
        drive = p[self.a_node] * aa - self.p_b(p) * ab - self.load()
        fc = self.friction()
        at_end = self.limited and self.x >= self.travel() - 1e-9
        at_start = self.limited and self.x <= 1e-9
        changed = False
        if self.dir != 0:
            self.v = v
            if v * self.dir <= 0 or (self.dir > 0 and at_end) or (self.dir < 0 and at_start):
                self.dir, self.v = 0, 0.0
                changed = True
        else:
            self.v = 0.0
            if drive > fc and not at_end:
                self.dir = 1
                changed = True
            elif drive < -fc and not at_start:
                self.dir = -1
                changed = True
        return changed

    def commit(self, p, dt):
        self.v_old = self.v
        if self.v == 0.0:
            return
        self.x += self.v * dt
        if self.limited:
            if self.x >= self.travel():
                self.x = self.travel()
                self.v = self.v_old = 0.0
                self.dir = 0
            elif self.x <= 0.0:
                self.x = 0.0
                self.v = self.v_old = 0.0
                self.dir = 0
        elif self.rotary:
            self.x = math.fmod(self.x, 2 * math.pi * 1000)

    def reset(self):
        self.x = self.travel() * self.part.params.get("start", 0.0) / 100.0
        self.v = self.v_old = 0.0
        self.dir = 0

    def flows(self, p):
        aa, ab = self.areas()
        out = {self.names[0]: aa * self.v}
        if self.b_term is not None:
            out[self.b_term] = -ab * self.v
        return out

    @property
    def fraction(self):
        t = self.travel()
        return self.x / t if self.limited and t > 0 else 0.0

    def status(self, p):
        if self.rotary:
            if abs(self.v) > MOVE_EPS:
                return "Turning forward" if self.v > 0 else "Turning reverse"
            if self.limited and self.x >= self.travel() - 1e-9:
                return "At end of rotation"
            return "Stopped"
        if self.v > MOVE_EPS:
            return "Extending"
        if self.v < -MOVE_EPS:
            return "Retracting"
        if self.x >= self.travel() - 1e-6:
            return "Fully extended"
        if self.x <= 1e-6:
            return "Fully retracted"
        return "Holding"

    def readings(self, p):
        rows = []
        if self.rotary:
            rows.append(("Speed", "rpm", abs(self.v)))
            rows.append(("Port " + self.names[0], "pressure", p[self.a_node]))
            if self.b_node is not None:
                rows.append(("Port " + self.names[1], "pressure", p[self.b_node]))
            return rows
        rows.append(("Position", "length", self.x))
        rows.append(("Speed", "speed", abs(self.v)))
        rows.append(("Cap side", "pressure", p[self.a_node]))
        if self.b_node is not None:
            rows.append(("Rod side", "pressure", p[self.b_node]))
        aa, ab = self.areas()
        rows.append(("Force", "force", p[self.a_node] * aa - self.p_b(p) * ab))
        return rows


class Accumulator(Behaviour):
    """Gas spring: fluid taken in compresses the gas above its precharge (isothermal)."""

    def extra_capacitance(self, p):
        pa = self.part.params
        n = self.node(0)
        pabs = max(p[n], 0.0) + ATM
        p0 = pa["precharge"] + ATM
        return {n: pa["volume"] * p0 / pabs ** 2} if pabs >= p0 else {}

    def _stored(self, p):
        pa = self.part.params
        pabs = max(p[self.node(0)], 0.0) + ATM
        p0 = pa["precharge"] + ATM
        return pa["volume"] * max(0.0, 1 - p0 / pabs)

    def status(self, p):
        return "Charged" if self._stored(p) > 1e-7 else "Empty"

    def readings(self, p):
        return [("Pressure", "pressure", p[self.node(0)]), ("Stored fluid", "volume", self._stored(p))]


class Receiver(Behaviour):
    def __init__(self, sim, part):
        super().__init__(sim, part)
        if len(part.names) > 1:
            self.lines = [(part.names[0], part.names[1], self.m["g_pass"] * 5)]

    def extra_capacitance(self, p):
        n = self.node(0)
        return {n: self.part.params["volume"] / (1.4 * (max(p[n], 0.0) + ATM))}

    def status(self, p):
        return "Pressurised" if p[self.node(0)] > 1e4 else "Empty"

    def readings(self, p):
        return [("Pressure", "pressure", p[self.node(0)])]


class Gauge(Behaviour):
    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.differential = bool(part.spec.options.get("differential")) and len(part.names) > 1
        self.silent = bool(part.spec.options.get("no_reading"))

    def value(self, p):
        if self.differential:
            return p[self.node(0)] - p[self.node(1)]
        return p[self.node(0)]

    def status(self, p):
        return ""

    def readings(self, p):
        return [] if self.silent else [("Pressure", "pressure", self.value(p))]


class PressureSwitch(Gauge):
    def __init__(self, sim, part):
        super().__init__(sim, part)
        self.on = False

    def commit(self, p, dt):
        st = self.part.params["setting"]
        self.on = p[self.node(0)] > (st * 0.95 if self.on else st)

    def reset(self):
        self.on = False

    def status(self, p):
        return "Switched" if self.on else "Off"


BEHAVIOURS = {
    "pump": Pump, "pump_pc": Pump, "compressor": Pump, "cylinder": Actuator, "cylinder_single": Actuator,
    "cylinder_equal": Actuator, "motor": Actuator, "rotary": Actuator, "relief": Relief, "sequence": Sequence,
    "unloading": Unloading, "reducer": Reducer, "check": Check, "pilot_check": PilotCheck, "shuttle": Shuttle,
    "throttle": Throttle, "oneway": OneWay, "flow_pc": FlowPC, "dcv": Valve, "switched": Switched,
    "switched_ports": Switched, "prop": Prop, "accumulator": Accumulator, "receiver": Receiver, "tank": Inert,
    "plug": Inert, "gauge": Gauge, "pressure_switch": PressureSwitch, "passage": Passage, "nozzle": Nozzle,
    "unsupported": Inert,
}
BEHAVIOURS.update(ELECTRIC_BEHAVIOURS)


# ---------------------------------------------------------------- simulator
class Simulator:
    def __init__(self, circuit: Circuit):
        self.circuit = circuit
        self.dt = DT
        self.idx = [None] * circuit.node_count
        n = 0
        self.free = []
        for node in range(circuit.node_count):
            if node not in circuit.fixed:
                self.idx[node] = n
                self.free.append(node)
                n += 1
        self.n_free = n
        self.base_c = [MEDIUM[circuit.node_medium.get(i, "hyd")]["c_line"] for i in range(circuit.node_count)]
        self.fluid = {p.key: BEHAVIOURS[p.kind](self, p) for p in circuit.parts if p.medium != "el"}
        self.parts = dict(self.fluid)
        self.net = Network(self, circuit)
        self.parts.update(self.net.by_key)
        self.cavitation = []        # seats that stop a node going below vacuum
        seen = set()
        for b in self.parts.values():
            if isinstance(b, Actuator):
                for node in (b.a_node, b.b_node):
                    if node is not None and self.idx[node] is not None and node not in seen:
                        seen.add(node)
                        seat = Seat(circuit.gnd, node, "", "", 1e-6, b.m["vacuum"])
                        self.cavitation.append((seat, node, b.part.tag))
        self.p = [0.0] * circuit.node_count
        self.x_vars = []
        self.time = 0.0
        self.events = []
        self.trace = Trace(self)
        self._idle = False
        self._last_status = {}
        self._pending = {}
        self._solves = 0
        self.reset()

    def reset(self):
        self.p = [0.0] * self.circuit.node_count
        self.time = 0.0
        self.events.clear()
        for b in self.parts.values():
            b.reset()
        for seat, *_ in self.cavitation:
            seat.open = False
        self.net.restart()
        self._idle = False
        self._last_status = {k: b.status(self.p) for k, b in self.parts.items()}
        self._pending = {}
        self.trace.clear()
        self.trace.record()

    def touch(self):
        """Something changed from outside (a command or a parameter): the circuit is no longer settled."""
        self._idle = False
        self.net.touch()

    def command(self, key, name) -> bool:
        b = self.parts.get(tuple(key))
        if b is None or not b.command(name):
            return False
        self.touch()
        self.log(b.part.tag, _command_text(b, name))
        return True

    def log(self, tag, text):
        self.events.append((self.time, tag, text))
        if len(self.events) > 5000:
            del self.events[:1000]

    # ---- stepping
    def _solve_once(self, p_old, caps):
        s = System(self)
        for node in self.free:
            i = self.idx[node]
            c = self.base_c[node] + caps.get(node, 0.0)
            k = c / self.dt
            s.rows[i][i] = s.rows[i].get(i, 0.0) + k
            s.rhs[i] += k * p_old[node]
        for b in self.fluid.values():
            b.stamp(s)
        for seat, _n, _t in self.cavitation:
            seat.stamp(s)
        scale = [1e5] * self.n_free + [1.0] * (len(s.rows) - self.n_free)
        if not s.rows:
            return list(self.p), []
        x = solve(s.rows, s.rhs, scale)
        self._solves += 1
        p = [0.0] * self.circuit.node_count
        for node in self.free:
            p[node] = x[self.idx[node]]
        return p, x

    def step(self):
        """Advance one time step: first the electrical side and any PLC, then the fluid they operate."""
        self.net.step(self.dt)
        if self._idle:
            self.time += self.dt
            if self.net.changed or self._pending:
                self._note_changes()
            return
        p_old = self.p
        caps = {}
        for b in self.fluid.values():
            for n, c in b.extra_capacitance(p_old).items():
                if self.idx[n] is not None:
                    caps[n] = caps.get(n, 0.0) + c
        was_moving = any(b.v != 0.0 for b in self.fluid.values() if isinstance(b, Actuator))
        p = p_old
        for _ in range(16):
            p, self.x_vars = self._solve_once(p_old, caps)
            changed = False
            for b in self.fluid.values():
                changed |= bool(b.update(p))
            for seat, _n, _t in self.cavitation:
                changed |= seat.update(p)
            if not changed:
                break
        self.p = p
        moving = False
        for b in self.fluid.values():
            b.commit(p, self.dt)
            if isinstance(b, Actuator) and b.v != 0.0:
                moving = True
        self.time += self.dt
        self._note_changes()
        settled = not moving and not was_moving and all(abs(a - c) < 20.0 for a, c in zip(p, p_old))
        self._idle = settled and all(b.dir == 0 for b in self.fluid.values() if isinstance(b, Actuator))

    def run(self, seconds: float):
        steps = max(1, int(round(seconds / self.dt)))
        for i in range(steps):
            self.step()
            self.trace.maybe_record()

    def _note_changes(self):
        """Log a part's new state once it has held for a moment, so chatter does not flood the log."""
        for k, b in self.parts.items():
            st = b.status(self.p)
            if st == self._last_status.get(k):
                self._pending.pop(k, None)
                continue
            cand = self._pending.get(k)
            if cand is None or cand[0] != st:
                self._pending[k] = (st, self.time)
            elif self.time - cand[1] >= 0.05:
                self._last_status[k] = st
                self._pending.pop(k, None)
                if st and b.part.kind not in ("passage",) and not getattr(b, "quiet", False):
                    self.log(b.part.tag, st)
        for seat, node, tag in self.cavitation:
            was = getattr(seat, "open", False)
            key = ("cav", node)
            if was and not self._last_status.get(key):
                self.log(tag, "Cavitation: a chamber is being pulled below atmospheric pressure")
            self._last_status[key] = was

    # ---- reading the state
    def node_pressure(self, node) -> float:
        return self.p[node]

    def status(self, key) -> str:
        b = self.parts.get(tuple(key))
        return b.status(self.p) if b else ""

    def terminal_flows(self) -> dict:
        """(sheet uid, comp id, terminal) -> signed flow into the component."""
        out = {}
        for b in self.fluid.values():
            for t, q in b.flows(self.p).items():
                out[(b.part.sheet, b.part.comp.id, t)] = q
        return out

    def actuators(self) -> list:
        return [b for b in self.parts.values() if isinstance(b, Actuator)]

    def max_pressure(self) -> float:
        """Highest setting or pressure seen, used to scale the wire colours."""
        top = 0.0
        for b in self.parts.values():
            v = b.part.params.get("setting")
            if v and b.part.kind in ("relief", "pump_pc", "compressor", "unloading"):
                top = max(top, v)
        return max(top, max(self.p, default=0.0), 1e5)

    def cavitating_nodes(self) -> set:
        return {n for seat, n, _t in self.cavitation if seat.open}


def _command_text(b, name) -> str:
    if hasattr(b, "command_text"):
        return b.command_text(name)
    if isinstance(b, Valve):
        word = "left" if name == "left" else "right"
        return f"{word.capitalize()} operator {'on' if b.cmd.get(name) else 'off'}"
    if isinstance(b, Pump):
        if name == "reverse":
            return "Direction reversed"
        return "Started" if b.running else "Stopped"
    if isinstance(b, Switched):
        return f"Switched to: {b.labels[b.state]}"
    if isinstance(b, Relief):
        return "Unloaded" if b.vented else "Loaded"
    return name


class Trace:
    """Recorded history for the trace chart and CSV export."""
    INTERVAL = 0.05
    MAX = 24000

    def __init__(self, sim: Simulator):
        self.sim = sim
        self.channels = []          # (id, label, quantity, reader)
        for b in sim.parts.values():
            part = b.part
            if isinstance(b, Actuator):
                q = "angle" if b.rotary else "length"
                if b.limited:
                    self.channels.append(((part.key, "x"), f"{part.tag} position", q, lambda bb=b: bb.x))
                speed_q = "rpm" if b.rotary else "speed"
                self.channels.append(((part.key, "v"), f"{part.tag} speed", speed_q, lambda bb=b: bb.v))
                self.channels.append(((part.key, "pa"), f"{part.tag} {part.names[0]}", "pressure",
                                      lambda n=b.a_node: sim.p[n]))
                if b.b_node is not None:
                    self.channels.append(((part.key, "pb"), f"{part.tag} {part.names[1]}", "pressure",
                                          lambda n=b.b_node: sim.p[n]))
            elif isinstance(b, Gauge) and not b.silent:
                self.channels.append(((part.key, "p"), f"{part.tag} pressure", "pressure",
                                      lambda bb=b: bb.value(sim.p)))
            elif isinstance(b, Pump):
                self.channels.append(((part.key, "p"), f"{part.tag} pressure", "pressure",
                                      lambda bb=b: bb._dp(sim.p)))
            elif hasattr(b, "trace_channels"):
                self.channels += b.trace_channels()
        self.times = []
        self.data = [[] for _ in self.channels]
        self._next = 0.0

    def clear(self):
        self.times = []
        self.data = [[] for _ in self.channels]
        self._next = 0.0

    def record(self):
        self.times.append(self.sim.time)
        for col, ch in zip(self.data, self.channels):
            col.append(ch[3]())
        self._next = self.sim.time + self.INTERVAL
        if len(self.times) > self.MAX:
            cut = self.MAX // 4
            del self.times[:cut]
            for col in self.data:
                del col[:cut]

    def maybe_record(self):
        if self.sim.time >= self._next - 1e-9:
            self.record()
