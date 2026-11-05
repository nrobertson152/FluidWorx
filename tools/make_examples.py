#!/usr/bin/env python3
"""Build the example circuits in fluidworx/examples with OpenSchematix's own project writer."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fluidworx.vendor.openschematix import projectio  # noqa: E402
from fluidworx.vendor.openschematix.model import Component, Wire  # noqa: E402
from fluidworx.vendor.openschematix.project import new_project  # noqa: E402

OUT = ROOT / "fluidworx" / "examples"


class B:
    """Small drawing helper: place parts, join terminals with orthogonal wires."""

    def __init__(self, title):
        self.project = new_project(title=title, size="A3")
        self.project.meta["title"] = title
        self.doc = self.project.sheets[0]
        self.doc.name = "Pneumatics" if "neumatic" in title or "Relay" in title else "Hydraulics"
        self.doc.sheet.title = title
        self.n = 1

    def _id(self):
        self.n += 1
        return self.n

    def part(self, symbol, x, y, des="", label="", rot=0, mirror=False, params=None, props=None, numbered=None):
        """`numbered` are terminal designations, as "13", "14": what tells a relay's contacts apart on a drawing."""
        c = Component(id=self._id(), symbol=symbol, x=x, y=y, rotation=rot, mirror=mirror, designator=des, label=label,
                      params=params or {}, props=props or {})
        if numbered:
            c.terminal_labels = dict(zip([t.name for t in c.terminal_defs()], numbered))
        self.doc.components[c.id] = c
        return c

    @staticmethod
    def _ortho(pts):
        """Insert an elbow wherever two neighbouring points aren't in line, so no wire is ever diagonal."""
        out = [tuple(pts[0])]
        for p in pts[1:]:
            q = out[-1]
            if q[0] != p[0] and q[1] != p[1]:
                out.append((q[0], p[1]))
            if tuple(p) != out[-1]:
                out.append(tuple(p))
        return out

    def wire(self, a, an, b, bn, via=(), style="solid"):
        p0, p1 = a.terminals()[an], b.terminals()[bn]
        pts = self._ortho([p0, *via, p1])
        w = Wire(id=self._id(), points=pts, start=[a.id, an], end=[b.id, bn], style=style)
        self.doc.wires[w.id] = w
        return w

    def tee(self, a, an, point, via=(), style="solid"):
        """Wire from a terminal onto an existing wire (junction by end point on segment)."""
        p0 = a.terminals()[an]
        w = Wire(id=self._id(), points=self._ortho([p0, *via, point]), start=[a.id, an], end=None, style=style)
        self.doc.wires[w.id] = w
        return w

    def line(self, *points):
        """A wire with no terminal at either end: a rail, or a bus."""
        w = Wire(id=self._id(), points=self._ortho(list(points)), start=None, end=None)
        self.doc.wires[w.id] = w
        return w

    def sheet(self, name):
        """Carry on drawing on a new sheet."""
        self.doc = self.project.add_sheet(name)
        self.doc.sheet.title = self.project.meta["title"]
        return self.doc

    def save(self, name):
        for doc in self.project.sheets:
            doc.next_id = self.n + 1
        projectio.save_project(self.project, str(OUT / name))


def _lowest(c):
    t = c.terminals()
    return max(t, key=lambda n: t[n][1])


def _highest(c):
    t = c.terminals()
    return min(t, key=lambda n: t[n][1])


def v43(positions=("parallel", "tandem", "crossed")):
    return {"medium": "hyd", "type": "4/3", "positions": list(positions), "left": ["spring", "solenoid"],
            "right": ["spring", "solenoid"]}


