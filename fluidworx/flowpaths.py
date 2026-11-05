"""Flow along each drawn wire segment, so the animation follows the real path through a branching net.

Terminal flows are known from the simulation. Each net is walked as a tree of wire segments from its first
tank port (the residual has to go somewhere) and the flow in each segment is the sum of what enters below it.
Sheet connectors with the same label join their net across sheets with a zero-length link.
"""
from __future__ import annotations

from .vendor.openschematix.geometry import point_on_segment
from .vendor.openschematix.netlist import link_label
from .vendor.openschematix.symbols.general import OFFPAGE_IDS


def _pt(uid, p):
    return (uid, round(p[0], 1), round(p[1], 1))


class FlowPaths:
    def __init__(self, circuit):
        self.circuit = circuit
        self.segments = []      # (sheet uid, wire id, (x0, y0), (x1, y1), node)
        self._plan = {}         # node -> (order[(pt, parent, seg index or None, sign)], {pt: [term refs]})
        self._build()

    def _build(self):
        c = self.circuit
        by_node_edges: dict = {}
        by_node_terms: dict = {}
        project = c.project
        fluid_tank = {p.key for p in c.parts if p.kind == "tank"}
        tank_terms: dict = {}
        offpage: dict = {}
        for doc in project.sheets:
            wires = [w for w in doc.wires.values() if (doc.uid, w.id) in c.wire_nodes]
            stops: dict = {}
            for w in wires:
                node = c.wire_nodes[(doc.uid, w.id)]
                stops.setdefault(node, []).extend([w.points[0], w.points[-1]])
            for w in wires:
                node = c.wire_nodes[(doc.uid, w.id)]
                for a, b in zip(w.points, w.points[1:]):
                    on = [q for q in stops[node] if point_on_segment(q, a, b)]
                    on.sort(key=lambda q: (q[0] - a[0]) ** 2 + (q[1] - a[1]) ** 2)
                    chain = [a] + [q for q in on if _pt("", q) not in (_pt("", a), _pt("", b))] + [b]
                    for u, v in zip(chain, chain[1:]):
                        if _pt("", u) == _pt("", v):
                            continue
                        idx = len(self.segments)
                        self.segments.append((doc.uid, w.id, tuple(u), tuple(v), node))
                        by_node_edges.setdefault(node, []).append((_pt(doc.uid, u), _pt(doc.uid, v), idx))
            for comp in doc.components.values():
                if comp.symbol in OFFPAGE_IDS and link_label(comp):
                    for pos in comp.terminals().values():
                        offpage.setdefault(link_label(comp), []).append(_pt(doc.uid, pos))
        for ref, node in c.term_nodes.items():
            uid, cid, name = ref
            comp = project.find_sheet(uid).components.get(cid)
            if comp is None:
                continue
            pos = comp.terminals().get(name)
            if pos is None:
                continue
            pt = _pt(uid, pos)
            by_node_terms.setdefault(node, {}).setdefault(pt, []).append(ref)
            if (uid, cid) in fluid_tank:
                tank_terms.setdefault(node, pt)
        for label, pts in offpage.items():
            for a, b in zip(pts, pts[1:]):
                for node, edges in by_node_edges.items():
                    known = {e[0] for e in edges} | {e[1] for e in edges}
                    if a in known or b in known:
                        edges.append((a, b, None))
                        break
        for node, edges in by_node_edges.items():
            adj: dict = {}
            for a, b, idx in edges:
                adj.setdefault(a, []).append((b, idx, 1))
                adj.setdefault(b, []).append((a, idx, -1))
            terms = by_node_terms.get(node, {})
            seen, order = set(), []
            roots = ([tank_terms[node]] if node in tank_terms else []) + list(adj)
            for root in roots:
                if root in seen or root not in adj:
                    continue
                seen.add(root)
                stack = [root]
                order.append((root, None, None, 0))
                while stack:
                    u = stack.pop()
                    for v, idx, sign in adj[u]:
                        if v not in seen:
                            seen.add(v)
                            # edge u->v has direction `sign` along its segment; flow v->u is the opposite
                            order.append((v, u, idx, -sign))
                            stack.append(v)
            self._plan[node] = (order, terms)

    def compute(self, term_flows: dict) -> list:
        """Signed flow along each segment (positive = from its first point to its second)."""
        out = [0.0] * len(self.segments)
        for _node, (order, terms) in self._plan.items():
            acc: dict = {}
            for pt, refs in terms.items():
                # flow into a component leaves the net, so it counts as negative injection here
                acc[pt] = -sum(term_flows.get(r, 0.0) for r in refs)
            for pt, parent, idx, sign in reversed(order):
                if parent is None:
                    continue
                q = acc.get(pt, 0.0)        # flow from pt to its parent
                acc[parent] = acc.get(parent, 0.0) + q
                if idx is not None:
                    out[idx] = q * sign
        return out
