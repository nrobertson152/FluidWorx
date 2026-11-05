"""Orchestrate raw-document integrity audit (internal)."""
from __future__ import annotations

import copy

from ._integrity_base import Finding, SEVERITY_ERROR
from ._integrity_doc_meta import _validate_document_header, _validate_document_pins
from ._integrity_doc_prims import _validate_document_prims


def validate_document(doc: dict, *, deep_copy: bool = True, source: str = "") -> list:
    """Strict structural audit of a raw custom-symbol document.

    Does **not** call ``normalise`` and does not repair data. Reports findings
    for issues that ``normalise`` might silently fix (missing pin ids, bad
    directions, etc.). Never raises for malformed field types: unhashable
    values, overflow, and unexpected nested structures become findings.

    When *deep_copy* is True (default), operates on a deep copy so the
    caller's document is unchanged.
    """
    findings = []
    try:
        if deep_copy:
            doc = copy.deepcopy(doc)
    except Exception as e:  # noqa: BLE001
        return [Finding("<unknown>", f"document could not be copied for inspection: {e}",
                        SEVERITY_ERROR, source=source)]

    if not isinstance(doc, dict):
        return [Finding("<unknown>", "symbol document is not a JSON object", SEVERITY_ERROR, source=source)]

    sid = str(doc.get("id") or "") or "<missing-id>"
    _validate_document_header(doc, sid, findings, source)
    _validate_document_pins(doc, sid, findings, source)
    _validate_document_prims(doc, sid, findings, source)
    return findings
