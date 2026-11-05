"""Loading and saving OpenSchematix single-sheet documents."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field

from . import FILE_FORMAT, FILE_SCHEMA, safejson, symbols
from .editing import route
from .geometry import norm_rotation, snap
from .model import Component, Document, Wire
from .symbols.fluid import default_valve_params
from .symbols.general import UNKNOWN_ID


class FileFormatError(ValueError):
    pass


@dataclass
class LoadResult:
    document: Document
    migrated: bool = False
    warnings: list = field(default_factory=list)


def save(doc: Document, path: str):
    """Write atomically: a crash or full disk never leaves a half-written file."""
    d = doc.to_dict()
    where = safejson.find_non_finite(d)
    if where is not None:
        raise FileFormatError(f"Cannot save: the drawing contains a value that is not a finite number ({where}).")
    data = json.dumps(d, indent=1, ensure_ascii=False, allow_nan=False)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".osch-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


MAX_FILE_BYTES = 200 * 1024 * 1024


def load(path: str) -> LoadResult:
    with open(path, "rb") as f:
        raw = f.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise FileFormatError("The file is unreasonably large for a schematic drawing.")
    try:
        data = safejson.loads(raw)
    except safejson.JSONFormatError as e:
        raise FileFormatError(f"The file {e}.") from None
    return load_data(data)


def load_data(data) -> LoadResult:
    if not isinstance(data, dict):
        raise FileFormatError("Unrecognised file contents.")
    fmt = data.get("format")
    if fmt == FILE_FORMAT:
        schema = data.get("schema", 1)
        if isinstance(schema, bool) or not isinstance(schema, int) or schema > FILE_SCHEMA:
            raise FileFormatError("This file was written by a newer version of OpenSchematix "
                                  f"(schema {schema if isinstance(schema, int) else '?'}).")
        try:
            doc = Document.from_dict(data)
        except ValueError as e:
            raise FileFormatError(f"The file is damaged or incomplete: {e}") from None
        res = LoadResult(doc)
        unknown = sorted({c.symbol for c in doc.components.values() if symbols.lookup(c.symbol) is None})
        if unknown:
            res.warnings.append("Unknown symbols shown as placeholders: " + ", ".join(unknown))
        return res
    raise FileFormatError("Not an OpenSchematix file.")


