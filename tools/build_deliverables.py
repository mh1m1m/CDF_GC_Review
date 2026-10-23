#!/usr/bin/env python3
"""Builds, verifies and packages every CDF–GCO–CRMS v7.12 deliverable.

Stages (run all, or one by name):
  demo      five-round demonstration history, Word files, the demo workbook
  verify    LibreOffice recalculation of every view, empty state, refresh pair, performance
  render    dashboard and before/after screenshots
  gates     G-DASH and G-UX gates (reads tools/manual_inspection.json for inspected renders)
  tests     pytest regression TEST 01–20 and the results workbook
  registers brand register, UX audit, guidance dictionary, innovation matrix
  protocol  consolidated v7.12 protocol (.md, .docx, .txt) and the v7.11 to v7.12 clause crosswalk (tools/build_protocol.py)
State is kept in build/state.json so that stages can be re-run independently.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cdf_gco_crms import ENGINE_VERSION  # noqa: E402
from cdf_gco_crms.config import round_schema as S  # noqa: E402
from cdf_gco_crms.config import workbook_settings as W  # noqa: E402

OUT = ROOT / "deliverables"
DEMO = OUT / "demo_rounds"
SHOTS = OUT / "screenshots"
BUILD = ROOT / "build"
STATE = BUILD / "state.json"
DEMO_XLSX = OUT / "CDF-GCO-CRMS-v7.12-EXECUTIVE-DASHBOARD-DEMO.xlsx"
LOGO = ROOT / "assets" / "cdf_logo_horizontal_transparent.png"


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(st: dict):
    BUILD.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2, default=str))


def _demo_history(outdir=None):
    from cdf_gco_crms.regression.synthetic import demo_history
    return demo_history(outdir)


# ---------------------------------------------------------------------------- demo
def stage_demo(st):
    from cdf_gco_crms.word.word_sync import build_review_docx
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    h = _demo_history(DEMO)
    docs = {}
    for r, p in h.files.items():
        d = build_review_docx(h.states[r], p.with_suffix(".docx"))
        docs[r] = str(d)
    shutil.copy2(h.files[5], DEMO_XLSX)
    st["demo"] = {"files": {r: str(p) for r, p in h.files.items()}, "docx": docs, "demo_xlsx": str(DEMO_XLSX),
                  "observations": len(h.states[5].observations), "rounds": 5}
    print("demo:", DEMO_XLSX.name, len(h.states[5].observations), "observations")


# ---------------------------------------------------------------------------- verify
def stage_verify(st):
    from cdf_gco_crms.model.entities import DashboardViewState, Document
    from cdf_gco_crms.qa.recalc_verify import check_view, standard_views
    from cdf_gco_crms.rounds.round_expansion import build_round1
    h = _demo_history(None)
    work = BUILD / "verify"
    if work.exists():
        shutil.rmtree(work)
    views = standard_views(h.states[5])
    views.append(DashboardViewState(2, S.SCOPE_ACTION, "#40", 1))      # observation born in round 3 viewed at round 2
    views.append(DashboardViewState(4, S.SCOPE_ALL, "#20", 2))         # reopened row, non-adjacent comparison
    res = []
    t0 = time.time()
    for vs in views:
        vc = check_view(h.states[5], vs, work)
        res.append(asdict(vc))
        print(("OK  " if vc.ok else "BAD ") + vc.view, vc.compared, vc.message)
    # every earlier round workbook verified in its own default view
    for r in range(1, 5):
        vc = check_view(h.states[r], DashboardViewState(r, S.SCOPE_ALL, None, max(1, r - 1)), work / f"r{r}")
        res.append(asdict(vc))
        print(("OK  " if vc.ok else "BAD ") + f"[round-{r} workbook] " + vc.view, vc.compared, vc.message)
    st["views"] = res
    st["views_seconds"] = round(time.time() - t0, 1)
    empty = build_round1(Document(name="وثيقة اختبار فارغة", code="EMP", is_demo=True), [], date=None)
    ev = check_view(empty, DashboardViewState(1, S.SCOPE_ALL, None, 1), work / "empty")
    st["empty_state"] = asdict(ev)
    print("empty state:", ev.message)
    # performance
    import random
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.qa import lo_engine
    from cdf_gco_crms.regression import synthetic as SY
    perf = []
    for n, R in ((200, 20), (500, 5)):
        traj = SY.random_trajectories(n, R, random.Random(n))
        hh = SY.run_history(SY.fixture_document("PRF"), [SY.topic_obs(i) for i in range(n)], traj, rounds=R,
                            outdir=None, roundtrip=False)
        p = BUILD / "perf" / f"perf_{n}x{R}.xlsx"
        import resource
        rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        t = time.time()
        b = build_workbook(hh.states[R], p, logo_path=False)
        bt = time.time() - t
        rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        q = p.with_name(p.stem + "_recalc.xlsx")
        shutil.copy(p, q)
        t = time.time()
        lo = lo_engine.recalc(q, timeout=600)
        rt = time.time() - t
        perf.append({"observations": n, "rounds": R, "build_seconds": round(bt, 1), "file_mb": round(p.stat().st_size / 1e6, 2),
                     "formulas": len(b.registry.entries), "recalc_seconds": round(rt, 1) if lo.ok else None,
                     "recalc": lo.message, "peak_rss_mb": round(rss1 / 1024, 1), "rss_growth_mb": round((rss1 - rss0) / 1024, 1)})
        print("perf", perf[-1])
    st["perf"] = perf


# ---------------------------------------------------------------------------- render
def stage_render(st):
    from openpyxl import load_workbook
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.model.entities import DashboardViewState
    from cdf_gco_crms.qa import lo_engine
    SHOTS.mkdir(parents=True, exist_ok=True)
    for f in SHOTS.glob("*"):
        f.unlink()
    work = BUILD / "render"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    def pages(xlsx, stem, first, last, dpi=100):
        pdf = lo_engine.to_pdf(xlsx, work)
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(first), "-l", str(last), str(pdf),
                        str(SHOTS / stem)], check=True)
        return sorted(SHOTS.glob(stem + "*.png"))

    shots = {}
    shots["after_dashboard_round5"] = [str(p) for p in pages(DEMO_XLSX, "after_dashboard_round5_p", 1, 4)]
    h = _demo_history(None)
    hist = build_workbook(h.states[5], work / "historical_view.xlsx",
                          view_state=DashboardViewState(2, S.SCOPE_ACTION, "#40", 1))
    shots["after_dashboard_round2_selected"] = [str(p) for p in pages(hist.path, "after_dashboard_round2_selected_p", 1, 1)]
    # before: v7.10 print view and the earlier prototype
    from cdf_gco_crms.migration.legacy_v710 import write_v710
    legacy = write_v710(h.states[5], work / "legacy_v710.xlsx")
    wb = load_workbook(legacy)
    del wb[wb.sheetnames[0]]
    wb.save(work / "before_v710_printview.xlsx")
    shots["before_v710_printview"] = [str(p) for p in pages(work / "before_v710_printview.xlsx", "before_v710_printview_p", 1, 1, 80)]
    proto = ROOT / "sources" / "earlier_package" / "CDF-GCO-CRMS_v7.11_Brand_Aligned_Dashboard.xlsx"
    if proto.exists():
        wb = load_workbook(proto)
        del wb[wb.sheetnames[1]]
        wb.save(work / "before_prototype.xlsx")
        shots["before_prototype"] = [str(p) for p in pages(work / "before_prototype.xlsx", "before_prototype_p", 1, 1, 80)]
    # before: the issued v7.11 dashboard (same synthetic history), rendered from the v7.11 package file as delivered
    v711 = ROOT / "sources" / "earlier_package" / "CDF-GCO-CRMS-v7.11-EXECUTIVE-DASHBOARD-DEMO.xlsx"
    if v711.exists():
        shots["before_v711_dashboard"] = [str(p) for p in pages(v711, "before_v711_dashboard_p", 1, 1, 80)]
    st["shots"] = shots
    print(json.dumps(shots, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------------------- gates
def stage_gates(st):
    from cdf_gco_crms.qa.gates import GateContext, run_dash_gates
    from cdf_gco_crms.qa.recalc_verify import ViewCheck
    from cdf_gco_crms.qa.report_xlsx import SheetSpec, write_report
    from cdf_gco_crms.qa.ux_gates import run_ux_gates
    h = _demo_history(None)
    files = {int(k): Path(v) for k, v in st["demo"]["files"].items()}
    manual = {}
    mf = ROOT / "tools" / "manual_inspection.json"
    if mf.exists():
        for k, v in json.loads(mf.read_text()).items():
            manual[k] = (v["status"], v["evidence"])
    vcs = [ViewCheck(**v) for v in st.get("views", [])]
    perf = st.get("perf", [None])[0]
    ctx = GateContext(xlsx=DEMO_XLSX, previous_xlsx=files[4], returned_state=h.returned[4],
                      docx=Path(st["demo"]["docx"]["5"] if "5" in st["demo"]["docx"] else st["demo"]["docx"][5]),
                      view_checks=vcs, empty_state_check=ViewCheck(**st["empty_state"]) if st.get("empty_state") else None,
                      refresh={"before": files[4], "after": files[5]}, manual=manual, perf=perf, logo_source=LOGO_SRC)
    dash = run_dash_gates(ctx)
    ux = run_ux_gates(ctx, dash)
    from cdf_gco_crms.qa.ref_gates import run_ref_gates
    from cdf_gco_crms.references.index import ReferenceIndex
    ref = run_ref_gates(ReferenceIndex.load(), h.states[5].document.owning_department, DEMO_XLSX.name)
    dash = dash + ref
    rows = [[g.gate, g.name, g.test, g.input, g.expected, g.actual, g.status, g.evidence] for g in dash + ux]
    st["gates"] = [dict(zip(["gate", "name", "test", "input", "expected", "actual", "status", "evidence"], r)) for r in rows]
    for g in dash + ux:
        print(f"{g.gate:10} {g.status:13} {g.actual[:110]}")
    from collections import Counter
    st["gate_summary"] = dict(Counter(g.status for g in dash + ux))
    print(st["gate_summary"])


LOGO_SRC = ROOT / "assets" / "cdf_logo_horizontal_source.jpg"

TEST_SPEC = {
    "01": ("Round 1", "10 observations, round 1", "F = مفتوحة (#F2F2F2), placeholders, totals 10/0/0/0/10/0, no row called overdue"),
    "02": ("Round 2 mixed closure states", "3 closed, 2 conditional, 3 requiring modification, 2 open", "cards 10/3/2/3/2, rate 30 %, closed-row prefill, change labels"),
    "03": ("Round 3 new and reopened observations", "5 rows + 1 new in round 3, one reopened", "GCO-TST-R3-001 as #06; not-raised cells grey; round-2 denominator 5"),
    "04": ("Five-round history", "12 observations over 5 rounds incl. reopen/reclose", "closure history and labels per round; stalled flags; counts add up"),
    "05": ("Ten-round history", "15 random trajectories, 10 rounds", "blocks 1–10 discovered, 44 columns, sheet الملاحظات حتى الجولة العاشرة"),
    "06": ("Twenty-round history", "40 random trajectories, 20 rounds", "84 columns, sheet الملاحظات حتى الجولة 20, build < 120 s"),
    "07": ("Closed-row preservation", "five-round fixture", "earlier blocks unchanged after each append; carried-closed prefill"),
    "08": ("Management response integrity", "returned round 4 with owner input, a late edit and a GCO-cell edit", "owner text kept, GCO cell restored, history identical after round 5"),
    "09": ("Duplicate round prevention", "round 5 applied twice; different content; gap; duplicated headers", "NO_OP; refused; refused; refused; deterministic rebuild"),
    "10": ("Formula reconciliation", "3 views recalculated by LibreOffice", "0 mismatches against the Python calculation"),
    "11": ("Navigation", "links in the delivered file and after a reverse sort + recalculation", "every link reaches the row holding its Internal_ID"),
    "12": ("Word–Excel synchronisation", "Word files of rounds 1, 3, 5 and a wrong status", "reconcile passes; wrong status detected"),
    "12b": ("Word reply threads (G-SYNC-9)", "round-3 Word file; commentsExtended parents; LibreOffice opens the file",
            "every round-3 follow-up is a reply to the round-1 comment of its observation; reconcile check true"),
    "13": ("v7.10 migration", "v7.10 fixture with print view", "PASSED; source hash unchanged; backup; data sheet identical; no round added"),
    "14": ("Metadata", "every demo workbook and a Word file", "Author/LastModifiedBy/Company/Title per 09.4; no library names; stems per 09.1"),
    "15": ("Information boundary", "helper allowlist and all package parts", "no severity, integrity, closure-path code or hash; no visible Internal_ID"),
    "16": ("Visual inspection (automated part)", "PDF render, fonts, RTL, sizes, chart rectangles", "render produced; Calibri only; RTL; ≥ 9 pt; no chart over content"),
    "17": ("No macro dependency", "package parts and content types", "no VBA, ActiveX, external link or connection"),
    "18": ("Dashboard refresh", "workbooks of rounds 2–5", "labels, selectors, round tables, cards and chart ranges follow each round"),
    "19": ("Historical round selection", "selected round 2 in a five-round workbook", "no observation born in round 4 shown (model)"),
    "19b": ("Historical round selection (spreadsheet)", "selected round 2, LibreOffice recalculation", "0 mismatches"),
    "20": ("Closure sustainability", "closed–reopened–reclosed and closed–reopened rows", "history kept; latest-closure ordinal; reopen state and counts"),
    "25": ("Reopened follow-up (16.1, AMB-164)", "row closed in round 2, reopened in round 4; round-4 Word file", "a round-4 follow-up exists, threaded under the first comment; rows that stay closed get none; reconcile counts it"),
    "26": ("Historical response (10.4A.6)", "every observation with two or more responses, every selected round", "the detail panel shows the latest response up to the selected round, never a later one"),
    "27": ("Closure round (10.2)", "closed–closed, closed–reopened–reclosed rows", "closure round stays at the actual closure event; a reclosure reports its own round"),
}


# ---------------------------------------------------------------------------- tests
def stage_tests(st):
    import xml.etree.ElementTree as ET
    from cdf_gco_crms.qa.report_xlsx import SheetSpec, write_report
    junit = BUILD / "junit.xml"
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q", "-p", "no:cacheprovider",
                        f"--junitxml={junit}"], capture_output=True, text=True, cwd=str(ROOT))
    print(r.stdout[-600:])
    root = ET.parse(junit).getroot()
    rows = []
    # test files other than the regression catalogue are reported as groups TEST 21 (references), 22 (assurance),
    # 23 (protocol consolidation), one row per pytest check
    groups = {"test_references": ("21", "Reference index (02.9, D.13)"), "test_assurance": ("22", "Assurance (19A)"),
              "test_protocol": ("23", "Protocol consolidation v7.11 to v7.12"), "test_brand": ("24", "Brand library (D.11, D.12)"),
              "test_titles": ("28", "Observation title (10.4A.16, 19A.9)"),
              "test_security": ("29", "Safe ingestion and formula injection (15A.3(h), I-15)"),
              "test_word_lifecycle": ("30", "Word lifecycle on case documents (08.2, 16.1, G-SYNC-9)"),
              "test_challenge": ("31", "Grounded adversarial challenge (19A)"),
              "test_e2e": ("32", "Production end-to-end case (15A, 16.1, 17.7, 19A)"),
              "test_release_gate": ("33", "Release authorisation gate: no issue without a CLEAR review of this content (19A.9)"),
              "test_reference_synthetic": ("34", "Public SYNTHETIC reference fixture (reference layer and challenge without institutional sources)")}
    counters: dict[str, int] = {}
    for tc in root.iter("testcase"):
        name = tc.get("name")
        cls = (tc.get("classname") or "").split(".")[-1]
        fail = tc.find("failure") or tc.find("error")
        skip = tc.find("skipped")
        status = "FAIL" if fail is not None else ("NOT_RUN" if skip is not None else "PASS")
        actual = (fail.get("message", "")[:300] if fail is not None else
                  (skip.get("message", "") if skip is not None else "as expected"))
        if cls == "test_regression":
            num = "19b" if name.startswith("test_19b") else ("12b" if name.startswith("test_12b") else name.split("_")[1])
            title, inp, exp = TEST_SPEC.get(num, (name, "", ""))
            label = f"TEST {num}"
        elif cls in groups:
            g, gtitle = groups[cls]
            counters[g] = counters.get(g, 0) + 1
            label, title, inp, exp = f"TEST {g}.{counters[g]}", gtitle, name, "check passes"
        else:
            label, title, inp, exp = cls, name, "", ""
        rows.append([label, title, inp, exp, actual, status, f"{float(tc.get('time')):.2f} s", f"tests/{cls}.py::{name}"])
    st["tests"] = rows
    st["tests_seconds"] = round(time.time() - t0, 1)
    from collections import Counter
    st["test_summary"] = dict(Counter(r[5] for r in rows))
    print(st["test_summary"])


# ---------------------------------------------------------------------------- registers
def stage_registers(st):
    from cdf_gco_crms.branding.pdf_brand_extractor import extract, summary_rows
    from cdf_gco_crms.guidance import guidance_dictionary as G
    from cdf_gco_crms.qa.report_xlsx import SheetSpec, write_report
    from cdf_gco_crms.regression import registers as RG
    from cdf_gco_crms.branding.guide_page_check import check_page12, page_surface
    guide = ROOT / "sources" / "CDF_Design_Guide.pdf"            # the 8-page identity-applications file (logo source)
    gr = extract(guide)
    ext_rows = [[r["page"], r["space"], r["components"], r["srgb_hex"], r["area_pt2"], r["verification"]]
                for r in summary_rows(gr)]
    p12 = ROOT / "sources" / "v7.12" / "guide_page12.png"
    checks = check_page12(p12)
    import hashlib
    st["brand_page12"] = {"swatches": len(checks), "equal": sum(c.equal for c in checks),
                          "page_surface": page_surface(p12), "png_sha256": hashlib.sha256(p12.read_bytes()).hexdigest()[:16]}
    p1 = write_report(OUT / "CDF - Brand Identity Verification.xlsx", "CDF – Brand Identity Verification", [
        SheetSpec("Brand register", ["Token", "Value", "Verification", "Source", "Page / Component", "Intended Excel use", "Note"],
                  RG.brand_rows(), [26, 22, 26, 26, 34, 34, 60], status_col="Verification",
                  notes=["Colour source (v7.12): CDF Design Guide, 87 pages; page 12 'Color Library' prints seven named colours "
                         "with their HEX; page 21 'Typography' names Calibri with its type scale. Pages supplied as renders "
                         f"(guide_page12.png sha256 {st['brand_page12']['png_sha256']}…, guide_page21.png).",
                         f"Logo source: CDF Identity Applications PDF, {gr.pages} pages, {gr.page_size[0]:.0f} × {gr.page_size[1]:.0f} pt, "
                         f"producer {gr.producer}; sha256 {gr.sha256}; embedded fonts: {', '.join(gr.fonts)}"]),
        SheetSpec("Guide page 12 check", ["Colour", "Printed HEX", "Sampled pixel", "Equal", "x", "y"],
                  [[c.name, "#" + c.printed, "#" + c.sampled, "PASS" if c.equal else "FAIL", c.x, c.y] for c in checks]
                  + [["page background", "(not printed)", "#" + st["brand_page12"]["page_surface"], "PASS", "", ""]],
                  [22, 14, 14, 8, 6, 6], status_col="Equal",
                  notes=["The token is the printed value; the sample only confirms that the render shows the same colour."]),
        SheetSpec("Identity file colour operators", ["Page", "Colour space", "Components", "sRGB", "Filled area (pt²)", "Verification"],
                  ext_rows, [8, 14, 26, 12, 16, 30],
                  notes=["Read from the 8-page identity file's vector content streams; its CMYK conversions are superseded by the "
                         "printed HEX of the 87-page guide (D.11)."]),
        SheetSpec("Contrast", ["Pair", "Text", "Background", "Ratio", "WCAG 2.2 AA", "Note"], RG.contrast_rows(),
                  [34, 12, 12, 10, 22, 50], status_col="WCAG 2.2 AA"),
        SheetSpec("Website comparison", ["Item", "Result"], [
            ["https://cdf.gov.sa", "Fetched on 23 October 2026: text content only; style sheets and colour values could not be "
                                   "retrieved from this environment (HTTP 405 from the workspace; the fetch tool returns text only)."],
            ["Comparison with the guide", "NOT_RUN – no CSS colour values available. No website colour is used as a brand token."],
        ], [30, 110]),
    ])
    p2 = write_report(OUT / "CDF - Excel UX Audit.xlsx", "CDF – Excel UX Audit", [
        SheetSpec("Audit", ["Component", "Current design (before)", "CDF brand alignment", "UX issue", "Redesign (v7.12)", "Priority",
                            "Evidence"], [list(r) for r in RG.UX_AUDIT], [24, 40, 22, 36, 44, 9, 40], rtl=False,
                  notes=["Before: the v7.10 print view, the earlier prototype and the issued v7.11 dashboard; "
                         "after: the v7.12 demonstration workbook. Screenshots are LibreOffice renders (fonts substituted)."]),
        SheetSpec("Design specification", ["Element", "Specification"], [
            ["Layout grid", "Column A 2; B–M 13 characters each; N 2; right-to-left; gridlines hidden; 100 % zoom; page surface #F3F3F4 behind white cards"],
            ["Colour tokens", "D.10 / D.11 / D.12 of the protocol; cdf_gco_crms/config/design_tokens.py (brand, derived, protocol families)"],
            ["Identity band", "6 pt ink rule, then Warm Gray #D7D2CB rows 2–4 edge to edge with the black logo at the reading edge; powder-blue divider under the selectors"],
            ["Typography", "Calibri (guide page 21): title 24 bold; document 14 bold; sections 16 bold; card values 32 bold; detail head 14; secondary 16; body 10; notes 9"],
            ["Card dimensions", "2 grid columns × 3 rows (20/44/16 pt); cap row in the D.2 fill of the status (the register's own colour); white body; warm-grey frame"],
            ["Section rows", "16 pt bold with a Warm Gray rule below and a Powder Blue marker in the margin column"],
            ["Table widths", "# 1 | location 2 | summary 3 | previous 1 | selected 1 | change 1 | action 2 | link 1 (grid columns)"],
            ["Row heights", "Computed at build from the longest content over all rounds; capped at 72 pt (tables) and 409 pt (data sheet)"],
            ["Navigation", "Row 8 links to each zone and to the current input column; a link on every table row; links in #3F4F9E"],
            ["Guidance behaviour", "Notes (hover on desktop), input messages (on selection), visible labels, user guide"],
            ["Chart treatments", "Native bar/column/line; marks filled with the D.2 status fills of the register and outlined in ink; rate line in ink with Wistful Blue markers; Calibri 9 pt; category axis reversed for right-to-left"],
            ["Interaction states", "Selectors in #FFF9E5 with an ink frame; selected observation in #A5B0E3; historic band in #FDD086; demonstration band and reopened flag in #FA9370"],
        ], [26, 110]),
    ])
    p3 = OUT / "CDF - Cell Guidance Dictionary.json"
    G.export_json(str(p3), rounds=5)
    reg = G.export_register(5)
    p3x = write_report(OUT / "CDF - Cell Guidance Dictionary.xlsx", "CDF – Cell Guidance Dictionary", [
        SheetSpec("Dictionary", ["key", "field_role", "round", "audience", "editability", "closure_state", "input_title",
                                 "input_prompt", "visible", "note"],
                  [[e["key"], e["field_role"], e["round"], e["audience"], e["editability"], e["closure_state"], e["input_title"],
                    e["input_prompt"], e["visible"], e["note"]] for e in reg], [16, 14, 7, 11, 12, 12, 22, 50, 22, 70], rtl=True,
                  notes=[f"Integrity check (10.4A.14): {G.validate_integrity() or 'no problem found'}"]),
    ])
    p4 = write_report(OUT / "CDF - 50 UX Innovations Implementation Matrix.xlsx", "CDF – UX Innovations Implementation Matrix", [
        SheetSpec("Innovations", ["#", "Group", "Innovation", "Implemented", "Priority", "Engineering approach", "Excel compatibility",
                                  "Performance impact", "Security and governance", "Validation", "Limitations"],
                  [list(r) for r in RG.INNOVATIONS], [5, 7, 30, 18, 8, 50, 22, 16, 36, 20, 40], status_col="Implemented",
                  notes=[f"Implemented {sum(1 for r in RG.INNOVATIONS if r[3] == 'IMPLEMENTED')}, partial "
                         f"{sum(1 for r in RG.INNOVATIONS if r[3] == 'PARTIAL')}, not implemented "
                         f"{sum(1 for r in RG.INNOVATIONS if r[3] == 'NOT_IMPLEMENTED')} of 50."]),
        SheetSpec("Concepts A–E", ["Concept", "Title", "Status", "Assessment"], [list(c) for c in RG.CONCEPTS], [9, 34, 18, 100],
                  status_col="Status"),
    ])
    st["registers"] = [str(p) for p in (p1, p2, p3, p3x, p4)]
    print(st["registers"])


# ---------------------------------------------------------------------------- results workbook
def stage_results(st):
    from cdf_gco_crms.qa.report_xlsx import SheetSpec, write_report
    views = st.get("views", [])
    vrows = [[v["view"], v["formulas"], v["compared"], len(v["mismatches"]), len(v["errors"]), v["engine"],
              "PASS" if v["ok"] else "FAIL", v["message"]] for v in views]
    es = st.get("empty_state")
    if es:
        vrows.append(["empty workbook (0 observations)", es["formulas"], es["compared"], len(es["mismatches"]), len(es["errors"]),
                      es["engine"], "PASS" if es["ok"] else "FAIL", es["message"]])
    prow = [[p["observations"], p["rounds"], p["build_seconds"], p["file_mb"], p["formulas"], p["recalc_seconds"], p["recalc"]]
            for p in st.get("perf", [])]
    g = st.get("gates", [])
    p = write_report(OUT / "CDF-GCO-CRMS-v7.12-REGRESSION-RESULTS.xlsx", "CDF–GCO–CRMS v7.12 – Regression results", [
        SheetSpec("TEST 01–23", ["Test", "Title", "Input", "Expected", "Actual", "Status", "Duration", "Implementation"],
                  st.get("tests", []), [10, 30, 40, 50, 40, 10, 10, 50], status_col="Status",
                  notes=[f"pytest run of tests/ (regression catalogue TEST 01–20 with 12b and 19b; TEST 21 references, TEST 22 assurance, TEST 23 protocol), engine {ENGINE_VERSION}: {st.get('test_summary')}"]),
        SheetSpec("Gates", ["Gate", "Name", "Test", "Input", "Expected", "Actual", "Status", "Evidence"],
                  [[x["gate"], x["name"], x["test"], x["input"], x["expected"], x["actual"], x["status"], x["evidence"]] for x in g],
                  [11, 26, 44, 30, 40, 50, 14, 40], status_col="Status",
                  notes=[f"Gate results on the demonstration workbook: {st.get('gate_summary')}"]),
        SheetSpec("Recalculated views", ["View", "Formulas", "Compared", "Mismatches", "Error values", "Engine", "Status", "Result"],
                  vrows, [60, 10, 10, 11, 11, 26, 9, 30], status_col="Status",
                  notes=["Each view: workbook built without cached values, recalculated by LibreOffice, every formula result "
                         "compared with the independent Python calculation."]),
        SheetSpec("Performance", ["Observations", "Rounds", "Build (s)", "File (MB)", "Formulas", "Recalculation (s)", "Engine result"],
                  prow, [13, 9, 10, 10, 10, 16, 30]),
    ])
    st["results_xlsx"] = str(p)
    print(p)


# ---------------------------------------------------------------------------- protocol
def stage_protocol(st):
    from cdf_gco_crms.protocol.consolidate import consolidate, crosswalk
    from cdf_gco_crms.protocol.render import to_docx, to_markdown
    from cdf_gco_crms.protocol.v711_amendments import ISSUE_DATE, edits
    from cdf_gco_crms.qa.report_xlsx import SheetSpec, write_report
    tests = st.get("test_summary", {})
    gates = st.get("gate_summary", {})
    base = ROOT / "sources" / "CDF-GCO-CRMS-v7.10.txt"
    first = consolidate(base, {})
    results = {
        "p10_new": "zero hits" if not first.p10_hits else f"{len(first.p10_hits)} hits",
        "xref": f"{first.xref_checked} references checked, {len(first.xref_unresolved)} unresolved",
        "preservation": (f"{first.removed_lines} v7.10 lines changed, each the anchor of a declared edit; "
                         f"{len(first.unexplained_removed_lines)} unexplained"),
        "regression": (("TEST 01 to TEST 20 all PASS (" if set(tests) == {"PASS"} else "TEST 01 to TEST 20: ")
                       + ", ".join(f"{v} {k}" for k, v in sorted(tests.items()))
                       + " pytest checks; TEST 19 runs twice, in the Python model and in the spreadsheet engine"
                       + (")" if set(tests) == {"PASS"} else "")) if tests else "not run",
        "gates": ", ".join(f"{v} {k}" for k, v in sorted(gates.items())) or "not run",
    }
    res = consolidate(base, results)
    txt = OUT / "CDF-GCO-CRMS-v7.11-FULL-CONSOLIDATED.txt"
    txt.write_text(res.text, encoding="utf-8")
    md = OUT / "CDF-GCO-CRMS-v7.11-FULL-CONSOLIDATED.md"
    md.write_text(to_markdown(res.text, "7.11", ISSUE_DATE), encoding="utf-8")
    docx = to_docx(res.text, OUT / "CDF-GCO-CRMS-v7.11-FULL-CONSOLIDATED.docx", "7.11", ISSUE_DATE)
    rows = crosswalk(base.read_text(encoding="utf-8"), res.text, edits(results))
    cols = ["Original_Clause", "Original_Text_Hash", "New_Clause", "Change_Type", "Change_Reason", "Preservation_Status",
            "Verification_Result"]
    from collections import Counter
    cnt = Counter(r["Change_Type"] for r in rows)
    edit_rows = [[e.clause, e.new_clause or e.clause, e.kind, e.change_type, e.reason, e.anchor[:200]] for e in edits(results)]
    cw = write_report(OUT / "CDF-GCO-CRMS-v710-v711-CROSSWALK.xlsx", "CDF–GCO–CRMS v7.10 to v7.11 clause crosswalk", [
        SheetSpec("Crosswalk", cols, [[r[c] for c in cols] for r in rows], [24, 18, 24, 22, 50, 50, 40], status_col="Change_Type",
                  notes=[f"{len(rows)} entries: " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())),
                         "Hash: first 16 hex digits of SHA-256 over the clause text after NFC and whitespace normalisation."]),
        SheetSpec("Declared edits", ["Clause", "New clause", "Operation", "Change type", "Reason", "Anchor in v7.10"], edit_rows,
                  [14, 22, 18, 22, 50, 70], status_col="Change type"),
        SheetSpec("Release checks", ["Check", "Result"], [
            ["P10 typography on added text", results["p10_new"]],
            ["Cross-references in added text", results["xref"] + (f": {res.xref_unresolved}" if res.xref_unresolved else "")],
            ["Preservation of v7.10 lines", results["preservation"]],
            ["Structure (articles 00–23, annexes A–F, END line)", "no problem" if not res.structure_problems else str(res.structure_problems)],
            ["Lines v7.10 / v7.11", f"{len(base.read_text(encoding='utf-8').splitlines())} / {len(res.text.splitlines())}"],
            ["Workbook regression (Annex E.8)", results["regression"]],
            ["Dashboard and UX gates", results["gates"]],
            ["00.8 reference-case regression", "not run: reference package not supplied in this session"],
        ], [44, 100]),
    ])
    st["protocol"] = {"txt": str(txt), "md": str(md), "docx": str(docx), "crosswalk": str(cw), "counts": dict(cnt),
                      "p10": res.p10_hits, "xref_unresolved": res.xref_unresolved, "xref_checked": res.xref_checked,
                      "structure": res.structure_problems, "removed_lines": res.removed_lines,
                      "unexplained": res.unexplained_removed_lines, "lines_v710": len(base.read_text().splitlines()),
                      "lines_v711": len(res.text.splitlines())}
    print(json.dumps(st["protocol"], ensure_ascii=False, indent=1)[:1500])


def stage_migration(st):
    from cdf_gco_crms.migration.legacy_v710 import write_v710
    from cdf_gco_crms.migration.migrate import migrate
    from cdf_gco_crms.config.workbook_settings import file_stem
    h = _demo_history(None)
    base = OUT / "migration_demo"
    if base.exists():
        shutil.rmtree(base)
    src_dir = base / "v7.10_input"
    out_dir = base / "v7.12_output"
    reports = []
    for r in (3, 5):
        src = write_v710(h.states[r], src_dir / f"{file_stem(h.states[r].document.name, r)}.xlsx")
        rep = migrate(src, out_dir / f"round{r}", round_meta={k: {"date": v, "version": None}
                                                               for k, v in {1: "2026-07-05", 2: "2026-07-26", 3: "2026-08-17",
                                                                            4: "2026-09-09", 5: "2026-10-01"}.items() if k <= r})
        (out_dir / f"round{r}" / (src.stem + ".migration-report.json")).write_text(rep.to_json(), encoding="utf-8")
        reports.append(json.loads(rep.to_json()))
        print(r, rep.status, rep.cells_compared, rep.removed_sheets)
    proto = ROOT / "sources" / "earlier_package" / "CDF-GCO-CRMS_v7.11_Brand_Aligned_Dashboard.xlsx"
    if proto.exists():
        rep = migrate(proto, base / "earlier_prototype_output",
                      overrides={"name": "نموذج اللوحة السابق (بيانات تجريبية)", "is_demo": True})
        (base / "earlier_prototype_output" / "migration-report.json").write_text(rep.to_json(), encoding="utf-8")
        d = json.loads(rep.to_json())
        from openpyxl import load_workbook
        wb = load_workbook(proto)
        ws = wb.worksheets[1]
        r1 = [ws.cell(row=i, column=6).value for i in range(2, ws.max_row + 1)]
        d["source_findings"] = [f"source workbook creator property = {wb.properties.creator!r} (09.4 requires {W.AUTHOR})",
                                f"round-1 closure values {sorted(set(r1))} (10.3: always مفتوحة in round 1); preserved, not rewritten"]
        reports.append(d)
        print("prototype", rep.status, d["source_findings"])
    # v7.11 to v7.12: the issued v7.11 demonstration workbook, dashboard and helper rebuilt in the v7.12 design
    v711 = ROOT / "sources" / "earlier_package" / "CDF-GCO-CRMS-v7.11-EXECUTIVE-DASHBOARD-DEMO.xlsx"
    if v711.exists():
        rep = migrate(v711, base / "v7.11_to_v7.12_output")
        (base / "v7.11_to_v7.12_output" / "migration-report.json").write_text(rep.to_json(), encoding="utf-8")
        reports.append(json.loads(rep.to_json()))
        print("v7.11", rep.status, rep.cells_compared, rep.removed_sheets)
    st["migration"] = reports


def stage_protocol_v712(st):
    """Consolidated v7.12 protocol and the v7.11 to v7.12 crosswalk (tools/build_protocol.py, run as a subprocess so that the
    build state carries the test and gate summaries it reads)."""
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_protocol.py")], capture_output=True, text=True, cwd=str(ROOT))
    print(r.stdout[-2500:])
    if r.returncode != 0:
        print(r.stderr[-2500:])
        raise SystemExit("protocol consolidation failed")
    summary = BUILD / "protocol_summary.json"
    if summary.exists():
        st["protocol"] = json.loads(summary.read_text(encoding="utf-8"))


def stage_references(st):
    """Reference index (02.9, D.13): JSON export with provenance and status flags, and an Excel register."""
    from cdf_gco_crms.references.index import ReferenceIndex
    from cdf_gco_crms.qa.report_xlsx import SheetSpec, write_report
    idx = ReferenceIndex.load()
    out_dir = OUT / "reference_index"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    exported = idx.export_json(out_dir)
    cov = idx.coverage()
    srcs = [v.to_dict() for v in idx.sources.values()]
    st["references"] = {"exported": [str(p) for p in exported.values()], "coverage": cov, "sources": srcs}
    units = [[u.sector, u.name, u.page, len(u.tasks)] for u in idx.org.units]
    items = [[it.number, it.category, it.title, it.page, it.confidence,
              "; ".join(f"{b}: {r}" for b, r in it.roles.items()),
              "; ".join(f"{b}: {t}" for b, t in it.unresolved.items())] for it in idx.matrix.items]
    write_report(OUT / "CDF-GCO-CRMS-v7.12-REFERENCE-INDEX.xlsx", "CDF–GCO–CRMS v7.12 – Reference index (02.9, D.13)", [
        SheetSpec("Sources", ["Key", "File", "SHA-256 (computed)", "Hash check", "Approval status", "Approval evidence", "Pages"],
                  [[d.get("key"), d.get("file"), d.get("computed_sha256"), d.get("hash_status"), d.get("approval_status"),
                    d.get("approval_evidence"), d.get("pages")] for d in srcs], [18, 40, 40, 12, 24, 16, 7],
                  status_col="Approval status",
                  notes=["An occurrence of a passage in a reference proves that the passage exists, never that it is approved or current "
                         "(02.9, 19A). The status recorded here is never upgraded by the engine; applicability NOT_ESTABLISHED."]),
        SheetSpec("Units", ["Sector", "Unit", "Page", "Tasks"], units, [30, 40, 7, 7], rtl=True),
        SheetSpec("Authority matrix", ["Item", "Category", "Title", "Page", "Confidence", "Roles by body", "Unresolved cells"], items,
                  [8, 24, 50, 6, 12, 80, 30], rtl=True, status_col="Confidence",
                  notes=[f"Coverage: {json.dumps(cov, ensure_ascii=False)}",
                         "Titles are provenance text as extracted from the PDF (glyph artefacts possible); role cells, numbers and "
                         "categories are read from the ruled table."]),
    ])
    print(json.dumps(cov, ensure_ascii=False))


def stage_decisions(st):
    """Decisions traceability register (D.15) and the synthetic end-to-end case (V712-055) through the CLI."""
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "decisions_traceability.py")], capture_output=True, text=True, cwd=str(ROOT))
    print(r.stdout[-400:], r.stderr[-400:])
    st["decisions_rc"] = r.returncode
    e2e = OUT / "demo_e2e"
    r = subprocess.run([sys.executable, str(ROOT / "main.py"), "demo-e2e", str(e2e), "--rounds", "5"], capture_output=True, text=True, cwd=str(ROOT))
    print(r.stdout[-300:], r.stderr[-400:])
    st["demo_e2e_rc"] = r.returncode
    st["environment"] = __import__("cdf_gco_crms.config.environment", fromlist=["describe"]).describe()


STAGES = {"demo": stage_demo, "migration": stage_migration, "verify": stage_verify, "render": stage_render, "gates": stage_gates, "tests": stage_tests,
          "registers": stage_registers, "references": stage_references, "results": stage_results, "protocol": stage_protocol_v712, "decisions": stage_decisions}


def main(argv):
    OUT.mkdir(exist_ok=True)
    st = load_state()
    names = argv or list(STAGES)
    for n in names:
        t = time.time()
        print(f"== {n}")
        STAGES[n](st)
        st.setdefault("timings", {})[n] = round(time.time() - t, 1)
        save_state(st)


if __name__ == "__main__":
    main(sys.argv[1:])
