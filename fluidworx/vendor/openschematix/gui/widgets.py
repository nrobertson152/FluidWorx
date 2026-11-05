"""Reusable interface components built on the design system (theme.py)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as th
from .icons import draw_icon

_CURRENT = {"theme": None}


def current_theme() -> th.Theme:
    return _CURRENT["theme"]


def set_current_theme(t):
    _CURRENT["theme"] = t


# ================================================================ tooltip
class Tooltip:
    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = None
        self.after = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set(self, text):
        self.text = text

    def _schedule(self, _e):
        self._hide()
        self.after = self.widget.after(self.delay, self._show)

    def _show(self):
        if self.tip or not self.text:
            return
        t = current_theme()
        bg = t.ui["tooltip_bg"] if t else "#1f2329"
        fg = t.ui["tooltip_fg"] if t else "#ffffff"
        try:
            x = self.widget.winfo_rootx() + 4
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        try:
            self.tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg=bg, fg=fg, padx=8, pady=4, justify="left",
                 font=t.fonts["small"] if t else None).pack()

    def hide(self):
        self._hide()

    def _hide(self, _e=None):
        if self.after:
            try:
                self.widget.after_cancel(self.after)
            except tk.TclError:
                pass
            self.after = None
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


# ================================================================ icon button
class IconButton(tk.Canvas):
    """Flat toolbar button with a vector icon, hover/pressed/checked states
    and an optional text label."""

    def __init__(self, master, icon, command=None, tooltip="", text="", size=18, checkable=False, bg_key="toolbar",
                 pad=6, accent_checked=True):
        self.f = th.dpi_factor(master)
        self.icon, self.text, self.command = icon, text, command
        self.size = size * self.f
        self.pad = pad * self.f
        self.checkable, self.checked, self.enabled = checkable, False, True
        self.bg_key = bg_key
        self.hover = self.pressed = False
        self.accent_checked = accent_checked
        t = current_theme()
        w = self.size + 2 * self.pad
        self._text_w = 0
        if text and t:
            from tkinter import font as tkfont
            self._text_w = tkfont.Font(font=t.fonts["small"]).measure(text) + 6 * self.f
            w += self._text_w
        super().__init__(master, width=int(w), height=int(self.size + 2 * self.pad), highlightthickness=0,
                         borderwidth=0, cursor="hand2", takefocus=0)
        # add="+": the tooltip binds <Enter>/<Leave> on this widget too; a plain
        # bind() here replaced its handlers, so toolbar tooltips never appeared.
        self.tip = Tooltip(self, tooltip) if tooltip else None
        self.bind("<Enter>", lambda e: self._set(hover=True), add="+")
        self.bind("<Leave>", lambda e: self._set(hover=False, pressed=False), add="+")
        self.bind("<ButtonPress-1>", self._press, add="+")
        self.bind("<ButtonRelease-1>", self._release, add="+")
        th.subscribe(self._retheme)
        self.bind("<Destroy>", lambda e: th.unsubscribe(self._retheme) if e.widget is self else None)
        self.draw()

    def _retheme(self, _t):
        self.draw()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def _press(self, _e):
        # <ButtonPress-1> is more specific than the tooltip's <ButtonPress>, so
        # Tk runs only this handler: hide the tooltip here.
        if self.tip is not None:
            self.tip.hide()
        self._set(pressed=True)

    def set_tooltip(self, text: str):
        """Set or replace the tooltip text (creates the tooltip if needed)."""
        if self.tip is None:
            self.tip = Tooltip(self, text)
        else:
            self.tip.set(text)

    def _release(self, e):
        was = self.pressed
        self._set(pressed=False)
        if was and self.enabled and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            if self.command:
                self.command()

    def set_checked(self, v: bool):
        if self.checked != bool(v):
            self.checked = bool(v)
            self.draw()

    def set_enabled(self, v: bool):
        if self.enabled != bool(v):
            self.enabled = bool(v)
            self.configure(cursor="hand2" if v else "")
            self.draw()

    def draw(self):
        t = current_theme()
        if t is None:
            return
        u = t.ui
        try:
            self.delete("all")
        except tk.TclError:
            return
        base = u[self.bg_key]
        bg = base
        if self.enabled and self.pressed:
            bg = u["pressed"]
        elif self.checked and self.accent_checked:
            bg = u["accent_soft"]
        elif self.enabled and self.hover:
            bg = u["hover"]
        self.configure(bg=base)
        W, H = int(self["width"]), int(self["height"])
        if bg != base:
            r = 4 * self.f
            x1, y1, x2, y2 = 1, 1, W - 1, H - 1
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2,
                   x1, y2 - r, x1, y1 + r, x1, y1]
            self.create_polygon(*pts, smooth=True, fill=bg, outline="")
        col = u["faint"] if not self.enabled else (u["accent"] if self.checked else u["text"])
        acc = u["faint"] if not self.enabled else u["accent"]
        draw_icon(self, self.icon, self.pad, self.pad, self.size, col, acc, width=1.55,
                  font_family=t.fonts.get("family", "Helvetica"))
        if self.text:
            self.create_text(self.pad + self.size + 5 * self.f, H / 2, text=self.text, anchor="w",
                             fill=col if self.enabled else u["faint"], font=t.fonts["small"])


class ToolbarSeparator(tk.Frame):
    def __init__(self, master, vertical=True):
        f = th.dpi_factor(master)
        super().__init__(master, width=int(1 * f) if vertical else 1, height=int(22 * f) if vertical else 1,
                         bd=0, highlightthickness=0)
        self._theme_bg = "border"
        t = current_theme()
        if t:
            self.configure(bg=t.ui["border"])


# ================================================================ panel header / sections
class PanelHeader(ttk.Frame):
    """Header row for a sidebar panel: title + action buttons."""

    def __init__(self, master, title, actions=()):
        super().__init__(master, style="Surface.TFrame", padding=(10, 8, 6, 6))
        self.title = ttk.Label(self, text=title.upper(), style="Heading.TLabel")
        self.title.pack(side="left")
        self.buttons = []
        for icon, cmd, tip in reversed(list(actions)):
            b = IconButton(self, icon, cmd, tip, size=15, bg_key="surface", pad=4)
            b.pack(side="right")
            self.buttons.append(b)


class Section(ttk.Frame):
    """Collapsible inspector section."""

    def __init__(self, master, title, expanded=True, on_toggle=None):
        super().__init__(master, style="Surface.TFrame")
        self.expanded = expanded
        self.on_toggle = on_toggle
        head = ttk.Frame(self, style="Surface.TFrame", padding=(8, 7, 8, 3))
        head.pack(fill="x")
        self.chev = IconButton(head, "chevron_down" if expanded else "chevron_right", self.toggle,
                               "Expand / collapse this section", size=12, bg_key="surface", pad=2)
        self.chev.pack(side="left")
        lab = ttk.Label(head, text=title.upper(), style="Heading.TLabel", cursor="hand2")
        lab.pack(side="left", padx=(4, 0))
        lab.bind("<Button-1>", lambda e: self.toggle())
        self.body = ttk.Frame(self, style="Surface.TFrame", padding=(12, 2, 10, 8))
        self.body.columnconfigure(1, weight=1)
        if expanded:
            self.body.pack(fill="x")
        self.row = 0

    def toggle(self):
        self.expanded = not self.expanded
        self.chev.icon = "chevron_down" if self.expanded else "chevron_right"
        self.chev.draw()
        if self.expanded:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()
        if self.on_toggle:
            self.on_toggle(self.expanded)

    def add_row(self, label, widget, hint=""):
        if label:
            ttk.Label(self.body, text=label, style="Muted.TLabel").grid(row=self.row, column=0, sticky="w",
                                                                         padx=(0, 10), pady=2)
        widget.grid(row=self.row, column=1, sticky="ew", pady=2)
        if hint:
            Tooltip(widget, hint)
        self.row += 1
        return widget

    def add_full(self, widget, pady=2):
        widget.grid(row=self.row, column=0, columnspan=2, sticky="ew", pady=pady)
        self.row += 1
        return widget


class ScrollFrame(ttk.Frame):
    """Vertically scrollable frame (inspector, long forms)."""

    def __init__(self, master, style="Surface.TFrame"):
        super().__init__(master, style=style)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style=style)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self._bind_wheel(True))
            w.bind("<Leave>", lambda e: self._bind_wheel(False))
        th.subscribe(self._retheme)
        self._retheme(current_theme())

    def _retheme(self, t):
        if t is not None:
            try:
                self.canvas.configure(bg=t.ui["surface"])
            except tk.TclError:
                pass

    def _sync(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _bind_wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._wheel)
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))
        else:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


class SearchEntry(ttk.Frame):
    """Entry with a search icon and placeholder text."""

    def __init__(self, master, placeholder="Search", on_change=None, on_enter=None):
        super().__init__(master, style="Surface.TFrame")
        self.var = tk.StringVar()
        self.placeholder = placeholder
        self.entry = ttk.Entry(self, textvariable=self.var, style="Search.TEntry")
        self.entry.pack(fill="x", expand=True)
        self._ph = True
        self._show_ph()
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", lambda e: self._show_ph())
        self.entry.bind("<Escape>", lambda e: self.clear())
        if on_enter:
            self.entry.bind("<Return>", lambda e: on_enter(self.get()))
        self.on_change = on_change
        self.var.trace_add("write", lambda *a: (not self._ph and self.on_change and self.on_change(self.get())))

    def _show_ph(self):
        if not self.var.get():
            self._ph = True
            self.entry.configure(foreground=current_theme().ui["faint"] if current_theme() else "gray")
            self.var.set(self.placeholder)

    def _focus_in(self, _e):
        if self._ph:
            self._ph = False
            self.var.set("")
            self.entry.configure(foreground=current_theme().ui["text"] if current_theme() else "black")

    def get(self) -> str:
        return "" if self._ph else self.var.get()

    def clear(self):
        if not self._ph:
            self.var.set("")

    def focus(self):
        self.entry.focus_set()


# ================================================================ notifications
class ToastHost:
    """Non-intrusive notifications in the bottom-right corner of a widget."""

    def __init__(self, parent):
        self.parent = parent
        self.items = []

    def show(self, text, kind="info", ms=3500):
        t = current_theme()
        if t is None:
            return
        u = t.ui
        color = {"info": u["info"], "success": u["success"], "warning": u["warning"], "error": u["danger"]}.get(
            kind, u["info"])
        f = tk.Frame(self.parent, bg=u["border_strong"], bd=0, highlightthickness=0)
        inner = tk.Frame(f, bg=u["surface"], bd=0)
        inner.pack(padx=1, pady=1)
        bar = tk.Frame(inner, bg=color, width=4)
        bar.pack(side="left", fill="y")
        tk.Label(inner, text=text, bg=u["surface"], fg=u["text"], font=t.fonts["ui"], padx=12, pady=8,
                 justify="left", wraplength=int(360 * th.dpi_factor(self.parent))).pack(side="left")
        self.items.append(f)
        while len(self.items) > 3:
            self._remove(self.items[0])
        self._layout()
        self.parent.after(ms, lambda: self._remove(f))

    def clear(self):
        for f in list(self.items):
            self._remove(f)

    def _remove(self, f):
        if f in self.items:
            self.items.remove(f)
        try:
            f.destroy()
        except tk.TclError:
            pass
        self._layout()

    def _layout(self):
        y = -12
        for f in reversed(self.items):
            try:
                f.place(relx=1.0, rely=1.0, x=-14, y=y, anchor="se")
                f.update_idletasks()
                y -= f.winfo_reqheight() + 8
            except tk.TclError:
                pass


def make_menu(master, tearoff=0) -> tk.Menu:
    m = tk.Menu(master, tearoff=tearoff)
    t = current_theme()
    if t is not None:
        th.recolor_menu(m, t)
    return m
