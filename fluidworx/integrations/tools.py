"""Finding and starting the other programs of the family. Nothing here is required: FluidWorx works alone."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

TOOLS = {
    "openschematix": {"label": "OpenSchematix", "env": "FLUIDWORX_OPENSCHEMATIX", "setting": "openschematix_path",
                      "names": ["openschematix", "OpenSchematix"], "module": "openschematix"},
    "revisionworx": {"label": "RevisionWorx", "env": "FLUIDWORX_REVISIONWORX", "setting": "revisionworx_path",
                     "names": ["revisionworx"], "module": "revisionworx"},
    "revisionworx-gui": {"label": "RevisionWorx", "env": "FLUIDWORX_REVISIONWORX_GUI", "setting": "",
                         "names": ["revisionworx-gui"], "module": "revisionworx.gui.app"},
    "caldera": {"label": "Caldera", "env": "FLUIDWORX_CALDERA", "setting": "caldera_path",
                "names": ["caldera", "Caldera"], "module": "caldera"},
}


def _module_available(name: str) -> bool:
    if getattr(sys, "frozen", False):
        return False
    import importlib.util
    try:
        return importlib.util.find_spec(name.split(".")[0]) is not None
    except (ImportError, ValueError):
        return False


def find(tool: str, settings=None) -> list | None:
    """Command prefix that runs a tool: the path in Preferences, an environment variable, then PATH."""
    info = TOOLS[tool]
    candidates = []
    if settings is not None and info["setting"]:
        candidates.append(settings[info["setting"]])
    candidates.append(os.environ.get(info["env"], ""))
    for c in candidates:
        if c and (os.path.isfile(c) or shutil.which(c)):
            return [c]
    for n in info["names"]:
        w = shutil.which(n)
        if w:
            return [w]
    if _module_available(info["module"]):
        return [sys.executable, "-m", info["module"]]
    return None


def child_environment(environ=None, frozen=None) -> dict:
    """Environment for another program. A packaged FluidWorx points these at its own libraries, which would break
    a different program that inherited them."""
    env = dict(os.environ if environ is None else environ)
    if getattr(sys, "frozen", False) if frozen is None else frozen:
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        for key in ("TCL_LIBRARY", "TK_LIBRARY", "TKPATH"):
            env.pop(key, None)
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is not None:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def launch(tool: str, args=(), settings=None) -> bool:
    """Start a tool and leave it running. Returns False if it isn't installed."""
    cmd = find(tool, settings)
    if cmd is None:
        return False
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "env": child_environment()}
    if sys.platform.startswith("win"):
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([*cmd, *[str(a) for a in args]], **kw)  # noqa: S603 - the user's own configured program
    return True
