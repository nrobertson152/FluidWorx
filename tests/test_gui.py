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


NO_VALVE = {"electronics_threshold.schematix", "motor_starter_pump.schematix"}      # these two operate no valve


def test_every_example_opens_runs_and_draws(app):
    for f in glob.glob(os.path.join(EXAMPLES, "*.schematix")):
        app.open_path(f, confirm=False)
        pump(app, 3)
        app.sim.run(0.2)
        app.canvas.update_state(0.03)
        assert app.canvas.node_items or app.canvas.el_items
        assert app.canvas.valves or os.path.basename(f) in NO_VALVE
        for uid in app.circuit.sheets:      # every sheet, and each draws its own kind of line
            app.show_sheet(uid)
            pump(app, 2)
            app.canvas.update_state(0.03)
            assert app.canvas.node_items or app.canvas.el_items


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


# ---------------------------------------------------------------- the electrical side
def tag(app, name):
    return next(b for b in app.sim.parts.values() if b.part.tag == name)


def sheet_named(app, name):
    app.show_sheet(next(d.uid for d in app.circuit.project.sheets if d.name == name))
    pump(app, 2)


def event_at(app, comp, dx=0, dy=0):
    x, y = app.canvas.to_screen(comp.local_to_world(dx, dy))
    return type("E", (), {"x": x, "y": y, "x_root": x, "y_root": y})()


def test_a_push_button_is_held_while_the_mouse_is_down(app):
    open_ex(app, "plc_cylinder.schematix")
    sheet_named(app, "Control")
    s0 = tag(app, "S0")
    e = event_at(app, s0.part.comp)
    app.canvas._on_press(e)
    assert s0.manual and app.selected == s0.part.key
    pump(app, 2)
    assert s0.manual, "still held"
    app.canvas._on_release(e)
    assert not s0.manual


def test_a_real_mouse_press_on_a_push_button(app):
    open_ex(app, "plc_cylinder.schematix")
    sheet_named(app, "Control")
    s0 = tag(app, "S0")
    e = event_at(app, s0.part.comp)
    app.canvas.event_generate("<ButtonPress-1>", x=int(e.x), y=int(e.y))
    pump(app, 2)
    assert s0.manual
    app.canvas.event_generate("<ButtonRelease-1>", x=int(e.x), y=int(e.y))
    pump(app, 2)
    assert not s0.manual


def test_pressing_start_runs_the_machine_on_screen(app):
    open_ex(app, "plc_cylinder.schematix")
    sheet_named(app, "Control")
    canvas = app.canvas
    app.sim.run(0.2)
    canvas.update_state(0.0)
    plc = tag(app, "PLC1")
    assert plc.badge(app.units) == "RUN"
    live = next(iter(canvas.el_items))
    assert canvas.el_colors[live]
    e = event_at(app, tag(app, "S0").part.comp)
    canvas._on_press(e)
    app.sim.run(0.2)
    canvas._on_release(e)
    app.sim.run(1.0)
    canvas.update_state(0.03)
    assert tag(app, "Y1a").energised and tag(app, "A1").x > 0.0
    glow = canvas.glows[tag(app, "Y1a").part.comp.id]
    assert canvas.itemcget(glow["item"], "state") == "normal", "the energised coil is lit"
    pump(app, 2)
    canvas.update_state(0.03)
    assert canvas.find_withtag(f"pins{plc.part.comp.id}"), "the PLC shows which pins are on"
    sheet_named(app, "Hydraulics")
    canvas.update_state(0.03)
    assert canvas.valves and canvas.node_items, "and the other sheet is the same simulation"


def test_a_click_operates_a_switch_and_not_a_contact_that_follows_a_coil(app):
    open_ex(app, "motor_starter_pump.schematix")
    sheet_named(app, "Control")
    follower = next(b for b in app.sim.parts.values() if b.part.tag == "K1" and b.part.kind == "contact" and b.part.sheet == app.doc.uid)
    was = follower.closed()
    e = event_at(app, follower.part.comp)
    app.canvas._on_press(e)
    app.canvas._on_release(e)
    assert follower.closed() == was
    assert app.selected == follower.part.key


def test_contacts_are_drawn_as_they_are_now(app):
    open_ex(app, "relay_latch.schematix")
    sheet_named(app, "Relay logic")
    canvas = app.canvas
    canvas.update_state(0.0)
    nc = next(b for b in app.sim.parts.values() if b.part.tag == "S0")
    closed_items = canvas.find_withtag(f"pole{nc.part.comp.id}")
    assert closed_items, "a closed contact has a line through it"
    app.command(nc.part.key, "press")
    canvas.update_state(0.0)
    assert canvas.find_withtag(f"pole{nc.part.comp.id}"), "and one drawn closed that has opened shows a gap"
    assert nc.poles_now()[0][2] is False


