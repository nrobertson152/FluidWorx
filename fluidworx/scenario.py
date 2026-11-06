"""Test scenarios: what's done to a machine and what should happen, saved in the study and run again after a change.

A scenario is a list of steps, always from a clean start: the machine reset, nothing failed.

    {"name": "Normal cycle", "steps": [
        {"do": "wait", "seconds": 0.5},
        {"do": "command", "part": "uid/id", "tag": "S1", "command": "press"},
        {"do": "wait_for", "part": "uid/id", "tag": "A1", "status": "Fully extended", "timeout": 10.0},
        {"do": "check", "part": "uid/id", "tag": "Y1", "status": "Energised"},
        {"do": "check", "part": "uid/id", "tag": "A1", "reading": "Position", "quantity": "length", "at_least": 0.19, "at_most": 0.21},
        {"do": "fault", "part": "uid/id", "tag": "S2", "fault": "stuck_open"},
        {"do": "line", "line": "uid/id", "tag": "K1 13 to Y1 A1", "failed": true}]}

Parts are found by what never changes in a drawing, their sheet and component ids, and tags are kept to say what's meant if one has
gone. What a check says is the simulation's word: that this model behaves this way. It says nothing about a real machine.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MAX_SCENARIOS = 200
MAX_STEPS = 5000
MAX_TEXT = 200
MAX_SECONDS = 36000.0
DEFAULT_TIMEOUT = 30.0
_KINDS = ("wait", "command", "wait_for", "check", "fault", "line")


def part_id(key) -> str:
    return f"{key[0]}/{key[1]}"


def _text(x) -> str:
    return x[:MAX_TEXT] if isinstance(x, str) else ""


def _number(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _clean_step(raw):
    """A step with only what it should have in it, or None if it can't be made sense of."""
    if not isinstance(raw, dict) or raw.get("do") not in _KINDS:
        return None
    kind = raw["do"]
    step = {"do": kind}
    if kind == "wait":
        seconds = _number(raw.get("seconds"))
        if seconds is None:
            return None
        step["seconds"] = max(0.0, min(MAX_SECONDS, seconds))
        return step
    step["tag"] = _text(raw.get("tag"))
    if kind == "line":
        where = _text(raw.get("line"))
        if not where or "/" not in where:
            return None
        step["line"] = where
        step["failed"] = raw.get("failed") is True
        return step
    where = _text(raw.get("part"))
    if not where or "/" not in where:
        return None
    step["part"] = where
    if kind == "command":
        step["command"] = _text(raw.get("command"))
        return step if step["command"] else None
    if kind == "fault":
        fault = raw.get("fault")
        step["fault"] = _text(fault) if isinstance(fault, str) else None
        return step
    if raw.get("reading") is not None:
        step["reading"] = _text(raw.get("reading"))
        step["quantity"] = _text(raw.get("quantity"))
        low, high = _number(raw.get("at_least")), _number(raw.get("at_most"))
        if not step["reading"] or (low is None and high is None):
            return None
        if low is not None:
            step["at_least"] = low
        if high is not None:
            step["at_most"] = high
    else:
        step["status"] = _text(raw.get("status"))
    if kind == "wait_for":
        timeout = _number(raw.get("timeout"))
        step["timeout"] = max(0.0, min(MAX_SECONDS, DEFAULT_TIMEOUT if timeout is None else timeout))
    return step


