"""User symbol libraries and library packages.

Libraries live in the user's configuration folder:

    <config>/libraries/<Library name>/<folder>/<subfolder>/<symbol>.osym

A library is a top-level folder; folders may be nested freely. Each
``.osym`` file holds one custom symbol (see symbols/custom.py). The symbol's
``id`` inside the file is its identity: moving or renaming files never
changes it, so drawings keep working.

Library packages (``.osymlib``) are ZIP files used to share libraries
between users; the format is documented in docs/LIBRARY_FORMAT.md:

    mimetype        application/x-openschematix-library (stored, first)
    manifest.json   {"format": "OpenSchematix Symbol Library", "version": 1,
                     "name", "description", "author", "created", "app",
                     "folders": ["Sensors", "Sensors/Inductive", ...],
                     "symbols": [{"id", "name", "revision", "folder", "file"}]}
    symbols/0001.osym ...
All paths inside a package are relative, use "/" and contain no "..".
"""
from __future__ import annotations

import copy
import datetime as _dt
import io
import json
import os
import re
import shutil
import struct
import tempfile
import zipfile
from dataclasses import dataclass, field

from . import VERSION, symbols
from .settings import config_dir
from .symbols.custom import (MAX_SYMBOL_BYTES, SYMBOL_FORMAT, SymbolFormatError, alias_problems,
                             load_symbol_json, new_symbol_id, normalise, parse_symbol_json, to_symdef)

LIB_FORMAT = "OpenSchematix Symbol Library"
LIB_VERSION = 1
LIB_MIMETYPE = "application/x-openschematix-library"
SYMBOL_EXT = ".osym"
PACKAGE_EXT = ".osymlib"
MAX_PACKAGE_ENTRIES = 2048
MAX_PACKAGE_SYMBOLS = 1000
MAX_PACKAGE_FOLDERS = 1024
MAX_PACKAGE_PATH_DEPTH = 16
MAX_PACKAGE_PATH_BYTES = 512
MAX_PACKAGE_UNCOMPRESSED = 64 * 1024 * 1024
MAX_PACKAGE_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_PACKAGE_DIRECTORY_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = MAX_SYMBOL_BYTES
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str, fallback: str = "Untitled") -> str:
    n = _BAD.sub("_", (name or "").strip()).strip(". ")
    if n.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
        n = "_" + n
    return n[:80] or fallback


def _rel_ok(p: str) -> bool:
    parts = p.replace("\\", "/").split("/")
    return bool(p) and not p.startswith("/") and ".." not in parts and ":" not in p


def _recover_interrupted_package_import(root: str):
    """Restore a prior library directory left in staging by an interrupted swap.

    The normal successful commit always leaves root present. A missing root
    with a sibling staging backup indicates the operation stopped after the
    old directory was moved but before the replacement was installed.
    """
    root = os.path.abspath(root)
    if os.path.exists(root):
        return
    parent = os.path.dirname(root)
    if not os.path.isdir(parent):
        return
    candidates = []
    for name in os.listdir(parent):
        if name.startswith(".osymlib-import-"):
            directory = os.path.join(parent, name)
            backup = os.path.join(directory, "previous")
            marker = os.path.join(directory, "target.txt")
            try:
                with open(marker, encoding="utf-8") as f:
                    expected = f.read(4097)
            except (OSError, UnicodeError):
                continue
            if expected == root and os.path.isdir(backup):
                candidates.append(backup)
    if candidates:
        backup = max(candidates, key=os.path.getmtime)
        os.replace(backup, root)


def _assert_no_library_symlinks(root: str) -> None:
    """Reject symlinks before copying an untrusted library into staging.

    Reject a symlinked library root and any linked directory/file anywhere in
    the source tree. Avoid following links; never traverse linked directories.
    """
    if os.path.islink(root):
        raise ValueError("library import cannot stage a symbolic-link library root")
    if not os.path.isdir(root):
        return
    for directory, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for name in dirs + files:
            if os.path.islink(os.path.join(directory, name)):
                raise ValueError("library import cannot stage symbolic links")


def _read_symbol_file(path: str) -> dict:
    """Read one .osym with a hard byte budget before JSON decoding."""
    with open(path, "rb") as f:
        raw = f.read(MAX_SYMBOL_BYTES + 1)
    if len(raw) > MAX_SYMBOL_BYTES:
        raise SymbolFormatError(f"symbol file exceeds {MAX_SYMBOL_BYTES} bytes: {path}")
    try:
        return load_symbol_json(raw.decode("utf-8"), source=path)
    except UnicodeDecodeError as e:
        raise SymbolFormatError(f"symbol file is not UTF-8: {path}") from e


