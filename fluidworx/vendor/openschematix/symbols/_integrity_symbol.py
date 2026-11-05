"""SymbolDef library validation (internal)."""
from __future__ import annotations

import copy
from typing import Iterable, Optional, Sequence

from .base import SymbolDef
from ._integrity_base import Finding, SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO
from ._integrity_geom import _check_geometry


def validate_symbol_def(sd: SymbolDef, *, params: Optional[dict] = None) -> list:
    """Inspect one SymbolDef. Never mutates ``sd``, its geometry, or ``params``.

    For parametric symbols, ``sd.build`` is called with a **deep** copy of
    ``params`` (or ``None``) so a builder cannot mutate nested structures in
    the caller's dict. Built-in builders are expected to return fresh geometry;
    this function does not write back to ``sd.geometry`` or ``sd.default_params``.
    """
    findings = []
    sid = getattr(sd, "id", None) or ""
    if not sid or not isinstance(sid, str):
        findings.append(Finding(sid or "<missing>", "missing or invalid symbol identifier", SEVERITY_ERROR))
        sid = sid or "<missing>"
    if not (getattr(sd, "name", None) or "").strip():
        findings.append(Finding(sid, "symbol name is empty", SEVERITY_WARNING))
    build_params = copy.deepcopy(params) if params is not None else None
    try:
        g = sd.build(build_params)
    except Exception as e:  # noqa: BLE001
        findings.append(Finding(sid, f"failed to build geometry: {e}", SEVERITY_ERROR))
        return findings
    _check_geometry(g, sid, findings)
    custom = getattr(sd, "custom", None)
    if custom is not None and not isinstance(custom, dict):
        findings.append(Finding(sid, "custom metadata is not a dict", SEVERITY_ERROR))
    return findings


def validate_library(symbols: Iterable[SymbolDef], *, check_duplicates: bool = True) -> list:
    findings = []
    seen = {}
    for sd in symbols:
        sid = getattr(sd, "id", "") or ""
        if check_duplicates and sid:
            if sid in seen:
                findings.append(Finding(sid, "duplicate symbol identifier (also defined earlier in library)",
                                        SEVERITY_ERROR))
            else:
                seen[sid] = sd
        findings.extend(validate_symbol_def(sd))
    return findings


def validate_builtin_library() -> list:
    from . import builtin_symbols
    return validate_library(builtin_symbols(), check_duplicates=True)


def findings_by_severity(findings: Sequence) -> dict:
    out = {SEVERITY_ERROR: [], SEVERITY_WARNING: [], SEVERITY_INFO: []}
    for f in findings:
        out.setdefault(f.severity, []).append(f)
    return out
