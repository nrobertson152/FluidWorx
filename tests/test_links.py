"""How the two sides of a drawing are tied together, and the case it's all for: a 24 V control circuit with a PLC
running hydraulics, with position and pressure feeding back."""
import pytest
from drawing import Drawing, diff, part

from fluidworx import links
from fluidworx.vendor.openschematix import plc as plc_core
from fluidworx.vendor.openschematix.symbols.fluid import default_valve_params


@pytest.mark.parametrize("text,target,mode,frac,si", [
    ("A1 100%", "A1", "at", 1.0, None),
    ("A1 0%", "A1", "at", 0.0, None),
    ("A1 50%", "A1", "at", 0.5, None),
    ("A1 extended", "A1", "at", 1.0, None),
    ("A1 retracted", "A1", "at", 0.0, None),
    ("A1+", "A1", "at", 1.0, None),
    ("A1-", "A1", "at", 0.0, None),
    ("A1 150 mm", "A1", "at", None, 0.15),
    ("A1 at 150 mm", "A1", "at", None, 0.15),
    ("A1 > 50%", "A1", "above", 0.5, None),
    ("A1 >= 150 mm", "A1", "above", None, 0.15),
    ("A1 < 20 mm", "A1", "below", None, 0.02),
    ("A1>150mm", "A1", "above", None, 0.15),
    ("PT1 > 120 bar", "PT1", "above", None, 120e5),
    ("PT1 < 5 bar", "PT1", "below", None, 5e5),
    ("A1", "A1", "value", None, None),
    ("PT1", "PT1", "value", None, None),
])
def test_senses_reads_what_people_write(text, target, mode, frac, si):
    s = links.parse_senses(text)
    assert s.target == target and s.mode == mode
    assert (s.frac == frac) if frac is None else s.frac == pytest.approx(frac)
    assert (s.si is None) if si is None else s.si == pytest.approx(si)


@pytest.mark.parametrize("text", ["A1 sideways", "A1 > lots", "> 5 bar", "A1 12 parsecs"])
def test_senses_it_cant_read_is_none(text):
    assert links.parse_senses(text) is None


@pytest.mark.parametrize("text,volts", [
    ("+24V", 24.0), ("24V", 24.0), ("24 VDC", 24.0), ("-15V", -15.0), ("0V", 0.0), ("GND", 0.0), ("N", 0.0), ("M", 0.0),
    ("L+", 24.0), ("VCC", 5.0), ("230 VAC", 230.0), ("SIG1", None), ("", None), ("Motor", None),
])
def test_what_a_label_says_about_a_line(text, volts):
    assert links.parse_rail(text) == volts


def test_three_phases_are_120_degrees_apart():
    import cmath
    import math
    a, b, c = (links.parse_rail(x) for x in ("L1", "L2", "L3"))
    assert abs(a) == abs(b) == pytest.approx(230.0)
    assert math.degrees(cmath.phase(a / b)) == pytest.approx(120.0)
    assert math.degrees(cmath.phase(b / c)) == pytest.approx(120.0)
    assert abs(links.parse_rail("L1 400V") - links.parse_rail("L2 400V")) == pytest.approx(400.0)


# ---------------------------------------------------------------- a small hydraulic circuit to tie things to
def hydraulics(d, sheet=0, solenoids=("solenoid", "solenoid"), flow="10 L/min", tag="Y1"):
    params = default_valve_params("hyd", "4/3")
    params["left"], params["right"] = [solenoids[0], "spring"], [solenoids[1], "spring"]
    pump, tank, relief = d.add("fl.hyd.pump", "P1", flow, sheet=sheet), d.add("fl.hyd.tank", "Z1", sheet=sheet), d.add("fl.hyd.relief", "V2", "100 bar", sheet=sheet)
    valve, cyl = d.add("fl.hyd.dcv", tag, params=params, sheet=sheet), d.add("fl.hyd.cyl.double", "A1", "50/28x200", sheet=sheet)
    tank2, tank3 = d.add("fl.hyd.tank", "Z2", sheet=sheet), d.add("fl.hyd.tank", "Z3", sheet=sheet)
    gauge = d.add("fl.hyd.pressure.transducer", "PT1", sheet=sheet)
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (valve, "P"))
    d.wire((pump, "P"), (relief, "P"))
    d.wire((relief, "T"), (tank2, "T"))
    d.wire((valve, "T"), (tank3, "T"))
    d.wire((valve, "A"), (cyl, "A"))
    d.wire((valve, "B"), (cyl, "B"))
    d.wire((cyl, "A"), (gauge, gauge.terminals().__iter__().__next__()))
    return valve, cyl, gauge, pump


def rails(d, sheet=0):
    return d.add("el.rail.pos", "", "+24V", sheet=sheet), d.add("el.rail.neg", "", "0V", sheet=sheet)


def coil_on_switch(d, pos, neg, tag, sheet=0, symbol="el.coil.valve"):
    sw, coil = d.add("el.switch.selector.no", f"S{tag}", sheet=sheet), d.add(symbol, tag, sheet=sheet)
    a, b = [t.name for t in coil.terminal_defs()][:2]
    d.wire((pos, "1"), (sw, "1"))
    d.wire((sw, "2"), (coil, a))
    d.wire((coil, b), (neg, "1"))
    return sw, coil


def test_coil_y1a_is_the_left_solenoid_of_valve_y1_and_moves_a_cylinder():
    d = Drawing(sheets=2)
    valve, cyl, _g, _p = hydraulics(d)
    pos, neg = rails(d, 1)
    swa, _ca = coil_on_switch(d, pos, neg, "Y1a", 1)
    swb, _cb = coil_on_switch(d, pos, neg, "Y1b", 1)
    sim = d.sim()
    sim.run(0.2)
    v, a = part(sim, valve), part(sim, cyl)
    assert v.sol == {"left": False, "right": False} and a.x == 0.0
    sim.command(part(sim, swa).part.key, "toggle")
    sim.run(0.1)
    assert v.sol["left"] and v.position == 0
    sim.run(4.0)
    assert a.x == pytest.approx(0.2, abs=1e-4), "flow 10 L/min into 50 mm bore: 85 mm/s, so 2.4 s to do 200 mm"
    sim.command(part(sim, swa).part.key, "toggle")
    sim.command(part(sim, swb).part.key, "toggle")
    sim.run(0.1)
    assert v.sol["right"] and v.position == 2
    sim.run(4.0)
    assert a.x == pytest.approx(0.0, abs=1e-4)
    texts = " / ".join(link.text for link in sim.circuit.links)
    assert "Coil Y1a operates the left-hand solenoid of Y1" in texts and "Coil Y1b operates the right-hand solenoid of Y1" in texts


def test_a_single_solenoid_takes_the_valves_own_tag():
    d = Drawing(sheets=2)
    params = default_valve_params("hyd", "4/2")
    params["left"], params["right"] = ["solenoid"], ["spring"]
    valve = d.add("fl.hyd.dcv", "Y3", params=params)
    pos, neg = rails(d, 1)
    sw, _c = coil_on_switch(d, pos, neg, "Y3", 1)
    sim = d.sim()
    sim.run(0.05)
    b = part(sim, valve)
    assert b.position == b.normal
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(0.05)
    assert b.position == 0


