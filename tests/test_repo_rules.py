"""The family's product rules, enforced."""
import ast
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "fluidworx"
CORE = ["__init__", "units", "catalog", "circuit", "engine", "electric", "links", "linsolve", "flowpaths", "study", "report",
        "settings", "cli"]
FORBIDDEN_NETWORK = {"socket", "http", "urllib", "requests", "ftplib", "smtplib", "ssl"}


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(n.module.split(".")[0])
    return out


def test_core_never_imports_tkinter_at_module_level():
    for name in CORE:
        tree = ast.parse((PKG / f"{name}.py").read_text(encoding="utf-8"))
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                assert not any(x.startswith("tkinter") for x in names), name


def test_no_network_anywhere_in_our_code():
    for f in PKG.rglob("*.py"):
        if "vendor" in f.parts:
            continue
        assert not imports(f) & FORBIDDEN_NETWORK, f


def test_only_standard_library_at_runtime():
    import sys
    for f in PKG.rglob("*.py"):
        if "vendor" in f.parts:
            continue
        for m in imports(f):
            assert m == "fluidworx" or m in sys.stdlib_module_names, f"{f}: {m}"


def test_vendor_records_where_it_came_from():
    up = json.loads((PKG / "vendor" / "openschematix" / "UPSTREAM.json").read_text())
    assert up["project"] == "OpenSchematix" and len(up["commit"]) == 40 and up["license"].startswith("GPL")


def test_examples_and_resources_are_packaged():
    assert len(list((PKG / "examples").glob("*.schematix"))) >= 5
    assert (PKG / "resources" / "fluidworx-64.png").exists() and (PKG / "resources" / "fluidworx.ico").exists()
    assert os.path.exists(ROOT / "LICENSE")
