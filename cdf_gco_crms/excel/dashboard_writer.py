"""One-sheet executive dashboard "لوحة المتابعة التنفيذية" (protocol 10.4A; kit 1.1.0, v7.15 draft; spec 5–10).

The sheet is a formula view of the data sheet through the calculation block written on the same sheet from column
R (``helper_writer``). It is read-only except for four selector cells; no response is entered here (10.4A.12).
Every formula is registered with its independently computed expected value (``formula_registry``), so the build
writes cached values for the default view and the verifier compares a LibreOffice recalculation for every view.

Layout (``dash_layout.plan``): twelve grid positions g1..g12 = columns B..M (g1 is the right edge in RTL), column A
and N margins, no frozen panes, 100 % zoom. Zones in order: A identity band, facts, band row, navigation chips and
selectors; B six KPI cards; C closure level (narrative, dark gauge deck, distribution); D the complete action list;
E round analysis (two charts, transition matrix); F the observation table; G the user guide; H one card per
observation; footer. Colours are the tokens of ``design_tokens``; icons are the guide's own (pages 17 and 18).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl.chart import BarChart, DoughnutChart, LineChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.chart.marker import Marker
from openpyxl.chart.series import DataPoint, SeriesLabel
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.comments import Comment
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.text import CharacterProperties, Font as DFont, Paragraph, ParagraphProperties
from openpyxl.formatting.rule import ColorScaleRule, FormulaRule
from openpyxl.styles import Protection
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.pagebreak import Break, RowBreak

from ..analytics.dashboard_analytics import Analytics, View, CARD_TAG, KPI_KEYS
from ..config import design_tokens as T
from ..config import round_schema as S
from ..config import workbook_settings as W
from ..guidance import guidance_dictionary as G
from . import styles as st
from .dash_layout import CARD, CARD_HEIGHT, CARD_STRIDE, GRID0, HELP_ROWS, NGRID, Layout as Plan, gc, L
from .formula_registry import Registry
from .helper_writer import HP, HelperRefs, q, sheet_ref

KIT_ROOT = Path(__file__).resolve().parents[2]
DASH = f"'{W.DASHBOARD_SHEET}'"
COL_PX = int(W.GRID_WIDTH * 7 + 5)          # 96 px per grid column
MARGIN_PX = int(W.MARGIN_WIDTH * 7 + 5)


@dataclass
class DashInfo:
    sections: dict[str, int] = field(default_factory=dict)       # zone -> band row
    last_row: int = 0
    queue_rows: list[int] = field(default_factory=list)
    table_rows: list[int] = field(default_factory=list)
    card_rows: list[int] = field(default_factory=list)
    link_cells: list[str] = field(default_factory=list)          # HYPERLINK formula cells
    nav_cells: list[str] = field(default_factory=list)           # static internal hyperlinks
    charts: list[dict] = field(default_factory=list)
    chart_alts: list[str] = field(default_factory=list)          # in the order openpyxl writes the charts
    image_alts: list[str] = field(default_factory=list)          # then the images
    images: list[dict] = field(default_factory=list)             # {key, file, sha256, row, grid}
    selector_cells: list[str] = field(default_factory=list)
    gauge_groups: list[dict] = field(default_factory=list)        # overlaid charts sharing anchor, size, layout
    notes: list[str] = field(default_factory=list)
    missing_assets: list[str] = field(default_factory=list)       # pictures not provisioned in this checkout
    layout: Plan | None = None


# ------------------------------------------------------------------ cell helpers
def _note(text: str, width: int = 300) -> Comment:
    lines = sum(max(1, len(seg) // 45 + 1) for seg in text.split("\n"))
    c = Comment(text, G.NOTE_AUTHOR)
    c.width = width
    c.height = min(380, 17 * lines + 28)
    return c


def _merge(ws, r1: int, g1: int, r2: int | None = None, g2: int | None = None):
    r2 = r2 or r1
    g2 = g1 if g2 is None else g2
    c1, c2 = gc(g1), gc(g2)
    if (r1, c1) != (r2, c2):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    return ws.cell(row=r1, column=c1)


def _fill_cols(ws, r1, c1, r2, c2, color):
    f = st.fill(color)
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            ws.cell(row=r, column=c).fill = f


def _fill(ws, r1, g1, r2, g2, color):
    _fill_cols(ws, r1, gc(g1), r2, gc(g2), color)


def _box(ws, r1, g1, r2, g2, color=T.CARD_BORDER, style="thin"):
    """Frame a rectangle of grid cells, changing only the sides on its perimeter.

    A border is the shared edge between logical neighbours: a cell's "left" edge touches the previous column,
    which on a right-to-left sheet is its visual right (Excel and LibreOffice mirror the grid with its borders).
    So g1, the visual right edge, takes "left" and g2, the visual left edge, "right"."""
    from openpyxl.styles import Border
    side = st.side(style, color)
    for r in range(r1, r2 + 1):
        for g in range(g1, g2 + 1):
            if not (r in (r1, r2) or g in (g1, g2)):
                continue
            cell = ws.cell(row=r, column=gc(g))
            b = cell.border or Border()
            cell.border = Border(left=side if g == g1 else b.left, right=side if g == g2 else b.right,
                                 top=side if r == r1 else b.top, bottom=side if r == r2 else b.bottom)


def _text(ws, r, g1, g2, value, *, size=T.SZ_BODY, bold=False, color=T.INK, h="right", v="center",
          wrap=True, fill=None, r2=None, underline=None):
    cell = _merge(ws, r, g1, r2, g2)
    cell.value = value
    cell.font = st.font(size, bold=bold, color=color, underline=underline)
    cell.alignment = st.align(h, v, wrap)
    if fill:
        _fill(ws, r, g1, r2 or r, g2, fill)
    return cell


def _formula(ws, reg: Registry, r, g1, g2, formula, expected, *, size=T.SZ_BODY, bold=False, color=T.INK,
             h="right", v="center", wrap=True, fill=None, r2=None, fmt=None, underline=None):
    cell = _merge(ws, r, g1, r2, g2)
    reg.put(ws, cell.coordinate, formula, expected)
    cell.font = st.font(size, bold=bold, color=color, underline=underline)
    cell.alignment = st.align(h, v, wrap)
    if fmt:
        cell.number_format = fmt
    if fill:
        _fill(ws, r, g1, r2 or r, g2, fill)
    return cell


def _status_rules(ws, rng: str, top_left: str, *, size=T.SZ_BODY):
    """D.2 fills with bold Cinder text for the four official values; grey for not raised (G-DASH-10)."""
    for value in S.CLOSURE_VALUES:
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f'{top_left}="{value}"'], fill=st.fill(T.STATUS_FILL[value]),
            font=st.font(size, bold=True, color=T.INK), stopIfTrue=True))
    ws.conditional_formatting.add(rng, FormulaRule(
        formula=[f'OR({top_left}="{S.NOT_RAISED}",{top_left}="{S.PREV_NA}",{top_left}="لم تكن مطروحة")'],
        fill=st.fill(T.NOT_RAISED_FILL), font=st.font(T.SZ_NOTE, color=T.MUTED), stopIfTrue=True))


def _lines(text: str, width_chars: float) -> int:
    if not text:
        return 1
    per = max(6, int(width_chars * 1.05))
    return sum(max(1, math.ceil(len(seg) / per)) for seg in str(text).split("\n"))


# ------------------------------------------------------------------ drawing helpers
def _row_px(lay: Plan, r: int) -> float:
    return lay.heights.get(r, 15) * 96 / 72


def _rows_px(lay: Plan, r1: int, r2: int) -> float:
    return sum(_row_px(lay, r) for r in range(r1, r2 + 1))


def _place(lay: Plan, grid: int, row: int, *, x_from_right: float = 0.0, y: float = 0.0):
    """One-cell anchor marker at grid column ``grid`` and ``row``; offsets in px from the column's leading (right,
    RTL) edge and the row's top. Excel and LibreOffice mirror drawings on right-to-left sheets."""
    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker
    from openpyxl.utils.units import pixels_to_EMU
    col0 = gc(grid) - 1
    while x_from_right >= COL_PX:
        x_from_right -= COL_PX
        col0 += 1
    r0 = row - 1
    while y >= _row_px(lay, r0 + 1) and r0 < lay.last_row:
        y -= _row_px(lay, r0 + 1)
        r0 += 1
    return AnchorMarker(col=col0, colOff=pixels_to_EMU(int(round(x_from_right))), row=r0,
                        rowOff=pixels_to_EMU(int(round(y))))


def _add_picture(ws, info: DashInfo, lay: Plan, path: Path, grid: int, row: int, w_px: float, h_px: float, alt: str,
                 *, x_from_right: float = 0.0, y: float = 0.0, key: str = "", sha: str = ""):
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.utils.units import pixels_to_EMU
    if not path.exists():
        # The guide icons and the logo are institutional assets kept in private storage (C5). A public checkout
        # builds the dashboard without them; G-UX-21 then reports NOT_VERIFIED, never PASS.
        info.missing_assets.append(key or path.name)
        return
    img = XLImage(str(path))
    img.width, img.height = int(round(w_px)), int(round(h_px))
    img.anchor = OneCellAnchor(_from=_place(lay, grid, row, x_from_right=x_from_right, y=y),
                               ext=XDRPositiveSize2D(pixels_to_EMU(int(round(w_px))), pixels_to_EMU(int(round(h_px)))))
    ws.add_image(img)
    info.image_alts.append(alt)
    info.images.append({"key": key, "file": path.name, "sha256": sha, "row": row, "grid": grid,
                        "w_px": int(round(w_px)), "h_px": int(round(h_px))})


def _icon(ws, info, lay, key: str, variant: str, grid: int, row: int, px: int, *, side="right", margin=6,
          rows: int = 1):
    """A guide icon (``variant`` ink on light, white on dark) in grid column ``grid``: at the column's right
    (reading) edge or at its left edge, vertically centred over ``rows`` rows."""
    meta = T.ICONS[key]
    path = KIT_ROOT / T.ICON_DIR / f"{key}-{variant}.png"
    x = margin if side == "right" else COL_PX - px - margin
    y = max(0.0, (_rows_px(lay, row, row + rows - 1) - px) / 2)
    _add_picture(ws, info, lay, path, grid, row, px, px, f"أيقونة: {meta['meaning'].split(' (')[0]}",
                 x_from_right=x, y=y, key=key, sha=meta[variant])


