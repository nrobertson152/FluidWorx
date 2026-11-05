"""Simulation results as files: trace CSV and a self-contained HTML report with a picture of the circuit."""
from __future__ import annotations

import csv
import html
import io
import math
import os
import tempfile
from datetime import datetime

from . import APP_NAME, VERSION, catalog, electric
from .engine import Actuator
from .units import Units
from .vendor.openschematix.connectivity import analyse
from .vendor.openschematix.render import scene


def _safe_cell(s) -> str:
    """Text that a spreadsheet won't run as a formula."""
    s = str(s)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def trace_csv(sim, units: Units) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    tr = sim.trace
    w.writerow(["Time (s)"] + [_safe_cell(f"{c[1]} ({units.label(c[2])})") for c in tr.channels])
    for i, t in enumerate(tr.times):
        w.writerow([f"{t:.3f}"] + [f"{units.from_si(c[2], col[i]):.5g}" for c, col in zip(tr.channels, tr.data)])
    return buf.getvalue()


def events_csv(sim) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Time (s)", "Part", "Event"])
    for t, tag, text in sim.events:
        w.writerow([f"{t:.2f}", _safe_cell(tag), _safe_cell(text)])
    return buf.getvalue()


def write_text(path: str, text: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".fluidworx-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_STOPS = [(0.0, (37, 99, 235)), (0.35, (8, 145, 178)), (0.6, (101, 163, 13)), (0.8, (234, 88, 12)), (1.0, (220, 38, 38))]
_STOPS_DARK = [(0.0, (96, 165, 250)), (0.35, (34, 211, 238)), (0.6, (163, 230, 53)), (0.8, (251, 146, 60)),
               (1.0, (248, 113, 113))]


def pressure_color(p: float, pmax: float, dark: bool = False) -> str:
    """Wire colour: blue at tank pressure, through to red at the highest setting in the circuit."""
    if p < -1000:
        return "#c4b5fd" if dark else "#7c3aed"     # below atmospheric
    t = math.sqrt(max(0.0, min(1.0, p / max(pmax, 1.0))))
    stops = _STOPS_DARK if dark else _STOPS
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return "#%02x%02x%02x" % tuple(int(a + (b - a) * f) for a, b in zip(c0, c1))
    return "#%02x%02x%02x" % stops[-1][1]


def voltage_color(net, node, dark: bool = False) -> str:
    """The same colours for voltage, from blue at 0 V to red at the full voltage of that wire's own circuit."""
    return pressure_color(abs(net.v[node]), net.nominal(node), dark)


def _choice_shown(d, value):
    return d.choices[max(0, min(len(d.choices) - 1, int(round(value))))]


def electrical_rows(circuit, sim, units):
    """Supplies and protection against what they carried, and what's connected: the engineering check of a drawing."""
    supplies, protection = [], []
    loads: dict = {}
    of = circuit.el_circuit_of
    for b in sim.net.parts:
        if isinstance(b, (electric.Coil, electric.Load)) and not getattr(b, "proportional", False):
            r = b.rated()
            loads[of.get(b.t[b.names[0]])] = loads.get(of.get(b.t[b.names[0]]), 0.0) + b.g() * r * r
        elif isinstance(b, electric.Motor3):
            loads[of.get(b.t[b.names[0]])] = loads.get(of.get(b.t[b.names[0]]), 0.0) + b.par["power"]
        elif isinstance(b, electric.Plc):
            loads[of.get(b.t["L+"])] = loads.get(of.get(b.t["L+"]), 0.0) + b.par["power"]
    for b in sim.net.parts:
        if isinstance(b, electric.Source):
            v = abs(b.emf())
            limit = b.limit()
            connected = loads.get(of.get(b.t[b.plus]), 0.0)
            supplies.append((b.part.tag, units.fmt("voltage", v), units.fmt("current", b.peak),
                             units.fmt("current", limit) if limit else "not set", units.fmt("power", connected),
                             units.fmt("current", connected / v if v else 0.0)))
        elif isinstance(b, electric.Protection):
            rating = b.par["rating"]
            protection.append((b.part.tag, units.fmt("current", rating), units.fmt("current", b.peak),
                               f"{100.0 * b.peak / rating:.0f}%", b.status()))
    return supplies, protection


def svg_snapshot(doc, circuit, sim, project) -> str:
    """The sheet as it stands now, wires coloured by pressure. Valves are drawn as in the schematic."""
    pmax = sim.max_pressure()
    xs, ys = [], []
    for c in doc.components.values():
        b = c.bbox()
        xs += [b[0], b[2]]
        ys += [b[1], b[3]]
    for w in doc.wires.values():
        xs += [p[0] for p in w.points]
        ys += [p[1] for p in w.points]
    pad = 40
    x0, y0, x1, y1 = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad) if xs else (0, 0, 100, 100)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:g} {y0:g} {x1 - x0:g} {y1 - y0:g}" '
           'style="width:100%;max-height:640px;background:#fff;border:1px solid #d5d9df" '
           'font-family="Arial, Helvetica, sans-serif">']

    def col(it):
        if it.get("role") == "wire":
            node = circuit.wire_nodes.get((doc.uid, it.get("item")))
            if node is not None:
                return pressure_color(sim.p[node], pmax)
            node = circuit.el_wire_nodes.get((doc.uid, it.get("item")))
            if node is not None:
                return voltage_color(sim.net, node)
            return "#0b4f9c"
        return "#8a939d" if it.get("role") == "frame" else "#14181d"
    for it in scene(doc, screen=False, conn=analyse(doc), project=project, frame=False):
        k, c = it["k"], col(it)
        w = it.get("wpx", 1.4) * (1.5 if it.get("role") == "wire" else 1)
        dash = ' stroke-dasharray="6 3"' if it.get("dash") else ""
        if k == "line":
            pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in it["pts"])
            out.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="{w:.2f}" '
                       f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
        elif k == "poly":
            pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in it["pts"])
            fill = c if it.get("fill") else "none"
            out.append(f'<polygon points="{pts}" fill="{fill}" stroke="{c}" stroke-width="{w:.2f}"{dash}/>')
        elif k == "circle":
            x, y = it["c"]
            fill = c if it.get("fill") else "none"
            out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{it["r"]:.2f}" fill="{fill}" stroke="{c}" '
                       f'stroke-width="{w:.2f}"{dash}/>')
        elif k == "text":
            x, y = it["p"]
            anchor = {"w": "start", "e": "end"}.get(it.get("anchor", "c")[-1:], "middle")
            out.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{it.get("size", 10):.2f}" fill="{c}" '
                       f'text-anchor="{anchor}" dominant-baseline="middle">{html.escape(str(it["s"]))}</text>')
    out.append("</svg>")
    return "".join(out)


