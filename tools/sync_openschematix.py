#!/usr/bin/env python3
"""Refresh fluidworx/vendor/openschematix from an OpenSchematix checkout.

FluidWorx reads circuits and draws symbols with OpenSchematix's own code, so a circuit looks and connects
exactly as it does in the editor. Only the modules needed for that are copied, unchanged.

    python tools/sync_openschematix.py ../OpenSchematix
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

MODULES = ["__init__.py", "bom.py", "check.py", "commands.py", "connectivity.py", "editing.py", "fileio.py",
           "geometry.py", "model.py", "netlist.py", "project.py", "projectio.py", "regions.py", "render.py",
           "revisions.py", "safejson.py", "settings.py", "shapes.py", "simlinks.py", "templates.py", "titleblock.py",
           "userlib.py", "gui/__init__.py", "gui/canvas_view.py", "gui/icons.py", "gui/interact.py",
           "gui/theme.py", "gui/widgets.py"]


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    src_repo = Path(argv[1]).resolve()
    src = src_repo / "openschematix"
    dst = Path(__file__).resolve().parent.parent / "fluidworx" / "vendor" / "openschematix"
    if dst.exists():
        shutil.rmtree(dst)
    for rel in MODULES:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dst / rel)
    for package in ("symbols", "plc"):
        for f in (src / package).glob("*.py"):
            (dst / package).mkdir(exist_ok=True)
            shutil.copy2(f, dst / package / f.name)
    sha = subprocess.run(["git", "-C", str(src_repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=False).stdout.strip()
    ns: dict = {}
    exec((src / "__init__.py").read_text(encoding="utf-8").split("FILE_FORMAT")[0], ns)
    (dst / "UPSTREAM.json").write_text(json.dumps(
        {"project": "OpenSchematix", "url": "https://github.com/nrobertson152/OpenSchematix",
         "version": ns.get("__version__", ""), "commit": sha, "license": "GPL-3.0-or-later",
         "note": "Copied unchanged by tools/sync_openschematix.py. Do not edit; change OpenSchematix and re-sync."},
        indent=2) + "\n", encoding="utf-8")
    print(f"synced {len(MODULES)} modules + symbols from {sha[:10]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
