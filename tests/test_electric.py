"""The electrical network, against values worked out by hand. Logic has to be exactly right; numbers are good to the
stated tolerance, which is what the model promises."""
import math

import pytest
from drawing import Drawing, diff, part, volts


def supply(d, volts_=24.0):
    src = d.add("el.source.dc", "G1", f"{volts_} V")
    return src, (src, "+"), (src, "-")


def test_a_divider():
    """24 V across 1k and 3k: 6 mA, and 18 V at the middle."""
    d = Drawing()
    _src, plus, minus = supply(d)
    r1, r2 = d.add("el.resistor.iec", "R1", "1k"), d.add("el.resistor.iec", "R2", "3k")
    d.wire(plus, (r1, "1"))
    d.wire((r1, "2"), (r2, "1"))
    d.wire((r2, "2"), minus)
    sim = d.sim()
    sim.step()
    assert diff(sim, r2, "1", "2") == pytest.approx(18.0, abs=1e-3)
    assert part(sim, r1).through() == pytest.approx(6e-3, abs=1e-6)


def test_values_come_from_the_drawing_as_it_writes_them():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "12 V")
    r = d.add("el.resistor.iec", "R1", "4k7")
    c = d.add("el.capacitor.pol", "C1", "470 uF")
    fuse = d.add("el.fuse.iec", "F1", "6.3 A")
    coil = d.add("el.coil.iec", "K1", "24 V 3 W")
    timer = d.add("el.coil.ondelay", "KT1", "2.5 s")
    sim = d.sim()
    assert part(sim, src).par["voltage"] == 12.0
    assert part(sim, r).par["ohms"] == 4700.0
    assert part(sim, c).par["farads"] == pytest.approx(470e-6)
    assert part(sim, fuse).par["rating"] == 6.3
    assert part(sim, coil).par["rated"] == 24.0 and part(sim, coil).par["power"] == 3.0
    assert part(sim, timer).par["delay"] == 2.5


def test_an_led_and_its_resistor():
    """(24 - 2) / (1000 + 10) = 21.8 mA"""
    d = Drawing()
    _s, plus, minus = supply(d)
    r, led = d.add("el.resistor.iec", "R1", "1k"), d.add("el.led", "H1")
    d.wire(plus, (r, "1"))
    d.wire((r, "2"), (led, "A"))
    d.wire((led, "K"), minus)
    sim = d.sim()
    sim.step()
    assert part(sim, led).through() == pytest.approx(22.0 / 1010.0, abs=1e-5)
    assert part(sim, led).status() == "Lit"


def test_a_diode_backwards_passes_nothing():
    d = Drawing()
    _s, plus, minus = supply(d)
    r, led = d.add("el.resistor.iec", "R1", "1k"), d.add("el.led", "H1")
    d.wire(plus, (r, "1"))
    d.wire((r, "2"), (led, "K"))
    d.wire((led, "A"), minus)
    sim = d.sim()
    sim.step()
    assert part(sim, led).through() == 0.0
    assert part(sim, led).status() == "Off"
    assert diff(sim, led, "K", "A") == pytest.approx(24.0, abs=0.01)


def test_a_zener_holds_its_voltage():
    """5.1 V, plus 18.9 mA through its 1 ohm"""
    d = Drawing()
    _s, plus, minus = supply(d)
    r, z = d.add("el.resistor.iec", "R1", "1k"), d.add("el.diode.zener", "D1", "5.1 V")
    d.wire(plus, (r, "1"))
    d.wire((r, "2"), (z, "K"))
    d.wire((z, "A"), minus)
    sim = d.sim()
    sim.step()
    assert diff(sim, z, "K", "A") == pytest.approx(5.1 + 18.9e-3, abs=2e-3)


def rung(d, plus, minus, *parts_):
    """Series chain from one rail to another. Each part is (component, in, out)."""
    pins = [plus]
    for c, a, b in parts_:
        pins.append((c, a))
        d.wire(pins[-2], pins[-1])
        pins[-1] = (c, b)
    d.wire(pins[-1], minus)


def latch(d):
    pos, neg = d.add("el.rail.pos", "", "+24V"), d.add("el.rail.neg", "", "0V")
    plus, minus = (pos, "1"), (neg, "1")
    stop, start = d.add("el.pushbutton.nc.iec", "S0"), d.add("el.pushbutton.no.iec", "S1")
    hold, coil = d.add("el.contact.no.iec", "K1"), d.add("el.coil.iec", "K1")
    d.wire(plus, (stop, "1"))
    d.wire((stop, "2"), (start, "1"))
    d.wire((stop, "2"), (hold, "1"))
    d.wire((start, "2"), (coil, "A1"))
    d.wire((hold, "2"), (coil, "A1"))
    d.wire((coil, "A2"), minus)
    return stop, start, hold, coil


def test_a_label_makes_a_line_live_when_nothing_real_feeds_it_and_a_latch_latches():
    d = Drawing()
    stop, start, _hold, coil = latch(d)
    sim = d.sim()
    sim.run(0.05)
    assert not part(sim, coil).energised
    assert diff(sim, coil, "A1", "A2") == pytest.approx(0.0, abs=1e-3)
    sim.command(part(sim, start).part.key, "press")
    sim.run(0.05)
    assert part(sim, coil).energised
    sim.command(part(sim, start).part.key, "release")
    sim.run(0.05)
    assert part(sim, coil).energised, "the K1 contact holds it"
    sim.command(part(sim, stop).part.key, "press")
    sim.run(0.05)
    assert not part(sim, coil).energised
    sim.command(part(sim, stop).part.key, "release")
    sim.run(0.05)
    assert not part(sim, coil).energised, "and it stays off"


def test_supply_lines_with_the_same_name_are_one_line():
    """A PSU feeds one +24V rail, a lamp hangs off another with no wire between: it's the same line, so it's fed by the
    PSU, and its current goes through the PSU."""
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    p1, n1 = d.add("el.rail.pos", "", "+24V"), d.add("el.rail.neg", "", "0V")
    d.wire((src, "+"), (p1, "1"))
    d.wire((src, "-"), (n1, "1"))
    p2, n2 = d.add("el.rail.pos", "", "24 VDC"), d.add("el.rail.neg", "", "0 V")
    lamp = d.add("el.lamp.iec", "H1", "24 V 12 W")
    d.wire((p2, "1"), (lamp, "1"))
    d.wire((lamp, "2"), (n2, "1"))
    sim = d.sim()
    sim.step()
    assert part(sim, lamp).status() == "Lit"
    assert part(sim, src).readings()[1][2] == pytest.approx(0.5, abs=1e-3)
    assert not sim.circuit.el_rails, "the source feeds it, so no line is live merely because of its label"


def test_a_study_can_change_a_live_lines_voltage_from_any_symbol_on_it():
    """What does it do on 17 V? Two rails on one line, with the change made on the second."""
    d = Drawing()
    p1, p2, n = d.add("el.rail.pos", "", "+24V"), d.add("el.rail.pos", "", "24V"), d.add("el.rail.neg", "", "0V")
    coil, lamp = d.add("el.coil.iec", "K1", "24 V 4 W"), d.add("el.lamp.iec", "H1", "24 V 2 W")
    d.wire((p1, "1"), (coil, "A1"))
    d.wire((coil, "A2"), (n, "1"))
    d.wire((p2, "1"), (lamp, "1"))
    d.wire((lamp, "2"), (n, "1"))
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, coil).energised
    part(sim, p2).par["voltage"] = 8.0
    sim.touch()
    sim.run(0.02)
    assert not part(sim, coil).energised, "below its 40% it lets go"
    assert diff(sim, coil, "A1", "A2") == pytest.approx(8.0, abs=0.01)


def test_a_label_does_not_override_what_really_feeds_a_line():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "12 V")
    p, lamp = d.add("el.rail.pos", "", "+24V"), d.add("el.lamp.iec", "H1", "12 V 12 W")
    d.wire((src, "+"), (p, "1"))
    d.wire((p, "1"), (lamp, "1"))
    d.wire((lamp, "2"), (src, "-"))
    sim = d.sim()
    sim.step()
    assert diff(sim, lamp, "1", "2") == pytest.approx(12.0, abs=0.02)


