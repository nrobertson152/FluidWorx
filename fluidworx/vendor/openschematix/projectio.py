"""Reading and writing ``.schematix`` project files, and opening older
documents (including legacy single-sheet drawings).

The ``.schematix`` container is a ZIP archive (see docs/FILE_FORMAT.md):

    mimetype                         application/x-openschematix-project (stored, first)
    manifest.json                    container format/version, app version, sheet list
    project.json                     metadata, settings, layers, sheet order
    sheets/<sheet uid>.json          one JSON document per sheet
    symbols/<n>.osym                 embedded custom symbol definitions
    revisions/index.json             revision history entries
    revisions/objects/<sha256>       content-addressed, zlib-compressed snapshots

All member paths are relative and machine-independent. Files are written to
a temporary file in the destination folder, flushed to disk and then
atomically renamed over the destination, so an interrupted save never
damages the previous file.
"""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field

from . import FILE_FORMAT, VERSION, fileio, safejson
from .model import SHEET_SCHEMA, Document
from .project import Project, project_from_document
from .revisions import RevisionDataError, RevisionStore

PROJECT_FORMAT = "OpenSchematix Project"
PROJECT_VERSION = 1            # container layout version
PROJECT_EXTENSION = ".schematix"
MIMETYPE = "application/x-openschematix-project"
MAX_MEMBER_BYTES = 200 * 1024 * 1024      # one member, uncompressed
MAX_TOTAL_BYTES = 1024 * 1024 * 1024      # all members together, uncompressed
MAX_MEMBERS = 100_000


class ProjectFormatError(ValueError):
    """The file is not a readable OpenSchematix project. The message says
    which part is damaged and how; it never quotes the file's content."""


@dataclass
class OpenResult:
    project: Project
    migrated: bool = False          # converted from an older format: must be saved under a new name
    source_format: str = "schematix"
    warnings: list = field(default_factory=list)
    # Parts of the file were damaged and left out (revisions, embedded
    # symbols); `warnings` lists them. Like a migrated file, the project must
    # be saved under a new name, so the damaged original is never overwritten.
    recovered: bool = False

    @property
    def needs_new_name(self) -> bool:
        return self.migrated or self.recovered


# ================================================================ writing
def project_bytes(project: Project) -> bytes:
    """Serialise a project to .schematix bytes."""
    import io
    buf = io.BytesIO()
    write_zip(project, buf)
    return buf.getvalue()


def required_schema(project: Project) -> int:
    """Sheet schema written to the manifest: the lowest one able to hold
    every sheet AND every revision snapshot stored in the file (2 unless a
    boundary fill exists anywhere, so fill-free projects open in 1.0.x)."""
    need = max((doc.required_schema() for doc in project.sheets), default=2)
    if project.revisions is not None:
        need = max(need, project.revisions.required_schema())
    return need


def _dumps(obj, member: str) -> str:
    """JSON for one member. Non-finite numbers are not valid JSON and no
    reader accepts them, so they are reported instead of written."""
    where = safejson.find_non_finite(obj)
    if where is not None:
        raise ProjectFormatError(f"cannot save: {member} contains a value that is not a finite number ({where})")
    return json.dumps(obj, indent=1, ensure_ascii=False, allow_nan=False)


def _restore_symbols(project: Project, saved: dict) -> None:
    """Put back the embedded-symbol map captured by dict(project.symbols).

    Serialising (Project.to_dict -> embed_symbols) re-embeds custom symbols:
    it replaces or deletes entries of project.symbols but never edits a
    definition in place, so a shallow copy restores it exactly. The dict is
    restored in place to keep its identity for callers holding it."""
    project.symbols.clear()
    project.symbols.update(saved)


def check_savable(project: Project) -> None:
    """Validate every serialized member before recording a save snapshot.

    Sheets alone are insufficient: embedded symbols, the manifest and the
    revision index must also be serializable. This does not mutate the project:
    the embedded symbols that serialising re-embeds are restored afterwards.
    """
    saved = dict(project.symbols)
    try:
        project_bytes(project)
    finally:
        _restore_symbols(project, saved)


