"""Read-only integrity checks for symbol definitions and libraries.

Inspects SymbolDef instances and (optionally) raw custom-symbol documents
without modifying them. Reuses ``validate_geometry`` from ``base`` where
possible. Findings are structured so callers can report or filter by severity.

This module is intentionally separate from the Symbol Editor and from
load-time normalisation so validation never mutates source data.

Strict validation vs normalisation
----------------------------------
``validate_document`` is a **strict structural audit** of a raw symbol
document (as stored on disk or embedded). It reports problems without
repairing them. ``normalise`` (in ``custom``) is the **load-time path** and
may repair limited legacy issues (missing pin id, invalid direction, etc.).

CLI (``python -m openschematix.symbols.integrity``)
-------------------------------------------------
* Without paths (or with ``--builtins``): audits the built-in library.
* With paths: audits each ``.osym`` / JSON file (does **not** call ``normalise``).
* Exit code **0** if there are no error-severity findings; **1** otherwise
  (warnings alone still exit 0).
* ``--json`` prints structured findings including ``source`` and ``location``.
"""
from __future__ import annotations

import json
import sys
from typing import Optional, Sequence

from ._integrity_base import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING, Finding
from ._integrity_doc import validate_document
from ._integrity_symbol import (
    findings_by_severity,
    validate_builtin_library,
    validate_library,
    validate_symbol_def,
)

__all__ = [
    "SEVERITY_ERROR", "SEVERITY_WARNING", "SEVERITY_INFO", "Finding",
    "validate_symbol_def", "validate_document", "validate_library",
    "validate_builtin_library", "findings_by_severity", "main",
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: validate built-ins and/or .osym paths.

    Exit code 0 when there are no error-severity findings; 1 otherwise.
    ``--json`` emits a JSON array of findings (with source and location).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    builtins_only = "--builtins" in argv
    argv = [a for a in argv if a != "--builtins"]
    paths = [a for a in argv if not a.startswith("-")]
    findings = []
    if builtins_only or not paths:
        findings.extend(validate_builtin_library())
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            findings.append(Finding("<file>", f"could not read {path}: {e}", SEVERITY_ERROR, source=path))
            continue
        if not text.strip():
            findings.append(Finding("<file>", "symbol file is empty or truncated", SEVERITY_ERROR, source=path))
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            findings.append(Finding("<file>", f"invalid JSON: {e.msg} (line {e.lineno}, column {e.colno})",
                                    SEVERITY_ERROR, source=path))
            continue
        findings.extend(validate_document(data, source=path))
    errors = [f for f in findings if f.severity == SEVERITY_ERROR]
    if as_json:
        print(json.dumps([f.as_dict() for f in findings], indent=2))
    else:
        if not findings:
            print("No integrity problems found.")
        for f in findings:
            loc = f" [{f.location}]" if f.location else ""
            src = f" ({f.source})" if f.source else ""
            print(f"{f.severity.upper()}: {f.symbol_id}{loc}{src}: {f.problem}")
        if findings:
            print(f"\n{len(errors)} error(s), {len(findings) - len(errors)} warning/info.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
