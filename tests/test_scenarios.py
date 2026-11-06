"""Saved test scenarios: what's done to a machine and what should happen, run again after a change."""
import json
import os
import zipfile

import pytest
from conftest import EXAMPLES, run_example

from fluidworx import circuit, cli, engine, scenario, study as st
from fluidworx.units import Units


def tag(sim, name):
    return next(b for b in sim.parts.values() if b.part.tag == name)


def key(sim, name):
    return tag(sim, name).part.key


def machine():
    _c, sim = run_example("relay_latch.schematix")
    return sim


def pid(k):
    return f"{k[0]}/{k[1]}"


def normal_cycle(sim):
    """Press start, and the rod goes out."""
    return {"name": "Normal cycle", "steps": [
        {"do": "wait", "seconds": 0.2},
        {"do": "command", "part": pid(key(sim, "S1")), "tag": "S1", "command": "press"},
        {"do": "wait", "seconds": 0.1},
        {"do": "command", "part": pid(key(sim, "S1")), "tag": "S1", "command": "release"},
        {"do": "wait_for", "part": pid(key(sim, "A1")), "tag": "A1", "status": "Fully extended", "timeout": 10.0},
        {"do": "check", "part": pid(key(sim, "Y1a")), "tag": "Y1a", "status": "Energised"},
        {"do": "check", "part": pid(key(sim, "A1")), "tag": "A1", "reading": "Position", "quantity": "length", "at_least": 0.1},
    ]}


def run(sim, test):
    return scenario.Runner(sim, test, Units("metric")).run()


def test_a_scenario_that_should_pass_passes_and_says_how_long_it_took():
    sim = machine()
    result = run(sim, scenario.clean([normal_cycle(sim)])[0])
    assert result.passed, [(r.text, r.detail) for r in result.failures]
    waited = next(r for r in result.rows if r.text.startswith("Wait for A1"))
    assert waited.detail.startswith("took ") and waited.ok
    assert result.time > 0.3


def test_it_starts_from_a_reset_with_nothing_failed():
    sim = machine()
    sim.run(1.0)
    sim.set_fault(key(sim, "S1"), "stuck_open")
    result = run(sim, normal_cycle(sim))
    assert result.passed
    assert sim.time == result.time


def test_a_broken_machine_fails_and_says_what_it_saw():
    sim = machine()
    test = normal_cycle(sim)
    test["steps"].insert(0, {"do": "fault", "part": pid(key(sim, "S1")), "tag": "S1", "fault": "stuck_open"})
    test["steps"][5]["timeout"] = 1.0
    result = run(sim, test)
    assert not result.passed
    failed = result.failures[0]
    assert "after 1 s" in failed.detail and "A1" in failed.text and "Fully retracted" in failed.detail


def test_a_change_to_the_design_shows_up():
    """The point of it. The same scenario, on a longer stroke, against the same limit."""
    sim = machine()
    test = normal_cycle(sim)
    test["steps"][4]["timeout"] = 3.0
    assert run(sim, test).passed
    tag(sim, "A1").part.params["stroke"] *= 10
    result = run(sim, test)
    assert not result.passed and result.failures[0].text.startswith("Wait for A1")


def test_a_reading_out_of_its_limits_fails():
    sim = machine()
    test = normal_cycle(sim)
    test["steps"][-1] = {"do": "check", "part": pid(key(sim, "A1")), "tag": "A1", "reading": "Position", "quantity": "length", "at_most": 0.01}
    result = run(sim, test)
    assert not result.passed
    assert "Position is" in result.failures[0].detail and "mm" in result.failures[0].detail


def test_a_reading_it_doesnt_have_fails():
    sim = machine()
    result = run(sim, {"name": "x", "steps": [{"do": "check", "part": pid(key(sim, "A1")), "tag": "A1", "reading": "Colour", "at_least": 1.0}]})
    assert "no reading called Colour" in result.failures[0].detail