def write_zip(project: Project, fileobj):
    d = project.to_dict()
    sheets = d.pop("sheets")
    symbols = d.pop("symbols")
    manifest = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "sheet_schema": required_schema(project),
        "app": f"OpenSchematix {VERSION}",
        "project_uid": project.uid,
        "sheets": [{"uid": s["uid"], "name": s["name"], "path": f"sheets/{s['uid']}.json"} for s in sheets],
        "symbols": [],
        "revisions": "revisions/index.json" if project.revisions is not None else None,
    }
    with zipfile.ZipFile(fileobj, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED)
        for i, (sid, sdoc) in enumerate(sorted(symbols.items())):
            path = f"symbols/{i + 1:04d}.osym"
            manifest["symbols"].append({"id": sid, "path": path})
            z.writestr(path, _dumps(sdoc, f"embedded symbol {sid}"))
        z.writestr("manifest.json", _dumps(manifest, "the manifest"))
        d["sheet_order"] = [s["uid"] for s in sheets]
        z.writestr("project.json", _dumps(d, "the project settings"))
        for s in sheets:
            z.writestr(f"sheets/{s['uid']}.json", _dumps(s, f"sheet '{s['name']}'"))
        if project.revisions is not None:
            st = project.revisions
            z.writestr("revisions/index.json", _dumps(st.index(), "the revision index"))
            for h, blob in st.objects.items():
                z.writestr(zipfile.ZipInfo(f"revisions/objects/{h}"), blob, compress_type=zipfile.ZIP_STORED)


def atomic_write_bytes(path: str, data: bytes):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".schematix-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
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


def save_project(project: Project, path: str, snapshot: bool = True):
    """Save atomically. With `snapshot`, an automatic revision snapshot is
    recorded first if the content changed since the last snapshot.

    A save that fails leaves the project as it was: no new revision, and the
    embedded symbols unchanged (serialising re-embeds them, see
    _restore_symbols); a committed save keeps the re-embedded symbols."""
    original_symbols = dict(project.symbols)
    original_store = project.revisions
    # Keep the original store identity for any callers holding a reference.
    # A failed serialization, verification, or disk write must not leave a
    # newly recorded revision in memory when no save was committed.
    original_state = None
    if original_store is not None:
        original_state = (
            list(original_store.entries),
            dict(original_store.objects),
            dict(original_store._schema_cache),
        )
    try:
        check_savable(project)      # validate all existing members before recording a snapshot
        if project.revisions is None:
            project.revisions = RevisionStore()
        if snapshot:
            project.revisions.create(project, "auto", description="Saved")
        data = project_bytes(project)
        # verify before replacing the user's file: the bytes must load back
        verified = _verify(data, project.revisions)
        atomic_write_bytes(path, data)
    except BaseException:
        _restore_symbols(project, original_symbols)
        if original_store is None:
            project.revisions = None
        else:
            original_store.entries[:] = original_state[0]
            original_store.objects.clear()
            original_store.objects.update(original_state[1])
            original_store._schema_cache.clear()
            original_store._schema_cache.update(original_state[2])
            project.revisions = original_store
        raise
    if verified is not None and verified.project.revisions is not None:
        # history now known to be intact: later saves need not parse it again
        project.revisions.mark_verified(verified.project.revisions._verified)


def _verify(data: bytes, revisions: RevisionStore | None = None) -> OpenResult:
    """Check that `data` reads back as a complete project; raise OSError if not.

    The bytes must load with nothing left out: a part that reopening would
    drop as damaged is as bad as an unreadable file. Revision objects that
    `revisions` has already verified, and that are byte-identical in `data`,
    are not parsed again, so the cost of a save does not grow with the
    length of the history."""
    import io
    try:
        res = read_zip(io.BytesIO(data), trusted_revisions=revisions)
    except Exception as e:  # noqa: BLE001 - never replace a good file with a bad one
        raise OSError(f"internal error: the project could not be verified before saving ({e})") from e
    if res.recovered:
        raise OSError("internal error: the project could not be verified before saving (parts of it would "
                      "not reopen: " + "; ".join(res.warnings) + ")")
    return res


# ================================================================ reading
# Every way a damaged file can fail is classified here as ProjectFormatError
# (whole file unreadable) or as a warning with OpenResult.recovered (a
# damaged part left out). Model readers raise ValueError for malformed data;
# nothing else is caught, so any other exception is a programming defect and
# is reported as one (see gui/errors.py) instead of as a damaged file.

# Exceptions zipfile raises while reading a member's bytes: damaged
# compressed data (zlib.error, EOFError), bad CRC (BadZipFile), an unknown
# compression method (NotImplementedError) or an encrypted member (RuntimeError).
_MEMBER_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError)


