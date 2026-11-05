"""The real window, driven under a virtual display. Skipped where there is no Tk or no display."""
import glob
import os

import pytest
from conftest import EXAMPLES

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path):
    from fluidworx.gui.app import App
    from fluidworx.settings import Settings
    try:
        root = tk.Tk(className="FluidWorx")
    except tk.TclError:
        pytest.skip("no display")
    root.geometry("1400x850+0+0")
    a = App(root, None, Settings(str(tmp_path / "settings.json")))
    root.update()
    errors = []
    import traceback
    root.report_callback_exception = lambda exc, val, tb: (errors.append(val), traceback.print_exception(exc, val, tb))
    a._errors = errors
    yield a
    a.dirty = False
    try:
        root.destroy()
    except tk.TclError:
        pass
    assert not errors, errors


def pump(a, n=6):
    for _ in range(n):
        a.root.update()
        a.root.after(10)


def open_ex(a, name="lift_cylinder.schematix"):
    assert a.open_path(os.path.join(EXAMPLES, name), confirm=False)
    pump(a)


def test_welcome_then_open(app):
    assert app.welcome is not None
    open_ex(app)
    assert app.welcome is None and app.sim is not None
    assert "lift_cylinder" in app.root.title()


def test_every_example_opens_runs_and_draws(app):
    for f in glob.glob(os.path.join(EXAMPLES, "*.schematix")):
        app.open_path(f, confirm=False)
        pump(app, 3)
        app.sim.run(0.2)
        app.canvas.update_state(0.03)
        assert app.canvas.node_items
        assert app.canvas.valves


def test_clicking_a_valve_side_operates_it(app):
    open_ex(app)
    v = next(b for b in app.sim.parts.values() if b.part.kind == "dcv")
    c = v.part.comp
    x, y = app.canvas.to_screen(c.local_to_world(-30, 0))
    app.canvas._on_press(type("E", (), {"x": x, "y": y})())
    app.canvas._on_release(type("E", (), {"x": x, "y": y})())
    assert v.cmd["left"] and v.position == 0
    assert app.selected == v.part.key
    x, y = app.canvas.to_screen(c.local_to_world(30, 0))
    app.canvas._on_press(type("E", (), {"x": x, "y": y})())
    app.canvas._on_release(type("E", (), {"x": x, "y": y})())
    assert v.cmd["right"] and not v.cmd["left"] and v.position == 2


def test_drag_pans_and_does_not_operate(app):
    open_ex(app)
    v = next(b for b in app.sim.parts.values() if b.part.kind == "dcv")
    x, y = app.canvas.to_screen(v.part.comp.local_to_world(-30, 0))
    ox = app.canvas.ox
    app.canvas._on_press(type("E", (), {"x": x, "y": y})())
    app.canvas._on_drag(type("E", (), {"x": x + 50, "y": y})())
    app.canvas._on_release(type("E", (), {"x": x + 50, "y": y})())
    assert app.canvas.ox != ox and not v.cmd["left"]


def test_play_advances_time_and_reset_returns(app):
    open_ex(app)
    app.toggle_run()
    for _ in range(40):
        app.root.update()
        app.root.after(5)
    pump(app, 12)
    assert app.running
    assert app.sim.time > 0
    app.reset()
    assert app.sim.time == 0.0 and not app.running


def test_wire_colour_changes_with_pressure(app):
    open_ex(app)
    v = next(b for b in app.sim.parts.values() if b.part.kind == "dcv")
    app.sim.command(v.part.key, "left")
    app.sim.run(6.0)
    app.canvas.update_state(0.0)
    node = v.t["P"]
    cid = app.canvas.node_items[node][0]
    high = app.canvas.itemcget(cid, "fill")
    app.sim.reset()
    app.canvas.update_state(0.0)
    assert app.canvas.itemcget(cid, "fill") != high


def test_inspector_edit_goes_to_the_study_and_marks_dirty(app):
    open_ex(app)
    p = next(x for x in app.circuit.parts if x.tag == "V2")
    app.select(p.key)
    pump(app, 2)
    app.set_param(p.key, "setting", 100e5)
    assert app.dirty and "*" in app.root.title()
    assert app.study.params[f"{p.key[0]}/{p.key[1]}"]["setting"] == 100e5
    app.reset_part_params(p.key)
    assert p.params["setting"] == 160e5
    assert f"{p.key[0]}/{p.key[1]}" not in app.study.params


