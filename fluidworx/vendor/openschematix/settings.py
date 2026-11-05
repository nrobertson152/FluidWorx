"""User settings stored as JSON in the platform's configuration directory:
  Windows: %APPDATA%\\OpenSchematix\\settings.json
  macOS:   ~/Library/Application Support/OpenSchematix/settings.json
  Linux:   $XDG_CONFIG_HOME/openschematix/settings.json (default ~/.config)
"""
from __future__ import annotations

import json
import os
import sys
import shutil
import tempfile

DEFAULTS = {
    "theme": "modern_light",        # UI theme (see gui/theme.py)
    "canvas_theme": "auto",         # drawing canvas colours: auto = follow the UI theme
    "show_grid": True,
    "show_markers": True,
    "snap_grid": True,
    "osnap": True,                  # object snap for drafting tools
    "fill_gap_mm": 0.0,             # FILL/HATCH gap tolerance (0 = boundaries must be closed)
    "ortho": False,
    "grid_step": 10,                # snap/grid step in drawing units (0.25 mm)
    "recent_files": [],
    "last_dir": "",
    "geometry": "",
    "default_sheet": "ANSI A",       # new drawings: 8.5 x 11 in (a saved choice is kept)
    "autosave_minutes": 5,          # 0 = off
    "recent_symbols": [],
    "favorite_symbols": [],
    "shortcuts": {},                # command -> key sequence overrides
    "aliases": {},                  # extra command aliases
    "layout": {},                   # panel sizes / visibility
    "ui_scale": 0.0,                # 0 = automatic
    "show_command_line": True,
    "selection_filter": ["component", "wire", "shape"],
    "command_history": [],
    "recent_templates": [],
}
THEME_MIGRATION = {"light": "modern_light", "dark": "modern_dark"}
MAX_RECENT = 8


def config_dir() -> str:
    override = os.environ.get("OPENSCHEMATIX_CONFIG_DIR")
    if override:
        return override
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(base, "OpenSchematix")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/OpenSchematix")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "openschematix")


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.data = dict(DEFAULTS)
        self.last_load_error = None
        self.last_save_error = None
        self._corrupt_file = False
        self._warning_handler = None
        self._warned = set()
        self.load()

    def set_warning_handler(self, handler):
        """Register a GUI callback after the window is initialized."""
        self._warning_handler = handler
        if self.last_load_error:
            self._warn_once("load", self.last_load_error)
        if self.last_save_error:
            self._warn_once("save", self.last_save_error)

    def _warn_once(self, kind, message):
        if self._warning_handler is not None and kind not in self._warned:
            self._warned.add(kind)
            self._warning_handler(kind, message)

    def load(self):
        self.last_load_error = None
        self._corrupt_file = False
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("Settings must be a JSON object")
            invalid = []
            for k, v in loaded.items():
                if k not in DEFAULTS:
                    continue
                expected = DEFAULTS[k]
                valid = (type(v) is type(expected) or
                         (type(expected) is float and type(v) is int))
                if valid:
                    self.data[k] = v
                else:
                    invalid.append(k)
            self.data["theme"] = THEME_MIGRATION.get(self.data["theme"], self.data["theme"])
            if invalid:
                self.last_load_error = ("Invalid preferences were ignored: " +
                                        ", ".join(sorted(invalid)))
        except FileNotFoundError:
            pass  # normal first run
        except (OSError, ValueError, UnicodeError) as e:
            self._corrupt_file = os.path.isfile(self.path)
            self.last_load_error = f"Could not load preferences from {self.path}: {e}"
        if self.last_load_error:
            self._warn_once("load", self.last_load_error)

    def save(self):
        tmp = None
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
            # Never destroy the only copy of a malformed configuration.
            if self._corrupt_file and os.path.exists(self.path):
                fd, backup = tempfile.mkstemp(prefix="settings-corrupt-", suffix=".bak", dir=directory)
                os.close(fd)
                try:
                    shutil.copy2(self.path, backup)
                except OSError:
                    os.unlink(backup)
                    raise
                self._corrupt_file = False
            fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            self.last_save_error = None
            return True
        except (OSError, TypeError, ValueError) as e:
            self.last_save_error = f"Could not save preferences to {self.path}: {e}"
            self._warn_once("save", self.last_save_error)
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def __getitem__(self, k):
        import copy
        v = self.data.get(k, DEFAULTS.get(k))
        return copy.copy(v) if isinstance(v, (list, dict)) else v

    def __setitem__(self, k, v):
        self.data[k] = v

    def remove_recent(self, path: str) -> bool:
        """Drop `path` from the recent files; True if it was there."""
        path = os.path.abspath(path)
        rec = self.data.get("recent_files", [])
        if path not in rec:
            return False
        self.data["recent_files"] = [p for p in rec if p != path]
        return True

    def add_recent(self, path: str):
        path = os.path.abspath(path)
        rec = [p for p in self.data.get("recent_files", []) if p != path]
        self.data["recent_files"] = [path] + rec[: MAX_RECENT - 1]
