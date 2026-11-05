# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec. Run from the repository root: pyinstaller packaging/fluidworx.spec --noconfirm
import os
import sys

root = os.path.abspath(".")
a = Analysis([os.path.join(root, "packaging", "launcher.py")], pathex=[root],
             datas=[(os.path.join(root, "fluidworx", "resources"), "fluidworx/resources"),
                    (os.path.join(root, "fluidworx", "examples"), "fluidworx/examples")],
             hiddenimports=["fluidworx.gui.app"], excludes=["pytest", "PIL", "numpy"])
pyz = PYZ(a.pure)
icon = os.path.join(root, "fluidworx", "resources", "fluidworx.ico") if sys.platform.startswith("win") else None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FluidWorx", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="FluidWorx")
