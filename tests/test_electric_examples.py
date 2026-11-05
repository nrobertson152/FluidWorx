"""The electrical examples do what their titles say, against what was worked out by hand."""
import pytest
from conftest import run_example


def tag(sim, name):
    return next(b for b in sim.parts.values() if b.part.tag == name)


def tags(sim, name):
    return [b for b in sim.parts.values() if b.part.tag == name]


def press(sim, name, seconds=0.1):
    key = tag(sim, name).part.key
    sim.command(key, "press")
    sim.run(seconds)
    sim.command(key, "release")


def until(sim, test, limit):
    t0 = sim.time
    while not test():
        assert sim.time - t0 < limit, "never happened"
        sim.step()
    return sim.time - t0


def test_plc_cylinder_goes_out_and_back_on_its_own():
    c, sim = run_example("plc_cylinder.schematix")
    assert not [i for i in c.issues if i.level != "info"], c.issues
    sim.run(0.2)
    plc, cyl = tag(sim, "PLC1"), tag(sim, "A1")
    assert plc.status() == "Run" and plc.inputs["I1"], "powered, and it can see the rod is home"
    press(sim, "S0")
    # 10 L/min into 50 mm bore: 85 mm/s, 2.36 s for 200 mm
    t = until(sim, lambda: cyl.x >= 0.197, 5.0)
    assert t + 0.1 == pytest.approx(0.2 / (10e-3 / 60 / (3.14159 / 4 * 0.05 ** 2)), rel=0.08)
    assert tag(sim, "H1").is_on(), "the Moving lamp is on"
    # back into the annulus, 1348 mm2: 124 mm/s, 1.62 s
    t = until(sim, lambda: cyl.x <= 0.003, 5.0)
    assert t == pytest.approx(0.2 / (10e-3 / 60 / (3.14159 / 4 * (0.05 ** 2 - 0.028 ** 2))), rel=0.08)
    sim.run(0.1)
    assert not plc.outs["Q0"] and not plc.outs["Q1"] and not tag(sim, "H1").is_on()
    assert not [text for _t, _tag, text in sim.events if "carrying" in text], "its 10 W coils are within the outputs' rating"


def test_plc_cylinder_e_stop_takes_the_plc_down():
    _c, sim = run_example("plc_cylinder.schematix")
    sim.run(0.2)
    press(sim, "S0")
    sim.run(0.5)
    plc, cyl, y1a = tag(sim, "PLC1"), tag(sim, "A1"), tag(sim, "Y1a")
    assert y1a.energised and cyl.dir == 1
    sim.command(tag(sim, "S9").part.key, "toggle")
    sim.run(0.2)
    assert plc.status() == "No supply" and not y1a.energised
    x = cyl.x
    sim.run(1.0)
    assert cyl.x == pytest.approx(x, abs=1e-4), "the valve centres and the rod stays where it is"
    sim.command(tag(sim, "S9").part.key, "toggle")
    sim.run(1.0)
    assert plc.status() == "Run"
    assert not y1a.energised, "a cold start: it doesn't remember it was extending"


def test_plc_cylinder_feeds_pressure_back():
    """A load of 18 kN needs 92 bar on a 50 mm bore: over the program's 90 bar, so it turns round without getting there."""
    _c, sim = run_example("plc_cylinder.schematix")
    tag(sim, "A1").part.params["load"] = 18000.0
    sim.touch()
    sim.run(0.2)
    press(sim, "S0", 0.3)
    plc = tag(sim, "PLC1")
    sim.run(1.3)
    assert plc.rt.read("Extending") is False
    assert tag(sim, "A1").x < 0.02


def test_relay_latch_dwells_then_comes_back():
    c, sim = run_example("relay_latch.schematix")
    assert not [i for i in c.issues if i.level != "info"], c.issues
    sim.run(0.2)
    cyl, k1, ya, yb, lamp = tag(sim, "A1"), next(b for b in tags(sim, "K1") if b.part.kind == "coil"), tag(sim, "Y1a"), tag(sim, "Y1b"), tag(sim, "H1")
    assert cyl.x == 0.0 and not k1.energised
    press(sim, "S1")
    assert k1.energised and ya.energised and not yb.energised and lamp.is_on()
    until(sim, lambda: cyl.x >= 0.1485, 10.0)
    assert k1.energised, "it holds itself in after the button is let go"
    dwell = until(sim, lambda: not k1.energised, 3.0)
    assert dwell == pytest.approx(1.0, abs=0.1), "KT1 holds it at the end for its 1 s"
    assert yb.energised and not ya.energised
    until(sim, lambda: cyl.x <= 0.0015, 10.0)
    sim.run(0.05)
    assert not yb.energised and not lamp.is_on(), "home again: the NC home switch drops Y1b"


def test_relay_latch_stop_button_ends_the_cycle_at_once():
    _c, sim = run_example("relay_latch.schematix")
    sim.run(0.2)
    press(sim, "S1")
    sim.run(0.05)
    press(sim, "S0")
    k1, yb = next(b for b in tags(sim, "K1") if b.part.kind == "coil"), tag(sim, "Y1b")
    assert not k1.energised and yb.energised
    sim.run(5.0)
    assert not k1.energised, "and it doesn't start again on its own"


