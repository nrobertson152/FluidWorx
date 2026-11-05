# Changelog

## 0.1.0 (unreleased)

First version.

- Imports OpenSchematix `.schematix` and `.osch` circuits, with OpenSchematix's own symbols and connectivity,
  including lines that cross sheets through sheet connectors.
- Lumped simulation of hydraulic and pneumatic circuits: pumps, air supply, cylinders, motors, directional valves,
  relief, sequence, reducing and unloading valves, checks, pilot checks, shuttles, flow controls, accumulators and
  receivers. All 300-odd built-in fluid symbols have a defined behaviour, or are reported as not simulated.
- Live drawing: wires coloured by pressure, flow along the actual paths, valves that shift when clicked, moving rods,
  values on the drawing.
- Trace chart, event log, circuit checks, parameter editing, metric or US customary units.
- `.fluidworx` study files that carry a copy of the schematic, and notice when the original changes.
- Works with OpenSchematix (edit, then reload), RevisionWorx (revision status; register, check out and check in
  studies) and Caldera (send cylinder calculations; use saved values).
- HTML report, trace and event CSV.