def test_a_property_ties_a_valve_to_a_coil_with_another_tag():
    d = Drawing(sheets=2)
    valve, _c, _g, _p = hydraulics(d, tag="V7")
    valve.props["Solenoid a"] = "K5"
    pos, neg = rails(d, 1)
    sw, _coil = coil_on_switch(d, pos, neg, "K5", 1)
    sim = d.sim()
    sim.run(0.05)
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, valve).sol["left"]


def test_a_property_naming_a_coil_that_isnt_there_is_reported():
    d = Drawing(sheets=2)
    valve, _c, _g, _p = hydraulics(d, tag="V7")
    valve.props["Solenoid a"] = "K5"
    pos, neg = rails(d, 1)
    coil_on_switch(d, pos, neg, "K6", 1)
    assert any("no coil has that tag" in i.text for i in d.build().issues)


def test_a_coil_tagged_just_like_a_double_solenoid_valve_is_ambiguous_and_says_so():
    d = Drawing(sheets=2)
    hydraulics(d)
    pos, neg = rails(d, 1)
    coil_on_switch(d, pos, neg, "Y1", 1)
    assert any("Y1a and Y1b" in i.text for i in d.build().issues)


def test_a_valve_with_no_coil_can_still_be_clicked():
    d = Drawing(sheets=2)
    valve, _c, _g, _p = hydraulics(d)
    pos, neg = rails(d, 1)
    coil_on_switch(d, pos, neg, "K1", 1)
    sim = d.sim()
    sim.run(0.05)
    sim.command(part(sim, valve).part.key, "left")
    sim.run(0.05)
    assert part(sim, valve).position == 0
    assert any("operate its solenoid by clicking the valve" in i.text for i in sim.circuit.issues)


def test_a_click_on_a_wired_valve_is_a_manual_override_that_the_coil_does_not_fight():
    d = Drawing(sheets=2)
    valve, _c, _g, _p = hydraulics(d)
    pos, neg = rails(d, 1)
    coil_on_switch(d, pos, neg, "Y1a", 1)
    coil_on_switch(d, pos, neg, "Y1b", 1)
    sim = d.sim()
    sim.run(0.05)
    b = part(sim, valve)
    assert "manual override" in " ".join(a[1] for a in b.actions())
    sim.command(b.part.key, "right")
    sim.run(0.5)
    assert b.position == 2


def test_a_solenoid_coil_with_no_supply_does_nothing():
    d = Drawing(sheets=2)
    valve, _c, _g, _p = hydraulics(d)
    d.add("el.coil.valve", "Y1a", sheet=1)
    sim = d.sim()
    sim.run(0.1)
    assert not part(sim, valve).sol["left"]


def test_a_contact_with_the_tag_of_a_pressure_switch_follows_it():
    d = Drawing(sheets=2)
    pump, relief, tank, tank2 = d.add("fl.hyd.pump", "P1", "10 L/min"), d.add("fl.hyd.relief", "V1", "100 bar"), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.tank", "Z2")
    ps = d.add("fl.hyd.pressure.switch", "S3", "80 bar")
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (relief, "P"))
    d.wire((relief, "T"), (tank2, "T"))
    d.wire((pump, "P"), (ps, ps.terminal_defs()[0].name))
    pos, neg = rails(d, 1)
    contact, lamp = d.add("el.switch.pressure.no", "S3", sheet=1), d.add("el.lamp.iec", "H1", sheet=1)
    d.wire((pos, "1"), (contact, "1"))
    d.wire((contact, "2"), (lamp, "1"))
    d.wire((lamp, "2"), (neg, "1"))
    sim = d.sim()
    assert not part(sim, lamp).is_on()
    t0 = sim.time
    while not part(sim, lamp).is_on() and sim.time - t0 < 2.0:
        sim.step()
    assert part(sim, lamp).is_on() and part(sim, ps).on
    part(sim, pump).command("toggle")
    sim.touch()
    sim.run(0.5)
    assert sim.status(part(sim, pump).part.key) == "Stopped"


def test_pressure_contact_with_no_switch_is_reported_and_can_be_clicked():
    d = Drawing()
    pos, neg = rails(d)
    contact, lamp = d.add("el.switch.pressure.no", "S3"), d.add("el.lamp.iec", "H1")
    d.wire((pos, "1"), (contact, "1"))
    d.wire((contact, "2"), (lamp, "1"))
    d.wire((lamp, "2"), (neg, "1"))
    sim = d.sim()
    assert any("no pressure switch" in i.text for i in sim.circuit.issues)
    sim.run(0.02)
    assert not part(sim, lamp).is_on()
    sim.command(part(sim, contact).part.key, "toggle")
    sim.run(0.02)
    assert part(sim, lamp).is_on()


def limit_rig(senses, symbol="el.switch.limit.no", **kw):
    d = Drawing(sheets=2)
    valve, cyl, gauge, pump = hydraulics(d, **kw)
    pos, neg = rails(d, 1)
    sw, _coil = coil_on_switch(d, pos, neg, "Y1a", 1)
    limit, lamp = d.add(symbol, "S2", sheet=1, props={"Senses": senses}), d.add("el.lamp.iec", "H1", sheet=1)
    d.wire((pos, "1"), (limit, "1"))
    d.wire((limit, "2"), (lamp, "1"))
    d.wire((lamp, "2"), (neg, "1"))
    return d, sw, limit, lamp, cyl


def extend_until(sim, cyl, x):
    b = part(sim, cyl)
    while b.x < x:
        sim.step()


def test_a_limit_switch_at_the_end_of_stroke():
    d, sw, _limit, lamp, cyl = limit_rig("A1 100%")
    sim = d.sim()
    sim.run(0.05)
    assert not part(sim, lamp).is_on()
    sim.command(part(sim, sw).part.key, "toggle")
    extend_until(sim, cyl, 0.19)
    sim.run(0.01)
    assert not part(sim, lamp).is_on()
    sim.run(4.0)
    assert part(sim, lamp).is_on()


def test_a_limit_switch_at_home_is_made_at_the_start():
    d, sw, _limit, lamp, cyl = limit_rig("A1 retracted")
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, lamp).is_on()
    sim.command(part(sim, sw).part.key, "toggle")
    extend_until(sim, cyl, 0.01)
    sim.run(0.02)
    assert not part(sim, lamp).is_on()


def test_a_normally_closed_limit_switch_opens_when_reached():
    d, sw, _limit, lamp, cyl = limit_rig("A1 100%", "el.switch.limit.nc")
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(4.0)
    assert not part(sim, lamp).is_on()


def test_a_cam_in_mid_stroke_is_not_missed_at_any_speed():
    """1% of 200 mm is a 4 mm window. At 2000 L/min the rod goes 170 mm a step, right over it."""
    d, sw, limit, _lamp, cyl = limit_rig("A1 50%", flow="2000 L/min")
    sim = d.sim()
    sim.run(0.02)
    b, seen = part(sim, cyl), []
    sim.command(part(sim, sw).part.key, "toggle")
    for _ in range(30):
        sim.step()
        seen.append(part(sim, limit).closed())
    assert b.x == pytest.approx(0.2, abs=1e-3)
    assert True in seen, "it passed through and the switch saw it"
    assert seen[-1] is False


def test_threshold_on_position():
    d, sw, _limit, lamp, cyl = limit_rig("A1 > 150 mm")
    sim = d.sim()
    sim.run(0.02)
    sim.command(part(sim, sw).part.key, "toggle")
    extend_until(sim, cyl, 0.149)
    assert not part(sim, lamp).is_on()
    extend_until(sim, cyl, 0.153)
    sim.run(0.02)
    assert part(sim, lamp).is_on()


