"""Sequential function charts: steps, the transitions between them, and the actions a step carries.

    {"steps": [{"id": 1, "name": "Idle", "initial": true, "actions": [{"q": "N", "target": "Lamp"}]},
               {"id": 2, "name": "Extend", "actions": [{"q": "N", "target": "Y1"},
                                                       {"q": "P", "code": "Count := Count + 1;"}]}],
     "transitions": [{"id": 1, "from": [1], "to": [2], "cond": "Start AND NOT Stop"},
                     {"id": 2, "from": [2], "to": [1], "cond": "AtEnd OR Extend.T > T#10s"}]}

As IEC 61131-3 lays down: a transition with several "from" steps fires when they are all active (convergence), one
with several "to" steps starts them all (a parallel branch), and a step stays active for at least one scan.
A step's name reads as a variable from anywhere: ``Extend.X`` (active), ``Extend.T`` (time active).

Action qualifiers: N while active; S set and R reset (stored until reset); P once on entry, P0 once on exit;
L for a limited time; D after a delay. The time for L and D is in "time".
"""
from __future__ import annotations

import re

from .core import CompileError, coercer, parse_time
from .stlang import Compiler, parse_expression, parse_statements

QUALIFIERS = {"N": "While active", "S": "Set (stays on)", "R": "Reset", "P": "Once, on entry", "P0": "Once, on exit",
              "L": "For a limited time", "D": "After a delay"}
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class StepState:
    """What ``Step.X`` and ``Step.T`` read."""
    __slots__ = ("active", "elapsed", "name", "was_active")

    def __init__(self, name=""):
        self.name = name
        self.active = False
        self.elapsed = 0
        self.was_active = False

    @classmethod
    def new(cls):
        return cls()


def _parts(source):
    steps = source.get("steps") if isinstance(source, dict) else None
    trans = source.get("transitions") if isinstance(source, dict) else None
    if not isinstance(steps, list) or not isinstance(trans, list):
        raise CompileError("this chart is damaged")
    ids = set()
    names = set()
    for s in steps:
        if not isinstance(s, dict) or isinstance(s.get("id"), bool) or not isinstance(s.get("id"), int):
            raise CompileError("a step is damaged")
        if s["id"] in ids:
            raise CompileError(f"two steps have the number {s['id']}")
        ids.add(s["id"])
        name = str(s.get("name") or "")
        if not _NAME.match(name):
            raise CompileError(f"“{name}” can't be a step's name: use letters, digits and _")
        if name.casefold() in names:
            raise CompileError(f"two steps are called {name}")
        names.add(name.casefold())
    return steps, trans, ids


def collect(source, program):
    steps, _t, _ids = _parts(source)
    for s in steps:
        program.declare_step(s["name"])
        for a in s.get("actions") or []:
            target = str(a.get("target") or "").strip() if isinstance(a, dict) else ""
            if target and _NAME.match(target):
                program.auto_bool(target)


def compile_pou(source, ctx, program, pou):
    steps, trans, ids = _parts(source)
    comp = Compiler(ctx, program, program.scope, pou)
    frame: dict = {}
    if not steps:
        return frame, lambda L: None
    if not any(s.get("initial") for s in steps):
        raise CompileError("a chart needs an initial step: mark one of the steps as the start", 0, pou)
    G = ctx.G
    states = {s["id"]: program.scope.find(s["name"]).key for s in steps}
    initial = [s["id"] for s in steps if s.get("initial")]
    compiled_trans = []
    for t in trans:
        compiled_trans.append(_transition(t, comp, ids, pou))
    actions = []
    bool_targets = {}
    for s in steps:
        for a in s.get("actions") or []:
            actions.append(_action(s, a, comp, pou, bool_targets, states[s["id"]]))
    started_key = "started"
    frame[started_key] = False
    stored: dict = {}
    frame["stored"] = stored
    targets = list(bool_targets.values())

    def run(L):
        if not L[started_key]:
            L[started_key] = True
            stored.clear()
            for sid in initial:
                st = G[states[sid]]
                st.active, st.elapsed = True, 0
        # 1. actions
        for f in targets:
            f["on"] = False
        for act in actions:
            act(L, stored, ctx.dt_ms)
        for f in targets:
            f["store"](L, f["on"] or stored.get(f["name"], False))
        # 2. timers
        for key in states.values():
            st = G[key]
            st.was_active = st.active
            if st.active:
                st.elapsed += ctx.dt_ms
        # 3. evolve: each step can give up its token to one transition per scan
        fired = []
        spent = set()
        for from_keys, to_keys, cond in compiled_trans:
            if not from_keys or any(k in spent or not G[k].active for k in from_keys):
                continue
            if cond(L):
                spent.update(from_keys)
                fired.append((from_keys, to_keys))
        for from_keys, _to in fired:
            for k in from_keys:
                st = G[k]
                st.active, st.elapsed = False, 0
        for _from, to_keys in fired:
            for k in to_keys:
                st = G[k]
                st.active, st.elapsed = True, 0
    return frame, run


