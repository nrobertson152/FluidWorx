"""Document metadata and pin integrity checks (internal)."""
from __future__ import annotations

from .base import PORT_TYPES
from .custom import SYMBOL_FORMAT, SYMBOL_VERSION, USER_PREFIX
from ._integrity_base import Finding, SEVERITY_ERROR, SEVERITY_WARNING, _check_coordinates, _safe_in
from ._integrity_aliases import _validate_document_aliases


def _validate_document_header(doc: dict, sid: str, findings: list, source: str) -> str:
    if doc.get("format") != SYMBOL_FORMAT:
        findings.append(Finding(sid, f"missing or invalid format field (expected {SYMBOL_FORMAT!r})",
                                SEVERITY_ERROR, source=source))
    ver = doc.get("version", 1)
    if not isinstance(ver, int) or isinstance(ver, bool):
        findings.append(Finding(sid, f"version must be an integer, got {type(ver).__name__}",
                                SEVERITY_ERROR, source=source))
    elif ver < 1:
        findings.append(Finding(sid, f"unsupported schema version {ver}", SEVERITY_ERROR, source=source))
    elif ver > SYMBOL_VERSION:
        findings.append(Finding(sid, f"symbol format version {ver} is newer than supported "
                                f"({SYMBOL_VERSION})", SEVERITY_ERROR, source=source))
    if not isinstance(sid, str) or not sid.startswith(USER_PREFIX) or len(sid) <= len(USER_PREFIX):
        findings.append(Finding(sid, "custom symbol id must start with 'user:' and include a unique suffix",
                                SEVERITY_ERROR, source=source))
    name = doc.get("name", "")
    if name is not None and not isinstance(name, str):
        findings.append(Finding(sid, "name must be a string", SEVERITY_ERROR, source=source))
    if "properties" in doc and doc["properties"] is not None and not isinstance(doc["properties"], dict):
        findings.append(Finding(sid, "properties must be an object/dict", SEVERITY_ERROR, source=source))
    if "tags" in doc and doc["tags"] is not None and not isinstance(doc["tags"], (list, tuple)):
        findings.append(Finding(sid, "tags must be a list", SEVERITY_ERROR, source=source))
    if "revision" in doc and doc["revision"] is not None and doc["revision"] != "":
        rev = doc["revision"]
        if isinstance(rev, bool) or not isinstance(rev, int):
            findings.append(Finding(sid, f"revision must be a non-negative integer, got {type(rev).__name__}",
                                    SEVERITY_ERROR, source=source))
        elif rev < 0:
            findings.append(Finding(sid, f"revision must be non-negative, got {rev}",
                                    SEVERITY_ERROR, source=source))
    _validate_document_aliases(doc, sid, findings, source)
    return sid


def _validate_document_pins(doc: dict, sid: str, findings: list, source: str) -> None:
    pins = doc.get("pins")
    if pins is None:
        return
    if not isinstance(pins, list):
        findings.append(Finding(sid, "pins must be a list", SEVERITY_ERROR, source=source))
        return
    seen_pins = set()
    for i, p in enumerate(pins):
        loc = f"pin[{i}]"
        if not isinstance(p, dict):
            findings.append(Finding(sid, f"pin {i}: not an object", SEVERITY_ERROR, loc, source))
            continue
        raw_id = p.get("id")
        if raw_id is None or raw_id == "":
            findings.append(Finding(sid, f"pin {i}: missing id", SEVERITY_ERROR, loc, source))
            pid = ""
        else:
            try:
                pid = str(raw_id)
            except Exception:  # noqa: BLE001
                findings.append(Finding(sid, f"pin {i}: id is not convertible to string",
                                        SEVERITY_ERROR, loc, source))
                pid = ""
        if pid:
            if pid in seen_pins:
                findings.append(Finding(sid, f"duplicate pin id {pid}", SEVERITY_ERROR, pid, source))
            else:
                seen_pins.add(pid)
        _check_coordinates(f"pin {pid or i}", p.get("x"), p.get("y"), sid, findings,
                           require_grid=True, source=source)
        d = p.get("dir", "r")
        if d not in ("l", "r", "u", "d"):
            findings.append(Finding(sid, f"pin {pid or i}: invalid direction {d!r}",
                                    SEVERITY_ERROR, pid or loc, source))
        ptype = p.get("type") or ""
        if ptype and not _safe_in(ptype, PORT_TYPES):
            findings.append(Finding(sid, f"pin {pid or i}: unknown port type {ptype!r}",
                                    SEVERITY_WARNING, pid or loc, source))
