"""General drafting symbols that are not tied to one discipline."""
from __future__ import annotations

from .base import GENERIC, Geometry, SymbolDef, Terminal as T, line, poly, rect, text

UNKNOWN_ID = "gen.unknown"
OFFPAGE_ID = "gen.offpage"
OFFPAGE_IDS = (OFFPAGE_ID,)


def symbols():
    return [
        SymbolDef("gen.block2", "Function block, 2 terminals", "General", "Blocks", GENERIC,
                  "Generic rectangular function block (use the label for its function).", "U",
                  Geometry([rect(-20, -10, 20, 10), line(-30, 0, -20, 0), line(20, 0, 30, 0)],
                           [T("1", -30, 0, "l"), T("2", 30, 0, "r")]), keywords=("box", "device")),
        SymbolDef("gen.block4", "Function block, 4 terminals", "General", "Blocks", GENERIC,
                  "Generic rectangular function block with two terminals on each side.", "U",
                  Geometry([rect(-20, -20, 20, 20), line(-30, -10, -20, -10), line(-30, 10, -20, 10),
                            line(20, -10, 30, -10), line(20, 10, 30, 10)],
                           [T("1", -30, -10, "l"), T("2", -30, 10, "l"), T("3", 30, -10, "r"), T("4", 30, 10, "r")]),
                  keywords=("box", "device")),
        SymbolDef(OFFPAGE_ID, "Sheet connector (cross-sheet reference)", "General", "Connections", GENERIC,
                  "Connects a signal or line to every sheet connector with the same label anywhere in the "
                  "project. The sheet and zone of the matching connectors are shown next to it automatically.",
                  "", Geometry([line(0, 0, 10, 0), poly(10, -6, 32, -6, 40, 0, 32, 6, 10, 6)],
                               [T("1", 0, 0, "l")]),
                  keywords=("off-page", "off page", "cross reference", "xref", "continuation", "link")),
        SymbolDef(UNKNOWN_ID, "Missing symbol", "General", "Internal", GENERIC,
                  "Placeholder for a symbol that is not available in this version (for example from an older file).", "?",
                  Geometry([rect(-20, -10, 20, 10, dash=True), text(0, 0, "?", size=10),
                            line(-30, 0, -20, 0), line(20, 0, 30, 0)],
                           [T("1", -30, 0, "l"), T("2", 30, 0, "r")])),
    ]