def _cp(size=9, color=T.CHART_TEXT, bold=False):
    return CharacterProperties(sz=int(size * 100), b=bold, solidFill=color, latin=DFont(typeface=T.FONT),
                               cs=DFont(typeface=T.FONT))


def _txpr(size: int = 9, color=T.CHART_TEXT, bold=False) -> RichText:
    cp = _cp(size, color, bold)
    return RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=cp), endParaRPr=cp)])


def _no_fill() -> GraphicalProperties:
    return GraphicalProperties(noFill=True, ln=LineProperties(noFill=True))


def _bare(ch):
    """Chart and plot areas without fill or line; plotVisOnly 0 (the block's columns are hidden); no auto title."""
    ch.graphical_properties = _no_fill()
    ch.plot_area.graphicalProperties = _no_fill()
    ch.visible_cells_only = False
    ch.roundedCorners = False
    orig = ch._write

    def _write():
        tree = orig()
        ns = "http://schemas.openxmlformats.org/drawingml/2006/chart"
        chart = tree.find(f"{{{ns}}}chart")
        if chart is not None and chart.find(f"{{{ns}}}title") is None and chart.find(f"{{{ns}}}autoTitleDeleted") is None:
            from lxml import etree as _et
            el = _et.Element(f"{{{ns}}}autoTitleDeleted")
            el.set("val", "1")
            chart.insert(0, el)
        return tree
    ch._write = _write
    return ch


def _mark(series_or_point, fill_hex: str, line_hex: str | None, width_emu: int | None):
    gp = GraphicalProperties(solidFill=fill_hex)
    if line_hex:
        gp.line = LineProperties(solidFill=line_hex, w=width_emu)
    else:
        gp.line = LineProperties(noFill=True)
    series_or_point.graphicalProperties = gp


def _invisible(point):
    point.graphicalProperties = _no_fill()


def _anchor_chart(ws, ch, lay: Plan, g1: int, g2: int, r1: int, r2: int, info: DashInfo, name: str, alt: str,
                  kind: str, source: str, series: list[str], *, inset_px: float = 0.0):
    """Anchor ``ch`` so that its box spans grid columns g1..g2 and rows r1..r2 exactly (less ``inset_px``)."""
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.utils.units import pixels_to_EMU
    w = (g2 - g1 + 1) * COL_PX - 2 * inset_px
    h = _rows_px(lay, r1, r2) - 2 * inset_px
    ch.anchor = OneCellAnchor(_from=_place(lay, g1, r1, x_from_right=inset_px, y=inset_px),
                              ext=XDRPositiveSize2D(pixels_to_EMU(int(round(w))), pixels_to_EMU(int(round(h)))))
    ch.width, ch.height = w / 96 * 2.54, h / 96 * 2.54
    ws.add_chart(ch)
    info.chart_alts.append(alt)
    info.charts.append({"name": name, "kind": kind, "source": source, "series": series, "grid": (g1, g2),
                        "rows": (r1, r2), "w_px": int(round(w)), "h_px": int(round(h)), "alt": alt})
    return w, h


def _plot_layout():
    return Layout(manualLayout=ManualLayout(x=0.05, y=0.05, w=0.9, h=0.9, xMode="edge", yMode="edge"))


