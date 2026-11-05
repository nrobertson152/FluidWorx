"""Interactive command framework.

Commands that need user input (LINE, MOVE, TRIM, …) are written as Python
generators that *yield requests* and receive the answers:

    def cmd_circle(app):
        c = yield GetPoint("Centre")
        r = yield GetDistance("Radius", base=c)
        ...

The CommandRunner answers requests from canvas clicks (with grid/object
snap and ortho applied) or from text typed in the command line (coordinates,
numbers, keywords), so the same command code serves the mouse, the keyboard
and the command line. Everything a command changes becomes one undo step.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import commands as cmdparse


@dataclass
class Request:
    prompt: str = ""
    keywords: tuple = ()          # accepted keyword answers, e.g. ("Close", "Undo")

    def keyword_hint(self):
        return f" [{'/'.join(self.keywords)}]" if self.keywords else ""


@dataclass
class GetPoint(Request):
    base: Optional[tuple] = None              # rubber-band origin (model units)
    preview: Optional[Callable] = None        # fn(point) -> list of scene prims
    allow_enter: bool = False                 # Enter/right-click answers None
    snap_grid: Optional[bool] = None          # None = user setting
    osnap: Optional[bool] = None              # None = user setting; False = never snap to objects


@dataclass
class GetDistance(Request):
    base: Optional[tuple] = None
    preview: Optional[Callable] = None
    default: Optional[float] = None           # in mm


@dataclass
class GetAngle(Request):
    base: Optional[tuple] = None
    preview: Optional[Callable] = None
    default: Optional[float] = None
    step: float = 0.0                         # snap angle (e.g. 90 for symbols)


@dataclass
class GetText(Request):
    default: str = ""


@dataclass
class GetNumber(Request):
    default: Optional[float] = None


@dataclass
class GetSelection(Request):
    use_current: bool = True                  # accept the existing selection immediately


@dataclass
class GetObject(Request):
    accept: Optional[Callable] = None         # fn(obj) -> bool
    allow_enter: bool = True
    want_point: bool = True


@dataclass
class Answer:
    value: object = None
    keyword: str = ""


class CommandError(Exception):
    pass


class CommandRunner:
    def __init__(self, app):
        self.app = app
        self.gen = None
        self.req: Optional[Request] = None
        self.name = ""
        self.snap = None
        self.last_point = None
        self.message = ""
        self.typed = False      # the last answer was typed (not clicked)

    @property
    def active(self) -> bool:
        return self.gen is not None

    # ---------------------------------------------------------------- lifecycle
    def start(self, name: str, gen):
        if self.active:
            self.cancel()
        self.name = name
        self.gen = gen
        self.snap = self.app.begin_change()
        self.message = ""
        self._send(None, first=True)

    def _send(self, value, first=False):
        try:
            req = next(self.gen) if first else self.gen.send(value)
        except StopIteration as stop:
            self._finish(stop.value)
            return
        except CommandError as e:
            self.app.log(f"{self.name}: {e}", "error")
            self._finish(None, cancelled=True)
            return
        self.req = req
        if isinstance(req, GetSelection) and req.use_current and self.app.selection:
            self._send(set(self.app.selection))
            return
        self.app.show_prompt(self._prompt_text())
        self.app.canvas.on_request(req)

    def _prompt_text(self):
        r = self.req
        if r is None:
            return ""
        extra = ""
        if isinstance(r, (GetDistance, GetNumber, GetAngle)) and getattr(r, "default", None) is not None:
            extra = f" <{r.default:g}>"
        if isinstance(r, GetText) and r.default:
            extra = f" <{r.default}>"
        return f"{self.name}: {r.prompt}{r.keyword_hint()}{extra}"

    def _finish(self, result, cancelled=False):
        gen, self.gen, self.req = self.gen, None, None
        try:
            if gen is not None:
                gen.close()
        except Exception:  # noqa: BLE001
            pass
        msg = result if isinstance(result, str) else ("Cancelled." if cancelled else f"{self.name} done.")
        self.app.commit_change(self.snap, msg if not cancelled else None)
        self.snap = None
        self.app.show_prompt("")
        self.app.canvas.on_request(None)
        if cancelled:
            self.app.set_status(f"{self.name} cancelled.")

    def cancel(self):
        if self.active:
            self._finish(None, cancelled=True)

    # ---------------------------------------------------------------- answers
    def answer(self, value):
        """Give the current request a value (point in model units, ids, …)."""
        if not self.active:
            return
        self.typed = False
        if isinstance(self.req, (GetPoint, GetDistance, GetAngle)) and isinstance(value, tuple):
            if isinstance(self.req, GetPoint):
                self.last_point = value
            if isinstance(self.req, GetDistance):
                b = self.req.base
                value = math.hypot(value[0] - b[0], value[1] - b[1]) * self.app.mm_per_unit()
            elif isinstance(self.req, GetAngle):
                b = self.req.base
                value = math.degrees(math.atan2(-(value[1] - b[1]), value[0] - b[0]))
                if self.req.step:
                    value = round(value / self.req.step) * self.req.step
        self._send(value)

    def enter(self):
        """Empty Enter / right-click."""
        r = self.req
        if r is None:
            return
        if isinstance(r, GetSelection):
            self._send(set(self.app.selection))
        elif isinstance(r, GetPoint) and r.allow_enter:
            self._send(None)
        elif isinstance(r, GetObject) and r.allow_enter:
            self._send(None)
        elif isinstance(r, (GetDistance, GetNumber, GetAngle)) and r.default is not None:
            self._send(r.default)
        elif isinstance(r, GetText):
            self._send(r.default)
        else:
            self._finish("Done.")

    def text(self, s: str) -> bool:
        """Typed answer from the command line. Returns False if not understood."""
        r = self.req
        s = s.strip()
        if r is None:
            return False
        self.typed = True
        if not s:
            self.enter()
            return True
        for kw in r.keywords:
            if kw.upper().startswith(s.upper()) and len(s) >= 1:
                self._send(Answer(keyword=kw))
                return True
        try:
            if isinstance(r, GetText):
                self._send(s)
            elif isinstance(r, GetPoint):
                last = self.app.to_user(self.last_point) if self.last_point else None
                p = self.app.to_model(cmdparse.parse_point(s, last))
                self.last_point = p
                self._send(p)
            elif isinstance(r, (GetDistance, GetNumber)):
                if isinstance(r, GetDistance) and cmdparse.is_point_text(s):
                    p = self.app.to_model(cmdparse.parse_point(s, self.app.to_user(r.base) if r.base else None))
                    self.answer(p)
                else:
                    self._send(cmdparse.parse_number(s))
            elif isinstance(r, GetAngle):
                self._send(cmdparse.parse_number(s))
            else:
                return False
        except cmdparse.ParseError as e:
            self.app.log(str(e), "error")
            return True
        return True
