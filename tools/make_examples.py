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
        self.doc.name = "Pneumatics" if "neumatic" in title else "Hydraulics"
        self.doc.sheet.title = title
        self.n = 1

    def _id(self):
        self.n += 1
        return self.n

    def part(self, symbol, x, y, des="", label="", rot=0, mirror=False, params=None, props=None):
        c = Component(id=self._id(), symbol=symbol, x=x, y=y, rotation=rot, mirror=mirror, designator=des, label=label,
                      params=params or {}, props=props or {})
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

    def save(self, name):
        self.doc.next_id = self.n + 1
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


def main():
    OUT.mkdir(exist_ok=True)
    lift()
    sequence()
    load_holding()
    motor()
    accumulator()
    pneumatic()
    pneumatic_single()
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