def test_threshold_on_pressure():
    """Extending against the end stop, the pressure climbs to the relief setting."""
    d, sw, _limit, lamp, cyl = limit_rig("PT1 > 80 bar")
    sim = d.sim()
    sim.run(0.02)
    sim.command(part(sim, sw).part.key, "toggle")
    extend_until(sim, cyl, 0.1)
    sim.run(0.02)
    assert not part(sim, lamp).is_on()
    sim.run(4.0)
    assert part(sim, lamp).is_on()


def test_threshold_on_a_motors_speed():
    d = Drawing(sheets=2)
    pump, tank, motor, t2 = d.add("fl.hyd.pump", "P1", "10 L/min"), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.motor", "M9", "25 cc/rev"), d.add("fl.hyd.tank", "Z2")
    names = [t.name for t in motor.terminal_defs()]
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (motor, names[0]))
    d.wire((motor, names[1]), (t2, "T"))
    pos, neg = rails(d, 1)
    s, lamp = d.add("el.switch.limit.no", "S1", sheet=1, props={"Senses": "M9 > 300 rpm"}), d.add("el.lamp.iec", "H1", sheet=1)
    d.wire((pos, "1"), (s, "1"))
    d.wire((s, "2"), (lamp, "1"))
    d.wire((lamp, "2"), (neg, "1"))
    sim = d.sim()
    sim.run(1.0)
    b = part(sim, motor)
    assert abs(b.v) * 60 / (2 * 3.14159) == pytest.approx(400.0, rel=0.05), "10 L/min through 25 cc/rev is 400 rpm"
    assert part(sim, lamp).is_on()


def test_a_position_on_a_motor_that_turns_without_end_is_reported():
    d = Drawing()
    d.add("fl.hyd.motor", "M9", "25 cc/rev")
    d.add("el.switch.limit.no", "S1", props={"Senses": "M9 100%"})
    c = d.build()
    assert any("turns without end" in i.text for i in c.issues) and not c.links


def test_a_pressure_switch_contact_can_read_a_gauge_instead():
    d, sw, _limit, lamp, cyl = limit_rig("PT1 > 80 bar", "el.switch.pressure.no")
    sim = d.sim()
    sim.run(0.02)
    sim.command(part(sim, sw).part.key, "toggle")
    extend_until(sim, cyl, 0.1)
    sim.run(0.02)
    assert not part(sim, lamp).is_on()
    sim.run(4.0)
    assert part(sim, lamp).is_on()


def test_a_sensor_naming_a_tag_nothing_has_is_reported():
    d = Drawing()
    limit = d.add("el.switch.limit.no", "S2", props={"Senses": "A9 100%"})
    c = d.build()
    assert any("A9" in i.text for i in c.issues)
    assert not c.links
    assert limit


def test_a_switch_that_only_names_a_cylinder_is_told_it_needs_a_place():
    d = Drawing()
    d.add("fl.hyd.cyl.double", "A1", "50/28x200")
    d.add("el.switch.limit.no", "S2", props={"Senses": "A1"})
    c = d.build()
    assert any("needs to know where" in i.text for i in c.issues) and not c.links


def test_parts_with_no_tag_are_not_the_same_device():
    """Both would otherwise go by the name of their symbol."""
    d = Drawing()
    d.add("el.coil.iec")
    d.add("el.coil.iec")
    d.add("el.contact.no.iec")
    c = d.build()
    assert not c.links and not any("coils are tagged" in i.text for i in c.issues)


def test_a_valve_with_no_tag_says_so():
    d = Drawing()
    params = default_valve_params("hyd", "4/3")
    params["left"], params["right"] = ["solenoid", "spring"], ["solenoid", "spring"]
    d.add("fl.hyd.dcv", params=params)
    d.add("el.coil.valve", "Y1a")
    assert any("no tag to find a coil by" in i.text for i in d.build().issues)


def test_two_coils_with_one_tag_are_reported():
    d = Drawing()
    d.add("el.coil.iec", "K1")
    d.add("el.coil.iec", "K1")
    assert any("2 coils are tagged K1" in i.text for i in d.build().issues)


def test_senses_it_cant_read_is_reported():
    d = Drawing()
    d.add("el.switch.limit.no", "S2", props={"Senses": "A1 sideways"})
    assert any("can't read" in i.text for i in d.build().issues)


def analog_rig(symbol, signal, ai_signal, lo=0.0, hi=0.0, senses=None, tag="PT1"):
    d = Drawing(sheets=2)
    _v, cyl, gauge, pump = hydraulics(d)
    pos, neg = rails(d, 1)
    sensor = d.add(symbol, tag, sheet=1, props={"Senses": senses} if senses else {})
    r = d.add("el.resistor.iec", "R1", "250 ohm" if "mA" in signal else "100k", sheet=1)
    if symbol == "el.sensor.loop":
        d.wire((pos, "1"), (sensor, "+"))
        d.wire((sensor, "-"), (r, "1"))
    else:
        d.wire((pos, "1"), (sensor, "+"))
        d.wire((sensor, "-"), (neg, "1"))
        d.wire((sensor, "OUT"), (r, "1"))
    d.wire((r, "2"), (neg, "1"))
    return d, sensor, r, cyl, pump


def test_analog_sensor_with_the_tag_of_a_transducer_reads_it():
    """At the end of its stroke, the pump is against the 100 bar relief: on a 0-250 bar 0-10 V transducer, about 4 V."""
    d, sensor, r, _cyl, _p = analog_rig("el.sensor.analog", "0-10V", "0-10V")
    sensor.label = "0-250 bar 0-10 V"
    pos, neg = next(c for c in d.sheet(1).components.values() if c.symbol == "el.rail.pos"), next(c for c in d.sheet(1).components.values() if c.symbol == "el.rail.neg")
    sw, _coil = coil_on_switch(d, pos, neg, "Y1a", 1)
    sim = d.sim()
    sim.run(0.02)
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(4.0)
    assert part(sim, sensor).par["hi"] == pytest.approx(250.0)
    p_bar = sim.p[next(b for b in sim.fluid.values() if b.part.tag == "PT1").node(0)] / 1e5
    assert p_bar > 90.0
    assert diff(sim, r, "1", "2") == pytest.approx(10.0 * p_bar / 250.0, abs=0.02)


def test_analog_sensor_on_position_with_senses():
    d, sensor, r, cyl, _p = analog_rig("el.sensor.analog", "0-10V", "0-10V", senses="A1", tag="B1")
    d2_sw = None
    del d2_sw
    pos, neg = next(c for c in d.sheet(1).components.values() if c.symbol == "el.rail.pos"), next(c for c in d.sheet(1).components.values() if c.symbol == "el.rail.neg")
    sw, _coil = coil_on_switch(d, pos, neg, "Y1a", 1)
    sim = d.sim()
    sim.run(0.02)
    assert diff(sim, r, "1", "2") == pytest.approx(0.0, abs=0.01)
    sim.command(part(sim, sw).part.key, "toggle")
    extend_until(sim, cyl, 0.1)
    sim.run(0.01)
    assert diff(sim, r, "1", "2") == pytest.approx(5.0, abs=0.1), "half way along the stroke"
    sim.run(4.0)
    assert diff(sim, r, "1", "2") == pytest.approx(10.0, abs=0.01)