# ------------------------------------------------------------------ main
def write_dashboard(wb, ws, an: Analytics, view: View, schema, refs: HelperRefs, reg: Registry, state, *,
                    data_sheet: str, lay: Plan, logo_path: str | None = None) -> DashInfo:
    info = DashInfo(layout=lay)
    ws.sheet_view.rightToLeft = True
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 100
    ws.sheet_properties.tabColor = "FF" + T.SECTION
    t = refs.tables
    obs_t, lt, tr, rt, qt, tt, kt, gt, lg = (t["obs"], t["long"], t["trend"], t["round"], t["q"], t["t"], t["kpi"],
                                             t["gauge"], t["legend"])
    R = an.R
    N = len(an.obs)
    doc = state.document
    cur = state.round(R)
    Sx, Rx, Kx = "crms_S", "crms_R", "crms_k"
    ROW = lay.rows

    def M(key):
        return refs.meta(key)

    def TR(col):
        return f"INDEX({tr.rng(col, sheet=True)},{Sx})"

    def O(col, k):
        return obs_t.cell(col, k, sheet=True)

    # ------------------------------------------------------------ grid and rows
    ws.column_dimensions["A"].width = W.MARGIN_WIDTH
    for g in range(NGRID):
        ws.column_dimensions[L(gc(g))].width = W.GRID_WIDTH
    ws.column_dimensions[L(gc(NGRID))].width = W.MARGIN_WIDTH
    for c in range(gc(NGRID) + 1, W.CALC_FIRST_COL):          # O..Q: empty page surface
        ws.column_dimensions[L(c)].width = W.MARGIN_WIDTH
    for r, h in lay.heights.items():
        ws.row_dimensions[r].height = h

    # ============================================================ ZONE A — identity band (DASH_HEADER)
    _fill_cols(ws, ROW["top"], 1, ROW["band_bottom"], gc(NGRID), T.BAND_DARK)
    tg = 3                                       # the logo slot g1–g3, the texts g4–g12
    _merge(ws, ROW["hline"], 0, ROW["doc"], tg - 1)
    if logo_path:
        _logo(ws, info, lay, Path(logo_path))
    else:
        info.notes.append("logo slot g1–g3 empty: no official white-on-dark logo file supplied, and the Design Guide "
                          "prints none (G-UX-02 NOT_VERIFIED)")
    _text(ws, ROW["hline"], tg, NGRID - 1, W.HEADER_LINE, size=T.SZ_SUBTITLE, color=T.ON_DARK_MUTED, v="bottom",
          wrap=False)
    _text(ws, ROW["title"], tg, NGRID - 1, W.DASHBOARD_TITLE, size=T.SZ_TITLE, bold=True, color=T.ON_DARK, wrap=False)
    _text(ws, ROW["doc"], tg, NGRID - 1, doc.name, size=T.SZ_DOC, bold=True, color=T.ON_DARK, v="top", wrap=False)

    # facts strip: a white card; 9-pt label with its 16-px icon over an 11-pt bold value
    need, filled = M("complete_needed"), M("complete_filled")
    next_f = (f'IF({need}=0,"لا توجد ملاحظات تتطلب إفادة في الجولة الحالية",'
              f'"الإفادة عن "&{need}&" ملاحظة غير مغلقة في ورقة الملاحظات (أُدخلت "&{filled}&")")')

    def next_exp(v: View):
        f_, n_ = v.completeness()
        return ("لا توجد ملاحظات تتطلب إفادة في الجولة الحالية" if n_ == 0
                else f"الإفادة عن {n_} ملاحظة غير مغلقة في ورقة الملاحظات (أُدخلت {f_})")
    facts = [("الجولة الحالية", S.round_label(R) if R else S.NOT_RECORDED, 0, 1),
             ("إصدار الوثيقة", doc.cover_version or cur.document_version or S.NOT_RECORDED, 2, 3),
             ("تاريخ آخر مراجعة", cur.date or S.NOT_RECORDED, 4, 5),
             ("الإدارة صاحبة الوثيقة", doc.owning_department or S.NOT_RECORDED, 6, 8),
             ("المطلوب من الإدارة صاحبة الطلب في الجولة الحالية", None, 9, 11)]
    _fill(ws, ROW["fact_l"], 0, ROW["fact_v"], NGRID - 1, T.CARD)
    for i, (lab, val, g1, g2) in enumerate(facts):
        c = _text(ws, ROW["fact_l"], g1, g2, lab, size=T.SZ_NOTE, color=T.MUTED, v="bottom", wrap=False)
        c.alignment = st.align("right", "bottom", False, indent=3)
        _icon(ws, info, lay, T.FACT_ICON[i], "ink", g1, ROW["fact_l"], T.ICON_PX["fact"], side="right", margin=4)
        if val is None:
            _formula(ws, reg, ROW["fact_v"], g1, g2, next_f, next_exp, size=T.SZ_FACT, bold=True,
                     color=T.STATUS_DEEP[S.OPEN], v="top")
        else:
            _text(ws, ROW["fact_v"], g1, g2, val, size=T.SZ_FACT, bold=True, v="top")
        _box(ws, ROW["fact_l"], g1, ROW["fact_v"], g2)

    # band row: demonstration band, historic-round band, both, or nothing (rows never shift)
    demo = bool(doc.is_demo)
    hist = (f'"تعرض اللوحة "&{M("selected_label")}&" (جولة سابقة)، والجولة الحالية هي "&{M("current_label")}&"."')
    band_f = (f'IF({Sx}<>{Rx},{hist}' + (f'&"{S.SEP}{S.DEMO_BANNER}"' if demo else "") + ","
              + (f'"{S.DEMO_BANNER}"' if demo else '""') + ")")

    def band_exp(v: View):
        h = v.historical_band()
        if h:
            return h + (f"{S.SEP}{S.DEMO_BANNER}" if demo else "")
        return S.DEMO_BANNER if demo else ""
    bc = _formula(ws, reg, ROW["band"], 0, NGRID - 1, band_f, band_exp, bold=True, h="center", wrap=False)
    band_rng = f"{L(gc(0))}{ROW['band']}:{L(gc(NGRID - 1))}{ROW['band']}"
    ws.conditional_formatting.add(band_rng, FormulaRule(formula=[f"{Sx}<>{Rx}"], fill=st.fill(T.HISTORIC_BAND),
                                                        stopIfTrue=True))
    ws.conditional_formatting.add(band_rng, FormulaRule(formula=[f'LEN(${L(gc(0))}${ROW["band"]})>0'],
                                                        fill=st.fill(T.DEMO_BAND), stopIfTrue=True))

    # navigation chips (filled in once the zones are placed) and selectors
    sel_specs = [(0, 1, "الجولة المعروضة", "dash_round", lay.sel_round, W.NAME_ROUNDS, S.round_label(view.S)),
                 (2, 3, "جولة المقارنة", "dash_compare", lay.sel_compare, W.NAME_ROUNDS, S.round_label(view.C)),
                 (4, 6, "نطاق جدول الملاحظات", "dash_scope", lay.sel_scope, W.NAME_SCOPES, view.scope),
                 (7, 8, "الانتقال إلى ملاحظة", "dash_jump", lay.sel_obs, W.NAME_READERS, view.reader_label or "")]
    for g1, g2, lab, key, ref, src, default in sel_specs:
        lc = _text(ws, ROW["sel_l"], g1, g2, lab, size=T.SZ_NOTE, bold=True, color=T.MUTED, v="bottom", wrap=False)
        lc.comment = _note(G.entry(key).note)
        cell = _merge(ws, ROW["sel_v"], g1, None, g2)
        cell.value = default
        cell.number_format = "@"
        cell.font = st.font(11, bold=True, color=T.INK)
        cell.alignment = st.align("center", "center", False)
        _fill(ws, ROW["sel_v"], g1, ROW["sel_v"], g2, T.CARD)
        _box(ws, ROW["sel_v"], g1, ROW["sel_v"], g2, color=T.SECTION, style="thick")
        for gg in range(g1, g2 + 1):
            ws.cell(row=ROW["sel_v"], column=gc(gg)).protection = Protection(locked=False)
        title, prompt = G.input_message(key)
        dv = DataValidation(type="list", formula1=src, allow_blank=False, showDropDown=False,
                            showInputMessage=True, showErrorMessage=True, errorStyle="stop",
                            promptTitle=title, prompt=prompt, errorTitle=title, error="يرجى الاختيار من القائمة.")
        dv.sqref = cell.coordinate
        ws.add_data_validation(dv)
        info.selector_cells.append(cell.coordinate)
    noobs = f"{M('obs_count')}=0"
    jc = _formula(ws, reg, ROW["sel_v"], 9, 9,
                  f'IF({noobs},"",HYPERLINK("#{DASH}!{L(gc(0))}"&INDEX({obs_t.rng("card_row", sheet=True)},{Kx}),'
                  f'"اذهب إلى البطاقة"))', lambda v: "اذهب إلى البطاقة" if v.sel else "",
                  bold=True, color=T.LINK, h="center", underline="single", fill=T.CARD)
    info.link_cells.append(jc.coordinate)
    resp_col = schema.col(R, S.ROLE_RESPONSE) if R else 1
    pc = _text(ws, ROW["sel_v"], 10, 11, "ورقة الملاحظات (الإدخال)", bold=True, h="center", fill=T.SECTION,
               wrap=False)
    pc.hyperlink = Hyperlink(ref=pc.coordinate, location=f"'{data_sheet}'!{L(resp_col)}2",
                             display="ورقة الملاحظات (الإدخال)")
    info.nav_cells.append(pc.coordinate)

    # ============================================================ ZONE B — KPI cards
    labels = {"issued": "إجمالي الملاحظات", "closed": "الملاحظات المغلقة", "cond": "مغلقة بشرط",
              "req": "يتطلب تعديل", "open": "مفتوحة", "rate": "نسبة الإغلاق"}
    for i, key in enumerate(KPI_KEYS):
        g = 2 * i
        _fill(ws, ROW["kpi_cap"], g, ROW["kpi_cap"], g + 1, T.CARD_CAP[key])
        _fill(ws, ROW["kpi_l"], g, ROW["kpi_f"], g + 1, T.CARD)
        lc = _text(ws, ROW["kpi_l"], g, g + 1, labels[key], size=T.SZ_CARD_LABEL, bold=True, color=T.MUTED,
                   wrap=False)
        lc.alignment = st.align("right", "center", False, indent=1)
        _icon(ws, info, lay, T.KPI_ICON[key], "ink", g + 1, ROW["kpi_l"], T.ICON_PX["kpi"], side="left")
        if key == "rate":
            lc.comment = _note(G.entry("kpi_rate").note)
        kr = KPI_KEYS.index(key) + 1
        _formula(ws, reg, ROW["kpi_v"], g, g + 1, f"{kt.cell('cur', kr, sheet=True)}",
                 lambda v, key=key: v.kpi(key)["cur"], size=T.SZ_CARD_VALUE, bold=True, color=T.KPI_VALUE[key],
                 h="center", fmt="0.0%" if key == "rate" else "0", wrap=False)
        _formula(ws, reg, ROW["kpi_f"], g, g, f"{kt.cell('prevtxt', kr, sheet=True)}",
                 lambda v, key=key: v.kpi(key)["prevtxt"], size=T.SZ_NOTE, color=T.MUTED, wrap=True)
        chip = _formula(ws, reg, ROW["kpi_f"], g + 1, g + 1, f"{kt.cell('chip', kr, sheet=True)}",
                        lambda v, key=key: v.kpi(key)["chip"], size=T.SZ_NOTE, bold=True, color=T.MUTED, h="center",
                        wrap=False)
        d = kt.cell("dir", kr, sheet=True)
        cc = chip.coordinate
        for cond, (fill_hex, text_hex) in ((f'AND({cc}<>"",{d}=1)', T.CHIP["fav"]),
                                           (f'AND({cc}<>"",{d}=-1)', T.CHIP["unfav"]),
                                           (f'{cc}<>""', T.CHIP["neutral"])):
            ws.conditional_formatting.add(cc, FormulaRule(formula=[cond], fill=st.fill(fill_hex),
                                                          font=st.font(T.SZ_NOTE, bold=True, color=text_hex),
                                                          stopIfTrue=True))
        _box(ws, ROW["kpi_cap"], g, ROW["kpi_f"], g + 1)

    # ============================================================ ZONE C — closure level
    _band(ws, info, lay, "closure", "مستوى إغلاق الملاحظات")
    issued, closed, cond, req, open_ = TR("issued"), TR("closed"), TR("cond"), TR("req"), TR("open")
    rate = TR("rate")
    lab = M("selected_label")
    n1 = (f'IF({issued}=0,"لا توجد ملاحظات مسجلة حتى الآن.",IF({Sx}=1,"حتى "&{lab}&": عدد الملاحظات الصادرة "'
          f'&{issued}&"، وجميعها بانتظار الإفادة الأولى من الإدارة صاحبة الطلب.","حتى "&{lab}&": مغلقة "&{closed}'
          f'&" من أصل "&{issued}&" ("&FIXED({rate}*100,1)&"%)؛ يتطلب تعديل "&{req}&"؛ مغلقة بشرط "&{cond}'
          f'&"؛ مفتوحة "&{open_}&"."))')
    n2 = (f'IF(OR({Sx}=1,{issued}=0),"","خلال "&{lab}&": أُغلقت "&{TR("closed_event")}&"، وأُعيد فتح "'
          f'&{TR("reopen_event")}&"، وأُضيفت "&{TR("new")}&"، ومتعثرة "&{TR("stalled")}&".")')
    _fill(ws, ROW["narr1"], 0, ROW["narr2"], NGRID - 1, T.CARD)
    _formula(ws, reg, ROW["narr1"], 0, NGRID - 1, n1, lambda v: v.narrative1(), size=T.SZ_NARRATIVE, wrap=False)
    _formula(ws, reg, ROW["narr2"], 0, NGRID - 1, n2, lambda v: v.narrative2(), size=T.SZ_NARRATIVE, color=T.MUTED,
             wrap=False)
    for c in (ws.cell(row=ROW["narr1"], column=gc(0)), ws.cell(row=ROW["narr2"], column=gc(0))):
        c.alignment = st.align("right", "center", False, indent=1)
    _box(ws, ROW["narr1"], 0, ROW["narr2"], NGRID - 1)
    _deck(ws, info, lay, reg, refs, an, M, TR, gt)
    _distribution(ws, info, lay, reg, refs, tr, lg)

    # ============================================================ ZONE D — the complete action list
    qc = M("queue_count")
    _band(ws, info, lay, "queue", None, reg=reg, formula=f'"الملاحظات التي تتطلب إجراء ("&{qc}&")"',
          expected=lambda v: f"الملاحظات التي تتطلب إجراء ({len(v.queue)})")
    _text(ws, ROW["q_note"], 0, NGRID - 1, "الترتيب لأغراض المتابعة وليس تصنيفاً للأهمية. انقر رقم الملاحظة أو عنوانها "
          "لعرض بطاقتها، وانقر (فتح الصف) للانتقال إلى صفها في ورقة الملاحظات.", size=T.SZ_NOTE, color=T.MUTED)
    qh = ROW["q_head"]
    for lab_, g1, g2 in (("الملاحظة #", 0, 0), ("عنوان الملاحظة", 1, 4), ("الحالة", 5, 5),
                         ("سبب الظهور في القائمة", 6, 7), ("الإجراء المطلوب", 8, 10), ("الانتقال", 11, 11)):
        _text(ws, qh, g1, g2, lab_, bold=True, h="center", fill=T.SECTION)
    QN = lay.QN
    _fill(ws, lay.q0, 0, lay.q0 + QN - 1, NGRID - 1, T.CARD)
    card_rng = obs_t.rng("card_row", sheet=True)
    for i in range(1, QN + 1):
        rr = lay.q0 + i - 1
        info.queue_rows.append(rr)
        kq = qt.cell("k", i, sheet=True)

        def qa(fn, i=i):
            return lambda v: (fn(v, v.queue[i - 1]) if i <= len(v.queue) else "")
        c = _formula(ws, reg, rr, 0, 0, f'IF({kq}="","",HYPERLINK("#{DASH}!{L(gc(0))}"&INDEX({card_rng},{kq}),'
                     f'INDEX({obs_t.rng("reader_label", sheet=True)},{kq})))', qa(lambda v, a: a.reader_label),
                     bold=True, color=T.LINK, h="center", underline="single")
        info.link_cells.append(c.coordinate)
        empty = '"لا توجد ملاحظات تتطلب إجراء في الجولة المعروضة"' if i == 1 else '""'

        def title_e(v, i=i):
            if i <= len(v.queue):
                from ..analytics.dashboard_analytics import list_title
                return list_title(v.queue[i - 1])
            return "لا توجد ملاحظات تتطلب إجراء في الجولة المعروضة" if (i == 1 and not v.queue) else ""
        c = _formula(ws, reg, rr, 1, 4, f'IF({kq}="",IF({qc}=0,{empty},""),HYPERLINK("#{DASH}!{L(gc(0))}"&'
                     f'INDEX({card_rng},{kq}),INDEX({obs_t.rng("title_list", sheet=True)},{kq})&""))', title_e)
        info.link_cells.append(c.coordinate)
        _formula(ws, reg, rr, 5, 5, f'IF({kq}="","",INDEX({obs_t.rng("v", sheet=True)},{kq}))',
                 qa(lambda v, a: a.long[v.S].value), h="center", bold=True)
        _formula(ws, reg, rr, 6, 7, f'IF({kq}="","",INDEX({obs_t.rng("reason", sheet=True)},{kq}))',
                 qa(lambda v, a: a.long[v.S].reason), bold=True, h="center")
        _formula(ws, reg, rr, 8, 10, f'IF({kq}="","",INDEX({obs_t.rng("action", sheet=True)},{kq})&"")',
                 qa(lambda v, a: a.long[v.S].action))
        c = _formula(ws, reg, rr, 11, 11, f'IF({kq}="","",HYPERLINK(INDEX({obs_t.rng("link", sheet=True)},{kq}),'
                     f'"فتح الصف"))', qa(lambda v, a: "فتح الصف"), h="center", color=T.LINK, underline="single")
        info.link_cells.append(c.coordinate)
    a_, b_ = lay.q0, lay.q0 + QN - 1
    _status_rules(ws, f"{L(gc(5))}{a_}:{L(gc(5))}{b_}", f"${L(gc(5))}{a_}")
    rs = f"{L(gc(6))}{a_}:{L(gc(7))}{b_}"
    for value, color in ((S.REASON_REOPENED, T.FLAG_REOPENED), (S.REASON_STALLED, T.FLAG_STALLED),
                         (S.REASON_COND, T.FLAG_COND)):
        ws.conditional_formatting.add(rs, FormulaRule(formula=[f'${L(gc(6))}{a_}="{value}"'], fill=st.fill(color),
                                                      font=st.font(T.SZ_BODY, bold=True, color=T.INK),
                                                      stopIfTrue=True))
    _zebra(ws, a_, b_)
    over = (f'IF({M("queue_more")}>0,"و "&{M("queue_more")}&" ملاحظة أخرى{S.SEP}تُعرض كاملة في جدول الملاحظات '
            f'بالنطاق (الملاحظات التي تتطلب إجراء)","")')
    _formula(ws, reg, ROW["q_over"], 0, NGRID - 1, over,
             lambda v: (f"و {len(v.queue) - QN} ملاحظة أخرى{S.SEP}تُعرض كاملة في جدول الملاحظات بالنطاق "
                        f"(الملاحظات التي تتطلب إجراء)") if len(v.queue) > QN else "",
             size=T.SZ_NOTE, bold=True, color=T.MUTED, wrap=False)

    # ============================================================ ZONE E — round analysis
    _band(ws, info, lay, "rounds", "تطور الملاحظات عبر جولات المراجعة (جميع الجولات المسجلة)")
    _round_charts(ws, info, lay, tr, R)
    _matrix(ws, info, lay, reg, refs, obs_t, M)

    # ============================================================ ZONE F — the observation table
    tc = M("table_count")
    _band(ws, info, lay, "table", None, reg=reg,
          formula=f'"جدول الملاحظات في "&{M("selected_label")}&"{S.SEP}"&{M("scope")}&" ("&{tc}&")"',
          expected=lambda v: f"جدول الملاحظات في {S.round_label(v.S)}{S.SEP}{v.scope} ({len(v.table)})")
    th = ROW["t_head"]
    prev_h = f'IF({Sx}=1,"الجولة السابقة","الحالة في "&INDEX({rt.rng("label", sheet=True)},{Sx}-1))'
    sel_h = f'"الحالة في "&{M("selected_label")}'
    for lab_, g1, g2, dyn in (("الملاحظة #", 0, 0, None), ("عنوان الملاحظة", 1, 4, None),
                              (None, 5, 5, (prev_h, lambda v: "الجولة السابقة" if v.S == 1
                                            else f"الحالة في {S.round_label(v.S - 1)}")),
                              (None, 6, 6, (sel_h, lambda v: f"الحالة في {S.round_label(v.S)}")),
                              ("التغير", 7, 8, None), ("الإجراء المطلوب", 9, 10, None), ("الانتقال", 11, 11, None)):
        if dyn:
            _formula(ws, reg, th, g1, g2, dyn[0], dyn[1], bold=True, h="center", fill=T.SECTION)
        else:
            c = _text(ws, th, g1, g2, lab_, bold=True, h="center", fill=T.SECTION)
            if lab_ == "التغير":
                c.comment = _note(G.entry("kpi_change").note)
    TN = lay.TN
    _fill(ws, lay.t0, 0, lay.t0 + TN - 1, NGRID - 1, T.CARD)
    for i in range(1, TN + 1):
        rr = lay.t0 + i - 1
        info.table_rows.append(rr)
        kt_ = tt.cell("k", i, sheet=True)

        def tv(fn, i=i):
            return lambda v: (fn(v, v.table[i - 1]) if i <= len(v.table) else "")
        c = _formula(ws, reg, rr, 0, 0, f'IF({kt_}="","",HYPERLINK("#{DASH}!{L(gc(0))}"&INDEX({card_rng},{kt_}),'
                     f'INDEX({obs_t.rng("reader_label", sheet=True)},{kt_})))', tv(lambda v, a: a.reader_label),
                     bold=True, color=T.LINK, h="center", underline="single")
        info.link_cells.append(c.coordinate)
        empty = '"لا توجد ملاحظات ضمن النطاق المختار في الجولة المعروضة."' if i == 1 else '""'

        def ttitle(v, i=i):
            from ..analytics.dashboard_analytics import list_title
            if i <= len(v.table):
                return list_title(v.table[i - 1])
            return "لا توجد ملاحظات ضمن النطاق المختار في الجولة المعروضة." if i == 1 else ""
        c = _formula(ws, reg, rr, 1, 4, f'IF({kt_}="",IF({tc}=0,{empty},""),HYPERLINK("#{DASH}!{L(gc(0))}"&'
                     f'INDEX({card_rng},{kt_}),INDEX({obs_t.rng("title_list", sheet=True)},{kt_})&""))', ttitle)
        info.link_cells.append(c.coordinate)
        _formula(ws, reg, rr, 5, 5, f'IF({kt_}="","",INDEX({obs_t.rng("prev_disp", sheet=True)},{kt_}))',
                 tv(lambda v, a: v.prev_disp[a.k]), h="center")
        _formula(ws, reg, rr, 6, 6, f'IF({kt_}="","",INDEX({obs_t.rng("v", sheet=True)},{kt_}))',
                 tv(lambda v, a: a.long[v.S].value), h="center", bold=True)
        _formula(ws, reg, rr, 7, 8, f'IF({kt_}="","",INDEX({obs_t.rng("change", sheet=True)},{kt_}))',
                 tv(lambda v, a: a.long[v.S].change), h="center", size=T.SZ_NOTE)
        _formula(ws, reg, rr, 9, 10, f'IF({kt_}="","",INDEX({obs_t.rng("action", sheet=True)},{kt_})&"")',
                 tv(lambda v, a: a.long[v.S].action), size=T.SZ_NOTE)
        c = _formula(ws, reg, rr, 11, 11, f'IF({kt_}="","",HYPERLINK(INDEX({obs_t.rng("link", sheet=True)},{kt_}),'
                     f'"فتح الصف"))', tv(lambda v, a: "فتح الصف"), h="center", color=T.LINK, underline="single")
        info.link_cells.append(c.coordinate)
    a_, b_ = lay.t0, lay.t0 + TN - 1
    _status_rules(ws, f"{L(gc(5))}{a_}:{L(gc(6))}{b_}", f"{L(gc(5))}{a_}")
    chg = f"{L(gc(7))}{a_}:{L(gc(8))}{b_}"
    for value, color in ((S.CHANGE_REOPENED, T.FLAG_REOPENED), (S.CHANGE_NO_PROGRESS, T.FLAG_STALLED),
                         (S.CHANGE_CLOSED, T.STATUS_FILL[S.CLOSED]), (S.CHANGE_COND_REGRESS, T.FLAG_STALLED)):
        ws.conditional_formatting.add(chg, FormulaRule(formula=[f'${L(gc(7))}{a_}="{value}"'], fill=st.fill(color),
                                                       stopIfTrue=True))
    _zebra(ws, a_, b_)

    # ============================================================ ZONE G — user guide (D.12)
    _band(ws, info, lay, "help", "دليل الاستخدام")
    help_lines = [
        ("أين تُكتب الإفادة؟", "تُعبأ الإفادات وحالات التطبيق في ورقة الملاحظات فقط، في عمودي الجولة الحالية للملاحظات غير "
                               "المغلقة. لا تُدخل أي بيانات في هذه اللوحة، فهي للعرض والانتقال."),
        ("معاني حالات الإغلاق", f"{S.CLOSED}: لا يلزم إجراء. {S.CLOSED_COND}: يلزم استيفاء الشرط المذكور في مرئيات الحوكمة. "
                                f"{S.REQUIRES_EDIT}: يلزم استكمال التعديل المذكور في سطر \"المطلوب:\". {S.OPEN}: لم تُقدَّم "
                                "إفادة أو تعديل يمكن التحقق منه. في الجولة الأولى تعني \"مفتوحة\" أن الملاحظة بانتظار الإفادة الأولى."),
        ("حالة التطبيق", "القيمة التي تختارها الإدارة صاحبة الطلب إفادة منها، ولا تُغلق الملاحظة بذاتها؛ تحدد إدارة الحوكمة "
                         "والامتثال المؤسسي حالة الإغلاق بعد التحقق من النص."),
        ("اختيار الجولة والمقارنة", "تغيّر القوائم المنسدلة في أعلى اللوحة الجولة المعروضة وجولة المقارنة ونطاق الجدول، "
                                    "وتنقل القائمة الرابعة إلى بطاقة الملاحظة المختارة. الاختيار للعرض فقط ولا يغيّر أي بيانات أو تقييم."),
        ("السجل التاريخي", "تُحفظ تقييمات الحوكمة وإفادات الإدارة في كل جولة في أعمدتها بورقة الملاحظات دون تعديل. يمكن طي "
                           "أعمدة الجولات الأقدم أو إظهارها من علامة (+) أعلى الأعمدة."),
        ("المؤشرات المشتقة", "التغير والمتعثرة والمعاد فتحها وجاهزية المراجعة ونسبة تطبيق الملاحظات أوصاف للعرض مستمدة من "
                             "حالات الإغلاق، وليست حالات إغلاق. ولا تعني نسبة الإغلاق اعتماد الوثيقة أو مستوى امتثالها."),
        ("الاعتراض على الإغلاق", "يُكتب الاعتراض على إغلاق ملاحظة في خلية الإفادة الخاصة بها في الجولة الحالية، وسيُعاد تقييمه."),
        ("مثال توضيحي", f"{G.EXAMPLE_TAG} \"عُدّل البند (5-2) بإضافة اشتراط موافقة صاحب الصلاحية قبل إطلاق أي مبادرة، "
                        "انظر الصفحة 4 من النسخة المحدثة.\""),
    ]
    assert len(help_lines) == HELP_ROWS
    h0 = ROW["help_rows"]
    _fill(ws, h0, 0, h0 + HELP_ROWS - 1, NGRID - 1, T.CARD)
    for i, (lab_, txt) in enumerate(help_lines):
        r = h0 + i
        ws.row_dimensions[r].height = max(20, 14 * _lines(txt, 10 * W.GRID_WIDTH * 0.95) + 6)
        lay.heights[r] = ws.row_dimensions[r].height
        _text(ws, r, 0, 1, lab_, bold=True, v="top")
        _text(ws, r, 2, NGRID - 1, txt, v="top")
    _box(ws, h0, 0, h0 + HELP_ROWS - 1, NGRID - 1)

    # ============================================================ ZONE H — observation cards
    _band(ws, info, lay, "cards", None, reg=reg, formula=f'"بطاقات الملاحظات{S.SEP}"&{M("selected_label")}',
          expected=lambda v: f"بطاقات الملاحظات{S.SEP}{S.round_label(v.S)}")
    if N:
        _cards(ws, info, lay, reg, refs, an, schema, data_sheet)
    else:
        _text(ws, lay.card0, 0, NGRID - 1, S.READY_EMPTY_DETAIL, color=T.MUTED, fill=T.CARD)

    # ============================================================ footer
    _text(ws, ROW["foot_note"], 0, NGRID - 1, W.FOOTER_NOTE, size=T.SZ_NOTE, color=T.MUTED, wrap=False)
    _fill_cols(ws, ROW["footer"], 1, ROW["footer"], gc(NGRID), T.INK)
    _text(ws, ROW["footer"], 0, 5, W.FOOTER_RIGHT, size=T.SZ_NOTE, color=T.ON_DARK, wrap=False)
    _text(ws, ROW["footer"], 6, NGRID - 1, f"آخر تحديث: {cur.date or S.NOT_RECORDED}", size=T.SZ_NOTE,
          color=T.ON_DARK, h="left", wrap=False)
    info.last_row = lay.last_row

    # ============================================================ navigation chips (zones placed)
    chips = [("مستوى الإغلاق", "closure"), ("الملاحظات التي تتطلب إجراء", "queue"), ("تحليل الجولات", "rounds"),
             ("جدول الملاحظات", "table"), ("بطاقات الملاحظات", "cards"), ("دليل الاستخدام", "help")]
    for i, (lab_, zone) in enumerate(chips):
        c = _text(ws, ROW["nav"], 2 * i, 2 * i + 1, lab_, bold=True, color=T.LINK, h="center", fill=T.CARD,
                  underline="single", wrap=False)
        c.hyperlink = Hyperlink(ref=c.coordinate, location=f"{DASH}!{L(gc(0))}{lay.bands[zone]}", display=lab_)
        _box(ws, ROW["nav"], 2 * i, ROW["nav"], 2 * i + 1)
        info.nav_cells.append(c.coordinate)
    info.sections = dict(lay.bands)

    # page surface behind every cell no zone painted (A..Q); cards stay white
    for r in range(1, lay.last_row + 1):
        for c in range(1, W.CALC_FIRST_COL):
            cell = ws.cell(row=r, column=c)
            if cell.fill is None or cell.fill.fill_type is None:
                cell.fill = st.fill(T.PAGE)

    _sheet_settings(ws, lay, doc, info)
    return info


