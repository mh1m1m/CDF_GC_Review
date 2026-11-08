"""Assembles the requester workbook: the one-sheet executive dashboard and the data sheet (kit 1.1.0).

Exactly two sheets (v7.15 draft of 10.4A.2): "لوحة المتابعة التنفيذية" first and active, then the data sheet of
10.4. The dashboard carries its own calculation block in hidden columns from R; no helper sheet is created, and a
workbook that still carries the v7.14 helper sheet "بيانات اللوحة" loses it once the block exists.

Two entry points:
* ``build_workbook`` renders a fresh workbook from the review state (rounds 1..n).
* ``assemble`` adds the dashboard to a workbook whose data sheet already exists (used by the migration, which
  keeps the data sheet as delivered).

Output is written atomically: a temporary file is produced, post-processed (cached values of the selected view,
app.xml without library names, alt text on every chart and image), reopened and checked, and only then moved over
the target (directive §10).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.workbook.properties import CalcProperties

from .. import ENGINE_VERSION, WORKBOOK_SCHEMA
from ..analytics.dashboard_analytics import Analytics, View
from ..config import round_schema as S
from ..config import design_tokens as T
from ..config import workbook_settings as W
from ..model.entities import DashboardViewState, ReviewState
from ..rounds.round_parser import RoundSchema
from .dash_layout import Layout as Plan, plan
from .dashboard_writer import DashInfo, write_dashboard
from .formula_registry import Registry
from .helper_writer import HelperRefs, write_helper
from .register_writer import write_data_sheet

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
RIYADH = ZoneInfo("Asia/Riyadh")


@dataclass
class BuildResult:
    path: Path
    state: ReviewState
    schema: RoundSchema
    analytics: Analytics
    view: View
    registry: Registry
    refs: HelperRefs
    dash: DashInfo
    data_sheet: str
    rows: dict[str, int]
    cached: bool
    build_time: dt.datetime
    warnings: list[str] = field(default_factory=list)


def default_view(an: Analytics, vs: DashboardViewState | None) -> View:
    if vs is None:
        return an.view(an.R, S.SCOPE_ALL, an.default_reader_label(), max(1, an.R - 1))
    return an.view(vs.selected_round, vs.scope, vs.selected_reader or an.default_reader_label(),
                   getattr(vs, "compare_round", None) or max(1, vs.selected_round - 1))


def assemble(wb, state: ReviewState, data_ws, schema: RoundSchema, rows: dict[str, int], *,
             view_state: DashboardViewState | None = None, logo_path=None):
    """Add the one-sheet dashboard (with its calculation block) in front of ``data_ws``.

    ``logo_path`` is the official white-on-dark logo file (DASH_HEADER); None or False leaves the logo slot empty.
    """
    data_sheet = data_ws.title
    an = Analytics(state, rows, round_cols=schema.blocks, data_sheet=data_sheet)
    view = default_view(an, view_state)
    reg = Registry()
    lay = plan(len(an.obs), an.R, len(an.view(an.R).queue))
    last_row = max(rows.values()) if rows else 1
    for name in (W.DASHBOARD_SHEET,):
        if name in wb.sheetnames:                     # a derived sheet is rebuilt, never edited (10.4A.15)
            del wb[name]
    ws = wb.create_sheet(W.DASHBOARD_SHEET, 0)
    refs = write_helper(wb, ws, an, schema, lay, reg, data_sheet=data_sheet,
                        data_last_row=max(last_row, data_ws.max_row), data_last_col=schema.last_col, state=state)
    logo = str(logo_path) if logo_path and Path(logo_path).exists() else None
    dash = write_dashboard(wb, ws, an, view, schema, refs, reg, state, data_sheet=data_sheet, lay=lay,
                           logo_path=logo)
    if W.HELPER_SHEET in wb.sheetnames:               # v7.14 helper sheet: removed once the block exists
        del wb[W.HELPER_SHEET]
    order = [wb[W.DASHBOARD_SHEET], data_ws]
    others = [s for s in wb._sheets if s not in order]
    wb._sheets = order + others
    for s in wb.worksheets:
        s.sheet_view.tabSelected = False
    wb.active = 0
    wb[W.DASHBOARD_SHEET].sheet_view.tabSelected = True
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    return an, view, reg, refs, dash


def set_properties(wb, state: ReviewState, build_time: dt.datetime, *, working_copy: bool = False):
    p = wb.properties
    p.creator = W.AUTHOR
    p.lastModifiedBy = W.AUTHOR
    p.title = W.workbook_title(state.document.name, state.current_round)
    p.created = build_time.astimezone(dt.timezone.utc).replace(tzinfo=None)
    p.modified = p.created
    p.subject = None
    keywords = ["بيانات تجريبية"] if state.document.is_demo else []
    if working_copy:                          # release gate: an unauthorised build is marked in the package itself
        from ..release.authorization_gate import WORKING_COPY_KEYWORD, WORKING_COPY_MARK
        keywords.append(WORKING_COPY_KEYWORD)
    p.keywords = "؛ ".join(keywords) if keywords else None
    p.description = None
    p.category = WORKING_COPY_MARK if working_copy else None


def build_workbook(state: ReviewState, out_path, *, view_state: DashboardViewState | None = None,
                   write_cache: bool = True, build_time: dt.datetime | None = None, logo_path=None,
                   guidance: bool = True, working_copy: bool = False) -> BuildResult:
    build_time = build_time or dt.datetime.now(RIYADH)
    wb = Workbook()
    wb.remove(wb.active)
    data_ws, schema = write_data_sheet(wb, state, guidance=guidance)
    rows = {o.internal_id: 2 + i for i, o in enumerate(state.ordered())}
    an, view, reg, refs, dash = assemble(wb, state, data_ws, schema, rows, view_state=view_state,
                                         logo_path=logo_path)
    set_properties(wb, state, build_time, working_copy=working_copy)
    out_path = Path(out_path)
    save_atomic(wb, out_path, reg.expected(view) if write_cache else None, build_time,
                alts=dash.chart_alts + dash.image_alts)
    return BuildResult(out_path, state, schema, an, view, reg, refs, dash, data_ws.title, rows, write_cache, build_time)


# ------------------------------------------------------------------ saving
def save_atomic(wb, out_path: Path, cached: dict | None, build_time: dt.datetime, *, require_dashboard: bool = True,
                alts: list[str] | None = None):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=str(out_path.parent))
    os.close(fd)
    try:
        wb.save(tmp)
        postprocess(tmp, cached, build_time, alts=alts)
        chk = load_workbook(tmp)                  # must reopen before it replaces anything
        if require_dashboard and W.DASHBOARD_SHEET not in chk.sheetnames:
            raise RuntimeError("dashboard sheet missing after save")
        chk.close()
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _sheet_paths(z: zipfile.ZipFile) -> dict[str, str]:
    wbx = etree.fromstring(z.read("xl/workbook.xml"))
    rels = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {r.get("Id"): r.get("Target") for r in rels}
    out = {}
    for sh in wbx.iter(f"{{{NS_MAIN}}}sheet"):
        target = rid_to_target[sh.get(f"{{{NS_REL}}}id")]
        target = target.lstrip("/")
        out[sh.get("name")] = target if target.startswith("xl/") else "xl/" + target
    return out


def _set_cached(root, values: dict[str, object]):
    for c in root.iter(f"{{{NS_MAIN}}}c"):
        f = c.find(f"{{{NS_MAIN}}}f")
        if f is None:
            continue
        coord = c.get("r")
        if coord not in values:
            continue
        val = values[coord]
        v = c.find(f"{{{NS_MAIN}}}v")
        if v is None:
            v = etree.SubElement(c, f"{{{NS_MAIN}}}v")
        if val is None or val == "":
            c.set("t", "str")
            v.text = ""
        elif isinstance(val, bool):
            c.set("t", "b")
            v.text = "1" if val else "0"
        elif isinstance(val, (int, float)):
            if "t" in c.attrib:
                del c.attrib["t"]
            v.text = repr(float(val)) if isinstance(val, float) else str(val)
        elif isinstance(val, str) and val.startswith("#") and val.endswith(("!", "?", "A")) and len(val) <= 7:
            c.set("t", "e")
            v.text = val
        else:
            c.set("t", "str")
            v.text = str(val)


APP_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
           'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
           '<DocSecurity>0</DocSecurity><ScaleCrop>false</ScaleCrop>'
           f'<Company>{W.COMPANY}</Company><LinksUpToDate>false</LinksUpToDate>'
           '<SharedDoc>false</SharedDoc><HyperlinksChanged>false</HyperlinksChanged></Properties>')


def postprocess(path, cached: dict | None, build_time: dt.datetime, *, alts: list[str] | None = None):
    """Write cached results for the selected view, library-free app properties (09.4, D5) and the alt text of every
    chart and image of the dashboard (spec 7.5: ``alts`` in drawing order, charts then images)."""
    path = str(path)
    by_sheet: dict[str, dict[str, object]] = {}
    for (sheet, coord), val in (cached or {}).items():
        by_sheet.setdefault(sheet, {})[coord] = val
    tmp = path + ".pp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        paths = _sheet_paths(zin)
        rev = {v: k for k, v in paths.items()}
        dash_drawing = _drawing_of(zin, paths.get(W.DASHBOARD_SHEET)) if alts else None
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/app.xml":
                data = APP_XML.encode("utf-8")
            elif item.filename == "docProps/core.xml":
                data = _fix_core(data, build_time)
            elif re.fullmatch(r"xl/comments/comment\d+\.xml", item.filename):
                data = _note_runs(data)
            elif re.fullmatch(r"xl/drawings/commentsDrawing\d+\.vml", item.filename):
                data = _note_vml(data)
            elif dash_drawing and item.filename == dash_drawing:
                data = _alt_text(data, alts)
            elif item.filename in rev and rev[item.filename] in by_sheet:
                root = etree.fromstring(data)
                _set_cached(root, by_sheet[rev[item.filename]])
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = item.external_attr
            zout.writestr(zi, data)
    os.replace(tmp, path)


def _drawing_of(z: zipfile.ZipFile, sheet_part: str | None) -> str | None:
    if not sheet_part:
        return None
    d, f = os.path.split(sheet_part)
    rp = f"{d}/_rels/{f}.rels"
    if rp not in z.namelist():
        return None
    for r in etree.fromstring(z.read(rp)):
        if r.get("Type", "").endswith("/drawing"):
            t = r.get("Target")
            if t.startswith("/"):                           # openpyxl writes absolute part names
                return t.lstrip("/")
            return os.path.normpath(os.path.join(d, t)).replace("\\", "/")
    return None


XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"


def _alt_text(data: bytes, alts: list[str]) -> bytes:
    """Alt text (``descr``) on every chart frame and picture: openpyxl numbers them 1..n in drawing order."""
    root = etree.fromstring(data)
    for el in root.iter(f"{{{XDR}}}cNvPr"):
        i = int(el.get("id") or 0)
        if 1 <= i <= len(alts):
            el.set("descr", alts[i - 1])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


NOTE_FONT_SIZE = 9
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _note_runs(data: bytes) -> bytes:
    """Notes in Calibri 9 (D.9, D.12): plain note text becomes one run with explicit run properties."""
    root = etree.fromstring(data)
    q = lambda t: f"{{{MAIN_NS}}}{t}"  # noqa: E731
    for text in root.iter(q("text")):
        plain = [c for c in text if c.tag == q("t")]
        if not plain or len(plain) != len(text):
            for rpr in text.iter(q("rPr")):
                for f in rpr.findall(q("rFont")):
                    f.set("val", T.FONT)
            continue
        value = "".join(t.text or "" for t in plain)
        for t in plain:
            text.remove(t)
        r = etree.SubElement(text, q("r"))
        rpr = etree.SubElement(r, q("rPr"))
        etree.SubElement(rpr, q("sz")).set("val", str(NOTE_FONT_SIZE))
        etree.SubElement(rpr, q("color")).set("rgb", "FF" + T.TEXT_BLACK)
        etree.SubElement(rpr, q("rFont")).set("val", T.FONT)
        etree.SubElement(rpr, q("family")).set("val", "2")
        t = etree.SubElement(r, q("t"))
        t.text = value
        if value != value.strip():
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _note_vml(data: bytes) -> bytes:
    """Note boxes right-aligned for Arabic text and filled with a design token instead of the library default."""
    s = data.decode("utf-8")
    s = s.replace("text-align:left", "text-align:right")
    s = re.sub(r'(fillcolor|color2)="#ffffe1"', lambda m: f'{m.group(1)}="#{T.NOTE_FILL}"', s, flags=re.I)
    return s.encode("utf-8")


def _fix_core(data: bytes, build_time: dt.datetime) -> bytes:
    root = etree.fromstring(data)
    ns = {"cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
          "dc": "http://purl.org/dc/elements/1.1/", "dcterms": "http://purl.org/dc/terms/",
          "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    stamp = build_time.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for tag in ("created", "modified"):
        el = root.find(f"dcterms:{tag}", ns)
        if el is None:
            el = etree.SubElement(root, f"{{{ns['dcterms']}}}{tag}")
            el.set(f"{{{ns['xsi']}}}type", "dcterms:W3CDTF")
        el.text = stamp
    lm = root.find("cp:lastModifiedBy", ns)
    if lm is None:
        lm = etree.SubElement(root, f"{{{ns['cp']}}}lastModifiedBy")
    lm.text = W.AUTHOR
    cr = root.find("dc:creator", ns)
    if cr is None:
        cr = etree.SubElement(root, f"{{{ns['dc']}}}creator")
    cr.text = W.AUTHOR
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