def lift():
    b = B("Lift cylinder, 4/3 tandem centre")
    cyl = b.part("fl.hyd.cyl.double", 710, 240, "A1", "63/36x300", rot=180, mirror=True)
    v = b.part("fl.hyd.dcv", 700, 400, "V1", params=v43())
    pump = b.part("fl.hyd.pump", 500, 580, "P1", "12 L/min")
    t1 = b.part("fl.hyd.tank", 500, 660, "Z1")
    rv = b.part("fl.hyd.relief", 600, 530, "V2", "160 bar", rot=180)
    t2 = b.part("fl.hyd.tank", 600, 610, "Z2")
    g = b.part("fl.hyd.gauge", 560, 440, "S1")
    f = b.part("fl.hyd.filter", 800, 510, "Z3", rot=90)
    t3 = b.part("fl.hyd.tank", 800, 590, "Z4")
    b.wire(pump, "S", t1, "T")
    b.wire(pump, "P", v, "P", via=[(500, 480), (690, 480)])
    b.tee(rv, "P", (600, 480))
    b.wire(rv, "T", t2, "T")
    b.tee(g, "P", (560, 480))
    b.wire(v, "T", f, "1", via=[(710, 460), (800, 460)])
    b.wire(f, "2", t3, "T")
    b.wire(v, "A", cyl, "A")
    b.wire(v, "B", cyl, "B", via=[(710, 350), (720, 350)])
    b.save("lift_cylinder.schematix")


def sequence():
    b = B("Clamp then press, sequence valve")
    clamp = b.part("fl.hyd.cyl.double", 330, 200, "A1", "50/28x100 clamp", rot=180, mirror=True)
    press = b.part("fl.hyd.cyl.double", 660, 200, "A2", "80/45x200 press", rot=180, mirror=True)
    v = b.part("fl.hyd.dcv", 480, 470, "V1", params=v43(("parallel", "closed", "crossed")))
    seq = b.part("fl.hyd.sequence", 640, 340, "V3", "60 bar", rot=180)
    chk = b.part("fl.hyd.check", 580, 340, "V4", rot=90)
    pump = b.part("fl.hyd.pump", 300, 620, "P1", "20 L/min")
    t1 = b.part("fl.hyd.tank", 300, 680, "Z1")
    rv = b.part("fl.hyd.relief", 400, 590, "V2", "160 bar", rot=180)
    t2 = b.part("fl.hyd.tank", 400, 650, "Z2")
    t3 = b.part("fl.hyd.tank", 490, 540, "Z3")
    g = b.part("fl.hyd.gauge", 360, 500, "S1")
    b.wire(pump, "S", t1, "T")
    b.wire(pump, "P", v, "P", via=[(300, 540), (470, 540)])
    b.tee(rv, "P", (400, 540))
    b.tee(g, "P", (360, 540))
    b.wire(rv, "T", t2, "T")
    b.wire(v, "T", t3, "T")
    # A: to the clamp's cap end, and through the sequence valve to the press's
    b.wire(v, "A", clamp, "A", via=[(470, 400), (310, 400)])
    b.tee(seq, "P", (470, 400), via=[(640, 400)])
    b.wire(seq, "A", press, "A")
    # the bypass check lets the press return past the sequence valve: free flow from its outlet to the A line
    assert chk.terminals()["1"][1] < chk.terminals()["2"][1], "check must be free-flowing downward"
    b.tee(chk, "1", (640, 280), via=[(chk.terminals()["1"][0], 280)])
    b.tee(chk, "2", (580, 400))
    # B: to both rod ends
    b.wire(v, "B", press, "B", via=[(490, 420), (720, 420), (720, 260), (670, 260)])
    b.tee(clamp, "B", (670, 260), via=[(340, 260)])
    b.save("sequence_clamp_press.schematix")