def cycle_times(sim) -> dict:
    """{part key: {"extend": s, "retract": s}} measured from the recorded trace."""
    out = {}
    tr = sim.trace
    for i, ch in enumerate(tr.channels):
        if ch[0][1] != "x":
            continue
        key = ch[0][0]
        b = sim.parts[key]
        trav = b.travel()
        if trav <= 0:
            continue
        col = tr.data[i]
        res = {}
        start, direction = None, 0
        for t, x, x_prev in zip(tr.times[1:], col[1:], col):
            d = (x > x_prev + 1e-7) - (x < x_prev - 1e-7)
            if d != direction:
                start, direction = (t if d else None), d
            if d > 0 and x >= trav * 0.999 and start is not None:
                res.setdefault("extend", t - start)
                start = None
            if d < 0 and x <= trav * 0.001 and start is not None:
                res.setdefault("retract", t - start)
                start = None
        if res:
            out[key] = res
    return out


CSS = """body{font:14px/1.45 Arial,Helvetica,sans-serif;color:#1b1f24;margin:32px auto;max-width:1000px;padding:0 16px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:28px 0 8px;color:#626b75;text-transform:uppercase;letter-spacing:.03em}
.muted{color:#626b75}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:4px 10px 4px 0;
border-bottom:1px solid #e5e7eb;vertical-align:top;font-variant-numeric:tabular-nums}th{color:#626b75;font-weight:600}
.note{border-left:3px solid #c27803;padding:6px 12px;background:#fff8eb;margin:14px 0}"""


