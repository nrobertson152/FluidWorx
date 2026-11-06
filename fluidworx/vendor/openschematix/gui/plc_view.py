"""Drawing PLC programs: rungs, blocks and steps, with what's live lit up.

Used in two places: the program editor, and FluidWorx, which shows a program running inside a simulated machine. So this
only draws. What's selected and what happens on a click belong to whoever is showing it.

Ladder is lit by real power flow, as the last scan left it: the program records what entered and left each element while it
runs (plc.ladder). A contact with no power reaching it was never evaluated, so whether it's closed is only known if its
operand is a plain name. Function blocks are lit by the signals on their wires, and charts by their active steps. The
text languages have nothing to light.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..plc.core import CompileError, FB_TYPES
from ..plc.fbd import pins_of

CW, CH = 96, 66         # ladder: an element's cell
X0, TOP = 44, 8
BW, PIN = 96, 18        # function block: width, and height of a pin's row
SW, SH, SGAP, COLW = 110, 34, 62, 190   # chart: a step, the gap below it, and the width of a column
SNAP = 10
_COILS = ("coil", "ncoil", "set", "reset")
_SIMPLE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _hot(u):
    return u["success"] if "success" in u else "#1a8f3c"


def coord(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and -1e6 < v < 1e6 else 40


def snap_grid(v):
    return round(v / SNAP) * SNAP


def measure(series) -> tuple:
    """(columns, rows) a series takes up."""
    cols, rows = 0, 1
    for el in series:
        if el.get("t") == "par":
            c, r = measure_par(el)
            cols += c
            rows = max(rows, r)
        else:
            cols += 1
    return max(cols, 1), rows


def measure_par(el) -> tuple:
    branches = el.get("branches") or [[]]
    cols, rows = 0, 0
    for b in branches:
        c, r = measure(b)
        cols = max(cols, c)
        rows += r
    return cols, max(rows, 1)


def box_text(el):
    k = el.get("t")
    if k in ("ton", "tof", "tp"):
        return k.upper(), [str(el.get("a") or "?"), str(el.get("pt") or "")]
    if k in ("ctu", "ctd"):
        return k.upper(), [str(el.get("a") or "?"), "PV " + str(el.get("pv") or "")]
    if k == "cmp":
        return str(el.get("op", ">")), [str(el.get("a") or "?"), str(el.get("b") or "?")]
    if k == "move":
        return ":=", [str(el.get("a") or "?"), str(el.get("b") or "?")]
    if k == "st":
        return "ST", [str(el.get("code") or "")]
    return str(k), []


def _show(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


# ================================================================ ladder
class Ladder:
    """One ladder program on a canvas. `rt`, a running PLC, and `pou`, this program's name, light it up."""

    def __init__(self, cv, theme, rungs, sel=None, rt=None, pou="", running=None):
        self.cv, self.t, self.rungs, self.sel, self.rt = cv, theme, rungs, sel, rt
        self.live = rt is not None and (rt.running if running is None else running)
        self.power = rt.program.power.get(pou, {}) if rt is not None else {}
        self.hits = []

    def draw(self):
        cv = self.cv
        cv.delete("all")
        self.hits = []
        t = self.t
        u = t.ui
        widest = max((measure(r.get("items", []))[0] for r in self.rungs), default=1)
        right = max(X0 + (widest + 1) * CW + 30, cv.winfo_width() - 30)
        rail = _hot(u) if self.live else u["text"]
        y = TOP
        for i, rung in enumerate(self.rungs):
            items = rung.get("items", [])
            _c, rows = measure(items)
            h = rows * CH
            comment = str(rung.get("comment") or "")
            if self.sel is not None and self.sel[0][0] == i:
                cv.create_rectangle(4, y, right + 26, y + h + 22, fill=u["surface2"], outline="")
            cv.create_text(10, y + 3, text=str(i + 1), anchor="nw", fill=u["faint"], font=t.fonts["small"])
            if comment:
                cv.create_text(X0, y + 3, text=comment, anchor="nw", fill=u["muted"], font=t.fonts["small"])
            cy = y + 18 + CH // 2
            cv.create_line(X0 - 14, y + 2, X0 - 14, y + h + 20, fill=rail, width=2)
            cv.create_line(right + 14, y + 2, right + 14, y + h + 20, fill=u["text"], width=2)
            self._series(items, (i,), X0 - 14, cy, right + 14, self.live)
            self.hits.append((0, y, right + 40, y + h + 22, ((i,), "rung")))
            y += h + 24
        cv.configure(scrollregion=(0, 0, right + 40, y + 10))

    def _flow(self, ref) -> tuple:
        return self.power.get(ref, (False, False)) if self.live else (False, False)

    def _wire(self, x0, y0, x1, y1, on):
        self.cv.create_line(x0, y0, x1, y1, fill=_hot(self.t.ui) if on else self.t.ui["text"], width=2.5 if on else 1.5)

    def _series(self, series, path, x, cy, xend, p):
        """A series from x to xend on the row centred at cy. Coils at the very end of a rung sit at the rail."""
        tail = 0
        if len(path) == 1:
            while tail < len(series) and series[len(series) - 1 - tail].get("t") in _COILS:
                tail += 1
        px = x
        for i, el in enumerate(series[:len(series) - tail] if tail else series):
            if el.get("t") == "par":
                px, p = self._par(el, path, i, px, cy)
            else:
                pi, p = self._flow((path, i))
                self._element(el, (path, i), px, cy, pi, p)
                px += CW
        if not series:
            self._wire(px, cy, xend, cy, p)
            self._empty(path, px, cy)
            return p
        if tail:
            start = xend - tail * CW
            self._wire(px, cy, start, cy, p)
            for k in range(tail):
                i = len(series) - tail + k
                pi, po = self._flow((path, i))
                self._element(series[i], (path, i), start + k * CW, cy, pi, po)
            return p
        self._wire(px, cy, xend, cy, p)
        return p

    def _empty(self, path, px, cy):
        """Where something can be added: for an editor. Running, there's nothing to say about it."""
        if self.rt is not None:
            return
        u = self.t.ui
        sel = self.sel == (path, None)
        self.cv.create_rectangle(px + 30, cy - 10, px + 66, cy + 10, fill=u["accent_soft"] if sel else u["surface"],
                                 outline=u["accent"] if sel else u["border"], dash=(3, 2))
        self.cv.create_text(px + 48, cy, text="add", fill=u["muted"], font=self.t.fonts["small"])
        self.hits.append((px + 30, cy - 10, px + 66, cy + 10, (path, None)))

    def _par(self, el, path, i, x, cy) -> tuple:
        cv = self.cv
        u = self.t.ui
        pi, po = self._flow((path, i))
        cols, _rows = measure_par(el)
        end = x + cols * CW
        y = cy
        last_y = cy
        for b_i, branch in enumerate(el.get("branches") or [[]]):
            self._series(branch, path + ((i, b_i),), x, y, end, pi)
            last_y = y
            y += measure(branch)[1] * CH
        selected = self.sel == (path, i)
        hot = _hot(u)
        cv.create_line(x, cy, x, last_y, fill=u["accent"] if selected else hot if pi else u["text"], width=2 if selected or pi else 1.5)
        cv.create_line(end, cy, end, last_y, fill=u["accent"] if selected else hot if po else u["text"], width=2 if selected or po else 1.5)
        self.hits.append((x - 6, cy - 6, x + 6, last_y + 6, (path, i)))
        self.hits.append((end - 6, cy - 6, end + 6, last_y + 6, (path, i)))
        return end, po

    def _closed(self, el, pi, po):
        """Whether a contact is closed: what it did with its power, or what its operand says if none reached it, or don't know."""
        if pi:
            return po
        name = str(el.get("a") or "")
        if self.rt is None or not self.live or not name or not _SIMPLE.issuperset(name):
            return False
        value = self.rt.read(name)
        if value is None:
            return False
        if el.get("t") == "nc":
            return not value
        return bool(value) if el.get("t") == "no" else False

    def _reading(self, el):
        """What's worth saying beside it while it runs."""
        if not self.live:
            return ""
        k = el.get("t")
        name = str(el.get("a") or "")
        if not name or not _SIMPLE.issuperset(name):
            return ""
        value = self.rt.read(name)
        if value is None:
            return ""
        if k in ("ton", "tof", "tp"):
            return f"{value.ET / 1000.0:.2f} s"
        if k in ("ctu", "ctd"):
            return f"count {value.CV}"
        return _show(value) if k in ("cmp", "move") else ""

    def _element(self, el, ref, x, cy, pi, po):
        cv = self.cv
        t = self.t
        u = t.ui
        k = el.get("t")
        small = t.fonts["small"]
        mid = x + CW // 2
        if self.sel == ref:
            cv.create_rectangle(x + 2, cy - CH // 2 + 2, x + CW - 2, cy + CH // 2 - 2, fill=u["accent_soft"], outline=u["accent"])
        label = str(el.get("a") or "")
        self.hits.append((x, cy - CH // 2, x + CW, cy + CH // 2, ref))
        hot, ink = _hot(u), u["text"]
        if k in ("no", "nc", "rise", "fall"):
            on = self._closed(el, pi, po)
            color = hot if on else ink
            width = 2 if on else 1.5
            self._wire(x, cy, mid - 6, cy, pi)
            self._wire(mid + 6, cy, x + CW, cy, po)
            cv.create_line(mid - 6, cy - 11, mid - 6, cy + 11, fill=color, width=width)
            cv.create_line(mid + 6, cy - 11, mid + 6, cy + 11, fill=color, width=width)
            if k == "nc":
                cv.create_line(mid - 12, cy + 11, mid + 12, cy - 11, fill=color, width=width)
            elif k in ("rise", "fall"):
                cv.create_text(mid, cy, text="P" if k == "rise" else "N", fill=color, font=small)
            cv.create_text(mid, cy - 22, text=label or "?", fill=ink if label else u["danger"], font=small)
        elif k in _COILS:
            color = hot if pi else ink
            width = 2 if pi else 1.5
            self._wire(x, cy, mid - 14, cy, pi)
            self._wire(mid + 14, cy, x + CW, cy, po)
            cv.create_arc(mid - 16, cy - 12, mid + 2, cy + 12, start=90, extent=180, style="arc", outline=color, width=width)
            cv.create_arc(mid - 2, cy - 12, mid + 16, cy + 12, start=-90, extent=180, style="arc", outline=color, width=width)
            mark = {"set": "S", "reset": "R", "ncoil": "/"}.get(k, "")
            if mark:
                cv.create_text(mid, cy, text=mark, fill=color, font=small)
            cv.create_text(mid, cy - 22, text=label or "?", fill=ink if label else u["danger"], font=small)
        else:
            title, lines = box_text(el)
            color = hot if po else ink
            self._wire(x, cy, x + 8, cy, pi)
            self._wire(x + CW - 8, cy, x + CW, cy, po)
            cv.create_rectangle(x + 8, cy - 22, x + CW - 8, cy + 24, outline=color, width=2 if po else 1.5, fill=u["surface"])
            cv.create_text(mid, cy - 14, text=title, fill=color, font=t.fonts["heading"])
            for n, line in enumerate(lines[:2]):
                cv.create_text(mid, cy + n * 12, text=line[:14], fill=u["muted"], font=small)
            said = self._reading(el)
            if said:
                cv.create_text(mid, cy + 30, text=said[:16], fill=u["text"], font=small)


# ================================================================ function block diagram
def block_rect(b) -> tuple:
    i, o = pins_of(b)
    rows = max(len(i), len(o), 1)
    x, y = coord(b.get("x")), coord(b.get("y"))
    small = b.get("type") in ("input", "output")
    return x, y, x + BW, y + (24 if small else 18 + rows * PIN)


def pin_xy(b, pin, side) -> tuple:
    i, o = pins_of(b)
    x0, y0, x1, _y1 = block_rect(b)
    small = b.get("type") in ("input", "output")
    names = i if side == "in" else o
    k = names.index(pin) if pin in names else 0
    y = y0 + 12 if small else y0 + 18 + k * PIN + PIN // 2
    return (x0 - 12, y) if side == "in" else (x1 + 12, y)


def wire_path(blocks, w):
    by_id = {b.get("id"): b for b in blocks}
    a, c = by_id.get(w["from"][0]), by_id.get(w["to"][0])
    if a is None or c is None:
        return None
    ax, ay = pin_xy(a, w["from"][1], "out")
    cx, cy = pin_xy(c, w["to"][1], "in")
    if cx >= ax + 16:
        mx = snap_grid((ax + cx) / 2)
        return [ax, ay, mx, ay, mx, cy, cx, cy]
    my = max(block_rect(a)[3], block_rect(c)[3]) + 14
    return [ax, ay, ax + 12, ay, ax + 12, my, cx - 12, my, cx - 12, cy, cx, cy]


def draw_fbd(cv, t, src, sel=None, frame=None):
    """A function block diagram on a canvas. `frame` is the running program's own values, by "block.pin"."""
    cv.delete("all")
    u = t.ui
    small = t.fonts["small"]
    hot = _hot(u)
    blocks = src["blocks"]
    for w in src["wires"]:
        try:
            path = wire_path(blocks, w) if isinstance(w, dict) else None
        except (CompileError, LookupError, TypeError):
            path = None
        if not path:
            continue
        selected = sel == ("wire", w)
        value = frame.get(f"{w['from'][0]}.{w['from'][1]}") if frame is not None else None
        cv.create_line(*path, fill=u["accent"] if selected else (hot if value is True else u["text"]), width=2.5 if selected or value is True else 1.5)
    for b in blocks:
        try:
            _block(b, src, cv, u, small, frame, t, sel)
        except CompileError:
            continue


def _block(b, src, cv, u, small, frame, t, sel):
    x0, y0, x1, y1 = block_rect(b)
    kind = b.get("type")
    selected = sel == ("block", b.get("id"))
    cv.create_rectangle(x0, y0, x1, y1, fill=u["accent_soft"] if selected else u["surface2"], outline=u["accent"] if selected else u["text"],
                        width=2 if selected else 1)
    ins, outs = pins_of(b)
    if kind in ("input", "output"):
        label = str(b.get("expr") if kind == "input" else b.get("target")) if (b.get("expr") or b.get("target")) else "?"
        cv.create_text((x0 + x1) / 2, y0 + 12, text=label[:15], fill=u["text"] if label != "?" else u["danger"], font=small)
    else:
        cv.create_text((x0 + x1) / 2, y0 + 9, text=kind, fill=u["text"], font=t.fonts["heading"])
        if b.get("name"):
            cv.create_text((x0 + x1) / 2, y0 - 7, text=str(b["name"]), fill=u["muted"], font=small)
        for k, name in enumerate(ins):
            yy = y0 + 18 + k * PIN + PIN // 2
            constant = (b.get("pins") or {}).get(name)
            cv.create_text(x0 + 4, yy, text=name if len(ins) > 1 or kind in FB_TYPES else "", anchor="w", fill=u["muted"], font=small)
            if constant and not any(isinstance(w, dict) and w.get("to") == [b["id"], name] for w in src["wires"]):
                cv.create_text(x0 - 15, yy, text=str(constant)[:10], anchor="e", fill=u["muted"], font=small)
        for k, name in enumerate(outs):
            yy = y0 + 18 + k * PIN + PIN // 2
            cv.create_text(x1 - 4, yy, text=name if len(outs) > 1 or kind in FB_TYPES else "", anchor="e", fill=u["muted"], font=small)
    negated = b.get("neg") or []
    for side, names in (("in", ins), ("out", outs)):
        for name in names:
            px, py = pin_xy(b, name, side)
            edge = x0 if side == "in" else x1
            cv.create_line(px, py, edge, py, fill=u["text"])
            if name in negated:
                cv.create_oval(edge - 8, py - 4, edge, py + 4, fill=u["surface"], outline=u["text"])
            cv.create_oval(px - 3, py - 3, px + 3, py + 3, fill=u["accent"], outline="")
            if frame is not None and side == "out":
                value = frame.get(f"{b['id']}.{name}")
                if value is not None and not isinstance(value, bool):
                    cv.create_text(px + 4, py - 8, text=f"{value:.4g}" if isinstance(value, float) else str(value), anchor="w", fill=u["muted"], font=small)


# ================================================================ sequential function chart
def chart_steps(src) -> list:
    return [s for s in src["steps"] if isinstance(s, dict) and isinstance(s.get("id"), int)]


def chart_transitions(src) -> list:
    return [t for t in src["transitions"] if isinstance(t, dict)]


def chart_layout(src) -> dict:
    """Where each step goes: by how many transitions it is from the start."""
    steps = chart_steps(src)
    trans = chart_transitions(src)
    rank = {}
    order = [s["id"] for s in steps if s.get("initial")] or [s["id"] for s in steps[:1]]
    for sid in order:
        rank[sid] = 0
    queue = list(order)
    while queue:
        cur = queue.pop(0)
        for t in trans:
            if cur in (t.get("from") or []):
                for nxt in t.get("to") or []:
                    if nxt not in rank:
                        rank[nxt] = rank[cur] + 1
                        queue.append(nxt)
    for s in steps:
        rank.setdefault(s["id"], max(rank.values(), default=-1) + 1)
    rows = {}
    for s in steps:
        rows.setdefault(rank[s["id"]], []).append(s["id"])
    pos = {}
    for r, ids in rows.items():
        for c, sid in enumerate(ids):
            pos[sid] = (70 + c * COLW, 30 + r * (SH + SGAP))
    return pos


def draw_chart(cv, t, src, sel=None, active=None) -> list:
    """A chart on a canvas. `active(step)` says whether a step is active. Returns what can be clicked."""
    cv.delete("all")
    hits = []
    u = t.ui
    small = t.fonts["small"]
    pos = chart_layout(src)
    hot = _hot(u)
    lane = 0
    for tr in chart_transitions(src):
        sources = [pos[i] for i in tr.get("from") or [] if i in pos]
        targets = [pos[i] for i in tr.get("to") or [] if i in pos]
        if not sources or not targets:
            continue
        color = u["accent"] if sel == ("trans", tr.get("id")) else u["text"]
        sy = max(y for _x, y in sources) + SH
        ty = min(y for _x, y in targets)
        mx = sum(x for x, _y in sources) / len(sources) + SW / 2
        if ty > sy:                 # forward
            by = (sy + ty) / 2
            for x, y in sources:
                cv.create_line(x + SW / 2, y + SH, x + SW / 2, by, mx, by, fill=color)
            for x, y in targets:
                cv.create_line(mx, by, x + SW / 2, by, x + SW / 2, y, fill=color, arrow="last")
        else:                       # back up the chart, round the left side
            lane += 1
            bx = 40 - lane * 10
            by = sy + 18
            for x, y in sources:
                cv.create_line(x + SW / 2, y + SH, x + SW / 2, by, fill=color)
            for x, y in targets:
                cv.create_line(mx, by, bx, by, bx, y + SH / 2, x, y + SH / 2, fill=color, arrow="last")
        cv.create_line(mx - 14, by, mx + 14, by, fill=color, width=3)
        cond = str(tr.get("cond") or "?")
        cv.create_text(mx + 18, by - 2, text=cond[:34], anchor="sw", fill=u["danger"] if cond == "?" else u["muted"], font=small)
        hits.append((mx - 20, by - 16, mx + 160, by + 8, ("trans", tr.get("id"))))
    for s in chart_steps(src):
        x, y = pos[s["id"]]
        selected = sel == ("step", s["id"])
        on = bool(active(s)) if active is not None else False
        cv.create_rectangle(x, y, x + SW, y + SH, fill=hot if on else (u["accent_soft"] if selected else u["surface2"]),
                            outline=u["accent"] if selected else u["text"], width=2 if selected else 1)
        if s.get("initial"):
            cv.create_rectangle(x + 3, y + 3, x + SW - 3, y + SH - 3, outline=u["text"])
        cv.create_text(x + SW / 2, y + SH / 2, text=str(s.get("name"))[:14], fill=u["text"], font=t.fonts["heading"])
        hits.append((x, y, x + SW, y + SH, ("step", s["id"])))
        acts = [a for a in (s.get("actions") or []) if isinstance(a, dict)]
        if acts:
            text = "\n".join(f"{a.get('q', 'N')} {a.get('target') or (str(a.get('code') or '')[:16])}" for a in acts[:4])
            cv.create_text(x + SW + 6, y + 1, text=text, anchor="nw", fill=u["muted"], font=small)
    xs = [p[0] for p in pos.values()] or [0]
    ys = [p[1] for p in pos.values()] or [0]
    cv.configure(scrollregion=(0, 0, max(xs) + COLW + 200, max(ys) + SH + SGAP + 40))
    return hits


# ================================================================ a program, running
def running_frame(rt, name):
    """The running program's own values."""
    return next((p.frame for p in rt.program.pous if p.name == name), None)


def step_is_active(rt):
    return lambda s: rt.read(str(s.get("name")))


class ProgramView(ttk.Frame):
    """One program of a running PLC, read-only. `theme` is a function that returns the current theme. Whoever hosts the PLC can say
    whether it's running, with `is_running`, since a PLC on a machine can be stopped or lose its supply and still have a program."""

    def __init__(self, master, theme, is_running=None):
        super().__init__(master, style="Surface.TFrame")
        self.theme = theme
        self.is_running = is_running
        self.rt = None
        self.pou = None
        self._last = None
        t = theme()
        self.note = ttk.Label(self, text="", style="Faint.TLabel", wraplength=700, justify="left", padding=(8, 2))
        self.holder = ttk.Frame(self, style="Surface.TFrame")
        self.holder.pack(fill="both", expand=True)
        self.cv = tk.Canvas(self.holder, bg=t.ui["surface"], highlightthickness=0)
        self.xs = ttk.Scrollbar(self.holder, orient="horizontal", command=self.cv.xview)
        self.ys = ttk.Scrollbar(self.holder, command=self.cv.yview)
        self.cv.configure(xscrollcommand=self.xs.set, yscrollcommand=self.ys.set)
        self.text = tk.Text(self.holder, wrap="none", state="disabled", highlightthickness=0, bd=0, padx=8, pady=6)
        self.cv.bind("<Configure>", lambda e: self.refresh(force=True))
        self.cv.bind("<MouseWheel>", lambda e: self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cv.bind("<Button-4>", lambda e: self.cv.yview_scroll(-1, "units"))
        self.cv.bind("<Button-5>", lambda e: self.cv.yview_scroll(1, "units"))
        self._place(False)

    def _place(self, text):
        for w in (self.cv, self.xs, self.ys, self.text):
            w.pack_forget()
        if text:
            self.text.pack(fill="both", expand=True)
        else:
            self.xs.pack(side="bottom", fill="x")
            self.ys.pack(side="right", fill="y")
            self.cv.pack(side="left", fill="both", expand=True)

    def show(self, rt, pou):
        """`pou` is the stored program, as in plc.program_of(params)["pous"]."""
        self.rt, self.pou = rt, pou
        self._last = None
        lang = pou.get("lang") if isinstance(pou, dict) else None
        graphic = lang in ("ld", "fbd", "sfc")
        self._place(not graphic)
        self.note.pack_forget()
        say = "" if graphic or pou is None else ("Text programs have nothing to light up. Their variables are listed alongside.")
        if rt is not None and pou is not None and running_frame(rt, pou.get("name")) is None:
            say = "This program is switched off, or it has errors, so it isn't running."
        if say:
            self.note.configure(text=say)
            self.note.pack(fill="x", before=self.holder)
        if not graphic:
            t = self.theme()
            self.text.configure(state="normal", bg=t.ui["surface"], fg=t.ui["text"], font=t.fonts["mono"])
            self.text.delete("1.0", "end")
            source = pou.get("source") if isinstance(pou, dict) else ""
            self.text.insert("1.0", source if isinstance(source, str) else "")
            self.text.configure(state="disabled")
        self.refresh(force=True)

    def refresh(self, force=False):
        rt, pou = self.rt, self.pou
        if rt is None or pou is None or pou.get("lang") not in ("ld", "fbd", "sfc"):
            return
        name = pou.get("name")
        running = rt.running if self.is_running is None else bool(self.is_running())
        now = (running, dict(rt.program.power.get(name, {})), repr(rt.watch()))
        if not force and now == self._last:
            return
        self._last = now
        t = self.theme()
        self.cv.configure(bg=t.ui["surface"])
        src = pou.get("source")
        if not isinstance(src, dict):
            return
        lang = pou["lang"]
        if lang == "ld":
            Ladder(self.cv, t, src.get("rungs") or [], rt=rt, pou=name, running=running).draw()
        elif lang == "fbd":
            if isinstance(src.get("blocks"), list) and isinstance(src.get("wires"), list):
                draw_fbd(self.cv, t, src, frame=running_frame(rt, name) if running else None)
                box = self.cv.bbox("all")
                if box:
                    self.cv.configure(scrollregion=(0, 0, box[2] + 40, box[3] + 40))
        elif isinstance(src.get("steps"), list) and isinstance(src.get("transitions"), list):
            draw_chart(self.cv, t, src, active=step_is_active(rt) if running else None)