def test_two_wire_sensor_takes_4_to_20_ma_from_the_loop():
    d, sensor, r, cyl, _p = analog_rig("el.sensor.loop", "4-20mA", "4-20mA", senses="A1", tag="B1")
    pos, neg = next(c for c in d.sheet(1).components.values() if c.symbol == "el.rail.pos"), next(c for c in d.sheet(1).components.values() if c.symbol == "el.rail.neg")
    sw, _coil = coil_on_switch(d, pos, neg, "Y1a", 1)
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, r).through() == pytest.approx(4e-3, abs=1e-5)
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(4.0)
    assert part(sim, r).through() == pytest.approx(20e-3, abs=1e-5)
    assert diff(sim, r, "1", "2") == pytest.approx(5.0, abs=0.01), "1-5 V across 250 ohm"


def test_three_wire_current_output_stops_at_what_its_supply_allows():
    """20 mA into 10k would be 200 V. It has 24 V, less 2 V, to push with."""
    d = Drawing()
    pos, neg = rails(d)
    s, r = d.add("el.sensor.analog", "B1", "4-20 mA", params={}), d.add("el.resistor.iec", "R1", "10k")
    d.wire((pos, "1"), (s, "+"))
    d.wire((s, "-"), (neg, "1"))
    d.wire((s, "OUT"), (r, "1"))
    d.wire((r, "2"), (neg, "1"))
    sim = d.sim()
    b = part(sim, s)
    assert b._output()[0] == "A"
    b.par["manual"] = 100.0
    sim.run(0.03)
    assert diff(sim, r, "1", "2") == pytest.approx(22.0, abs=0.1)


def test_three_wire_sensors_need_their_supply():
    d = Drawing()
    src, sw = d.add("el.source.dc", "G1", "24 V"), d.add("el.switch.selector.no", "Q1")
    prox, r = d.add("el.sensor.prox.pnp", "B1"), d.add("el.resistor.iec", "R1", "1k")
    d.wire((src, "+"), (sw, "1"))
    d.wire((sw, "2"), (prox, "+"))
    d.wire((prox, "-"), (src, "-"))
    d.wire((prox, "OUT"), (r, "1"))
    d.wire((r, "2"), (src, "-"))
    sim = d.sim()
    b = part(sim, prox)
    sim.command(b.part.key, "toggle")
    sim.run(0.02)
    assert b.status() == "No supply" and part(sim, r).through() == 0.0
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(0.02)
    assert b.status() == "Detecting" and part(sim, r).through() == pytest.approx(24e-3, abs=1e-4)


def test_npn_output_pulls_low():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    prox, r = d.add("el.sensor.prox.npn", "B1"), d.add("el.resistor.iec", "R1", "1k")
    d.wire((src, "+"), (prox, "+"))
    d.wire((prox, "-"), (src, "-"))
    d.wire((src, "+"), (r, "1"))
    d.wire((r, "2"), (prox, "OUT"))
    sim = d.sim()
    b = part(sim, prox)
    sim.run(0.02)
    assert part(sim, r).through() < 1e-6
    sim.command(b.part.key, "toggle")
    sim.run(0.02)
    assert part(sim, r).through() == pytest.approx(24e-3, abs=1e-4)


def test_a_motor_drives_the_pump_with_its_tag():
    d = Drawing(sheets=2)
    pump, tank, relief, t2 = d.add("fl.hyd.pump", "M1", "10 L/min"), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.relief", "V1", "50 bar"), d.add("fl.hyd.tank", "Z2")
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (relief, "P"))
    d.wire((relief, "T"), (t2, "T"))
    pos, neg = rails(d, 1)
    sw, motor = coil_on_switch(d, pos, neg, "M1", 1, symbol="el.motor")
    del motor
    sim = d.sim()
    sim.run(0.5)
    b = part(sim, pump)
    assert not b.running and b.status(sim.p).startswith("Stopped: M1")
    assert not b.actions(), "and it can't be started by hand"
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(1.0)
    assert b.running and sim.p[b.node(0)] > 45e5


def pump_rig(flow, relief, motor_symbol, motor_label):
    d = Drawing(sheets=2)
    pump, tank, rv, t2 = d.add("fl.hyd.pump", "M1", flow), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.relief", "V1", relief), d.add("fl.hyd.tank", "Z2")
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (rv, "P"))
    d.wire((rv, "T"), (t2, "T"))
    motor = d.add(motor_symbol, "M1", motor_label, sheet=1)
    return d, motor, pump


def test_a_motor_draws_what_its_pump_is_doing():
    """10 L/min at 100 bar is 1667 W, or 1961 W at 85%. At 400 V that's 1961 / (sqrt(3) x 400) = 2.83 A."""
    d, motor, _pump = pump_rig("10 L/min", "100 bar", "el.motor.3ph", "3 kW")
    for name, pin in (("L1", "U1"), ("L2", "V1"), ("L3", "W1")):
        d.wire((d.add("el.rail.pos", "", name, sheet=1), "1"), (motor, pin))
    sim = d.sim()
    sim.run(1.0)
    b = part(sim, motor)
    assert b.shaft_watts() == pytest.approx(10e-3 / 60 * 100e5 / 0.85, rel=0.03)
    assert max(abs(i) for i in b.currents(sim.net.v).values()) == pytest.approx(2.83, rel=0.03)
    assert not any("asking" in text for _t, _tag, text in sim.events)


def test_a_pump_asking_too_much_of_its_motor_is_reported():
    """The same 1961 W from a 750 W motor. On a 12 V DC motor as well, to show it's the same rule. It's a resistance of
    12^2 / 1961 = 73 mOhm, so with the source's 20 mOhm in series it takes 12 / 0.0934 = 128 A."""
    d, motor, _pump = pump_rig("10 L/min", "100 bar", "el.motor", "12 V 750 W")
    src = d.add("el.source.dc", "G1", "12 V", sheet=1)
    d.wire((src, "+"), (motor, "1"))
    d.wire((motor, "2"), (src, "-"))
    sim = d.sim()
    sim.run(1.0)
    assert any("asking for" in text and "750 W" in text for _t, _tag, text in sim.events)
    assert part(sim, motor).through() == pytest.approx(12.0 / (12.0 ** 2 / 1961.0 + 0.02), rel=0.03)


def test_a_motor_turning_an_unloaded_pump_draws_little():
    """Nothing resists the pump: about a tenth of its rating."""
    d = Drawing(sheets=2)
    pump, tank, t2 = d.add("fl.hyd.pump", "M1", "10 L/min"), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.tank", "Z2")
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (t2, "T"))
    src, motor = d.add("el.source.dc", "G1", "24 V", sheet=1), d.add("el.motor", "M1", "24 V 1 kW", sheet=1)
    d.wire((src, "+"), (motor, "1"))
    d.wire((motor, "2"), (src, "-"))
    sim = d.sim()
    sim.run(0.5)
    assert part(sim, motor).shaft_watts() == pytest.approx(100.0, rel=0.05)


def test_a_motor_driving_nothing_draws_its_rating():
    d = Drawing()
    src, motor = d.add("el.source.dc", "G1", "24 V"), d.add("el.motor", "M1", "24 V 240 W")
    d.wire((src, "+"), (motor, "1"))
    d.wire((motor, "2"), (src, "-"))
    sim = d.sim()
    sim.run(0.1)
    assert part(sim, motor).through() == pytest.approx(24.0 / 2.42, abs=0.01), "2.4 ohm, and the source's 20 mOhm"


