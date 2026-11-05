"""Reusable circuit templates.

A template is a saved selection of components, wires and drafting shapes
(plus any custom symbols they use) that can be inserted into any sheet.
Inserted components get new identifiers automatically.

User templates are stored as ``.ostpl`` JSON files in
``<config>/templates/<folder>/...``. Built-in templates are generated from
code so they always use the current symbol library.

    {"format": "OpenSchematix Template", "version": 1, "name", "description",
     "category", "created", "content": {"components", "wires", "shapes", "symbols"}}

Content coordinates are relative to the template's insertion point (the
top-left of its bounding box, on the grid).
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os

from .editing import add_wire, copy_items, paste, place
from .geometry import snap
from .model import Document, Shape
from .settings import config_dir
from .userlib import _atomic_json, _rel_ok, safe_name

TPL_FORMAT = "OpenSchematix Template"
TPL_VERSION = 2          # 2 = content may contain boundary fills ("hatch" shapes); written only then
TPL_EXT = ".ostpl"
BUILTIN_PREFIX = "builtin:"


class TemplateError(ValueError):
    pass


def normalise_content(clip: dict) -> dict:
    """Shift content so its bounding box starts at (0, 0) on the grid."""
    doc = Document()
    paste(doc, clip, 0, 0)
    b = doc.bbox()
    if b is None:
        raise TemplateError("the template is empty")
    dx, dy = -snap(b[0]), -snap(b[1])
    out = copy_items(doc, doc.all_ids())
    shifted = Document()
    paste(shifted, out, dx, dy)
    return copy_items(shifted, shifted.all_ids())


def make_template(name: str, clip: dict, description: str = "", category: str = "Custom") -> dict:
    content = normalise_content(clip)
    # lowest version able to hold the content, so fill-free templates still load in 1.0.x
    version = 2 if any(s.get("kind") == "hatch" for s in content.get("shapes", [])) else 1
    return {"format": TPL_FORMAT, "version": version, "name": name.strip() or "Template",
            "description": description, "category": category or "Custom",
            "created": _dt.datetime.now().isoformat(timespec="seconds"), "content": content}


def validate(data) -> dict:
    if not isinstance(data, dict) or data.get("format") != TPL_FORMAT:
        raise TemplateError("not an OpenSchematix circuit template")
    if not isinstance(data.get("version"), int) or data["version"] > TPL_VERSION:
        raise TemplateError("the template was made by a newer version of OpenSchematix")
    c = data.get("content")
    if not isinstance(c, dict):
        raise TemplateError("the template has no content")
    try:
        d = Document()
        paste(d, c, 0, 0)
    except (KeyError, TypeError, ValueError) as e:
        raise TemplateError(f"the template is damaged: {e}") from e
    return data


def insert(doc: Document, tpl: dict, x: float, y: float) -> list[int]:
    """Insert at (x, y) with automatic identifier reassignment."""
    return paste(doc, tpl["content"], snap(x), snap(y), renumber=True)


def preview_document(tpl: dict) -> Document:
    d = Document()
    paste(d, tpl["content"], 0, 0)
    return d


class TemplateStore:
    def __init__(self, root: str | None = None):
        self.root = root or os.path.join(config_dir(), "templates")

    def items(self) -> list[tuple[str, str, dict]]:
        """[(key, folder, template)] for built-in and user templates."""
        out = [(BUILTIN_PREFIX + k, "Built-in/" + t["category"], t) for k, t in builtin_templates().items()]
        if os.path.isdir(self.root):
            for dirpath, dirnames, files in os.walk(self.root):
                dirnames.sort()
                rel = os.path.relpath(dirpath, self.root)
                folder = "" if rel == "." else rel.replace(os.sep, "/")
                for fn in sorted(files):
                    if fn.lower().endswith(TPL_EXT):
                        p = os.path.join(dirpath, fn)
                        try:
                            with open(p, encoding="utf-8") as f:
                                out.append((p, folder or "My templates", validate(json.load(f))))
                        except (OSError, ValueError):
                            continue
        return out

    def get(self, key: str) -> dict:
        if key.startswith(BUILTIN_PREFIX):
            return builtin_templates()[key[len(BUILTIN_PREFIX):]]
        with open(key, encoding="utf-8") as f:
            return validate(json.load(f))

    def save(self, tpl: dict, folder: str = "") -> str:
        if folder and not _rel_ok(folder):
            raise ValueError("invalid folder")
        d = os.path.join(self.root, *folder.split("/")) if folder else self.root
        os.makedirs(d, exist_ok=True)
        base = safe_name(tpl["name"], "Template")
        p = os.path.join(d, base + TPL_EXT)
        n = 2
        while os.path.exists(p):
            p = os.path.join(d, f"{base} ({n}){TPL_EXT}")
            n += 1
        _atomic_json(p, tpl)
        return p

    def delete(self, key: str):
        if key.startswith(BUILTIN_PREFIX):
            raise ValueError("built-in templates cannot be deleted")
        os.unlink(key)

    def folders(self) -> list[str]:
        out = []
        if os.path.isdir(self.root):
            for dirpath, dirnames, _f in os.walk(self.root):
                dirnames.sort()
                rel = os.path.relpath(dirpath, self.root)
                if rel != ".":
                    out.append(rel.replace(os.sep, "/"))
        return out

    def import_file(self, path: str, folder: str = "") -> str:
        with open(path, encoding="utf-8") as f:
            tpl = validate(json.load(f))
        return self.save(tpl, folder)

    @staticmethod
    def export_file(tpl: dict, path: str):
        _atomic_json(path, tpl)


# ================================================================ built-in templates
def _wire(doc, *pts):
    w = add_wire(doc, list(pts))
    if w is None:
        raise RuntimeError(f"bad template wire {pts}")
    return w


def _link(doc, c1, t1, c2, t2):
    """Routed wire between two terminals (same router as the editor)."""
    from .editing import route
    from .model import Wire
    p, q = c1.terminals()[t1], c2.terminals()[t2]
    pts = route(p, c1.terminal_dirs()[t1], q, c2.terminal_dirs()[t2], [c1.bbox(), c2.bbox()])
    w = Wire(id=doc.new_id(), points=pts, start=[c1.id, t1], end=[c2.id, t2], auto=True)
    doc.add_wire(w)
    return w


def _relay_latch():
    d = Document()
    f1 = place(d, "el.fuse.iec", 0, 0, rotation=90)
    s1 = place(d, "el.pushbutton.nc.iec", 0, 60, rotation=90)
    s1.label = "Stop"
    s2 = place(d, "el.pushbutton.no.iec", 0, 130, rotation=90)
    s2.label = "Start"
    k1a = place(d, "el.contact.no.iec", 60, 130, rotation=90)
    k1a.designator, k1a.label = "K1", "13-14"
    k1 = place(d, "el.coil.iec", 0, 210)
    k1.designator = "K1"
    _link(d, f1, "2", s1, "1")
    _link(d, s1, "2", s2, "1")
    _link(d, s2, "2", k1, "A1")
    a, b = k1a.terminals()["1"], k1a.terminals()["2"]
    ya, yb = s2.terminals()["1"][1] - 10, s2.terminals()["2"][1] + 10
    _wire(d, a, (a[0], ya), (0, ya))
    _wire(d, b, (b[0], yb), (0, yb))
    return d


def _motor_starter():
    d = Document()
    q1 = place(d, "el.breaker.iec", 0, 0, rotation=90)
    km = place(d, "el.contact.no.iec", 0, 70, rotation=90)
    km.designator, km.label = "K1", "1-2"
    m1 = place(d, "el.motor", 0, 150, rotation=90)
    _link(d, q1, "2", km, "1")
    _link(d, km, "2", m1, "1")
    s1 = place(d, "el.pushbutton.nc.iec", 120, 0, rotation=90)
    s1.label = "Stop"
    s2 = place(d, "el.pushbutton.no.iec", 120, 70, rotation=90)
    s2.label = "Start"
    k1 = place(d, "el.coil.iec", 120, 150)
    k1.designator = "K1"
    hold = place(d, "el.contact.no.iec", 180, 70, rotation=90)
    hold.designator, hold.label = "K1", "13-14"
    _link(d, s1, "2", s2, "1")
    _link(d, s2, "2", k1, "A1")
    a, b = hold.terminals()["1"], hold.terminals()["2"]
    ya, yb = s2.terminals()["1"][1] - 10, s2.terminals()["2"][1] + 10
    _wire(d, a, (a[0], ya), (120, ya))
    _wire(d, b, (b[0], yb), (120, yb))
    return d


def _hyd_cylinder():
    from .symbols.fluid import default_valve_params
    d = Document()
    cyl = place(d, "fl.hyd.cyl.double", 100, 0)
    v = place(d, "fl.hyd.dcv", 100, 120, params=default_valve_params("hyd", "4/3"))
    pump = place(d, "fl.hyd.pump", 40, 240)
    tank = place(d, "fl.hyd.tank", 170, 300)
    vt = v.terminals()
    ct = cyl.terminals()
    for n_ in ("A", "B"):
        a, b = vt[n_], ct[n_]
        mid = snap((a[1] + b[1]) / 2)
        if abs(a[0] - b[0]) > 0.01:
            _wire(d, a, (a[0], mid), (b[0], mid), b)
        else:
            _wire(d, a, b)
    pt = pump.terminals()
    _wire(d, pt["P"], (pt["P"][0], vt["P"][1] + 40), (vt["P"][0], vt["P"][1] + 40), vt["P"])
    tt = tank.terminals()
    _wire(d, vt["T"], (vt["T"][0], tt["T"][1] - 30), (tt["T"][0], tt["T"][1] - 30), tt["T"])
    return d


def _pneu_dcv():
    from .symbols.fluid import default_valve_params
    d = Document()
    cyl = place(d, "fl.pneu.cyl.double", 100, 0)
    v = place(d, "fl.pneu.dcv", 100, 120, params=default_valve_params("pneu", "5/2"))
    vt, ct = v.terminals(), cyl.terminals()
    for pv, pc in (("4", "A"), ("2", "B")):
        if pv in vt and pc in ct:
            a, b = vt[pv], ct[pc]
            mid = snap((a[1] + b[1]) / 2)
            if abs(a[0] - b[0]) > 0.01:
                _wire(d, a, (a[0], mid), (b[0], mid), b)
            else:
                _wire(d, a, b)
    return d


_BUILTIN = None


def builtin_templates() -> dict:
    global _BUILTIN
    if _BUILTIN is None:
        out = {}
        for key, name, cat, desc, fn in (
            ("relay-latch", "Start/stop relay latch", "Relay control",
             "Stop (NC) and start (NO) push-buttons with a self-holding contact on relay K1.", _relay_latch),
            ("motor-starter", "DOL motor starter (single line)", "Motor starters",
             "Circuit breaker, contactor main contact and motor, with the start/stop control circuit.",
             _motor_starter),
            ("hyd-cylinder", "Hydraulic cylinder with 4/3 valve", "Hydraulic",
             "Double-acting cylinder controlled by a 4/3 directional valve, pump and tank.", _hyd_cylinder),
            ("pneu-dcv", "Pneumatic cylinder with 5/2 valve", "Pneumatic",
             "Double-acting cylinder controlled by a 5/2 directional valve.", _pneu_dcv),
        ):
            try:
                doc = fn()
                clip = copy_items(doc, doc.all_ids())
                out[key] = make_template(name, clip, desc, cat)
            except (KeyError, RuntimeError, TemplateError):
                continue
        _BUILTIN = out
    return copy.deepcopy(_BUILTIN)


__all__ = ["TemplateStore", "make_template", "insert", "builtin_templates", "validate", "TemplateError", "Shape"]