# ------------------------------------------------------------------ zone pieces
def _band(ws, info, lay: Plan, zone: str, title: str | None, *, reg=None, formula=None, expected=None):
    """Full-width Powder Blue section band: cultural icon at g1, title, "العودة إلى الأعلى" at g12."""
    r = lay.bands[zone]
    _fill(ws, r, 0, r, NGRID - 1, T.SECTION)
    _icon(ws, info, lay, T.BAND_ICON[zone], "ink", 0, r, T.ICON_PX["band"], side="right", margin=8)
    if formula:
        _formula(ws, reg, r, 1, NGRID - 2, formula, expected, size=T.SZ_SECTION, bold=True, wrap=False)
    else:
        _text(ws, r, 1, NGRID - 2, title, size=T.SZ_SECTION, bold=True, wrap=False)
    c = _text(ws, r, NGRID - 1, NGRID - 1, "العودة إلى الأعلى", size=T.SZ_NOTE, color=T.LINK, h="left",
              underline="single", wrap=True)
    c.hyperlink = Hyperlink(ref=c.coordinate, location=f"{DASH}!{L(gc(0))}1", display="العودة إلى الأعلى")
    info.nav_cells.append(c.coordinate)


def _zebra(ws, a: int, b: int):
    """Zebra and bottom rule only on filled rows (lower priority than the status and flag fills)."""
    rule_border = st.border(None, None, None, "thin", color=T.CARD_BORDER)
    whole = f"{L(gc(0))}{a}:{L(gc(NGRID - 1))}{b}"
    ws.conditional_formatting.add(whole, FormulaRule(
        formula=[f'AND(OR(${L(gc(0))}{a}<>"",${L(gc(1))}{a}<>""),MOD(ROW()-{a},2)=1)'], fill=st.fill(T.ZEBRA),
        border=rule_border))
    ws.conditional_formatting.add(whole, FormulaRule(formula=[f'OR(${L(gc(0))}{a}<>"",${L(gc(1))}{a}<>"")'],
                                                     border=rule_border))