def test_a_bidirectional_pump_follows_its_motor_round():
    d = Drawing(sheets=2)
    pump, t1, t2 = d.add("fl.hyd.pump.bidir", "M1", "10 L/min"), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.tank", "Z2")
    names = [t.name for t in pump.terminal_defs()]
    d.wire((pump, names[0]), (t1, "T"))
    d.wire((pump, names[1]), (t2, "T"))
    motor = d.add("el.motor.3ph", "M1", "1 kW", sheet=1)
    for name, pin in (("L1", "V1"), ("L2", "U1"), ("L3", "W1")):        # two phases swapped
        d.wire((d.add("el.rail.pos", "", name, sheet=1), "1"), (motor, pin))
    sim = d.sim()
    sim.run(0.1)
    assert part(sim, motor).status() == "Running, reversed"
    assert part(sim, pump).reversed


def test_driven_by_names_the_motor():
    d = Drawing(sheets=2)
    pump, tank = d.add("fl.hyd.pump", "P1", "10 L/min", props={"Driven by": "M7"}), d.add("fl.hyd.tank", "Z1")
    d.wire((pump, "S"), (tank, "T"))
    pos, neg = rails(d, 1)
    sw, _m = coil_on_switch(d, pos, neg, "M7", 1, symbol="el.motor")
    sim = d.sim()
    sim.run(0.05)
    assert not part(sim, pump).running
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, pump).running


def test_driven_by_a_motor_that_isnt_there_is_reported():
    d = Drawing(sheets=2)
    d.add("fl.hyd.pump", "P1", "10 L/min", props={"Driven by": "M7"})
    pos, neg = rails(d, 1)
    coil_on_switch(d, pos, neg, "M8", 1, symbol="el.motor")
    assert any("M7" in i.text for i in d.build().issues)


def test_a_proportional_valve_follows_its_coils_voltage():
    d = Drawing(sheets=2)
    pump, tank, valve, t2 = d.add("fl.hyd.pump", "P1", "10 L/min"), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.valve.prop.nc", "Y4"), d.add("fl.hyd.tank", "Z2")
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (valve, valve.terminal_defs()[0].name))
    d.wire((valve, valve.terminal_defs()[1].name), (t2, "T"))
    src, coil = d.add("el.source.dc", "G1", "5 V", sheet=1), d.add("el.coil.valve", "Y4", sheet=1)
    d.wire((src, "+"), (coil, "A1"))
    d.wire((coil, "A2"), (src, "-"))
    sim = d.sim()
    sim.run(0.05)
    b = part(sim, valve)
    assert b.opening() == pytest.approx(50.0, abs=1.0), "5 V on a 10 V command"
    part(sim, src).par["voltage"] = 10.0
    sim.touch()
    sim.run(0.05)
    assert b.opening() == pytest.approx(100.0, abs=1.0)
    part(sim, src).par["voltage"] = 0.0
    sim.touch()
    sim.run(0.05)
    assert b.opening() == 0.0


def test_links_a_study_sets_change_only_the_study():
    d = Drawing(sheets=2)
    valve, _c, _g, _p = hydraulics(d, tag="V7")
    pos, neg = rails(d, 1)
    coil_on_switch(d, pos, neg, "K5", 1)
    assert not [link for link in d.build().links if link.kind == "solenoid"]
    uid = d.sheet(0).uid
    c = d.build({f"{uid}/{valve.id}": {"Solenoid a": "K5"}})
    assert [link.text for link in c.links if link.kind == "solenoid"]


# ---------------------------------------------------------------- the point of it all
ST_PROGRAM = """
(* Press Start: extend until the end of stroke or until the pressure says it has met something, then retract. *)
IF Start AND AtHome THEN Extending := TRUE; END_IF;
IF AtEnd OR Pressure > 80.0 THEN Extending := FALSE; END_IF;
Extend := Extending;
Retract := NOT Extending AND NOT AtHome;
"""


def plc_params(**program):
    params = plc_core.default_params()
    params["tags"] = {"I0": "Start", "I1": "AtHome", "I2": "AtEnd", "AI0": "Pressure", "Q0": "Extend", "Q1": "Retract"}
    prog = {"pous": [{"name": "Main", "lang": "st", "source": ST_PROGRAM}], "io": {"AI0": {"signal": "0-10V", "lo": 0, "hi": 250}},
            "vars": [{"name": "Extending", "type": "BOOL", "init": "", "note": ""}], "scan_ms": 10}
    prog.update(program)
    params["program"] = prog
    return params


def plc_rig(params=None, relief="100 bar", load=None, plc_supply=True):
    """A 24 V control circuit with a PLC running a hydraulic cylinder, and position and pressure feeding back."""
    d = Drawing(sheets=2)
    valve, cyl, gauge, pump = hydraulics(d)
    if load:
        cyl.label = load
    pos, neg = rails(d, 1)
    plc_ = d.add("el.plc", "PLC1", params=params or plc_params(), sheet=1)
    start = d.add("el.pushbutton.no.iec", "S0", sheet=1)
    home = d.add("el.switch.limit.no", "S1", sheet=1, props={"Senses": "A1 retracted"})
    end = d.add("el.switch.limit.no", "S2", sheet=1, props={"Senses": "A1 extended"})
    pt = d.add("el.sensor.analog", "PT1", "0-250 bar 0-10 V", sheet=1)
    ya, yb = d.add("el.coil.valve", "Y1a", "24 V 20 W", sheet=1), d.add("el.coil.valve", "Y1b", "24 V 20 W", sheet=1)
    if plc_supply:
        d.wire((pos, "1"), (plc_, "L+"))
        d.wire((neg, "1"), (plc_, "M"))
    for sw, pin in ((start, "I0"), (home, "I1"), (end, "I2")):
        d.wire((pos, "1"), (sw, "1"))
        d.wire((sw, "2"), (plc_, pin))
    d.wire((pos, "1"), (pt, "+"))
    d.wire((neg, "1"), (pt, "-"))
    d.wire((pt, "OUT"), (plc_, "AI0"))
    d.wire((plc_, "Q0"), (ya, "A1"))
    d.wire((ya, "A2"), (neg, "1"))
    d.wire((plc_, "Q1"), (yb, "A1"))
    d.wire((yb, "A2"), (neg, "1"))
    return d, dict(plc=plc_, start=start, valve=valve, cyl=cyl, ya=ya, yb=yb, pump=pump, pt=pt)


def press(sim, comp, seconds=0.1):
    key = part(sim, comp).part.key
    sim.command(key, "press")
    sim.run(seconds)
    sim.command(key, "release")


def test_plc_runs_a_cylinder_out_and_back_with_feedback():
    d, r = plc_rig()
    sim = d.sim()
    sim.run(0.2)
    cyl, plc_ = part(sim, r["cyl"]), part(sim, r["plc"])
    assert plc_.status() == "Run" and plc_.inputs["I1"], "the home switch is made and the PLC sees it"
    assert cyl.x == 0.0 and not part(sim, r["ya"]).energised
    press(sim, r["start"])
    assert plc_.outs["Q0"] and part(sim, r["ya"]).energised and part(sim, r["valve"]).sol["left"]
    # 10 L/min into 50 mm: 85 mm/s, so 200 mm takes 2.36 s, and retracting into the annulus (1350 mm2) takes 1.62 s
    t0 = sim.time
    while cyl.x < 0.199 and sim.time - t0 < 10.0:
        sim.step()
    assert sim.time - t0 == pytest.approx(0.2 / (10e-3 / 60 / (3.14159 / 4 * 0.05 ** 2)), rel=0.1)
    sim.run(0.1)
    assert plc_.outs["Q1"] and not plc_.outs["Q0"], "the end switch made it turn round"
    t0 = sim.time
    while cyl.x > 0.001 and sim.time - t0 < 10.0:
        sim.step()
    area = 3.14159 / 4 * (0.05 ** 2 - 0.028 ** 2)
    assert sim.time - t0 == pytest.approx(0.2 / (10e-3 / 60 / area), rel=0.1)
    sim.run(0.1)
    assert cyl.x == pytest.approx(0.0, abs=1e-3)
    assert not plc_.outs["Q0"] and not plc_.outs["Q1"], "and home again it waits"


