"""Valves the machine operates itself: a roller, plunger or cam, tied to a cylinder."""
import pytest
from conftest import run_example
from drawing import Drawing, part

from fluidworx import circuit, engine, study as st
from fluidworx.vendor.openschematix import simlinks
from fluidworx.vendor.openschematix.symbols.fluid import default_valve_params


def tag(sim, name):
    return next(b for b in sim.parts.values() if b.part.tag == name)


def roller_valve(d, des, left=("roller",), right=("spring",), props=None, medium="pneu", vtype="3/2"):
    return d.add(f"fl.{medium}.dcv", des, params={**default_valve_params(medium, vtype), "left": list(left), "right": list(right)}, props=props or {})


def rig(props=None, des="V1", cylinder="A1"):
    """A cylinder on a held-over valve, and a roller valve looking at it, feeding a gauge."""
    d = Drawing()
    comp = d.add("fl.pneu.compressor", "P1", "6 bar")
    cyl = d.add("fl.pneu.cyl.double", cylinder, "40/16x100")
    main = d.add("fl.pneu.dcv", "V9", params={**default_valve_params("pneu", "5/2"), "left": ["lever"], "right": ["spring"]})
    v = roller_valve(d, des, props=props)
    gauge = d.add("fl.pneu.gauge", "G1")
    d.wire((comp, "2"), (main, "1"))
    d.wire((comp, "2"), (v, "1"))
    d.wire((main, "4"), (cyl, "A"))
    d.wire((main, "2"), (cyl, "B"))
    d.wire((v, "2"), (gauge, gauge.terminal_defs()[0].name))
    return d, main, cyl, v, gauge


def test_a_roller_shifts_its_valve_at_the_end_of_the_stroke():
    d, main, cyl, v, gauge = rig({"Senses": "A1 100%"})
    sim = d.sim()
    b = part(sim, v)
    sim.run(0.5)
    assert b.position == b.normal and part(sim, cyl).fraction == 0.0
    assert sim.p[part(sim, gauge).node(0)] == pytest.approx(0.0, abs=1e4)
    sim.command(part(sim, main).part.key, "left")
    t = 0.0
    while part(sim, cyl).fraction < 0.98 and t < 15.0:
        sim.step()
        t += sim.dt
        assert b.roller["left"] == (part(sim, cyl).fraction >= 0.99) or part(sim, cyl).fraction > 0.97
    sim.run(2.0)
    assert part(sim, cyl).fraction == 1.0 and b.roller["left"] and b.position != b.normal
    assert sim.p[part(sim, gauge).node(0)] > 1e5, "air through to the gauge"
    # and it lets go when the rod leaves
    sim.command(part(sim, main).part.key, "left")
    sim.run(5.0)
    assert part(sim, cyl).fraction == 0.0 and not b.roller["left"] and b.position == b.normal


def test_a_roller_already_on_its_cam_holds_from_the_start():
    d, _main, _cyl, v, _gauge = rig({"Senses": "A1 0%"})
    sim = d.sim()
    b = part(sim, v)
    assert b.roller["left"] and b.position != b.normal
    sim.run(0.2)
    sim.reset()
    assert b.roller["left"] and b.position != b.normal


def test_a_position_by_length_and_a_long_cam():
    for props, want in (({"Senses": "A1 50 mm"}, True), ({"Senses": "A1 > 50%"}, True), ({"Senses": "A1 > 150 mm"}, False)):
        d, main, cyl, v, _gauge = rig(props)
        sim = d.sim()
        sim.command(part(sim, main).part.key, "left")
        seen = False
        for _ in range(1500):
            sim.step()
            seen = seen or part(sim, v).roller["left"]
        assert seen is want, props
        assert part(sim, cyl).fraction == 1.0


def test_the_tag_says_it_on_a_pneumatic_drawing():
    """a1 is at the end of cylinder A's stroke, and a0 at the start, as these circuits are always drawn."""
    d, _m, _c, _v, _g = rig(des="a1", cylinder="A")
    c = d.build()
    assert [link.text for link in c.links if link.kind == "roller"] == ["The left-hand roller of a1 senses A 100%"]
    d, _m, _c, v, _g = rig(des="a0", cylinder="A")
    sim = d.sim()
    assert part(sim, v).roller["left"]


def test_senses_beats_the_tag_and_a_study_can_set_it():
    d, _m, cyl, v, _g = rig({"Senses": "A 100%"}, des="a0", cylinder="A")
    sim = d.sim()
    assert not part(sim, v).roller["left"] and part(sim, cyl).fraction == 0.0
    d, _m, _c, v, _g = rig()
    uid = d.doc.uid
    assert not d.build().links or all(link.kind != "roller" for link in d.build().links)
    sim = d.sim({f"{uid}/{v.id}": {"Senses": "A1 0%"}})
    assert part(sim, v).roller["left"]


