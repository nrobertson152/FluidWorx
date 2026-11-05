"""Command-line definitions and parsing (GUI independent).

Commands are typed in the command line at the bottom of the window, like
AutoCAD: type a name or alias and press Enter or Space. Every command calls
the same operation as the corresponding menu item or toolbar button.

Coordinates typed at a point prompt are in millimetres with the origin at
the sheet's lower-left corner and Y pointing up (as in CAD programs and in
exported DXF files):
    x,y        absolute point
    @dx,dy     relative to the last point
    @d<a       polar: distance d at angle a degrees (counter-clockwise from +X)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandDef:
    name: str
    aliases: tuple
    summary: str
    usage: str = ""
    category: str = "General"


COMMANDS = [
    # drafting
    CommandDef("FILL", ("HATCH", "H"), "Fill closed areas solid (boundary fill)",
               "FILL  then click inside closed areas (Enter to finish); G sets the gap tolerance", "Draw"),
    CommandDef("LINE", ("L",), "Draw lines", "LINE  then pick points (Enter to finish)", "Draw"),
    CommandDef("PLINE", ("PL",), "Draw a polyline", "PLINE  then pick points; C closes", "Draw"),
    CommandDef("RECTANGLE", ("REC", "RECT"), "Draw a rectangle", "RECTANGLE  then two corners", "Draw"),
    CommandDef("CIRCLE", ("C",), "Draw a circle", "CIRCLE  centre, then radius point or value", "Draw"),
    CommandDef("ARC", ("A",), "Draw an arc", "ARC  centre, start point, end point", "Draw"),
    CommandDef("TEXT", ("T", "DT"), "Place text", "TEXT  position, then the text", "Draw"),
    CommandDef("WIRE", ("W",), "Draw wires", "WIRE  then click terminals / bend points", "Draw"),
    # modify
    CommandDef("MOVE", ("M",), "Move objects", "MOVE  base point, second point", "Modify"),
    CommandDef("COPY", ("CO", "CP"), "Copy objects", "COPY  base point, then target points", "Modify"),
    CommandDef("ROTATE", ("RO",), "Rotate objects", "ROTATE  base point, angle (multiples of 90° for symbols)",
               "Modify"),
    CommandDef("MIRROR", ("MI",), "Mirror objects", "MIRROR  (about a vertical axis through the selection)",
               "Modify"),
    CommandDef("SCALE", ("SC",), "Scale drafting objects or the drawing layout",
               "SCALE  base point, factor", "Modify"),
    CommandDef("TRIM", ("TR",), "Trim drafting objects at cutting edges", "TRIM  then click the parts to remove",
               "Modify"),
    CommandDef("EXTEND", ("EX",), "Extend drafting objects to boundaries", "EXTEND  then click near line ends",
               "Modify"),
    CommandDef("ERASE", ("E", "DEL"), "Delete the selection", "ERASE", "Modify"),
    CommandDef("UNDO", ("U",), "Undo", "UNDO", "Edit"),
    CommandDef("REDO", (), "Redo", "REDO", "Edit"),
    CommandDef("SELECTALL", ("ALL",), "Select everything on the sheet", "SELECTALL", "Edit"),
    CommandDef("GROUP", ("G",), "Group the selection", "GROUP", "Modify"),
    CommandDef("UNGROUP", ("UG",), "Ungroup the selection", "UNGROUP", "Modify"),
    CommandDef("LOCK", (), "Lock the selection against editing", "LOCK", "Modify"),
    CommandDef("UNLOCK", (), "Unlock all objects on the sheet", "UNLOCK", "Modify"),
    CommandDef("ALIGN", ("AL",), "Align the selection", "ALIGN left|center|right|top|middle|bottom", "Modify"),
    CommandDef("DISTRIBUTE", ("DI",), "Distribute the selection evenly", "DISTRIBUTE h|v", "Modify"),
    CommandDef("CONNECT", ("CW",), "Connect crossing wires at a point", "CONNECT  then click the crossing",
               "Wires"),
    CommandDef("DISCONNECT", ("DW",), "Remove a junction", "DISCONNECT  then click the junction", "Wires"),
    # place
    CommandDef("INSERT", ("I",), "Insert a symbol", "INSERT <symbol name>   or   INSERT K1 (identifier)", "Place"),
    CommandDef("TEMPLATE", ("TPL",), "Insert a circuit template", "TEMPLATE [name]", "Place"),
    CommandDef("PROPERTIES", ("PR", "PROPS"), "Show the properties panel", "PROPERTIES", "View"),
    # view
    CommandDef("ZOOM", ("Z",), "Zoom", "ZOOM E (extents) | S (sheet) | IN | OUT | <factor>", "View"),
    CommandDef("PAN", ("P",), "Pan the view", "PAN dx,dy (mm)", "View"),
    CommandDef("GRID", (), "Toggle the grid", "GRID [on|off]", "View"),
    CommandDef("SNAP", ("SN",), "Toggle grid snap", "SNAP [on|off]", "View"),
    CommandDef("ORTHO", ("OR",), "Toggle orthogonal drafting", "ORTHO [on|off]", "View"),
    CommandDef("OSNAP", ("OS",), "Toggle object snap", "OSNAP [on|off]", "View"),
    CommandDef("LAYER", ("LA",), "Layer manager", "LAYER [name]  (sets the current layer)", "View"),
    CommandDef("THEME", (), "Change the theme", "THEME <name>", "View"),
    # project
    CommandDef("NEW", (), "New project", "NEW", "File"),
    CommandDef("OPEN", (), "Open a project or drawing", "OPEN", "File"),
    CommandDef("SAVE", ("QSAVE",), "Save the project", "SAVE", "File"),
    CommandDef("SAVEAS", (), "Save the project as", "SAVEAS", "File"),
    CommandDef("SHEET", ("SH",), "Sheets", "SHEET new | next | prev | <number> | delete | rename <name>", "Project"),
    CommandDef("SEARCH", ("FIND", "F"), "Search the project", "SEARCH <text>", "Project"),
    CommandDef("BOM", (), "Bill of materials", "BOM", "Reports"),
    CommandDef("WIRELIST", ("WL",), "Connection and wire lists", "WIRELIST", "Reports"),
    CommandDef("TERMINALS", ("TS",), "Terminal strip report", "TERMINALS", "Reports"),
    CommandDef("WIRENUMBER", ("WN",), "Assign wire numbers", "WIRENUMBER [renumber]", "Reports"),
    CommandDef("CHECK", ("CHK",), "Check the drawing", "CHECK", "Reports"),
    CommandDef("EXPORT", ("EXP",), "Export", "EXPORT PDF | SVG | DXF | BOM | WIRELIST", "File"),
    CommandDef("IMPORT", ("IMP",), "Import a DXF drawing", "IMPORT DXF", "File"),
    CommandDef("FIT", (), "Fit the drawing to the sheet (sets the print scale)", "FIT", "Sheet"),
    CommandDef("PLOTSCALE", ("PS",), "Set the sheet's presentation (print) scale", "PLOTSCALE 1:2", "Sheet"),
    CommandDef("REVISION", ("REV",), "Revision history", "REVISION", "Project"),
    CommandDef("COMPARE", ("CMP",), "Compare revisions", "COMPARE", "Project"),
    CommandDef("SYMBOL", ("SE", "SYMEDIT"), "Open the symbol editor", "SYMBOL", "Library"),
    CommandDef("PREFERENCES", ("OPTIONS", "OP"), "Preferences", "PREFERENCES", "General"),
    CommandDef("HELP", ("?",), "List commands", "HELP [command]", "General"),
]

_BY_NAME = {c.name: c for c in COMMANDS}


def alias_table(extra: dict | None = None) -> dict:
    t = {}
    for c in COMMANDS:
        t[c.name] = c.name
        for a in c.aliases:
            t[a] = c.name
    for a, n in (extra or {}).items():
        if n.upper() in _BY_NAME and a.strip():
            t[a.strip().upper()] = n.upper()
    return t


def get(name: str) -> CommandDef | None:
    return _BY_NAME.get(name.upper())


def resolve(word: str, extra_aliases: dict | None = None) -> str | None:
    return alias_table(extra_aliases).get(word.strip().upper())


def typed_forms(name: str, extra_aliases: dict | None = None) -> list[str]:
    """What can be typed for a command: its shortest built-in alias first
    (the usual way to start it), then user aliases; the full name if none."""
    c = get(name)
    if c is None:
        return []
    user = sorted(a.strip().upper() for a, n in (extra_aliases or {}).items()
                  if a.strip() and n.upper() == c.name and a.strip().upper() not in c.aliases)
    forms = sorted(c.aliases, key=len)[:1] + user
    return forms or [c.name]


def tooltip(name: str, accel: str = "", extra_aliases: dict | None = None, summary: str | None = None) -> str:
    """Toolbar tooltip for a command: what it does, then how to start it from
    the keyboard, e.g. "Draw lines (type L)" or "Undo (Ctrl+Z · type U)".
    Used by every toolbar so wording and shortcut format stay consistent."""
    c = get(name)
    text = summary or (c.summary if c else name)
    keys = [accel] if accel else []
    forms = typed_forms(name, extra_aliases)
    if forms:
        keys.append("type " + " / ".join(forms))
    return f"{text} ({' · '.join(keys)})" if keys else text


def split(line: str) -> tuple[str, str]:
    line = line.strip()
    if not line:
        return "", ""
    parts = line.split(None, 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def complete(prefix: str, extra_aliases: dict | None = None, limit: int = 12) -> list[tuple[str, str]]:
    """Suggestions [(typed form, summary)] for a partial command name: exact
    alias first, then names and aliases starting with the prefix."""
    p = prefix.strip().upper()
    if not p:
        return []
    table = alias_table(extra_aliases)
    out = []
    if p in table:
        out.append((p, _BY_NAME[table[p]].summary + ("" if p == table[p] else f"  ({table[p]})")))
    for c in COMMANDS:
        if c.name.startswith(p) and c.name != p:
            out.append((c.name, c.summary))
    for a, n in sorted(table.items()):
        if a.startswith(p) and a != p and a != n and (a, None) not in out:
            item = (a, _BY_NAME[n].summary + f"  ({n})")
            if item not in out:
                out.append(item)
    seen, res = set(), []
    for k, v in out:
        if k not in seen:
            seen.add(k)
            res.append((k, v))
    return res[:limit]


# ================================================================ values
class ParseError(ValueError):
    pass


_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def parse_number(text: str) -> float:
    t = text.strip().replace(",", ".") if text.count(",") == 1 and "." not in text else text.strip()
    if not re.fullmatch(_NUM, t):
        raise ParseError(f"“{text}” is not a number")
    return float(t)


def parse_point(text: str, last: tuple | None = None) -> tuple[float, float]:
    """Parse a CAD point (mm, Y up). Returns (x_mm, y_mm)."""
    t = text.strip().replace(" ", "")
    rel = t.startswith("@")
    if rel:
        t = t[1:]
        if last is None:
            raise ParseError("there is no previous point for a relative coordinate")
    m = re.fullmatch(rf"({_NUM})<({_NUM})", t)
    if m:
        d, a = float(m.group(1)), math.radians(float(m.group(2)))
        dx, dy = d * math.cos(a), d * math.sin(a)
        base = last if rel else (0.0, 0.0)
        return (base[0] + dx, base[1] + dy)
    m = re.fullmatch(rf"({_NUM})[,;]({_NUM})", t)
    if not m:
        raise ParseError(f"“{text}” is not a point: type x,y  or  @dx,dy  or  @distance<angle (millimetres)")
    x, y = float(m.group(1)), float(m.group(2))
    if rel:
        return (last[0] + x, last[1] + y)
    return (x, y)


def is_point_text(text: str) -> bool:
    try:
        parse_point(text, (0.0, 0.0))
        return True
    except ParseError:
        return False


def parse_scale_factor(text: str) -> float:
    t = text.strip()
    if ":" in t or "/" in t:
        a, b = re.split(r"[:/]", t, 1)
        f = parse_number(a) / parse_number(b)
    else:
        f = parse_number(t)
    if f <= 0:
        raise ParseError("the factor must be positive")
    return f


def help_text(name: str | None = None) -> str:
    if name:
        c = get(resolve(name) or name)
        if c is None:
            return f"Unknown command: {name}"
        al = f"  (aliases: {', '.join(c.aliases)})" if c.aliases else ""
        return f"{c.name}{al}: {c.summary}. Usage: {c.usage}"
    cats = {}
    for c in COMMANDS:
        cats.setdefault(c.category, []).append(c.name + (f" ({'/'.join(c.aliases)})" if c.aliases else ""))
    return " | ".join(f"{k}: {', '.join(v)}" for k, v in cats.items())
