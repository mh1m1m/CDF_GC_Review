"""Dashboard gates G-DASH-01…24 (protocol Art. 18; kit 1.1.0 one-sheet dashboard, v7.15 draft gates 21–24).

Every gate is an executable check on the saved file (or on recorded manual
inspection evidence). Status values:

  PASS          the check ran and met its expected result
  FAIL          the check ran and did not
  NOT_VERIFIED  the check needs something unavailable here (Microsoft Excel);
                never reported as passed
  MANUAL_PASS   visual inspection of a rendered page, with the image as evidence

Gates whose v7.14 wording the one-sheet design cannot meet before the v7.15 amendment is approved
(``W.AMENDMENT_DEPENDENT``) report NOT_VERIFIED when their check runs and meets the v7.15 draft, never PASS.
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


def _one_cell(ref: str) -> str:
    """A one-row range ("$A$2:$A$2", round 1) and its single-cell form ("$A$2") are the same reference."""
    return re.sub(r"(\$[A-Z]+\$\d+):\1$", r"\1", ref or "")


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


def amendment_cap(results: list) -> list:
    """A check that meets the v7.15 draft reports NOT_VERIFIED until the amendment is approved (spec 11)."""
    for g in results:
        if g.gate in W.AMENDMENT_DEPENDENT and g.status == PASS:
            g.status = NV
            g.evidence = (g.evidence + "; " if g.evidence else "") + f"check met; depends on the {W.AMENDMENT}"
    return results


def layout_of(st):
    """The row plan of the dashboard of a parsed workbook (same inputs as the build: N, R, rows not مغلقة at R)."""
    from ..excel.dash_layout import plan
    R = st.current_round
    qn = sum(1 for o in st.observations if o.value(R) not in ("", S.CLOSED))
    return plan(len(st.observations), R, qn)


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

    # G-DASH-01 structure (v7.15 draft of 10.4A.2: two sheets, the dashboard first and active, no helper sheet)
    lay = layout_of(st)
    visible = [n for n, s, _ in pkg.sheets if s == "visible"]
    hidden = [n for n, s, _ in pkg.sheets if s != "visible"]
    ok = (visible == [W.DASHBOARD_SHEET, data_name] and hidden == [] and len(pkg.sheets) == 2 and pkg.active_tab == 0
          and W.LEGACY_PRINT_VIEW_SHEET not in wb.sheetnames and W.HELPER_SHEET not in wb.sheetnames
          and pw.schema.rounds == list(range(1, R + 1)))
    out.append(GateResult("G-DASH-01", "Structure", "sheet set, order, visibility, active tab; complete round blocks",
                          inp, f"sheets=[{W.DASHBOARD_SHEET}, {data_name}], none hidden, active=0, blocks 1..{R}",
                          f"visible={visible}, hidden={hidden}, active={pkg.active_tab}, blocks={pw.schema.rounds}",
                          _status(ok), "v7.14 text requires the hidden helper sheet; the v7.15 draft retires it"))

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
    from ..ingestion.workbook_reader import calc_block
    hs, hdr = calc_block(wbv)
    mism = []
    for o in st.ordered():
        k = o.reader_int  # k == position in Reader_No order (rows written in that order)
    ordered = st.ordered()
    for k, o in enumerate(ordered, start=1):
        cached = hs.cell(row=k + 1, column=hdr["obs.vR"]).value or ""
        if cached != o.value(R):
            mism.append(f"#{o.reader_no}: {cached!r} != {o.value(R)!r}")
    out.append(GateResult("G-DASH-03", "Current-status accuracy", "block obs.vR (cached) vs latest closure cell",
                          inp, "all equal", f"{len(ordered) - len(mism)}/{len(ordered)} equal", _status(not mism),
                          "; ".join(mism[:5])))

    # G-DASH-04 KPI reconciliation: dashboard cached KPIs vs counts computed from the data sheet
    dv = wbv[W.DASHBOARD_SHEET]
    kpi_row = lay.rows["kpi_v"]
    kpis = [dv.cell(row=kpi_row, column=c).value for c in (2, 4, 6, 8, 10, 12)]
    # the round the saved view shows (the current round unless the file was saved on an earlier round)
    meta = {hs.cell(row=r, column=hdr["meta.key"]).value: hs.cell(row=r, column=hdr["meta.value"]).value
            for r in range(2, 60) if hs.cell(row=r, column=hdr["meta.key"]).value}
    Sv = int(meta.get("selected_round") or R)
    counts = [sum(1 for o in st.observations if o.value(Sv) not in ("", S.NOT_RAISED))] + \
             [sum(1 for o in st.observations if o.value(Sv) == v) for v in (S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN)]
    rate = counts[1] / counts[0] if counts[0] else ""
    ok = kpis[:5] == counts and (abs((kpis[5] or 0) - rate) < 1e-9 if rate != "" else kpis[5] in ("", None))
    out.append(GateResult("G-DASH-04", "KPI reconciliation", f"six KPI cards vs independent count of the data sheet "
                          f"(round {Sv}, the round the saved view shows)",
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
    for row in dash.iter_rows(min_row=1, max_row=lay.last_row, max_col=W.CALC_FIRST_COL - 1):
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
    fn_bad, prefixed, arrays = excel2010_scan(x)
    out.append(GateResult("G-DASH-07", "Formula integrity", "no error value cached or recalculated; no #REF! "
                          "in any formula; no formula in the data sheet; Excel 2010 functions only (10.4A.15): no "
                          "_xlfn/_xlpm/_xlws prefix, no array formula", inp, "0/0/0/0",
                          f"{len(errs)} cached errors, {vc_err} recalculated errors, {len(ref_in_formula)} #REF!, "
                          f"{len(data_formulas)} data-sheet formulas; functions outside the list={sorted(fn_bad)}; "
                          f"prefixed={prefixed}; array formulas={arrays}",
                          _status(not errs and not vc_err and not ref_in_formula and not data_formulas and not fn_bad
                                  and not prefixed and not arrays)))

    # G-DASH-08 chart accuracy (bound to the block's tables on the dashboard)
    from openpyxl.utils import get_column_letter as gl
    DQ = "'" + W.DASHBOARD_SHEET + "'"

    def col_rng(name, n):
        c = gl(hdr[name])
        return f"{DQ}!${c}$2:${c}${n + 1}"
    trng = lambda col: col_rng(f"trend.{col}", R)                     # noqa: E731
    expect = {
        ("barChart/col", "stacked"): ([trng(c) for c in ("closed", "cond", "req", "open")],
                                      [S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN], trng("label")),
        ("lineChart", "standard"): ([trng("rate"), trng("impl")], ["نسبة الإغلاق", "نسبة تطبيق الملاحظات"],
                                    trng("label")),
        ("barChart/bar", "percentStacked"): ([col_rng(f"bar.{c}", 1) for c in ("closed", "cond", "req", "open")],
                                             [S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN], col_rng("bar.label", 1)),
    }
    gauge_refs = {col_rng(f"gauge.{k}_arc", 5 if k == "comp" else 3) for k in ("comp", "rate", "sus")} | \
        {col_rng(f"gauge.{k}_needle", 3) for k in ("comp", "rate", "sus")}
    problems = []
    seen = 0
    gauges = 0
    for ch in pkg.charts:
        if ch.sheet != W.DASHBOARD_SHEET:
            continue
        key = (ch.kinds[0], ch.grouping)
        if ch.kinds[0] in ("doughnutChart", "pieChart"):
            gauges += 1
            if not all(_one_cell(r) in {_one_cell(x) for x in gauge_refs} for r in ch.series_refs):
                problems.append(f"gauge {ch.part}: {ch.series_refs}")
            continue
        if key in expect:
            seen += 1
            refs, names, cat = expect[key]
            if ([_one_cell(r) for r in ch.series_refs] != [_one_cell(r) for r in refs] or ch.series_names != names
                    or any(_one_cell(c) != _one_cell(cat) for c in ch.category_refs)):
                problems.append(f"{key}: {ch.series_refs} {ch.series_names}")
        else:
            problems.append(f"unexpected chart {key}")
    bar_vals = [hs.cell(row=2, column=hdr[f"bar.{k}"]).value for k in ("closed", "cond", "req", "open")]
    if bar_vals != counts[1:]:
        problems.append(f"bar feed {bar_vals} != KPIs {counts[1:]}")
    out.append(GateResult("G-DASH-08", "Chart accuracy", "series ranges, names, categories; status bar = KPIs; "
                          "gauges read the gauge table", inp,
                          "3 charts bound to the trend/bar tables, 6 gauge charts (3 arcs, 3 needles); bar = KPI counts",
                          f"{seen} charts and {gauges} gauge charts checked; bar {bar_vals}",
                          _status(seen == 3 and gauges == 6 and not problems), "; ".join(problems)))

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
                          FAIL if xsd_status == FAIL else NV,   # NOT_RUN (no schemas here) is NOT_VERIFIED
                          "Excel-specific repair behaviour cannot be observed in this environment"))

    # G-DASH-14 round refresh
    if ctx.refresh:
        b, a = parse_workbook(ctx.refresh["before"]), parse_workbook(ctx.refresh["after"])
        av = load_workbook(ctx.refresh["after"], data_only=True)
        ah, ahdr = calc_block(av)
        Ra = a.schema.current_round
        la = layout_of(a.state)
        trend_rows = sum(1 for r in range(2, ah.max_row + 1) if isinstance(ah.cell(row=r, column=ahdr["trend.r"]).value, int))
        cur_label = av[W.DASHBOARD_SHEET].cell(row=la.rows["fact_v"], column=2).value
        sel = av[W.DASHBOARD_SHEET].cell(row=la.rows["sel_v"], column=2).value
        apkg = I.package(ctx.refresh["after"])
        cats_ok = all(c.endswith(f"${Ra + 1}") for ch in apkg.charts
                      if ch.kinds[0] in ("barChart/col", "lineChart") for c in ch.category_refs)
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

    # G-DASH-18 executive readability (spec 1.1: the first screen answers where the review stands and what the
    # owning department must do; the action list follows the gauge deck and is one click away by its chip)
    widths = sum((dash.column_dimensions[gl(c)].width or 8.43) for c in range(1, 15))
    min_font = I.min_font_size(dash)
    first_screen = sum((dash.row_dimensions[r].height or 15) for r in range(1, lay.rows["kpi_f"] + 1))
    to_list = sum((dash.row_dimensions[r].height or 15) for r in range(1, lay.q0))
    man = ctx.manual.get("G-DASH-18")
    auto_ok = widths <= W.LAPTOP_WIDTH_BUDGET and min_font >= T.MIN_FONT and first_screen <= 470
    out.append(GateResult("G-DASH-18", "Executive readability", "used width, smallest font, height of the facts and "
                          "KPI cards (first screen); position of the action list; rendered page inspected", inp,
                          f"width ≤ {W.LAPTOP_WIDTH_BUDGET} chars; font ≥ {T.MIN_FONT} pt; facts, required action "
                          f"and KPI cards within 470 pt", f"width={widths:.0f}; min font={min_font}; first screen ends "
                          f"at {first_screen:.0f} pt; action list starts at {to_list:.0f} pt (v7.14 asked ≤ 470 pt)",
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
    cond_ok = counts[1] == sum(1 for o in st.observations if o.value(Sv) == S.CLOSED)
    out.append(GateResult("G-DASH-19", "Closure-semantics accuracy", "closure cells hold only the four values or "
                          "the not-raised text; derived labels disjoint from official values; conditional closure "
                          "not counted as closed", inp, "0 / empty / true",
                          f"{len(leak)} invalid closure cells; overlap={sorted(overlap)}; closed excludes "
                          f"conditional={cond_ok}", _status(not leak and not overlap and cond_ok), "; ".join(leak[:4])))

    # G-DASH-20 protection of authoritative records
    sel_cells = {f"{gl(2 + g1)}{lay.rows['sel_v']}" for g1, _ in lay.selector_spans}
    allowed = {f"{gl(2 + g)}{lay.rows['sel_v']}" for g1, g2 in lay.selector_spans for g in range(g1, g2 + 1)}
    unlocked = [c.coordinate for row in dash.iter_rows() for c in row
                if c.protection is not None and c.protection.locked is False]
    extra_unlocked = [c for c in unlocked if c not in allowed]
    no_password = not dash.protection.password
    ok = (dash.protection.sheet and no_password and not data_ws.protection.sheet
          and sel_cells <= set(unlocked) and not extra_unlocked and not data_formulas)
    out.append(GateResult("G-DASH-20", "Protection of authoritative records", "dashboard protected without a password "
                          "except the four selectors; data sheet unprotected (10.4) and free of cell formulas; nothing "
                          "on the dashboard writes to it", inp, "protected; only the 4 selectors unlocked; data sheet "
                          "without formulas", f"dashboard protected={dash.protection.sheet}; password set="
                          f"{not no_password}; selector anchors unlocked={sorted(sel_cells & set(unlocked))}; other "
                          f"unlocked={extra_unlocked[:3]}; data sheet protected={data_ws.protection.sheet}", _status(ok),
                          "v7.14 text also asks for a protected helper sheet, which the v7.15 draft retires"))

    out += _new_gates(ctx, x, wb, wbv, pkg, pw, st, lay, hs, hdr, data_ws, data_name)
    return amendment_cap(sorted(out, key=lambda g: (g.gate[:6], int(re.sub(r"\D", "", g.gate) or 0))))


def _new_gates(ctx, x, wb, wbv, pkg, pw, st, lay, hs, hdr, data_ws, data_name) -> list[GateResult]:
    """G-DASH-21…24 of the v7.15 draft (spec 11.7)."""
    from openpyxl.utils import get_column_letter as gl
    from ..excel.dash_layout import CARD_STRIDE
    out = []
    inp = x.name
    dash = wb[W.DASHBOARD_SHEET]
    dv = wbv[W.DASHBOARD_SHEET]
    # G-DASH-21 two sheets, calculation block in hidden columns outside the print area, O..Q empty
    block_cols = sorted(set(hdr.values())) if hs is not None and hs.title == W.DASHBOARD_SHEET else []
    not_hidden = [gl(c) for c in range(W.CALC_FIRST_COL, (max(block_cols) if block_cols else 0) + 1)
                  if not dash.column_dimensions[gl(c)].hidden]
    grouped = [gl(c) for c in range(W.CALC_FIRST_COL, (max(block_cols) if block_cols else 0) + 1)
               if dash.column_dimensions[gl(c)].outline_level]
    pa = str(dash.print_area or "")
    oq = [f"{gl(c)}{r}" for r in range(1, lay.last_row + 1) for c in range(15, W.CALC_FIRST_COL)
          if dash.cell(row=r, column=c).value not in (None, "")]
    ok = (len(wb.sheetnames) == 2 and W.HELPER_SHEET not in wb.sheetnames and bool(block_cols)
          and min(block_cols) >= W.CALC_FIRST_COL and not not_hidden and not grouped and pa.endswith(f"$A$1:$N${lay.last_row}")
          and not oq)
    out.append(GateResult("G-DASH-21", "Two-sheet structure and calculation block", "no third sheet; the block's "
                          "tables from column R, hidden (not grouped), outside the print area; O..Q empty", inp,
                          f"2 sheets; block ≥ R hidden; print area A1:N{lay.last_row}",
                          f"sheets={wb.sheetnames}; block columns {gl(min(block_cols)) if block_cols else '-'}.."
                          f"{gl(max(block_cols)) if block_cols else '-'}; not hidden={not_hidden[:3]}; grouped="
                          f"{grouped[:3]}; print area={pa}; O..Q values={oq[:3]}", _status(ok)))
    # G-DASH-22 gridlines hidden on both sheets
    gl_state = {ws.title: ws.sheet_view.showGridLines for ws in wb.worksheets}
    out.append(GateResult("G-DASH-22", "Gridlines hidden on both sheets", "showGridLines read back", inp,
                          "0 on every sheet", str(gl_state), _status(all(v is False for v in gl_state.values()))))
    # G-DASH-23 plotVisOnly 0 on every chart reading the block; overlaid gauges share anchor, size, plot layout
    import zipfile
    from lxml import etree
    bad_vis, anchors = [], {}
    with zipfile.ZipFile(x) as z:
        for ch in pkg.charts:
            root = etree.fromstring(z.read(ch.part))
            pv = root.find(".//c:plotVisOnly", I.NS)
            if pv is None or pv.get("val") not in ("0", "false"):
                bad_vis.append(ch.part)
        dpart = [t for n, s_, part in pkg.sheets if n == W.DASHBOARD_SHEET
                 for rid, (typ, t) in I._rels(z, part).items() if typ == "drawing"]
        layouts = {}
        if dpart:
            droot = etree.fromstring(z.read(dpart[0]))
            drel = I._rels(z, dpart[0])
            for anc in droot:
                gf = anc.find(".//c:chart", I.NS)
                if gf is None:
                    continue
                cpart = drel[gf.get(f"{{{I.NS['r']}}}id")][1]
                frm, ext = anc.find("xdr:from", I.NS), anc.find("xdr:ext", I.NS)
                anchors[cpart] = (frm.find("xdr:col", I.NS).text, frm.find("xdr:colOff", I.NS).text,
                                  frm.find("xdr:row", I.NS).text, frm.find("xdr:rowOff", I.NS).text,
                                  ext.get("cx"), ext.get("cy"))
                croot = etree.fromstring(z.read(cpart))
                ml = croot.find(".//c:plotArea/c:layout/c:manualLayout", I.NS)
                layouts[cpart] = tuple(ml.find(f"c:{k}", I.NS).get("val") if ml is not None and
                                       ml.find(f"c:{k}", I.NS) is not None else None for k in ("x", "y", "w", "h"))
    gauge_parts = [ch.part for ch in pkg.charts if ch.kinds[0] in ("doughnutChart", "pieChart")]
    pairs = [gauge_parts[i:i + 2] for i in range(0, len(gauge_parts), 2)]
    misaligned = [p for p in pairs if len(p) != 2 or anchors.get(p[0]) != anchors.get(p[1])
                  or layouts.get(p[0]) != layouts.get(p[1]) or layouts.get(p[0]) != ("0.05", "0.05", "0.9", "0.9")]
    out.append(GateResult("G-DASH-23", "plotVisOnly and gauge overlays", "plotVisOnly=0 on every chart (the block's "
                          "columns are hidden); each gauge's arc and needle share anchor, size and manual plot layout "
                          "0.05/0.05/0.9/0.9", inp, f"{len(pkg.charts)} charts with plotVisOnly 0; 3 aligned pairs",
                          f"plotVisOnly not 0: {bad_vis}; gauge pairs {len(pairs)}, misaligned {misaligned}",
                          _status(not bad_vis and len(pairs) == 3 and not misaligned),
                          "overlay alignment and hub position as Excel draws them: NOT_VERIFIED (G-DASH-13)"))
    # G-DASH-24 links resolve; card count = observation count; back links land on the observation's list row
    ordered = st.ordered()
    N = len(ordered)
    problems = []
    cards = [c.row for c in dash[gl(2)][:lay.last_row] if isinstance(c.value, str) and c.font is not None
             and c.font.sz == T.SZ_CHIP and c.value.startswith("#")]
    if len(cards) != N:
        problems.append(f"{len(cards)} cards for {N} observations")
    for k, o in enumerate(ordered, start=1):
        cr = hs.cell(row=k + 1, column=hdr["obs.card_row"]).value
        if cr != lay.card0 + (k - 1) * CARD_STRIDE or dash.cell(row=cr + 1, column=2).value != f"#{o.reader_no}":
            problems.append(f"#{o.reader_no}: card row {cr}")
        lr = hs.cell(row=k + 1, column=hdr["obs.list_row"]).value
        qpos = hs.cell(row=k + 1, column=hdr["obs.qpos"]).value
        if qpos in (None, "") or (isinstance(qpos, (int, float)) and qpos > lay.QN):
            if lr != lay.bands["queue"]:
                problems.append(f"#{o.reader_no}: back link {lr} != zone D {lay.bands['queue']}")
        elif dv.cell(row=lr, column=2).value != f"#{o.reader_no}":
            problems.append(f"#{o.reader_no}: back link row {lr} shows {dv.cell(row=lr, column=2).value!r}")
        t = I.hyperlink_target(hs.cell(row=k + 1, column=hdr["obs.link_row"]).value)
        if t is None or t[0] != data_name or data_ws[t[1]].row != pw.rows.get(o.internal_id):
            problems.append(f"#{o.reader_no}: row link {t}")
    statics = []
    for row in dash.iter_rows(min_row=1, max_row=lay.last_row, max_col=W.CALC_FIRST_COL - 1):
        for c in row:
            if c.hyperlink is not None and c.hyperlink.location:
                sheet, _, coord = c.hyperlink.location.rpartition("!")
                sheet = sheet.strip("'")
                if sheet not in wb.sheetnames or not re.fullmatch(r"\$?[A-Z]+\$?\d+", coord):
                    statics.append(c.hyperlink.location)
    n_formula_links = sum(1 for row in dash.iter_rows(max_col=W.CALC_FIRST_COL - 1) for c in row
                          if isinstance(c.value, str) and c.value.startswith("=") and "HYPERLINK(" in c.value)
    out.append(GateResult("G-DASH-24", "Links, cards and back links", "card k starts at CARD0 + (k − 1) × 17 and its "
                          "header shows #k; "
                          "card links (block card_row), back links (block list_row) and row links (block link_row) "
                          "resolve; static links resolve", inp, f"{N} cards; 0 broken",
                          f"{len(cards)} cards; {n_formula_links} HYPERLINK formulas; {len(problems)} problems; "
                          f"{len(statics)} broken static links", _status(not problems and not statics),
                          "; ".join((problems + statics)[:4])))
    return out




# functions the builders use, every one available since Excel 2007/2010 (10.4A.15)
EXCEL2010_FUNCTIONS = {"ABS", "ADDRESS", "AND", "CHOOSE", "COUNT", "COUNTIF", "COUNTIFS", "EXACT", "FIXED", "HYPERLINK",
                       "IF", "IFERROR", "INDEX", "ISNA", "ISNUMBER", "LEFT", "LEN", "MATCH", "MAX", "MOD", "NOT", "OR",
                       "ROW", "SIGN", "SMALL", "SUMIFS", "SUMPRODUCT"}


def excel2010_scan(path) -> tuple[set, int, int]:
    """(functions outside the list, count of _xlfn/_xlpm/_xlws prefixes, count of array formulas) over every cell
    formula and conditional-format formula of the workbook."""
    import zipfile
    names, prefixed, arrays = set(), 0, 0
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if not n.startswith("xl/worksheets/sheet"):
                continue
            txt = z.read(n).decode("utf-8")
            prefixed += len(re.findall(r"_xl(?:fn|pm|ws)\.", txt))
            arrays += len(re.findall(r'<f[^>]*t="array"', txt))
            for f in re.findall(r"<f[^>]*>(.*?)</f>|<formula>(.*?)</formula>", txt, flags=re.S):
                body = re.sub(r'"[^"]*"', "", f[0] or f[1])
                names |= set(re.findall(r"([A-Z][A-Z0-9.]*)\(", body))
    return names - EXCEL2010_FUNCTIONS, prefixed, arrays


def _formula_cells(ws, needle: str) -> list[str]:
    return [c.coordinate for row in ws.iter_rows() for c in row
            if isinstance(c.value, str) and c.value.startswith("=") and needle in c.value]