def test_a_part_no_longer_in_the_drawing_fails_by_name():
    sim = machine()
    for step in ({"do": "command", "part": "gone/1", "tag": "S9", "command": "press"}, {"do": "check", "part": "gone/1", "tag": "S9", "status": "Open"},
                 {"do": "wait_for", "part": "gone/1", "tag": "S9", "status": "Open", "timeout": 1.0}, {"do": "fault", "part": "gone/1", "tag": "S9", "fault": "stuck"}):
        result = run(sim, {"name": "x", "steps": [step]})
        assert not result.passed and "S9 isn't in the drawing" in result.failures[0].detail
    result = run(sim, {"name": "x", "steps": [{"do": "line", "line": "gone/1", "tag": "K1 to K2", "failed": True}]})
    assert "K1 to K2 isn't in the drawing" in result.failures[0].detail


def test_a_command_it_wont_take_fails():
    sim = machine()
    result = run(sim, {"name": "x", "steps": [{"do": "command", "part": pid(key(sim, "S1")), "tag": "S1", "command": "dance"}]})
    assert "wouldn't do that" in result.failures[0].detail
    result = run(sim, {"name": "x", "steps": [{"do": "fault", "part": pid(key(sim, "S1")), "tag": "S1", "fault": "dance"}]})
    assert "no such fault" in result.failures[0].detail


def test_faults_and_broken_wires_are_steps():
    sim = machine()
    ref = next(iter(sim.net._drawn_wires))
    test = {"name": "x", "steps": [{"do": "fault", "part": pid(key(sim, "S1")), "tag": "S1", "fault": "stuck_open"},
                                   {"do": "line", "line": f"{ref[0]}/{ref[1]}", "tag": "a wire", "failed": True},
                                   {"do": "wait", "seconds": 0.1},
                                   {"do": "fault", "part": pid(key(sim, "S1")), "tag": "S1", "fault": None},
                                   {"do": "line", "line": f"{ref[0]}/{ref[1]}", "tag": "a wire", "failed": False}]}
    runner = scenario.Runner(sim, test)
    while runner.advance():
        pass
    assert runner.result.passed and runner.lines_changed
    assert sim.fault_rows() == []
    assert [line[1] for line in sim.events if line[2].startswith("Failed on purpose")] == ["S1", sim.line_name(ref)]


def test_races_are_reported_with_the_result():
    from drawing import Drawing
    from test_electric import interlock
    d = Drawing()
    interlock(d, "K1", "K2")
    sim = d.sim()
    result = run(sim, {"name": "x", "steps": [{"do": "wait", "seconds": 0.1}]})
    assert result.passed and result.races == [(0.0, "K1", "K2")]


def test_it_comes_out_the_same_every_time():
    sim = machine()
    test = normal_cycle(sim)
    results = [run(sim, test) for _ in range(3)]
    assert len({r.time for r in results}) == 1
    assert len({tuple(row.detail for row in r.rows) for r in results}) == 1


# ---------------------------------------------------------------- recording
def test_recording_writes_down_what_was_done_and_when():
    sim = machine()
    rec = scenario.Recorder(sim)
    sim.run(0.25)
    rec.command(key(sim, "S1"), "press", "S1")
    sim.command(key(sim, "S1"), "press")
    sim.run(0.1)
    rec.command(key(sim, "S1"), "release", "S1")
    sim.command(key(sim, "S1"), "release")
    sim.run(1.0)
    rec.fault(key(sim, "S2"), "stuck_open", "S2")
    rec.line(("u", 1), True, "S1 to K1")
    assert [s["do"] for s in rec.steps] == ["wait", "command", "wait", "command", "wait", "fault", "line"]
    assert rec.steps[0]["seconds"] == pytest.approx(0.25, abs=0.011)
    assert rec.steps[2]["seconds"] == pytest.approx(0.1, abs=0.011)
    assert scenario.clean([{"name": "r", "steps": rec.steps}])[0]["steps"] == rec.steps


def test_what_it_expects_comes_from_how_it_is_now():
    sim = machine()
    sim.command(key(sim, "S1"), "press")
    sim.run(0.2)
    check = scenario.state_check(sim, key(sim, "K1"))
    assert check["do"] == "check" and check["status"] == sim.status(key(sim, "K1"))
    wait = scenario.state_check(sim, key(sim, "K1"), wait=True, timeout=4.0)
    assert wait["do"] == "wait_for" and wait["timeout"] == 4.0
    reading = scenario.reading_check(sim, key(sim, "A1"), "Position", 0.1)
    assert reading["at_least"] <= tag(sim, "A1").x <= reading["at_most"]
    assert scenario.reading_check(sim, key(sim, "A1"), "Colour") is None


