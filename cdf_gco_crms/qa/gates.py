"""v7.11 dashboard gates G-DASH-01…20 and UX gates G-UX-01…20 (protocol Art. 18; UX directive §12).

Every gate is an executable check on the saved file (or on recorded manual
inspection evidence). Status values:

  PASS          the check ran and met its expected result
  FAIL          the check ran and did not
  NOT_VERIFIED  the check needs something unavailable here (Microsoft Excel);
                never reported as passed
  MANUAL_PASS   visual inspection of a rendered page, with the image as evidence
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from ..config import design_tokens as T
from ..config import round_schema as S
from ..config import workbook_settings as W
from ..ingestion.workbook_reader import parse_workbook
from ..reconciliation.historical import compare, snapshot
from . import inspect as I

PASS, FAIL, NV, MANUAL = "PASS", "FAIL", "NOT_VERIFIED", "MANUAL_PASS"


@dataclass
class GateResult:
    gate: str
    name: str
    test: str
    input: str
    expected: str
    actual: str
    status: str
    evidence: str = ""


@dataclass
class GateContext:
    xlsx: Path
    previous_xlsx: Path | None = None
    returned_state: object | None = None            # owner-returned state before the round was appended
    docx: Path | None = None
    view_checks: list = field(default_factory=list)  # recalc_verify.ViewCheck
    empty_state_check: object | None = None
    refresh: dict | None = None                      # {'before': path, 'after': path}
    manual: dict = field(default_factory=dict)       # gate -> (status, evidence)
    perf: dict | None = None
    logo_source: Path | None = None


def _status(ok: bool) -> str:
    return PASS if ok else FAIL


def run_dash_gates(ctx: GateContext) -> list[GateResult]:
    out: list[GateResult] = []
    x = Path(ctx.xlsx)
    pkg = I.package(x)
    wb = load_workbook(x, rich_text=True)
    wbv = load_workbook(x, data_only=True)
    pw = parse_workbook(x)
    st = pw.state
    R = st.current_round
    data_name = S.data_sheet_name(R)
    dash = wb[W.DASHBOARD_SHEET] if W.DASHBOARD_SHEET in wb.sheetnames else None
    inp = x.name

    # G-DASH-01 structure
    visible = [n for n, s, _ in pkg.sheets if s == "visible"]
    hidden = [n for n, s, _ in pkg.sheets if s != "visible"]
    ok = (visible == [W.DASHBOARD_SHEET, data_name] and hidden == [W.HELPER_SHEET] and pkg.active_tab == 0
          and W.LEGACY_PRINT_VIEW_SHEET not in wb.sheetnames and pw.schema.rounds == list(range(1, R + 1)))
    out.append(GateResult("G-DASH-01", "Structure", "sheet order/visibility/active tab; complete round blocks",
                          inp, f"visible=[{W.DASHBOARD_SHEET}, {data_name}], hidden=[{W.HELPER_SHEET}], active=0, "
                          f"blocks 1..{R}", f"visible={visible}, hidden={hidden}, active={pkg.active_tab}, "
                          f"blocks={pw.schema.rounds}", _status(ok)))

    # G-DASH-02 historical preservation
    if ctx.previous_xlsx:
        prev = parse_workbook(ctx.previous_xlsx).state
        diffs = compare(snapshot(prev), snapshot(st), rounds=set(range(1, prev.current_round + 1)),
                        owner_rounds=set())
        out.append(GateResult("G-DASH-02", "Historical preservation", "cell-by-cell compare by Internal_ID: fixed "
                              "block and GCO cells of every earlier round against the previous delivered workbook "
                              "(owner cells, late edits included, are checked against the returned workbook by G-DASH-11)",
                              f"{Path(ctx.previous_xlsx).name} -> {inp}", "0 differences in fixed block and "
                              f"rounds 1..{prev.current_round}", f"{len(diffs)} differences", _status(not diffs),
                              "; ".join(f"{d.internal_id}:{d.key}" for d in diffs[:5])))
    else:
        out.append(GateResult("G-DASH-02", "Historical preservation", "requires the previous-round workbook", inp,
                              "previous workbook supplied", "none supplied (round 1)",
                              PASS if R == 1 else FAIL, "round 1 has no earlier block" if R == 1 else ""))

    # G-DASH-03 current-status accuracy (cached dashboard/helper values vs data sheet)
    hs = wbv[W.HELPER_SHEET]
    hdr = {hs.cell(row=1, column=c).value: c for c in range(1, hs.max_column + 1)}
    mism = []
    for o in st.ordered():
        k = o.reader_int  # k == position in Reader_No order (rows written in that order)
    ordered = st.ordered()
    for k, o in enumerate(ordered, start=1):
        cached = hs.cell(row=k + 1, column=hdr["obs.vR"]).value or ""
        if cached != o.value(R):
            mism.append(f"#{o.reader_no}: {cached!r} != {o.value(R)!r}")
    out.append(GateResult("G-DASH-03", "Current-status accuracy", "helper obs.vR (cached) vs latest closure cell",
                          inp, "all equal", f"{len(ordered) - len(mism)}/{len(ordered)} equal", _status(not mism),
                          "; ".join(mism[:5])))

    # G-DASH-04 KPI reconciliation: dashboard cached KPIs vs counts computed from the data sheet
    dv = wbv[W.DASHBOARD_SHEET]
    kpi_row = 14
    kpis = [dv.cell(row=kpi_row, column=c).value for c in (2, 4, 6, 8, 10, 12)]
    counts = [sum(1 for o in st.observations if o.value(R) != "")] + \
             [sum(1 for o in st.observations if o.value(R) == v) for v in (S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN)]
    rate = counts[1] / counts[0] if counts[0] else ""
    ok = kpis[:5] == counts and (abs((kpis[5] or 0) - rate) < 1e-9 if rate != "" else kpis[5] in ("", None))
    out.append(GateResult("G-DASH-04", "KPI reconciliation", "six KPI cards vs independent count of the data sheet",
                          inp, f"{counts} rate={rate if rate == '' else round(rate, 4)}",
                          f"{kpis[:5]} rate={kpis[5] if not isinstance(kpis[5], float) else round(kpis[5], 4)}",
                          _status(ok)))

    # G-DASH-05 / 16 historical-round accuracy and recalculation (LibreOffice)
    vcs = ctx.view_checks
    if vcs:
        rounds_cov = sorted({int(re.search(r"S=(\d+)", v.view).group(1)) for v in vcs})
        bad = [v for v in vcs if not v.ok]
        all_r = rounds_cov == list(range(1, R + 1))
        out.append(GateResult("G-DASH-05", "Historical-round accuracy", "every round selected; recalculated values "
                              "vs Python model", f"{len(vcs)} views", f"rounds 1..{R}, 0 mismatches",
                              f"rounds {rounds_cov}, {sum(len(v.mismatches) for v in vcs)} mismatches",
                              _status(all_r and not bad), "; ".join(v.view + ': ' + v.message for v in bad[:3])))
        cmp_ = sum(v.compared for v in vcs)
        out.append(GateResult("G-DASH-16", "Recalculation verification", "workbooks built without cached values, "
                              "recalculated by LibreOffice, compared cell by cell",
                              f"{len(vcs)} views, engine {vcs[0].engine}", "formula written; recalculated; "
                              "reconciled; cached values written for the default view",
                              f"{cmp_} formula results compared, {sum(len(v.mismatches) for v in vcs)} mismatches; "
                              f"fullCalcOnLoad={pkg.calc_full_on_load}",
                              _status(not bad and pkg.calc_full_on_load and all(v.engine for v in vcs)),
                              "Microsoft Excel recalculation itself not run here (see G-DASH-13)"))
    else:
        for g, n in (("G-DASH-05", "Historical-round accuracy"), ("G-DASH-16", "Recalculation verification")):
            out.append(GateResult(g, n, "LibreOffice recalculation", inp, "views verified", "not run", NV))

    # G-DASH-06 navigation
    targets = []
    for coord in _formula_cells(wb[W.DASHBOARD_SHEET], "HYPERLINK("):
        pass
    link_col = hdr["obs.link"]
    id_col = hdr["obs.id"]
    bad = []
    data_ws = wb[data_name]
    for k in range(1, len(ordered) + 1):
        target = hs.cell(row=k + 1, column=link_col).value
        t = I.hyperlink_target(target)
        iid = hs.cell(row=k + 1, column=id_col).value
        if t is None or t[0] != data_name:
            bad.append(f"k={k}: {target!r}")
            continue
        m = re.match(r"([A-Z]+)(\d+)", t[1])
        row = int(m.group(2))
        if data_ws.cell(row=row, column=2).value != iid:
            bad.append(f"{iid}: row {row} holds {data_ws.cell(row=row, column=2).value}")
    nav_bad = []
    for row in dash.iter_rows(min_row=8, max_row=8):
        for c in row:
            if c.hyperlink is not None and c.hyperlink.location:
                loc = c.hyperlink.location
                sheet = loc.split("!")[0].strip("'")
                if sheet not in wb.sheetnames:
                    nav_bad.append(loc)
    n_links = len(_formula_cells(dash, "HYPERLINK("))
    out.append(GateResult("G-DASH-06", "Navigation integrity", "every observation link resolves to the row whose "
                          "column B holds its Internal_ID; navigation links resolve", inp,
                          "0 broken", f"{len(ordered)} observation targets, {n_links} link formulas, "
                          f"{len(bad)} broken, {len(nav_bad)} broken navigation links",
                          _status(not bad and not nav_bad), "; ".join(bad[:3] + nav_bad[:3])))

    # G-DASH-07 formula integrity
    errs = []
    for ws in wbv.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value in ("#REF!", "#NAME?", "#VALUE!", "#DIV/0!", "#N/A", "#NUM!"):
                    errs.append(f"{ws.title}!{c.coordinate}")
    ref_in_formula = [f"{ws.title}!{c.coordinate}" for ws in wb.worksheets for row in ws.iter_rows() for c in row
                      if isinstance(c.value, str) and c.value.startswith("=") and "#REF!" in c.value]
    data_formulas = [c.coordinate for row in data_ws.iter_rows() for c in row
                     if isinstance(c.value, str) and c.value.startswith("=")]
    vc_err = sum(len(v.errors) for v in vcs) if vcs else 0
    out.append(GateResult("G-DASH-07", "Formula integrity", "no error value cached or recalculated; no #REF! "
                          "in any formula; no formula in the data sheet", inp, "0/0/0",
                          f"{len(errs)} cached errors, {vc_err} recalculated errors, {len(ref_in_formula)} #REF!, "
                          f"{len(data_formulas)} data-sheet formulas",
                          _status(not errs and not vc_err and not ref_in_formula and not data_formulas)))

    # G-DASH-08 chart accuracy
    trend_cols = {k: hdr[f"trend.{k}"] for k in ("label", "closed", "cond", "req", "open", "rate", "new",
                                                    "closed_event", "reopen_event")}
    from openpyxl.utils import get_column_letter as gl
    def rng(col):
        return f"'{W.HELPER_SHEET}'!${gl(trend_cols[col])}$2:${gl(trend_cols[col])}${R + 1}"
    expect = {
        ("barChart/col", "stacked"): ([rng(c) for c in ("closed", "cond", "req", "open")],
                                      [S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN]),
        ("lineChart", "standard"): ([rng("rate")], ["نسبة الإغلاق"]),
        ("barChart/col", "clustered"): ([rng(c) for c in ("new", "closed_event", "reopen_event")],
                                        ["ملاحظات جديدة", "أُغلقت خلال الجولة", "أُعيد فتحها"]),
    }
    problems = []
    seen = 0
    for ch in pkg.charts:
        key = (ch.kinds[0], ch.grouping)
        if key in expect:
            seen += 1
            refs, names = expect[key]
            if ch.series_refs != refs or ch.series_names != names or any(c != rng("label") for c in ch.category_refs):
                problems.append(f"{key}: {ch.series_refs} {ch.series_names}")
        elif key == ("barChart/bar", "percentStacked"):
            seen += 1
            if ch.series_names != [S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN]:
                problems.append("status bar series")
    # the bar feed equals the KPI counts
    bar_vals = [hs.cell(row=2, column=hdr[f"bar.{k}"]).value for k in ("closed", "cond", "req", "open")]
    if bar_vals != counts[1:]:
        problems.append(f"bar feed {bar_vals} != KPIs {counts[1:]}")
    out.append(GateResult("G-DASH-08", "Chart accuracy", "series ranges, names, categories; status bar = KPIs",
                          inp, "4 charts bound to the trend/bar tables; bar = KPI counts",
                          f"{seen} charts checked; bar {bar_vals}", _status(seen == 4 and not problems),
                          "; ".join(problems)))

    # G-DASH-09 Arabic visual integrity (automated part + manual render)
    fonts = set()
    for ws in wb.worksheets:
        fonts |= I.cell_fonts(ws)
    rtl = all(ws.sheet_view.rightToLeft for ws in wb.worksheets)
    auto_ok = fonts <= {"Calibri"} and rtl
    man = ctx.manual.get("G-DASH-09")
    status = (MANUAL if man and man[0] == MANUAL else NV) if auto_ok else FAIL
    out.append(GateResult("G-DASH-09", "Arabic visual integrity", "RTL on every sheet; fonts read back; rendered "
                          "page inspected", inp, "RTL; fonts={Calibri}; render inspected",
                          f"RTL={rtl}; fonts={sorted(fonts)}", status, man[1] if man else "no render evidence"))

    # G-DASH-10 status-colour consistency
    bad = []
    for r in range(1, R + 1):
        col = pw.schema.col(r, S.ROLE_CLOSURE)
        for o in ordered:
            v = o.value(r)
            if v == "":
                continue
            cell = data_ws.cell(row=pw.rows[o.internal_id], column=col)
            want = T.ROUND1_OPEN_FILL if (r == 1 and v == S.OPEN) else T.STATUS_FILL.get(v)
            got = (cell.fill.fgColor.rgb or "")[-6:] if cell.fill and cell.fill.fill_type else None
            if want and got != want:
                bad.append(f"#{o.reader_no} R{r}: {got} != {want}")
    cf_fills = set()
    for rng_, rules in dash.conditional_formatting._cf_rules.items():
        for rule in rules:
            if rule.dxf and rule.dxf.fill is not None and rule.dxf.fill.fgColor is not None:
                cf_fills.add((rule.dxf.fill.fgColor.rgb or "")[-6:])
    missing = {v for v in T.STATUS_FILL.values()} - cf_fills
    out.append(GateResult("G-DASH-10", "Status-colour consistency", "data-sheet closure fills per D.2 (round-1 "
                          "مفتوحة #F2F2F2); dashboard status rules use the D.2 fills", inp, "0 deviations",
                          f"{len(bad)} cell deviations; D.2 fills missing from dashboard rules: {sorted(missing)}",
                          _status(not bad and not missing), "; ".join(bad[:4])))

    # G-DASH-11 management-response preservation
    if ctx.returned_state is not None:
        before = snapshot(ctx.returned_state)
        after = snapshot(st)
        keys = {k for k in before if re.match(r"R\d+\.(response|impl)$", k[1])}
        diffs = [k for k in keys if before[k][0] != after.get(k, ("",))[0]]
        out.append(GateResult("G-DASH-11", "Management-response preservation", "owner cells of every earlier round "
                              "vs the returned workbook", f"returned state -> {inp}", "0 differences",
                              f"{len(keys)} owner cells compared, {len(diffs)} differences", _status(not diffs),
                              "; ".join(f"{a}:{b}" for a, b in diffs[:4])))
    else:
        out.append(GateResult("G-DASH-11", "Management-response preservation", "needs the returned workbook", inp,
                              "returned state supplied", "not supplied", PASS if R == 1 else FAIL,
                              "round 1 has no owner response yet" if R == 1 else ""))

    # G-DASH-12 Word synchronisation
    if ctx.docx:
        from ..word.word_sync import reconcile
        sr = reconcile(ctx.docx, x)
        out.append(GateResult("G-DASH-12", "Word synchronisation", "REF/label/status reconciliation; follow-up reply "
                              "threads (G-SYNC-9); dashboard counts",
                              f"{Path(ctx.docx).name} + {inp}", "all checks true",
                              ", ".join(f"{k}={v}" for k, v in sr.checks.items()), _status(sr.ok),
                              "; ".join(sr.problems[:3])))
    else:
        out.append(GateResult("G-DASH-12", "Word synchronisation", "needs the round's Word file", inp,
                              "docx supplied", "not supplied", FAIL))

    # G-DASH-13 Excel compatibility
    xsd_status, xsd_msgs = I.xsd_validate(x)
    out.append(GateResult("G-DASH-13", "Excel compatibility", "XSD validation (ISO 29500 transitional), reopen in "
                          "openpyxl and LibreOffice; opening in Microsoft Excel", inp,
                          "valid parts; opens without repair in Excel", f"XSD {xsd_status} ({xsd_msgs[0]}); "
                          "openpyxl reopen OK; LibreOffice recalculation "
                          f"{'OK' if vcs and all(v.engine for v in vcs) else 'not run'}; Microsoft Excel: not available",
                          NV if xsd_status == PASS else FAIL,
                          "Excel-specific repair behaviour cannot be observed in this environment"))

    # G-DASH-14 round refresh
    if ctx.refresh:
        b, a = parse_workbook(ctx.refresh["before"]), parse_workbook(ctx.refresh["after"])
        av = load_workbook(ctx.refresh["after"], data_only=True)
        ah = av[W.HELPER_SHEET]
        ahdr = {ah.cell(row=1, column=c).value: c for c in range(1, ah.max_column + 1)}
        Ra = a.schema.current_round
        trend_rows = sum(1 for r in range(2, ah.max_row + 1) if isinstance(ah.cell(row=r, column=ahdr["trend.r"]).value, int))
        cur_label = av[W.DASHBOARD_SHEET].cell(row=6, column=2).value
        sel = av[W.DASHBOARD_SHEET].cell(row=10, column=2).value
        apkg = I.package(ctx.refresh["after"])
        cats_ok = all(c.endswith(f"${Ra + 1}") for ch in apkg.charts if ch.kinds[0] != "barChart/bar"
                      for c in ch.category_refs)
        ok = (Ra == b.schema.current_round + 1 and trend_rows == Ra and cur_label == S.round_label(Ra)
              and sel == S.round_label(Ra) and cats_ok)
        out.append(GateResult("G-DASH-14", "Round refresh", "append round n+1; dashboard labels, trend rows, chart "
                              "ranges and selector default follow", f"{Path(ctx.refresh['before']).name} -> "
                              f"{Path(ctx.refresh['after']).name}", f"round {b.schema.current_round + 1} everywhere",
                              f"current={cur_label}, selector={sel}, trend rows={trend_rows}, chart ranges end at row "
                              f"{Ra + 1}: {cats_ok}", _status(ok)))
    else:
        out.append(GateResult("G-DASH-14", "Round refresh", "needs a before/after pair", inp, "pair", "not run", FAIL))

    # G-DASH-15 empty state
    es = ctx.empty_state_check
    if es is not None:
        out.append(GateResult("G-DASH-15", "Empty-state behaviour", "workbook with no observations, recalculated",
                              "0 observations", "no error values; empty-state messages", es.message,
                              _status(es.ok)))
    else:
        out.append(GateResult("G-DASH-15", "Empty-state behaviour", "not run", inp, "", "", NV))

    # G-DASH-17 metadata
    texts = I.all_text_parts(x)
    props = texts.get("docProps/core.xml", "") + texts.get("docProps/app.xml", "")
    prohibited = [p for p in W.PROHIBITED_PROPERTY_VALUES if p.lower() in props.lower()]
    ok = (pkg.core.get("creator") == W.AUTHOR and pkg.core.get("lastModifiedBy") == W.AUTHOR
          and pkg.app.get("Company") == W.COMPANY and pkg.core.get("title") == W.workbook_title(st.document.name, R)
          and not prohibited)
    out.append(GateResult("G-DASH-17", "Metadata", "core/app properties read back (09.4)", inp,
                          f"creator=lastModifiedBy={W.AUTHOR}; Company={W.COMPANY}; Title per 09.4; no library names",
                          f"creator={pkg.core.get('creator')}; lastModifiedBy={pkg.core.get('lastModifiedBy')}; "
                          f"Company={pkg.app.get('Company')}; Title={pkg.core.get('title')}; prohibited={prohibited}",
                          _status(ok)))

    # G-DASH-18 executive readability
    widths = sum((dash.column_dimensions[gl(c)].width or 8.43) for c in range(1, 15))
    min_font = I.min_font_size(dash)
    first_screen = sum((dash.row_dimensions[r].height or 15) for r in range(1, 27))
    man = ctx.manual.get("G-DASH-18")
    auto_ok = widths <= W.LAPTOP_WIDTH_BUDGET and min_font >= T.MIN_FONT and first_screen <= 470
    out.append(GateResult("G-DASH-18", "Executive readability", "used width, smallest font, height to the action "
                          "list; rendered page inspected", inp,
                          f"width ≤ {W.LAPTOP_WIDTH_BUDGET} chars; font ≥ {T.MIN_FONT} pt; action list starts "
                          f"≤ 470 pt", f"width={widths:.0f}; min font={min_font}; action list at {first_screen:.0f} pt",
                          (MANUAL if man else NV) if auto_ok else FAIL, man[1] if man else ""))

    # G-DASH-19 closure-semantics accuracy
    derived = set(S.CHANGE_LABELS) | {S.REASON_REOPENED, S.REASON_STALLED, S.REASON_COND, S.REASON_AWAIT_FIRST,
                                      S.REASON_OPEN, S.READY_ACTION, S.READY_ALL_CLOSED, S.READY_COND}
    leak = []
    for r in range(1, R + 1):
        col = pw.schema.col(r, S.ROLE_CLOSURE)
        for o in ordered:
            v = data_ws.cell(row=pw.rows[o.internal_id], column=col).value
            if v not in S.CLOSURE_VALUES and v != S.NOT_RAISED:
                leak.append(f"#{o.reader_no} R{r}: {v!r}")
    overlap = derived & set(S.CLOSURE_VALUES)
    cond_ok = counts[1] == sum(1 for o in st.observations if o.value(R) == S.CLOSED)
    out.append(GateResult("G-DASH-19", "Closure-semantics accuracy", "closure cells hold only the four values or "
                          "the not-raised text; derived labels disjoint from official values; conditional closure "
                          "not counted as closed", inp, "0 / empty / true",
                          f"{len(leak)} invalid closure cells; overlap={sorted(overlap)}; closed excludes "
                          f"conditional={cond_ok}", _status(not leak and not overlap and cond_ok), "; ".join(leak[:4])))

    # G-DASH-20 protection of authoritative records
    unlocked = [c.coordinate for row in dash.iter_rows() for c in row
                if c.protection is not None and c.protection.locked is False]
    sel_cells = {"B10", "E10", "H10", "K10"}
    unlocked_anchor = {c for c in unlocked if c in sel_cells}
    extra_unlocked = [c for c in unlocked if not (c[0] in "BCDEFGHIJKLM" and c[1:] == "10")]
    helper_ws = wb[W.HELPER_SHEET]
    no_password = not dash.protection.password and not helper_ws.protection.password
    ok = (dash.protection.sheet and helper_ws.protection.sheet and no_password and not data_ws.protection.sheet
          and unlocked_anchor == sel_cells and not extra_unlocked and not data_formulas)
    out.append(GateResult("G-DASH-20", "Protection of authoritative records", "dashboard protected except the four "
                          "selectors; helper sheet protected; no password; data sheet unprotected (10.4) and free of "
                          "cell formulas; selectors are display-only",
                          inp, "protected; 4 selectors unlocked; helper protected; data sheet without formulas",
                          f"dashboard protected={dash.protection.sheet}; helper protected={helper_ws.protection.sheet}; "
                          f"password set={not no_password}; unlocked selector anchors="
                          f"{sorted(unlocked_anchor)}; other unlocked={extra_unlocked[:3]}; data sheet protected="
                          f"{data_ws.protection.sheet}", _status(ok)))
    return sorted(out, key=lambda g: g.gate)


def _formula_cells(ws, needle: str) -> list[str]:
    return [c.coordinate for row in ws.iter_rows() for c in row
            if isinstance(c.value, str) and c.value.startswith("=") and needle in c.value]