def _zip_preflight(path: str):
    """Reject oversized archives and excessive directory entries before ZipFile.

    ZIP's end-of-central-directory record contains the entry count. ZIP64
    sentinel counts are rejected: packages support at most MAX_PACKAGE_ENTRIES.
    """
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size > MAX_PACKAGE_ARCHIVE_BYTES:
                raise ValueError(f"package archive exceeds {MAX_PACKAGE_ARCHIVE_BYTES} bytes")
            f.seek(max(0, size - (65535 + 22)))
            tail = f.read()
    except OSError as e:
        raise ValueError("cannot read symbol library package") from e
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or pos + 22 > len(tail):
        raise ValueError("not a valid symbol library package")
    disk, cd_disk, local_count, total_count, _cd_size, _cd_offset, _comment = struct.unpack_from(
        "<HHHHIIH", tail, pos + 4)
    if disk or cd_disk or local_count != total_count:
        raise ValueError("multi-disk ZIP packages are not supported")
    if _cd_size > MAX_PACKAGE_DIRECTORY_BYTES:
        raise ValueError(f"ZIP directory exceeds {MAX_PACKAGE_DIRECTORY_BYTES} bytes")
    if total_count > MAX_PACKAGE_ENTRIES:
        raise ValueError(f"package has more than {MAX_PACKAGE_ENTRIES} ZIP entries")


def _zip_member(z: zipfile.ZipFile, name: str, limit: int) -> str:
    """Read only up to the given byte limit, regardless of ZIP metadata."""
    try:
        entry = z.getinfo(name)
        if entry.is_dir():
            raise ValueError(f"package entry is a directory: {name}")
        if entry.file_size > limit:
            raise ValueError(f"package entry exceeds {limit} bytes: {name}")
        with z.open(entry) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError(f"package entry exceeds {limit} bytes: {name}")
        return raw.decode("utf-8")
    except KeyError as e:
        raise ValueError(f"missing package entry: {name}") from e
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, UnicodeDecodeError, OSError) as e:
        raise ValueError(f"unreadable package entry {name}: {e}") from e


def _package_rel_ok(path: str) -> bool:
    """Cross-platform, bounded package path; do not change local folder rules."""
    if not isinstance(path, str) or len(path) > MAX_PACKAGE_PATH_BYTES or not _rel_ok(path):
        return False
    if "\\" in path:
        return False
    parts = path.split("/")
    return (len(parts) <= MAX_PACKAGE_PATH_DEPTH
            and all(p not in ("", ".", "..") and safe_name(p) == p for p in parts))


def _atomic_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class Entry:
    id: str
    path: str          # absolute file path
    folder: str        # "Library/Folder/Sub" (relative to the libraries root, "/" separated)
    doc: dict

    @property
    def name(self):
        return self.doc.get("name", "")