def html_report(study, circuit, sim, units: Units, doc, title: str = "") -> str:
    e = html.escape
    rev = study.source_rev or {}
    rows = [("Schematic", study.source_name), ("Content SHA-256", study.source_sha256)]
    if rev.get("summary"):
        rows.append(("RevisionWorx", str(rev["summary"])))
    rows += [("Simulated time", f"{sim.time:.2f} s"),
             ("Generated", f"{datetime.now():%Y-%m-%d %H:%M} by {APP_NAME} {VERSION}")]
    head = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in rows)
    state_rows = []
    for p in circuit.parts:
        st = sim.status(p.key)
        if not st:
            b = sim.parts[p.key]
            rd = b.readings(sim.p)
            if not rd:
                continue
        b = sim.parts[p.key]
        vals = ", ".join(f"{lab} {units.fmt(q, v)}" for lab, q, v in b.readings(sim.p))
        state_rows.append(f"<tr><td>{e(p.tag)}</td><td>{e(p.symbol_name)}</td><td>{e(st)}</td><td>{e(vals)}</td></tr>")
    param_rows = []
    for p in circuit.parts:
        for d in catalog.PARAMS.get(p.kind, []):
            if d.quantity == "choice":
                shown = _choice_shown(d, p.params[d.key])
            else:
                shown = units.fmt(d.quantity, p.params[d.key])
            origin = "drawing" if d.key in p.from_schematic else "default"
            if p.params[d.key] != p.base_params.get(d.key):
                origin = "study"
            param_rows.append(f"<tr><td>{e(p.tag)}</td><td>{e(d.label)}</td><td>{e(shown)}</td><td>{origin}</td></tr>")
    times = cycle_times(sim)
    time_rows = []
    for b in sim.parts.values():
        if isinstance(b, Actuator) and b.part.key in times:
            t = times[b.part.key]
            ext = f'{t["extend"]:.2f} s' if "extend" in t else "not seen"
            ret = f'{t["retract"]:.2f} s' if "retract" in t else "not seen"
            time_rows.append(f"<tr><td>{e(b.part.tag)}</td><td>{ext}</td><td>{ret}</td></tr>")
    issues = "".join(f"<tr><td>{e(i.level)}</td><td>{e(i.text)}</td></tr>" for i in circuit.issues)
    events = "".join(f"<tr><td>{t:.2f}</td><td>{e(tag)}</td><td>{e(text)}</td></tr>" for t, tag, text in sim.events[-400:])
    sections = [f'<h1>{e(title or study.source_name)}</h1><p class="muted">{APP_NAME} simulation report</p>',
                f"<table>{head}</table>",
                '<p class="note">An idealised model to show how a circuit behaves. Speeds and pressures are '
                "indicative; it is not a sizing tool or evidence that a circuit is safe.</p>",
                f"<h2>Circuit at {sim.time:.2f} s</h2>", svg_snapshot(doc, circuit, sim, circuit.project),
                '<p class="muted">Line colours show pressure at this moment, from blue at tank to red at '
                f"{e(units.fmt('pressure', sim.max_pressure()))}"
                + (", and voltage, from blue at 0 V to red at the full voltage of that circuit" if circuit.electrical_parts else "")
                + ". Parts are drawn in their rest positions; their state is listed below.</p>"]
    if circuit.electrical_parts:
        sections.append('<p class="note">Electrical results are logic and approximate loads: AC is carried at its RMS value, '
                        "with no waveforms, and contacts and relays act instantly. Fuse and breaker times are indicative. "
                        "This is not a protection study or a check of wiring against a standard.</p>")
        supplies, protection = electrical_rows(circuit, sim, units)
        if supplies:
            sections.append("<h2>Supplies</h2><table><tr><th>Supply</th><th>Voltage</th><th>Peak current so far</th><th>Its limit</th>"
                            "<th>Connected load</th><th>at</th></tr>"
                            + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in supplies) + "</table>")
        if protection:
            sections.append("<h2>Protection</h2><table><tr><th>Part</th><th>Rating</th><th>Peak current so far</th><th>Of rating</th>"
                            "<th>State</th></tr>"
                            + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in protection) + "</table>")
    if sim.net.races:
        sections.append('<h2>Races</h2><p class="note">These relays were ready to change at the same moment, and the result above is '
                        "only one of the answers: the simulation changes them in drawing order, and a real machine has no drawing order.</p>"
                        "<table><tr><th>Time (s)</th><th>Went first</th><th>Raced</th></tr>"
                        + "".join(f"<tr><td>{t:.2f}</td><td>{e(a)}</td><td>{e(b)}</td></tr>" for t, a, b in sim.net.races) + "</table>")
    if time_rows:
        sections.append("<h2>Measured strokes</h2><table><tr><th>Actuator</th><th>Extend</th><th>Retract</th></tr>"
                        + "".join(time_rows) + "</table>")
    sections.append("<h2>State</h2><table><tr><th>Part</th><th>Type</th><th>State</th><th>Readings</th></tr>"
                    + "".join(state_rows) + "</table>")
    sections.append("<h2>Parameters</h2><table><tr><th>Part</th><th>Parameter</th><th>Value</th><th>From</th></tr>"
                    + "".join(param_rows) + "</table>")
    if issues:
        sections.append(f"<h2>Checks</h2><table>{issues}</table>")
    if events:
        sections.append("<h2>Events</h2><table><tr><th>Time (s)</th><th>Part</th><th>Event</th></tr>" + events + "</table>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title or study.source_name)}</title>'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body>'
            + "".join(sections) + "</body></html>")
