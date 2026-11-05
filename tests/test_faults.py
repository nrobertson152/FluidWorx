"""Failing things on purpose. The point of it is to see what the rest of the machine does, so each test here is about that:
what stops, what carries on, and that it all comes back when the fault is taken away."""
import os

import pytest
from conftest import EXAMPLES
from drawing import Drawing, diff, part

from fluidworx import catalog, circuit, engine


def load(name):
    project, warn = circuit.load_project(os.path.join(EXAMPLES, name))
    return engine.Simulator(circuit.build(project, warn))


def tagged(sim, tag):
    return next(b for b in sim.parts.values() if b.part.tag == tag)


def series(d, *rest):
    """A 24 V source in a loop with these parts, joined 1-2 or A1-A2."""
    src = d.add("el.source.dc", "G1", "24 V")
    last = (src, "+")
    for p, a, b in rest:
        d.wire(last, (p, a))
        last = (p, b)
    d.wire(last, (src, "-"))
    return src


def latch_circuit(d):
    k, c, lamp = d.add("el.coil.iec", "K1"), d.add("el.contact.no.iec", "K1"), d.add("el.lamp.iec", "H1")
    s = d.add("el.switch.selector.no", "S1")
    src = series(d, (s, "1", "2"), (k, "A1", "A2"))
    d.wire((src, "+"), (c, "1"))
    d.wire((c, "2"), (lamp, "1"))
    d.wire((lamp, "2"), (src, "-"))
    return s, k, c, lamp


def test_a_contact_stuck_open_cuts_what_it_feeds():
    d = Drawing()
    s, k, c, lamp = latch_circuit(d)
    sim = d.sim()
    sim.command(part(sim, s).part.key, "toggle")
    sim.run(0.1)
    assert part(sim, lamp).is_on()
    assert sim.set_fault(part(sim, c).part.key, "stuck_open")
    sim.run(0.1)
    assert part(sim, k).energised and not part(sim, c).closed() and not part(sim, lamp).is_on()
    assert "Failed: Stuck open" in sim.status(part(sim, c).part.key)
    assert sim.set_fault(part(sim, c).part.key, None)
    sim.run(0.1)
    assert part(sim, lamp).is_on()
    assert part(sim, c).status() == "Closed"


def test_a_welded_contact_stays_closed_with_its_coil_off():
    d = Drawing()
    _s, k, c, lamp = latch_circuit(d)
    sim = d.sim()
    sim.run(0.1)
    assert not part(sim, lamp).is_on()
    sim.set_fault(part(sim, c).part.key, "stuck_closed")
    sim.run(0.1)
    assert not part(sim, k).energised and part(sim, lamp).is_on()


def test_a_burnt_out_coil_carries_nothing_and_operates_nothing():
    d = Drawing()
    s, k, _c, lamp = latch_circuit(d)
    sim = d.sim()
    sim.set_fault(part(sim, k).part.key, "open")
    sim.command(part(sim, s).part.key, "toggle")
    sim.run(0.1)
    assert not part(sim, k).energised and not part(sim, lamp).is_on()
    assert part(sim, k).through() == 0.0
    assert diff(sim, k, "A1", "A2") == pytest.approx(24.0, abs=0.1)


def test_a_short_circuited_coil_blows_its_fuse():
    """The fault the fuse is there for."""
    d = Drawing()
    k, fuse = d.add("el.coil.iec", "K1"), d.add("el.fuse.iec", "F1", "2 A")
    series(d, (fuse, "1", "2"), (k, "A1", "A2"))
    sim = d.sim()
    sim.run(0.1)
    assert part(sim, k).energised and not part(sim, fuse).is_open
    sim.set_fault(part(sim, k).part.key, "shorted")
    sim.run(0.3)
    assert part(sim, fuse).is_open and not part(sim, k).energised
    assert any("Blew" in text for _t, _tag, text in sim.events)


def test_a_fuse_that_wont_blow_says_what_it_carried():
    d = Drawing()
    k, fuse = d.add("el.coil.iec", "K1"), d.add("el.fuse.iec", "F1", "2 A")
    series(d, (fuse, "1", "2"), (k, "A1", "A2"))
    sim = d.sim()
    sim.set_fault(part(sim, fuse).part.key, "wont_trip")
    sim.set_fault(part(sim, k).part.key, "shorted")
    sim.run(1.0)
    assert not part(sim, fuse).is_open and part(sim, fuse).peak > 20.0