class UserLibrary:
    """All user libraries under one root folder."""

    def __init__(self, root: str | None = None):
        self.root = root or os.path.join(config_dir(), "libraries")
        self.entries: dict[str, Entry] = {}
        self.problems: list[str] = []

    # ---------------------------------------------------------------- scanning
    def scan(self):
        _recover_interrupted_package_import(self.root)
        self.entries.clear()
        self.problems.clear()
        if not os.path.isdir(self.root):
            return
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames.sort()
            for fn in sorted(filenames):
                if not fn.lower().endswith(SYMBOL_EXT):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    doc = _read_symbol_file(path)
                except (OSError, ValueError) as e:
                    self.problems.append(f"{path}: {e}")
                    continue
                if doc["id"] in self.entries:
                    self.problems.append(f"{path}: duplicate symbol id {doc['id']} (ignored; first copy is "
                                         f"{self.entries[doc['id']].path})")
                    continue
                self.entries[doc["id"]] = Entry(doc["id"], path, self.rel(dirpath), doc)
        self.publish()

    def publish(self):
        """Register the user symbols with the symbol registry."""
        defs = []
        for e in self.entries.values():
            try:
                defs.append(to_symdef(e.doc))
            except SymbolFormatError as ex:
                self.problems.append(f"{e.path}: {ex}")
        symbols.set_user_symbols(defs)

    def rel(self, abs_dir: str) -> str:
        r = os.path.relpath(abs_dir, self.root)
        return "" if r == "." else r.replace(os.sep, "/")

    def abs(self, folder: str) -> str:
        if folder and not _rel_ok(folder):
            raise ValueError(f"invalid folder {folder!r}")
        return os.path.join(self.root, *folder.split("/")) if folder else self.root

    # ---------------------------------------------------------------- folders
    def libraries(self) -> list[str]:
        if not os.path.isdir(self.root):
            return []
        return sorted(d for d in os.listdir(self.root) if os.path.isdir(os.path.join(self.root, d)))

    def folders(self) -> list[str]:
        out = []
        if not os.path.isdir(self.root):
            return out
        for dirpath, dirnames, _f in os.walk(self.root):
            dirnames.sort()
            r = self.rel(dirpath)
            if r:
                out.append(r)
        return out

    def create_folder(self, parent: str, name: str) -> str:
        folder = f"{parent}/{safe_name(name)}" if parent else safe_name(name)
        p = self.abs(folder)
        if os.path.exists(p):
            raise FileExistsError(f"a folder named {name!r} already exists")
        os.makedirs(p)
        return folder

    def rename_folder(self, folder: str, new_name: str) -> str:
        parent = folder.rsplit("/", 1)[0] if "/" in folder else ""
        dest = f"{parent}/{safe_name(new_name)}" if parent else safe_name(new_name)
        if os.path.exists(self.abs(dest)):
            raise FileExistsError(f"{new_name!r} already exists")
        os.rename(self.abs(folder), self.abs(dest))
        self.scan()
        return dest

    def move_folder(self, folder: str, new_parent: str) -> str:
        name = folder.rsplit("/", 1)[-1]
        dest = f"{new_parent}/{name}" if new_parent else name
        if dest == folder or dest.startswith(folder + "/"):
            raise ValueError("cannot move a folder into itself")
        if os.path.exists(self.abs(dest)):
            raise FileExistsError(f"{dest!r} already exists")
        shutil.move(self.abs(folder), self.abs(dest))
        self.scan()
        return dest

    def copy_folder(self, folder: str, new_parent: str) -> str:
        """Copy a folder; the copies get new symbol ids (they are new symbols)."""
        name = folder.rsplit("/", 1)[-1]
        dest = f"{new_parent}/{name}" if new_parent else name
        n = 2
        while os.path.exists(self.abs(dest)):
            dest = f"{new_parent}/{name} ({n})" if new_parent else f"{name} ({n})"
            n += 1
        shutil.copytree(self.abs(folder), self.abs(dest))
        for dirpath, _d, files in os.walk(self.abs(dest)):
            for fn in files:
                if fn.lower().endswith(SYMBOL_EXT):
                    p = os.path.join(dirpath, fn)
                    try:
                        with open(p, encoding="utf-8") as f:
                            doc = json.load(f)
                        doc["id"] = new_symbol_id()
                        doc["revision"] = 0
                        doc.pop("aliases", None)      # aliases stay with the original
                        _atomic_json(p, doc)
                    except (OSError, ValueError):
                        pass
        self.scan()
        return dest

    def delete_folder(self, folder: str):
        if not folder:
            raise ValueError("cannot delete the library root")
        shutil.rmtree(self.abs(folder))
        self.scan()

    # ---------------------------------------------------------------- symbols
    def save_symbol(self, doc: dict, folder: str) -> Entry:
        """Create or update a symbol. Updating increments its revision; the
        id never changes, so drawings using it stay connected."""
        doc = normalise(copy.deepcopy(doc))
        problems = alias_problems(doc.get("aliases", []), doc["id"], self.alias_pairs())
        if problems:
            raise ValueError("Symbol aliases: " + "; ".join(problems) + ".")
        old = self.entries.get(doc["id"])
        doc["revision"] = (old.doc.get("revision", 0) + 1) if old else max(1, doc.get("revision", 0))
        doc["modified"] = _dt.datetime.now().isoformat(timespec="seconds")
        target_dir = self.abs(folder)
        os.makedirs(target_dir, exist_ok=True)
        if old and os.path.dirname(old.path) == target_dir:
            path = old.path
            want = os.path.join(target_dir, safe_name(doc["name"]) + SYMBOL_EXT)
            if os.path.basename(want) != os.path.basename(path) and not os.path.exists(want):
                path = want
        else:
            path = self._free_path(target_dir, doc["name"])
        _atomic_json(path, doc)
        if old and os.path.abspath(old.path) != os.path.abspath(path):
            try:
                os.unlink(old.path)
            except OSError:
                pass
        self.scan()
        return self.entries[doc["id"]]

    def alias_pairs(self) -> list[tuple[str, tuple, str]]:
        """(id, aliases, name) of the built-in symbols and of every library symbol (see alias_problems)."""
        return symbols.alias_pairs(symbols.builtin_symbols()) + \
            [(sid, tuple(e.doc.get("aliases", ())), e.doc.get("name", "")) for sid, e in self.entries.items()]

    def _free_path(self, d: str, name: str) -> str:
        base = safe_name(name)
        p = os.path.join(d, base + SYMBOL_EXT)
        n = 2
        while os.path.exists(p):
            p = os.path.join(d, f"{base} ({n}){SYMBOL_EXT}")
            n += 1
        return p

    def move_symbol(self, sid: str, folder: str):
        e = self.entries[sid]
        d = self.abs(folder)
        os.makedirs(d, exist_ok=True)
        dest = self._free_path(d, e.name)
        shutil.move(e.path, dest)
        self.scan()

    def copy_symbol(self, sid: str, folder: str) -> Entry:
        e = self.entries[sid]
        doc = copy.deepcopy(e.doc)
        doc["id"] = new_symbol_id()
        doc["revision"] = 0
        doc.pop("aliases", None)              # aliases stay with the original
        if os.path.abspath(self.abs(folder)) == os.path.dirname(os.path.abspath(e.path)):
            doc["name"] = doc["name"] + " (copy)"
        return self.save_symbol(doc, folder)

    def rename_symbol(self, sid: str, name: str) -> Entry:
        e = self.entries[sid]
        doc = copy.deepcopy(e.doc)
        doc["name"] = name.strip() or doc["name"]
        return self.save_symbol(doc, e.folder)

    def delete_symbol(self, sid: str):
        e = self.entries.pop(sid)
        os.unlink(e.path)
        self.scan()

    def set_tags(self, sid: str, tags: list, category: str | None = None):
        e = self.entries[sid]
        doc = copy.deepcopy(e.doc)
        doc["tags"] = [t.strip() for t in tags if t.strip()]
        if category:
            doc["category"] = category
        return self.save_symbol(doc, e.folder)

    def in_folder(self, folder: str, recursive: bool = False) -> list[Entry]:
        out = []
        for e in self.entries.values():
            if e.folder == folder or (recursive and (folder == "" or e.folder.startswith(folder + "/"))):
                out.append(e)
        return sorted(out, key=lambda e: e.name.lower())

    def search(self, query: str, folder: str | None = None, category: str | None = None, tag: str | None = None):
        words = query.lower().split()
        out = []
        for e in self.entries.values():
            d = e.doc
            if folder is not None and not (e.folder == folder or e.folder.startswith(folder + "/")):
                continue
            if category and d.get("category") != category:
                continue
            if tag and tag.lower() not in (t.lower() for t in d.get("tags", [])):
                continue
            blob = " ".join([d.get("name", ""), d.get("description", ""), d.get("category", ""), d.get("group", ""),
                             d.get("prefix", ""), e.folder, *d.get("tags", []), *d.get("aliases", [])]).lower()
            if all(w in blob for w in words):
                out.append(e)
        return sorted(out, key=lambda e: e.name.lower())

    def all_tags(self) -> list[str]:
        return sorted({t for e in self.entries.values() for t in e.doc.get("tags", [])}, key=str.lower)

    # ---------------------------------------------------------------- single symbols
    def export_symbol(self, sid: str, path: str):
        doc = copy.deepcopy(self.entries[sid].doc)
        _atomic_json(path, doc)

    def import_symbol_file(self, path: str, folder: str, on_conflict: str = "duplicate") -> Entry | None:
        return self.import_symbol_doc(_read_symbol_file(path), folder, on_conflict)

    def import_symbol_doc(self, data: dict, folder: str, on_conflict: str = "duplicate") -> Entry | None:
        """on_conflict (same id already present): skip | replace | duplicate."""
        doc = normalise(data)
        if doc["id"] in self.entries:
            if on_conflict == "skip":
                return None
            if on_conflict == "duplicate":
                doc["id"] = new_symbol_id()
                doc["revision"] = 0
                doc.pop("aliases", None)      # aliases stay with the original
            elif on_conflict == "replace":
                old = self.entries[doc["id"]]
                doc["revision"] = max(doc.get("revision", 0), old.doc.get("revision", 0))
                # save_symbol writes the replacement atomically and only then
                # removes the previous file, preserving it on write failure.
        # an imported symbol must not take identifiers already in use: keep only its unambiguous aliases
        if doc.get("aliases"):
            pairs = self.alias_pairs()
            keep = [a for a in doc["aliases"] if not alias_problems([a], doc["id"], pairs)]
            if keep:
                doc["aliases"] = keep
            else:
                doc.pop("aliases")
        return self.save_symbol(doc, folder)

    # ---------------------------------------------------------------- packages
    def export_package(self, folder: str, path: str, description: str = "", author: str = ""):
        """Export a library (or any folder) with its subfolders as .osymlib."""
        name = folder.rsplit("/", 1)[-1] if folder else "Library"
        prefix = folder + "/" if folder else ""
        folders = [f[len(prefix):] for f in self.folders() if f.startswith(prefix)]
        syms = self.in_folder(folder, recursive=True)
        manifest = {"format": LIB_FORMAT, "version": LIB_VERSION, "name": name, "description": description,
                    "author": author, "created": _dt.datetime.now().isoformat(timespec="seconds"),
                    "app": f"OpenSchematix {VERSION}", "folders": folders, "symbols": []}
        if len(syms) > MAX_PACKAGE_SYMBOLS:
            raise ValueError(f"library contains more than {MAX_PACKAGE_SYMBOLS} symbols")
        if len(folders) > MAX_PACKAGE_FOLDERS or any(not _package_rel_ok(f) for f in folders):
            raise ValueError("library contains too many folders or an unsupported folder path")
        serialized = []
        uncompressed = len(LIB_MIMETYPE.encode("utf-8"))
        for i, e in enumerate(syms, 1):
            f = f"symbols/{i:04d}{SYMBOL_EXT}"
            rel = e.folder[len(prefix):] if e.folder.startswith(prefix) else ""
            if e.folder == folder:
                rel = ""
            if rel and not _package_rel_ok(rel):
                raise ValueError(f"unsupported library folder path: {rel!r}")
            manifest["symbols"].append({"id": e.id, "name": e.name, "revision": e.doc.get("revision", 0),
                                        "folder": rel, "file": f})
            payload = json.dumps(e.doc, indent=1, ensure_ascii=False).encode("utf-8")
            if len(payload) > MAX_SYMBOL_BYTES:
                raise ValueError(f"symbol {e.id} exceeds {MAX_SYMBOL_BYTES} bytes")
            uncompressed += len(payload)
            serialized.append((f, payload))
        manifest_data = json.dumps(manifest, indent=1, ensure_ascii=False).encode("utf-8")
        if len(manifest_data) > MAX_MANIFEST_BYTES:
            raise ValueError("library manifest exceeds the package import size limit")
        if uncompressed + len(manifest_data) > MAX_PACKAGE_UNCOMPRESSED:
            raise ValueError("library exceeds the package import uncompressed size limit")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo("mimetype"), LIB_MIMETYPE, compress_type=zipfile.ZIP_STORED)
            for f, payload in serialized:
                z.writestr(f, payload)
            z.writestr("manifest.json", manifest_data)
        if buf.tell() > MAX_PACKAGE_ARCHIVE_BYTES:
            raise ValueError("library exceeds the package import archive size limit")
        from .projectio import atomic_write_bytes
        atomic_write_bytes(path, buf.getvalue())
        return manifest