def load_holding():
    b = B("Load holding, pilot-operated check valve")
    cyl = b.part("fl.hyd.cyl.double", 560, 160, "A1", "63/36x400 hanging load", rot=180, mirror=True,
                 props={"Load": "8000", "Load mode": "constant"})
    pc = b.part("fl.hyd.check.pilot", 540, 290, "V3", rot=270)
    fc = b.part("fl.hyd.flow.oneway", 540, 370, "V4", rot=270, props={"Opening": "10"})
    v = b.part("fl.hyd.dcv", 550, 470, "V1", params=v43(("parallel", "float", "crossed")))
    pump = b.part("fl.hyd.pump", 380, 620, "P1", "15 L/min")
    t1 = b.part("fl.hyd.tank", 380, 680, "Z1")
    rv = b.part("fl.hyd.relief", 460, 590, "V2", "180 bar", rot=180)
    t2 = b.part("fl.hyd.tank", 460, 650, "Z2")
    t3 = b.part("fl.hyd.tank", 560, 540, "Z3")
    g = b.part("fl.hyd.gauge", 470, 210, "S1")
    b.wire(pump, "S", t1, "T")
    b.wire(pump, "P", v, "P", via=[(380, 540), (540, 540)])
    b.tee(rv, "P", (460, 540))
    b.wire(rv, "T", t2, "T")
    b.wire(v, "T", t3, "T")
    # lowering is metered 2 -> 1, so the load can't run away from the pump
    b.wire(v, "A", fc, "1")
    b.wire(fc, "2", pc, "1")
    b.wire(pc, "2", cyl, "A")
    b.wire(v, "B", cyl, "B", via=[(560, 400), (640, 400), (640, 220), (570, 220)])
    b.tee(pc, "X", (640, 245), via=[(pc.terminals()["X"][0], 245)], style="dashed")
    b.tee(g, "P", (540, 230), via=[(470, 230)])
    b.save("load_holding.schematix")


def motor():
    b = B("Hydraulic motor with meter-out speed control")
    m = b.part("fl.hyd.motor.bidir", 620, 170, "M1", "32 cc/rev", props={"Torque": "20"})
    fc = b.part("fl.hyd.flow.oneway", 720, 290, "V3", rot=270, props={"Opening": "15"})
    v = b.part("fl.hyd.dcv", 620, 470, "V1", params=v43(("parallel", "tandem", "crossed")))
    pump = b.part("fl.hyd.pump", 400, 620, "P1", "25 L/min")
    t1 = b.part("fl.hyd.tank", 400, 680, "Z1")
    rv = b.part("fl.hyd.relief", 500, 590, "V2", "140 bar", rot=180)
    t2 = b.part("fl.hyd.tank", 500, 650, "Z2")
    t3 = b.part("fl.hyd.tank", 630, 540, "Z3")
    g = b.part("fl.hyd.gauge", 460, 500, "S1")
    b.wire(pump, "S", t1, "T")
    b.wire(pump, "P", v, "P", via=[(400, 540), (610, 540)])
    b.tee(rv, "P", (500, 540))
    b.tee(g, "P", (460, 540))
    b.wire(rv, "T", t2, "T")
    b.wire(v, "T", t3, "T")
    b.wire(v, "A", m, _highest(m), via=[(610, 300), (540, 300), (540, 120), (620, 120)])
    # return flow leaves the motor and is metered 2 -> 1 on its way back to the valve
    assert _highest(fc) == "2", "the metered direction must be away from the motor"
    b.wire(fc, "2", m, _lowest(m), via=[(fc.terminals()["2"][0], 215), (620, 215)])
    b.wire(v, "B", fc, "1", via=[(630, 400), (fc.terminals()["1"][0], 400)])
    b.save("hydraulic_motor.schematix")


def accumulator():
    b = B("Accumulator charging and unloading")
    cyl = b.part("fl.hyd.cyl.double", 750, 160, "A1", "50/28x300", rot=180, mirror=True)
    v = b.part("fl.hyd.dcv", 740, 340, "V1", params=v43(("parallel", "closed", "crossed")))
    chk = b.part("fl.hyd.check", 470, 420, "V3")
    acc = b.part("fl.hyd.accumulator", 560, 340, "Z2", props={"Volume": "2", "Precharge": "80"})
    drain = b.part("fl.hyd.shutoff", 620, 480, "V4", "closed", rot=90)
    t4 = b.part("fl.hyd.tank", 620, 540, "Z5")
    pump = b.part("fl.hyd.pump", 330, 560, "P1", "8 L/min")
    t1 = b.part("fl.hyd.tank", 330, 620, "Z1")
    rv = b.part("fl.hyd.relief", 400, 510, "V2", "160 bar", rot=180)
    t2 = b.part("fl.hyd.tank", 400, 570, "Z3")
    t3 = b.part("fl.hyd.tank", 750, 410, "Z4")
    g = b.part("fl.hyd.gauge", 670, 380, "S1")
    b.wire(pump, "S", t1, "T")
    b.wire(pump, "P", chk, "1", via=[(330, 420)])
    b.tee(rv, "P", (400, 420), via=[])
    b.wire(rv, "T", t2, "T")
    b.wire(chk, "2", v, "P", via=[(730, 420)])
    b.tee(acc, "P", (acc.terminals()["P"][0], 420))
    top = _highest(drain)
    b.tee(drain, top, (620, 420))
    b.wire(drain, _lowest(drain), t4, "T")
    b.tee(g, "P", (670, 420))
    b.wire(v, "T", t3, "T")
    b.wire(v, "A", cyl, "A", via=[])
    b.wire(v, "B", cyl, "B", via=[(750, 280), (760, 280)])
    b.save("accumulator_circuit.schematix")


