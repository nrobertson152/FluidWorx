"""The linear system both the fluid and the electrical networks are solved with. No third-party code.

Values may be complex: the electrical network carries a three-phase supply as phasors, and nothing here minds.
"""
from __future__ import annotations


class System:
    """Equations: for each free node, sum of outflows + C/dt (p - p_old) = injection; further rows for extra unknowns."""

    def __init__(self, sim):
        self.idx = sim.idx
        self.rows = [dict() for _ in range(sim.n_free)]
        self.rhs = [0.0] * sim.n_free

    def add_var(self) -> int:
        self.rows.append({})
        self.rhs.append(0.0)
        return len(self.rows) - 1

    def _a(self, r, c, v):
        row = self.rows[r]
        row[c] = row.get(c, 0.0) + v

    def line(self, a, b, g, e=0.0):
        """Q(a->b) = g (pa - pb - e)."""
        ia, ib = self.idx[a], self.idx[b]
        if ia is not None:
            self._a(ia, ia, g)
            if ib is not None:
                self._a(ia, ib, -g)
            self.rhs[ia] += g * e
        if ib is not None:
            self._a(ib, ib, g)
            if ia is not None:
                self._a(ib, ia, -g)
            self.rhs[ib] -= g * e

    def source(self, a, b, q):
        """Q(a->b) = q, whatever the pressures."""
        ia, ib = self.idx[a], self.idx[b]
        if ia is not None:
            self.rhs[ia] -= q
        if ib is not None:
            self.rhs[ib] += q

    def inlet_held(self, a, b, g, pset):
        """Q(a->b) = g (pa - pset): flow set by the inlet alone, whatever the outlet does."""
        ia, ib = self.idx[a], self.idx[b]
        if ia is not None:
            self._a(ia, ia, g)
            self.rhs[ia] += g * pset
            if ib is not None:
                self._a(ib, ia, -g)
        if ib is not None:
            self.rhs[ib] -= g * pset

    def regulated(self, a, b, g, pset):
        """Q(a->b) = g (pset - pb): a pressure regulator's flow, set by its outlet alone."""
        ia, ib = self.idx[a], self.idx[b]
        if ib is not None:
            self._a(ib, ib, g)
            self.rhs[ib] += g * pset
            if ia is not None:
                self._a(ia, ib, -g)
        if ia is not None:
            self.rhs[ia] -= g * pset

    def vccs(self, a, b, c, d, g):
        """Q(a->b) = g (pc - pd): a flow set by the difference between two other nodes."""
        ic, id_ = self.idx[c], self.idx[d]
        for r, sign in ((self.idx[a], 1.0), (self.idx[b], -1.0)):
            if r is None:
                continue
            if ic is not None:
                self._a(r, ic, sign * g)
            if id_ is not None:
                self._a(r, id_, -sign * g)


def solve(rows: list, rhs: list, scale: list) -> list:
    """Sparse Gaussian elimination with partial pivoting. `scale` = column scaling (pressures in bar, say)."""
    n = len(rows)
    work = []
    b = []
    for row, r in zip(rows, rhs):
        scaled = {j: a * scale[j] for j, a in row.items() if a != 0.0}
        m = max((abs(a) for a in scaled.values()), default=1.0) or 1.0
        work.append({j: a / m for j, a in scaled.items()})
        b.append(r / m)
    for k in range(n):
        best, best_v = None, 0.0
        for i in range(k, n):
            v = abs(work[i].get(k, 0.0))
            if v > best_v:
                best, best_v = i, v
        if best is None or best_v < 1e-14:
            work[k] = {k: 1.0}      # a free-floating unknown: pin it rather than fail
            b[k] = 0.0
            continue
        if best != k:
            work[k], work[best] = work[best], work[k]
            b[k], b[best] = b[best], b[k]
        pivot_row = work[k]
        piv = pivot_row[k]
        for i in range(k + 1, n):
            ri = work[i]
            f = ri.get(k)
            if f is None:
                continue
            f = f / piv
            del ri[k]
            for j, a in pivot_row.items():
                if j != k:
                    ri[j] = ri.get(j, 0.0) - f * a
            b[i] -= f * b[k]
    x = [0.0] * n
    for k in range(n - 1, -1, -1):
        s = b[k]
        row = work[k]
        for j, a in row.items():
            if j != k:
                s -= a * x[j]
        x[k] = s / row[k]
    return [v * c for v, c in zip(x, scale)]