def test_plc_turns_round_on_pressure_when_the_rod_meets_something():
    """A 15000 N load needs about 76 bar on a 50 mm bore. Set the limit lower and it never gets out."""
    params = plc_params()
    params["program"]["pous"][0]["source"] = ST_PROGRAM.replace("80.0", "40.0")
    d, r = plc_rig(params)
    sim = d.sim()
    part(sim, r["cyl"]).part.params["load"] = 15000.0
    sim.touch()
    sim.run(0.2)
    press(sim, r["start"])
    sim.run(0.5)
    plc_ = part(sim, r["plc"])
    assert plc_.rt.read("Pressure") > 40.0
    assert not plc_.rt.read("Extending"), "the pressure limit stopped it"
    assert part(sim, r["cyl"]).x < 0.02


EVERY_LANGUAGE = {
    "st": ST_PROGRAM,
    "c": """
bool extending;
void loop(void) {
    if (Start && AtHome) extending = true;
    if (AtEnd || Pressure > 80.0) extending = false;
    Extend = extending;
    Retract = !extending && !AtHome;
}
""",
    "python": """
extending = False
def loop():
    global extending, Extend, Retract
    if Start and AtHome:
        extending = True
    if AtEnd or Pressure > 80.0:
        extending = False
    Extend = extending
    Retract = not extending and not AtHome
""",
    "ld": {"rungs": [
        {"items": [{"t": "par", "branches": [[{"t": "no", "a": "Start"}, {"t": "no", "a": "AtHome"}], [{"t": "no", "a": "Extending"}]]},
                   {"t": "nc", "a": "AtEnd"}, {"t": "coil", "a": "Extending"}]},
        {"items": [{"t": "no", "a": "Extending"}, {"t": "coil", "a": "Extend"}]},
        {"items": [{"t": "nc", "a": "Extending"}, {"t": "nc", "a": "AtHome"}, {"t": "coil", "a": "Retract"}]}]},
    "fbd": {"blocks": [
        {"id": 1, "type": "input", "expr": "Start", "x": 0, "y": 0}, {"id": 2, "type": "input", "expr": "AtHome", "x": 0, "y": 40},
        {"id": 3, "type": "AND", "x": 100, "y": 0}, {"id": 4, "type": "input", "expr": "Extending", "x": 0, "y": 80},
        {"id": 5, "type": "OR", "x": 200, "y": 0}, {"id": 6, "type": "input", "expr": "AtEnd", "x": 0, "y": 120},
        {"id": 7, "type": "NOT", "x": 100, "y": 120}, {"id": 8, "type": "AND", "x": 300, "y": 0},
        {"id": 9, "type": "output", "target": "Extending", "x": 400, "y": 0}, {"id": 10, "type": "output", "target": "Extend", "x": 400, "y": 40},
        {"id": 11, "type": "NOT", "x": 300, "y": 80}, {"id": 12, "type": "NOT", "x": 100, "y": 40}, {"id": 13, "type": "AND", "x": 400, "y": 80},
        {"id": 14, "type": "output", "target": "Retract", "x": 500, "y": 80}],
        "wires": [{"from": [1, "OUT"], "to": [3, "IN1"]}, {"from": [2, "OUT"], "to": [3, "IN2"]}, {"from": [3, "OUT"], "to": [5, "IN1"]},
                  {"from": [4, "OUT"], "to": [5, "IN2"]}, {"from": [5, "OUT"], "to": [8, "IN1"]}, {"from": [6, "OUT"], "to": [7, "IN"]},
                  {"from": [7, "OUT"], "to": [8, "IN2"]}, {"from": [8, "OUT"], "to": [9, "IN"]}, {"from": [8, "OUT"], "to": [10, "IN"]},
                  {"from": [8, "OUT"], "to": [11, "IN"]}, {"from": [2, "OUT"], "to": [12, "IN"]}, {"from": [11, "OUT"], "to": [13, "IN1"]},
                  {"from": [12, "OUT"], "to": [13, "IN2"]}, {"from": [13, "OUT"], "to": [14, "IN"]}]},
    "sfc": {"steps": [
        {"id": 1, "name": "Waiting", "initial": True, "actions": []},
        {"id": 2, "name": "GoingOut", "actions": [{"q": "N", "target": "Extend"}]},
        {"id": 3, "name": "ComingBack", "actions": [{"q": "N", "target": "Retract"}]}],
        "transitions": [{"id": 1, "from": [1], "to": [2], "cond": "Start AND AtHome"},
                        {"id": 2, "from": [2], "to": [3], "cond": "AtEnd"},
                        {"id": 3, "from": [3], "to": [1], "cond": "AtHome"}]},
}


@pytest.mark.parametrize("lang", sorted(EVERY_LANGUAGE))
def test_the_same_machine_runs_the_same_in_every_language(lang):
    """Out on Start, back at the end of the stroke, waiting again at home: the same times, whichever language says so."""
    variables = [{"name": "Extending", "type": "BOOL", "init": "", "note": ""}] if lang in ("st", "ld", "fbd") else []
    params = plc_params(pous=[{"name": "Main", "lang": lang, "source": EVERY_LANGUAGE[lang]}], vars=variables)
    assert not [x for x in plc_core.check(params) if x.level == "error"], plc_core.check(params)
    d, r = plc_rig(params)
    sim = d.sim()
    sim.run(0.2)
    cyl = part(sim, r["cyl"])
    assert part(sim, r["plc"]).status() == "Run" and cyl.x == 0.0
    press(sim, r["start"])
    sim.run(2.0)
    assert cyl.x > 0.15 and part(sim, r["ya"]).energised, "on its way out"
    sim.run(0.6)
    assert part(sim, r["yb"]).energised and not part(sim, r["ya"]).energised, "the end switch turned it round"
    sim.run(2.5)
    assert cyl.x < 0.005 and not part(sim, r["yb"]).energised, "and home it stops"
    assert part(sim, r["plc"]).status() == "Run"
    press(sim, r["start"])
    sim.run(0.5)
    assert cyl.x > 0.0, "and it goes again"


def test_plc_does_not_run_without_its_supply():
    d, r = plc_rig(plc_supply=False)
    sim = d.sim()
    sim.run(0.2)
    b = part(sim, r["plc"])
    assert b.status().startswith("No supply") and not b.running()
    press(sim, r["start"])
    assert not part(sim, r["ya"]).energised
    assert any("L+" in i.text for i in sim.circuit.issues)