def pneumatic():
    b = B("Pneumatic cylinder, 5/2 valve with speed control")
    cyl = b.part("fl.pneu.cyl.double", 600, 150, "A1", "40/16x150", props={"Load": "100"})
    fa = b.part("fl.pneu.flow.oneway", 580, 280, "V2", rot=270)
    fb = b.part("fl.pneu.flow.oneway", 690, 280, "V3", rot=270)
    v = b.part("fl.pneu.dcv", 620, 430, "V1", params={"medium": "pneu", "type": "5/2", "positions": ["1-4", "1-2"],
                                                       "left": ["solenoid"], "right": ["spring"]})
    frl = b.part("fl.pneu.frl", 420, 540, "Z1", rot=0)
    comp = b.part("fl.pneu.compressor", 300, 540, "P1", "7 bar", rot=90)
    reg = b.part("fl.pneu.regulator", 520, 540, "V4", "5 bar", rot=90)
    t = v.terminals()
    b.wire(comp, "2", frl, "1")
    b.wire(frl, "2", reg, "1")
    b.wire(reg, "2", v, "1", via=[(t["1"][0], reg.terminals()["2"][1])])
    b.wire(v, "4", fa, _lowest(fa), via=[(t["4"][0], 350), (fa.terminals()[_lowest(fa)][0], 350)])
    b.wire(v, "2", fb, _lowest(fb), via=[(t["2"][0], 350), (fb.terminals()[_lowest(fb)][0], 350)])
    b.wire(fa, _highest(fa), cyl, "A")
    b.wire(fb, _highest(fb), cyl, "B", via=[(fb.terminals()[_highest(fb)][0], 110), (cyl.terminals()["B"][0], 110)])
    b.save("pneumatic_cylinder.schematix")


def pneumatic_single():
    b = B("Pneumatic single-acting cylinder, 3/2 valve")
    cyl = b.part("fl.pneu.cyl.single", 560, 170, "A1", "32x80")
    v = b.part("fl.pneu.dcv", 540, 370, "V1", params={"medium": "pneu", "type": "3/2", "positions": ["P-A", "A-T"],
                                                       "left": ["pushbutton"], "right": ["spring"]})
    comp = b.part("fl.pneu.compressor", 360, 500, "P1", "6 bar", rot=90)
    t = v.terminals()
    b.wire(comp, "2", v, "1", via=[(t["1"][0], comp.terminals()["2"][1])])
    b.wire(v, "2", cyl, "A", via=[(t["2"][0], 260), (cyl.terminals()["A"][0], 260)])
    b.save("pneumatic_single_acting.schematix")


DOWN = {"rot": 270, "mirror": True}      # a two-terminal part drawn with terminal 1 at the top
ST_CYCLE = """(* Press Start with the rod home to extend it. At the end of its stroke, or if the pressure
   says it has met something, it comes back on its own. *)
IF Start AND AtHome THEN Extending := TRUE; END_IF;
IF AtEnd OR Pressure > 90.0 THEN Extending := FALSE; END_IF;
Extend := Extending;
Retract := NOT Extending AND NOT AtHome;
Moving := Extend OR Retract;
"""


