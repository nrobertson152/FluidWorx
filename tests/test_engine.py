"""Behaviour checked against hand calculations and against what these circuits are known to do."""
import math

import pytest
from conftest import by_tag, load, run_example

from fluidworx import engine

L_MIN = 1e-3 / 60


def valve(sim, tag="V1"):
    return by_tag(sim, tag).part.key


def test_extend_speed_is_flow_over_area():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "left")
    sim.run(2.0)
    a1 = by_tag(sim, "A1")
    assert a1.v == pytest.approx(12 * L_MIN / (math.pi / 4 * 0.063 ** 2), rel=0.01)
    assert a1.status(sim.p) == "Extending"


def test_retract_speed_uses_the_annulus():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "right")
    a1 = by_tag(sim, "A1")
    a1.x = 0.3
    sim.touch()
    sim.run(1.0)
    annulus = math.pi / 4 * (0.063 ** 2 - 0.036 ** 2)
    assert a1.v == pytest.approx(-12 * L_MIN / annulus, rel=0.01)


def test_stroke_time_and_end_stop():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "left")
    a1 = by_tag(sim, "A1")
    expected = 0.3 * (math.pi / 4 * 0.063 ** 2) / (12 * L_MIN)
    sim.run(expected * 0.95)
    assert a1.x < 0.3
    sim.run(expected * 0.1 + 0.2)
    assert a1.x == pytest.approx(0.3)
    assert a1.status(sim.p) == "Fully extended"


def test_relief_valve_limits_pressure_and_takes_all_flow():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "left")
    sim.run(6.0)
    v2 = by_tag(sim, "V2")
    assert v2.status(sim.p) == "Relieving"
    assert sim.p[by_tag(sim, "P1").t["P"]] == pytest.approx(160e5, rel=0.01)
    assert v2.seat.q(sim.p) == pytest.approx(12 * L_MIN, rel=0.02)


def test_tandem_centre_unloads_the_pump_and_holds_the_cylinder():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "left")
    sim.run(2.0)
    sim.command(valve(sim), "left")     # back to centre
    x = by_tag(sim, "A1").x
    sim.run(1.0)
    assert sim.p[by_tag(sim, "P1").t["P"]] < 2e5
    assert by_tag(sim, "A1").x == pytest.approx(x, abs=1e-3)
    assert by_tag(sim, "V2").status(sim.p) == "Closed"


def test_load_sets_pressure():
    c, sim = run_example("lift_cylinder.schematix")
    a1 = by_tag(sim, "A1")
    a1.part.params["load"] = 20000.0
    sim.command(valve(sim), "left")
    sim.run(1.0)
    bore = math.pi / 4 * 0.063 ** 2
    expected = 20000 / bore
    assert expected < sim.p[a1.a_node] < expected + 8e5     # load + breakaway + drag


def test_load_above_relief_does_not_move():
    _c, sim = run_example("lift_cylinder.schematix")
    a1 = by_tag(sim, "A1")
    a1.part.params["load"] = 200000.0        # needs far more than 160 bar on this bore
    sim.command(valve(sim), "left")
    sim.run(2.0)
    assert a1.x == 0.0
    assert by_tag(sim, "V2").status(sim.p) == "Relieving"


def test_sequence_valve_runs_clamp_first_and_holds_its_pressure():
    _c, sim = run_example("sequence_clamp_press.schematix")
    a1, a2 = by_tag(sim, "A1"), by_tag(sim, "A2")
    sim.command(valve(sim), "left")
    while a1.x < a1.travel() and sim.time < 5:
        sim.run(0.05)
        assert a2.x == 0.0, "press moved before the clamp finished"
    sim.run(0.5)
    assert a2.v > 0
    assert sim.p[a1.a_node] >= 60e5 * 0.98, "clamp pressure must stay at the sequence setting while the press moves"
    sim.run(6.0)
    assert a2.x == pytest.approx(a2.travel())


def test_sequence_check_bypass_lets_the_press_return():
    _c, sim = run_example("sequence_clamp_press.schematix")
    sim.command(valve(sim), "left")
    sim.run(5.0)
    sim.command(valve(sim), "right")
    sim.run(8.0)
    assert by_tag(sim, "A1").x == 0.0 and by_tag(sim, "A2").x == 0.0


def test_pilot_check_holds_a_hanging_load_then_lowers_it_when_piloted():
    _c, sim = run_example("load_holding.schematix")
    a1, v3 = by_tag(sim, "A1"), by_tag(sim, "V3")
    sim.command(valve(sim), "left")
    sim.run(4.0)
    x = a1.x
    assert x > 0.1
    sim.command(valve(sim), "left")     # centre: float, A and B vented
    sim.run(5.0)
    assert a1.x == pytest.approx(x, abs=2e-3), "load must not drift with the check closed"
    assert sim.p[a1.a_node] == pytest.approx(8000 / (math.pi / 4 * .063 ** 2), rel=0.2)
    sim.command(valve(sim), "right")
    sim.run(2.0)
    assert a1.x < x - 0.02 and v3.piloted