def test_a_roller_on_each_side():
    d = Drawing()
    comp = d.add("fl.pneu.compressor", "P1", "6 bar")
    cyl = d.add("fl.pneu.cyl.double", "A1", "40/16x100", props={"Start": "50"})
    v = roller_valve(d, "V1", ("roller",), ("cam",), {simlinks.SENSES_A: "A1 0%", simlinks.SENSES_B: "A1 100%"}, vtype="5/2")
    d.wire((comp, "2"), (v, "1"))
    d.wire((v, "4"), (cyl, "A"))
    d.wire((v, "2"), (cyl, "B"))
    sim = d.sim()
    b = part(sim, v)
    assert {link.side for link in sim.circuit.links if link.kind == "roller"} == {"left", "right"}
    assert b.roller["left"] and not b.roller["right"], "at the start of the stroke"
    sim.run(6.0)
    # it reciprocates: extends until the right-hand cam, retracts until the left-hand roller
    assert any(b.part.tag == "A1" for b in sim.actuators())
    seen = set()
    for _ in range(4000):
        sim.step()
        seen.add(round(part(sim, cyl).fraction, 1))
    assert {0.0, 1.0} <= seen


@pytest.mark.parametrize("props,says", [
    ({"Senses": "A9 100%"}, "no cylinder has that tag"),
    ({"Senses": "A1"}, "needs to know where"),
    ({"Senses": "over there"}, "can't read"),
    ({"Senses": "A1 > 5 bar"}, "follows where a cylinder is"),
    ({}, "nothing operates"),
])
def test_what_it_says_about_a_link_it_cant_use(props, says):
    d, _m, _c, v, _g = rig(props)
    c = d.build()
    assert not [link for link in c.links if link.kind == "roller"]
    assert any(says in i.text and i.part == (d.doc.uid, v.id) for i in c.issues), [i.text for i in c.issues]
    engine.Simulator(c).run(0.1)


def test_a_motor_turns_without_end_so_it_cant_hold_a_roller():
    d = Drawing()
    d.add("fl.pneu.compressor", "P1", "6 bar")
    d.add("fl.hyd.motor", "M1")
    v = roller_valve(d, "V1", props={"Senses": "M1 100%"})
    c = d.build()
    assert any("follows where a cylinder is" in i.text and i.part == (d.doc.uid, v.id) for i in c.issues)


def test_it_can_be_clicked_as_a_manual_override():
    d, _m, _c, v, _g = rig({"Senses": "A1 100%"})
    sim = d.sim()
    b = part(sim, v)
    label = dict((n, t) for n, t, _on in b.actions())["left"]
    assert "roller" in label and "manual override" in label
    sim.command(b.part.key, "left")
    sim.step()
    assert b.position != b.normal
    sim.command(b.part.key, "left")
    sim.step()
    assert b.position == b.normal


def test_a_stuck_valve_ignores_its_roller():
    d, _m, _c, v, _g = rig({"Senses": "A1 0%"})
    sim = d.sim()
    b = part(sim, v)
    assert b.position != b.normal
    sim.reset()
    sim.set_fault(b.part.key, "stuck")
    sim.reset()
    assert b.roller["left"]


def test_the_sequence_example_runs_a_plus_b_plus_a_minus_b_minus():
    c, sim = run_example("pneumatic_sequence.schematix")
    assert not [i.text for i in c.issues if i.level in ("error", "warning")]
    assert {link.text for link in c.links} == {f"The left-hand roller of {t} senses {w}" for t, w in
                                               (("a0", "A 0%"), ("a1", "A 100%"), ("b0", "B 0%"), ("b1", "B 100%"))}
    a, b = tag(sim, "A"), tag(sim, "B")
    sim.run(1.0)
    assert a.fraction == 0.0 and b.fraction == 0.0, "nothing moves until it's started"
    key = tag(sim, "S1").part.key
    sim.command(key, "left")
    order = []

    def note(what, test):
        if test and what not in order:
            order.append(what)
    for _ in range(4000):
        sim.step()
        note("A+", a.fraction > 0.99)
        note("B+", b.fraction > 0.99)
        if "B+" in order:
            note("A-", a.fraction < 0.01)
        if "A-" in order:
            note("B-", b.fraction < 0.01)
        if len(order) == 2 and sim.parts[key].cmd["left"]:
            sim.command(key, "left")    # let go of the start button, or it goes round again
    assert order == ["A+", "B+", "A-", "B-"]
    assert a.fraction == 0.0 and b.fraction == 0.0


def test_the_sequence_stops_where_a_stuck_roller_stops_it():
    """What a fault is for: a1 never makes, so B never starts."""
    _c, sim = run_example("pneumatic_sequence.schematix")
    a, b = tag(sim, "A"), tag(sim, "B")
    sim.run(0.5)
    sim.set_fault(tag(sim, "a1").part.key, "stuck")
    sim.command(tag(sim, "S1").part.key, "left")
    sim.run(10.0)
    assert a.fraction == 1.0 and b.fraction == 0.0


def test_a_saved_study_keeps_a_roller_link(tmp_path):
    d, _m, _c, v, _g = rig()
    from fluidworx.vendor.openschematix import projectio
    p = tmp_path / "r.schematix"
    projectio.save_project(d.project, str(p))
    s = st.from_source(str(p))
    pid = f"{d.doc.uid}/{v.id}"
    s.links = {pid: {"Senses": "A1 100%", simlinks.SENSES_A: "A1 0%", "Not a link": "x"}}
    f = tmp_path / "r.fluidworx"
    st.save(s, str(f))
    assert st.load(str(f)).links == {pid: {"Senses": "A1 100%", simlinks.SENSES_A: "A1 0%"}}
    project, warn = circuit.load_project(str(p))
    assert any(link.kind == "roller" for link in circuit.build(project, warn, s.links).links)