def cylinder_sheet(b, tag_valve, label="50/28x200", flow="10 L/min", relief="100 bar"):
    """The hydraulics of the electrical examples: a pump, a 4/3 double-solenoid valve and a cylinder."""
    cyl = b.part("fl.hyd.cyl.double", 710, 240, "A1", label, rot=180, mirror=True)
    v = b.part("fl.hyd.dcv", 700, 400, tag_valve, params=v43())
    pump = b.part("fl.hyd.pump", 500, 580, "P1", flow)
    t1 = b.part("fl.hyd.tank", 500, 660, "Z1")
    rv = b.part("fl.hyd.relief", 600, 530, "V2", relief, rot=180)
    t2 = b.part("fl.hyd.tank", 600, 610, "Z2")
    f = b.part("fl.hyd.filter", 800, 510, "Z3", rot=90)
    t3 = b.part("fl.hyd.tank", 800, 590, "Z4")
    b.wire(pump, "S", t1, "T")
    b.wire(pump, "P", v, "P", via=[(500, 480), (690, 480)])
    b.tee(rv, "P", (600, 480))
    b.wire(rv, "T", t2, "T")
    b.wire(v, "T", f, "1", via=[(710, 460), (800, 460)])
    b.wire(f, "2", t3, "T")
    b.wire(v, "A", cyl, "A")
    b.wire(v, "B", cyl, "B", via=[(710, 350), (720, 350)])
    return cyl, v, pump


def plc_cylinder():
    b = B("PLC running a cylinder, with position and pressure feedback")
    _cyl, v, _pump = cylinder_sheet(b, "Y1")
    ax = v.terminals()["A"][0]
    pt_h = b.part("fl.hyd.pressure.transducer", 620, 290, "PT1")
    b.tee(pt_h, "P", (ax, 340), via=[(620, 340)])
    b.sheet("Control")
    psu = b.part("el.psu", 170, 365, "G1", "24 V 5 A")
    b.wire(b.part("el.rail.pos", 100, 335, label="L"), "1", psu, "L")
    b.wire(b.part("el.rail.neg", 100, 395, label="N"), "1", psu, "N")
    b.line(psu.terminals()["+"], (230, 355), (230, 90), (610, 90))
    b.line(psu.terminals()["-"], (230, 375), (230, 640), (920, 640))
    b.tee(b.part("el.rail.pos", 300, 50, label="+24V"), "1", (300, 90))
    b.tee(b.part("el.rail.neg", 300, 680, label="0V"), "1", (300, 640))
    params = {"di": 3, "do": 3, "ai": 1, "ao": 0, "do_type": "source",
              "tags": {"I0": "Start", "I1": "AtHome", "I2": "AtEnd", "AI0": "Pressure", "Q0": "Extend", "Q1": "Retract", "Q2": "Moving"},
              "program": {"scan_ms": 10, "io": {"AI0": {"signal": "0-10V", "lo": 0, "hi": 250, "note": "PT1, bar"}},
                          "vars": [{"name": "Extending", "type": "BOOL", "init": "", "note": "the rod is on its way out"}],
                          "pous": [{"name": "Cycle", "lang": "st", "source": ST_CYCLE}]}}
    plc = b.part("el.plc", 640, 340, "PLC1", params=params)
    pins = plc.terminals()
    start = b.part("el.pushbutton.no.iec", 360, 190, "S0", "Start")
    home = b.part("el.switch.limit.no", 360, 250, "S1", "Home", props={"Senses": "A1 retracted"})
    end = b.part("el.switch.limit.no", 360, 310, "S2", "End", props={"Senses": "A1 extended"})
    pt = b.part("el.sensor.analog", 440, pins["AI0"][1], "PT1", "0-250 bar 0-10 V")
    plus_y = pt.terminals()["+"][1]
    b.line((300, 90), (300, plus_y))        # what feeds the inputs
    for device, y in ((start, 190), (home, 250), (end, 310)):
        b.tee(device, "1", (300, y))
    b.wire(start, "2", plc, "I0", via=[(530, 190), (530, pins["I0"][1])])
    b.wire(home, "2", plc, "I1", via=[(510, 250), (510, pins["I1"][1])])
    b.wire(end, "2", plc, "I2", via=[(490, 310), (490, pins["I2"][1])])
    b.tee(pt, "+", (300, plus_y))
    b.tee(pt, "-", (380, 640), via=[(380, pt.terminals()["-"][1])])
    b.wire(pt, "OUT", plc, "AI0")
    estop = b.part("el.estop", pins["L+"][0], 150, "S9", **DOWN)
    b.tee(estop, "1", (pins["L+"][0], 90))
    b.wire(estop, "2", plc, "L+")
    b.tee(plc, "M", (pins["M"][0], 640))
    lamp = b.part("el.lamp.iec", 780, 400, "H1", "Moving", **DOWN)
    yb = b.part("el.coil.valve", 850, 400, "Y1b", "24 V 10 W")
    ya = b.part("el.coil.valve", 920, 400, "Y1a", "24 V 10 W")
    b.wire(plc, "Q0", ya, "A1", via=[(920, pins["Q0"][1])])
    b.wire(plc, "Q1", yb, "A1", via=[(850, pins["Q1"][1])])
    b.wire(plc, "Q2", lamp, "1", via=[(780, pins["Q2"][1])])
    for load, pin in ((lamp, "2"), (yb, "A2"), (ya, "A2")):
        x = load.terminals()[pin][0]
        b.tee(load, pin, (x, 640))
    b.save("plc_cylinder.schematix")


