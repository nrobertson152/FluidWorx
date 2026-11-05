"""Command line: open a file, or run a circuit without a window."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from . import APP_NAME, VERSION


def _load(path):
    from . import circuit, study as st
    if path.lower().endswith(".fluidworx"):
        s = st.load(path)
        project, warn = circuit.load_project_bytes(s.source_bytes, s.source_ext)
        c = circuit.build(project, warn, s.links)
        circuit.apply_study_params(c, s.params)
    else:
        project, warn = circuit.load_project(path)
        c = circuit.build(project, warn)
    return c


def _say(text="", err=False):
    """Print if there is anywhere to print to: a windowed Windows build has no console at all."""
    stream = sys.stderr if err else sys.stdout
    if stream is not None:
        print(text, file=stream)


def check(path) -> int:
    from .circuit import CircuitError
    from .study import StudyError
    try:
        c = _load(path)
    except (CircuitError, StudyError) as e:
        _say(e, err=True)
        return 2
    say = [f"{len(c.fluid_parts)} fluid parts"]
    if c.electrical_parts:
        say.append(f"{len(c.electrical_parts)} electrical parts")
    _say(f"{' and '.join(say)} on {len(c.sheets)} sheet(s), {c.node_count - 1} lines"
         + (f", {len(c.links)} links." if c.links else "."))
    for link in c.links:
        _say(f"link: {link.text}")
    for i in c.issues:
        _say(f"{i.level}: {i.text}")
    return 1 if any(i.level == "error" for i in c.issues) else 0


def self_test(report) -> int:
    """Create a circuit, simulate it and check the result: a one-command proof that an install works."""
    from . import circuit, engine, study as st
    lines, ok = [], True

    def note(cond, text):
        nonlocal ok
        ok = ok and bool(cond)
        lines.append(("ok   " if cond else "FAIL ") + text)
    ex = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples", "lift_cylinder.schematix")
    try:
        project, warn = circuit.load_project(ex)
        c = circuit.build(project, warn)
        sim = engine.Simulator(c)
        valve = next(k for k, b in sim.parts.items() if b.part.kind == "dcv")
        sim.run(0.5)
        sim.command(valve, "left")
        sim.run(5.0)
        act = sim.actuators()[0]
        note(act.fraction == 1.0, "cylinder reached full extension")
        project, warn = circuit.load_project(os.path.join(os.path.dirname(ex), "plc_cylinder.schematix"))
        sim = engine.Simulator(circuit.build(project, warn))
        sim.run(0.2)
        note(sim.net.plcs and sim.net.plcs[0].status() == "Run", "PLC powered up and running its program")
        button = next(k for k, b in sim.parts.items() if b.part.tag == "S0")
        sim.command(button, "press")
        sim.run(0.1)
        sim.command(button, "release")
        act = sim.actuators()[0]
        sim.run(2.0)
        note(act.x > 0.01, "PLC output energised a solenoid and the cylinder moved")
        t, peak = 0.0, 0.0
        while t < 20.0:
            sim.run(0.1)
            t += 0.1
            peak = max(peak, act.x)
            if act.x < 0.005 and peak > 0.01:
                break
        note(act.x < 0.005 and peak >= act.travel() * 0.9, "a limit switch fed back, and it came back to the start")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.fluidworx")
            s = st.from_source(ex)
            st.save(s, p)
            note(st.load(p).source_sha256 == s.source_sha256, "study saved and reopened")
    except Exception as e:  # noqa: BLE001 - this command reports every failure instead of raising
        note(False, f"{type(e).__name__}: {e}")
    lines.append(f"self-test {'PASSED' if ok else 'FAILED'} ({APP_NAME} {VERSION})")
    text = "\n".join(lines) + "\n"
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write(text)
    _say(text.rstrip("\n"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fluidworx", description="Hydraulic, pneumatic and electrical circuit simulator")
    ap.add_argument("file", nargs="?", help=".schematix, .osch or .fluidworx file to open")
    ap.add_argument("--version", "-V", action="store_true", help="show the version")
    ap.add_argument("--check", metavar="FILE", help="report what would be simulated, without a window")
    ap.add_argument("--self-test", nargs="?", const="", metavar="REPORT", help="check this install works")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        _say(f"{APP_NAME} {VERSION}")
        return 0
    if args.check:
        return check(args.check)
    if args.self_test is not None:
        return self_test(args.self_test)
    try:
        import tkinter  # noqa: F401
    except ImportError:
        _say("FluidWorx needs Tkinter (Debian/Ubuntu: sudo apt install python3-tk).", err=True)
        return 3
    from .gui.app import main as gui_main
    return gui_main(args.file)