def test_float_centre_without_a_pilot_check_would_drop_the_load():
    """Same circuit, pilot check removed from the picture by opening it: proves the test above means something."""
    _c, sim = run_example("load_holding.schematix")
    a1, v3 = by_tag(sim, "A1"), by_tag(sim, "V3")
    sim.command(valve(sim), "left")
    sim.run(4.0)
    sim.command(valve(sim), "left")
    v3._pilot_state = lambda p: True
    x = a1.x
    sim.run(2.0)
    assert a1.x < x - 0.005


def test_meter_out_slows_only_the_metered_direction():
    _c, sim = run_example("hydraulic_motor.schematix")
    m1 = by_tag(sim, "M1")
    sim.command(valve(sim), "left")
    sim.run(2.0)
    metered = m1.v
    sim.command(valve(sim), "right")
    sim.run(2.0)
    free = m1.v
    full = 25 * L_MIN / (32e-6 / (2 * math.pi))
    assert free == pytest.approx(-full, rel=0.01)
    assert 0 < metered < 0.6 * full
    assert by_tag(sim, "V2").status(sim.p) == "Closed"


def test_opening_a_flow_control_speeds_it_up():
    _c, sim = run_example("hydraulic_motor.schematix")
    m1, v3 = by_tag(sim, "M1"), by_tag(sim, "V3")
    sim.command(valve(sim), "left")
    sim.run(1.5)
    slow = m1.v
    v3.part.params["opening"] = 60.0
    sim.touch()
    sim.run(1.5)
    assert m1.v > slow * 1.5


def test_accumulator_stores_above_precharge_and_drives_a_stroke():
    _c, sim = run_example("accumulator_circuit.schematix")
    z2, p1 = by_tag(sim, "Z2"), by_tag(sim, "P1")
    sim.run(20.0)
    assert sim.p[z2.node(0)] == pytest.approx(160e5, rel=0.02)
    stored = z2._stored(sim.p)
    assert stored == pytest.approx(2e-3 * (1 - (80e5 + 101325) / (160e5 + 101325)), rel=0.03)
    # pump off: the stored oil alone still moves the cylinder
    sim.command(p1.part.key, "toggle")
    sim.command(valve(sim), "left")
    sim.run(2.0)
    a1 = by_tag(sim, "A1")
    assert a1.x > 0.05
    assert sim.p[z2.node(0)] < 160e5 * 0.98


def test_shutoff_drains_the_accumulator():
    _c, sim = run_example("accumulator_circuit.schematix")
    z2, v4 = by_tag(sim, "Z2"), by_tag(sim, "V4")
    sim.run(5.0)
    assert sim.p[z2.node(0)] > 80e5
    sim.command(v4.part.key, "toggle")
    sim.run(3.0)
    assert sim.p[z2.node(0)] < 2e5


def test_stopping_the_pump_stops_the_cylinder():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "left")
    sim.run(1.0)
    sim.command(by_tag(sim, "P1").part.key, "toggle")
    sim.run(0.5)
    x = by_tag(sim, "A1").x
    sim.run(1.0)
    assert by_tag(sim, "A1").x == pytest.approx(x, abs=1e-4)


def test_pneumatic_double_acting_cycle():
    _c, sim = run_example("pneumatic_cylinder.schematix")
    a1 = by_tag(sim, "A1")
    sim.run(1.0)
    assert a1.x == 0.0
    assert sim.p[a1.b_node] > 1e5         # spring position pressurises the rod end
    sim.command(valve(sim), "left")
    sim.run(6.0)
    assert a1.x == pytest.approx(a1.travel())
    assert sim.p[a1.a_node] == pytest.approx(5e5, rel=0.05)     # regulator setting from the drawing
    sim.command(valve(sim), "left")
    sim.run(8.0)
    assert a1.x == 0.0


def test_pneumatic_regulator_and_vented_exhaust():
    c, sim = run_example("pneumatic_cylinder.schematix")
    v1 = by_tag(sim, "V1")
    assert v1.t["5"] in c.fixed and v1.t["3"] in c.fixed      # unpiped exhausts vent
    sim.run(3.0)
    assert sim.p[by_tag(sim, "V4").t["2"]] == pytest.approx(5e5, rel=0.05)


def test_single_acting_spring_return():
    _c, sim = run_example("pneumatic_single_acting.schematix")
    a1 = by_tag(sim, "A1")
    sim.command(valve(sim), "left")
    sim.run(3.0)
    assert a1.x == pytest.approx(a1.travel())
    sim.command(valve(sim), "left")
    sim.run(3.0)
    assert a1.x == 0.0


def test_two_position_valve_position_rules():
    _c, sim = run_example("pneumatic_cylinder.schematix")
    v1 = by_tag(sim, "V1")
    assert v1.position == v1.normal == 1              # spring on the right holds the right-hand envelope
    assert not v1.side_can_actuate("right")
    sim.command(v1.part.key, "left")
    assert v1.position == 0
    sim.command(v1.part.key, "left")
    assert v1.position == 1