def _transition(t, comp, ids, pou):
    if not isinstance(t, dict):
        raise CompileError("a transition is damaged", 0, pou)
    label = t.get("id", "?")
    try:
        sources, targets = t.get("from"), t.get("to")
        if not isinstance(sources, list) or not isinstance(targets, list) or not sources or not targets:
            raise CompileError("it must lead from a step to a step")
        for i in sources + targets:
            if i not in ids:
                raise CompileError(f"there is no step number {i}")
        text = str(t.get("cond") or "").strip()
        if not text:
            raise CompileError("it has no condition (use TRUE for one that always passes)")
        cond = comp.expr(parse_expression(text))
    except CompileError as e:
        raise CompileError(f"transition {label}: {e.message}", 0, pou) from None
    key = {s["id"]: comp.program.scope.find(s["name"]).key for s in comp.program.sfc_steps(pou)}
    return [key[i] for i in sources], [key[i] for i in targets], cond


def _action(step, a, comp, pou, bool_targets, state_key):
    where = f"step {step.get('name')}"
    if not isinstance(a, dict):
        raise CompileError(f"{where}: an action is damaged", 0, pou)
    q = a.get("q", "N")
    if q not in QUALIFIERS:
        raise CompileError(f"{where}: unknown action qualifier {q}", 0, pou)
    G = comp.G
    limit_ms = 0
    if q in ("L", "D"):
        try:
            limit_ms = parse_time(str(a.get("time") or "T#1s"))
        except (ValueError, OverflowError):
            raise CompileError(f"{where}: “{a.get('time')}” is not a time such as T#2s", 0, pou) from None
    try:
        target = str(a.get("target") or "").strip()
        code = str(a.get("code") or "").strip()
        if bool(target) == bool(code):
            raise CompileError("an action sets a tag or runs some ST, one or the other")
        if target:
            comp.writer(parse_expression(target))   # checks it can be written
            flag = bool_targets.get(target.casefold())
            if flag is None:
                flag = bool_targets[target.casefold()] = {"name": target.casefold(), "on": False,
                                                           "store": comp.writer(parse_expression(target))}
            body = None
        else:
            flag = None
            body = comp.block(parse_statements(code))
    except CompileError as e:
        raise CompileError(f"{where}: {e.message}", 0, pou) from None

    def entered(st):
        return st.active and st.elapsed == 0 and not st.was_active

    def run(L, stored, dt_ms):
        st = G[state_key]
        if q == "N":
            want = st.active
        elif q == "L":
            want = st.active and st.elapsed < limit_ms
        elif q == "D":
            want = st.active and st.elapsed >= limit_ms
        elif q == "P":
            want = entered(st)
        elif q == "P0":
            want = st.was_active and not st.active
        elif q == "S":
            if st.active:
                if flag is not None:
                    stored[flag["name"]] = True
                else:
                    stored[id(run)] = True
            want = flag is None and stored.get(id(run), False)
        else:   # R
            if st.active and flag is not None:
                stored[flag["name"]] = False
            want = False if flag is not None else st.active
        if flag is not None:
            if q != "S" and q != "R" and want:
                flag["on"] = True
        elif want:
            body(L)
    return run


def empty_program() -> dict:
    return {"steps": [{"id": 1, "name": "Step1", "initial": True, "actions": []}], "transitions": []}


__all__ = ["collect", "compile_pou", "empty_program", "QUALIFIERS", "StepState", "coercer"]
