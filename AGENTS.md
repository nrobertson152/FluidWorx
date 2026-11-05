# FluidWorx — development workflow

FluidWorx follows the same rules as OpenSchematix.

## Roles

- **Director (`nrobertson152`)** has sole authority over releases, release/version tags and licensing.
- **Developer (Claude)** plans, implements, tests and reviews its own work on branches and PRs.

## Product rules

- GPL-3.0-or-later, free and open source.
- Fully offline: no network access, accounts, telemetry, ads or feature limits.
- Standard library only at runtime. `[dev]` extras are for tests and builds only.
- The simulation core (`units`, `catalog`, `circuit`, `links`, `linsolve`, `engine`, `electric`, `flowpaths`, `study`, `scenario`, `report`) never
  imports Tkinter.
- Windows and Linux; Python 3.10–3.13; Tk 8.6 and 9.0.
- A schematic belongs to OpenSchematix: FluidWorx never writes to it. A study keeps its own copy and its own values.
- `.fluidworx` files must keep opening. Document any format change, version it and test it.
- `fluidworx/vendor/openschematix` is copied by `tools/sync_openschematix.py`. Never edit it by hand.
- Saves are atomic and verified. A malformed file shows a message; it never crashes.
- Say what the model doesn't do. A simple result must not look like an exact one.

## Priorities

1. Data loss, corruption and unsafe writes.
2. Wrong behaviour: connectivity, valve positions, what moves and in what order.
3. Crashes and runaway resource use.
4. Platform compatibility.
5. Performance, features, cosmetics.

## Commands

```sh
python -m pip install -e ".[dev]"            # Linux also: sudo apt-get install -y xvfb python3-tk
python -m compileall -q fluidworx tests
xvfb-run -a python -m pytest -q -ra          # Windows: python -m pytest -q -ra
python -m fluidworx --self-test
```

The RevisionWorx and Caldera exchange tests run against the real programs when they can be imported and skip
otherwise; CI installs both. When OpenSchematix adds symbols, re-sync and `tests/test_catalog.py` lists what needs
a behaviour.

Add a regression test with every behaviour change. Never weaken or skip tests to make CI pass. Never describe
unverified behaviour (native Windows, for example) as verified.