@dataclass
class PackageItem:
    id: str
    name: str
    folder: str
    doc: dict
    revision: int = 0
    conflict: str = ""        # "" | "same id" | "same id (older here)" | "same id (newer here)"


@dataclass
class PackageInfo:
    path: str
    name: str
    description: str
    author: str
    created: str
    folders: list = field(default_factory=list)
    items: list = field(default_factory=list)
    problems: list = field(default_factory=list)

    @property
    def conflicts(self):
        return [i for i in self.items if i.conflict]


def read_package(path: str, lib: UserLibrary | None = None) -> PackageInfo:
    """Read a bounded, validated package for preview; do not write to disk."""
    _zip_preflight(path)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError("not a valid symbol library package") from e
    with z:
        entries = z.infolist()
        if len(entries) > MAX_PACKAGE_ENTRIES:
            raise ValueError(f"package has more than {MAX_PACKAGE_ENTRIES} ZIP entries")
        if sum(e.file_size for e in entries) > MAX_PACKAGE_UNCOMPRESSED:
            raise ValueError(f"package exceeds {MAX_PACKAGE_UNCOMPRESSED} uncompressed bytes")
        names = [e.filename for e in entries]
        if len(set(names)) != len(names):
            raise ValueError("package contains duplicate ZIP member names")
        try:
            man = parse_symbol_json(_zip_member(z, "manifest.json", MAX_MANIFEST_BYTES),
                                    source="manifest.json")
        except (SymbolFormatError, ValueError) as e:
            raise ValueError(f"the package has no readable manifest: {e}") from e
        if man.get("format") != LIB_FORMAT:
            raise ValueError("not an OpenSchematix symbol library")
        version = man.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1 or version > LIB_VERSION:
            raise ValueError(f"unsupported library format version {version!r}")
        folders = man.get("folders", [])
        listed = man.get("symbols", [])
        if not isinstance(folders, list) or not isinstance(listed, list):
            raise ValueError("package manifest folders and symbols must be arrays")
        if len(folders) > MAX_PACKAGE_FOLDERS:
            raise ValueError(f"package contains more than {MAX_PACKAGE_FOLDERS} folders")
        if len(listed) > MAX_PACKAGE_SYMBOLS:
            raise ValueError(f"package contains more than {MAX_PACKAGE_SYMBOLS} symbols")
        info = PackageInfo(path, str(man.get("name") or "Imported library"), str(man.get("description", "")),
                           str(man.get("author", "")), str(man.get("created", "")))
        for folder in folders:
            if _package_rel_ok(folder):
                info.folders.append(folder)
            else:
                info.problems.append(f"unsafe or malformed folder skipped: {folder!r}")
        seen_files = set()
        for index, item in enumerate(listed):
            if not isinstance(item, dict):
                info.problems.append(f"symbol entry {index}: expected an object")
                continue
            f = item.get("file", "")
            folder = item.get("folder", "") or ""
            if (not _package_rel_ok(f) or not f.lower().endswith(SYMBOL_EXT) or
                    not isinstance(folder, str) or (folder and not _package_rel_ok(folder))):
                info.problems.append(f"unsafe or malformed symbol path skipped: {f!r}")
                continue
            if f in seen_files:
                info.problems.append(f"duplicate symbol member skipped: {f!r}")
                continue
            seen_files.add(f)
            try:
                doc = load_symbol_json(_zip_member(z, f, MAX_SYMBOL_BYTES), source=f)
            except (SymbolFormatError, ValueError) as e:
                info.problems.append(f"{item.get('name', f)}: {e}")
                continue
            it = PackageItem(doc["id"], doc["name"], folder, doc, doc.get("revision", 0))
            if lib is not None and doc["id"] in lib.entries:
                mine = lib.entries[doc["id"]].doc.get("revision", 0)
                it.conflict = "same id" + (" (newer in package)" if it.revision > mine else
                                           " (older in package)" if it.revision < mine else "")
            if symbols.is_builtin(doc["id"]):
                info.problems.append(f"{doc['name']}: uses a built-in id (skipped)")
                continue
            info.items.append(it)
    return info


