# What the simulation does, and doesn't

FluidWorx shows how a circuit behaves: what shifts, where pressure goes, what moves, in what order, at about what
speed. It's a model for understanding and checking logic. **It is not a sizing tool and it doesn't show that a
circuit is safe.** Use Caldera for sizing.

This page is about the fluid side. The electrical side, the PLC and how they're tied to it are in [ELECTRICAL.md](ELECTRICAL.md).

## How it works

Each net in the schematic is one node with one pressure. Every 10 ms of simulated time, a linear system is solved
(backward Euler) for the node pressures and the speed of each moving actuator. Parts that switch (check valves,
relief valves, end stops, friction) are re-solved until their state agrees with the pressures they see.

| Part | Model |
|---|---|
| Fixed pump | Constant flow. Stalls at a 700 bar ceiling if blocked with no relief valve, and says so |
| Variable pump | Fixed pump at the flow you set |
| Compensated pump, air supply | Constant flow until the set pressure, then destrokes over a 4% droop |
| Open valve path, filter, hose | Conductance: about 0.33 bar at 10 L/min (hydraulic) |
| Throttle | Conductance proportional to opening³, so the control has a useful range |
| Check valve | Opens above its cracking pressure; flow is linear above that |
| Relief valve | A check valve with a high cracking pressure; about 0.33 bar override per 10 L/min |
| Sequence valve | Holds its inlet at the setting while passing flow; fully open when the outlet needs more |
| Reducing valve, regulator | Open below the setting, then holds the outlet at the setting |
| Pilot check | Opens in reverse when pilot pressure × ratio exceeds the load-side pressure |
| Compensated flow control | Open, until flow reaches the setting, then holds it |
| Directional valve | Connects ports as the drawn position does. Springs, detents and pilots follow the symbol |
| Cylinder | Force balance on the actual areas, with breakaway friction, viscous drag, moving mass and end stops |
| Motor | The same, with displacement, torque and inertia |
| Accumulator | Isothermal gas above its precharge |
| Line | About 1 L of compliance per net, so pressure doesn't change instantly |

## Limits worth knowing

- **Flow is linear in pressure drop**, where real valves are nearer to square-law. Pressure drops are indicative.
- **Lines have no length, volume or friction.** There is no water hammer, and pipe sizing has no effect.
- **Air is treated as a compressible liquid.** Sequence and logic are right; speeds are rough, and there's no choked
  flow or temperature. Pneumatic flows are actual volume, not free air.
- **Directional valves switch at once**, with no overlap. Transitions and spool shapes aren't modelled.
- **A solenoid valve with no coil on an electrical sheet** works by clicking it. Mechanically operated valves (cams and
  rollers) aren't linked to cylinders; position switches are, through their `Senses` property.
- **Cushions are drawn but not modelled.** Telescopic cylinders are one equivalent bore.
- **Below about -0.9 bar**, the model supplies fluid to stop the pressure falling further, and logs "cavitation".
- Parts modelled more simply than this are listed in the Checks panel. Symbols with no model (intensifiers, servo
  positioners, your own custom symbols) have blocked ports, and the Checks panel says so.

## Reading values from the drawing

FluidWorx reads a component's label and properties, so a drawing already carries its numbers:

| On the drawing | Sets |
|---|---|
| Label or `rating`: `160 bar`, `3000 psi` | Relief, sequence, reducing, compensator or supply setting |
| Label or `rating`: `10 L/min`, `3 gpm` | Pump flow |
| Label: `63/36x300` or `2.5/1.25 x 12 in` | Bore, rod, stroke (mm unless it says otherwise) |
| Label: `32x80` | Bore and stroke |
| Label: `32 cc/rev` | Motor or rotary actuator displacement |
| Property `Bore`, `Rod`, `Stroke`, `Load`, `Mass`, `Flow`, `Setting`, `Precharge`, `Volume`, `Displacement`, `Torque`, `Opening` | That parameter (metric if the value has no unit) |
| Property `Load mode` = `constant` | The load always acts one way, like a hanging weight |
| Shut-off valve labelled `closed` | Starts closed |
