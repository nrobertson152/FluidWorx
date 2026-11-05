"""Symbol library registry.

Three layers are searched in order:
  1. project symbols - custom symbols embedded in the open project (the
     exact versions its drawings were made with);
  2. user library    - custom symbols in the user's own libraries;
  3. built-in        - the read-only symbols shipped with the program.
Built-in ids can never be overridden by custom symbols.
"""
from __future__ import annotations

import contextlib
import functools
import json
import weakref
from functools import lru_cache

from .base import Geometry, SymbolDef, Terminal, validate_geometry, LINE_WIDTHS, PORT_TYPES, port_domain  # noqa: F401
from . import drafting, electrical, electrical_control, electrical_devices, electrical_logic, electrical_passive, electrical_semis, fluid, fluid_conditioning, fluid_cylinders, fluid_flow, fluid_instruments, fluid_lines, fluid_nonreturn, fluid_pressure, fluid_rotary, fluid_storage, general

CATEGORY_ORDER = ["Electrical", "Electronic", "Hydraulic", "Pneumatic", "General"]

_REGISTRY: dict[str, SymbolDef] = {}     # built-in
_USER: dict[str, SymbolDef] = {}         # user libraries
_PROJECT: dict[str, SymbolDef] = {}      # embedded in the open project
_OWNER = None                            # weakref to the project whose symbols _PROJECT holds, if known


def _register_all():
    for mod in (electrical, electrical_passive, electrical_semis, electrical_devices, electrical_logic, electrical_control, fluid, general, fluid_lines, fluid_storage, fluid_conditioning, fluid_rotary, fluid_cylinders, fluid_pressure, fluid_nonreturn, fluid_flow, fluid_instruments, drafting):
        for sym in mod.symbols():
            if sym.id in _REGISTRY:
                raise ValueError(f"duplicate symbol id {sym.id}")
            _REGISTRY[sym.id] = sym


_register_all()


def is_builtin(symbol_id: str) -> bool:
    return symbol_id in _REGISTRY


def get(symbol_id: str) -> SymbolDef | None:
    return _REGISTRY.get(symbol_id) or _PROJECT.get(symbol_id) or _USER.get(symbol_id)


def lookup(symbol_id: str, project_defs: dict | None = None) -> SymbolDef | None:
    """Definition of a symbol for a project that may not be the active one.

    Searches the built-in symbols, then `project_defs` (that project's own embedded definitions, id ->
    SymbolDef), then the user libraries. Unlike get(), it never consults the active project's symbols,
    so reading one project cannot pick up another project's version of a custom symbol."""
    sd = _REGISTRY.get(symbol_id)
    if sd is None and project_defs:
        sd = project_defs.get(symbol_id)
    return sd or _USER.get(symbol_id)


def alias_pairs(defs=None) -> list[tuple[str, tuple, str]]:
    """(symbol id, aliases, name) of every known symbol (or of `defs`), for symbols.custom.alias_problems."""
    return [(s.id, s.aliases, s.name) for s in (all_symbols() if defs is None else defs)]


def resolve(identifier: str) -> SymbolDef | None:
    """Symbol for a canonical id (exact, else case-insensitive) or an alias (case-insensitive). Never
    ambiguous: if more than one symbol matches case-insensitively - possible only with symbol files edited
    outside OpenSchematix, since aliases are checked against every id and alias when saved - it resolves to
    nothing."""
    if not identifier:
        return None
    sd = get(identifier)
    if sd is not None:
        return sd
    low = identifier.strip().lower()
    hits = {}
    for s in all_symbols():
        if s.id.lower() == low or any(a.lower() == low for a in s.aliases):
            hits[s.id] = s
    return next(iter(hits.values())) if len(hits) == 1 else None


def builtin_symbols() -> list[SymbolDef]:
    return list(_REGISTRY.values())


def all_symbols(include_custom: bool = True) -> list[SymbolDef]:
    out = list(_REGISTRY.values())
    if include_custom:
        ids = set(_REGISTRY)
        for d in (_PROJECT, _USER):
            for k, v in d.items():
                if k not in ids:
                    out.append(v)
                    ids.add(k)
    return out