def ladder_rails(b, first, last, x0=120, x1=900, plus="+24V", minus="0V"):
    """The two sides of a ladder, from the first rung to the last, with what they are named at the ends."""
    b.tee(b.part("el.rail.pos", x0, first - 100, label=plus), "1", (x0, first - 60))
    b.tee(b.part("el.rail.neg", x1, last + 100, label=minus), "1", (x1, last + 60))
    b.line((x0, first - 60), (x0, last))
    b.line((x1, first), (x1, last + 60))
    return x0, x1


def relay_latch():
    b = B("Relay logic: start, stop and automatic return")
    cyl = b.part("fl.pneu.cyl.double", 600, 150, "A1", "40/16x150", props={"Load": "100"})
    v = b.part("fl.pneu.dcv", 620, 430, "Y1", params={"medium": "pneu", "type": "5/2", "positions": ["1-4", "1-2"],
                                                       "left": ["solenoid"], "right": ["solenoid"]})
    comp = b.part("fl.pneu.compressor", 360, 540, "P1", "6 bar", rot=90)
    t = v.terminals()
    b.wire(comp, "2", v, "1", via=[(t["1"][0], comp.terminals()["2"][1])])
    b.wire(v, "4", cyl, "A", via=[(t["4"][0], 300), (cyl.terminals()["A"][0], 300)])
    b.wire(v, "2", cyl, "B", via=[(t["2"][0], 340), (690, 340), (690, 110), (cyl.terminals()["B"][0], 110)])
    b.sheet("Relay logic")
    x0, x1 = ladder_rails(b, 140, 500)
    y = 140     # rung 1: the latch, broken by the timer that runs at the end of the stroke
    stop = b.part("el.pushbutton.nc.nema", 200, y, "S0", "Stop")
    start = b.part("el.pushbutton.no.nema", 320, y, "S1", "Start")
    dwell = b.part("el.contact.nc.nema", 480, y, "KT1")
    k1 = b.part("el.coil.nema", 760, y, "K1")
    hold = b.part("el.contact.no.nema", 320, y + 60, "K1", numbered=("13", "14"))
    b.tee(stop, "1", (x0, y))
    b.wire(stop, "2", start, "1")
    b.wire(start, "2", dwell, "1")
    b.wire(dwell, "2", k1, "1")
    b.tee(k1, "2", (x1, y))
    b.tee(hold, "1", (260, y), via=[(260, y + 60)])
    b.tee(hold, "2", (400, y), via=[(400, y + 60)])
    y = 270     # rung 2: extend while the latch holds
    c = b.part("el.contact.no.nema", 320, y, "K1", numbered=("23", "24"))
    ya = b.part("el.coil.nema", 760, y, "Y1a")
    b.tee(c, "1", (x0, y))
    b.wire(c, "2", ya, "1")
    b.tee(ya, "2", (x1, y))
    y = 340     # rung 3: otherwise retract, until home
    c = b.part("el.contact.nc.nema", 320, y, "K1", numbered=("31", "32"))
    home = b.part("el.switch.limit.nc", 480, y, "S2", "Home", props={"Senses": "A1 retracted"})
    yb = b.part("el.coil.nema", 760, y, "Y1b")
    b.tee(c, "1", (x0, y))
    b.wire(c, "2", home, "1")
    b.wire(home, "2", yb, "1")
    b.tee(yb, "2", (x1, y))
    y = 420     # rung 4: lamp
    c = b.part("el.contact.no.nema", 320, y, "K1", numbered=("43", "44"))
    lamp = b.part("el.lamp.iec", 760, y, "H1", "Cycle running")
    b.tee(c, "1", (x0, y))
    b.wire(c, "2", lamp, "1")
    b.tee(lamp, "2", (x1, y))
    y = 500     # rung 5: dwell at the end of the stroke
    end = b.part("el.switch.limit.no", 320, y, "S3", "End", props={"Senses": "A1 extended"})
    timer = b.part("el.coil.ondelay", 760, y, "KT1", "1 s", rot=270)
    b.tee(end, "1", (x0, y))
    b.wire(end, "2", timer, "A1")
    b.tee(timer, "A2", (x1, y))
    b.save("relay_latch.schematix")


