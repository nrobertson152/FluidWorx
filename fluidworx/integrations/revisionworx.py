"""RevisionWorx: which controlled revision is being simulated, and keeping studies under revision control.

Everything goes through RevisionWorx's public command line (`--json`), so its workspace rules, locks and audit
trail apply exactly as they would by hand. FluidWorx never touches a `.revisionworx` folder itself.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

from . import tools

TIMEOUT = 30
# a windowed Windows build must not flash a console for each command
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform.startswith("win") else {}


class RevisionWorxError(RuntimeError):
    """A RevisionWorx command failed. The message is RevisionWorx's own."""


def find_workspace(path: str) -> str | None:
    """The folder holding `.revisionworx`, searching upward from a file."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.isdir(os.path.join(d, ".revisionworx")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


@dataclass
class DocStatus:
    workspace: str
    doc_id: str = ""
    project_id: str = ""
    number: str = ""
    title: str = ""
    latest_label: str = ""
    latest_state: str = ""
    released_label: str = ""
    file_state: str = ""        # unchanged | modified | modified-externally | missing | unrevisioned
    checked_out_by: str = ""
    matched_label: str = ""     # the revision whose content is exactly the bytes being simulated
    managed: bool = False       # registered as a document

    def summary(self) -> str:
        if not self.managed:
            return "In a RevisionWorx workspace; not registered"
        if self.matched_label:
            return f"{self.number or self.title} Rev {self.matched_label}"
        return f"{self.number or self.title}: differs from Rev {self.latest_label or '?'}"


class Client:
    def __init__(self, workspace: str, settings=None):
        self.workspace = workspace
        self.settings = settings
        self.cmd = tools.find("revisionworx", settings)

    @property
    def available(self) -> bool:
        return self.cmd is not None

    def _run(self, *args):
        if self.cmd is None:
            raise RevisionWorxError("RevisionWorx is not installed, or FluidWorx can't find it. "
                                    "Set its location in Preferences.")
        try:
            r = subprocess.run([*self.cmd, "--json", "-w", self.workspace, *args], capture_output=True, text=True,
                               timeout=TIMEOUT, check=False, encoding="utf-8", errors="replace",
                               env=tools.child_environment(), stdin=subprocess.DEVNULL, **_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RevisionWorxError(f"RevisionWorx could not be run: {e}") from e
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip()
            msg = msg[len("error: "):] if msg.startswith("error: ") else msg
            raise RevisionWorxError(msg or f"RevisionWorx exited with code {r.returncode}.")
        try:
            return json.loads(r.stdout) if r.stdout.strip() else None
        except ValueError as e:
            raise RevisionWorxError("RevisionWorx returned something FluidWorx could not read.") from e

    def _find_doc(self, path: str):
        """(list row, show result) of the document at this path, or None."""
        target = os.path.normcase(os.path.realpath(path))
        name = os.path.basename(path)
        for row in self._run("doc", "list", name) or []:
            if os.path.basename(str(row.get("rel_path", ""))) != name:
                continue
            shown = self._run("doc", "show", row["id"], "--hash")
            found = str((shown.get("status") or {}).get("path", ""))
            if os.path.normcase(os.path.realpath(found)) == target:
                return row, shown
        return None

    def status(self, path: str, sha256: str = "") -> DocStatus:
        st = DocStatus(self.workspace)
        hit = self._find_doc(path)
        if hit is None:
            return st
        row, shown = hit
        status = shown.get("status") or {}
        history = shown.get("history") or []
        st.managed = True
        st.doc_id, st.project_id = row["id"], row.get("project_id", "")
        st.number, st.title = row.get("number", ""), row.get("title", "")
        st.latest_label = row.get("latest_label") or ""
        st.latest_state = row.get("latest_state") or ""
        st.released_label = row.get("released_label") or ""
        st.checked_out_by = row.get("checked_out_by") or ""
        st.file_state = status.get("state", "")
        if sha256:
            for rev in reversed(history):
                if rev.get("sha256") == sha256:
                    st.matched_label = rev.get("label", "")
                    break
        return st

    def register(self, project_id: str, path: str, title: str, message: str):
        return self._run("doc", "register", project_id, os.path.abspath(path), "--title", title, "-m", message)

    def checkout(self, doc_id: str):
        return self._run("doc", "checkout", doc_id)

    def checkin(self, doc_id: str, message: str):
        return self._run("doc", "checkin", doc_id, "-m", message)

    def cancel(self, doc_id: str):
        return self._run("doc", "cancel", doc_id)
