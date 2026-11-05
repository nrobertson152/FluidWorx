"""Real exchange with the sibling programs when they can be imported, their documented formats otherwise."""
import json
import os
import shutil
import subprocess
import sys

import pytest
from conftest import run_example

from fluidworx import report, study as st
from fluidworx.integrations import caldera as cal
from fluidworx.integrations import revisionworx as rw
from fluidworx.integrations import tools
from fluidworx.units import Units

IN = 0.0254


def _ran():
    c, sim = run_example("lift_cylinder.schematix")
    k = next(k for k, b in sim.parts.items() if b.part.kind == "dcv")
    sim.command(k, "left")
    sim.run(6.0)
    sim.command(k, "left")
    sim.run(.2)
    sim.command(k, "right")
    sim.run(6.0)
    return c, sim


def test_caldera_export_values_are_in_calderas_units(tmp_path):
    _c, sim = _ran()
    recs = cal.cylinder_records(sim, "Lift", report.cycle_times(sim))
    assert len(recs) == 1
    r = recs[0]
    assert r["tool"] == "Hydraulic Cylinder"
    bore, rod, stroke, psi, gpm = (float(x) for x in r["inputs"])
    assert bore == pytest.approx(.063 / IN, rel=1e-3)
    assert stroke == pytest.approx(.3 / IN, rel=1e-3)
    assert psi == pytest.approx(160e5 / 6894.757, rel=1e-3)
    assert gpm == pytest.approx(12 / 3.785412, rel=1e-3)
    assert "Simulated extend" in r["note"]


def test_caldera_file_is_accepted_by_the_real_parser_when_available(tmp_path):
    _c, sim = _ran()
    p = tmp_path / "x.caldera"
    cal.write_project(str(p), "Lift", cal.cylinder_records(sim, "Lift"))
    obj = json.loads(p.read_text())
    assert obj["format"] == "caldera-project" and obj["format_version"] == 1
    try:
        from caldera import extended, workspace     # noqa: F401
    except ImportError:
        pytest.skip("Caldera is not installed here")
    parsed = workspace.parse_project(p.read_text())
    assert parsed["name"] == "Lift" and parsed["history"][0]["tool"] == "Hydraulic Cylinder"
    # same inputs, in the same order, as Caldera's own calculator; recalculating agrees with what we wrote
    rec = parsed["history"][0]
    assert len(extended.EXTRA["Hydraulic Cylinder"]) == len(rec["inputs"])
    result = extended.calculate("Hydraulic Cylinder", [float(x) for x in rec["inputs"]])
    assert f"Extend time (s): {result['Extend time (s)']:.2f}" in rec["result"]
    assert f"Retract force (lbf): {result['Retract force (lbf)']:.1f}" in rec["result"]


def test_caldera_round_trip_applies_to_matching_parts(tmp_path):
    c, sim = _ran()
    p = tmp_path / "x.caldera"
    cal.write_project(str(p), "Lift", cal.cylinder_records(sim, "Lift"))
    proj = cal.read_project(str(p))
    parts = {x.tag: x for x in c.parts}
    vals = cal.applicable(proj["history"][0], parts["A1"])
    assert vals["bore"] == pytest.approx(.063, rel=1e-3) and vals["stroke"] == pytest.approx(.3, rel=1e-3)
    assert cal.applicable(proj["history"][0], parts["P1"])["flow"] == pytest.approx(12e-3 / 60, rel=1e-3)
    assert cal.applicable(proj["history"][0], parts["V2"])["setting"] == pytest.approx(160e5, rel=1e-3)
    assert cal.applicable(proj["history"][0], parts["V1"]) == {}


def test_caldera_import_accepts_math_and_rejects_rubbish(tmp_path):
    good = {"tool": "Hydraulic Cylinder", "inputs": ["5/2", "1", "12", "2500", "10"]}
    assert cal.values_from_record(good)["cylinder"]["bore"] == pytest.approx(2.5 * IN)
    assert cal.values_from_record({"tool": "Hydraulic Cylinder", "inputs": ["x", "1"]}) == {}
    assert cal.values_from_record({"tool": "Wire Gauge", "inputs": []}) == {}
    f = tmp_path / "bad.caldera"
    f.write_text("{}")
    with pytest.raises(cal.CalderaError):
        cal.read_project(str(f))
    f.write_text("nonsense{")
    with pytest.raises(cal.CalderaError):
        cal.read_project(str(f))