def motor_starter():
    b = B("Three-phase starter driving a hydraulic pump")
    pump = b.part("fl.hyd.pump", 500, 500, "P1", "10 L/min", props={"Driven by": "M1"})
    t1 = b.part("fl.hyd.tank", 500, 580, "Z1")
    rv = b.part("fl.hyd.relief", 640, 420, "V1", "100 bar", rot=180)
    t2 = b.part("fl.hyd.tank", 640, 500, "Z2")
    gauge = b.part("fl.hyd.gauge", 420, 310, "G1")
    ps = b.part("fl.hyd.pressure.switch", 560, 310, "S3", "80 bar")
    b.wire(pump, "S", t1, "T")
    b.line(pump.terminals()["P"], (500, 370), (640, 370))
    b.wire(rv, "T", t2, "T")
    b.tee(rv, "P", (640, 370))
    b.tee(gauge, "P", (500, 370), via=[(420, 370)])
    b.tee(ps, "X", (560, 370))
    b.sheet("Power")
    xs = (300, 320, 340)
    for x, name, rx in zip(xs, ("L1", "L2", "L3"), (260, 320, 380)):
        rail = b.part("el.rail.pos", rx, 50, label=name)
        b.line(rail.terminals()["1"], (rx, 90), (x, 90), (x, 110))
    q1 = b.part("el.breaker.3p", 320, 130, "Q1", "16 A", rot=270, mirror=True)
    k1 = b.part("el.contact.3no", 320, 210, "K1", rot=270, mirror=True)
    f1 = b.part("el.overload.3p", 320, 290, "F1", "5 A", rot=270, mirror=True)
    motor = b.part("el.motor.3ph", 320, 380, "M1", "3 kW")
    for up, down in ((q1, k1), (k1, f1)):
        for a, c in (("2", "1"), ("4", "3"), ("6", "5")):
            b.wire(up, a, down, c)
    b.wire(f1, "2", motor, "U1", via=[(300, 340), (310, 340)])
    b.wire(f1, "4", motor, "V1")
    b.wire(f1, "6", motor, "W1", via=[(340, 340), (330, 340)])
    b.sheet("Control")
    x0, x1 = ladder_rails(b, 140, 410)
    y = 140     # the start/stop latch, broken by the overload
    stop = b.part("el.pushbutton.nc.nema", 200, y, "S0", "Stop")
    trip = b.part("el.contact.nc.nema", 300, y, "F1", numbered=("95", "96"))
    start = b.part("el.pushbutton.no.nema", 420, y, "S1", "Start")
    coil = b.part("el.coil.nema", 760, y, "K1")
    hold = b.part("el.contact.no.nema", 420, y + 60, "K1", numbered=("13", "14"))
    b.tee(stop, "1", (x0, y))
    b.wire(stop, "2", trip, "1")
    b.wire(trip, "2", start, "1")
    b.wire(start, "2", coil, "1")
    b.tee(coil, "2", (x1, y))
    b.tee(hold, "1", (360, y), via=[(360, y + 60)])
    b.tee(hold, "2", (500, y), via=[(500, y + 60)])
    for y, tag, symbol, numbers, lamp_tag, text in ((270, "K1", "el.contact.no.nema", ("23", "24"), "H1", "Running"),
                                                    (340, "S3", "el.switch.pressure.no", None, "H2", "Pressure OK"),
                                                    (410, "F1", "el.contact.no.nema", ("97", "98"), "H3", "Overload")):
        c = b.part(symbol, 420, y, tag, numbered=numbers)
        lamp = b.part("el.lamp.iec", 760, y, lamp_tag, text)
        b.tee(c, "1", (x0, y))
        b.wire(c, "2", lamp, "1")
        b.tee(lamp, "2", (x1, y))
    b.save("motor_starter_pump.schematix")


