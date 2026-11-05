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
- Electrical and electronic sheets run in the same simulation as the fluid sheets. The same tag means the same device: a
  coil operates the valve with its tag, a contact follows the pressure switch or coil with its tag, a motor drives the pump with
  its tag. `Senses`, `Solenoid a`, `Solenoid b` and `Driven by` properties say what a tag can't, and a study can set them for itself.
- Every built-in electrical and electronic symbol has a behaviour, except vacuum tubes: sources, supplies, transformers, relays,
  timers, switches, sensors, fuses, breakers, overloads, motors, three-phase motors, diodes, transistors, op-amps, logic gates.
- Runs the PLC block programmed in OpenSchematix (ladder, function blocks, sequential function chart, structured text, C, Python),
  powered from its own wires, with live inputs, outputs and variables.
- Wires coloured by voltage, current along the real paths, contacts drawn as they are now, a Links tab, on/off signals on the trace,
  and supply and protection tables in the report. Study files are format 2 only if they hold links.
- Fail a part or a line on purpose, while it runs, to see what the rest of the machine does: stuck contacts, burnt-out coils, broken wires, sensors reading
  zero, seized cylinders, stuck spools, burst lines and PLC inputs and outputs. It's marked on the drawing, counted in the status bar and listed in the report,
  which says it isn't a failure analysis.
- Says when relays race: when another order would leave them differently, the first drawn won only because it was drawn first, and a
  real machine could go either way.