def test_coil_pulls_in_at_75_percent_and_lets_go_at_40():
    d = Drawing()
    src, coil = d.add("el.source.dc", "G1", "24 V"), d.add("el.coil.iec", "K1", "24 V 4 W")
    d.wire((src, "+"), (coil, "A1"))
    d.wire((coil, "A2"), (src, "-"))
    sim = d.sim()
    key = part(sim, src).part.key

    def at(v):
        sim.circuit.part(key).params["voltage"] = v
        sim.touch()
        sim.run(0.05)
        return part(sim, coil).energised
    assert not at(9.0), "it started on 24 V"
    assert not at(17.9)
    assert at(18.1)
    assert at(9.7), "between the two it holds"
    assert not at(9.5)
    assert not at(17.9), "and between them it doesn't pull in again"


def test_coil_draws_what_its_power_says():
    """24 V, 4 W: 144 ohm, 167 mA."""
    d = Drawing()
    src, coil = d.add("el.source.dc", "G1", "24 V"), d.add("el.coil.iec", "K1", "24 V 4 W")
    d.wire((src, "+"), (coil, "A1"))
    d.wire((coil, "A2"), (src, "-"))
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, coil).through() == pytest.approx(24.0 / 144.0, abs=1e-3)


def test_a_coil_with_no_rating_runs_on_its_own_circuit():
    """A 230 V control circuit and a 24 V one in one drawing: each coil takes its circuit's voltage as rated."""
    d = Drawing()
    a, ka = d.add("el.source.ac", "G1", "230 V"), d.add("el.coil.iec", "KA")
    b, kb = d.add("el.source.dc", "G2", "24 V"), d.add("el.coil.iec", "KB")
    d.wire((a, "1"), (ka, "A1"))
    d.wire((ka, "A2"), (a, "2"))
    d.wire((b, "+"), (kb, "A1"))
    d.wire((kb, "A2"), (b, "-"))
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, ka).energised and part(sim, kb).energised
    assert part(sim, ka).rated() == 230.0 and part(sim, kb).rated() == 24.0


def timer_circuit(symbol):
    d = Drawing()
    src, sw = d.add("el.source.dc", "G1", "24 V"), d.add("el.switch.selector.no", "S1")
    coil, contact, lamp = d.add(symbol, "KT1", "1 s"), d.add("el.contact.no.iec", "KT1"), d.add("el.lamp.iec", "H1")
    d.wire((src, "+"), (sw, "1"))
    d.wire((sw, "2"), (coil, "A1"))
    d.wire((coil, "A2"), (src, "-"))
    d.wire((src, "+"), (contact, "1"))
    d.wire((contact, "2"), (lamp, "1"))
    d.wire((lamp, "2"), (src, "-"))
    return d, sw, lamp


def seconds_until(sim, test, limit=5.0):
    t0 = sim.time
    while sim.time - t0 < limit:
        if test():
            return sim.time - t0
        sim.step()
    raise AssertionError("never happened")


def test_on_delay_timer():
    d, sw, lamp = timer_circuit("el.coil.ondelay")
    sim = d.sim()
    sim.run(0.1)
    assert not part(sim, lamp).is_on()
    sim.command(part(sim, sw).part.key, "toggle")
    assert seconds_until(sim, lambda: part(sim, lamp).is_on()) == pytest.approx(1.0, abs=0.03)
    sim.command(part(sim, sw).part.key, "toggle")
    assert seconds_until(sim, lambda: not part(sim, lamp).is_on()) == pytest.approx(0.0, abs=0.03)


def test_on_delay_timer_powered_from_the_start_takes_its_whole_delay():
    d = Drawing()
    src, coil, contact, lamp = d.add("el.source.dc", "G1", "24 V"), d.add("el.coil.ondelay", "KT1", "1 s"), d.add("el.contact.no.iec", "KT1"), d.add("el.lamp.iec", "H1")
    d.wire((src, "+"), (coil, "A1"))
    d.wire((coil, "A2"), (src, "-"))
    d.wire((src, "+"), (contact, "1"))
    d.wire((contact, "2"), (lamp, "1"))
    d.wire((lamp, "2"), (src, "-"))
    sim = d.sim()
    assert part(sim, coil).timer == 0.0
    assert seconds_until(sim, lambda: part(sim, lamp).is_on()) == pytest.approx(1.0, abs=0.03)


def test_on_delay_timer_starts_again_if_interrupted():
    d, sw, lamp = timer_circuit("el.coil.ondelay")
    sim = d.sim()
    key = part(sim, sw).part.key
    sim.command(key, "toggle")
    sim.run(0.7)
    sim.command(key, "toggle")
    sim.run(0.1)
    sim.command(key, "toggle")
    sim.run(0.7)
    assert not part(sim, lamp).is_on()
    assert seconds_until(sim, lambda: part(sim, lamp).is_on()) == pytest.approx(0.3, abs=0.03)


def test_off_delay_timer():
    d, sw, lamp = timer_circuit("el.coil.offdelay")
    sim = d.sim()
    key = part(sim, sw).part.key
    sim.command(key, "toggle")
    assert seconds_until(sim, lambda: part(sim, lamp).is_on()) == pytest.approx(0.0, abs=0.03)
    sim.run(5.0)
    assert part(sim, lamp).is_on()
    sim.command(key, "toggle")
    assert seconds_until(sim, lambda: not part(sim, lamp).is_on()) == pytest.approx(1.0, abs=0.03)


def interlock(d, first, second):
    """Each relay's coil goes through an NC contact of the other. first, second are their tags, in drawing order."""
    src = d.add("el.source.dc", "G1", "24 V")
    k1, k2 = d.add("el.coil.iec", first), d.add("el.coil.iec", second)
    c1, c2 = d.add("el.contact.nc.iec", second), d.add("el.contact.nc.iec", first)
    d.wire((src, "+"), (c1, "1"))
    d.wire((c1, "2"), (k1, "A1"))
    d.wire((k1, "A2"), (src, "-"))
    d.wire((src, "+"), (c2, "1"))
    d.wire((c2, "2"), (k2, "A1"))
    d.wire((k2, "A2"), (src, "-"))
    return k1, k2


def test_an_interlock_race_has_one_answer():
    """Powered at the same moment. The first in drawing order wins, every time, and the other stays off."""
    d = Drawing()
    k1, k2 = interlock(d, "K1", "K2")
    sim = d.sim()
    for _ in range(3):
        sim.reset()
        sim.run(0.2)
        assert part(sim, k1).energised and not part(sim, k2).energised


def test_a_relay_that_interrupts_itself_buzzes_and_says_so():
    d = Drawing()
    src, coil, nc = d.add("el.source.dc", "G1", "24 V"), d.add("el.coil.iec", "K1"), d.add("el.contact.nc.iec", "K1")
    d.wire((src, "+"), (nc, "1"))
    d.wire((nc, "2"), (coil, "A1"))
    d.wire((coil, "A2"), (src, "-"))
    sim = d.sim()
    states = []
    for _ in range(20):
        sim.step()
        states.append(part(sim, coil).energised)
    assert True in states and False in states
    sim.run(1.0)
    assert part(sim, coil).status() == "Chattering"
    assert any("Chattering" in text for _t, _tag, text in sim.events)


def test_a_chain_of_relays_settles_within_one_step():
    d = Drawing()
    src, sw = d.add("el.source.dc", "G1", "24 V"), d.add("el.switch.selector.no", "S1")
    previous = (sw, "2")
    d.wire((src, "+"), (sw, "1"))
    coils = []
    for i in range(8):
        coil = d.add("el.coil.iec", f"K{i}")
        contact = d.add("el.contact.no.iec", f"K{i}")
        d.wire(previous, (coil, "A1"))
        d.wire((coil, "A2"), (src, "-"))
        d.wire(previous, (contact, "1"))
        previous = (contact, "2")
        coils.append(coil)
    sim = d.sim()
    sim.run(0.02)
    sim.command(part(sim, sw).part.key, "toggle")
    sim.step()
    assert all(part(sim, c).energised for c in coils)


def test_an_rc_charges_with_its_time_constant():
    """1k and 1000 uF: tau = 1 s, 15.17 V after one tau. The step's backward Euler gives 15.13 V."""
    d = Drawing()
    _s, plus, minus = supply(d)
    r, c = d.add("el.resistor.iec", "R1", "1k"), d.add("el.capacitor.pol", "C1", "1000 uF")
    d.wire(plus, (r, "1"))
    d.wire((r, "2"), (c, "+"))
    d.wire((c, "-"), minus)
    sim = d.sim()
    sim.run(1.0)
    assert diff(sim, c, "+", "-") == pytest.approx(24.0 * (1 - math.exp(-1)), abs=0.1)
    sim.run(10.0)
    assert diff(sim, c, "+", "-") == pytest.approx(24.0, abs=0.01)
    assert not sim.net.dirty, "and once charged there is nothing left to solve"


