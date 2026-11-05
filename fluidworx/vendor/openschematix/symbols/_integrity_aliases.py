"""Alias field integrity checks (internal)."""
from __future__ import annotations

from ._integrity_base import Finding, SEVERITY_ERROR, SEVERITY_WARNING


def _validate_document_aliases(doc: dict, sid: str, findings: list, source: str) -> None:
    if "aliases" not in doc or doc["aliases"] is None:
        return
    als = doc["aliases"]
    if not isinstance(als, (list, tuple)):
        findings.append(Finding(sid, "aliases must be a list", SEVERITY_ERROR, source=source))
        return
    try:
        from . import is_builtin, get as _sym_get
    except Exception:  # noqa: BLE001
        is_builtin = lambda _a: False  # type: ignore
        _sym_get = lambda _a: None  # type: ignore
    seen_a: set[str] = set()
    for i, a in enumerate(als):
        if not isinstance(a, str) or not a.strip():
            findings.append(Finding(sid, f"alias {i}: must be a non-empty string",
                                    SEVERITY_WARNING, f"aliases[{i}]", source))
            continue
        low = a.lower()
        if low in seen_a:
            findings.append(Finding(sid, f"duplicate alias {a!r}",
                                    SEVERITY_WARNING, f"aliases[{i}]", source))
        seen_a.add(low)
        if low == sid.lower():
            findings.append(Finding(sid, f"alias {a!r} equals this symbol's own id",
                                    SEVERITY_WARNING, f"aliases[{i}]", source))
        elif is_builtin(a) or (callable(_sym_get) and _sym_get(a) is not None and getattr(_sym_get(a), "id", "") != sid):
            findings.append(Finding(sid, f"alias {a!r} collides with an existing symbol identifier",
                                    SEVERITY_WARNING, f"aliases[{i}]", source))