def clean(raw) -> list:
    """Scenarios from a file. Nothing in a file is trusted: what can't be used is left out."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:MAX_SCENARIOS]:
        if not isinstance(item, dict):
            continue
        steps = item.get("steps")
        steps = [s for s in (_clean_step(x) for x in steps[:MAX_STEPS]) if s is not None] if isinstance(steps, list) else []
        out.append({"name": _text(item.get("name")) or f"Scenario {len(out) + 1}", "steps": steps})
    return out


def describe(step, units=None) -> str:
    """A step in words."""
    kind = step["do"]
    tag = step.get("tag") or "?"
    if kind == "wait":
        return f"Wait {step['seconds']:g} s"
    if kind == "command":
        return f"{tag}: {step['command']}"
    if kind == "fault":
        return f"{tag}: fail it, {step['fault']}" if step.get("fault") else f"{tag}: put it right"
    if kind == "line":
        return f"{tag}: fail this line" if step["failed"] else f"{tag}: repair this line"
    what = _expectation(step, units)
    if kind == "wait_for":
        return f"Wait for {tag} {what}, at most {step['timeout']:g} s"
    return f"Check {tag} {what}"


def _shown(step, value, units) -> str:
    q = step.get("quantity") or ""
    if units is not None and q:
        try:
            return units.fmt(q, value)
        except (KeyError, ValueError):
            pass
    return f"{value:g}"


def _expectation(step, units=None) -> str:
    if "reading" not in step:
        return f"is {step.get('status', '')}"
    label = step["reading"]
    low, high = step.get("at_least"), step.get("at_most")
    if low is not None and high is not None:
        return f"{label} is {_shown(step, low, units)} to {_shown(step, high, units)}"
    if low is not None:
        return f"{label} is at least {_shown(step, low, units)}"
    return f"{label} is at most {_shown(step, high, units)}"


@dataclass
class StepResult:
    index: int
    text: str
    ok: bool
    detail: str = ""
    at: float = 0.0


@dataclass
class Result:
    name: str
    rows: list = field(default_factory=list)
    time: float = 0.0
    races: list = field(default_factory=list)
    finished: bool = False

    @property
    def passed(self) -> bool:
        return self.finished and all(r.ok for r in self.rows)

    @property
    def failures(self) -> list:
        return [r for r in self.rows if not r.ok]


class Runner:
    """Runs a scenario on a simulator, a step at a time, so that a window can stay alive around it or show it happening."""

    def __init__(self, sim, scenario, units=None):
        self.sim, self.scenario, self.units = sim, scenario, units
        self.steps = scenario["steps"]
        self.result = Result(scenario.get("name", ""))
        self.i = 0
        self.until = None
        self.lines_changed = False
        self.by_id = {part_id(k): k for k in sim.parts}
        sim.clear_faults()
        sim.reset()

    def advance(self) -> bool:
        """As far as the next simulation step. False once it's finished."""
        sim = self.sim
        while self.i < len(self.steps):
            step = self.steps[self.i]
            kind = step["do"]
            if kind == "wait":
                if self.until is None:
                    self.until = sim.time + step["seconds"]
                if sim.time >= self.until - 1e-9:
                    self._done(True)
                    continue
                self._step()
                return True
            if kind == "wait_for":
                if not self._wait_for(step):
                    return True
                continue
            if kind == "check":
                self._check(step)
            elif kind == "command":
                self._command(step)
            elif kind == "fault":
                self._fault(step)
            else:
                self._line(step)
        self._finish()
        return False

    def run(self) -> Result:
        while self.advance():
            pass
        return self.result

    # ---- stepping
    def _step(self):
        self.sim.step()
        self.sim.trace.maybe_record()

    def _done(self, ok, detail=""):
        step = self.steps[self.i]
        self.result.rows.append(StepResult(self.i, describe(step, self.units), ok, detail, self.sim.time))
        self.i += 1
        self.until = None

    def _finish(self):
        self.result.time = self.sim.time
        self.result.races = list(self.sim.net.races)
        self.result.finished = True

    def _key(self, step):
        return self.by_id.get(step.get("part", ""))

    # ---- each kind of step
    def _gone(self, step):
        self._done(False, f"{step.get('tag') or 'This part'} isn't in the drawing any more")

    def _wait_for(self, step) -> bool:
        """True once this step is over."""
        key = self._key(step)
        if key is None:
            self._gone(step)
            return True
        if self.until is None:
            self.until = self.sim.time + step["timeout"]
            self._started = self.sim.time
        met, seen = self._met(step, key)
        if met:
            self._done(True, f"took {self.sim.time - self._started:.2f} s")
            return True
        if self.sim.time >= self.until - 1e-9:
            self._done(False, f"after {step['timeout']:g} s, {seen}")
            return True
        self._step()
        return False

    def _check(self, step):
        key = self._key(step)
        if key is None:
            self._gone(step)
            return
        met, seen = self._met(step, key)
        self._done(met, "" if met else seen)

    def _met(self, step, key):
        """(whether what it expects is so, what it is instead)."""
        sim = self.sim
        if "reading" not in step:
            now = sim.status(key)
            return now == step.get("status", ""), f"it's “{now}”"
        rows = {label: value for label, _q, value in sim.parts[key].readings(sim.p)}
        if step["reading"] not in rows:
            return False, f"it has no reading called {step['reading']}"
        value = rows[step["reading"]]
        value = abs(value) if isinstance(value, complex) else float(value)
        ok = value >= step.get("at_least", -math.inf) and value <= step.get("at_most", math.inf)
        return ok, f"{step['reading']} is {_shown(step, value, self.units)}"

    def _command(self, step):
        key = self._key(step)
        if key is None:
            self._gone(step)
        elif self.sim.command(key, step["command"]):
            self._done(True)
        else:
            self._done(False, f"it wouldn't do that: {step['command']}")

    def _fault(self, step):
        key = self._key(step)
        if key is None:
            self._gone(step)
        elif self.sim.set_fault(key, step.get("fault")):
            self._done(True)
        else:
            self._done(False, f"it has no such fault: {step.get('fault')}")

    def _line(self, step):
        sheet, _slash, wire = step["line"].partition("/")
        ref = (sheet, _int(wire))
        if not self.sim.line_can_fail(ref):
            self._done(False, f"{step.get('tag') or 'This line'} isn't in the drawing any more")
            return
        if bool(self.sim.line_fault(ref)) != step["failed"]:
            self.sim.set_line_fault(ref, step["failed"])
            self.lines_changed = True
        self._done(True)