def _deck(ws, info, lay: Plan, reg, refs, an, M, TR, gt):
    """Dark gauge deck: composite needle gauge, two mini gauges, indicator tiles (spec 5 zone C.2, 7.1, 7.2)."""
    ROW = lay.rows
    r_top, r_bot = ROW["deck_top"], ROW["deck_bottom"]
    pt, u1, l1, l2, l3 = ROW["panel_title"], ROW["g_u1"], ROW["g_l1"], ROW["g_l2"], ROW["g_l3"]
    _fill_cols(ws, r_top, 1, r_bot, gc(NGRID), T.BAND_DARK)
    panels = [(0, 3, "نسبة تطبيق الملاحظات"), (4, 5, "نسبة الإغلاق"), (6, 7, "استدامة الإغلاق"),
              (8, 11, "مؤشرات الجولة المعروضة")]
    for g1, g2, title in panels:
        _fill(ws, pt, g1, l3, g2, T.PANEL_DARK)
        _text(ws, pt, g1, g2, title, size=T.SZ_PANEL_TITLE, bold=True, color=T.ON_DARK, h="center", wrap=False)
        _box(ws, pt, g1, l3, g2, color=T.BAND_DARK, style="thick")
    issued = TR("issued")
    # composite gauge g1–g4: value, scale labels, caption in the lower half (under the transparent chart)
    impl = M("impl_rate")
    # issued = 0: the 21-character message cannot fit at 30 pt in the panel, so it is written at 11 pt bold directly
    # under the (blank) value cell, and the needle rests at 0 (spec 7.1 edge case; recorded deviation)
    _formula(ws, reg, l1, 1, 2, f'IF({issued}=0,"",{impl})', lambda v: "" if not v.t.issued else v.gauge()["impl"],
             size=T.SZ_GAUGE, bold=True, color=T.ON_DARK, h="center", v="top", fmt="0.0%", wrap=False)
    _text(ws, l1, 3, 3, "0%", size=T.SZ_NOTE, color=T.ON_DARK_CAPTION, h="right", v="top", wrap=False)
    _text(ws, l1, 0, 0, "100%", size=T.SZ_NOTE, color=T.ON_DARK_CAPTION, h="left", v="top", wrap=False)
    _formula(ws, reg, l2, 0, 3, f'IF({issued}=0,"لا توجد ملاحظات صادرة","")',
             lambda v: "لا توجد ملاحظات صادرة" if not v.t.issued else "", size=T.SZ_NARRATIVE, bold=True,
             color=T.ON_DARK, h="center", v="top", wrap=False)
    _text(ws, l3, 0, 3, "(المغلقة + المغلقة بشرط) ÷ الصادرة – مؤشر عرض لا يغيّر حالة الإغلاق؛ ولا تُحسب المغلقة بشرط "
          "مغلقة", size=T.SZ_NOTE, color=T.ON_DARK_CAPTION, h="center", v="top")
    # mini gauge: closure rate g5–g6
    _formula(ws, reg, l1, 4, 5, f'IF({issued}=0,"",{M("rate_v")})', lambda v: "" if not v.t.issued else v.gauge()["rate"],
             size=T.SZ_MINI, bold=True, color=T.ON_DARK, h="center", v="top", fmt="0.0%", wrap=False)
    _text(ws, l2, 4, 5, "المغلقة ÷ الصادرة", size=T.SZ_NOTE, color=T.ON_DARK_CAPTION, h="center", v="top", r2=l3)
    # mini gauge: closure sustainability g7–g8
    ever = TR("ever")
    _formula(ws, reg, l1, 6, 7, f'IF({ever}=0,"",{M("sus_v")})', lambda v: "" if not v.t.ever else v.gauge()["sus"],
             size=T.SZ_MINI, bold=True, color=T.ON_DARK, h="center", v="top", fmt="0.0%", wrap=False)
    _formula(ws, reg, l2, 6, 7, f'IF({ever}=0,"لم تُغلق أي ملاحظة بعد",{TR("closed")}&" من "&{ever})',
             lambda v: "لم تُغلق أي ملاحظة بعد" if not v.t.ever else f"{v.t.closed} من {v.t.ever}",
             size=T.SZ_BODY, bold=True, color=T.ON_DARK, h="center", v="top", wrap=False)
    _text(ws, l3, 6, 7, "المغلقة ÷ ما أُغلق في أي جولة", size=T.SZ_NOTE, color=T.ON_DARK_CAPTION, h="center", v="top")
    # tiles g9–g12: three rows, two columns, the readiness tile full width
    tiles = [("stalled", "المتعثرة", TR("stalled"), lambda v: v.t.stalled, T.STATUS_MARK[S.REQUIRES_EDIT], 8, u1),
             ("reopen", "المعاد فتحها", TR("reopen_state"), lambda v: v.t.reopen_state, T.STATUS_MARK[S.OPEN], 10, u1),
             ("closed_event", "أُغلقت خلال الجولة", TR("closed_event"), lambda v: v.t.closed_event,
              T.STATUS_MARK[S.CLOSED], 8, u1 + 2),
             ("new", "جديدة في الجولة", TR("new"), lambda v: v.t.new, T.SECTION, 10, u1 + 2)]
    for key, caption, f, exp, color, g, r in tiles:
        c = _text(ws, r, g, g + 1, caption, size=T.SZ_NOTE, color=T.ON_DARK_CAPTION, wrap=False)
        c.alignment = st.align("right", "center", False, indent=1)
        _icon(ws, info, lay, T.TILE_ICON[key], "white", g + 1, r, T.ICON_PX["tile"], side="left")
        _formula(ws, reg, r + 1, g, g + 1, f, exp, size=T.SZ_TILE, bold=True, color=color, h="center", wrap=False)
        _box(ws, r, g, r + 1, g + 1, color=T.BAND_DARK, style="thick")
    c = _text(ws, l2, 8, 11, "جاهزية المراجعة", size=T.SZ_NOTE, color=T.ON_DARK_CAPTION, wrap=False)
    c.alignment = st.align("right", "center", False, indent=1)
    c.comment = _note(G.entry("readiness").note)
    _icon(ws, info, lay, T.TILE_ICON["ready"], "white", 11, l2, T.ICON_PX["tile"], side="left")
    cond, req, open_ = TR("cond"), TR("req"), TR("open")
    rf = (f'IF({issued}=0,"{S.READY_EMPTY}",IF({TR("invalid")}>0,"{S.READY_NO_DATA}",'
          f'IF({open_}+{req}>0,"{S.READY_ACTION}",IF({cond}>0,"{S.READY_COND}",'
          f'"{S.READY_ALL_CLOSED} {S.READY_NOTE}"))))')
    _formula(ws, reg, l3, 8, 11, rf, lambda v: v.readiness_tile(), size=T.SZ_NARRATIVE, bold=True, color=T.ON_DARK,
             h="center")
    _box(ws, l2, 8, l3, 11, color=T.BAND_DARK, style="thick")
    # the three gauges: doughnut arc + pie needle overlaid (same anchor, size and manual plot layout) + hub
    gw = ws
    feeds = [("comp", 0, 3, "نسبة تطبيق الملاحظات", [T.STATUS_MARK[v] for v in S.CLOSURE_VALUES], 5,
              "مؤشر نسبة تطبيق الملاحظات في الجولة المعروضة: القوس توزيع حالات الإغلاق، والمؤشر عند (المغلقة + المغلقة بشرط) ÷ الصادرة"),
             ("rate", 4, 5, "نسبة الإغلاق", [T.STATUS_MARK[S.CLOSED], T.TRACK_DARK], 3,
              "مؤشر نسبة الإغلاق في الجولة المعروضة: المغلقة ÷ الصادرة"),
             ("sus", 6, 7, "استدامة الإغلاق", [T.SECTION, T.TRACK_DARK], 3,
              "مؤشر استدامة الإغلاق في الجولة المعروضة: المغلقة ÷ ما أُغلق في أي جولة")]
    for key, g1, g2, name, fills, npts, alt in feeds:
        arc = DoughnutChart(holeSize=52, firstSliceAng=270)
        arc.varyColors = True
        arc.add_data(Reference(gw, min_col=gt.cols[f"{key}_arc"], min_row=2, max_row=1 + npts), titles_from_data=False)
        s = arc.series[0]
        s.tx = SeriesLabel(v=name)
        for i in range(npts):
            pt_ = DataPoint(idx=i)
            if i < len(fills) and not (key == "comp" and i == 4):
                _mark(pt_, fills[i], T.DECK_SEPARATOR, T.DECK_SEPARATOR_EMU)
            else:
                _invisible(pt_)
            s.dPt.append(pt_)
        arc.legend = None
        arc.title = None
        arc.layout = _plot_layout()
        _bare(arc)
        needle = PieChart(firstSliceAng=270)
        needle.varyColors = True
        needle.add_data(Reference(gw, min_col=gt.cols[f"{key}_needle"], min_row=2, max_row=4), titles_from_data=False)
        s2 = needle.series[0]
        s2.tx = SeriesLabel(v=f"{name} – المؤشر")
        for i in range(3):
            pt_ = DataPoint(idx=i)
            if i == 1:
                _mark(pt_, T.ON_DARK, T.ON_DARK, T.OUTLINE_EMU)
            else:
                _invisible(pt_)
            s2.dPt.append(pt_)
        needle.legend = None
        needle.title = None
        needle.layout = _plot_layout()
        _bare(needle)
        r1, r2 = ROW["g_u1"], ROW["g_l3"]
        w, h = _anchor_chart(ws, arc, lay, g1, g2, r1, r2, info, f"gauge_{key}_arc", alt, "doughnut",
                             f"gauge.{key}_arc", [name])
        _anchor_chart(ws, needle, lay, g1, g2, r1, r2, info, f"gauge_{key}_needle", f"{alt} (المؤشر)", "pie",
                      f"gauge.{key}_needle", [name])
        # hub: centred on the circle's centre (the centre of the plot area = the centre of the chart box)
        cx = w / 2
        cy = h / 2
        hub = KIT_ROOT / T.ICON_DIR / T.HUB["file"]
        _add_picture(ws, info, lay, hub, g1, r1, 16, 16, f"محور مؤشر {name}", x_from_right=cx - 8, y=cy - 8,
                     key="hub", sha=T.HUB["sha256"])
        info.gauge_groups.append({"name": name, "charts": [f"gauge_{key}_arc", f"gauge_{key}_needle"],
                                  "grid": (g1, g2), "rows": (r1, r2), "center_px": (round(cx, 1), round(cy, 1)),
                                  "upper_rows": (ROW["g_u1"], ROW["g_u3"]), "lower_rows": (ROW["g_l1"], ROW["g_l3"])})


