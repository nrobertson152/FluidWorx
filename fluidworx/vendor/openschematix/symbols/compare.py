"""Compare two definitions of one custom-symbol id, and predict what
replacing a project's drawn definition would do to its wires.

A project embeds the definition its drawings were made with; the user
library holds its own definition under the same id. The two may be an older
and a newer revision of the same symbol, or two different symbols that share
an id (for example made in two projects). Documents carry no provenance that
tells these cases apart, so the application treats any difference in content
as something the user must see before it edits or replaces a definition.

Pure functions: no GUI, no registry access.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .custom import SymbolFormatError, normalise

# keys that do not change what a definition draws or how it connects
_BOOKKEEPING = ("revision",)


def _clean(doc) -> dict:
    try:
        d = normalise(copy.deepcopy(doc))
    except SymbolFormatError:
        d = copy.deepcopy(doc) if isinstance(doc, dict) else {}
    for k in _BOOKKEEPING:
        d.pop(k, None)
    return d


def _pins(doc) -> dict:
    return {str(p.get("id")): p for p in (doc or {}).get("pins", []) if isinstance(p, dict)}


def _xy(p) -> tuple:
    return (float(p.get("x", 0)), float(p.get("y", 0)))


def label(doc) -> str:
    """“Name” revision n, for messages."""
    doc = doc or {}
    return f"“{doc.get('name') or doc.get('id') or '?'}” revision {doc.get('revision', 0)}"


def pin_list(doc) -> str:
    return ", ".join(str(p.get("name") or p.get("id")) for p in (doc or {}).get("pins", [])) or "none"


@dataclass
class SymbolDiff:
    identical: bool
    renamed: bool = False
    pins_removed: list = field(default_factory=list)    # pin ids in `old` that `new` lacks
    pins_added: list = field(default_factory=list)
    pins_moved: list = field(default_factory=list)      # same id, other position
    pins_turned: list = field(default_factory=list)     # same id and position, other direction
    pins_retyped: list = field(default_factory=list)    # same id, other port type
    drawing_changed: bool = False
    other_changed: bool = False                         # description, properties, prefix, ...

    def summary(self) -> list[str]:
        """Human-readable differences, most important first."""
        out = []
        if self.renamed:
            out.append("different name")
        if self.pins_removed:
            out.append("connection points only in the drawn version: " + ", ".join(self.pins_removed))
        if self.pins_added:
            out.append("connection points only in the library version: " + ", ".join(self.pins_added))
        if self.pins_moved:
            out.append("connection points in other positions: " + ", ".join(self.pins_moved))
        if self.pins_turned:
            out.append("connection points facing another way: " + ", ".join(self.pins_turned))
        if self.pins_retyped:
            out.append("connection points of another type (Check drawing results may change): "
                       + ", ".join(self.pins_retyped))
        if self.drawing_changed:
            out.append("different drawing")
        if self.other_changed and not out:
            out.append("different description or properties")
        return out


def diff(old, new) -> SymbolDiff:
    """Differences from definition `old` (e.g. drawn in a project) to `new`
    (e.g. in the library). Revision numbers alone do not count."""
    a, b = _clean(old), _clean(new)
    if a == b:
        return SymbolDiff(identical=True)
    pa, pb = _pins(a), _pins(b)
    d = SymbolDiff(identical=False)
    d.renamed = (a.get("name") or "") != (b.get("name") or "")
    d.pins_removed = [pid for pid in pa if pid not in pb]
    d.pins_added = [pid for pid in pb if pid not in pa]
    d.pins_moved = [pid for pid in pa if pid in pb and _xy(pa[pid]) != _xy(pb[pid])]
    d.pins_turned = [pid for pid in pa if pid in pb and pid not in d.pins_moved
                     and pa[pid].get("dir") != pb[pid].get("dir")]
    d.pins_retyped = [pid for pid in pa if pid in pb and pa[pid].get("type") != pb[pid].get("type")]
    d.drawing_changed = a.get("prims") != b.get("prims")
    rest = {k for k in set(a) | set(b) if k not in ("name", "pins", "prims")}
    d.other_changed = any(a.get(k) != b.get(k) for k in rest) or any(
        {k: v for k, v in pa[pid].items() if k not in ("x", "y", "dir", "type")} !=
        {k: v for k, v in pb[pid].items() if k not in ("x", "y", "dir", "type")} for pid in pa if pid in pb)
    return d


@dataclass
class WireEnd:
    sheet: str           # sheet name
    sheet_uid: str
    wire_id: int
    end: str             # "start" | "end"
    designator: str
    pin: str             # pin id

    def text(self) -> str:
        return f"{self.designator}.{self.pin} ({self.sheet})"


@dataclass
class UpdateImpact:
    sid: str
    diff: SymbolDiff
    components: int = 0                                  # components drawn with `sid`
    detached: list = field(default_factory=list)         # WireEnd: pin disappears -> end detached
    moved: list = field(default_factory=list)            # WireEnd: pin moves -> wire re-routed

    @property
    def harmless(self) -> bool:
        """Replacing changes no wire, no connection point's type or direction
        (Check drawing results and wire routing) and keeps the symbol's name.
        A change to the drawing alone is harmless."""
        d = self.diff
        return not (self.detached or self.moved or d.renamed or d.pins_retyped or d.pins_turned)


def update_impact(project, sid: str, new_doc) -> UpdateImpact:
    """What replacing the project's drawn definition of `sid` by `new_doc`
    would do to its wires. Uses the rule editing.sync_wire_ends applies:
    an end on a pin id the new definition lacks is detached; an end on a
    pin whose position changes is re-routed."""
    old = project.symbols.get(sid) or {}
    dif = diff(old, new_doc)
    impact = UpdateImpact(sid, dif)
    gone, moved = set(dif.pins_removed), set(dif.pins_moved)
    for doc in project.sheets:
        comps = {c.id: c for c in doc.components.values() if c.symbol == sid}
        impact.components += len(comps)
        if not comps:
            continue
        for w in doc.wires.values():
            for end in ("start", "end"):
                ref = getattr(w, end)
                if not ref or ref[0] not in comps:
                    continue
                pin = str(ref[1])
                if pin in gone:
                    target = impact.detached
                elif pin in moved:
                    target = impact.moved
                else:
                    continue
                target.append(WireEnd(doc.name, doc.uid, w.id, end, comps[ref[0]].designator or "?", pin))
    return impact