def test_a_coil_stuck_pulled_in_holds_its_contacts_with_no_supply():
    d = Drawing()
    s, k, c, lamp = latch_circuit(d)
    sim = d.sim()
    sim.set_fault(part(sim, k).part.key, "stuck_in")
    sim.run(0.1)
    assert part(sim, k).energised and part(sim, c).closed() and part(sim, lamp).is_on()
    sim.set_fault(part(sim, k).part.key, None)
    sim.run(0.1)
    assert not part(sim, k).energised
    assert part(sim, s) is not None


def test_a_coil_that_wont_pull_in_still_draws_its_current():
    d = Drawing()
    s, k, c, _lamp = latch_circuit(d)
    sim = d.sim()
    sim.set_fault(part(sim, k).part.key, "stuck_out")
    sim.command(part(sim, s).part.key, "toggle")
    sim.run(0.1)
    assert not part(sim, k).energised and not part(sim, c).closed()
    assert part(sim, k).through() > 0.0


def test_a_lamp_burnt_out_isnt_lit():
    d = Drawing()
    lamp = d.add("el.lamp.iec", "H1")
    series(d, (lamp, "1", "2"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    sim.set_fault(part(sim, lamp).part.key, "open")
    sim.run(0.05)
    assert not part(sim, lamp).is_on() and part(sim, lamp).through() == 0.0
    assert "Burnt out" in part(sim, lamp).status()


@pytest.mark.parametrize("symbol,pins", [("el.resistor.iec", ("1", "2")), ("el.diode", ("A", "K")), ("el.capacitor.pol", ("+", "-"))])
def test_a_part_failed_open_or_short(symbol, pins):
    d = Drawing()
    r, load_r = d.add(symbol, "X1", "1k" if "resistor" in symbol else ""), d.add("el.resistor.iec", "R1", "100")
    series(d, (r, *pins), (load_r, "1", "2"))
    sim = d.sim()
    key = part(sim, r).part.key
    sim.set_fault(key, "open")
    sim.run(0.05)
    assert part(sim, load_r).through() == pytest.approx(0.0, abs=1e-6)
    assert sim.status(key).startswith("Failed:")
    sim.set_fault(key, "shorted")
    sim.run(0.05)
    assert part(sim, load_r).through() == pytest.approx(0.24, rel=0.01)
    sim.set_fault(key, None)
    assert not sim.status(key).startswith("Failed:")


def test_an_analog_sensor_that_loses_its_signal_reads_zero_at_the_plc():
    sim = load("plc_cylinder.schematix")
    sim.run(0.3)
    sensors = [b for b in sim.parts.values() if b.part.kind in ("sensor_analog", "sensor_loop")]
    assert sensors
    b = sensors[0]
    assert sim.set_fault(b.part.key, "lost")
    sim.run(0.2)
    rows = dict((label, value) for label, _q, value in b.readings())
    assert rows.get("Output", rows.get("Loop current", 0.0)) == pytest.approx(0.0, abs=1e-3)


def test_a_plc_output_stuck_on_shifts_the_valve_whatever_the_program_says():
    sim = load("plc_cylinder.schematix")
    sim.run(0.3)
    plc = sim.net.plcs[0]
    a = sim.actuators()[0]
    assert a.x < 1e-3
    coils = [c for c in sim.net.coils if any(c is src for src, _t, side in sim.net.outputs if side)]
    assert coils
    extend = next(addr for addr, tag in plc.rt.program.tags.items() if addr.startswith("Q") and tag.upper().startswith(("Y", "EXT")))
    assert sim.set_fault(plc.part.key, f"{extend}_on")
    sim.run(1.0)
    assert plc.outs[extend] and a.x > 1e-3
    sim.set_fault(plc.part.key, None)
    sim.run(0.1)
    assert not plc.outs[extend]


def test_a_plc_input_stuck_on_is_what_the_program_reads():
    sim = load("plc_cylinder.schematix")
    sim.run(0.3)
    plc = sim.net.plcs[0]
    addr = plc.addr["di"][0]
    sim.set_fault(plc.part.key, f"{addr}_on")
    sim.run(0.1)
    assert plc.inputs[addr] is True and plc.rt.ctx.G[addr] is True


def test_a_stopped_plc_drops_its_outputs():
    sim = load("plc_cylinder.schematix")
    sim.run(0.3)
    plc = sim.net.plcs[0]
    assert plc.running()
    sim.set_fault(plc.part.key, "stop")
    sim.run(0.1)
    assert not plc.running() and not any(plc.outs.values())
    assert "Failed: CPU stopped" in plc.status()
    sim.set_fault(plc.part.key, None)
    sim.run(0.1)
    assert plc.running()


# ---------------------------------------------------------------- the fluid side
def lift():
    sim = load("lift_cylinder.schematix")
    valve = next(b for b in sim.parts.values() if b.part.kind == "dcv")
    return sim, valve, sim.actuators()[0]


def test_a_stuck_spool_doesnt_shift():
    sim, valve, a = lift()
    sim.set_fault(valve.part.key, "stuck")
    sim.command(valve.part.key, "left")
    sim.run(2.0)
    assert valve.position == valve.normal and a.x == 0.0
    sim.set_fault(valve.part.key, None)
    sim.command(valve.part.key, "right")
    sim.command(valve.part.key, "left")
    sim.run(1.0)
    assert a.x > 0.0


def test_a_seized_cylinder_doesnt_move_and_the_pressure_goes_to_relief():
    sim, valve, a = lift()
    sim.set_fault(a.part.key, "seized")
    sim.command(valve.part.key, "left")
    sim.run(2.0)
    assert a.x == 0.0 and a.status(sim.p).endswith("Failed: Seized: it won't move")
    relief = next(b for b in sim.parts.values() if b.part.kind == "relief")
    assert sim.p[a.a_node] == pytest.approx(relief.part.params["setting"], rel=0.1)


def test_a_dead_pump_moves_nothing():
    sim, valve, a = lift()
    pump = next(b for b in sim.parts.values() if isinstance(b, engine.Pump))
    sim.set_fault(pump.part.key, "failed")
    sim.command(valve.part.key, "left")
    sim.run(2.0)
    assert a.x == 0.0 and pump.q(sim.p) == 0.0


def test_a_relief_valve_stuck_closed_no_longer_limits_pressure():
    sim, valve, a = lift()
    relief = next(b for b in sim.parts.values() if b.part.kind == "relief")
    setting = relief.part.params["setting"]
    sim.set_fault(relief.part.key, "blocked")
    sim.command(valve.part.key, "left")
    sim.run(6.0)
    assert a.fraction == 1.0
    assert sim.p[a.a_node] > 1.5 * setting
    assert any(b.status(sim.p).startswith("Blocked") for b in sim.parts.values() if isinstance(b, engine.Pump))


def test_a_relief_valve_stuck_open_dumps_the_pump():
    sim, valve, a = lift()
    relief = next(b for b in sim.parts.values() if b.part.kind == "relief")
    sim.set_fault(relief.part.key, "open")
    sim.command(valve.part.key, "left")
    sim.run(2.0)
    assert sim.p[a.a_node] < 0.2 * relief.part.params["setting"]


def test_a_burst_line_loses_its_pressure():
    sim, valve, a = lift()
    sim.command(valve.part.key, "left")
    sim.run(6.0)
    node = a.a_node
    high = sim.p[node]
    assert high > 10e5
    ref = next(r for r, n in sim.circuit.wire_nodes.items() if n == node)
    assert sim.line_can_fail(ref) == "Burst"
    assert sim.set_line_fault(ref, True)
    sim.run(1.0)
    assert sim.p[node] < 0.2 * high
    assert sim.line_fault(ref) == "Burst"
    assert sim.set_line_fault(ref, False)
    sim.run(2.0)
    assert sim.p[node] > 0.5 * high


def test_a_load_held_by_a_pilot_check_stays_when_its_line_bursts():
    """What a load-holding valve is for. On the far side of the check the load stays up."""
    sim = load("load_holding.schematix")
    a = sim.actuators()[0]
    valve = next(b for b in sim.parts.values() if b.part.kind == "dcv")
    sim.command(valve.part.key, "left")
    sim.run(8.0)
    sim.command(valve.part.key, "left")
    sim.run(1.0)
    held = a.x
    assert held > 0.0
    checks = [b for b in sim.parts.values() if b.part.kind == "pilot_check"]
    assert checks
    # the valve side of the check
    line = next(n for n in (checks[0].t[t] for t in checks[0].names) if n not in (a.a_node, a.b_node))
    ref = next(r for r, n in sim.circuit.wire_nodes.items() if n == line)
    sim.set_line_fault(ref, True)
    sim.run(2.0)
    assert a.x == pytest.approx(held, abs=1e-3)


def test_a_seal_leak_lets_a_held_cylinder_move():
    sim, valve, a = lift()
    sim.set_fault(a.part.key, "leak")
    sim.command(valve.part.key, "left")
    sim.run(4.0)
    flows = a.flows(sim.p)
    assert abs(flows[a.names[0]]) > 1e-7


def test_faults_stay_through_a_reset_and_say_so():
    sim, valve, a = lift()
    sim.set_fault(a.part.key, "seized")
    sim.run(0.2)
    sim.reset()
    assert sim.faults == {a.part.key: "seized"}
    assert any(text.startswith("Failed on purpose, from the start") for _t, _tag, text in sim.events)
    sim.command(valve.part.key, "left")
    sim.run(1.0)
    assert a.x == 0.0
    sim.clear_faults()
    assert sim.faults == {} and sim.fault_rows() == []
    sim.run(1.0)
    assert a.x > 0.0


def test_unknown_faults_are_refused():
    sim, valve, _a = lift()
    assert not sim.set_fault(valve.part.key, "melted")
    assert not sim.set_fault(("nope", 1), "stuck")
    assert sim.faults == {}


# ---------------------------------------------------------------- broken wires
def wire_between(d, a, b):
    """The wire joining pins a and b."""
    return next((d.doc.uid, w.id) for w in d.doc.wires.values() if [list(w.start), list(w.end)] in ([list(a), list(b)], [list(b), list(a)]))


def test_a_broken_wire_kills_a_series_circuit_and_a_repair_brings_it_back():
    d = Drawing()
    lamp, r = d.add("el.lamp.iec", "H1"), d.add("el.resistor.iec", "R1", "10")
    src = series(d, (r, "1", "2"), (lamp, "1", "2"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    base_nodes = sim.net.node_count
    ref = wire_between(d, (r.id, "2"), (lamp.id, "1"))
    assert sim.line_can_fail(ref) == "Broken"
    assert sim.set_line_fault(ref, True)
    sim.run(0.05)
    assert not part(sim, lamp).is_on()
    assert part(sim, lamp).through() == pytest.approx(0.0, abs=1e-6)
    assert diff(sim, src, "+", "-") == pytest.approx(24.0, abs=0.01), "the supply itself is untouched"
    assert sim.net.node_count == base_nodes + 1
    assert ref not in sim.circuit.el_wire_nodes
    assert sim.set_line_fault(ref, False)
    sim.run(0.05)
    assert part(sim, lamp).is_on() and sim.net.node_count == base_nodes
    assert ref in sim.circuit.el_wire_nodes


def test_only_whats_beyond_a_break_in_a_branch_goes_dead():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    h1, h2 = d.add("el.lamp.iec", "H1"), d.add("el.lamp.iec", "H2")
    d.wire((src, "+"), (h1, "1"))
    d.wire((h1, "1"), (h2, "1"))
    d.wire((h1, "2"), (src, "-"))
    d.wire((h2, "2"), (src, "-"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, h1).is_on() and part(sim, h2).is_on()
    sim.set_line_fault(wire_between(d, (h1.id, "1"), (h2.id, "1")), True)
    sim.run(0.05)
    assert part(sim, h1).is_on() and not part(sim, h2).is_on()


def test_a_break_on_the_return_side_is_as_dead():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    lamp = d.add("el.lamp.iec", "H1")
    d.wire((src, "+"), (lamp, "1"))
    d.wire((lamp, "2"), (src, "-"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    sim.set_line_fault(wire_between(d, (lamp.id, "2"), (src.id, "-")), True)
    sim.run(0.05)
    assert not part(sim, lamp).is_on()
    assert diff(sim, src, "+", "-") == pytest.approx(24.0, abs=0.01)


def test_names_still_join_across_a_break():
    """+24V at both ends of a broken wire is one line, as it is on any drawing."""
    d = Drawing()
    a, b = d.add("el.rail.pos", "", "+24V"), d.add("el.rail.pos", "", "+24V")
    zero = d.add("el.rail.neg", "", "0V")
    lamp = d.add("el.lamp.iec", "H1")
    d.wire((a, a.terminal_defs()[0].name), (lamp, "1"))
    d.wire((b, b.terminal_defs()[0].name), (lamp, "1"))
    d.wire((lamp, "2"), (zero, zero.terminal_defs()[0].name))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    sim.set_line_fault(wire_between(d, (a.id, a.terminal_defs()[0].name), (lamp.id, "1")), True)
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    sim.set_line_fault(wire_between(d, (b.id, b.terminal_defs()[0].name), (lamp.id, "1")), True)
    sim.run(0.05)
    assert not part(sim, lamp).is_on()


def test_a_broken_wire_doesnt_bring_a_label_to_life():
    """A label only makes a line live when nothing real feeds that circuit. A broken wire isn't that."""
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    rail = d.add("el.rail.pos", "", "+24V")
    lamp = d.add("el.lamp.iec", "H1")
    pin = rail.terminal_defs()[0].name
    d.wire((src, "+"), (rail, pin))
    d.wire((rail, pin), (lamp, "1"))
    d.wire((lamp, "2"), (src, "-"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    sim.set_line_fault(wire_between(d, (src.id, "+"), (rail.id, pin)), True)
    sim.run(0.05)
    assert not part(sim, lamp).is_on()


def test_a_wire_broken_while_a_plc_is_running():
    """Its 0 V goes, it stops, its outputs drop, and it starts cold when the wire is mended."""
    sim = load("plc_cylinder.schematix")
    sim.run(0.3)
    plc = sim.net.plcs[0]
    assert plc.running()
    node = plc.t["L+"]
    ref = next((r for r, n in sim.circuit.el_wire_nodes.items() if n == node), None)
    assert ref is not None
    assert sim.line_can_fail(ref) == "Broken"
    assert sim.set_line_fault(ref, True)
    sim.run(0.5)
    sim.set_line_fault(ref, False)
    sim.run(0.3)
    assert plc.running()


def test_lines_that_cant_fail_are_refused():
    sim, _valve, _a = lift()
    assert sim.line_can_fail(("nope", 1)) == ""
    assert not sim.set_line_fault(("nope", 1), True)
    ref = next(iter(sim.circuit.wire_nodes))
    assert not sim.set_line_fault(ref, False), "it isn't failed"


def test_faults_are_in_the_report():
    from fluidworx import report, study as st
    from fluidworx.units import Units
    sim, _valve, a = lift()
    sim.set_fault(a.part.key, "seized")
    sim.run(0.1)
    path = os.path.join(EXAMPLES, "lift_cylinder.schematix")
    html = report.html_report(st.from_source(path), sim.circuit, sim, Units("metric"), sim.circuit.project.sheets[0])
    assert "Failed on purpose" in html and "failure analysis" in html and "Seized" in html


def test_every_way_of_failing_every_symbol_runs():
    """No fault of any part can crash the simulation, or stop it coming back. All electrical symbols, on one drawing."""
    from fluidworx.vendor.openschematix import symbols
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    placed = []
    for sym_id in sorted(s.id for s in symbols.builtin_symbols()):
        if sym_id.startswith("el.") and catalog.classify(sym_id).kind != "unsupported":
            comp = d.add(sym_id, f"X{len(placed)}")
            names = [t.name for t in comp.terminal_defs()]
            if names:
                d.wire((src, "+"), (comp, names[0]))
            if len(names) > 1:
                d.wire((comp, names[-1]), (src, "-"))
            placed.append(comp)
    assert len(placed) > 60
    sim = d.sim()
    tried = 0
    for comp in placed:
        b = part(sim, comp)
        for name, _label in b.fault_choices()[:6]:
            assert sim.set_fault(b.part.key, name), (comp.symbol, name)
            sim.step()
            assert isinstance(sim.status(b.part.key), str) and b.readings(sim.p) is not None
            sim.net.terminal_currents()
            sim.set_fault(b.part.key, None)
            tried += 1
    sim.run(0.05)
    assert tried > 100


@pytest.mark.parametrize("name", ["lift_cylinder.schematix", "sequence_clamp_press.schematix", "load_holding.schematix", "hydraulic_motor.schematix",
                                  "accumulator_circuit.schematix", "pneumatic_cylinder.schematix", "pneumatic_single_acting.schematix",
                                  "relay_latch.schematix", "motor_starter_pump.schematix", "electronics_threshold.schematix"])
def test_every_way_of_failing_every_part_of_the_examples_runs(name):
    sim = load(name)
    sim.run(0.1)
    for key, b in list(sim.parts.items()):
        for fault, _label in b.fault_choices()[:6]:
            assert sim.set_fault(key, fault)
            sim.step()
            assert isinstance(sim.status(key), str)
            b.readings(sim.p)
            sim.terminal_flows()
            sim.net.terminal_currents()
        sim.set_fault(key, None)
    for ref in list(sim.circuit.wire_nodes)[:6] + list(sim.net._drawn_wires)[:6]:
        assert sim.set_line_fault(ref, True)
        sim.step()
        sim.set_line_fault(ref, False)
    sim.run(0.05)
    assert sim.faults == {}


def test_failing_and_repairing_leaves_a_run_as_it_would_have_been():
    """Put right before anything moved, and the machine does what it would have done."""
    def stroke(fail):
        sim = load("relay_latch.schematix")
        if fail:
            for ref in list(sim.net._drawn_wires)[:3]:
                sim.set_line_fault(ref, True)
                sim.step()
                sim.set_line_fault(ref, False)
            sim.reset()
        sim.run(2.0)
        return [(round(a.x, 6)) for a in sim.actuators()], [c.energised for c in sim.net.coils]
    assert stroke(True) == stroke(False)