def _distribution(ws, info, lay: Plan, reg, refs, tr, lg):
    ROW = lay.rows
    t1, b1, b3, lr, pad = ROW["dist_title"], ROW["dist_bar"], ROW["dist_bar"] + 2, ROW["dist_legend"], ROW["dist_pad"]
    _fill(ws, t1, 0, pad, NGRID - 1, T.CARD)
    _text(ws, t1, 0, NGRID - 1, "توزيع حالات الإغلاق في الجولة المعروضة", size=T.SZ_NARRATIVE, bold=True, wrap=False)
    ws.cell(row=t1, column=gc(0)).alignment = st.align("right", "center", False, indent=1)
    for i in range(4):
        g1 = 3 * i
        _formula(ws, reg, lr, g1, g1 + 2, f"{lg.cell('text', i + 1, sheet=True)}", lambda v, i=i: v.legend()[i],
                 bold=True, h="center", fill=T.STATUS_FILL[S.CLOSURE_VALUES[i]], wrap=False)
    _box(ws, t1, 0, pad, NGRID - 1)
    ch = BarChart()
    ch.type = "bar"
    ch.grouping = "percentStacked"
    ch.overlap = 100
    ch.gapWidth = 30
    bar = refs.tables["bar"]
    for col, value in (("closed", S.CLOSED), ("cond", S.CLOSED_COND), ("req", S.REQUIRES_EDIT), ("open", S.OPEN)):
        ch.add_data(Reference(ws, min_col=bar.cols[col], min_row=2, max_row=2), titles_from_data=False)
        s = ch.series[-1]
        s.tx = SeriesLabel(v=value)
        _mark(s, T.STATUS_MARK[value], T.CHART_OUTLINE, T.OUTLINE_EMU)
        s.dLbls = DataLabelList(showVal=True, showSerName=False, showCatName=False, showLegendKey=False)
        s.dLbls.numFmt = "0;;;"
        s.dLbls.txPr = _txpr(10, T.INK, True)
    ch.set_categories(Reference(ws, min_col=bar.cols["label"], min_row=2, max_row=2))
    ch.legend = None
    ch.title = None
    ch.y_axis.number_format = "0%"
    ch.y_axis.scaling.orientation = "maxMin"          # RTL: the bar starts at the right edge
    ch.y_axis.delete = True
    ch.x_axis.delete = True
    ch.y_axis.majorGridlines = None
    ch.layout = _plot_layout()
    _bare(ch)
    _anchor_chart(ws, ch, lay, 0, NGRID - 1, b1, b3, info, "status_distribution",
                  "توزيع حالات الإغلاق في الجولة المعروضة: شريط واحد بنسب المغلقة والمغلقة بشرط ويتطلب تعديل والمفتوحة",
                  "bar/percentStacked", "bar.closed..bar.open", [S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN],
                  inset_px=2)


def _axis(ax, *, gridlines: bool = False):
    from openpyxl.chart.axis import ChartLines
    ax.delete = False
    ax.txPr = _txpr(9, T.CHART_TEXT)
    ax.graphicalProperties = GraphicalProperties(ln=LineProperties(solidFill=T.CHART_GRID))
    if gridlines:
        ax.majorGridlines = ChartLines(spPr=GraphicalProperties(ln=LineProperties(solidFill=T.CHART_GRID,
                                                                                  prstDash="dash")))
    else:
        ax.majorGridlines = None


