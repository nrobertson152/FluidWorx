"""Every OpenSchematix fluid symbol must have a deliberate behaviour. A new symbol fails this until classified."""
from fluidworx import catalog, electric, engine
from fluidworx.gui_support import cylinder_motion
from fluidworx.vendor.openschematix import symbols

NOT_SIMULATED_ON_PURPOSE = {"fl.hyd.intensifier", "fl.pneu.intensifier", "fl.hyd.servopositioner",
                            "fl.pneu.servopositioner"}


def fluid_symbols():
    return [s for s in symbols.builtin_symbols() if s.id.startswith("fl.") and symbols.geometry(s.id).terminals]


def electrical_symbols():
    return [s for s in symbols.builtin_symbols() if s.id.startswith("el.") and symbols.geometry(s.id).terminals]


def test_every_electrical_symbol_is_classified():
    """Vacuum tubes are left out on purpose, and say so when simulated."""
    missing = [s.id for s in electrical_symbols() if catalog.classify(s.id).kind == "unsupported"
               and not catalog.NOT_SIMULATED_ELECTRIC.search(s.id)]
    assert not missing
    assert all(catalog.classify(s.id).kind == "unsupported" for s in electrical_symbols() if ".tube." in s.id)


def test_every_electrical_kind_has_a_behaviour_and_a_name():
    kinds = {catalog.classify(s.id).kind for s in electrical_symbols()} - {"unsupported"}
    assert kinds <= set(electric.BEHAVIOURS)
    assert kinds <= set(catalog.KIND_NAMES)


def test_electrical_and_fluid_kinds_never_share_a_name():
    """They have different parameters and behaviours, and the fluid side's motor is not the electrical side's."""
    fluid = {catalog.classify(s.id).kind for s in fluid_symbols()}
    assert not (fluid & set(electric.BEHAVIOURS)) - {"unsupported"}
    assert catalog.PARAMS["motor"][0].key == "displacement"
    assert catalog.KIND_NAMES["motor"] == "Motor" and catalog.KIND_NAMES["rotary"] == "Rotary actuator"


def test_the_terminals_each_electrical_kind_uses_exist():
    needs = {"psu": None, "plc": ("L+", "M"), "coil_on": ("A1", "A2"), "coil_off": ("A1", "A2"), "relay": ("A1", "A2", "13", "14"),
             "bjt": ("B", "C", "E"), "fet": ("G", "D", "S"), "regulator": ("IN", "OUT", "GND"), "rectifier": ("AC1", "AC2", "+", "-"),
             "pot": ("1", "2", "3"), "autotransformer": ("1", "2", "3"), "changeover": ("C", "A", "B"),
             "selector4": ("C", "1", "2", "3", "4"), "prox": ("+", "-", "OUT"), "sensor_analog": ("+", "-", "OUT"),
             "sensor_loop": ("+", "-"), "opamp": ("+", "-", "OUT"), "transformer": ("P1", "P2")}
    for s in electrical_symbols():
        spec = catalog.classify(s.id)
        names = {t.name for t in symbols.geometry(s.id).terminals}
        wanted = needs.get(spec.kind) or ()
        assert set(wanted) <= names, s.id
        for key in ("poles", "pairs"):
            for a, b in spec.options.get(key, ()):
                assert a in names and b in names, s.id
        for a, b, _k in spec.options.get("windings", ()):
            assert a in names and b in names, s.id
        if spec.kind == "psu" or spec.kind == "scr":
            assert set(spec.options["pins"]) <= names, s.id


def test_every_electrical_symbol_can_stand_alone_in_a_running_simulation():
    from drawing import Drawing
    d = Drawing()
    for s in electrical_symbols():
        d.add(s.id, "T" + str(d.n))
    sim = d.sim()
    sim.run(0.05)
    sim.reset()
    for b in sim.net.parts:
        b.status()
        b.readings()
        b.actions()
        b.currents(sim.net.v)
    assert sim.net.parts


def test_every_fluid_symbol_is_classified():
    missing = [s.id for s in fluid_symbols() if catalog.classify(s.id).kind == "unsupported"
               and s.id not in NOT_SIMULATED_ON_PURPOSE]
    assert not missing


def test_every_kind_has_a_behaviour():
    kinds = {catalog.classify(s.id).kind for s in fluid_symbols()}
    assert kinds <= set(engine.BEHAVIOURS)


def test_terminal_counts_fit_the_kind():
    needs = {"pump": 2, "pump_pc": 2, "compressor": 2, "relief": 2, "sequence": 2, "reducer": 2, "check": 2,
             "pilot_check": 2, "shuttle": 3, "throttle": 2, "oneway": 2, "flow_pc": 2, "unloading": 2,
             "motor": 2, "rotary": 2, "cylinder": 2, "cylinder_equal": 2, "cylinder_single": 1, "prop": 2}
    for s in fluid_symbols():
        kind = catalog.classify(s.id).kind
        if kind in needs:
            n = len(symbols.geometry(s.id).terminals)
            assert n >= needs[kind], f"{s.id}: {kind} needs {needs[kind]} ports, has {n}"


def test_switched_state_ports_exist():
    for s in fluid_symbols():
        spec = catalog.classify(s.id)
        if spec.kind == "switched":
            names = {t.name for t in symbols.geometry(s.id).terminals}
            for state in spec.options["states"]:
                for a, b, _how in state:
                    assert a in names and b in names, s.id


def test_cylinders_animate():
    """All but telescopic and single-acting special cases have a rod that can be drawn moving."""
    for s in fluid_symbols():
        if catalog.classify(s.id).kind in ("cylinder", "cylinder_equal", "cylinder_single") and ".tele." not in s.id:
            assert cylinder_motion(symbols.geometry(s.id)) is not None, s.id
