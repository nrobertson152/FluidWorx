"""Every OpenSchematix fluid symbol must have a deliberate behaviour. A new symbol fails this until classified."""
from fluidworx import catalog, engine
from fluidworx.gui_support import cylinder_motion
from fluidworx.vendor.openschematix import symbols

NOT_SIMULATED_ON_PURPOSE = {"fl.hyd.intensifier", "fl.pneu.intensifier", "fl.hyd.servopositioner",
                            "fl.pneu.servopositioner"}


def fluid_symbols():
    return [s for s in symbols.builtin_symbols() if s.id.startswith("fl.") and symbols.geometry(s.id).terminals]


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