def test_an_rl_builds_up_with_its_time_constant():
    """1 H and 10 ohm: tau = 0.1 s, 1.52 A after one tau. Backward Euler in 10 ms steps: 1.47 A."""
    d = Drawing()
    src, r = d.add("el.source.dc", "G1", "24 V"), d.add("el.inductor", "L1", "1000 mH")
    d.wire((src, "+"), (r, "1"))
    d.wire((r, "2"), (src, "-"))
    sim = d.sim()
    part(sim, r).par["rdc"] = 10.0
    sim.touch()
    sim.run(0.1)
    assert part(sim, r).i == pytest.approx(2.4 * (1 - math.exp(-1)), abs=0.08)
    sim.run(2.0)
    assert part(sim, r).i == pytest.approx(2.4, abs=0.01)


def fused_load(d, symbol, rating, load_ohms):
    src, fuse, r = d.add("el.source.dc", "G1", "24 V"), d.add(symbol, "F1", rating), d.add("el.resistor.iec", "R1", f"{load_ohms} ohm")
    d.wire((src, "+"), (fuse, "1"))
    d.wire((fuse, "2"), (r, "1"))
    d.wire((r, "2"), (src, "-"))
    return src, fuse, r


def test_a_fuse_holds_its_rating_and_blows_on_more():
    """24 V through 1.23 ohm in all is 19.5 A, on a 10 A fuse: heat grows at (1.95^2 - 1) a second, and 10 of it blows
    it: 3.6 s."""
    d = Drawing()
    _src, fuse, _r = fused_load(d, "el.fuse.iec", "10 A", 2.4)
    sim = d.sim()
    sim.run(600.0)
    assert part(sim, fuse).status() == "OK"
    d = Drawing()
    _src, fuse, r = fused_load(d, "el.fuse.iec", "10 A", 1.2)
    sim = d.sim()
    assert seconds_until(sim, lambda: part(sim, fuse).status() == "Blown") == pytest.approx(10.0 / ((24 / 1.23 / 10) ** 2 - 1), abs=0.05)
    sim.run(0.05)
    assert part(sim, r).through() == 0.0
    assert any("Blew" in text for _t, _tag, text in sim.events)
    sim.command(part(sim, fuse).part.key, "reset")
    sim.run(0.05)
    assert part(sim, fuse).status() == "OK" and part(sim, r).through() > 19.0


def test_a_big_short_blows_a_fuse_at_once():
    d = Drawing()
    _src, fuse, _r = fused_load(d, "el.fuse.iec", "1 A", 0.1)
    sim = d.sim()
    assert seconds_until(sim, lambda: part(sim, fuse).status() == "Blown") <= 0.02


def test_a_breaker_trips_at_once_at_five_times_its_rating_and_can_be_switched():
    d = Drawing()
    _src, b, r = fused_load(d, "el.breaker.iec", "10 A", 0.4)
    sim = d.sim()
    assert seconds_until(sim, lambda: part(sim, b).status() == "Tripped") <= 0.02
    d = Drawing()
    _src, b, r = fused_load(d, "el.breaker.iec", "10 A", 2.4)
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, r).through() == pytest.approx(24.0 / 2.43, abs=0.01)
    sim.command(part(sim, b).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, b).status() == "Off" and part(sim, r).through() == 0.0


def test_a_transformer_steps_down_and_the_primary_carries_what_the_secondary_uses():
    """230/24 with 24 ohm on it: about 1 A, and about 104 mA on the primary."""
    d = Drawing()
    src, tr, r = d.add("el.source.ac", "G1", "230 V"), d.add("el.transformer", "T1", "230/24 V"), d.add("el.resistor.iec", "R1", "24 ohm")
    d.wire((src, "1"), (tr, "P1"))
    d.wire((tr, "P2"), (src, "2"))
    d.wire((tr, "S1"), (r, "1"))
    d.wire((r, "2"), (tr, "S2"))
    sim = d.sim()
    sim.step()
    assert diff(sim, r, "1", "2") == pytest.approx(24.0, abs=0.1)
    assert part(sim, src).readings()[1][2] == pytest.approx(24.0 / 230.0, abs=2e-3)


