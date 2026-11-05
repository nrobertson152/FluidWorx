"""The `.fluidworx` study file. See docs/FILE_FORMAT.md.

A study is a ZIP like a `.schematix`: a mimetype member first, JSON manifest and study data, and a byte-exact
copy of the schematic it simulates. The schematic stays OpenSchematix's: a study never edits it. Saves are
written to a temporary file, read back and verified, then renamed over the old file, as OpenSchematix does.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

from . import APP_NAME, VERSION
from .vendor.openschematix import safejson

MIMETYPE = "application/x-fluidworx-study"
FORMAT_NAME = "FluidWorx Study"
FORMAT_VERSION = 1
MAX_MEMBER = 200 * 1024 * 1024


class StudyError(ValueError):
    """The file cannot be used. The message is written for the user."""


@dataclass
class Study:
    source_name: str = ""               # original file name of the schematic
    source_path: str = ""               # where it was last seen on this computer (a hint, may be gone)
    source_sha256: str = ""
    source_bytes: bytes = b""
    source_rev: dict = field(default_factory=dict)      # RevisionWorx facts recorded when imported or reloaded
    units: str = "metric"
    params: dict = field(default_factory=dict)          # "uid/id" -> {param: SI value}, user edits only
    notes: str = ""
    created: str = ""

    @property
    def source_ext(self) -> str:
        ext = os.path.splitext(self.source_name)[1].lower()
        return ext if ext in (".schematix", ".osch") else ".schematix"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def part_id(key) -> str:
    return f"{key[0]}/{key[1]}"


def from_source(path: str) -> Study:
    with open(path, "rb") as f:
        data = f.read()
    return Study(source_name=os.path.basename(path), source_path=os.path.abspath(path), source_sha256=sha256(data),
                 source_bytes=data, created=datetime.now().isoformat(timespec="seconds"))


def to_bytes(study: Study) -> bytes:
    if not study.source_bytes:
        raise StudyError("This study has no schematic to save.")
    doc = {"created": study.created, "units": study.units, "notes": study.notes, "params": study.params,
           "source": {"name": study.source_name, "path": study.source_path, "sha256": study.source_sha256,
                      "revisionworx": study.source_rev}}
    manifest = {"format": FORMAT_NAME, "version": FORMAT_VERSION, "app": f"{APP_NAME} {VERSION}",
                "saved": datetime.now().isoformat(timespec="seconds"), "study": "study.json",
                "source": "source/schematic" + study.source_ext}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED)
        z.writestr("manifest.json", json.dumps(manifest, indent=1, allow_nan=False))
        z.writestr("study.json", json.dumps(doc, indent=1, allow_nan=False))
        z.writestr(manifest["source"], study.source_bytes)
    return buf.getvalue()


def _read(z: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = z.getinfo(name)
    except KeyError as e:
        raise StudyError(f"The study is damaged: {name} is missing.") from e
    if info.file_size > MAX_MEMBER:
        raise StudyError(f"The study is damaged: {name} is too large.")
    return z.read(info)


def _clean_params(raw) -> dict:
    out = {}
    if not isinstance(raw, dict):
        raise StudyError("The study is damaged: its parameters could not be read.")
    for pid, vals in raw.items():
        if not isinstance(pid, str) or not isinstance(vals, dict):
            continue
        good = {k: float(v) for k, v in vals.items() if isinstance(k, str) and isinstance(v, (int, float))
                and not isinstance(v, bool) and math.isfinite(v)}
        if good:
            out[pid] = good
    return out


def from_bytes(data: bytes) -> Study:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if not names or names[0] != "mimetype" or _read(z, "mimetype").decode("ascii", "replace").strip() != MIMETYPE:
                raise StudyError("This is not a FluidWorx study.")
            manifest = safejson.loads(_read(z, "manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != FORMAT_NAME:
                raise StudyError("This is not a FluidWorx study.")
            version = manifest.get("version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise StudyError("The study is damaged: its version could not be read.")
            if version > FORMAT_VERSION:
                raise StudyError(f"This study was saved by a newer FluidWorx (format {version}). Please update.")
            doc = safejson.loads(_read(z, "study.json"))
            source_member = manifest.get("source")
            if not isinstance(doc, dict) or not isinstance(source_member, str):
                raise StudyError("The study is damaged.")
            source = _read(z, source_member)
    except (zipfile.BadZipFile, safejson.JSONFormatError, UnicodeDecodeError, RuntimeError, OSError) as e:
        raise StudyError(f"The study is damaged and could not be read.\n\n{e}") from e
    src = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    recorded = str(src.get("sha256") or "")
    if recorded and recorded != sha256(source):
        raise StudyError("The study is damaged: its copy of the schematic does not match its checksum.")
    rev = src.get("revisionworx")
    units = doc.get("units")
    return Study(source_name=str(src.get("name") or os.path.basename(source_member)),
                 source_path=str(src.get("path") or ""), source_sha256=sha256(source), source_bytes=source,
                 source_rev=rev if isinstance(rev, dict) else {},
                 units=units if units in ("metric", "us") else "metric",
                 params=_clean_params(doc.get("params", {})), notes=str(doc.get("notes") or ""),
                 created=str(doc.get("created") or ""))


def save(study: Study, path: str) -> None:
    """Atomic and verified: an interrupted or failed save leaves the previous file untouched."""
    data = to_bytes(study)
    check = from_bytes(data)
    if check.source_sha256 != sha256(study.source_bytes) or check.params != _clean_params(study.params):
        raise StudyError("The study could not be saved: verification after writing failed.")
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".fluidworx-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, "rb") as f:
            if f.read() != data:
                raise StudyError("The study could not be saved: the disk returned different data.")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load(path: str) -> Study:
    try:
        with open(path, "rb") as f:
            return from_bytes(f.read())
    except OSError as e:
        raise StudyError(f"The study could not be opened.\n\n{e}") from e


def source_changed(study: Study) -> bool | None:
    """True if the schematic on disk differs from the study's copy; None if it can't be found."""
    if not study.source_path or not os.path.isfile(study.source_path):
        return None
    try:
        with open(study.source_path, "rb") as f:
            return sha256(f.read()) != study.source_sha256
    except OSError:
        return None
