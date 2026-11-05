"""Drawing frames, reference zones, title blocks and revision tables.

Everything is laid out in *paper* units (0.25 mm) and then scaled by the
sheet's presentation scale into model units, so a sheet printed at 1:2 has a
frame twice as large around the drawing and prints at the paper size.

Title-block styles:
  standard - two-row block: organisation/title, then drawn/checked/approved,
             date, drawing number, revision and sheet; revision table above.
  compact  - a single row, for small sheets.
  iso      - layout modelled on ISO 7200 (180 mm wide, identification
             zone at the right), with a revision table above.
  none     - frame and zones only.
"""
from __future__ import annotations

from .geometry import UNIT_MM

MARGIN = 40          # 10 mm from the paper edge to the frame
ZONE_BAND = 20       # 5 mm band for zone references
THICK, THIN = 2.2, 1.0
CAPTION = 5.5        # 1.4 mm captions
VALUE = 10           # 2.5 mm values
REV_ROWS = 4


def _zone_counts(pw, ph):
    # About 50 mm per zone, even counts (ISO 5457 practice).
    cols = max(2, int(round(pw * UNIT_MM / 50 / 2)) * 2)
    rows = max(2, int(round(ph * UNIT_MM / 50 / 2)) * 2)
    return cols, rows


def zone_letter(i: int) -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"   # I and O are not used
    return letters[i] if i < len(letters) else letters[i // len(letters) - 1] + letters[i % len(letters)]


def _tb_size(style):
    """Title block (width, height) in paper units."""
    if style == "standard":
        return (720, 80)
    if style == "compact":
        return (720, 44)
    if style == "iso":
        return (720, 108)
    return (0, 0)


def frame_layout(doc) -> dict:
    """Geometry of the frame in model units."""
    s = doc.sheet
    pw, ph = s.paper_units()
    k = 1.0 / s.scale_factor()   # model units per paper unit
    m = MARGIN
    band = ZONE_BAND if s.zones else 0
    inner = (m + band, m + band, pw - m - band, ph - m - band)
    style = s.title_block if s.show_title_block else "none"
    tw, th = _tb_size(style)
    tw = min(tw, inner[2] - inner[0])
    tb = (inner[2] - tw, inner[3] - th, inner[2], inner[3]) if tw else None
    rev_h = 0
    if style in ("standard", "iso"):
        rev_h = 12 * (REV_ROWS + 1)
    drawable = (inner[0], inner[1], inner[2], inner[3] - (th + rev_h if tb else 0))
    cols, rows = _zone_counts(pw - 2 * m, ph - 2 * m)

    def sc(b):
        return None if b is None else tuple(v * k for v in b)
    return {"paper": (0, 0, pw * k, ph * k), "frame": sc((m, m, pw - m, ph - m)), "inner": sc(inner),
            "title_block": sc(tb), "drawable": sc(drawable), "k": k, "style": style,
            "zones": (cols, rows) if s.zones else None, "rev_h": rev_h * k,
            "paper_units": (pw, ph)}


def zone_of(doc, p) -> str:
    """Grid reference ("C4") of model point p, or "" without zones."""
    lay = frame_layout(doc)
    if not lay["zones"]:
        return ""
    cols, rows = lay["zones"]
    x0, y0, x1, y1 = lay["frame"]
    cx = int((p[0] - x0) / ((x1 - x0) / cols))
    cy = int((p[1] - y0) / ((y1 - y0) / rows))
    cx, cy = max(0, min(cols - 1, cx)), max(0, min(rows - 1, cy))
    return f"{zone_letter(cy)}{cx + 1}"


def field_values(doc, project=None) -> dict:
    """Resolve title-block fields: a sheet's own value wins, otherwise the
    project metadata."""
    s = doc.sheet
    meta = project.meta if project is not None else {}

    def pick(sheet_val, key):
        return sheet_val or meta.get(key, "")
    sheet_no = project.sheet_number_text(doc) if project is not None and doc in project.sheets else (s.sheet or "1 / 1")
    return {
        "organisation": pick(s.organisation, "organisation"),
        "title": s.title or meta.get("title", ""),
        "subtitle": (doc.name if not s.title and meta.get("title") and doc.name and not doc.name.startswith("Sheet ")
                     else (s.description or "")),
        "project_title": meta.get("title", ""),
        "project_number": meta.get("number", ""),
        "client": meta.get("client", ""),
        "author": pick(s.author, "author"),
        "checked_by": pick(s.checked_by, "checked_by"),
        "approved_by": pick(s.approved_by, "approved_by"),
        "date": pick(s.date, "date"),
        "drawing_number": s.drawing_number or (f"{meta.get('number')}-{project.sheet_number(doc):02d}"
                                               if project is not None and meta.get("number") and doc in project.sheets
                                               else ""),
        "revision": pick(s.revision, "revision"),
        "sheet": sheet_no,
        "scale": s.scale,
        "size": s.size if s.size != "Custom" else f"{s.custom_w:g}×{s.custom_h:g} mm",
    }


def revision_rows(project) -> list:
    if project is None or project.revisions is None:
        return []
    rows = []
    for e in project.revisions.approved()[-REV_ROWS:]:
        rows.append((e.get("label", ""), e.get("description", ""), e.get("timestamp", "")[:10],
                     e.get("author", ""), e.get("approved_by", "")))
    return rows


def frame_prims(doc, project=None) -> list:
    """Frame, zone markers, title block and revision table, in model units."""
    lay = frame_layout(doc)
    k = lay["k"]
    pw, ph = lay["paper_units"]
    out = []

    def ln(a, b, c, d, w=THIN):
        out.append({"k": "line", "pts": [(a * k, b * k), (c * k, d * k)], "role": "frame", "item": None,
                    "wpx": w, "dash": False, "fill": False})

    def box(a, b, c, d, w=THIN):
        out.append({"k": "poly", "pts": [(a * k, b * k), (c * k, b * k), (c * k, d * k), (a * k, d * k)],
                    "role": "frame", "item": None, "wpx": w, "dash": False, "fill": False})

    def txt(x, y, s, size=VALUE, anchor="nw", bold=False):
        if s:
            out.append({"k": "text", "p": (x * k, y * k), "s": str(s), "size": size * k, "anchor": anchor,
                        "role": "frame", "item": None, "bold": bold})

    m = MARGIN
    box(m, m, pw - m, ph - m, THICK)
    if lay["zones"]:
        cols, rows = lay["zones"]
        b = ZONE_BAND
        box(m + b, m + b, pw - m - b, ph - m - b, THIN)
        zw, zh = (pw - 2 * m) / cols, (ph - 2 * m) / rows
        for i in range(1, cols):
            x = m + i * zw
            ln(x, m, x, m + b)
            ln(x, ph - m - b, x, ph - m)
        for i in range(1, rows):
            y = m + i * zh
            ln(m, y, m + b, y)
            ln(pw - m - b, y, pw - m, y)
        for i in range(cols):
            x = m + (i + 0.5) * zw
            txt(x, m + b / 2, str(i + 1), 8, "c")
            txt(x, ph - m - b / 2, str(i + 1), 8, "c")
        for i in range(rows):
            y = m + (i + 0.5) * zh
            txt(m + b / 2, y, zone_letter(i), 8, "c")
            txt(pw - m - b / 2, y, zone_letter(i), 8, "c")
    tb = lay["title_block"]
    style = lay["style"]
    if not tb:
        return out
    x0, y0, x1, y1 = (v / k for v in tb)
    f = field_values(doc, project)
    tw = x1 - x0
    sc = tw / 720.0

    def cell(x, y, w, h, caption, value, size=VALUE, bold=False):
        txt(x + 3, y + 3, caption, CAPTION)
        if value:
            # shrink long values to fit the cell
            est = size * 0.6 * len(str(value))
            if est > w - 8:
                size = max(5.0, size * (w - 8) / est)
            txt(x + 4, y + h - 4, value, size, "sw", bold)

    box(x0, y0, x1, y1, THICK)
    if style == "standard":
        r1 = 44
        ln(x0, y0 + r1, x1, y0 + r1)
        ca = x0 + 240 * sc
        ln(ca, y0, ca, y0 + r1)
        cell(x0, y0, 240 * sc, r1, "ORGANISATION", f["organisation"])
        title = f["title"] + (f" — {f['subtitle']}" if f["subtitle"] else "")
        cell(ca, y0, x1 - ca, r1, "TITLE", title, 13, True)
        cols = [("DRAWN", f["author"], 95), ("CHECKED", f["checked_by"], 95), ("APPROVED", f["approved_by"], 95),
                ("DATE", f["date"], 100), ("DRAWING NO.", f["drawing_number"], 145), ("SCALE", f["scale"], 60),
                ("REV", f["revision"], 45), ("SHEET", f["sheet"], 85)]
        x = x0
        for i, (cap, val, wdt) in enumerate(cols):
            if i:
                ln(x, y0 + r1, x, y1)
            cell(x, y0 + r1, wdt * sc, y1 - y0 - r1, cap, val)
            x += wdt * sc
    elif style == "compact":
        cols = [("TITLE", f["title"], 250), ("DRAWING NO.", f["drawing_number"], 160), ("DRAWN", f["author"], 90),
                ("DATE", f["date"], 90), ("REV", f["revision"], 50), ("SHEET", f["sheet"], 80)]
        x = x0
        for i, (cap, val, wdt) in enumerate(cols):
            if i:
                ln(x, y0, x, y1)
            cell(x, y0, wdt * sc, y1 - y0, cap, val, 10, i == 0)
            x += wdt * sc
    elif style == "iso":
        # left: responsible / creator / approver ; right: identification zone
        h3 = (y1 - y0) / 3
        lw = 300 * sc
        ln(x0 + lw, y0, x0 + lw, y1)
        for i in (1, 2):
            ln(x0, y0 + i * h3, x0 + lw, y0 + i * h3)
        cell(x0, y0, lw, h3, "LEGAL OWNER", f["organisation"])
        cell(x0, y0 + h3, lw / 2, h3, "CREATED BY", f["author"])
        ln(x0 + lw / 2, y0 + h3, x0 + lw / 2, y1)
        cell(x0 + lw / 2, y0 + h3, lw / 2, h3, "APPROVED BY", f["approved_by"])
        cell(x0, y0 + 2 * h3, lw / 2, h3, "DOCUMENT TYPE", "Schematic")
        cell(x0 + lw / 2, y0 + 2 * h3, lw / 2, h3, "SCALE", f["scale"])
        xr = x0 + lw
        ln(xr, y0 + 2 * h3, x1, y0 + 2 * h3)
        cell(xr, y0, x1 - xr, 2 * h3, "TITLE", f["title"] + (f" — {f['subtitle']}" if f["subtitle"] else ""), 13, True)
        wid = x1 - xr
        parts = [("IDENTIFICATION NO.", f["drawing_number"], 0.45), ("REV", f["revision"], 0.12),
                 ("DATE OF ISSUE", f["date"], 0.23), ("SHEET", f["sheet"], 0.20)]
        x = xr
        for i, (cap, val, frac) in enumerate(parts):
            if i:
                ln(x, y0 + 2 * h3, x, y1)
            cell(x, y0 + 2 * h3, wid * frac, h3, cap, val)
            x += wid * frac
    if style in ("standard", "iso"):
        rows = revision_rows(project)
        rh = 12
        ry1 = y0
        ry0 = y0 - rh * (REV_ROWS + 1)
        box(x0, ry0, x1, ry1)
        widths = [("REV", 50), ("DESCRIPTION", 380), ("DATE", 110), ("BY", 90), ("APPR.", 90)]
        x = x0
        xs = []
        for i, (cap, wdt) in enumerate(widths):
            xs.append(x)
            if i:
                ln(x, ry0, x, ry1)
            txt(x + 3, ry1 - rh + 3, cap, CAPTION)
            x += wdt * sc
        ln(x0, ry1 - rh, x1, ry1 - rh)
        for r in range(1, REV_ROWS):
            ln(x0, ry1 - rh * (r + 1), x1, ry1 - rh * (r + 1))
        # newest revision directly above the header, older ones further up
        for r, row in enumerate(reversed(rows)):
            yb = ry1 - rh * (r + 1)
            for i, val in enumerate(row):
                w = widths[i][1] * sc
                s = str(val)
                maxc = int((w - 6) / (7 * 0.6))
                if len(s) > maxc:
                    s = s[:max(1, maxc - 1)] + "…"
                txt(xs[i] + 3, yb - 2.5, s, 7, "sw")
    return out
