"""Automatic bill of materials.

Physical devices. One physical device may be drawn as several symbols
("units"): a relay coil K1 and its contacts K1 13-14, K1 23-24, possibly on
different sheets. As in the drawing checks (see docs/VALIDATION.md), all
purchasable components that share a non-empty identifier are units of ONE
device and are counted once - provided they can be: no two of them may have
the same symbol, label and terminal designations (the criterion of the
"Duplicate identifiers" check; such units would be the same coil or contact
twice, i.e. an identifier clash such as two copies of resistor R1). A
clashing identifier is not merged: each of its symbols counts as a part, as
before, and the drawing checks report it. Terminal-block
terminals (X1:1, X1:2 ...) and components without an identifier are each one
physical part.

Part identity. Components are grouped into BOM lines by part identity:
  * with a part number: (manufacturer, part number)
  * without:           (symbol, description, rating, parameters)
For a device drawn with several units, the units that carry purchasing data
decide its line, and units without it are absorbed:
  1. Units with a part number. A device whose units carry DIFFERENT part
     numbers (e.g. a contactor and an auxiliary contact block both called
     K1) is counted once on each of those lines; the drawing check reports
     it ("device-parts").
  2. Otherwise units with a description or rating.
  3. Otherwise all units: if they differ, one line describes the device by
     its distinct symbols ("Coil ... + Contact, make (NO)").
A device belongs to a sheet-filtered BOM if any of its units is on the
selected sheets; its part identity always considers all of its units.

Items that are not purchasable are left out: components switched off with
"Include in BOM", and symbols that represent no physical part (earth and
ground marks, connection points, sheet connectors, missing-symbol
placeholders, symbols without a designator prefix).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import symbols
from .netlist import CONNECTION_COLUMNS, to_csv  # noqa: F401  (re-exported for convenience)
from .symbols.base import is_drafting_element
from .symbols.general import OFFPAGE_IDS, UNKNOWN_ID

NON_PURCHASABLE = {"el.earth", "el.earth.pe", "el.chassis", "el.ground.signal", "el.connector.point",
                   UNKNOWN_ID, *OFFPAGE_IDS}


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s or "")]


def purchasable(c) -> bool:
    if not c.in_bom or c.symbol in NON_PURCHASABLE:
        return False
    sd = symbols.get(c.symbol)
    if sd is None:
        return False
    if symbols.is_builtin(c.symbol) and is_drafting_element(sd):
        # a built-in drafting mark (direction arrow, standalone valve operator)
        # is never a purchased item, even with a part number typed into it
        return False
    return bool(sd.prefix) or bool(c.props.get("part_number"))


@dataclass
class BomLine:
    item: int = 0
    quantity: int = 0
    designators: list = field(default_factory=list)
    description: str = ""
    manufacturer: str = ""
    part_number: str = ""
    rating: str = ""
    symbol: str = ""
    sheets: list = field(default_factory=list)
    refs: list = field(default_factory=list)     # (sheet uid, component id)

    def designator_text(self) -> str:
        return compress_designators(self.designators)

    def as_row(self) -> dict:
        return {"item": self.item, "quantity": self.quantity, "designators": self.designator_text(),
                "description": self.description, "manufacturer": self.manufacturer,
                "part_number": self.part_number, "rating": self.rating, "symbol": self.symbol,
                "sheets": ", ".join(self.sheets)}


BOM_COLUMNS = [("item", "Item"), ("quantity", "Qty"), ("designators", "Designators"),
               ("description", "Description"), ("manufacturer", "Manufacturer"), ("part_number", "Part number"),
               ("rating", "Rating"), ("symbol", "Symbol"), ("sheets", "Sheets")]


def compress_designators(ds: list) -> str:
    """K1, K2, K3, K5 -> 'K1-K3, K5' (ranges of three or more)."""
    items = sorted(set(ds), key=natural_key)
    out, run = [], []

    def flush():
        if len(run) >= 3:
            out.append(f"{run[0][2]}–{run[-1][2]}")
        else:
            out.extend(r[2] for r in run)
        run.clear()
    for d in items:
        m = re.fullmatch(r"(.*?)(\d+)", d)
        if m and run and run[-1][0] == m.group(1) and run[-1][1] + 1 == int(m.group(2)) and ":" not in d:
            run.append((m.group(1), int(m.group(2)), d))
            continue
        flush()
        if m and ":" not in d:
            run.append((m.group(1), int(m.group(2)), d))
        else:
            out.append(d)
    flush()
    return ", ".join(out)


@dataclass
class _Unit:
    doc: object
    comp: object
    key: tuple
    name: str            # symbol name
    description: str
    manufacturer: str
    part_number: str
    rating: str

    @property
    def has_part_number(self) -> bool:
        return bool(self.part_number)

    @property
    def described(self) -> bool:
        return bool(self.comp.props.get("description", "").strip() or self.rating)


def _unit(doc, c) -> _Unit:
    sd = symbols.get(c.symbol)
    name = sd.name if sd else c.symbol
    pn = c.props.get("part_number", "").strip()
    mf = c.props.get("manufacturer", "").strip()
    desc = c.props.get("description", "").strip() or name
    rating = c.props.get("rating", "").strip()
    if pn:
        key = ("pn", mf.lower(), pn.lower())
    else:
        key = ("sym", c.symbol, desc.lower(), rating.lower(), json.dumps(c.params, sort_keys=True))
    return _Unit(doc, c, key, name, desc, mf, pn, rating)


def unit_slot(c) -> tuple:
    """What tells parts of one device apart, as in the "Duplicate identifiers" drawing check: symbol,
    label and terminal designations (e.g. contacts labelled 13-14 and 23-24). Two units of one device
    cannot share all three - they would be the same coil or contact drawn twice."""
    return (c.symbol, c.label.strip(), tuple(c.terminal_label(n) for n in sorted(c.terminals())))


def designator_groups(project, include_excluded: bool = False) -> list[tuple[str, list[_Unit]]]:
    """Purchasable units grouped by shared identifier, in project order: [(identifier, units)].
    Terminal-block terminals and components without an identifier form groups of their own ("")."""
    from .project import is_terminal_symbol
    out, by_designator = [], {}
    for doc in project.sheets:
        for c in doc.components.values():
            if not include_excluded and not purchasable(c):
                continue
            u = _unit(doc, c)
            if c.designator and not is_terminal_symbol(c.symbol):
                grp = by_designator.get(c.designator)
                if grp is None:
                    grp = by_designator[c.designator] = (c.designator, [])
                    out.append(grp)
                grp[1].append(u)
            else:
                out.append(("", [u]))
    return out


def is_one_device(units) -> bool:
    """True if the units can be parts of one device: no two share symbol, label and terminal designations."""
    slots = [unit_slot(u.comp) for u in units]
    return len(set(slots)) == len(slots)


def devices(project, include_excluded: bool = False) -> list[list[_Unit]]:
    """Physical devices in project order, each as the list of its units (see module docstring).

    A shared identifier makes its units one device only if they can be parts of one device
    (`is_one_device`). Otherwise the identifier is ambiguous (e.g. two different resistors both called R1)
    and every unit is counted as a part of its own, as before multi-unit support, so an identifier clash can
    never lower a quantity; the drawing checks report the clash."""
    out = []
    for _des, units in designator_groups(project, include_excluded):
        if len(units) == 1 or is_one_device(units):
            out.append(units)
        else:
            out.extend([u] for u in units)
    return out


def _distinct(units):
    seen = {}
    for u in units:
        seen.setdefault(u.key, u)
    return list(seen.values())


def device_lines(dev: list[_Unit]) -> list[tuple[tuple, dict, list[_Unit]]]:
    """BOM lines one device is counted on: [(line key, line fields, units shown on that line)]."""
    with_pn = [u for u in dev if u.has_part_number]
    if with_pn:
        plain = [u for u in dev if not u.has_part_number]
        out = []
        for first in _distinct(with_pn):
            units = [u for u in with_pn if u.key == first.key] + plain
            out.append((first.key, dict(description=first.description, manufacturer=first.manufacturer,
                                        part_number=first.part_number, rating=first.rating, symbol=first.name),
                        units))
        return out
    defining = [u for u in dev if u.described] or dev
    kinds = _distinct(defining)
    if len(kinds) == 1:
        u = kinds[0]
        return [(u.key, dict(description=u.description, rating=u.rating, symbol=u.name), dev)]
    kinds.sort(key=lambda u: u.key)
    ratings = []
    for u in kinds:
        if u.rating and u.rating not in ratings:
            ratings.append(u.rating)
    names = []
    for u in kinds:
        if u.name not in names:
            names.append(u.name)
    key = ("device",) + tuple(u.key for u in kinds)
    return [(key, dict(description=" + ".join(u.description for u in kinds), rating=", ".join(ratings),
                       symbol=" + ".join(names)), dev)]


@symbols.project_scoped
def generate(project, sheet_uids=None, include_excluded: bool = False) -> list[BomLine]:
    groups: dict = {}
    for dev in devices(project, include_excluded):
        if sheet_uids is not None and not any(u.doc.uid in sheet_uids for u in dev):
            continue
        for key, fields, units in device_lines(dev):
            line = groups.get(key)
            if line is None:
                line = groups[key] = BomLine(**fields)
            line.quantity += 1
            for u in units:
                if sheet_uids is not None and u.doc.uid not in sheet_uids:
                    continue
                line.designators.append(u.comp.tag())
                line.refs.append((u.doc.uid, u.comp.id))
                if u.doc.name not in line.sheets:
                    line.sheets.append(u.doc.name)
    lines = sorted(groups.values(), key=lambda l: natural_key(min(l.designators, key=natural_key)))
    for n, l in enumerate(lines, 1):
        l.item = n
    return lines


def filter_lines(lines, text: str = "") -> list:
    words = text.lower().split()
    if not words:
        return list(lines)
    out = []
    for l in lines:
        blob = " ".join(str(v) for v in l.as_row().values()).lower()
        if all(w in blob for w in words):
            out.append(l)
    return out


def sort_lines(lines, column: str, descending: bool = False) -> list:
    def key(l):
        v = l.as_row().get(column, "")
        return (0, v) if isinstance(v, int) else (1, natural_key(str(v)))
    return sorted(lines, key=key, reverse=descending)


def bom_csv(lines) -> str:
    return to_csv([l.as_row() for l in lines], BOM_COLUMNS)
