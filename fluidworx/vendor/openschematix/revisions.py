"""Built-in revision history.

Snapshots are stored inside the project file in a content-addressed object
store: the project header and every sheet are serialised separately, hashed
(SHA-256) and stored once. A snapshot is a list of object hashes, so a sheet
that did not change between revisions is stored only once.

Two kinds of entries:
  * ``auto``     - created automatically when the project is saved and its
                   content differs from the latest snapshot. Only the newest
                   AUTO_KEEP automatic snapshots are kept.
  * ``approved`` - formal revisions issued by the user ("Issue revision"),
                   with a revision identifier (A, B, C … or 0, 1, 2 …),
                   description, author and approver. They are never pruned
                   automatically and appear in title-block revision tables.
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import re
import zlib

AUTO_KEEP = 25
KINDS = ("auto", "approved")
MAX_OBJECT_BYTES = 64 * 1024 * 1024     # one decompressed snapshot object (a sheet or the project header)
_HASH = re.compile(r"[0-9a-f]{64}")
_ENTRY_TEXT = ("label", "description", "author", "approved_by", "timestamp", "content")


class RevisionDataError(ValueError):
    """A revision index entry or snapshot object read from a file is damaged."""


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def next_label(prev: str | None, style: str = "letter") -> str:
    """Next formal revision identifier: A, B, … Z, AA, AB … or 0, 1, 2 …"""
    if style == "number":
        try:
            return str(int(prev) + 1) if prev not in (None, "") else "0"
        except ValueError:
            return "0"
    if not prev or not prev.isalpha():
        return "A"
    s = list(prev.upper())
    i = len(s) - 1
    while i >= 0:
        if s[i] != "Z":
            s[i] = chr(ord(s[i]) + 1)
            return "".join(s)
        s[i] = "A"
        i -= 1
    return "A" + "".join(s)


class RevisionStore:
    def __init__(self):
        self.entries: list[dict] = []
        self.objects: dict[str, bytes] = {}   # sha -> zlib-compressed canonical JSON
        self._schema_cache: dict[str, int] = {}   # sha -> sheet schema needed (objects never change)
        # (sha, kind) -> the exact stored bytes that were fully verified in this
        # session (see _verify_object). Lets the pre-save check skip re-parsing
        # unchanged history, whose cost would otherwise grow with every
        # revision kept. In memory only; never written to a file.
        self._verified: dict[tuple[str, str], bytes] = {}

    # ---------------------------------------------------------------- objects
    def _put(self, obj) -> str:
        raw = _canon(obj)
        h = _sha(raw)
        if h not in self.objects:
            self.objects[h] = zlib.compress(raw, 6)
        return h

    def mark_verified(self, verified: dict[tuple[str, str], bytes]) -> None:
        """Record objects of this store that another store has verified
        byte for byte (see _verify_object). Keeps a reference to this store's
        own bytes, never a second copy."""
        for (h, kind), blob in verified.items():
            own = self.objects.get(h)
            if own is not None and own == blob:
                self._verified[(h, kind)] = own

    def _get(self, h: str):
        return json.loads(zlib.decompress(self.objects[h]).decode("utf-8"))

    # ---------------------------------------------------------------- snapshots
    @staticmethod
    def _split(project) -> tuple[dict, list]:
        d = project.to_dict()
        sheets = d.pop("sheets")
        return d, sheets

    def content_key(self, project) -> str:
        head, sheets = self._split(project)
        return _sha(_canon([head, sheets]))

    def latest(self, kind: str | None = None):
        for e in reversed(self.entries):
            if kind is None or e["kind"] == kind:
                return e
        return None

    def create(self, project, kind: str = "auto", label: str = "", description: str = "", author: str = "",
               approved_by: str = "", force: bool = False):
        """Create a snapshot. For automatic snapshots nothing is stored if the
        content equals the most recent snapshot. Returns the entry or None."""
        if kind not in KINDS:
            raise ValueError(kind)
        head, sheets = self._split(project)
        key = _sha(_canon([head, sheets]))
        last = self.latest()
        if kind == "auto" and not force and last is not None and last.get("content") == key:
            return None
        entry = {
            "n": (max((e["n"] for e in self.entries), default=0) + 1),
            "kind": kind,
            "label": label or "",
            "description": description,
            "author": author,
            "approved_by": approved_by,
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "content": key,
            "head": self._put(head),
            "sheets": [[s["uid"], s.get("name", ""), self._put(s)] for s in sheets],
        }
        self.entries.append(entry)
        self.prune()
        return entry

    def get(self, n: int) -> dict:
        for e in self.entries:
            if e["n"] == n:
                return e
        raise KeyError(n)

    def load(self, n: int):
        """Reconstruct the Project stored in snapshot n."""
        from .project import Project
        e = self.get(n)
        head = self._get(e["head"])
        head["sheets"] = [self._get(h) for _uid, _name, h in e["sheets"]]
        p = Project.from_dict(head)
        p.revisions = self
        return p

    def delete(self, n: int):
        e = self.get(n)
        if e["kind"] == "approved":
            raise ValueError("approved revisions cannot be deleted")
        self.entries.remove(e)
        self.gc()

    def prune(self):
        autos = [e for e in self.entries if e["kind"] == "auto"]
        if len(autos) > AUTO_KEEP:
            drop = {id(e) for e in autos[:len(autos) - AUTO_KEEP]}
            self.entries = [e for e in self.entries if id(e) not in drop]
            self.gc()

    def gc(self):
        live = set()
        for e in self.entries:
            live.add(e["head"])
            live.update(h for _u, _n, h in e["sheets"])
        for h in list(self.objects):
            if h not in live:
                del self.objects[h]
        for key in [k for k in self._verified if k[0] not in self.objects]:
            del self._verified[key]

    def approved(self) -> list[dict]:
        return [e for e in self.entries if e["kind"] == "approved"]

    def required_schema(self) -> int:
        """Lowest sheet schema able to represent every stored snapshot.

        The revision history is part of the project file, so a project whose
        current sheets have no boundary fills but whose history does must
        still be written as schema 3: an older reader would otherwise open it
        and fail (or misbehave) only when that revision is restored."""
        from .model import sheet_dict_schema
        need = 2
        for e in self.entries:
            for _uid, _name, h in e.get("sheets", []):
                v = self._schema_cache.get(h)
                if v is None:
                    try:
                        v = sheet_dict_schema(self._get(h))
                    except (KeyError, ValueError, zlib.error):
                        v = 2               # unreadable objects are dropped on load anyway
                    self._schema_cache[h] = v
                need = max(need, v)
        return need

    def stored_bytes(self) -> int:
        return sum(len(b) for b in self.objects.values())

    # ---------------------------------------------------------------- persistence
    def index(self) -> dict:
        return {"version": 1, "entries": copy.deepcopy(self.entries)}

    @classmethod
    def from_parts(cls, index, objects: dict[str, bytes]) -> "RevisionStore":
        """Store from a file's index and objects; damaged entries are left
        out. See from_file for the list of what was left out and why."""
        return cls.from_file(index, objects.get)[0]

    @classmethod
    def from_file(cls, index, read_object, trusted: "RevisionStore | None" = None
                  ) -> tuple["RevisionStore", list[str]]:
        """Rebuild the history read from a project file, keeping every entry
        that is intact and leaving out only damaged ones.

        `index` is the parsed revisions/index.json; `read_object(hash)`
        returns that object's stored bytes, or None if it is missing (it may
        raise RevisionDataError). Every object an entry uses is verified
        (size, zlib stream, SHA-256 against its name, strict JSON, and the
        structure of a sheet or project header), so restoring a kept
        revision cannot fail on damaged data later. Returns the store and one
        message per entry left out (empty if nothing was).

        `trusted` (optional) is an in-memory store whose verified objects are
        accepted without re-parsing when the stored bytes are identical to
        its copy; anything else is verified in full."""
        st, problems = cls(), []
        if not isinstance(index, dict) or not isinstance(index.get("entries"), list):
            return st, ["the revision index is not in the expected format; no revisions could be read"]
        verdict: dict[tuple[str, str], str | None] = {}  # (hash, semantic kind) -> problem
        seen = set()
        for i, raw in enumerate(index["entries"]):
            try:
                e = check_entry(raw)
                if e["n"] in seen:
                    raise RevisionDataError(f"duplicate revision number {e['n']}")
                for h, kind in [(e["head"], "head")] + [(sh[2], "sheet") for sh in e["sheets"]]:
                    key = (h, kind)
                    if key not in verdict:
                        verdict[key] = _verify_object(st, h, kind, read_object, trusted)
                    if verdict[key]:
                        raise RevisionDataError(verdict[key])
            except RevisionDataError as exc:
                problems.append(f"{_describe(raw, i)}: {exc}")
                continue
            seen.add(e["n"])
            st.entries.append(e)
        st.gc()
        return st, problems


def _describe(raw, i: int) -> str:
    """Identify a damaged entry without exposing user-supplied labels."""
    if isinstance(raw, dict):
        n = raw.get("n")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 1:
            return f"revision #{n}"
    return f"revision entry {i + 1}"


def check_entry(raw) -> dict:
    """Validated copy of one revisions/index.json entry, or RevisionDataError."""
    if not isinstance(raw, dict):
        raise RevisionDataError("the entry is not an object")
    n = raw.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise RevisionDataError("the revision number is missing or invalid")
    if raw.get("kind") not in KINDS:
        raise RevisionDataError("the revision kind is missing or invalid")
    e = copy.deepcopy(raw)          # unknown keys (newer versions) are kept and written back
    for k in _ENTRY_TEXT:
        v = raw.get(k, "")
        if not isinstance(v, str):
            raise RevisionDataError(f"'{k}' is not text")
        e[k] = v
    head = raw.get("head")
    if not isinstance(head, str) or not _HASH.fullmatch(head):
        raise RevisionDataError("the snapshot reference is invalid")
    e["head"] = head
    sheets = raw.get("sheets")
    if not isinstance(sheets, list):
        raise RevisionDataError("the sheet list is invalid")
    e["sheets"] = []
    for sh in sheets:
        if (not isinstance(sh, list) or len(sh) != 3 or not all(isinstance(x, str) for x in sh)
                or not _HASH.fullmatch(sh[2])):
            raise RevisionDataError("a sheet reference is invalid")
        e["sheets"].append(list(sh))
    return e


def _verify_object(st: "RevisionStore", h: str, kind: str, read_object,
                   trusted: "RevisionStore | None" = None) -> str | None:
    """Load object `h` into `st.objects` if it is intact; else the problem.

    An object whose stored bytes are identical to bytes that `trusted` has
    already verified as `kind` is accepted without parsing it again."""
    from . import safejson
    try:
        blob = read_object(h)
    except RevisionDataError as e:
        return str(e)
    if blob is None:
        return "a snapshot it uses is missing from the file"
    if trusted is not None and trusted._verified.get((h, kind)) == blob:
        st.objects[h] = blob
        st._verified[(h, kind)] = blob
        return None
    try:
        d = zlib.decompressobj()
        raw = d.decompress(blob, MAX_OBJECT_BYTES + 1)
        if len(raw) > MAX_OBJECT_BYTES:
            return "a snapshot it uses is unreasonably large"
        if not d.eof or d.unused_data:
            return "a snapshot it uses is truncated or damaged"
    except zlib.error:
        return "a snapshot it uses is damaged (not a valid compressed stream)"
    if _sha(raw) != h:
        return "a snapshot it uses is damaged (checksum mismatch)"
    try:
        obj = safejson.loads(raw)
        if kind == "sheet":
            from .model import Document
            # Model readers accept missing fields for legacy compatibility.
            # Revision objects need a stronger kind boundary: otherwise a
            # project header can be interpreted as an empty sheet on restore.
            if not isinstance(obj, dict) or "sheet" not in obj:
                raise ValueError("not a sheet snapshot")
            Document.from_dict(obj)
        else:
            from .project import Project
            # A stored header is the project dictionary with sheets removed.
            # Reject sheet-shaped objects before the permissive model reader.
            if (not isinstance(obj, dict)
                    or any(k in obj for k in ("sheets", "sheet", "components", "wires"))):
                raise ValueError("not a project header")
            Project.from_dict(obj)
    except ValueError as e:
        return f"a snapshot it uses is invalid ({e})"
    st.objects[h] = blob
    st._verified[(h, kind)] = blob
    return None


def restore(project, store: RevisionStore, n: int):
    """Return a new Project with the content of revision n. The current state
    is first saved as an automatic snapshot, so a restore can be undone."""
    store.create(project, "auto", description=f"Before restoring revision #{n}", force=False)
    p = store.load(n)
    p.uid = project.uid
    p.revisions = store
    return p
