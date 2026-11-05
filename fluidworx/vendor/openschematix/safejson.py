"""Strict JSON reading for files from disk (projects, revision snapshots,
legacy drawings).

Python's ``json`` module accepts input that no OpenSchematix version writes
and that later code cannot handle: the non-standard constants ``NaN`` and
``Infinity``, numbers that overflow to infinity (``1e999``), integers with
thousands of digits (which raise ValueError, or OverflowError on conversion)
and nesting deep enough to exhaust the interpreter stack (RecursionError,
here or in any later recursive copy). This module rejects all of these with
one exception type, so every damaged file is reported the same way and no
non-finite number ever reaches the drawing engine.
"""
from __future__ import annotations

import json
import math

MAX_DEPTH = 64            # real files nest at most ~6 levels (symbol primitives)
MAX_INT_DIGITS = 18       # anything longer cannot be a valid id, count or coordinate


class JSONFormatError(ValueError):
    """The text is not valid OpenSchematix JSON. The message describes where
    and why, never the offending content."""


def _bad_constant(name):
    raise JSONFormatError(f"contains the non-standard number {name}")


def _parse_float(s: str) -> float:
    f = float(s)
    if not math.isfinite(f):
        raise JSONFormatError("contains a number too large to represent")
    return f


def _parse_int(s: str) -> int:
    if len(s.lstrip("-")) > MAX_INT_DIGITS:
        raise JSONFormatError("contains an integer that is too large")
    return int(s)


def loads(data) -> object:
    """Parse `data` (bytes in UTF-8, or str). Raises JSONFormatError."""
    if isinstance(data, (bytes, bytearray)):
        try:
            data = bytes(data).decode("utf-8")
        except UnicodeDecodeError as e:
            raise JSONFormatError(f"is not UTF-8 text (byte {e.start})") from None
    try:
        obj = json.loads(data, parse_constant=_bad_constant, parse_float=_parse_float, parse_int=_parse_int)
    except JSONFormatError:
        raise
    except json.JSONDecodeError as e:
        # e.msg and the position only: e.doc (the content) is never included
        raise JSONFormatError(f"is not valid JSON ({e.msg} at line {e.lineno}, column {e.colno})") from None
    except RecursionError:
        raise JSONFormatError(f"is nested too deeply (more than {MAX_DEPTH} levels)") from None
    check_depth(obj)
    return obj


def check_depth(obj, limit: int = MAX_DEPTH) -> None:
    """Raise JSONFormatError if containers nest deeper than `limit`
    (iterative, so it cannot itself run out of stack)."""
    stack = [(obj, 1)]
    while stack:
        o, d = stack.pop()
        if isinstance(o, dict):
            children = o.values()
        elif isinstance(o, list):
            children = o
        else:
            continue
        if d > limit:
            raise JSONFormatError(f"is nested too deeply (more than {limit} levels)")
        stack.extend((c, d + 1) for c in children)


def find_non_finite(obj, path: str = "") -> str | None:
    """Location (e.g. ``wires[3].points[0][1]``) of the first NaN or infinite
    float in `obj`, or None. Used before writing, so a damaged in-memory
    value is reported instead of being written as invalid JSON."""
    stack = [(obj, path)]
    while stack:
        o, p = stack.pop()
        if isinstance(o, float):
            if not math.isfinite(o):
                return p or "<value>"
        elif isinstance(o, dict):
            stack.extend((v, f"{p}.{k}" if p else str(k)) for k, v in reversed(list(o.items())))
        elif isinstance(o, (list, tuple)):
            stack.extend((v, f"{p}[{i}]") for i, v in reversed(list(enumerate(o))))
    return None