def _clean(defs) -> dict:
    return {s.id: s for s in defs if s.id not in _REGISTRY}


def set_user_symbols(defs):
    _USER.clear()
    _USER.update(_clean(defs))
    _geometry_cached.cache_clear()


def set_project_symbols(defs, owner=None):
    """Register a project's embedded symbols. `owner` is that project
    (Project.activate_symbols passes it); see project_owner()."""
    global _OWNER
    _PROJECT.clear()
    _PROJECT.update(_clean(defs))
    _OWNER = weakref.ref(owner) if owner is not None else None
    _geometry_cached.cache_clear()


def project_owner():
    """The project whose embedded symbols are registered, or None if they
    were registered without one (or that project no longer exists).

    The registry is process-wide: symbols.get() and every geometry lookup
    see the embedded symbols of whichever project was activated last. Code
    that works on a project uses project_scope() so that it resolves that
    project's own definitions, and Project.embed_symbols() only trusts the
    registry for its owner."""
    return _OWNER() if _OWNER is not None else None


@contextlib.contextmanager
def project_scope(project):
    """Resolve symbols as `project` inside the block: its embedded symbols
    are registered for the duration, and the previous registration (and
    owner) is restored afterwards, even on error. A no-op if `project` is
    None or already registered (the normal case: the open project)."""
    global _OWNER
    if project is None or project_owner() is project:
        yield
        return
    saved, saved_owner = dict(_PROJECT), _OWNER
    project.activate_symbols()
    try:
        yield
    finally:
        _PROJECT.clear()
        _PROJECT.update(saved)
        _OWNER = saved_owner
        _geometry_cached.cache_clear()


def _scope_target(args, kwargs):
    """The project an engine call works on: a `project` argument, else the
    first argument that is a project, else the first sheet's project."""
    cands = [kwargs.get("project")] + list(args) + list(kwargs.values())
    for a in cands:
        if a is not None and hasattr(a, "activate_symbols") and hasattr(a, "sheets"):
            return a
    for a in cands:
        if a is not None and hasattr(a, "components") and hasattr(a, "project"):
            return a.project
    return None


def project_scoped(fn):
    """Decorator for engine functions that take a project (or a sheet that
    belongs to one): they resolve symbols as that project (project_scope)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with project_scope(_scope_target(args, kwargs)):
            return fn(*args, **kwargs)
    return wrapper


def add_project_symbol(sd: SymbolDef):
    if sd.id not in _REGISTRY:
        _PROJECT[sd.id] = sd
        _geometry_cached.cache_clear()


def project_symbols() -> dict:
    return dict(_PROJECT)


def user_symbols() -> dict:
    return dict(_USER)


def categories() -> list[str]:
    present = {s.category for s in all_symbols()}
    return [c for c in CATEGORY_ORDER if c in present] + sorted(present - set(CATEGORY_ORDER))


def search(query: str, category: str | None = None, include_custom: bool = True) -> list[SymbolDef]:
    words = query.lower().split()
    out = []
    for s in all_symbols(include_custom):
        if category and s.category != category:
            continue
        text = s.search_text()
        if all(w in text for w in words):
            out.append(s)
    return out


@lru_cache(maxsize=1024)
def _geometry_cached(symbol_id: str, params_json: str) -> Geometry:
    sym = get(symbol_id) or get(general.UNKNOWN_ID)
    return sym.build(json.loads(params_json) if params_json else None)


def geometry(symbol_id: str, params: dict | None = None) -> Geometry:
    """Return (cached) geometry for a symbol and its parameters. Unknown ids
    resolve to the 'missing symbol' placeholder."""
    if params and "program" in params:
        # a PLC's program can be long and doesn't change how the block looks; this is called constantly
        params = {k: v for k, v in params.items() if k != "program"}
    key = json.dumps(params, sort_keys=True) if params else ""
    return _geometry_cached(symbol_id, key)