def _entries(w, out=None):
    from tkinter import ttk
    out = [] if out is None else out
    for c in w.winfo_children():
        if isinstance(c, ttk.Entry) and not isinstance(c, ttk.Combobox):
            out.append(c)
        _entries(c, out)
    return out


def test_inspector_refuses_bad_entry_and_leaving_a_field_changes_nothing(app):
    open_ex(app)
    p = next(x for x in app.circuit.parts if x.tag == "A1")
    app.select(p.key)
    pump(app, 2)
    entries = _entries(app.inspector.inner)
    assert entries
    before = dict(p.params)
    for e in entries:      # focus passing through every field
        e.event_generate("<FocusOut>")
    pump(app, 2)
    assert p.params == before and not app.dirty
    bore = entries[0]
    bore.delete(0, "end")
    bore.insert(0, "banana")
    bore.event_generate("<FocusOut>")
    pump(app, 2)
    assert p.params == before and not app.dirty
    bore.delete(0, "end")
    bore.insert(0, "80/2")
    bore.event_generate("<FocusOut>")
    pump(app, 2)
    assert p.params["bore"] == pytest.approx(0.04) and app.dirty


def test_save_and_reopen_keeps_edits(app, tmp_path):
    open_ex(app)
    p = next(x for x in app.circuit.parts if x.tag == "V2")
    app.set_param(p.key, "setting", 111e5)
    path = str(tmp_path / "s.fluidworx")
    assert app._write(path)
    assert not app.dirty
    app.open_path(path, confirm=False)
    pump(app, 2)
    assert next(x for x in app.circuit.parts if x.tag == "V2").params["setting"] == 111e5


def test_changed_source_offers_reload_and_keeps_edits(app, tmp_path):
    import shutil
    f = tmp_path / "c.schematix"
    shutil.copy(os.path.join(EXAMPLES, "lift_cylinder.schematix"), f)
    app.open_path(str(f), confirm=False)
    pump(app, 2)
    p = next(x for x in app.circuit.parts if x.tag == "V2")
    app.set_param(p.key, "setting", 90e5)
    shutil.copy(os.path.join(EXAMPLES, "load_holding.schematix"), f)
    os.utime(f, (1, 1))
    app._watch_source()
    pump(app, 2)
    assert app.banner.winfo_manager() == "pack"
    app.reload_source()
    pump(app, 2)
    assert app.banner.winfo_manager() == ""
    assert any(x.kind == "pilot_check" for x in app.circuit.parts)


def test_every_theme_and_unit_switch(app):
    open_ex(app)
    from fluidworx.vendor.openschematix.gui import theme as th
    app.select(next(x for x in app.circuit.parts if x.tag == "A1").key)
    for name in th.THEMES:
        app.set_theme(name)
        pump(app, 2)
    app.set_units("us")
    pump(app, 2)
    assert app.units.system == "us"


def test_dialogs_open_and_close(app):
    from fluidworx.gui.dialogs import AboutDialog, PreferencesDialog, RevisionDialog, ShortcutsDialog
    open_ex(app)
    for cls in (AboutDialog, PreferencesDialog, ShortcutsDialog, RevisionDialog):
        d = cls(app)
        pump(app, 2)
        d.cancel()
        pump(app, 1)


def test_about_says_what_openschematix_says(app):
    from fluidworx import COPYRIGHT, LICENSE_NAME
    from fluidworx.gui.dialogs import AboutDialog
    d = AboutDialog(app)
    pump(app, 2)
    texts = []

    def walk(w):
        for c in w.winfo_children():
            try:
                texts.append(str(c.cget("text")))
            except tk.TclError:
                pass
            walk(c)
    walk(d)
    body = " ".join(texts)
    assert COPYRIGHT in body and LICENSE_NAME in body and "Ko-fi" in body and "no telemetry" in body
    d.cancel()


def test_panels_toggle(app):
    open_ex(app)
    for side in ("left", "right", "bottom"):
        app.toggle_panel(side)
        pump(app, 2)
        app.toggle_panel(side)
        pump(app, 2)


def test_bad_file_shows_a_message_not_a_crash(app, tmp_path, monkeypatch):
    from tkinter import messagebox
    shown = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: shown.append(a))
    f = tmp_path / "bad.fluidworx"
    f.write_bytes(b"nope")
    assert not app.open_path(str(f), confirm=False)
    assert shown and app.study is None