def test_recording_then_running_passes():
    sim = machine()
    rec = scenario.Recorder(sim)
    sim.run(0.2)
    rec.command(key(sim, "S1"), "press", "S1")
    sim.command(key(sim, "S1"), "press")
    sim.run(0.1)
    rec.command(key(sim, "S1"), "release", "S1")
    sim.command(key(sim, "S1"), "release")
    sim.run(4.0)
    rec.expect(scenario.state_check(sim, key(sim, "A1"), wait=True, timeout=8.0))
    rec.expect(scenario.reading_check(sim, key(sim, "A1"), "Position"))
    assert run(sim, {"name": "x", "steps": rec.steps}).passed


def test_steps_read_as_words():
    say = scenario.describe
    assert say({"do": "wait", "seconds": 1.5}) == "Wait 1.5 s"
    assert say({"do": "command", "tag": "S1", "command": "press"}) == "S1: press"
    assert say({"do": "fault", "tag": "S1", "fault": "stuck_open"}) == "S1: fail it, stuck_open"
    assert say({"do": "fault", "tag": "S1", "fault": None}) == "S1: put it right"
    assert say({"do": "line", "tag": "K1 13", "failed": True}) == "K1 13: fail this line"
    assert say({"do": "check", "tag": "Y1", "status": "Energised"}) == "Check Y1 is Energised"
    assert say({"do": "wait_for", "tag": "A1", "status": "Fully extended", "timeout": 10.0}) == "Wait for A1 is Fully extended, at most 10 s"
    text = say({"do": "check", "tag": "A1", "reading": "Position", "quantity": "length", "at_least": 0.19, "at_most": 0.21}, Units("metric"))
    assert "Position is 190 mm to 210 mm" in text


# ---------------------------------------------------------------- in the file
def _study(tests=()):
    return st.Study(source_name="x.schematix", source_sha256=st.sha256(b"abc"), source_bytes=b"abc", scenarios=list(tests))


def _version(data):
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read("manifest.json"))["version"]


def test_a_study_without_scenarios_stays_in_the_old_format():
    assert _version(st.to_bytes(_study())) == 1
    assert _version(st.to_bytes(st.Study(source_name="x.schematix", source_sha256=st.sha256(b"abc"), source_bytes=b"abc", links={"a/1": {"Senses": "A1"}}))) == 2


def test_scenarios_are_saved_and_come_back(tmp_path):
    test = {"name": "One", "steps": [{"do": "wait", "seconds": 1.0}, {"do": "check", "part": "a/1", "tag": "K1", "status": "Off"}]}
    data = st.to_bytes(_study([test]))
    assert _version(data) == 3
    assert st.from_bytes(data).scenarios == [test]
    f = tmp_path / "s.fluidworx"
    st.save(_study([test]), str(f))
    assert st.load(str(f)).scenarios == [test]


def test_older_studies_still_open():
    """Formats 1 and 2 have no scenarios, and that's all."""
    older = st.from_bytes(st.to_bytes(_study()))
    assert older.scenarios == []


def test_a_newer_format_is_refused_by_an_older_reader_with_a_message():
    import io
    data = st.to_bytes(_study([{"name": "One", "steps": []}]))
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as z, zipfile.ZipFile(out, "w") as w:
        for name in z.namelist():
            raw = z.read(name)
            if name == "manifest.json":
                doc = json.loads(raw)
                doc["version"] = st.FORMAT_VERSION + 1
                raw = json.dumps(doc)
            w.writestr(name, raw)
    with pytest.raises(st.StudyError, match="newer"):
        st.from_bytes(out.getvalue())