def test_a_power_supply_needs_its_input_and_draws_what_it_delivers():
    """24 V 1 A delivered at 90%: 26.7 W, or 116 mA at 230 V."""
    d = Drawing()
    src, sw = d.add("el.source.ac", "G1", "230 V"), d.add("el.switch.selector.no", "Q1")
    psu, r = d.add("el.psu", "T1", "24 V"), d.add("el.resistor.iec", "R1", "24 ohm")
    d.wire((src, "1"), (sw, "1"))
    d.wire((sw, "2"), (psu, "L"))
    d.wire((psu, "N"), (src, "2"))
    d.wire((psu, "+"), (r, "1"))
    d.wire((r, "2"), (psu, "-"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, psu).status() == "No input" and part(sim, r).through() == 0.0
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(0.1)
    assert part(sim, r).through() == pytest.approx(1.0, abs=2e-3)
    assert part(sim, src).readings()[1][2] == pytest.approx(24.0 / 0.9 / 230.0, abs=2e-3)


def test_a_power_supply_drawn_with_no_input_is_just_on():
    d = Drawing()
    psu, r = d.add("el.psu", "T1", "24 V"), d.add("el.resistor.iec", "R1", "24 ohm")
    d.wire((psu, "+"), (r, "1"))
    d.wire((r, "2"), (psu, "-"))
    sim = d.sim()
    sim.step()
    assert part(sim, r).through() == pytest.approx(1.0, abs=2e-3)


def test_a_supply_folds_back_to_its_current_limit():
    d = Drawing()
    psu, r = d.add("el.psu", "T1", "24 V 5 A"), d.add("el.resistor.iec", "R1", "1 ohm")
    d.wire((psu, "+"), (r, "1"))
    d.wire((r, "2"), (psu, "-"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, r).through() == pytest.approx(5.0, abs=1e-3)
    assert part(sim, psu).status().startswith("Overloaded")
    part(sim, r).par["ohms"] = 24.0
    sim.touch()
    sim.run(0.05)
    assert part(sim, r).through() == pytest.approx(1.0, abs=2e-3)
    assert part(sim, psu).status() == "On"


def test_a_dead_short_says_so_and_nothing_breaks():
    d = Drawing()
    src, sw = d.add("el.source.dc", "G1", "24 V"), d.add("el.switch.selector.no", "S1")
    d.wire((src, "+"), (sw, "1"))
    d.wire((sw, "2"), (src, "-"))
    sim = d.sim()
    sim.command(part(sim, sw).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, src).status() == "Short circuit"
    assert any("Short circuit" in text for _t, _tag, text in sim.events)


def common_emitter(d, symbol, base_r, vbase=5.0):
    """12 V, 1k in the collector, base through a resistor from 5 V."""
    v12, v5 = d.add("el.source.dc", "G1", "12 V"), d.add("el.source.dc", "G2", f"{vbase} V")
    q, rc, rb = d.add(symbol, "Q1"), d.add("el.resistor.iec", "R1", "1k"), d.add("el.resistor.iec", "R2", base_r)
    d.wire((v12, "+"), (rc, "1"))
    d.wire((rc, "2"), (q, "C"))
    d.wire((q, "E"), (v12, "-"))
    d.wire((v5, "-"), (v12, "-"))
    d.wire((v5, "+"), (rb, "1"))
    d.wire((rb, "2"), (q, "B"))
    return q, rc


def test_a_transistor_saturates_when_driven_hard():
    """Base 0.43 mA x 100 is more than the 12 mA the collector can have: fully on."""
    d = Drawing()
    q, rc = common_emitter(d, "el.npn", "10k")
    sim = d.sim()
    sim.step()
    assert part(sim, q).mode == "sat"
    assert diff(sim, q, "C", "E") == pytest.approx(0.2, abs=0.01)
    assert part(sim, rc).through() == pytest.approx(11.8e-3, abs=1e-4)


def test_a_transistor_amplifies_in_between():
    """Base (5 - 0.7) / 100k = 43 uA. x 100 = 4.3 mA, so 4.3 V across 1k: 7.7 V at the collector."""
    d = Drawing()
    q, _rc = common_emitter(d, "el.npn", "100k")
    sim = d.sim()
    sim.step()
    assert part(sim, q).mode == "active"
    assert diff(sim, q, "C", "E") == pytest.approx(7.7, abs=0.02)


def test_a_transistor_with_no_base_current_is_off():
    d = Drawing()
    q, rc = common_emitter(d, "el.npn", "10k", vbase=0.3)
    sim = d.sim()
    sim.step()
    assert part(sim, q).mode == "off" and part(sim, rc).through() < 1e-6


def test_pnp_mirrors_npn():
    """Emitter at 12 V, collector through 1k to 0 V, base pulled down to 0 V through 100k: (12 - 0.7) / 100k = 113 uA,
    11.3 mA wanted, 12 V available: not quite saturated."""
    d = Drawing()
    v12 = d.add("el.source.dc", "G1", "12 V")
    q, rc, rb = d.add("el.pnp", "Q1"), d.add("el.resistor.iec", "R1", "1k"), d.add("el.resistor.iec", "R2", "100k")
    d.wire((v12, "+"), (q, "E"))
    d.wire((q, "C"), (rc, "1"))
    d.wire((rc, "2"), (v12, "-"))
    d.wire((q, "B"), (rb, "1"))
    d.wire((rb, "2"), (v12, "-"))
    sim = d.sim()
    sim.step()
    assert part(sim, q).mode == "active"
    assert part(sim, rc).through() == pytest.approx(11.3e-3, abs=2e-4)


def test_a_mosfet_is_a_switch_on_its_gate_voltage():
    d = Drawing()
    v12, gate = d.add("el.source.dc", "G1", "12 V"), d.add("el.switch.spdt", "S1")
    q, r = d.add("el.nmos", "Q1"), d.add("el.resistor.iec", "R1", "1k")
    d.wire((v12, "+"), (r, "1"))
    d.wire((r, "2"), (q, "D"))
    d.wire((q, "S"), (v12, "-"))
    d.wire((gate, "C"), (q, "G"))
    d.wire((gate, "A"), (v12, "-"))
    d.wire((gate, "B"), (v12, "+"))
    sim = d.sim()
    sim.step()
    assert not part(sim, q).on and part(sim, r).through() < 1e-6
    sim.command(part(sim, gate).part.key, "toggle")
    sim.step()
    assert part(sim, q).on and part(sim, r).through() == pytest.approx(12e-3, abs=1e-4)


def test_a_thyristor_latches_until_the_current_falls():
    d = Drawing()
    src, gate_sw, load_sw = d.add("el.source.dc", "G1", "24 V"), d.add("el.switch.selector.no", "S1"), d.add("el.switch.selector.nc", "S2")
    scr, rl, rg = d.add("el.scr", "V1"), d.add("el.resistor.iec", "R1", "24 ohm"), d.add("el.resistor.iec", "R2", "100 ohm")
    d.wire((src, "+"), (load_sw, "1"))
    d.wire((load_sw, "2"), (rl, "1"))
    d.wire((rl, "2"), (scr, "A"))
    d.wire((scr, "K"), (src, "-"))
    d.wire((src, "+"), (gate_sw, "1"))
    d.wire((gate_sw, "2"), (rg, "1"))
    d.wire((rg, "2"), (scr, "G"))
    sim = d.sim()
    sim.step()
    assert not part(sim, scr).on
    sim.command(part(sim, gate_sw).part.key, "toggle")
    sim.step()
    assert part(sim, scr).on
    sim.command(part(sim, gate_sw).part.key, "toggle")
    sim.step()
    assert part(sim, scr).on, "latched"
    assert part(sim, rl).through() == pytest.approx(23.0 / 24.05, abs=1e-2)
    sim.command(part(sim, load_sw).part.key, "toggle")
    sim.step()
    assert not part(sim, scr).on
    sim.command(part(sim, load_sw).part.key, "toggle")
    sim.step()
    assert not part(sim, scr).on, "and stays off"


def test_an_op_amp_with_feedback():
    """Inverting, 10k / 1k, 1 V in: -10 V out."""
    d = Drawing()
    src, op = d.add("el.source.dc", "G1", "1 V"), d.add("el.opamp", "U1")
    ri, rf = d.add("el.resistor.iec", "R1", "1k"), d.add("el.resistor.iec", "R2", "10k")
    gnd = d.add("el.earth", "")
    d.wire((src, "-"), (gnd, "1"))
    d.wire((op, "+"), (gnd, "1"))
    d.wire((src, "+"), (ri, "1"))
    d.wire((ri, "2"), (op, "-"))
    d.wire((op, "-"), (rf, "1"))
    d.wire((rf, "2"), (op, "OUT"))
    sim = d.sim()
    sim.step()
    assert volts(sim, op, "OUT") == pytest.approx(-10.0, abs=0.01)
    part(sim, src).par["voltage"] = 5.0
    sim.touch()
    sim.step()
    assert volts(sim, op, "OUT") == pytest.approx(-13.5, abs=0.2), "the output is at its limit"


def test_an_op_amp_as_a_comparator_saturates_at_its_supply_pins():
    d = Drawing()
    v15, vin = d.add("el.source.dc", "G1", "15 V"), d.add("el.source.dc", "G2", "3 V")
    op = d.add("el.opamp.supply", "U1")
    gnd = d.add("el.earth", "")
    d.wire((v15, "-"), (gnd, "1"))
    d.wire((vin, "-"), (gnd, "1"))
    d.wire((op, "-"), (gnd, "1"))
    d.wire((op, "V-"), (gnd, "1"))
    d.wire((v15, "+"), (op, "V+"))
    d.wire((vin, "+"), (op, "+"))
    sim = d.sim()
    sim.step()
    assert volts(sim, op, "OUT") == pytest.approx(13.5, abs=0.05)
    part(sim, vin).par["voltage"] = -3.0
    sim.touch()
    sim.step()
    assert volts(sim, op, "OUT") == pytest.approx(0.1, abs=0.05)


def regulator_circuit(vin):
    d = Drawing()
    src, reg, r = d.add("el.source.dc", "G1", f"{vin} V"), d.add("el.regulator", "U1", "7805"), d.add("el.resistor.iec", "R1", "100 ohm")
    d.wire((src, "+"), (reg, "IN"))
    d.wire((reg, "OUT"), (r, "1"))
    d.wire((r, "2"), (src, "-"))
    d.wire((reg, "GND"), (src, "-"))
    return d, src, reg, r


def test_a_regulator_holds_its_output_and_the_input_carries_the_load():
    """7805: 5 V, 50 mA in the load, the same out of the 12 V."""
    d, src, reg, r = regulator_circuit(12)
    sim = d.sim()
    sim.step()
    assert part(sim, reg).par["voltage"] == 5.0
    assert diff(sim, r, "1", "2") == pytest.approx(5.0, abs=0.02)
    assert part(sim, src).readings()[1][2] == pytest.approx(0.05, abs=3e-3)


def test_a_regulator_drops_out_when_the_input_gets_low():
    """6 V in, 2 V dropout: 4 V out."""
    d, _src, reg, r = regulator_circuit(6)
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, reg).status().startswith("Dropped out")
    assert diff(sim, r, "1", "2") == pytest.approx(4.0, abs=0.05)


# ---------------------------------------------------------------- logic
def truth(symbol, table):
    """table: {inputs tuple: expected Y}"""
    n = len(next(iter(table)))
    names = "ABCDE"[:n]
    d = Drawing()
    src = d.add("el.source.dc", "G1", "5 V")
    gate = d.add(symbol, "U1")
    switches = []
    for i in range(n):
        sw = d.add("el.switch.spdt", f"S{i}")
        d.wire((sw, "A"), (src, "-"))
        d.wire((sw, "B"), (src, "+"))
        d.wire((sw, "C"), (gate, names[i]))
        switches.append(sw)
    d.wire((src, "-"), (d.add("el.earth", ""), "1"))
    sim = d.sim()
    state = [False] * n
    for inputs, expected in table.items():
        for i, want in enumerate(inputs):
            if state[i] != bool(want):
                sim.command(part(sim, switches[i]).part.key, "toggle")
                state[i] = bool(want)
        sim.step()
        assert (volts(sim, gate, "Y") > 2.5) == bool(expected), f"{symbol} {inputs}"


@pytest.mark.parametrize("symbol,table", [
    ("el.logic.and2", {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1}),
    ("el.logic.nand2", {(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 0}),
    ("el.logic.or2", {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1}),
    ("el.logic.nor2", {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 0}),
    ("el.logic.xor2", {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0}),
    ("el.logic.xnor2", {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 1}),
    ("el.logic.not", {(0,): 1, (1,): 0}),
    ("el.logic.schmitt", {(0,): 0, (1,): 1}),
    ("el.logic.schmitt.not", {(0,): 1, (1,): 0}),
    ("el.logic.and3", {(1, 1, 1): 1, (1, 0, 1): 0}),
    ("el.logic.or4", {(0, 0, 0, 0): 0, (0, 0, 1, 0): 1}),
    ("el.logic.xor3", {(1, 1, 1): 1, (1, 1, 0): 0, (1, 0, 0): 1}),
    ("el.logic.nand5", {(1, 1, 1, 1, 1): 0, (1, 1, 0, 1, 1): 1}),
])
def test_gates(symbol, table):
    truth(symbol, table)


def logic_bench():
    d = Drawing()
    src = d.add("el.source.dc", "G1", "5 V")
    d.wire((src, "-"), (d.add("el.earth", ""), "1"))
    return d, src


def signal(d, src, tag):
    sw = d.add("el.switch.spdt", tag)
    d.wire((sw, "A"), (src, "-"))
    d.wire((sw, "B"), (src, "+"))
    return sw


def test_two_flip_flops_on_one_clock_shift_by_one_place():
    """The second captures what the first held before the edge. A simulator that lets them change in turn gets this
    wrong."""
    d, src = logic_bench()
    data, clock = signal(d, src, "SD"), signal(d, src, "SC")
    f1, f2 = d.add("el.logic.dff", "U1"), d.add("el.logic.dff", "U2")
    d.wire((data, "C"), (f1, "D"))
    d.wire((f1, "Q"), (f2, "D"))
    d.wire((clock, "C"), (f1, "CLK"))
    d.wire((clock, "C"), (f2, "CLK"))
    sim = d.sim()
    sim.step()

    def tick():
        sim.command(part(sim, clock).part.key, "toggle")
        sim.step()
        sim.command(part(sim, clock).part.key, "toggle")
        sim.step()
    sim.command(part(sim, data).part.key, "toggle")
    sim.step()
    assert not part(sim, f1).q["Q"], "no clock yet"
    tick()
    assert part(sim, f1).q["Q"] and not part(sim, f2).q["Q"]
    tick()
    assert part(sim, f1).q["Q"] and part(sim, f2).q["Q"]
    assert not part(sim, f2).q["/Q"]


def test_jk_flip_flop():
    d, src = logic_bench()
    j, k, clock = signal(d, src, "SJ"), signal(d, src, "SK"), signal(d, src, "SC")
    ff = d.add("el.logic.jkff", "U1")
    d.wire((j, "C"), (ff, "J"))
    d.wire((k, "C"), (ff, "K"))
    d.wire((clock, "C"), (ff, "CLK"))
    sim = d.sim()
    sim.step()

    def tick():
        sim.command(part(sim, clock).part.key, "toggle")
        sim.step()
        sim.command(part(sim, clock).part.key, "toggle")
        sim.step()
        return part(sim, ff).q["Q"]
    sim.command(part(sim, j).part.key, "toggle")
    assert tick() is True, "set"
    sim.command(part(sim, k).part.key, "toggle")
    assert tick() is False, "toggle"
    assert tick() is True, "toggle"
    sim.command(part(sim, j).part.key, "toggle")
    assert tick() is False, "reset"
    assert tick() is False, "holds"


def test_d_latch_follows_while_enabled():
    d, src = logic_bench()
    data, enable = signal(d, src, "SD"), signal(d, src, "SE")
    latch_ = d.add("el.logic.dlatch", "U1")
    d.wire((data, "C"), (latch_, "D"))
    d.wire((enable, "C"), (latch_, "E"))
    sim = d.sim()
    sim.step()
    sim.command(part(sim, data).part.key, "toggle")
    sim.step()
    assert not part(sim, latch_).q["Q"]
    sim.command(part(sim, enable).part.key, "toggle")
    sim.step()
    assert part(sim, latch_).q["Q"]
    sim.command(part(sim, enable).part.key, "toggle")
    sim.step()
    sim.command(part(sim, data).part.key, "toggle")
    sim.step()
    assert part(sim, latch_).q["Q"], "held"


def test_full_adder():
    d, src = logic_bench()
    a, b, c = signal(d, src, "SA"), signal(d, src, "SB"), signal(d, src, "SC")
    fa = d.add("el.logic.fulladder", "U1")
    d.wire((a, "C"), (fa, "A"))
    d.wire((b, "C"), (fa, "B"))
    d.wire((c, "C"), (fa, "CIN"))
    sim = d.sim()
    sim.step()
    for switch, y, cout in ((a, True, False), (b, False, True), (c, True, True)):
        sim.command(part(sim, switch).part.key, "toggle")
        sim.step()
        assert part(sim, fa).q["Y"] is y and part(sim, fa).q["COUT"] is cout


def test_a_latch_of_two_nor_gates():
    d, src = logic_bench()
    s, r = signal(d, src, "SS"), signal(d, src, "SR")
    g1, g2 = d.add("el.logic.nor2", "U1"), d.add("el.logic.nor2", "U2")
    d.wire((r, "C"), (g1, "A"))
    d.wire((g2, "Y"), (g1, "B"))
    d.wire((s, "C"), (g2, "A"))
    d.wire((g1, "Y"), (g2, "B"))
    sim = d.sim()
    sim.step()
    sim.command(part(sim, s).part.key, "toggle")
    sim.step()
    assert part(sim, g1).q["Y"] and not part(sim, g2).q["Y"]
    sim.command(part(sim, s).part.key, "toggle")
    sim.step()
    assert part(sim, g1).q["Y"], "holds"
    sim.command(part(sim, r).part.key, "toggle")
    sim.step()
    assert not part(sim, g1).q["Y"]
    sim.command(part(sim, r).part.key, "toggle")
    sim.step()
    assert not part(sim, g1).q["Y"], "holds"


def test_a_ring_of_inverters_oscillates_instead_of_hanging():
    d, _src = logic_bench()
    gates = [d.add("el.logic.not", f"U{i}") for i in range(3)]
    for a, b in zip(gates, gates[1:] + gates[:1]):
        d.wire((a, "Y"), (b, "A"))
    sim = d.sim()
    seen = set()
    for _ in range(20):
        sim.step()
        seen.add(part(sim, gates[0]).q["Y"])
    assert seen == {True, False}
    assert any("oscillating" in text for _t, _tag, text in sim.events)


def test_logic_runs_on_the_regulator_in_its_circuit():
    d = Drawing()
    src, reg, cap = d.add("el.source.dc", "G1", "12 V"), d.add("el.regulator", "U1", "7805"), d.add("el.capacitor", "C1", "10 uF")
    gate = d.add("el.logic.not", "U2")
    d.wire((src, "+"), (reg, "IN"))
    d.wire((reg, "OUT"), (cap, "1"))
    d.wire((cap, "2"), (src, "-"))
    d.wire((reg, "GND"), (src, "-"))
    d.wire((reg, "OUT"), (gate, "Y"))
    d.wire((src, "-"), (d.add("el.earth", ""), "1"))
    sim = d.sim()
    sim.step()
    assert part(sim, gate)._vhigh() == 5.0


# ---------------------------------------------------------------- three phases
def three_phase(*extra):
    d = Drawing()
    rails = [d.add("el.rail.pos", "", f"L{i} 400V") for i in (1, 2, 3)]
    motor = d.add("el.motor.3ph", "M1", "3 kW")
    return d, rails, motor


def wire_motor(d, rails, motor, order=("U1", "V1", "W1")):
    for rail, pin in zip(rails, order):
        d.wire((rail, "1"), (motor, pin))


def test_three_phase_motor_draws_its_line_current():
    """3 kW at 400 V: P / (sqrt(3) V) = 4.33 A in each line."""
    d, rails, motor = three_phase()
    wire_motor(d, rails, motor)
    sim = d.sim()
    sim.run(0.02)
    b = part(sim, motor)
    assert b.running and b.status() == "Running"
    amps = [abs(i) for i in b.currents(sim.net.v).values()]
    assert amps == pytest.approx([3000.0 / (math.sqrt(3) * 400.0)] * 3, abs=0.02)
    assert abs(sim.net.v[b.star]) < 0.5, "balanced, so the star point sits at neutral"


def test_swapping_two_phases_reverses_a_three_phase_motor():
    d, rails, motor = three_phase()
    wire_motor(d, rails, motor, ("V1", "U1", "W1"))
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, motor).status() == "Running, reversed"


def test_a_lost_phase_stops_a_motor_starting_and_overloads_a_running_one():
    d, rails, motor = three_phase()
    breaker = d.add("el.switch.selector.no", "Q1")
    d.wire((rails[0], "1"), (motor, "U1"))
    d.wire((rails[1], "1"), (motor, "V1"))
    d.wire((rails[2], "1"), (breaker, "1"))
    d.wire((breaker, "2"), (motor, "W1"))
    sim = d.sim()
    sim.run(0.05)
    assert part(sim, motor).status().startswith("Won't start")
    assert not part(sim, motor).running
    sim.command(part(sim, breaker).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, motor).status() == "Running"
    healthy = max(abs(i) for i in part(sim, motor).currents(sim.net.v).values())
    sim.command(part(sim, breaker).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, motor).status().startswith("Running on two phases")
    now = max(abs(i) for i in part(sim, motor).currents(sim.net.v).values())
    assert now == pytest.approx(math.sqrt(3) * healthy, rel=0.02), "the sqrt(3) of a real motor single-phasing"


def test_a_starter_with_overload_stops_itself():
    """Contactor K1, overload F1 in the motor circuit, and F1's NC contact in the K1 coil circuit. This motor drives nothing,
    so it draws its rating."""
    d, rails, motor = three_phase()
    k_main, f1 = d.add("el.contact.3no", "K1"), d.add("el.overload.3p", "F1", "1.5 A")
    pos, neg = d.add("el.rail.pos", "", "+24V"), d.add("el.rail.neg", "", "0V")
    stop, coil = d.add("el.contact.nc.iec", "F1"), d.add("el.coil.iec", "K1")
    start = d.add("el.switch.selector.no", "S1")
    for rail, a, b, c, e, pin in zip(rails, "135", "246", "135", "246", ("U1", "V1", "W1")):
        d.wire((rail, "1"), (k_main, a))
        d.wire((k_main, b), (f1, c))
        d.wire((f1, e), (motor, pin))
    d.wire((pos, "1"), (start, "1"))
    d.wire((start, "2"), (stop, "1"))
    d.wire((stop, "2"), (coil, "A1"))
    d.wire((coil, "A2"), (neg, "1"))
    sim = d.sim()
    sim.run(0.05)
    assert not part(sim, motor).running
    sim.command(part(sim, start).part.key, "toggle")
    sim.run(0.05)
    assert part(sim, coil).energised and part(sim, motor).running
    # 4.33 A on a 1.5 A setting: (2.89^2 - 1.1) = 7.2 a second, 400 of it: 55 s
    t = seconds_until(sim, lambda: part(sim, f1).tripped, limit=120.0)
    assert t == pytest.approx(400.0 / ((3000 / (math.sqrt(3) * 400) / 1.5) ** 2 - 1.1), rel=0.05)
    sim.run(0.05)
    assert not part(sim, coil).energised and not part(sim, motor).running
    sim.command(part(sim, f1).part.key, "reset")
    sim.run(0.05)
    assert part(sim, coil).energised, "the selector is still on: it starts again once reset"


def test_potentiometer_divides_by_its_wiper():
    d = Drawing()
    src, pot = d.add("el.source.dc", "G1", "10 V"), d.add("el.potentiometer.iec", "R1", "10k")
    d.wire((src, "+"), (pot, "1"))
    d.wire((pot, "2"), (src, "-"))
    sim = d.sim()
    part(sim, pot).par["wiper"] = 25.0
    sim.touch()
    sim.step()
    assert diff(sim, pot, "3", "2") == pytest.approx(7.5, abs=0.01)


def test_meters_read_without_disturbing():
    d = Drawing()
    _s, plus, minus = supply(d)
    r, vm, am = d.add("el.resistor.iec", "R1", "1k"), d.add("el.meter.v", "P1"), d.add("el.meter.a", "P2")
    d.wire(plus, (am, "1"))
    d.wire((am, "2"), (r, "1"))
    d.wire((r, "2"), minus)
    d.wire((vm, "1"), (r, "1"))
    d.wire((vm, "2"), (r, "2"))
    sim = d.sim()
    sim.step()
    assert part(sim, vm).value() == pytest.approx(24.0, abs=0.01)
    assert part(sim, am).value() == pytest.approx(24e-3, abs=1e-5)


def test_isolated_circuits_are_separate():
    """A transformer's secondary has no connection to the primary, so each has its own 0 V."""
    d = Drawing()
    src, tr, r = d.add("el.source.ac", "G1", "230 V"), d.add("el.transformer", "T1", "230/24 V"), d.add("el.resistor.iec", "R1", "24 ohm")
    earth = d.add("el.earth", "")
    d.wire((src, "2"), (earth, "1"))
    d.wire((src, "1"), (tr, "P1"))
    d.wire((tr, "P2"), (src, "2"))
    d.wire((tr, "S1"), (r, "1"))
    d.wire((r, "2"), (tr, "S2"))
    sim = d.sim()
    sim.step()
    assert part(sim, tr).t["S2"] in sim.circuit.el_fixed
    assert sim.net.v[part(sim, tr).t["S1"]] == pytest.approx(24.0, abs=0.1)


def test_nothing_connected_is_not_a_problem():
    d = Drawing()
    for symbol in ("el.resistor.iec", "el.coil.iec", "el.contact.no.iec", "el.diode", "el.npn", "el.nmos", "el.opamp",
                   "el.logic.and2", "el.motor.3ph", "el.transformer", "el.psu", "el.plc", "el.sensor.analog", "el.sensor.loop",
                   "el.sensor.prox.pnp", "el.regulator", "el.scr", "el.capacitor", "el.inductor", "el.rectifier.bridge"):
        d.add(symbol, "X" + symbol[3:7])
    sim = d.sim()
    sim.run(0.1)
    assert all(abs(x) < 100.0 for x in sim.net.v)


def test_tubes_are_marked_not_simulated():
    d = Drawing()
    tube = d.add("el.tube.triode", "V1")
    sim = d.sim()
    sim.run(0.02)
    assert part(sim, tube).status() == "Not simulated"
    assert any("V1" in i.text and i.level != "info" or "not simulated" in i.text.lower() for i in sim.circuit.issues)


def test_a_rectifier_gives_dc_in_proportion_and_only_sources():
    """24 V AC, full-wave: 0.9 x 24 = 21.6 V DC."""
    d = Drawing()
    src, br, r = d.add("el.source.ac", "G1", "24 V"), d.add("el.rectifier.bridge", "V1"), d.add("el.resistor.iec", "R1", "100 ohm")
    d.wire((src, "1"), (br, "AC1"))
    d.wire((br, "AC2"), (src, "2"))
    d.wire((br, "+"), (r, "1"))
    d.wire((r, "2"), (br, "-"))
    sim = d.sim()
    sim.run(0.03)
    assert diff(sim, r, "1", "2") == pytest.approx(21.6, abs=0.05)
    assert part(sim, r).through() == pytest.approx(0.216, abs=1e-3)
    assert part(sim, src).readings()[1][2] == pytest.approx(21.6 ** 2 / 100 / 24, abs=2e-3), "the power comes from the input"


def test_a_diode_bridge_of_separate_diodes_rectifies():
    """Two forward drops out of 24 V, across the load, with the right polarity whichever way the source is."""
    d = Drawing()
    src, r = d.add("el.source.ac", "G1", "24 V"), d.add("el.resistor.iec", "R1", "100 ohm")
    d1, d2, d3, d4 = (d.add("el.diode", f"D{i}") for i in range(1, 5))
    d.wire((src, "1"), (d1, "A"))
    d.wire((src, "1"), (d3, "K"))
    d.wire((src, "2"), (d2, "A"))
    d.wire((src, "2"), (d4, "K"))
    d.wire((d1, "K"), (d2, "K"))
    d.wire((d1, "K"), (r, "1"))
    d.wire((d3, "A"), (d4, "A"))
    d.wire((r, "2"), (d3, "A"))
    sim = d.sim()
    sim.run(0.03)
    assert diff(sim, r, "1", "2") == pytest.approx(24.0 - 1.4, abs=0.1)
    assert part(sim, d1).mode == 1 and part(sim, d4).mode == 1 and part(sim, d2).mode == 0


def test_an_autotransformer_takes_its_share_of_the_winding():
    d = Drawing()
    src, tr, r = d.add("el.source.ac", "G1", "230 V"), d.add("el.autotransformer", "T1"), d.add("el.resistor.iec", "R1", "1k")
    d.wire((src, "1"), (tr, "1"))
    d.wire((tr, "2"), (src, "2"))
    d.wire((tr, "3"), (r, "1"))
    d.wire((r, "2"), (tr, "2"))
    sim = d.sim()
    sim.step()
    assert diff(sim, r, "1", "2") == pytest.approx(115.0, abs=1.0)


def test_a_centre_tap_gives_half_each_side():
    d = Drawing()
    src, tr, r1, r2 = d.add("el.source.ac", "G1", "230 V"), d.add("el.transformer.ct", "T1", "230/24 V"), d.add("el.resistor.iec", "R1", "1k"), d.add("el.resistor.iec", "R2", "1k")
    d.wire((src, "1"), (tr, "P1"))
    d.wire((tr, "P2"), (src, "2"))
    d.wire((tr, "S1"), (r1, "1"))
    d.wire((r1, "2"), (tr, "CT"))
    d.wire((tr, "CT"), (r2, "1"))
    d.wire((r2, "2"), (tr, "S2"))
    sim = d.sim()
    sim.step()
    assert diff(sim, r1, "1", "2") == pytest.approx(12.0, abs=0.05)
    assert diff(sim, r2, "1", "2") == pytest.approx(12.0, abs=0.05)


def test_a_transformer_with_no_supply_is_dead():
    d = Drawing()
    tr, r = d.add("el.transformer", "T1", "230/24 V"), d.add("el.resistor.iec", "R1", "24 ohm")
    d.wire((tr, "S1"), (r, "1"))
    d.wire((r, "2"), (tr, "S2"))
    sim = d.sim()
    sim.step()
    assert part(sim, r).through() < 1e-6 and part(sim, tr).status() == "No supply"


def test_a_sensor_with_its_return_loose_stays_off_and_settles():
    """Its own load keeps the loose wire at the same voltage, so it reads no supply, rather than flipping for ever."""
    d = Drawing()
    src, prox, ana = d.add("el.source.dc", "G1", "24 V"), d.add("el.sensor.prox.pnp", "B1"), d.add("el.sensor.analog", "B2")
    d.wire((src, "+"), (prox, "+"))
    d.wire((src, "+"), (ana, "+"))
    sim = d.sim()
    sim.run(0.1)
    assert part(sim, prox).status() == "No supply" and part(sim, ana).status() == "No supply"
    assert not sim.net.dirty


def test_when_nothing_changes_nothing_is_solved():
    d = Drawing()
    stop, _start, _hold, _coil = latch(d)
    sim = d.sim()
    sim.run(0.1)
    before = sim.net._solves
    sim.run(5.0)
    assert sim.net._solves == before
    sim.command(part(sim, stop).part.key, "press")
    sim.run(0.1)
    assert sim.net._solves > before


def test_big_circuit_stays_quick_enough_to_run_live():
    """Eighty rungs, all relays, must run faster than real time on any machine: well under a step's 10 ms per step."""
    import time
    d = Drawing()
    src, sw = d.add("el.source.dc", "G1", "24 V"), d.add("el.switch.selector.no", "S1")
    d.wire((src, "+"), (sw, "1"))
    for i in range(80):
        coil, c, lamp = d.add("el.coil.iec", f"K{i}"), d.add("el.contact.no.iec", f"K{i}"), d.add("el.lamp.iec", f"H{i}")
        d.wire((sw, "2"), (coil, "A1"))
        d.wire((coil, "A2"), (src, "-"))
        d.wire((src, "+"), (c, "1"))
        d.wire((c, "2"), (lamp, "1"))
        d.wire((lamp, "2"), (src, "-"))
    sim = d.sim()
    t0 = time.perf_counter()
    sim.command(part(sim, sw).part.key, "toggle")
    sim.step()
    first = time.perf_counter() - t0
    assert part(sim, coil).energised
    t0 = time.perf_counter()
    sim.run(1.0)
    assert time.perf_counter() - t0 < 1.0, "a settled network costs almost nothing"
    assert first < 5.0, "and even everything changing at once is a moment"


@pytest.mark.parametrize("symbol,label", [("el.resistor.iec", "0 ohm"), ("el.coil.iec", "0 V 0 W"), ("el.lamp.iec", "0 W"), ("el.fuse.iec", "0 A"),
                                          ("el.transformer", "0/0 V"), ("el.capacitor", "0 uF"), ("el.inductor", "0 mH"), ("el.psu", "0 V 0 A"),
                                          ("el.regulator", "0 V"), ("el.diode.zener", "0 V"), ("el.source.dc", "0 V"), ("el.motor", "0 V 0 W")])
def test_a_label_saying_zero_divides_nothing(symbol, label):
    d = Drawing()
    src, c = d.add("el.source.dc", "G1", "24 V"), d.add(symbol, "X1", label)
    names = [t.name for t in c.terminal_defs()]
    d.wire((src, "+"), (c, names[0]))
    d.wire((c, names[1]), (src, "-"))
    sim = d.sim()
    sim.run(0.05)
    assert all(math.isfinite(abs(x)) for x in sim.net.v)
    part(sim, c).readings()


def test_a_study_file_saying_zero_divides_nothing():
    from fluidworx import circuit
    d = Drawing()
    src, r = d.add("el.source.dc", "G1", "24 V"), d.add("el.resistor.iec", "R1", "1k")
    d.wire((src, "+"), (r, "1"))
    d.wire((r, "2"), (src, "-"))
    c = d.build()
    circuit.apply_study_params(c, {f"{p.key[0]}/{p.key[1]}": {"ohms": 0.0, "rint": 0.0} for p in c.parts})
    from fluidworx import engine
    sim = engine.Simulator(c)
    sim.run(0.02)
    assert all(math.isfinite(abs(x)) for x in sim.net.v)


def test_a_line_joining_the_two_sides_is_reported():
    d = Drawing()
    tank, coil = d.add("fl.hyd.tank", "Z1"), d.add("el.coil.iec", "K1")
    d.wire((tank, "T"), (coil, "A1"))
    assert any("joins a fluid port" in i.text for i in d.build().issues)


def _random_circuit(r):
    from fluidworx.vendor.openschematix import symbols
    electrical = [s.id for s in symbols.builtin_symbols() if s.id.startswith("el.") and symbols.geometry(s.id).terminals]
    fluid = ["fl.hyd.pump", "fl.hyd.tank", "fl.hyd.dcv", "fl.hyd.cyl.double", "fl.hyd.relief", "fl.hyd.gauge", "fl.hyd.pressure.switch",
             "fl.hyd.valve.prop.nc", "fl.hyd.motor"]
    labels = ["", "24 V", "12 V 4 W", "1k", "100 uF", "10 mH", "5 s", "5 A", "230/24 V", "0-250 bar", "4-20 mA", "+24V", "0V", "L1", "L2",
              "L3", "N", "7805", "0 V", "1000000 V"]
    tags = ["K1", "K2", "Y1", "Y1a", "Y1b", "S1", "M1", "PT1", "A1", "F1", ""]
    senses = ["A1 100%", "A1 0%", "A1 > 50%", "PT1 > 10 bar", "A1", "PT1", "M1 > 10 rpm", "nonsense", "A9 50%"]
    programs = ["Q0 := I0;", "Q0 := NOT Q0;", "AO0 := AI0 * 2.0; Q1 := I1 AND I2;", "WHILE TRUE DO Q0 := TRUE; END_WHILE;", "Q0 := 1/0 > 0;"]
    d = Drawing(sheets=2)
    pins = []
    for _ in range(r.randint(3, 30)):
        symbol = r.choice(electrical) if r.random() < 0.85 else r.choice(fluid)
        props = {"Senses": r.choice(senses)} if r.random() < 0.2 else {}
        params = {}
        if symbol == "el.plc" and r.random() < 0.7:
            params = {"di": 4, "do": 3, "ai": 1, "ao": 1, "do_type": r.choice(["source", "sink", "relay"]), "tags": {},
                      "program": {"pous": [{"name": "M", "lang": "st", "source": r.choice(programs)}]}}
        c = d.add(symbol, r.choice(tags), r.choice(labels), params=params, props=props, sheet=1 if symbol.startswith("el.") else 0)
        pins += [(c, t.name) for t in c.terminal_defs()]
    for group in ([p for p in pins if p[0].symbol.startswith("el.")], [p for p in pins if p[0].symbol.startswith("fl.")]):
        if len(group) >= 2:
            for _ in range(int(len(group) * r.uniform(0.3, 1.2))):
                d.wire(*r.sample(group, 2))
    return d


@pytest.mark.parametrize("seed", range(40))
def test_any_nonsense_drawn_runs_without_crashing(seed):
    """Anything can be drawn. Whatever it is, the numbers stay numbers and nothing raises."""
    import random
    from fluidworx.units import Units
    r = random.Random(seed)
    sim = _random_circuit(r).sim()
    for _ in range(r.randint(5, 30)):
        sim.step()
        if r.random() < 0.3:
            k = r.choice(list(sim.parts))
            actions = sim.parts[k].actions()
            if actions:
                sim.command(k, r.choice(actions)[0])
        if r.random() < 0.05:
            sim.reset()
    for b in sim.parts.values():
        b.status(sim.p)
        b.readings(sim.p)
    for b in sim.net.parts:
        b.badge(Units("metric"))
    sim.net.terminal_currents()
    assert all(math.isfinite(abs(x)) for x in sim.net.v)
    assert all(math.isfinite(x) for x in sim.p)


# ---------------------------------------------------------------- races
def races(sim):
    return [text for _t, _tag, text in sim.events if text.startswith("Race:")]


def test_an_interlock_race_says_so():
    """Either relay could win on a real machine, so a result that shows one winner has to say that."""
    d = Drawing()
    interlock(d, "K1", "K2")
    sim = d.sim()
    said = races(sim)
    assert len(said) == 1
    assert "K1 and K2" in said[0] and "drawn first" in said[0] and "either way" in said[0]
    assert sim.net.races == [(0.0, "K1", "K2")]


def test_the_warning_follows_the_drawing_order():
    d = Drawing()
    k2, k1 = interlock(d, "K2", "K1")
    sim = d.sim()
    sim.run(0.2)
    assert part(sim, k2).energised and not part(sim, k1).energised
    assert "K2 and K1" in races(sim)[0]


def test_a_race_is_said_once_a_run_and_again_after_a_reset():
    d = Drawing()
    interlock(d, "K1", "K2")
    sim = d.sim()
    sim.run(0.5)
    assert len(races(sim)) == 1
    sim.reset()
    sim.run(0.5)
    assert len(races(sim)) == 1


def test_trying_the_other_order_leaves_nothing_behind():
    """The other order is only looked at. It doesn't change who won, what they read, or how often they've flipped."""
    d = Drawing()
    k1, k2 = interlock(d, "K1", "K2")
    sim = d.sim()
    assert part(sim, k1).flip_times == [0.0] and part(sim, k2).flip_times == []
    assert part(sim, k1).energised and not part(sim, k2).energised
    assert not sim.net.what_if
    # K1's NC contact has opened in K2's circuit, and K2 has nothing across it
    assert part(sim, k2).volts(sim.net.v) == pytest.approx(0.0, abs=0.01)
    assert part(sim, k1).volts(sim.net.v) == pytest.approx(24.0, abs=0.1)


def test_relays_that_only_share_a_supply_dont_race():
    d = Drawing()
    src, button = d.add("el.source.dc", "G1", "24 V"), d.add("el.pushbutton.no.iec", "S1")
    d.wire((src, "+"), (button, "1"))
    coils = [d.add("el.coil.iec", f"K{i}") for i in range(4)]
    for coil in coils:
        d.wire((button, "2"), (coil, "A1"))
        d.wire((coil, "A2"), (src, "-"))
    sim = d.sim()
    sim.command(part(sim, button).part.key, "press")
    sim.run(0.1)
    assert all(part(sim, c).energised for c in coils)
    assert races(sim) == []


def _one_way(d):
    """A button feeds K1 directly, and K2 through an NC contact of K1. K1 always ends up on and K2 off, whichever goes first."""
    src, button = d.add("el.source.dc", "G1", "24 V"), d.add("el.pushbutton.no.iec", "S1")
    k2, k1 = d.add("el.coil.iec", "K2"), d.add("el.coil.iec", "K1")
    nc = d.add("el.contact.nc.iec", "K1")
    d.wire((src, "+"), (button, "1"))
    d.wire((button, "2"), (k1, "A1"))
    d.wire((k1, "A2"), (src, "-"))
    d.wire((button, "2"), (nc, "1"))
    d.wire((nc, "2"), (k2, "A1"))
    d.wire((k2, "A2"), (src, "-"))
    return src, button, k1, k2


def test_an_order_that_changes_nothing_in_the_end_is_not_a_race():
    d = Drawing()
    _src, button, k1, k2 = _one_way(d)
    sim = d.sim()
    sim.command(part(sim, button).part.key, "press")
    sim.run(0.1)
    assert part(sim, k1).energised and not part(sim, k2).energised
    assert races(sim) == []


def test_a_blip_that_latches_something_is_a_race():
    """K2 only gets a moment if it goes first, but that moment is enough to latch K3. So the order decides whether K3 is on."""
    d = Drawing()
    src, button, k1, k2 = _one_way(d)
    k3, seal, set_k3 = d.add("el.coil.iec", "K3"), d.add("el.contact.no.iec", "K3"), d.add("el.contact.no.iec", "K2")
    d.wire((src, "+"), (seal, "1"))
    d.wire((seal, "2"), (k3, "A1"))
    d.wire((src, "+"), (set_k3, "1"))
    d.wire((set_k3, "2"), (k3, "A1"))
    d.wire((k3, "A2"), (src, "-"))
    sim = d.sim()
    sim.command(part(sim, button).part.key, "press")
    sim.run(0.2)
    assert len(races(sim)) == 1 and "K2" in races(sim)[0] and "K1" in races(sim)[0]


def test_many_relays_changing_together_dont_cost_a_solve_each_per_relay():
    """A main relay bringing in thirty others mustn't stall the window while they're compared."""
    d = Drawing()
    src, button = d.add("el.source.dc", "G1", "24 V"), d.add("el.pushbutton.no.iec", "S1")
    d.wire((src, "+"), (button, "1"))
    for i in range(30):
        coil = d.add("el.coil.iec", f"K{i}")
        d.wire((button, "2"), (coil, "A1"))
        d.wire((coil, "A2"), (src, "-"))
    sim = d.sim()
    sim.step()
    before = sim.net._solves
    sim.command(part(sim, button).part.key, "press")
    sim.step()
    assert sim.net._solves - before < 120      # about one a relay to change it, one a relay to look, and no more
    assert races(sim) == []


def test_a_race_between_timers_timing_out_together():
    """Two timers with the same delay, each cutting the other off, are the same race a moment later."""
    d = Drawing()
    src = d.add("el.source.dc", "G1", "24 V")
    t1, t2 = d.add("el.coil.ondelay", "KT1", "0.2 s"), d.add("el.coil.ondelay", "KT2", "0.2 s")
    k1, k2 = d.add("el.coil.iec", "K1"), d.add("el.coil.iec", "K2")
    for t in (t1, t2):
        d.wire((src, "+"), (t, "A1"))
        d.wire((t, "A2"), (src, "-"))
    no1, no2 = d.add("el.contact.no.iec", "KT1"), d.add("el.contact.no.iec", "KT2")
    nc1, nc2 = d.add("el.contact.nc.iec", "K2"), d.add("el.contact.nc.iec", "K1")
    d.wire((src, "+"), (no1, "1"))
    d.wire((no1, "2"), (nc1, "1"))
    d.wire((nc1, "2"), (k1, "A1"))
    d.wire((k1, "A2"), (src, "-"))
    d.wire((src, "+"), (no2, "1"))
    d.wire((no2, "2"), (nc2, "1"))
    d.wire((nc2, "2"), (k2, "A1"))
    d.wire((k2, "A2"), (src, "-"))
    sim = d.sim()
    sim.run(0.15)
    assert races(sim) == []
    sim.run(0.2)
    assert len(races(sim)) == 1 and sim.net.races[0][0] > 0.15