def test_workspace_found_by_walking_up(tmp_path):
    (tmp_path / ".revisionworx").mkdir()
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert rw.find_workspace(str(deep / "f.schematix")) == str(tmp_path)
    assert rw.find_workspace("/definitely/not/here/f.schematix") in (None,)


def _rwx_cmd():
    cmd = tools.find("revisionworx")
    if cmd is None:
        pytest.skip("RevisionWorx is not installed here")
    return cmd


def test_real_revisionworx_status_register_and_checkin(tmp_path, examples_dir, monkeypatch):
    cmd = _rwx_cmd()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    ws = tmp_path / "eng"
    ws.mkdir()

    def run(*a):
        r = subprocess.run([*cmd, "--json", "-w", str(ws), *a], capture_output=True, text=True, check=True)
        return json.loads(r.stdout)
    subprocess.run([*cmd, "init", str(ws), "--name", "T"], capture_output=True, check=True)
    run("root", "add", "Projects", str(ws / "Projects")) if (ws / "Projects").mkdir() is None else None
    prj = run("project", "new", "--name", "Pump", "--number", "J1")
    folder = next((ws / "Projects").rglob("J1 Pump"))
    src = folder / "lift.schematix"
    shutil.copy(os.path.join(examples_dir, "lift_cylinder.schematix"), src)
    run("doc", "register", prj["id"], str(src), "--number", "D-1", "--title", "Lift", "-m", "first")

    client = rw.Client(rw.find_workspace(str(src)))
    sha = st.sha256(src.read_bytes())
    status = client.status(str(src), sha)
    assert status.managed and status.matched_label == "A" and status.file_state == "unchanged"
    assert "D-1 Rev A" in status.summary()
    # the bytes being simulated are no longer a checked-in revision
    assert client.status(str(src), "0" * 64).matched_label == ""
    # a study joins the schematic's project and goes through a full revision cycle
    study_path = folder / "lift.fluidworx"
    st.save(st.from_source(str(src)), str(study_path))
    assert not client.status(str(study_path)).managed
    client.register(status.project_id, str(study_path), "Lift simulation", "Created by test")
    s2 = client.status(str(study_path))
    assert s2.managed and s2.latest_label
    first_label = s2.latest_label
    client.checkout(s2.doc_id)
    assert client.status(str(study_path)).checked_out_by
    s = st.load(str(study_path))
    s.notes = "edited"
    st.save(s, str(study_path))
    client.checkin(s2.doc_id, "second")
    assert client.status(str(study_path)).latest_label != first_label


def test_revisionworx_failure_comes_back_as_its_own_message(tmp_path):
    _rwx_cmd()
    client = rw.Client(str(tmp_path))
    with pytest.raises(rw.RevisionWorxError):
        client.status(str(tmp_path / "x"))


def test_no_tool_is_not_an_error(monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", lambda n: None)
    monkeypatch.setattr(tools, "_module_available", lambda n: False)
    assert tools.find("caldera") is None
    assert tools.launch("caldera") is False
    client = rw.Client("/tmp")
    assert not client.available
    with pytest.raises(rw.RevisionWorxError, match="Preferences"):
        client.status("/tmp/x")


def test_report_contains_the_results(examples_dir):
    c, sim = _ran()
    s = st.from_source(os.path.join(examples_dir, "lift_cylinder.schematix"))
    html = report.html_report(s, c, sim, Units("metric"), c.project.sheets[0])
    assert "<svg" in html and "Measured strokes" in html and "160 bar" in html and s.source_sha256 in html
    times = report.cycle_times(sim)[next(p.key for p in c.parts if p.tag == "A1")]
    assert times["extend"] == pytest.approx(.3 * (3.14159 / 4 * .063 ** 2) / (12e-3 / 60), rel=0.05)


def test_csv_blocks_spreadsheet_formulas():
    c, sim = _ran()
    sim.log("=cmd()", "@bad")
    text = report.events_csv(sim)
    assert "'=cmd()" in text and "'@bad" in text
    assert report.trace_csv(sim, Units("us")).splitlines()[0].startswith("Time (s)")


def test_self_test_passes():
    r = subprocess.run([sys.executable, "-m", "fluidworx", "--self-test"], capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(__file__)))
    assert r.returncode == 0 and "PASSED" in r.stdout, r.stdout + r.stderr