def import_package(info: PackageInfo, lib: UserLibrary, mode: str = "separate", target: str = "",
                   on_conflict: str = "duplicate", selected_ids=None) -> dict:
    """Import all selected symbols as one filesystem transaction.

    Work is performed in a private sibling staging tree. An exception before
    commit leaves the original library untouched; a commit error restores the
    original tree. No project, symbol or package files are modified in place.
    """
    if mode not in ("separate", "merge"):
        raise ValueError(f"invalid import mode {mode!r}")
    if on_conflict not in ("skip", "replace", "duplicate"):
        raise ValueError(f"invalid symbol conflict action {on_conflict!r}")
    if not isinstance(target, str) or (target and not _rel_ok(target)):
        raise ValueError(f"invalid destination folder {target!r}")
    for folder in info.folders:
        if not _package_rel_ok(folder):
            raise ValueError(f"invalid package folder {folder!r}")
    for item in info.items:
        if not isinstance(item.folder, str) or (item.folder and not _package_rel_ok(item.folder)):
            raise ValueError(f"invalid symbol folder {item.folder!r}")
        if selected_ids is None or item.id in selected_ids:
            to_symdef(item.doc)  # preflight complete symbol geometry before writing

    original_root = os.path.abspath(lib.root)
    parent = os.path.dirname(original_root)
    # Do not stage an existing library if any component is a symbolic link.
    # The import must neither copy files from outside the library nor follow
    # symlink destinations while creating staged output.
    _assert_no_library_symlinks(original_root)
    os.makedirs(parent, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix=".osymlib-import-", dir=parent)
    staged_root = os.path.join(workdir, "staged")
    backup_root = os.path.join(workdir, "previous")
    failed_root = os.path.join(workdir, "failed")
    original_exists = os.path.isdir(original_root)
    user_registry = symbols.user_symbols()
    moved_old = moved_new = committed = False
    try:
        with open(os.path.join(workdir, "target.txt"), "w", encoding="utf-8") as f:
            f.write(original_root)
            f.flush()
            os.fsync(f.fileno())
        if original_exists:
            _assert_no_library_symlinks(original_root)
            shutil.copytree(original_root, staged_root, symlinks=True)
        else:
            os.makedirs(staged_root)
        staged = UserLibrary(staged_root)
        staged.scan()
        if mode == "separate":
            base = safe_name(info.name, "Imported library")
            name, n = base, 2
            while os.path.exists(staged.abs(name)):
                name = f"{base} ({n})"
                n += 1
            os.makedirs(staged.abs(name))
            root = name
        else:
            root = target
            os.makedirs(staged.abs(root), exist_ok=True)
        for folder in info.folders:
            os.makedirs(staged.abs(f"{root}/{folder}" if root else folder), exist_ok=True)
        counts = {"imported": 0, "skipped": 0, "replaced": 0, "duplicated": 0}
        for item in info.items:
            if selected_ids is not None and item.id not in selected_ids:
                continue
            folder = "/".join(x for x in (root, item.folder) if x)
            exists = item.id in staged.entries
            res = staged.import_symbol_doc(item.doc, folder, on_conflict if exists else "replace")
            if res is None:
                counts["skipped"] += 1
            elif exists and on_conflict == "replace":
                counts["replaced"] += 1
            elif exists:
                counts["duplicated"] += 1
            else:
                counts["imported"] += 1

        if original_exists:
            os.replace(original_root, backup_root)
            moved_old = True
        os.replace(staged_root, original_root)
        moved_new = True
        lib.scan()
        committed = True
        return counts
    except BaseException:
        # Neither staged writes nor a partially completed swap may alter
        # the existing user's library. Keep all backup bytes until restored.
        if moved_new:
            try:
                os.replace(original_root, failed_root)
            except OSError:
                # Keep the previous library in the backup rather than
                # overwriting an occupied destination or deleting its data.
                # A later recovery can use the matching target marker.
                pass
        if moved_old and not os.path.exists(original_root):
            os.replace(backup_root, original_root)
        if moved_new or moved_old:
            if os.path.isdir(original_root):
                lib.scan()
        else:
            symbols.set_user_symbols(user_registry.values())
        raise
    finally:
        # If rollback itself fails, retain the complete previous library for
        # manual recovery rather than deleting it during temporary cleanup.
        if committed or not os.path.exists(backup_root):
            shutil.rmtree(workdir, ignore_errors=True)




# ================================================================ favourites / recent (in settings)
MAX_RECENT_SYMBOLS = 16


def add_recent_symbol(settings, sid: str):
    rec = [s for s in settings["recent_symbols"] if s != sid]
    settings["recent_symbols"] = [sid] + rec[: MAX_RECENT_SYMBOLS - 1]


def toggle_favorite(settings, sid: str) -> bool:
    fav = list(settings["favorite_symbols"])
    if sid in fav:
        fav.remove(sid)
        settings["favorite_symbols"] = fav
        return False
    settings["favorite_symbols"] = fav + [sid]
    return True


__all__ = ["UserLibrary", "read_package", "import_package", "SYMBOL_FORMAT", "PACKAGE_EXT", "SYMBOL_EXT"]