def test_valve_patterns_connect_the_ports_their_labels_say():
    from fluidworx.vendor.openschematix.symbols.fluid import LAYOUTS, PATTERNS
    expect = {"parallel": {("P", "A"), ("B", "T")}, "crossed": {("P", "B"), ("A", "T")}, "tandem": {("P", "T")},
              "closed": set(), "float": {("A", "T"), ("B", "T")}, "ab-pt": {("A", "B"), ("P", "T")}}
    layout = [x[0] for x in LAYOUTS[("hyd", 4)]]
    for name, want in expect.items():
        pat = PATTERNS[4][name]
        pairs = [tuple(sorted((layout[a], layout[b]))) for a, b in pat.get("arrows", [])]
        pairs += [tuple(sorted((layout[a], layout[b]))) for a, b in engine._SPECIALS.get(pat.get("special"), [])]
        assert set(pairs) == {tuple(sorted(w)) for w in want}, name


def test_every_flow_is_conserved():
    """What enters each free node must leave it once the circuit has settled."""
    for name in ("lift_cylinder.schematix", "sequence_clamp_press.schematix", "hydraulic_motor.schematix"):
        c, sim = run_example(name)
        sim.command(valve(sim), "left")
        sim.run(1.5)
        flows = sim.terminal_flows()
        balance = {}
        for ref, q in flows.items():
            node = c.term_nodes.get(ref)
            if node is not None and node not in c.fixed:
                balance[node] = balance.get(node, 0.0) + q
        for node, q in balance.items():
            assert abs(q) < 1e-6, f"{name}: node {node} imbalance {q}"


def test_reset_restores_the_start():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "left")
    sim.run(2.0)
    sim.reset()
    a1 = by_tag(sim, "A1")
    assert a1.x == 0.0 and sim.time == 0.0 and not sim.events and by_tag(sim, "V1").position == by_tag(sim, "V1").normal
    assert max(abs(p) for p in sim.p) == 0.0


def test_settled_circuit_stops_solving_but_time_runs():
    _c, sim = run_example("lift_cylinder.schematix")
    sim.run(1.0)
    n = sim._solves
    sim.run(1.0)
    assert sim._solves == n
    assert sim.time == pytest.approx(2.0)


def test_end_of_stroke_is_not_mistaken_for_settled():
    """Regression: the step a cylinder stopped looked settled, and pressure never rose to the relief setting."""
    _c, sim = run_example("lift_cylinder.schematix")
    sim.command(valve(sim), "left")
    sim.run(6.0)
    assert sim.p[by_tag(sim, "A1").a_node] > 150e5


def test_dead_headed_fixed_pump_without_relief_stalls_at_the_ceiling():
    from fluidworx import circuit
    from fluidworx.vendor.openschematix.model import Component, Wire
    from fluidworx.vendor.openschematix.project import new_project
    p = new_project(title="x")
    d = p.sheets[0]
    d.components[1] = Component(id=1, symbol="fl.hyd.pump", x=100, y=100, designator="P1")
    d.components[2] = Component(id=2, symbol="fl.hyd.tank", x=100, y=160, designator="Z1")
    d.components[3] = Component(id=3, symbol="fl.hyd.gauge", x=100, y=40, designator="S1")
    t = d.components[1].terminals()
    d.wires[4] = Wire(id=4, points=[t["S"], d.components[2].terminals()["T"]], start=[1, "S"], end=[2, "T"])
    d.wires[5] = Wire(id=5, points=[t["P"], d.components[3].terminals()["P"]], start=[1, "P"], end=[3, "P"])
    c = circuit.build(p)
    assert any("no relief" in i.text for i in c.issues)
    sim = engine.Simulator(c)
    sim.run(2.0)
    assert sim.p[c.parts[0].terms["P"]] <= 701e5
    assert sim.status(c.parts[0].key).startswith("Blocked")


def test_every_example_runs_a_full_cycle_without_nonsense():
    import glob
    import os
    from conftest import EXAMPLES
    for f in glob.glob(os.path.join(EXAMPLES, "*.schematix")):
        c, sim = run_example(f)
        assert not [i for i in c.issues if i.level != "info"], f
        k = next((k for k, b in sim.parts.items() if b.part.kind == "dcv"), None)
        for side in ("left", "left", "right", "right"):
            if k is not None and sim.parts[k].side_can_actuate(side):
                sim.command(k, side)
            sim.run(3.0)
            assert all(math.isfinite(p) for p in sim.p), f
            assert all(p >= -1.05e5 and p < 1000e5 for p in sim.p), f"{f}: {[round(x / 1e5) for x in sim.p]}"
            assert all(abs(v) < 1e4 for v in sim.net.v), f"{f}: {sim.net.v}"


def test_wires_in_examples_are_orthogonal_and_attached():
    import glob
    import os
    from conftest import EXAMPLES
    from fluidworx.vendor.openschematix.connectivity import analyse
    for f in glob.glob(os.path.join(EXAMPLES, "*.schematix")):
        c = load(f)
        for d in c.project.sheets:
            for w in d.wires.values():
                for a, b in zip(w.points, w.points[1:]):
                    assert a[0] == b[0] or a[1] == b[1], f"{f}: wire {w.id} is diagonal"
            conn = analyse(d)
            assert not conn.open_wire_ends, f"{f}: {conn.open_wire_ends}"