def _read_member(z: zipfile.ZipFile, name: str, limit: int | None = None) -> bytes:
    limit = MAX_MEMBER_BYTES if limit is None else limit
    try:
        info = z.getinfo(name)
    except KeyError:
        raise ProjectFormatError(f"the project file is missing '{name}'") from None
    if info.file_size > limit:
        raise ProjectFormatError(f"'{name}' is unreasonably large")
    try:
        return z.read(info)
    except _MEMBER_ERRORS as e:
        raise ProjectFormatError(f"'{name}' is damaged ({type(e).__name__})") from None


def _read_json(z: zipfile.ZipFile, name: str):
    try:
        return safejson.loads(_read_member(z, name))
    except safejson.JSONFormatError as e:
        raise ProjectFormatError(f"'{name}' {e}") from None


def _str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def read_zip(fileobj, trusted_revisions: RevisionStore | None = None) -> OpenResult:
    """Read a .schematix container. Raises ProjectFormatError if the
    project cannot be read; damaged revisions and embedded symbols are left
    out with a warning (OpenResult.recovered). Changes no global state.
    `trusted_revisions`: see RevisionStore.from_file (used by the pre-save check)."""
    try:
        z = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, EOFError, ValueError) as e:
        raise ProjectFormatError("the file is not a valid OpenSchematix project (damaged ZIP container)") from e
    with z:
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise ProjectFormatError("the project file is unreasonably large")
        manifest = _read_json(z, "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("format") != PROJECT_FORMAT:
            raise ProjectFormatError("the file is not an OpenSchematix project")
        ver = manifest.get("version")
        if isinstance(ver, bool) or not isinstance(ver, int) or ver > PROJECT_VERSION:
            raise ProjectFormatError(f"this project was written by a newer version of OpenSchematix "
                                     f"(container version {ver if isinstance(ver, int) else '?'}); "
                                     f"please update the program")
        schema = manifest.get("sheet_schema", SHEET_SCHEMA)
        if isinstance(schema, bool) or not isinstance(schema, int) or schema > SHEET_SCHEMA:
            raise ProjectFormatError(f"this project uses sheet schema "
                                     f"{schema if isinstance(schema, int) else '?'}, newer than supported "
                                     f"({SHEET_SCHEMA})")
        head = _read_json(z, "project.json")
        if not isinstance(head, dict):
            raise ProjectFormatError("'project.json' is damaged: it is not a JSON object")
        warnings, recovered = [], False
        entries = manifest.get("sheets", [])
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise ProjectFormatError("'manifest.json' is damaged: the sheet list is invalid")
        sheets = []
        for entry in entries:
            path = entry.get("path", "")
            if not isinstance(path, str) or not path.startswith("sheets/") or ".." in path:
                raise ProjectFormatError("'manifest.json' is damaged: invalid sheet path")
            sheets.append(_read_json(z, path))
        order = head.pop("sheet_order", None)
        if order is not None and not _str_list(order):
            raise ProjectFormatError("'project.json' is damaged: the sheet order is invalid")
        if order:
            pos = {u: i for i, u in enumerate(order)}

            def rank(s):
                uid = s.get("uid") if isinstance(s, dict) else None
                return pos.get(uid, len(pos)) if isinstance(uid, str) else len(pos)
            sheets.sort(key=rank)
        head["sheets"] = sheets
        symbols, problems = _read_symbols(z, manifest.get("symbols", []))
        if problems:
            recovered = True
            warnings += problems
        head["symbols"] = symbols
        try:
            project = Project.from_dict(head)
        except ValueError as e:
            raise ProjectFormatError(f"the project is damaged: {e}") from None
        store = RevisionStore()
        if manifest.get("revisions"):
            store, problems = _read_revisions(z, trusted_revisions)
            if problems:
                recovered = True
                warnings.append(
                    "The revision history is damaged. Revisions that could not be read were left out "
                    f"({len(problems)}): " + "; ".join(problems) + ". The file itself is unchanged; save the "
                    "project under a new name to keep the original.")
        project.revisions = store
    return OpenResult(project, warnings=warnings, recovered=recovered)


def _read_symbols(z: zipfile.ZipFile, entries) -> tuple[dict, list]:
    """Embedded custom symbols: (documents by id, problems)."""
    from .symbols.custom import SymbolFormatError, to_symdef
    if not isinstance(entries, list):
        return {}, ["The list of embedded custom symbols is damaged; none were loaded."]
    out, problems = {}, []
    for i, entry in enumerate(entries):
        path = entry.get("path", "") if isinstance(entry, dict) else ""
        if not isinstance(path, str) or not path.startswith("symbols/") or ".." in path:
            problems.append(f"Embedded symbol entry {i + 1} is damaged and was not loaded.")
            continue
        try:
            doc = _read_json(z, path)
        except ProjectFormatError as e:
            problems.append(f"An embedded custom symbol could not be loaded: {e}")
            continue
        sid = doc.get("id", entry.get("id")) if isinstance(doc, dict) else None
        rev = doc.get("revision", 0) if isinstance(doc, dict) else None
        if not isinstance(sid, str) or not sid or isinstance(rev, bool) or not isinstance(rev, int):
            # the id keys the symbol; the revision is compared when saving (Project.embed_symbols)
            problems.append(f"The embedded custom symbol in '{path}' is damaged and was not loaded.")
            continue
        # A malformed structural container is not a recoverable drawing
        # definition. Preserve only semantically invalid but structurally
        # well-formed symbol documents for lossless round-tripping.
        if (any(key in doc and doc[key] is not None and not isinstance(doc[key], list)
                for key in ("tags", "prims", "pins")) or
                ("properties" in doc and doc["properties"] is not None and
                 not isinstance(doc["properties"], dict))):
            problems.append(f"The embedded custom symbol {sid} is damaged (invalid field structure) and was "
                            "not loaded; its components are shown as placeholders.")
            continue
        try:
            to_symdef(doc)
        except SymbolFormatError:
            pass        # kept: semantically invalid symbols are preserved unchanged
        except (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError, RecursionError) as e:
            problems.append(f"The embedded custom symbol {sid} is damaged ({type(e).__name__}) and was not "
                            "loaded; its components are shown as placeholders.")
            continue
        out[sid] = doc
    return out, problems


def _read_revisions(z: zipfile.ZipFile, trusted: RevisionStore | None = None) -> tuple[RevisionStore, list]:
    try:
        index = _read_json(z, "revisions/index.json")
    except ProjectFormatError as e:
        return RevisionStore(), [f"no revisions could be read: {e}"]
    names = set(z.namelist())

    def read_object(h):
        name = f"revisions/objects/{h}"
        if name not in names:
            return None
        try:
            return _read_member(z, name)
        except ProjectFormatError as e:
            raise RevisionDataError(str(e)) from None
    return RevisionStore.from_file(index, read_object, trusted)


def open_any(path: str, activate: bool = True) -> OpenResult:
    """Open a .schematix project, or convert a legacy drawing into a
    new (unsaved) one-sheet project. The original file is never modified.

    With `activate` (the default, for the project that becomes the open one) the project's embedded
    symbols are registered as the active project symbols. With activate=False the global symbol
    registry is left untouched, so a file can be read (imported, used as a template, compared) without
    disturbing the project that is currently open."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith(b"PK"):
        with open(path, "rb") as f:
            res = read_zip(f)
        if activate:
            res.warnings += res.project.activate_symbols()
        else:
            res.warnings += res.project.embedded_symdefs()[1]
        _check_unknown(res)
        return res
    try:
        legacy = fileio.load(path)
    except fileio.FileFormatError as e:
        raise ProjectFormatError(str(e)) from e
    name = os.path.splitext(os.path.basename(path))[0]
    project = project_from_document(legacy.document, title=legacy.document.sheet.title or name)
    project.revisions = RevisionStore()
    if activate:
        project.activate_symbols()
    fmt = "legacy" if legacy.migrated else "osch"
    warnings = list(legacy.warnings)
    warnings.insert(0, f"Converted from an older drawing format. "
                       f"The original file is unchanged; save the project as a new {PROJECT_EXTENSION} file.")
    return OpenResult(project, migrated=True, source_format=fmt, warnings=warnings)


def _check_unknown(res: OpenResult):
    resolve = res.project.symbol_resolver()
    unknown = sorted({c.symbol for _s, c in res.project.all_components() if resolve(c.symbol) is None})
    if unknown:
        res.warnings.append("Unknown symbols shown as placeholders: " + ", ".join(unknown))


def suggested_project_path(source_path: str) -> str:
    base = os.path.splitext(source_path)[0]
    cand = base + PROJECT_EXTENSION
    n = 2
    while os.path.exists(cand):
        cand = f"{base} ({n}){PROJECT_EXTENSION}"
        n += 1
    return cand


def export_sheet_osch(doc: Document, path: str):
    """Export one sheet as a standalone .osch drawing (schema 2)."""
    fileio.save(doc, path)


__all__ = ["required_schema", "PROJECT_EXTENSION", "ProjectFormatError", "OpenResult", "save_project", "open_any", "read_zip",
           "project_bytes", "FILE_FORMAT"]
