import pytest
from conftest import EXAMPLES, load

from fluidworx import circuit, engine, study
from fluidworx.flowpaths import FlowPaths


def test_label_values_become_parameters():
    c = load("lift_cylinder.schematix")
    parts = {p.tag: p for p in c.parts}
    assert parts["V2"].params["setting"] == pytest.approx(160e5)
    assert parts["P1"].params["flow"] == pytest.approx(12e-3 / 60)
    assert parts["A1"].params["bore"] == pytest.approx(.063)
    assert parts["A1"].params["stroke"] == pytest.approx(.3)
    assert "setting" in parts["V2"].from_schematic


def test_properties_become_parameters():
    c = load("load_holding.schematix")
    a1 = next(p for p in c.parts if p.tag == "A1")
    assert a1.params["load"] == 8000.0 and a1.params["load_mode"] == 1.0


def test_a_bad_property_is_ignored():
    c = load("lift_cylinder.schematix")
    p = c.parts[0]
    p.comp.props["bore"] = "not a number"
    circuit._params_from_schematic(p)


def test_tanks_are_fixed_nodes():
    c = load("lift_cylinder.schematix")
    for p in c.parts:
        if p.kind == "tank":
            assert p.terms["T"] in c.fixed


def test_non_fluid_file_refused(tmp_path):
    f = tmp_path / "x.schematix"
    f.write_bytes(b"this is not a project")
    with pytest.raises(circuit.CircuitError):
        circuit.load_project(str(f))


def test_truncated_project_refused(tmp_path, examples_dir):
    data = open(f"{examples_dir}/lift_cylinder.schematix", "rb").read()
    f = tmp_path / "t.schematix"
    f.write_bytes(data[: len(data) // 2])
    with pytest.raises(circuit.CircuitError):
        circuit.load_project(str(f))


def test_legacy_osch_and_multisheet_project_from_openschematix():
    """The two files OpenSchematix ships, copied unchanged into tests/data."""
    import os
    data = os.path.join(os.path.dirname(__file__), "data")
    c = load(os.path.join(data, "hydraulic_cylinder_circuit.osch"))
    assert len(c.parts) == 9
    sim = engine.Simulator(c)
    sim.command(next(k for k, b in sim.parts.items() if b.part.kind == "dcv"), "left")
    sim.run(4.0)
    assert sim.actuators()[0].fraction == 1.0
    d = load(os.path.join(data, "demo_project.schematix"))
    assert len(d.sheets) == 1 and len(d.skipped_sheets) == 2      # electrical sheets aren't simulated, and say so
    assert any("24 V supply" in i.text for i in d.issues)


def test_sheet_connectors_join_a_line_across_sheets():
    from fluidworx.vendor.openschematix.model import Component, Wire
    from fluidworx.vendor.openschematix.project import new_project
    p = new_project(title="x")
    d1 = p.sheets[0]
    d2 = p.add_sheet("Two") if hasattr(p, "add_sheet") else None
    assert d2 is not None
    d1.components[1] = Component(id=1, symbol="fl.hyd.pump", x=100, y=100, designator="P1")
    d1.components[2] = Component(id=2, symbol="gen.offpage", x=100, y=20, label="LINE-A")
    d2.components[1] = Component(id=1, symbol="gen.offpage", x=100, y=20, label="LINE-A")
    d2.components[2] = Component(id=2, symbol="fl.hyd.gauge", x=100, y=100, designator="S1")
    a = d1.components[1].terminals()["P"]
    b = list(d1.components[2].terminals().values())[0]
    n1 = list(d1.components[2].terminals())[0]
    d1.wires[3] = Wire(id=3, points=[a, (a[0], b[1])] if a[0] == b[0] else [a, (a[0], b[1]), b], start=[1, "P"], end=[2, n1])
    a2 = list(d2.components[1].terminals().values())[0]
    n2 = list(d2.components[1].terminals())[0]
    g = d2.components[2].terminals()["P"]
    d2.wires[3] = Wire(id=3, points=[a2, (a2[0], g[1])] if a2[0] == g[0] else [a2, (a2[0], g[1]), g], start=[1, n2], end=[2, "P"])
    c = circuit.build(p)
    pump = next(x for x in c.parts if x.tag == "P1")
    gauge = next(x for x in c.parts if x.tag == "S1")
    assert pump.terms["P"] == gauge.terms["P"]
    assert len(c.sheets) == 2


def test_custom_fluid_symbol_is_warned_about_not_guessed():
    from fluidworx import catalog
    assert catalog.classify("user:my-valve").kind == "unsupported"
    assert catalog.classify("el.coil.iec").kind == "unsupported"


def test_study_params_overlay(examples_dir):
    c = load("lift_cylinder.schematix")
    p = next(x for x in c.parts if x.tag == "V2")
    circuit.apply_study_params(c, {study.part_id(p.key): {"setting": 99e5, "nonsense": 1.0}})
    assert p.params["setting"] == 99e5 and "nonsense" not in p.params
    assert p.base_params["setting"] == 160e5


def test_flow_follows_branches_and_dead_legs_show_none():
    c = load("lift_cylinder.schematix")
    sim = engine.Simulator(c)
    fp = FlowPaths(c)
    sim.command(next(k for k, b in sim.parts.items() if b.part.kind == "dcv"), "left")
    sim.run(1.0)
    flows = fp.compute(sim.terminal_flows())
    doc = c.project.sheets[0]
    q = 12e-3 / 60
    gauge = next(p for p in c.parts if p.tag == "S1")
    gauge_wire = next(w for w in doc.wires.values() if w.start and w.start[0] == gauge.comp.id)
    gauge_flows = [abs(f) for s, f in zip(fp.segments, flows) if s[1] == gauge_wire.id]
    assert gauge_flows and max(gauge_flows) < 1e-7, "a gauge line carries no flow"
    pump = next(p for p in c.parts if p.tag == "P1")
    pump_wire = next(w for w in doc.wires.values() if w.start == [pump.comp.id, "P"])
    pump_flows = [abs(f) for s, f in zip(fp.segments, flows) if s[1] == pump_wire.id]
    assert max(pump_flows) == pytest.approx(q, rel=0.02)


def test_flow_direction_runs_from_pump_to_valve():
    c = load("lift_cylinder.schematix")
    sim = engine.Simulator(c)
    fp = FlowPaths(c)
    sim.command(next(k for k, b in sim.parts.items() if b.part.kind == "dcv"), "left")
    sim.run(1.0)
    flows = fp.compute(sim.terminal_flows())
    doc = c.project.sheets[0]
    pump = next(p for p in c.parts if p.tag == "P1")
    w = next(w for w in doc.wires.values() if w.start == [pump.comp.id, "P"])
    first = next(i for i, s in enumerate(fp.segments) if s[1] == w.id)
    assert flows[first] > 0      # the wire starts at the pump, so outward flow is positive


assert EXAMPLES