def _round_charts(ws, info, lay: Plan, tr, R: int):
    ROW = lay.rows
    tr_, c1, c2 = ROW["chart_title"], ROW["chart"], ROW["chart"] + 11
    _fill(ws, tr_, 0, c2, NGRID - 1, T.CARD)
    _text(ws, tr_, 0, 5, "حالات الإغلاق في كل جولة", size=T.SZ_NARRATIVE, bold=True, wrap=False)
    _text(ws, tr_, 6, 11, "اتجاه نسبة الإغلاق ونسبة التطبيق", size=T.SZ_NARRATIVE, bold=True, wrap=False)
    for g in (0, 6):
        ws.cell(row=tr_, column=gc(g)).alignment = st.align("right", "center", False, indent=1)
    _box(ws, tr_, 0, c2, 5)
    _box(ws, tr_, 6, c2, 11)
    n = max(R, 1)
    cats = Reference(ws, min_col=tr.cols["label"], min_row=2, max_row=1 + n)
    c = BarChart()
    c.type = "col"
    c.grouping = "stacked"
    c.overlap = 100
    c.gapWidth = 60
    for col, value in (("closed", S.CLOSED), ("cond", S.CLOSED_COND), ("req", S.REQUIRES_EDIT), ("open", S.OPEN)):
        c.add_data(Reference(ws, min_col=tr.cols[col], min_row=2, max_row=1 + n), titles_from_data=False)
        s = c.series[-1]
        s.tx = SeriesLabel(v=value)
        _mark(s, T.STATUS_MARK[value], T.CHART_OUTLINE, T.OUTLINE_EMU)
        s.dLbls = DataLabelList(showVal=True, showSerName=False, showCatName=False, showLegendKey=False)
        s.dLbls.numFmt = "0;;;"
        s.dLbls.txPr = _txpr(9, T.INK, True)
    c.set_categories(cats)
    c.title = None
    _axis(c.x_axis)
    _axis(c.y_axis, gridlines=True)
    c.x_axis.scaling.orientation = "maxMin"             # RTL: the first round at the right
    c.y_axis.number_format = "0"
    c.legend.position = "b"
    c.legend.txPr = _txpr(9, T.CHART_TEXT)
    _bare(c)
    _anchor_chart(ws, c, lay, 0, 5, c1, c2, info, "round_composition",
                  "حالات الإغلاق في كل جولة: أعمدة مكدسة لعدد المغلقة والمغلقة بشرط ويتطلب تعديل والمفتوحة",
                  "col/stacked", "trend.closed..trend.open", [S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN],
                  inset_px=3)
    ln = LineChart()
    for col, name, color, dash, symbol in (("rate", "نسبة الإغلاق", T.RATE_LINE, None, "circle"),
                                           ("impl", "نسبة تطبيق الملاحظات", T.IMPL_LINE, "dash", "diamond")):
        ln.add_data(Reference(ws, min_col=tr.cols[col], min_row=2, max_row=1 + n), titles_from_data=False)
        s = ln.series[-1]
        s.tx = SeriesLabel(v=name)
        s.smooth = False
        s.graphicalProperties = GraphicalProperties(ln=LineProperties(solidFill=color, w=T.LINE_EMU, prstDash=dash))
        s.marker = Marker(symbol=symbol, size=7)
        s.marker.graphicalProperties = GraphicalProperties(solidFill=color, ln=LineProperties(solidFill=color))
        s.dLbls = DataLabelList(showVal=True, showSerName=False, showCatName=False, showLegendKey=False)
        s.dLbls.numFmt = "0%"
        s.dLbls.position = "t" if col == "rate" else "b"
        s.dLbls.txPr = _txpr(9, color, True)
    ln.set_categories(cats)
    ln.title = None
    _axis(ln.x_axis)
    _axis(ln.y_axis, gridlines=True)
    ln.x_axis.scaling.orientation = "maxMin"
    ln.y_axis.number_format = "0%"
    ln.y_axis.scaling.min = 0
    ln.y_axis.scaling.max = 1
    ln.legend.position = "b"
    ln.legend.txPr = _txpr(9, T.CHART_TEXT)
    _bare(ln)
    _anchor_chart(ws, ln, lay, 6, 11, c1, c2, info, "rate_trend",
                  "اتجاه نسبة الإغلاق (خط متصل) ونسبة تطبيق الملاحظات (خط متقطع) عبر الجولات المسجلة",
                  "line", "trend.rate, trend.impl", ["نسبة الإغلاق", "نسبة تطبيق الملاحظات"], inset_px=3)


def _matrix(ws, info, lay: Plan, reg, refs, obs_t, M):
    ROW = lay.rows
    mt, mh, m0, mn = ROW["m_title"], ROW["m_head"], ROW["m_rows"], ROW["m_note"]
    _fill(ws, mt, 0, mn + 1, NGRID - 1, T.CARD)
    _formula(ws, reg, mt, 0, NGRID - 1, f'"مقارنة جولتين: من "&{M("compare_label")}&" إلى "&{M("selected_label")}',
             lambda v: f"مقارنة جولتين: من {S.round_label(v.C)} إلى {S.round_label(v.S)}", size=T.SZ_NARRATIVE,
             bold=True, wrap=False)
    ws.cell(row=mt, column=gc(0)).alignment = st.align("right", "center", False, indent=1)
    _formula(ws, reg, mh, 0, 1, f'"في "&{M("compare_label")}&" / في "&{M("selected_label")}',
             lambda v: f"في {S.round_label(v.C)} / في {S.round_label(v.S)}", size=T.SZ_NOTE, bold=True, h="center",
             fill=T.SECTION)
    cols = [(1, S.CLOSED), (2, S.CLOSED_COND), (3, S.REQUIRES_EDIT), (4, S.OPEN)]
    for j, (_, value) in enumerate(cols):
        _text(ws, mh, 2 + 2 * j, 3 + 2 * j, value, bold=True, h="center", fill=T.STATUS_FILL[value])
    rows = [(0, "لم تكن مطروحة"), (1, S.CLOSED), (2, S.CLOSED_COND), (3, S.REQUIRES_EDIT), (4, S.OPEN)]
    for i, (rc, rlabel) in enumerate(rows):
        rr = m0 + i
        _text(ws, rr, 0, 1, rlabel, bold=True, h="center", fill=T.STATUS_FILL.get(rlabel, T.NOT_RAISED_FILL))
        for j, (cc, _) in enumerate(cols):
            g1 = 2 + 2 * j
            _formula(ws, reg, rr, g1, g1 + 1,
                     f'COUNTIFS({obs_t.rng("codeC", sheet=True)},{rc},{obs_t.rng("codeS", sheet=True)},{cc})',
                     lambda v, rc=rc, cc=cc: v.matrix().get((rc, cc), 0), size=T.SZ_SECONDARY_VALUE, bold=True,
                     h="center")
            if rc == cc:
                _box(ws, rr, g1, rr, g1 + 1, color=T.INK)
    ws.conditional_formatting.add(f"{L(gc(2))}{m0}:{L(gc(9))}{m0 + 4}",
                                  ColorScaleRule(start_type="min", start_color="FF" + T.HEAT_LOW,
                                                 end_type="max", end_color="FF" + T.HEAT_HIGH))
    _text(ws, m0, 10, 11, "", r2=m0 + 4)
    _text(ws, mn, 0, NGRID - 1, "تبيّن المصفوفة عدد الملاحظات بحسب حالتها في الجولتين. القطر يمثل الملاحظات التي لم تتغير "
          "حالتها، وصف \"مغلقة\" في جولة المقارنة مع عمود غير \"مغلقة\" يمثل الملاحظات المعاد فتحها.",
          size=T.SZ_NOTE, color=T.MUTED, v="top", r2=mn + 1)
    _box(ws, mt, 0, mn + 1, NGRID - 1)


