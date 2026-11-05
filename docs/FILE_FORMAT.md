# The `.fluidworx` study format (version 2)

A study is a ZIP archive laid out like an OpenSchematix `.schematix`. Text members are UTF-8 JSON. Readers ignore
members they don't know.

```
mimetype              "application/x-fluidworx-study" (stored uncompressed, first member)
manifest.json         container information
study.json            the study
source/schematic.*    byte-exact copy of the schematic (.schematix or .osch)
```

`manifest.json`:

```json
{"format": "FluidWorx Study", "version": 1, "app": "FluidWorx 0.1.0", "saved": "2026-11-04T19:00:00",
 "study": "study.json", "source": "source/schematic.schematix"}
```

A reader refuses a higher `version` and asks the user to update; it never guesses.

A study is written in the lowest version that holds what it has, so most stay readable by older FluidWorx. Version 2
added `links`, and a study has `"version": 2` only if it has some.

`study.json`:

```json
{"created": "2026-11-04T18:00:00", "units": "metric", "notes": "",
 "params": {"<sheet uid>/<component id>": {"setting": 12000000.0}},
 "source": {"name": "lift.schematix", "path": "/last/known/path/lift.schematix", "sha256": "…",
            "revisionworx": {"summary": "D-1 Rev A", "document": "D-1", "revision": "A"}}}
```

- `params` holds only values the user changed. They are SI: Pa, m³/s, m, N, kg; see `catalog.py` for each key.
  Everything else comes from the schematic or from defaults, so a later change to the drawing still takes effect.
  Components are identified by sheet uid and component id, which OpenSchematix never reuses.
- `links` (version 2, optional) holds ties set in the study and not in the drawing, as component properties laid over the
  study's copy of the schematic: `{"<sheet uid>/<component id>": {"Senses": "A1 100%"}}`. The properties are `Senses`,
  `Solenoid a`, `Solenoid b` and `Driven by`. Empty text clears what the drawing says. Anything else in it is ignored.
- `source.path` is only a hint, used to notice that the original has changed. The study always runs from its own copy.
- `source.sha256` must match the embedded copy, or the study is rejected as damaged.
- Non-finite numbers are rejected, as OpenSchematix's readers do.

Saving writes a temporary file in the destination folder, reads it back and verifies it, then renames it over the
old file. An interrupted save leaves the previous file intact.

RevisionWorx recognizes a `.fluidworx` by its `mimetype` member and versions it byte for byte, as a "Simulation study" document.