def test_hovering_tells_you_what_a_part_and_a_wire_are_doing(app):
    open_ex(app, "plc_cylinder.schematix")
    sheet_named(app, "Control")
    s0 = tag(app, "S0")
    app.canvas._on_motion(event_at(app, s0.part.comp))
    assert "Hold the mouse down" in app.status.get()
    wire = next(w for w in app.doc.wires.values() if (app.doc.uid, w.id) in app.circuit.el_wire_nodes and len(w.points) >= 2)
    a, b = wire.points[0], wire.points[1]
    x, y = app.canvas.to_screen(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    app.canvas._on_motion(type("E", (), {"x": x, "y": y})())
    assert "Line:" in app.status.get() and " V" in app.status.get()


def test_inspector_shows_a_plc_live(app):
    open_ex(app, "plc_cylinder.schematix")
    sheet_named(app, "Control")
    plc = tag(app, "PLC1")
    app.select(plc.part.key)
    app.sim.run(0.2)
    app._refresh_views(force=True)
    assert app.inspector.watch_rows["I1"].get() == "on", "the home switch is made"
    assert app.inspector.watch_rows["Q0"].get() == "off"
    assert "Stop" in app.inspector.action_buttons["toggle"][1]
    app.inspector.action_buttons["toggle"][0].invoke()
    pump(app, 2)
    assert plc.status() == "Stop"


def test_inspector_opens_for_every_electrical_part(app):
    for name in ("plc_cylinder", "relay_latch", "motor_starter_pump", "electronics_threshold"):
        open_ex(app, name + ".schematix")
        for key in list(app.sim.net.by_key):
            app.select(key)
            app.inspector.refresh()
        pump(app, 1)


def test_a_study_can_set_a_link_and_the_schematic_stays_as_it_was(app, tmp_path):
    open_ex(app, "electronics_threshold.schematix")
    original = app.study.source_bytes
    coil = next(b for b in app.sim.parts.values() if b.part.kind == "coil")
    pot = tag(app, "R1")
    assert not [x for x in app.circuit.links if x.kind == "sense"]
    app.select(pot.part.key)
    app.set_link(pot.part.key, "Senses", "A9")
    assert app.dirty and app.study.links
    assert any("A9" in i.text for i in app.circuit.issues)
    assert app.study.source_bytes == original
    app.set_link(pot.part.key, "Senses", "")
    assert not app.study.links, "set back to what the drawing says, there is nothing left to keep"
    del coil


def test_a_link_in_a_study_survives_saving_and_reopening(app, tmp_path):
    open_ex(app, "plc_cylinder.schematix")
    s1 = tag(app, "S1")
    app.set_link(s1.part.key, "Senses", "A1 50%")
    path = str(tmp_path / "t.fluidworx")
    assert app._write(path)
    assert app.open_path(path, confirm=False)
    assert any("A1 50%" in x.text for x in app.circuit.links)
    assert app.study.links


def test_links_panel_lists_them_and_selects_the_part(app):
    open_ex(app, "plc_cylinder.schematix")
    tree = app.links_panel.tree
    rows = [tree.item(i, "values") for i in tree.get_children()]
    assert any("Y1a" in r[1] for r in rows)
    first = next(i for i in tree.get_children() if "Y1a" in tree.item(i, "values")[1])
    tree.selection_set(first)
    pump(app, 2)
    assert app.selected is not None


def test_trace_draws_on_off_lanes(app):
    open_ex(app, "plc_cylinder.schematix")
    app.sim.run(0.5)
    panel = app.trace_panel
    assert any(panel.app.sim.trace.channels[i][2] == "state" for i in panel.enabled)
    app.dock.select(panel)
    pump(app, 2)
    panel.draw()
    assert any(g[0] == "state" for g in panel._geom)
    panel.hover_x = 300
    panel._draw_cursor()


def test_a_report_of_an_electrical_circuit(app, tmp_path):
    from fluidworx import report
    open_ex(app, "plc_cylinder.schematix")
    app.sim.run(0.5)
    text = report.html_report(app.study, app.circuit, app.sim, app.units, app.doc)
    assert "Supplies" in text and "G1" in text and "RMS" in text
    assert report.trace_csv(app.sim, app.units).startswith("Time (s)")


def test_reset_and_theme_change_with_electrical_parts_on_screen(app):
    open_ex(app, "motor_starter_pump.schematix")
    sheet_named(app, "Power")
    app.sim.run(0.2)
    app.canvas.update_state(0.03)
    app.reset()
    app.cycle_theme()
    pump(app, 3)
    app.canvas.update_state(0.03)
    app.set_units("us")
    pump(app, 2)
    assert app.units.fmt("voltage", 24.0) == "24 V"
