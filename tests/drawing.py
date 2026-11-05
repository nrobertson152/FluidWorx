"""Draw a circuit in a test: real OpenSchematix components and wires, so the nets come from its own netlist."""
from __future__ import annotations

from fluidworx import circuit, engine
from fluidworx.vendor.openschematix.model import Component, Wire
from fluidworx.vendor.openschematix.project import new_project


class Drawing:
    """Parts sit far apart on a pattern with no three in line, so a wire's end can only be on the wires that share it."""

    def __init__(self, sheets=1):
        self.project = new_project(title="test", size="A0")
        self.doc = self.project.sheets[0]
        while len(self.project.sheets) < sheets:
            self.project.add_sheet()
        self.n = 1

    def sheet(self, i):
        return self.project.sheets[i]

    def add(self, symbol, des="", label="", params=None, props=None, sheet=0):
        self.n += 1
        doc = self.project.sheets[sheet]
        x = 1000 + (self.n * 739) % 90000 // 10 * 10
        y = 1000 + (self.n * self.n * 1283) % 90000 // 10 * 10
        c = Component(id=self.n, symbol=symbol, x=x, y=y, designator=des, label=label, params=params or {}, props=props or {})
        doc.components[c.id] = c
        return c

    def _doc_of(self, comp):
        return next(d for d in self.project.sheets if d.components.get(comp.id) is comp)

    def wire(self, *pins):
        """Join terminals in a chain: wire((a, "1"), (b, "2"), (c, "1"))."""
        for (a, an), (b, bn) in zip(pins, pins[1:]):
            self.n += 1
            doc = self._doc_of(a)
            w = Wire(id=self.n, points=[a.terminals()[an], b.terminals()[bn]], start=[a.id, an], end=[b.id, bn])
            doc.wires[w.id] = w

    def build(self, overrides=None):
        return circuit.build(self.project, (), overrides)

    def sim(self, overrides=None):
        return engine.Simulator(self.build(overrides))


def part(sim, comp):
    """The behaviour of a drawn component."""
    return next(b for b in sim.parts.values() if b.part.comp.id == comp.id)


def volts(sim, comp, pin):
    return sim.net.v[part(sim, comp).t[pin]]


def diff(sim, comp, a, b):
    return volts(sim, comp, a) - volts(sim, comp, b)