@pytest.mark.parametrize("raw,want", [
    (None, []), ("x", []), (3, []), ([], []), ([3], []),
    ([{"name": "A"}], [{"name": "A", "steps": []}]),
    ([{"steps": "x"}], [{"name": "Scenario 1", "steps": []}]),
    ([{"name": 4, "steps": [{"do": "explode"}, 7, {"do": "wait"}, {"do": "wait", "seconds": "9"}, {"do": "wait", "seconds": float("nan")}, {"do": "wait", "seconds": True}]}],
     [{"name": "Scenario 1", "steps": []}]),
    ([{"name": "B", "steps": [{"do": "wait", "seconds": -5}, {"do": "wait", "seconds": 1e12}]}], [{"name": "B", "steps": [{"do": "wait", "seconds": 0.0}, {"do": "wait", "seconds": scenario.MAX_SECONDS}]}]),
    ([{"name": "C", "steps": [{"do": "command", "part": "nothing", "command": "x"}, {"do": "command", "part": "a/1"}, {"do": "line", "line": 4}, {"do": "check", "part": "a/1", "reading": "P"}]}], [{"name": "C", "steps": []}]),
])
def test_nothing_in_a_file_is_trusted(raw, want):
    assert scenario.clean(raw) == want


def test_there_are_limits():
    many = [{"name": "x", "steps": [{"do": "wait", "seconds": 1}] * (scenario.MAX_STEPS + 5)}] * (scenario.MAX_SCENARIOS + 5)
    out = scenario.clean(many)
    assert len(out) == scenario.MAX_SCENARIOS and len(out[0]["steps"]) == scenario.MAX_STEPS
    long = scenario.clean([{"name": "n" * 9000, "steps": [{"do": "check", "part": "a/1", "tag": "t" * 9000, "status": "s" * 9000}]}])[0]
    assert len(long["name"]) == scenario.MAX_TEXT and len(long["steps"][0]["tag"]) == scenario.MAX_TEXT


# ---------------------------------------------------------------- the command line
def _saved_study(tmp_path, change=None):
    path = os.path.join(EXAMPLES, "relay_latch.schematix")
    s = st.from_source(path)
    project, warn = circuit.load_project(path)
    sim = engine.Simulator(circuit.build(project, warn))
    test = normal_cycle(sim)
    if change:
        change(test)
    s.scenarios = [test]
    f = tmp_path / "t.fluidworx"
    st.save(s, str(f))
    return str(f)


def test_the_command_line_passes(tmp_path, capsys):
    assert cli.main(["--test", _saved_study(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "pass  Normal cycle" in out and "1 of 1 passed" in out and "real machine" in out


def test_the_command_line_fails(tmp_path, capsys):
    def impossible(test):
        test["steps"].append({"do": "check", "part": test["steps"][-1]["part"], "tag": "A1", "status": "Melted"})
    assert cli.main(["--test", _saved_study(tmp_path, impossible)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  Normal cycle" in out and "Melted" in out and "0 of 1 passed" in out


def test_the_command_line_with_nothing_to_run(tmp_path, capsys):
    f = tmp_path / "n.fluidworx"
    st.save(st.from_source(os.path.join(EXAMPLES, "relay_latch.schematix")), str(f))
    assert cli.main(["--test", str(f)]) == 2
    assert "no test scenarios" in capsys.readouterr().err
    assert cli.main(["--test", str(tmp_path / "missing.fluidworx")]) == 2
    bad = tmp_path / "bad.fluidworx"
    bad.write_bytes(b"nope")
    assert cli.main(["--test", str(bad)]) == 2


def test_results_are_in_the_report(tmp_path):
    from fluidworx import report
    path = os.path.join(EXAMPLES, "relay_latch.schematix")
    study = st.from_source(path)
    sim = machine()
    good = run(sim, normal_cycle(sim))
    bad = run(sim, {"name": "Bad <one>", "steps": [{"do": "check", "part": pid(key(sim, "A1")), "tag": "A1", "status": "Melted"}]})
    html = report.html_report(study, sim.circuit, sim, Units("metric"), sim.circuit.project.sheets[0], tests=[good, bad])
    assert "<h2>Test scenarios</h2>" in html and "real machine" in html and "Bad &lt;one&gt;" in html and "Melted" in html and "FAIL" in html