def electronics():
    b = B("Electronics: a comparator and a transistor switch a relay")
    b.doc.name = "Electronics"
    top, bottom = 80, 520
    b.line((160, top), (800, top))
    b.line((160, bottom), (800, bottom))
    src = b.part("el.source.dc", 160, 300, "G1", "12 V", rot=90)
    b.line(src.terminals()["+"], (160, top))
    b.line(src.terminals()["-"], (160, bottom))
    b.tee(b.part("el.earth", 220, 560), "1", (220, bottom))
    pot = b.part("el.potentiometer.iec", 260, 300, "R1", "10k", rot=90)
    b.line(pot.terminals()["1"], (260, top))
    b.line(pot.terminals()["2"], (260, bottom))
    r2 = b.part("el.resistor.iec", 340, 180, "R2", "4.7k", rot=90)
    r3 = b.part("el.resistor.iec", 340, 420, "R3", "10k", rot=90)
    b.line(r2.terminals()["1"], (340, top))
    b.wire(r2, "2", r3, "1")
    b.line(r3.terminals()["2"], (340, bottom))
    op = b.part("el.opamp.supply", 470, 300, "U1")
    b.wire(pot, "3", op, "+")
    b.tee(op, "-", (340, op.terminals()["-"][1]))
    b.line(op.terminals()["V+"], (470, top))
    b.line(op.terminals()["V-"], (470, bottom))
    r4 = b.part("el.resistor.iec", 570, 300, "R4", "1k")
    q = b.part("el.npn", 640, 300, "Q1")
    b.wire(op, "OUT", r4, "1")
    b.wire(r4, "2", q, "B")
    b.line(q.terminals()["E"], (650, bottom))
    coil = b.part("el.coil.iec", 650, 200, "K1", "12 V 2 W")
    b.line(coil.terminals()["A1"], (650, top))
    b.wire(coil, "A2", q, "C")
    d1 = b.part("el.diode", 710, 200, "D1", rot=270)
    b.line(d1.terminals()["K"], (710, top))
    b.tee(d1, "A", (650, 250), via=[(710, 250)])
    contact = b.part("el.contact.no.iec", 800, 150, "K1", **DOWN)
    r5 = b.part("el.resistor.iec", 800, 240, "R5", "1k", rot=90)
    led = b.part("el.led", 800, 340, "H1", rot=90)
    b.line(contact.terminals()["1"], (800, top))
    b.wire(contact, "2", r5, "1")
    b.wire(r5, "2", led, "A")
    b.line(led.terminals()["K"], (800, bottom))
    b.save("electronics_threshold.schematix")


def main():
    OUT.mkdir(exist_ok=True)
    lift()
    sequence()
    load_holding()
    motor()
    accumulator()
    pneumatic()
    pneumatic_single()
    plc_cylinder()
    relay_latch()
    motor_starter()
    electronics()
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