def _int(text):
    try:
        return int(text)
    except ValueError:
        return text


class Recorder:
    """Writes down what someone does to a running simulation, and how long they took about it."""

    def __init__(self, sim):
        self.sim = sim
        self.steps = []
        self.last = sim.time

    def _pause(self):
        gap = round(self.sim.time - self.last, 2)
        if gap > 0:
            self.steps.append({"do": "wait", "seconds": gap})
        self.last = self.sim.time

    def command(self, key, name, tag):
        self._pause()
        self.steps.append({"do": "command", "part": part_id(key), "tag": tag, "command": name})

    def fault(self, key, name, tag):
        self._pause()
        self.steps.append({"do": "fault", "part": part_id(key), "tag": tag, "fault": name})

    def line(self, ref, failed, name):
        self._pause()
        self.steps.append({"do": "line", "line": f"{ref[0]}/{ref[1]}", "tag": name, "failed": bool(failed)})

    def expect(self, step):
        """What should be so by now, as the person says it is."""
        if step["do"] == "check":
            self._pause()
        else:
            self.last = self.sim.time   # waiting for it takes the place of the time spent waiting to see it
        self.steps.append(step)


def state_check(sim, key, wait=False, timeout=DEFAULT_TIMEOUT) -> dict:
    """A step that expects this part to be as it is now."""
    b = sim.parts[tuple(key)]
    step = {"do": "wait_for" if wait else "check", "part": part_id(tuple(key)), "tag": b.part.tag, "status": sim.status(key)}
    if wait:
        step["timeout"] = timeout
    return step


def reading_check(sim, key, label, tolerance=0.05, wait=False, timeout=DEFAULT_TIMEOUT):
    """A step that expects this reading, within a share of itself. None if it has no such reading."""
    b = sim.parts[tuple(key)]
    for name, quantity, value in b.readings(sim.p):
        if name == label:
            value = abs(value) if isinstance(value, complex) else float(value)
            margin = abs(value) * tolerance
            step = {"do": "wait_for" if wait else "check", "part": part_id(tuple(key)), "tag": b.part.tag, "reading": label,
                    "quantity": quantity, "at_least": value - margin, "at_most": value + margin}
            if wait:
                step["timeout"] = timeout
            return step
    return None
