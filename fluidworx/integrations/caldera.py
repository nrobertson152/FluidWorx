"""Caldera: exchange numbers through its documented `.caldera` project file (a JSON document).

Export writes each cylinder as a saved calculation Caldera can open, recalculate and report on. Import reads
saved calculations back and offers their sizes for parts in the circuit. Caldera stores inputs in US customary
units whichever display setting it is in, so the conversions here are fixed.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime

from .. import VERSION
from ..units import parse_number

PROJECT_FORMAT = "caldera-project"
IN = 0.0254
PSI = 6894.757
GPM = 3.785412e-3 / 60
CFM = 4.719474e-4
CC = 1e-6


class CalderaError(ValueError):
    """The file can't be used. The message is written for the user."""


def _n(x: float) -> str:
    return f"{x:.4g}"


def _cyl_rec(tool, values, text, stamp, project, note):
    return {"date": stamp, "tool": tool, "project": project, "inputs": values, "result": text, "note": note}


def cylinder_records(sim, project_name: str, measured: dict | None = None) -> list:
    """One Caldera calculation per linear actuator, using the supply this circuit actually has."""
    measured = measured or {}
    stamp = datetime.now().isoformat(timespec="seconds")
    from ..engine import Actuator, Pump
    pumps = [b for b in sim.parts.values() if isinstance(b, Pump)]
    settings = [b.part.params.get("setting") for b in sim.parts.values()
                if b.part.kind in ("relief", "pump_pc", "compressor") and b.part.params.get("setting")]
    out = []
    for b in sim.parts.values():
        if not isinstance(b, Actuator) or b.rotary:
            continue
        pa = b.part.params
        hyd = b.part.medium == "hyd"
        flows = [x.part.params["flow"] for x in pumps if x.part.medium == b.part.medium]
        press = [v for v in settings] or [0.0]
        p_psi = max(press) / PSI
        # results are worked out from the rounded inputs, so Caldera recalculates the same numbers
        bore, rod, stroke = (float(_n(x)) for x in (pa["bore"] / IN, pa.get("rod", 0.0) / IN, pa["stroke"] / IN))
        p_psi = float(_n(p_psi))
        cap = math.pi * bore * bore / 4
        ann = math.pi * (bore * bore - rod * rod) / 4
        if hyd:
            q = float(_n(max(flows) / GPM)) if flows else 10.0
            inputs = [_n(bore), _n(rod), _n(stroke), _n(p_psi), _n(q)]
            ext, ret = cap * stroke / 231 / q * 60, ann * stroke / 231 / q * 60
            tool = "Hydraulic Cylinder"
        else:
            q = float(_n(max(flows) / CFM)) if flows else 5.0
            inputs = [_n(bore), _n(rod), _n(p_psi), _n(stroke), _n(q)]
            ext, ret = cap * stroke / 1728 / q * 60, ann * stroke / 1728 / q * 60
            tool = "Pneumatic Cylinder"
        lines = [f"Extend force (lbf): {cap * p_psi:.1f}", f"Retract force (lbf): {ann * p_psi:.1f}",
                 f"Extend time (s): {ext:.2f}", f"Retract time (s): {ret:.2f}"]
        note = f"From FluidWorx {VERSION}: {b.part.title}."
        m = measured.get(b.part.key)
        if m:
            note += " Simulated " + ", ".join(f"{k} {v:.2f} s" for k, v in m.items()) + "."
        out.append(_cyl_rec(tool, inputs, "\n".join(lines), stamp, project_name, note))
    return out


def write_project(path: str, project_name: str, records: list, notes: str = "") -> None:
    payload = {"format": PROJECT_FORMAT, "format_version": 1, "app_version": f"FluidWorx {VERSION}",
               "exported": datetime.now().isoformat(timespec="seconds"),
               "project": {"name": project_name, "notes": notes, "history": records}}
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".caldera-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, allow_nan=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_project(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError) as e:
        raise CalderaError(f"That file could not be read as a Caldera project.\n\n{e}") from e
    if not isinstance(obj, dict) or obj.get("format") != PROJECT_FORMAT or not isinstance(obj.get("project"), dict):
        raise CalderaError("That file is not a Caldera project (.caldera).")
    proj = obj["project"]
    rows = proj.get("history")
    return {"name": str(proj.get("name") or "Caldera project"),
            "history": [r for r in rows if isinstance(r, dict) and isinstance(r.get("tool"), str)]
            if isinstance(rows, list) else []}


def _get(rec, i):
    ins = rec.get("inputs")
    if not isinstance(ins, list) or i >= len(ins):
        raise ValueError
    return parse_number(ins[i])


def values_from_record(rec: dict) -> dict:
    """{part kind group: {parameter: SI value}} that a saved calculation can supply. Empty if nothing usable."""
    tool = rec.get("tool")
    try:
        if tool == "Hydraulic Cylinder":
            return {"cylinder": {"bore": _get(rec, 0) * IN, "rod": _get(rec, 1) * IN, "stroke": _get(rec, 2) * IN},
                    "relief": {"setting": _get(rec, 3) * PSI}, "pump": {"flow": _get(rec, 4) * GPM}}
        if tool == "Pneumatic Cylinder":
            return {"cylinder": {"bore": _get(rec, 0) * IN, "rod": _get(rec, 1) * IN, "stroke": _get(rec, 3) * IN},
                    "compressor": {"setting": _get(rec, 2) * PSI}, "pump": {"flow": _get(rec, 4) * CFM}}
        if tool == "Hydraulic Cylinder Cycle Time":
            return {"cylinder": {"bore": _get(rec, 0) * IN, "rod": _get(rec, 1) * IN, "stroke": _get(rec, 2) * IN},
                    "pump": {"flow": _get(rec, 3) * GPM}}
        if tool == "Hydraulic Pump & Motor":
            d, rpm = _get(rec, 0), _get(rec, 1)
            eff = _get(rec, 3) / 100
            return {"pump": {"flow": d * CC * rpm / 60 * eff}, "motor": {"displacement": d * CC}}
        if tool == "Hydraulic Motor":
            return {"motor": {"displacement": _get(rec, 0) * CC}}
    except ValueError:
        return {}
    return {}


GROUP_OF_KIND = {"cylinder": "cylinder", "cylinder_equal": "cylinder", "cylinder_single": "cylinder",
                 "pump": "pump", "pump_pc": "pump", "compressor": "compressor", "relief": "relief", "motor": "motor",
                 "rotary": "motor"}


def applicable(rec: dict, part) -> dict:
    """Parameters from this calculation that fit this part."""
    group = GROUP_OF_KIND.get(part.kind)
    if group is None:
        return {}
    vals = dict(values_from_record(rec).get(group, {}))
    if part.kind == "compressor":
        vals.update(values_from_record(rec).get("pump", {}))
    return {k: v for k, v in vals.items() if k in part.params}