def test_plc_supply_the_wrong_way_round_is_no_supply():
    """A floating M would otherwise be dragged up by the input current, and read as a supply in reverse."""
    d = Drawing()
    src, plc_ = d.add("el.source.dc", "G1", "24 V"), d.add("el.plc", "PLC1", params=plc_params(pous=[{"name": "Main", "lang": "st", "source": "Extend := TRUE;"}], vars=[]))
    d.wire((src, "-"), (plc_, "L+"))
    d.wire((src, "+"), (plc_, "M"))
    sim = d.sim()
    sim.run(0.05)
    b = part(sim, plc_)
    assert not b.powered and b.status() == "Supply the wrong way round" and not b.outs["Q0"]


def supply_switched_rig():
    d = Drawing(sheets=2)
    hydraulics(d)
    src, main = d.add("el.source.dc", "G1", "24 V", sheet=1), d.add("el.switch.selector.no", "Q0", sheet=1)
    plc_ = d.add("el.plc", "PLC1", params=plc_params(pous=[{"name": "Main", "lang": "st", "source": "Extend := TRUE;"}], vars=[]), sheet=1)
    ya = d.add("el.coil.valve", "Y1a", "24 V 20 W", sheet=1)
    d.wire((src, "+"), (main, "1"))
    d.wire((main, "2"), (plc_, "L+"))
    d.wire((plc_, "M"), (src, "-"))
    d.wire((plc_, "Q0"), (ya, "A1"))
    d.wire((ya, "A2"), (src, "-"))
    return d, main, plc_, ya


def test_plc_starts_when_its_supply_comes_up_and_stops_when_it_goes():
    d, main, plc_, ya = supply_switched_rig()
    sim = d.sim()
    sim.run(0.1)
    b = part(sim, plc_)
    assert not b.powered and not part(sim, ya).energised
    sim.command(part(sim, main).part.key, "toggle")
    sim.run(0.1)
    assert b.powered and b.outs["Q0"] and part(sim, ya).energised
    sim.command(part(sim, main).part.key, "toggle")
    sim.run(0.1)
    assert not b.powered and not b.outs["Q0"] and not part(sim, ya).energised
    assert any("Lost its supply" in text for _t, _tag, text in sim.events)


def test_plc_switch_to_stop_drops_its_outputs_and_a_fault_says_why():
    params = plc_params(pous=[{"name": "Main", "lang": "st", "source": "Extend := TRUE;\nIF Start THEN Count := 1 / Zero; END_IF;"}],
                        vars=[{"name": "Count", "type": "INT", "init": "", "note": ""}, {"name": "Zero", "type": "INT", "init": "", "note": ""}])
    d, r = plc_rig(params)
    sim = d.sim()
    sim.run(0.1)
    b = part(sim, r["plc"])
    assert b.outs["Q0"]
    sim.command(b.part.key, "toggle")
    sim.run(0.05)
    assert b.status() == "Stop" and not b.outs["Q0"] and not part(sim, r["ya"]).energised
    sim.command(b.part.key, "toggle")
    sim.run(0.05)
    assert b.status() == "Run" and b.outs["Q0"]
    press(sim, r["start"], 0.05)
    assert b.status().startswith("Fault") and not b.outs["Q0"]
    assert any("Fault" in text for _t, _tag, text in sim.events)
    sim.run(0.05)
    sim.command(b.part.key, "restart")
    sim.run(0.05)
    assert b.status() == "Run" and b.outs["Q0"]


def test_plc_program_with_errors_says_so_and_does_nothing():
    params = plc_params(pous=[{"name": "Main", "lang": "st", "source": "Nonsense := ;"}], vars=[])
    d, r = plc_rig(params)
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, r["plc"]).status().startswith("Program has errors")
    assert not part(sim, r["plc"]).actions()
    assert any(i.level == "error" and "PLC1 program" in i.text for i in sim.circuit.issues)


def test_plc_input_needs_15_volts_on_a_24_volt_supply():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    plc_ = d.add("el.plc", "PLC1", params=plc_params(pous=[{"name": "Main", "lang": "st", "source": "Extend := Start;"}], vars=[]))
    probe = d.add("el.source.dc", "G2", "14 V")
    d.wire((src, "+"), (plc_, "L+"))
    d.wire((src, "-"), (plc_, "M"))
    d.wire((probe, "+"), (plc_, "I0"))
    d.wire((probe, "-"), (plc_, "M"))
    sim = d.sim()
    b, source = part(sim, plc_), part(sim, probe)

    def at(volts_):
        source.par["voltage"] = volts_
        sim.touch()
        sim.run(0.05)
        return b.inputs["I0"]
    assert not at(14.9)
    assert at(15.1)
    assert at(6.0), "between the two it holds"
    assert not at(4.9)


def test_too_much_on_a_plc_output_is_reported():
    """A 20 W coil on a 0.5 A output: 0.83 A."""
    params = plc_params(pous=[{"name": "Main", "lang": "st", "source": "Extend := TRUE;"}], vars=[])
    d, r = plc_rig(params)
    sim = d.sim()
    sim.run(0.1)
    assert any("Q0 is carrying 0.83 A" in text for _t, _tag, text in sim.events)
    assert part(sim, r["plc"]).peak["Q0"] == pytest.approx(20.0 / 24.0, abs=0.01)


@pytest.mark.parametrize("bad", [None, 1, "x", [], {"pous": 1}, {"pous": []}, {"pous": [1]}, {"pous": [{"lang": "cobol"}]},
                                 {"pous": [{"name": "A", "lang": "st", "source": 5}]}, {"scan_ms": "fast"}, {"io": 5}, {"vars": [1]}])
def test_a_damaged_program_never_stops_the_simulation(bad):
    d, r = plc_rig({**plc_core.default_params(), "program": bad})
    sim = d.sim()
    sim.run(0.05)
    press(sim, r["start"], 0.02)
    part(sim, r["plc"]).status()
    part(sim, r["plc"]).watch()


@pytest.mark.parametrize("params", [{"di": "many"}, {"di": 500, "do": -3, "ai": None}, {"do_type": "steam"}, {"tags": 5}])
def test_a_damaged_block_never_stops_the_simulation(params):
    d = Drawing()
    src, plc_ = d.add("el.source.dc", "G1", "24 V"), d.add("el.plc", "PLC1", params=params)
    d.wire((src, "+"), (plc_, "L+"))
    d.wire((src, "-"), (plc_, "M"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, plc_).status() == "Run"


def test_plc_comes_back_set_to_run_after_a_reset():
    d, r = plc_rig()
    sim = d.sim()
    sim.run(0.05)
    b = part(sim, r["plc"])
    sim.command(b.part.key, "toggle")
    sim.run(0.05)
    assert b.status() == "Stop"
    sim.reset()
    sim.run(0.05)
    assert b.status() == "Run"


def test_a_plc_on_a_dc_circuit_in_a_drawing_with_three_phases_still_knows_its_polarity():
    d = Drawing()
    src, plc_ = d.add("el.source.dc", "G1", "24 V"), d.add("el.plc", "PLC1", params=plc_core.default_params())
    d.wire((src, "-"), (plc_, "L+"))
    d.wire((src, "+"), (plc_, "M"))
    motor = d.add("el.motor.3ph", "M1", "1 kW")
    for name, pin in (("L1", "U1"), ("L2", "V1"), ("L3", "W1")):
        d.wire((d.add("el.rail.pos", "", name), "1"), (motor, pin))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, motor).running
    assert part(sim, plc_).status() == "Supply the wrong way round"