def _cards(ws, info, lay: Plan, reg, refs, an, schema, data_sheet):
    """One card per observation in observation-number order; card k starts at CARD0 + (k − 1) × 17 (spec 5 H)."""
    t = refs.tables
    obs_t, lt, rt = t["obs"], t["long"], t["round"]
    Sx, Rx = "crms_S", "crms_R"
    R = an.R
    pills, caps, strips, mutes, titles = [], [], [], [], []
    for a in an.obs:
        k = a.k
        b = lay.card_row(k)
        info.card_rows.append(b)
        rows = {name: b + off for name, (off, _) in CARD.items()}
        O = lambda col: obs_t.cell(col, k, sheet=True)        # noqa: E731
        idx = f"({k}-1)*{Rx}+{Sx}"
        ex = f"INDEX({lt.rng('exists', sheet=True)},{idx})"
        LT = lambda col, i=idx: f"INDEX({lt.rng(col, sheet=True)},{i})"   # noqa: E731

        def cf(key, default=""):
            return lambda v, a=a, key=key: v.card(a).get(key, default)

        def hide(f):
            return f'IF({ex}=0,"",{f})'
        _fill(ws, rows["head"], 0, rows["links"], NGRID - 1, T.CARD)
        # 2 header: chip, title, status pill, change label
        _text(ws, rows["head"], 0, 0, a.reader_label, size=T.SZ_CHIP, bold=True, color=T.ON_DARK, h="center",
              fill=T.INK, wrap=False)
        tc_ = _text(ws, rows["head"], 1, 8, a.title_disp, size=T.SZ_DETAIL_HEAD, bold=True)
        tc_.alignment = st.align("right", "center", True, indent=1)
        titles.append(tc_.coordinate)
        pc = _formula(ws, reg, rows["head"], 9, 10, f'IF({ex}=0,"{S.NOT_RAISED}",{LT("value")})', cf("pill"),
                      bold=True, h="center")
        pills.append(pc.coordinate)
        _formula(ws, reg, rows["head"], 11, 11, hide(LT("change")), cf("change"), size=T.SZ_NOTE, h="center")
        caps.append((rows["cap"], pc.coordinate))
        # 3 locations
        _formula(ws, reg, rows["loc_l"], 0, 5, hide('"الموضع عند الإصدار"'),
                 lambda v, a=a: "الموضع عند الإصدار" if a.long[v.S].exists else "", size=T.SZ_NOTE, color=T.MUTED)
        _formula(ws, reg, rows["loc_l"], 6, 11, hide('"الموضع الحالي"'),
                 lambda v, a=a: "الموضع الحالي" if a.long[v.S].exists else "", size=T.SZ_NOTE, color=T.MUTED)
        _formula(ws, reg, rows["loc_v"], 0, 5, hide(f'{O("location")}&""'), cf("loc"), v="top")
        _formula(ws, reg, rows["loc_v"], 6, 11, hide(f'{LT("cur_loc")}&""'), cf("cur_loc"), v="top")
        # 4 title tag and mechanical summary, only where no approved title exists
        approved = a.title_status in S.TITLE_SHOWN_STATES and a.title.strip()
        if not approved:
            _formula(ws, reg, rows["tag"], 0, 1, hide(f'"{CARD_TAG}"'),
                     lambda v, a=a: CARD_TAG if a.long[v.S].exists else "", size=T.SZ_NOTE, bold=True,
                     color=T.MUTED)
            _formula(ws, reg, rows["tag"], 2, 11, hide(f'{O("summary")}&""'), cf("summary"), color=T.MUTED,
                     wrap=False)

        def lab(row, g2, text, r2=None):
            return _formula(ws, reg, row, 0, g2, hide(f'"{text}"'),
                            lambda v, a=a, text=text: text if a.long[v.S].exists else "", size=T.SZ_NOTE, bold=True,
                            color=T.MUTED, v="top", r2=r2)
        # 5 the observation as issued (3 rows)
        lab(rows["obs"], 1, "الملاحظة كما صدرت", rows["obs3"])
        _formula(ws, reg, rows["obs"], 2, 11, hide(f'{O("comment_card")}&""'), cf("comment"), v="top",
                 r2=rows["obs3"])
        # 6 latest GCO feedback (2 rows)
        lab(rows["fb"], 1, "آخر مرئيات الحوكمة", rows["fb2"])
        _formula(ws, reg, rows["fb"], 2, 11,
                 hide(f'IF({Sx}=1,"لا توجد مرئيات متابعة في الجولة الأولى.",{LT("fb_cut")}&"")'), cf("feedback"),
                 v="top", r2=rows["fb2"])
        # 7 required action
        lab(rows["act"], 1, "الإجراء المطلوب")
        _formula(ws, reg, rows["act"], 2, 11, hide(f'{LT("action")}&""'), cf("action"), v="top")
        # 8 latest owner response | latest implementation claim, each with its round
        lfr, lfi = LT("lfr"), LT("lfi")
        lab(rows["resp"], 1, "آخر إفادة للإدارة")
        _formula(ws, reg, rows["resp"], 2, 5,
                 hide(f'IF({lfr}=0,"{S.NO_RESPONSE}",INDEX({lt.rng("resp", sheet=True)},({k}-1)*{Rx}+{lfr})'
                      f'&" ("&INDEX({rt.rng("label", sheet=True)},{lfr})&")")'), cf("resp"), v="top", size=T.SZ_NOTE)
        _formula(ws, reg, rows["resp"], 6, 7, hide('"آخر حالة تطبيق أفادت بها الإدارة"'),
                 lambda v, a=a: "آخر حالة تطبيق أفادت بها الإدارة" if a.long[v.S].exists else "", size=T.SZ_NOTE,
                 bold=True, color=T.MUTED, v="top")
        _formula(ws, reg, rows["resp"], 8, 11,
                 hide(f'IF({lfi}=0,"{S.NO_RESPONSE}",INDEX({lt.rng("impl", sheet=True)},({k}-1)*{Rx}+{lfi})'
                      f'&" ("&INDEX({rt.rng("label", sheet=True)},{lfi})&")")'), cf("impl"), v="top", size=T.SZ_NOTE)
        # 9 closure: round and basis words (09.2)
        lcr = LT("lcr")
        bs = f'INDEX({lt.rng("basis_static", sheet=True)},({k}-1)*{Rx}+{lcr})'
        lab(rows["close"], 1, "الإغلاق")
        _formula(ws, reg, rows["close"], 2, 11,
                 hide(f'IF({lcr}="","غير مغلقة في الجولة المعروضة","أُغلقت في "&INDEX({rt.rng("label", sheet=True)},'
                      f'{lcr})&"{S.SEP}أساس الإغلاق: "&IF({bs}="","{S.NOT_RECORDED}",{bs}))'), cf("closure"))
        # 10 timeline strip: rounds (window of eleven ending at the selected round; 1..11 while S ≤ 11)
        lab(rows["strip_l"], 0, "المسار", rows["strip_v"])
        start = f"MAX(1,{Sx}-10)"
        birth = O("birth")
        for i in range(11):
            g = 1 + i
            j = f"({start}+{i})"
            _formula(ws, reg, rows["strip_l"], g, g,
                     f'IF(OR({ex}=0,{j}>{Sx}),"",INDEX({rt.rng("label", sheet=True)},{j}))',
                     lambda v, a=a, i=i: v.strip(a, v.strip_start() + i)[0], size=T.SZ_NOTE, color=T.MUTED,
                     h="center", wrap=False)
            _formula(ws, reg, rows["strip_v"], g, g,
                     f'IF(OR({ex}=0,{j}>{Sx}),"",IF({j}<{birth},"لم تكن مطروحة",'
                     f'INDEX({lt.rng("value", sheet=True)},({k}-1)*{Rx}+{j})))',
                     lambda v, a=a, i=i: v.strip(a, v.strip_start() + i)[1], size=T.SZ_NOTE, bold=True,
                     h="center")
        strips.append(f"{L(gc(1))}{rows['strip_v']}:{L(gc(11))}{rows['strip_v']}")
        # 11 links: row, current response cell (rows not مغلقة in the current round), back to the list
        c = _formula(ws, reg, rows["links"], 0, 2,
                     hide(f'HYPERLINK({O("link_row")},"فتح الصف في ورقة الملاحظات")'),
                     lambda v, a=a: "فتح الصف في ورقة الملاحظات" if a.long[v.S].exists else "",
                     color=T.LINK, underline="single", wrap=False)
        info.link_cells.append(c.coordinate)
        open_now = a.long[R].value not in ("", S.CLOSED)
        c = _formula(ws, reg, rows["links"], 3, 5,
                     f'IF(OR({ex}=0,{O("vR")}="",{O("vR")}="{S.CLOSED}"),"",HYPERLINK({O("link")},'
                     f'"خلية الإفادة للجولة الحالية"))',
                     lambda v, a=a, o=open_now: "خلية الإفادة للجولة الحالية" if (a.long[v.S].exists and o) else "",
                     color=T.LINK, underline="single", wrap=False)
        info.link_cells.append(c.coordinate)
        c = _formula(ws, reg, rows["links"], 9, 11,
                     f'HYPERLINK("#{DASH}!{L(gc(0))}"&{O("list_row")},"العودة إلى القائمة")',
                     "العودة إلى القائمة", color=T.LINK, underline="single", h="left", wrap=False)
        info.link_cells.append(c.coordinate)
        _box(ws, rows["cap"], 0, rows["links"], NGRID - 1)
        mutes.append((rows["head"], pc.coordinate))
    # conditional formats over all cards (relative to the first card; one rule set, not one per card)
    if pills:
        from openpyxl.utils.cell import coordinate_from_string
        pill_rng = " ".join(f"{p}:{L(gc(10))}{coordinate_from_string(p)[1]}" for p in pills)
        _status_rules(ws, pill_rng, pills[0])
        cap_rng = " ".join(f"{L(gc(0))}{cr}:{L(gc(NGRID - 1))}{cr}" for cr, _ in caps)
        fr, fp = caps[0]
        anchor = f"${L(gc(9))}{fr + 1}"
        for value in S.CLOSURE_VALUES:
            ws.conditional_formatting.add(cap_rng, FormulaRule(formula=[f'{anchor}="{value}"'],
                                                               fill=st.fill(T.STATUS_MARK[value]), stopIfTrue=True))
        title_rng = " ".join(titles)
        ws.conditional_formatting.add(title_rng, FormulaRule(formula=[f'${L(gc(9))}{mutes[0][0]}="{S.NOT_RAISED}"'],
                                                             font=st.font(T.SZ_DETAIL_HEAD, bold=True, color=T.MUTED),
                                                             stopIfTrue=True))
        strip_rng = " ".join(strips)
        top_left = strips[0].split(":")[0]
        _status_rules(ws, strip_rng, top_left, size=T.SZ_NOTE)


def _logo(ws, info, lay: Plan, path: Path):
    """The supplied white-on-dark logo, unchanged, proportions kept, at g1–g3, about 44 px high (DASH_HEADER)."""
    import hashlib
    from PIL import Image
    with Image.open(path) as im:
        w0, h0 = im.size
    h = 44.0
    w = w0 * h / h0
    if w > 3 * COL_PX - 16:
        w = 3 * COL_PX - 16
        h = h0 * w / w0
    band = _rows_px(lay, lay.rows["hline"], lay.rows["doc"])
    _add_picture(ws, info, lay, path, 0, lay.rows["hline"], w, h, W.LOGO_ALT, x_from_right=8,
                 y=max(0.0, (band - h) / 2), key="logo", sha=hashlib.sha256(path.read_bytes()).hexdigest())


def _sheet_settings(ws, lay: Plan, doc, info: DashInfo):
    ws.protection.sheet = True                    # no password (SC-61); links stay clickable
    ws.protection.formatColumns = False
    ws.protection.formatRows = False
    ws.protection.selectLockedCells = False
    ws.protection.selectUnlockedCells = False
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:{L(gc(NGRID))}{lay.last_row}"
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    ws.page_margins.footer = 0.25
    name = doc.name.replace("&", "&&")
    ws.oddFooter.right.text = name
    ws.oddFooter.right.size = 9
    ws.oddFooter.right.font = "Calibri,Regular"
    ws.oddFooter.left.text = "صفحة &P من &N"
    ws.oddFooter.left.size = 9
    ws.oddFooter.left.font = "Calibri,Regular"
    # page breaks before each section band; cards never split (a break every two or three cards, by height)
    breaks = sorted(lay.bands[z] for z in ("closure", "queue", "rounds", "table", "help", "cards"))
    printable = (11.69 - 1.0) * 72 / ((8.27 - 0.8) * 72 / ((2 * W.MARGIN_WIDTH + NGRID * W.GRID_WIDTH) * 7 * 0.75))
    per_page = max(1, min(3, int((printable - 40) // CARD_HEIGHT)))
    if lay.N:
        for k in range(1 + per_page, lay.N + 1, per_page):
            breaks.append(lay.card_row(k))
    rb = RowBreak()
    for r in sorted(set(breaks)):
        rb.append(Break(id=r - 1))
    ws.row_breaks = rb
    info.notes.append(f"print: A4 portrait, one page wide, {len(rb.brk)} row breaks, {per_page} cards per page")
    sel = lay.sel_round.replace("$", "")
    ws.sheet_view.selection[0].activeCell = sel
    ws.sheet_view.selection[0].sqref = sel
