"""User settings, stored the way OpenSchematix stores its own (%APPDATA%\\FluidWorx or ~/.config/fluidworx)."""
from __future__ import annotations

import json
import os
import sys
import tempfile

DEFAULTS = {
    "theme": "",                # empty on first run: follow OpenSchematix's saved theme, if there is one
    "canvas_theme": "auto",
    "units": "metric",
    "recent_files": [],
    "last_dir": "",
    "geometry": "",
    "layout": {},
    "ui_scale": 0.0,
    "show_flow": True,
    "show_values": True,
    "openschematix_path": "",
    "revisionworx_path": "",
    "caldera_path": "",
}
MAX_RECENT = 8


def config_dir() -> str:
    override = os.environ.get("FLUIDWORX_CONFIG_DIR")
    if override:
        return override
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(base, "FluidWorx")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "fluidworx")


def _openschematix_theme() -> tuple[str, str]:
    """Theme the user chose in OpenSchematix, so the two programs match from the first run."""
    from .vendor.openschematix.settings import config_dir as os_dir
    try:
        with open(os.path.join(os_dir(), "settings.json"), encoding="utf-8") as f:
            d = json.load(f)
        return str(d.get("theme") or ""), str(d.get("canvas_theme") or "auto")
    except (OSError, ValueError, AttributeError):
        return "", "auto"


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.data = dict(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if k in DEFAULTS and isinstance(v, type(DEFAULTS[k])):
                        self.data[k] = v
        except (OSError, ValueError):
            pass
        if not self.data["theme"]:
            theme, canvas = _openschematix_theme()
            self.data["theme"] = theme or "modern_light"
            self.data["canvas_theme"] = canvas

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        rec = [p for p in self.data["recent_files"] if p != path]
        self.data["recent_files"] = [path] + rec[:MAX_RECENT - 1]

    def save(self) -> None:
        try:
            d = os.path.dirname(self.path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass        # settings are a convenience; failing to save them must never lose work