def test_plc_input_draws_about_7_ma():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    plc_ = d.add("el.plc", "PLC1", params=plc_params())
    d.wire((src, "+"), (plc_, "L+"))
    d.wire((src, "-"), (plc_, "M"))
    d.wire((src, "+"), (plc_, "I0"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, plc_).currents(sim.net.v)["I0"] == pytest.approx(24.0 / 3300.0, abs=1e-5)


@pytest.mark.parametrize("do_type,wiring", [("source", "source"), ("sink", "sink"), ("relay", "relay")])
def test_each_kind_of_output_switches_its_load(do_type, wiring):
    params = plc_params(pous=[{"name": "Main", "lang": "st", "source": "Extend := Start;"}], vars=[])
    params["do_type"] = do_type
    d = Drawing()
    src, sw = d.add("el.source.dc", "G1", "24 V"), d.add("el.switch.selector.no", "S0")
    plc_ = d.add("el.plc", "PLC1", params=params)
    lamp = d.add("el.lamp.iec", "H1", "24 V 12 W")
    d.wire((src, "+"), (plc_, "L+"))
    d.wire((src, "-"), (plc_, "M"))
    d.wire((src, "+"), (sw, "1"))
    d.wire((sw, "2"), (plc_, "I0"))
    if wiring == "source":
        d.wire((plc_, "Q0"), (lamp, "1"))
        d.wire((lamp, "2"), (src, "-"))
    elif wiring == "sink":
        d.wire((src, "+"), (lamp, "1"))
        d.wire((lamp, "2"), (plc_, "Q0"))
    else:
        d.wire((src, "+"), (plc_, "C"))
        d.wire((plc_, "Q0"), (lamp, "1"))
        d.wire((lamp, "2"), (src, "-"))
    sim = d.sim()
    sim.run(0.05)
    assert not part(sim, lamp).is_on()
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, lamp).is_on()
    assert diff(sim, lamp, "1", "2") == pytest.approx(24.0, abs=0.1)


def test_analog_input_in_each_signal_reads_right():
    """0-10 V on AI0 scaled 0-250, 4-20 mA on AI1 scaled 0-100: half way each."""
    params = plc_params(pous=[{"name": "Main", "lang": "st", "source": "Extend := AI0 > 124.0 AND AI0 < 126.0;\nRetract := AI1 > 49.0 AND AI1 < 51.0;"}], vars=[])
    params["program"]["io"] = {"AI0": {"signal": "0-10V", "lo": 0, "hi": 250}, "AI1": {"signal": "4-20mA", "lo": 0, "hi": 100}}
    params["tags"] = {"Q0": "Extend", "Q1": "Retract"}
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    plc_ = d.add("el.plc", "PLC1", params=params)
    v5, i12 = d.add("el.source.dc", "G2", "5 V"), d.add("el.source.i", "G3")
    d.wire((src, "+"), (plc_, "L+"))
    d.wire((src, "-"), (plc_, "M"))
    d.wire((v5, "+"), (plc_, "AI0"))
    d.wire((v5, "-"), (plc_, "M"))
    d.wire((i12, "2"), (plc_, "AI1"))
    d.wire((i12, "1"), (plc_, "M"))
    sim = d.sim()
    part(sim, i12).par["current"] = 0.012
    sim.touch()
    sim.run(0.05)
    b = part(sim, plc_)
    assert b.rt.read("AI0") == pytest.approx(125.0, abs=0.1)
    assert b.rt.read("AI1") == pytest.approx(50.0, abs=0.1)
    assert b.outs["Q0"] and b.outs["Q1"]


def test_analog_output_commands_a_proportional_valve():
    params = plc_params(pous=[{"name": "Main", "lang": "st", "source": "AO0 := 25.0;"}], vars=[])
    params["program"]["io"] = {"AO0": {"signal": "0-10V", "lo": 0, "hi": 100}}
    params["tags"] = {}
    d = Drawing(sheets=2)
    pump, tank, valve, t2 = d.add("fl.hyd.pump", "P1", "10 L/min"), d.add("fl.hyd.tank", "Z1"), d.add("fl.hyd.valve.prop.nc", "Y4"), d.add("fl.hyd.tank", "Z2")
    d.wire((pump, "S"), (tank, "T"))
    d.wire((pump, "P"), (valve, valve.terminal_defs()[0].name))
    d.wire((valve, valve.terminal_defs()[1].name), (t2, "T"))
    pos, neg = rails(d, 1)
    plc_ = d.add("el.plc", "PLC1", params=params, sheet=1)
    coil = d.add("el.coil.valve", "Y4", sheet=1)
    d.wire((pos, "1"), (plc_, "L+"))
    d.wire((neg, "1"), (plc_, "M"))
    d.wire((plc_, "AO0"), (coil, "A1"))
    d.wire((coil, "A2"), (neg, "1"))
    sim = d.sim()
    sim.run(0.1)
    assert diff(sim, coil, "A1", "A2") == pytest.approx(2.5, abs=0.01)
    assert part(sim, valve).opening() == pytest.approx(25.0, abs=0.5)


def test_plc_messages_and_scan_time():
    source = "count = 0\ndef loop():\n    global count\n    count += 1\n    if count == 5:\n        print('five')\n"
    params = plc_params(pous=[{"name": "Main", "lang": "python", "source": source}], vars=[], scan_ms=20)
    assert not [x for x in plc_core.check(params) if x.level == "error"], plc_core.check(params)
    d, r = plc_rig(params)
    sim = d.sim()
    sim.run(1.0)
    b = part(sim, r["plc"])
    assert b.rt.scans == pytest.approx(50, abs=2), "a 20 ms scan: 50 in a second"
    assert any("five" in text for _t, _tag, text in sim.events)


def test_a_timer_in_a_program_keeps_real_time():
    source = "T1(IN := Start, PT := T#1s);\nExtend := T1.Q;"
    params = plc_params(pous=[{"name": "Main", "lang": "st", "source": source}], vars=[{"name": "T1", "type": "TON", "init": "", "note": ""}], scan_ms=7)
    assert not [x for x in plc_core.check(params) if x.level == "error"], plc_core.check(params)
    d, r = plc_rig(params)
    sim = d.sim()
    sim.run(0.1)
    key = part(sim, r["start"]).part.key
    sim.command(key, "press")
    b = part(sim, r["plc"])
    t0 = sim.time
    while not b.outs["Q0"] and sim.time - t0 < 3.0:
        sim.step()
    assert sim.time - t0 == pytest.approx(1.0, abs=0.05)


def test_reset_starts_the_whole_machine_again():
    d, r = plc_rig()
    sim = d.sim()
    sim.run(0.2)
    press(sim, r["start"])
    sim.run(1.0)
    assert part(sim, r["cyl"]).x > 0.0
    sim.reset()
    sim.run(0.1)
    assert part(sim, r["cyl"]).x == 0.0
    assert not part(sim, r["ya"]).energised and not part(sim, r["plc"]).outs["Q0"]
    press(sim, r["start"])
    sim.run(1.0)
    assert part(sim, r["cyl"]).x > 0.0


def test_the_trace_records_both_sides():
    d, r = plc_rig()
    sim = d.sim()
    sim.run(0.2)
    press(sim, r["start"])
    sim.run(1.0)
    labels = [c[1] for c in sim.trace.channels]
    assert "A1 position" in labels and "PLC1 Q0 Extend" in labels and "Y1a" in labels
    q0 = labels.index("PLC1 Q0 Extend")
    assert sim.trace.data[q0][0] == 0.0 and sim.trace.data[q0][-1] == 1.0