def test_motor_starter_runs_the_pump_and_feeds_pressure_back():
    c, sim = run_example("motor_starter_pump.schematix")
    assert not [i for i in c.issues if i.level != "info"], c.issues
    sim.run(0.5)
    pump, motor = tag(sim, "P1"), tag(sim, "M1")
    assert not motor.running and not pump.running and sim.p[pump.t["P"]] < 1e5
    press(sim, "S1")
    assert motor.running and pump.running and tag(sim, "H1").is_on()
    sim.run(1.0)
    assert sim.p[pump.t["P"]] == pytest.approx(100e5, rel=0.05)
    assert tag(sim, "H2").is_on(), "pressure switch S3 at 80 bar lights Pressure OK"
    # 10 L/min at 100 bar through an 85% pump: 1961 W. At 400 V: 2.83 A
    assert max(abs(i) for i in motor.currents(sim.net.v).values()) == pytest.approx(2.83, rel=0.03)
    press(sim, "S0")
    assert not motor.running and not pump.running and not tag(sim, "H1").is_on()
    sim.run(1.0)
    assert tag(sim, "H2").is_on() == (sim.p[pump.t["P"]] > 76e5), "the switch follows the pressure, with its 5% hysteresis"


def test_motor_starter_overload_stops_it_and_it_stays_stopped():
    """Set the overload to 1 A against 2.83 A: (2.83^2 - 1.1) a second, 400 of it, in about 58 s."""
    _c, sim = run_example("motor_starter_pump.schematix")
    overload = next(b for b in tags(sim, "F1") if b.part.kind == "overload")
    overload.part.params["rating"] = 1.0
    sim.touch()
    sim.run(0.2)
    press(sim, "S1")
    sim.run(1.0)
    t = until(sim, lambda: overload.tripped, 90.0)
    assert t == pytest.approx(400.0 / (2.83 ** 2 - 1.1), rel=0.1)
    sim.run(0.05)
    motor, pump = tag(sim, "M1"), tag(sim, "P1")
    assert not motor.running and not pump.running and tag(sim, "H3").is_on(), "stopped, with the Overload lamp lit"
    sim.command(overload.part.key, "reset")
    sim.run(0.1)
    assert not motor.running and not tag(sim, "H3").is_on(), "reset, but the latch has gone: it needs Start"
    press(sim, "S1")
    assert motor.running


def test_motor_starter_breaker_cuts_a_phase_and_the_rest():
    _c, sim = run_example("motor_starter_pump.schematix")
    sim.run(0.2)
    press(sim, "S1")
    sim.run(0.2)
    motor = tag(sim, "M1")
    assert motor.running
    sim.command(tag(sim, "Q1").part.key, "toggle")
    sim.run(0.1)
    assert not motor.running and not motor.lost_phase, "all three poles open together"
    assert tag(sim, "K1").status() in ("Closed", "Energised"), "the control circuit has its own supply, so K1 stays in"


def test_electronics_comparator_switches_the_relay():
    """R1 sets + against R2 and R3, which put 12 x 10 / 14.7 = 8.16 V on -. At 50%, + is 6 V: off. At 20%, + is 9.6 V: on."""
    c, sim = run_example("electronics_threshold.schematix")
    assert not [i for i in c.issues if i.level != "info"], c.issues
    sim.run(0.1)
    u1, q1, coil, led = tag(sim, "U1"), tag(sim, "Q1"), next(b for b in tags(sim, "K1") if b.part.kind == "coil"), tag(sim, "H1")
    assert sim.net.v[u1.t["-"]] == pytest.approx(12.0 * 10 / 14.7, abs=0.02)
    assert sim.net.v[u1.t["+"]] == pytest.approx(6.0, abs=0.02)
    assert q1.mode == "off" and not coil.energised and not led.is_on()
    tag(sim, "R1").par["wiper"] = 20.0
    sim.touch()
    sim.run(0.1)
    assert sim.net.v[u1.t["+"]] == pytest.approx(9.6, abs=0.02)
    assert sim.net.v[u1.t["OUT"]] == pytest.approx(10.4, abs=0.02), "1.5 V below its supply, less 9.7 mA through its 10 ohm"
    assert q1.mode == "sat" and coil.energised, "9.7 mA in the base is plenty for 164 mA in the collector"
    assert coil.through() == pytest.approx((12.0 - 0.2) / 72.0, rel=0.02)
    assert led.is_on() and led.through() == pytest.approx((12.0 - 2.0) / 1010.0, abs=1e-4)
    tag(sim, "R1").par["wiper"] = 50.0
    sim.touch()
    sim.run(0.1)
    assert not coil.energised and not led.is_on()
    assert tag(sim, "D1").status() == "Blocking", "the flyback diode only blocks here: a coil is a plain resistance"
