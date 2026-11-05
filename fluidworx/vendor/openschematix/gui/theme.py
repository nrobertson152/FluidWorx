"""Design system: colour themes, typography, spacing and ttk styling.

All colours used by the interface come from the token tables below; widgets
never hard-code colours. Interface colours (``ui``) and drawing-canvas
colours (``canvas``) are separate, so the canvas can use a different scheme
from the interface (Preferences ▸ Canvas colours).

Switching themes recolours everything in place: ttk styles are reconfigured,
every classic Tk widget in the window tree (menus, canvases, text boxes,
list boxes, toplevels) is walked and recoloured, and widgets that draw their
own content (icon buttons, canvases) are notified through ``subscribe``.
Menus are never destroyed or replaced, which is what made the menubar vanish
in earlier builds.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont, ttk

# ---------------------------------------------------------------- spacing scale
XS, S, M, L, XL = 2, 4, 8, 12, 16

# ---------------------------------------------------------------- canvas palettes
_CANVAS_PAPER = {
    "desk": "#e4e7eb", "paper": "#ffffff", "paper_shadow": "#cdd2d8", "ink": "#14181d", "wire": "#0b4f9c",
    "frame": "#5d6670", "grid": "#eef1f4", "grid_major": "#dfe3e8", "select": "#e8590c", "junction": "#0b4f9c",
    "open_end": "#d6336c", "open_term": "#c2255c", "ghost": "#1f6feb", "band": "#1f6feb", "band_cross": "#2f9e44",
    "hover": "#2f9e44", "snap": "#e8590c", "pin": "#5d6670", "wirenum": "#2b6cb0", "xref": "#7048e8",
    "shape": "#14181d", "crosshair": "#8a939d",
    "diff_added": "#2b8a3e", "diff_removed": "#e03131", "diff_modified": "#e8590c", "diff_same": "#adb5bd",
}
_CANVAS_DARK = {
    "desk": "#15171a", "paper": "#1d2024", "paper_shadow": "#0b0c0e", "ink": "#e6e8eb", "wire": "#6cb2ff",
    "frame": "#7d8792", "grid": "#23272c", "grid_major": "#2d3238", "select": "#ff922b", "junction": "#6cb2ff",
    "open_end": "#ff6b9a", "open_term": "#ff6b9a", "ghost": "#4c8dff", "band": "#4c8dff", "band_cross": "#51cf66",
    "hover": "#51cf66", "snap": "#ffa94d", "pin": "#9aa3ad", "wirenum": "#74c0fc", "xref": "#b197fc",
    "shape": "#e6e8eb", "crosshair": "#5c6670",
    "diff_added": "#51cf66", "diff_removed": "#ff6b6b", "diff_modified": "#ffa94d", "diff_same": "#495057",
}
_CANVAS_BLUEPRINT = {
    "desk": "#0a2a4f", "paper": "#0f3a6b", "paper_shadow": "#071d36", "ink": "#e9f2ff", "wire": "#ffffff",
    "frame": "#9cc4f2", "grid": "#164477", "grid_major": "#1d5291", "select": "#ffd43b", "junction": "#ffffff",
    "open_end": "#ff8787", "open_term": "#ff8787", "ghost": "#a5d8ff", "band": "#a5d8ff", "band_cross": "#b2f2bb",
    "hover": "#b2f2bb", "snap": "#ffd43b", "pin": "#9cc4f2", "wirenum": "#d0ebff", "xref": "#e5dbff",
    "shape": "#e9f2ff", "crosshair": "#5f8fc4",
    "diff_added": "#8ce99a", "diff_removed": "#ffa8a8", "diff_modified": "#ffd43b", "diff_same": "#5f8fc4",
}
_CANVAS_HC = {
    "desk": "#000000", "paper": "#000000", "paper_shadow": "#000000", "ink": "#ffffff", "wire": "#00ffff",
    "frame": "#ffffff", "grid": "#262626", "grid_major": "#404040", "select": "#ffff00", "junction": "#00ffff",
    "open_end": "#ff00ff", "open_term": "#ff00ff", "ghost": "#00ff00", "band": "#ffff00", "band_cross": "#00ff00",
    "hover": "#00ff00", "snap": "#ffff00", "pin": "#ffffff", "wirenum": "#00ffff", "xref": "#ff80ff",
    "shape": "#ffffff", "crosshair": "#ffffff",
    "diff_added": "#00ff00", "diff_removed": "#ff4040", "diff_modified": "#ffff00", "diff_same": "#808080",
}
CANVAS_THEMES = {"paper": ("White paper", _CANVAS_PAPER), "dark": ("Dark", _CANVAS_DARK),
                 "blueprint": ("Blueprint", _CANVAS_BLUEPRINT), "high_contrast": ("High contrast", _CANVAS_HC)}

# ---------------------------------------------------------------- interface palettes
THEMES = {
    "modern_light": {
        "label": "Modern Light", "dark": False, "canvas": "paper",
        "ui": {"bg": "#f3f4f6", "surface": "#ffffff", "surface2": "#f7f8fa", "border": "#dcdfe4",
               "border_strong": "#c3c8cf", "text": "#1b1f24", "muted": "#626b75", "faint": "#8a929b",
               "accent": "#2563eb", "accent_text": "#ffffff", "accent_soft": "#e0eaff", "hover": "#eceef1",
               "pressed": "#dfe3e8", "input": "#ffffff", "select_bg": "#dbe6ff", "select_fg": "#10244d",
               "tooltip_bg": "#1f2329", "tooltip_fg": "#f5f6f8", "danger": "#d9364f", "warning": "#c27803",
               "success": "#1f8a46", "info": "#2563eb", "focus": "#2563eb", "toolbar": "#ffffff",
               "status": "#f7f8fa", "tab_active": "#ffffff", "tab_inactive": "#eceef1"},
    },
    "modern_dark": {
        "label": "Modern Dark", "dark": True, "canvas": "dark",
        "ui": {"bg": "#16181c", "surface": "#1e2126", "surface2": "#23272d", "border": "#2e333a",
               "border_strong": "#3b4149", "text": "#e6e8eb", "muted": "#9aa3ad", "faint": "#6c757f",
               "accent": "#4c8dff", "accent_text": "#ffffff", "accent_soft": "#1f3355", "hover": "#2a2f36",
               "pressed": "#343a42", "input": "#14161a", "select_bg": "#24406e", "select_fg": "#ffffff",
               "tooltip_bg": "#f1f3f5", "tooltip_fg": "#1b1f24", "danger": "#ff6b81", "warning": "#f5b649",
               "success": "#51cf66", "info": "#74a7ff", "focus": "#4c8dff", "toolbar": "#1e2126",
               "status": "#1a1d21", "tab_active": "#1e2126", "tab_inactive": "#16181c"},
    },
    "graphite": {
        "label": "Graphite", "dark": True, "canvas": "dark",
        "ui": {"bg": "#2b2d30", "surface": "#323538", "surface2": "#383b3f", "border": "#45494e",
               "border_strong": "#55595f", "text": "#e3e3e3", "muted": "#a7abb0", "faint": "#7d8186",
               "accent": "#e8a33d", "accent_text": "#1c1c1c", "accent_soft": "#4a3f2c", "hover": "#3d4044",
               "pressed": "#474a4f", "input": "#26282b", "select_bg": "#5a4a2e", "select_fg": "#ffffff",
               "tooltip_bg": "#f1f1f1", "tooltip_fg": "#1c1c1c", "danger": "#ff7b72", "warning": "#e8a33d",
               "success": "#7ee787", "info": "#79c0ff", "focus": "#e8a33d", "toolbar": "#323538",
               "status": "#2b2d30", "tab_active": "#323538", "tab_inactive": "#2b2d30"},
    },
    "neutral_gray": {
        "label": "Neutral Gray", "dark": False, "canvas": "paper",
        "ui": {"bg": "#d9dbde", "surface": "#e8e9eb", "surface2": "#e1e3e5", "border": "#c2c5ca",
               "border_strong": "#a9adb3", "text": "#1d2023", "muted": "#555b62", "faint": "#7b8188",
               "accent": "#3b6ea8", "accent_text": "#ffffff", "accent_soft": "#cfdcec", "hover": "#d4d7da",
               "pressed": "#c9ccd0", "input": "#f4f5f6", "select_bg": "#c3d5ea", "select_fg": "#10233a",
               "tooltip_bg": "#25282c", "tooltip_fg": "#f2f2f2", "danger": "#c0392b", "warning": "#a46a00",
               "success": "#25803d", "info": "#3b6ea8", "focus": "#3b6ea8", "toolbar": "#e8e9eb",
               "status": "#e1e3e5", "tab_active": "#e8e9eb", "tab_inactive": "#d4d7da"},
    },
    "blueprint": {
        "label": "Blueprint", "dark": True, "canvas": "blueprint",
        "ui": {"bg": "#0b2140", "surface": "#0f2a52", "surface2": "#13325f", "border": "#1f4478",
               "border_strong": "#2a5591", "text": "#e6f0ff", "muted": "#9fb9dc", "faint": "#6f8fbb",
               "accent": "#5ab0ff", "accent_text": "#06203f", "accent_soft": "#173f72", "hover": "#16386a",
               "pressed": "#1d4580", "input": "#0a1d38", "select_bg": "#1f4e8f", "select_fg": "#ffffff",
               "tooltip_bg": "#e6f0ff", "tooltip_fg": "#06203f", "danger": "#ff8a8a", "warning": "#ffd166",
               "success": "#7ee2a8", "info": "#5ab0ff", "focus": "#5ab0ff", "toolbar": "#0f2a52",
               "status": "#0b2140", "tab_active": "#0f2a52", "tab_inactive": "#0b2140"},
    },
    "high_contrast": {
        "label": "High Contrast", "dark": True, "canvas": "high_contrast",
        "ui": {"bg": "#000000", "surface": "#000000", "surface2": "#0d0d0d", "border": "#ffffff",
               "border_strong": "#ffffff", "text": "#ffffff", "muted": "#ffffff", "faint": "#d0d0d0",
               "accent": "#ffff00", "accent_text": "#000000", "accent_soft": "#333300", "hover": "#1f1f1f",
               "pressed": "#333333", "input": "#000000", "select_bg": "#ffff00", "select_fg": "#000000",
               "tooltip_bg": "#ffff00", "tooltip_fg": "#000000", "danger": "#ff4040", "warning": "#ffff00",
               "success": "#00ff00", "info": "#00ffff", "focus": "#ffff00", "toolbar": "#000000",
               "status": "#000000", "tab_active": "#000000", "tab_inactive": "#0d0d0d"},
    },
}
DEFAULT_THEME = "modern_light"


class Theme:
    """Resolved theme: interface tokens + canvas tokens + fonts."""

    def __init__(self, name: str, canvas: str = "auto"):
        if name not in THEMES:
            name = DEFAULT_THEME
        t = THEMES[name]
        self.name = name
        self.label = t["label"]
        self.dark = t["dark"]
        self.ui = dict(t["ui"])
        cname = t["canvas"] if canvas in ("auto", "", None) or canvas not in CANVAS_THEMES else canvas
        self.canvas_name = cname
        self.canvas = dict(CANVAS_THEMES[cname][1])
        self.fonts = {}

    def __getitem__(self, k):
        """Canvas colour lookup (used by the drawing code)."""
        if k in self.canvas:
            return self.canvas[k]
        return self.ui[k]

    def get(self, k, default=None):
        try:
            return self[k]
        except KeyError:
            return default


def _pick(root, prefs, fallback):
    fams = {f.lower(): f for f in tkfont.families(root)}
    for f in prefs:
        if f.lower() in fams:
            return fams[f.lower()]
    try:
        return tkfont.nametofont(fallback).actual("family")
    except tk.TclError:
        return "helvetica"


def ui_font_family(root) -> str:
    return _pick(root, ("Segoe UI Variable Text", "Segoe UI", "Inter", "Cantarell", "Ubuntu", "Noto Sans",
                        "Open Sans", "DejaVu Sans", "Liberation Sans", "Helvetica", "Arial", "FreeSans",
                        "Latin Modern Sans"), "TkDefaultFont")


def mono_font_family(root) -> str:
    return _pick(root, ("Cascadia Mono", "Consolas", "JetBrains Mono", "Ubuntu Mono", "Noto Sans Mono",
                        "DejaVu Sans Mono", "Liberation Mono", "Courier New", "Courier"), "TkFixedFont")


def canvas_font_family(root) -> str:
    return _pick(root, ("Arial", "Liberation Sans", "Helvetica", "Nimbus Sans", "DejaVu Sans", "FreeSans"),
                 "TkDefaultFont")


def base_size() -> int:
    return 9 if sys.platform.startswith("win") else 10


_subscribers = []


def subscribe(fn):
    """Register fn(theme) to be called after every theme change."""
    _subscribers.append(fn)
    return fn


def unsubscribe(fn):
    try:
        _subscribers.remove(fn)
    except ValueError:
        pass


def apply(root: tk.Tk, theme: Theme):
    """Apply a theme to the whole application, in place."""
    st = ttk.Style(root)
    try:
        if st.theme_use() != "clam":
            st.theme_use("clam")
    except tk.TclError:
        pass
    fam = ui_font_family(root)
    mono = mono_font_family(root)
    size = base_size()
    theme.fonts = {"ui": (fam, size), "small": (fam, size - 1), "bold": (fam, size, "bold"),
                   "heading": (fam, size - 1, "bold"), "title": (fam, size + 3, "bold"),
                   "large": (fam, size + 1), "mono": (mono, size), "family": fam, "mono_family": mono}
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                 "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=size if name != "TkSmallCaptionFont" else size - 1)
        except tk.TclError:
            pass
    try:
        tkfont.nametofont("TkFixedFont").configure(family=mono, size=size)
    except tk.TclError:
        pass
    u = theme.ui
    root.configure(bg=u["bg"])
    st.configure(".", background=u["bg"], foreground=u["text"], fieldbackground=u["input"],
                 bordercolor=u["border"], lightcolor=u["surface"], darkcolor=u["border"], troughcolor=u["surface2"],
                 focuscolor=u["focus"], selectbackground=u["select_bg"], selectforeground=u["select_fg"],
                 insertcolor=u["text"], arrowcolor=u["muted"], font=theme.fonts["ui"])
    st.map(".", foreground=[("disabled", u["faint"])])
    # frames and surfaces
    for name, bgk in (("TFrame", "bg"), ("Surface.TFrame", "surface"), ("Raised.TFrame", "surface2"),
                      ("Toolbar.TFrame", "toolbar"), ("Status.TFrame", "status"), ("Panel.TFrame", "surface")):
        st.configure(name, background=u[bgk])
    st.configure("Card.TFrame", background=u["surface"], bordercolor=u["border"], relief="solid", borderwidth=1)
    # labels
    for name, bgk, fgk, fnt in (("TLabel", "bg", "text", "ui"), ("Surface.TLabel", "surface", "text", "ui"),
                                ("Panel.TLabel", "surface", "text", "ui"),
                                ("Muted.TLabel", "surface", "muted", "small"),
                                ("Faint.TLabel", "surface", "faint", "small"),
                                ("Heading.TLabel", "surface", "muted", "heading"),
                                ("Title.TLabel", "surface", "text", "title"),
                                ("Bold.TLabel", "surface", "text", "bold"),
                                ("Status.TLabel", "status", "muted", "small"),
                                ("StatusStrong.TLabel", "status", "text", "small"),
                                ("Toolbar.TLabel", "toolbar", "muted", "small"),
                                ("Prompt.TLabel", "surface", "accent", "mono"),
                                ("Danger.TLabel", "surface", "danger", "small"),
                                ("Warning.TLabel", "surface", "warning", "small"),
                                ("Success.TLabel", "surface", "success", "small")):
        st.configure(name, background=u[bgk], foreground=u[fgk], font=theme.fonts[fnt])
    # buttons
    st.configure("TButton", background=u["surface2"], foreground=u["text"], bordercolor=u["border"],
                 lightcolor=u["surface2"], darkcolor=u["surface2"], padding=(10, 4), relief="flat",
                 focusthickness=1, focuscolor=u["focus"])
    st.map("TButton", background=[("disabled", u["surface2"]), ("pressed", u["pressed"]), ("active", u["hover"])],
           bordercolor=[("focus", u["focus"])], foreground=[("disabled", u["faint"])])
    st.configure("Accent.TButton", background=u["accent"], foreground=u["accent_text"], bordercolor=u["accent"],
                 lightcolor=u["accent"], darkcolor=u["accent"])
    st.map("Accent.TButton", background=[("pressed", u["accent"]), ("active", u["accent"])],
           foreground=[("disabled", u["faint"])])
    st.configure("Flat.TButton", background=u["surface"], bordercolor=u["surface"], lightcolor=u["surface"],
                 darkcolor=u["surface"], padding=(6, 2))
    st.map("Flat.TButton", background=[("pressed", u["pressed"]), ("active", u["hover"])])
    st.configure("Link.TButton", background=u["surface"], foreground=u["accent"], bordercolor=u["surface"],
                 lightcolor=u["surface"], darkcolor=u["surface"], padding=(2, 1))
    st.map("Link.TButton", background=[("active", u["surface"])], foreground=[("active", u["focus"])])
    # inputs
    st.configure("TEntry", fieldbackground=u["input"], foreground=u["text"], bordercolor=u["border"],
                 lightcolor=u["input"], darkcolor=u["input"], padding=(6, 3), insertcolor=u["text"])
    st.map("TEntry", bordercolor=[("focus", u["focus"])], lightcolor=[("focus", u["focus"])],
           fieldbackground=[("readonly", u["surface2"]), ("disabled", u["surface2"])])
    st.configure("Command.TEntry", fieldbackground=u["input"], foreground=u["text"], bordercolor=u["border"],
                 padding=(6, 4), font=theme.fonts["mono"])
    st.configure("Search.TEntry", padding=(6, 4))
    st.configure("TCombobox", fieldbackground=u["input"], foreground=u["text"], background=u["surface2"],
                 arrowcolor=u["muted"], bordercolor=u["border"], lightcolor=u["input"], darkcolor=u["input"],
                 padding=(5, 3))
    st.map("TCombobox", fieldbackground=[("readonly", u["input"]), ("disabled", u["surface2"])],
           foreground=[("readonly", u["text"]), ("disabled", u["faint"])],
           selectbackground=[("readonly", u["input"])], selectforeground=[("readonly", u["text"])],
           bordercolor=[("focus", u["focus"])], background=[("active", u["hover"])])
    st.configure("TSpinbox", fieldbackground=u["input"], foreground=u["text"], background=u["surface2"],
                 arrowcolor=u["muted"], bordercolor=u["border"], lightcolor=u["input"], darkcolor=u["input"],
                 padding=(5, 3))
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=u["surface"], foreground=u["text"], indicatorbackground=u["input"],
                     indicatorforeground=u["accent"], bordercolor=u["border_strong"], upperbordercolor=u["border_strong"],
                     lowerbordercolor=u["border_strong"], focuscolor=u["surface"])
        st.map(w, background=[("active", u["surface"])],
               indicatorbackground=[("selected", u["accent"]), ("active", u["hover"])],
               indicatorforeground=[("selected", u["accent_text"])])
    # notebooks (sidebar / dock tabs)
    st.configure("TNotebook", background=u["surface"], bordercolor=u["border"], tabmargins=(0, 0, 0, 0),
                 lightcolor=u["surface"], darkcolor=u["surface"])
    st.configure("TNotebook.Tab", background=u["tab_inactive"], foreground=u["muted"], padding=(12, 5),
                 bordercolor=u["border"], lightcolor=u["tab_inactive"], darkcolor=u["tab_inactive"],
                 font=theme.fonts["ui"])
    st.map("TNotebook.Tab", background=[("selected", u["tab_active"]), ("active", u["hover"])],
           foreground=[("selected", u["text"])], lightcolor=[("selected", u["tab_active"])],
           expand=[("selected", (0, 0, 0, 0))])
    # tree / lists
    rh = int(tkfont.Font(root=root, family=fam, size=size).metrics("linespace") * 1.65)
    st.configure("Treeview", background=u["surface"], fieldbackground=u["surface"], foreground=u["text"],
                 rowheight=rh, borderwidth=0, bordercolor=u["surface"], lightcolor=u["surface"],
                 darkcolor=u["surface"])
    st.map("Treeview", background=[("selected", u["select_bg"])], foreground=[("selected", u["select_fg"])])
    st.configure("Treeview.Heading", background=u["surface2"], foreground=u["muted"], bordercolor=u["border"],
                 lightcolor=u["surface2"], darkcolor=u["surface2"], relief="flat", padding=(6, 3),
                 font=theme.fonts["heading"])
    st.map("Treeview.Heading", background=[("active", u["hover"])])
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    # separators, panes, scrollbars
    st.configure("TSeparator", background=u["border"])
    st.configure("TPanedwindow", background=u["border"])
    st.configure("Sash", sashthickness=4, gripcount=0, background=u["border"], lightcolor=u["border"],
                 bordercolor=u["border"])
    for orient in ("Vertical", "Horizontal"):
        st.configure(f"{orient}.TScrollbar", background=u["surface2"], troughcolor=u["surface"],
                     bordercolor=u["surface"], lightcolor=u["surface2"], darkcolor=u["surface2"],
                     arrowcolor=u["muted"], gripcount=0, arrowsize=12)
        st.map(f"{orient}.TScrollbar", background=[("active", u["hover"]), ("pressed", u["pressed"])])
    st.configure("TLabelframe", background=u["surface"], bordercolor=u["border"])
    st.configure("TLabelframe.Label", background=u["surface"], foreground=u["muted"], font=theme.fonts["heading"])
    st.configure("Horizontal.TProgressbar", background=u["accent"], troughcolor=u["surface2"],
                 bordercolor=u["border"])
    # option database for classic widgets created later (menus, listboxes, text)
    root.option_add("*TCombobox*Listbox.background", u["input"])
    root.option_add("*TCombobox*Listbox.foreground", u["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", u["select_bg"])
    root.option_add("*TCombobox*Listbox.selectForeground", u["select_fg"])
    root.option_add("*TCombobox*Listbox.font", theme.fonts["ui"])
    root.option_add("*Menu.background", u["surface"])
    root.option_add("*Menu.foreground", u["text"])
    root.option_add("*Menu.activeBackground", u["select_bg"])
    root.option_add("*Menu.activeForeground", u["select_fg"])
    root.option_add("*Menu.disabledForeground", u["faint"])
    root.option_add("*Menu.selectColor", u["accent"])
    root.option_add("*Menu.relief", "flat")
    root.option_add("*Menu.borderWidth", 1)
    root.option_add("*Menu.activeBorderWidth", 0)
    root.option_add("*Menu.font", theme.fonts["ui"])
    root.option_add("*Listbox.background", u["surface"])
    root.option_add("*Listbox.foreground", u["text"])
    root.option_add("*Listbox.selectBackground", u["select_bg"])
    root.option_add("*Listbox.selectForeground", u["select_fg"])
    root.option_add("*Text.background", u["input"])
    root.option_add("*Text.foreground", u["text"])
    recolor_tree(root, theme)
    for fn in list(_subscribers):
        try:
            fn(theme)
        except tk.TclError:
            pass


def recolor_menu(m, theme: Theme, seen=None):
    """Recolour a menu and all of its cascades, in place."""
    u = theme.ui
    seen = set() if seen is None else seen
    if str(m) in seen:
        return
    seen.add(str(m))
    try:
        m.configure(background=u["surface"], foreground=u["text"], activebackground=u["select_bg"],
                    activeforeground=u["select_fg"], disabledforeground=u["faint"], selectcolor=u["accent"],
                    relief="flat", borderwidth=1, activeborderwidth=0, font=theme.fonts.get("ui"))
        end = m.index("end")
    except tk.TclError:
        return
    for i in range(0 if end is None else end + 1):
        try:
            if m.type(i) == "cascade":
                recolor_menu(m.nametowidget(m.entrycget(i, "menu")), theme, seen)
        except (tk.TclError, KeyError):
            pass


# backwards-compatible name used by older code and tests
def recolor_menus(menu, theme):
    recolor_menu(menu, theme if isinstance(theme, Theme) else _legacy(theme))


def _legacy(colors: dict) -> Theme:
    t = Theme(DEFAULT_THEME)
    t.ui.update({"surface": colors.get("panel", t.ui["surface"]), "text": colors.get("text", t.ui["text"])})
    return t


def recolor_tree(widget, theme: Theme):
    """Walk the widget tree and recolour classic (non-ttk) Tk widgets."""
    u = theme.ui
    stack = [widget]
    seen = set()
    while stack:
        w = stack.pop()
        try:
            cls = w.winfo_class()
        except tk.TclError:
            continue
        try:
            if cls == "Menu":
                recolor_menu(w, theme, seen)
            elif cls in ("Toplevel", "Tk"):
                w.configure(bg=u["bg"])
            elif cls == "Listbox":
                w.configure(bg=u["surface"], fg=u["text"], selectbackground=u["select_bg"],
                            selectforeground=u["select_fg"], highlightbackground=u["border"],
                            highlightcolor=u["focus"], font=theme.fonts.get("ui"))
            elif cls == "Text":
                w.configure(bg=u["input"], fg=u["text"], insertbackground=u["text"],
                            selectbackground=u["select_bg"], selectforeground=u["select_fg"],
                            highlightbackground=u["border"], highlightcolor=u["focus"])
            elif cls == "Frame" and getattr(w, "_theme_bg", None):
                w.configure(bg=u[w._theme_bg])
            elif cls == "Label" and getattr(w, "_theme_bg", None):
                w.configure(bg=u[w._theme_bg], fg=u[getattr(w, "_theme_fg", "text")])
        except tk.TclError:
            pass
        try:
            stack.extend(w.winfo_children())
        except tk.TclError:
            pass
        # menubar of a toplevel is not a child in the widget tree on all platforms
        try:
            mb = w.cget("menu") if cls in ("Toplevel", "Tk") else ""
            if mb:
                recolor_menu(w.nametowidget(mb), theme, seen)
        except (tk.TclError, KeyError):
            pass


def set_ui_scale(root, scale: float):
    """Interface scaling for high-DPI displays. 0 = automatic (system DPI)."""
    if scale and scale > 0:
        try:
            root.tk.call("tk", "scaling", scale * 96 / 72)
        except tk.TclError:
            pass


def dpi_factor(root) -> float:
    """Pixels per 'design pixel' (1.0 at 96 dpi)."""
    try:
        return max(1.0, float(root.tk.call("tk", "scaling")) * 72 / 96)
    except (tk.TclError, ValueError):
        return 1.0
