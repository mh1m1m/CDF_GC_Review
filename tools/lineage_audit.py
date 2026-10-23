#!/usr/bin/env python3
"""Independent five-round lineage validation (protocol 10.2, 10.6, 13, 16.1; gates G-DASH-02/11/12; v7.12).

Re-derives, from the original v7.11 round files, every figure that an external batch reported, with the
engine's own reader, reconciliation and Word synchroniser, and adds what that batch could not do: the
dynamic five-round dashboard recalculated in an independent spreadsheet engine for every round.

    python tools/lineage_audit.py ROUND_DIR [--external AUDIT.xlsx] [--out deliverables]

Checks per consecutive pair (r, r+1), by Internal_ID, never by row order:
  PROTECTED  fixed block (C, D, E) and every GCO cell of rounds <= r: must be identical (SC-38, G-DASH-02)
  OWNER r    owner cells of round r: placeholder -> response is the legitimate return (10.6)
  OWNER < r  owner cells of earlier rounds: a change is a late edit, kept and logged (SC-59)
  NEW ROWS   rows born in r+1: Internal_IDs continue the sequence; earlier blocks hold the not-raised text (10.2)
Word per round: REF/label/status reconciliation (G-SYNC-1 to 3); threading (G-SYNC-9) reported, not required
of v7.11 files. Dashboard: the round-5 register recalculated by LibreOffice for every selected round and
compared with the Python model (G-DASH-05/16).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASS_BASELINE = "BASELINE_INPUT_LIMITATION"
COVERING_V712_RULE = "tests/test_regression.py::test_25_reopened_row_gets_followup and tests/test_e2e.py::test_e2e_round3_reopening"
COVERING_THREADS = "tests/test_regression.py::test_12b_word_reply_threads (native w15 reply threads, G-SYNC-9) and tests/test_e2e.py"

sys.path.insert(0, str(ROOT))

from cdf_gco_crms.config import round_schema as S  # noqa: E402
from cdf_gco_crms.config import workbook_settings as W  # noqa: E402
from cdf_gco_crms.ingestion.workbook_reader import parse_workbook  # noqa: E402
from cdf_gco_crms.model.entities import DashboardViewState, plain_text  # noqa: E402
from cdf_gco_crms.reconciliation.historical import merge_returned  # noqa: E402
from cdf_gco_crms.word.word_sync import extract_comments, reconcile  # noqa: E402

ORD = {S.ordinal(i): i for i in range(1, 11)}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def round_of(path: Path) -> int | None:
    m = re.search(r"الجولة (\S+)\.(xlsx|docx)$", path.name)
    return ORD.get(m.group(1)) if m else None


def find_rounds(d: Path) -> dict[int, dict[str, Path]]:
    out: dict[int, dict[str, Path]] = {}
    for p in sorted(d.glob("*")):
        r = round_of(p)
        if r:
            out.setdefault(r, {})[p.suffix[1:]] = p
    return out


def not_input(v: str) -> bool:
    return v in ("", S.PH_TEXT, S.PH_STATUS, S.IMPL_PRIOR_CLOSED) or v.startswith(S.CLOSED_GUIDE_PREFIX)


def audit(round_dir: Path, out_dir: Path, external: Path | None) -> dict:
    files = find_rounds(round_dir)
    rounds = sorted(files)
    rep: dict = {"source_dir": str(round_dir), "rounds": {}, "pairs": [], "word": [], "dashboard": [], "checks": []}
    states, schemas = {}, {}
    for r in rounds:
        x = files[r]["xlsx"]
        pw = parse_workbook(x)
        states[r] = pw.state
        schemas[r] = pw.schema
        last_col = pw.schema.last_col
        from openpyxl.utils import get_column_letter as gl
        rep["rounds"][r] = {"xlsx": x.name, "sha256": sha(x), "kind": pw.kind, "data_sheet": pw.data_ws.title,
                            "observations": len(pw.state.observations), "current_round": pw.state.current_round,
                            "blocks": sorted(pw.schema.blocks), "last_col": gl(last_col),
                            "docx": files[r].get("docx").name if files[r].get("docx") else None,
                            "docx_sha256": sha(files[r]["docx"]) if files[r].get("docx") else None}
        rep["checks"].append((f"R{r}_PARSE", True, f"{pw.kind}; {len(pw.state.observations)} observations; blocks {sorted(pw.schema.blocks)}; last column {gl(last_col)}"))
        rep["checks"].append((f"R{r}_CURRENT_ROUND", pw.state.current_round == r, f"current round read as {pw.state.current_round}"))
        rep["checks"].append((f"R{r}_IDS_UNIQUE", len({o.internal_id for o in pw.state.observations}) == len(pw.state.observations), "Internal_IDs unique"))
    # consecutive pairs
    total_owner, total_late, total_gco, total_fmt = 0, 0, 0, 0
    owner_rows = []
    for a, b in zip(rounds, rounds[1:]):
        delivered, returned = states[a], states[b]
        merged, intake = merge_returned(delivered, returned)
        new_ids = sorted(set(returned.by_id()) - set(delivered.by_id()))
        # not-raised text in every earlier block of a row born later (10.2)
        nr_ok = all(plain_text(returned.by_id()[i].cells[k].closure) == S.NOT_RAISED for i in new_ids
                    for k in range(1, returned.by_id()[i].birth_round))
        # itemise the owner completions of round a
        for o in delivered.observations:
            ro = returned.by_id().get(o.internal_id)
            if ro is None:
                continue
            for role in (S.ROLE_RESPONSE, S.ROLE_IMPL):
                before = plain_text(getattr(o.cells[a], role)) or ""
                after = plain_text(getattr(ro.cells[a], role)) or ""
                if before != after:
                    from openpyxl.utils import get_column_letter as gl
                    owner_rows.append([f"{a}->{b}", o.internal_id, gl(schemas[b].col(a, role)), before[:60], after[:60],
                                       "OWNER_RETURN_COMPLETION" if not_input(before) and not not_input(after) else "OWNER_CELL_CHANGE"])
        pair = {"from": a, "to": b, "owner_inputs": intake.owner_inputs, "late_owner_edits": len(intake.late_owner_edits),
                "gco_cell_edits": len(intake.gco_cell_edits), "format_losses": len(intake.format_losses),
                "missing_rows": intake.missing_rows, "new_rows": new_ids, "not_raised_ok": nr_ok,
                "gco_edit_cells": [f"{d.internal_id}:{d.key}" for d in intake.gco_cell_edits][:10]}
        rep["pairs"].append(pair)
        total_owner += intake.owner_inputs
        total_late += len(intake.late_owner_edits)
        total_gco += len(intake.gco_cell_edits)
        total_fmt += len(intake.format_losses)
        rep["checks"].append((f"PAIR_{a}_{b}_PROTECTED", not intake.gco_cell_edits and not intake.missing_rows,
                              f"{len(intake.gco_cell_edits)} GCO or fixed-block cells changed; {len(intake.missing_rows)} rows missing"))
        rep["checks"].append((f"PAIR_{a}_{b}_LATE_EDITS", not intake.late_owner_edits, f"{len(intake.late_owner_edits)} earlier-round owner cells changed"))
        rep["checks"].append((f"PAIR_{a}_{b}_NEW_ROWS", nr_ok, f"{len(new_ids)} rows born in round {b}: {new_ids}; not-raised text in earlier blocks={nr_ok}"))
    rep["totals"] = {"owner_inputs": total_owner, "owner_completions_itemised": sum(1 for r in owner_rows if r[5] == "OWNER_RETURN_COMPLETION"),
                     "owner_other_changes": sum(1 for r in owner_rows if r[5] != "OWNER_RETURN_COMPLETION"),
                     "late_owner_edits": total_late, "gco_cell_edits": total_gco, "format_losses": total_fmt}
    rep["owner_rows"] = owner_rows
    # Word per round
    for r in rounds:
        d = files[r].get("docx")
        if not d:
            continue
        sr = reconcile(d, files[r]["xlsx"], round_no=r)
        comments = extract_comments(d)
        threaded = sum(1 for c in comments if c.parent_cid)
        core = {k: v for k, v in sr.checks.items() if k.startswith(("G-SYNC-2", "G-SYNC-3", "G-ID-1"))}   # count checks reported separately
        st_r = states[r]
        reopened = [o.reader_no for o in st_r.observations if o.birth_round < r and o.value(r - 1) == S.CLOSED and o.value(r) != S.CLOSED]
        v711_expected = sum(1 for o in st_r.observations if o.birth_round < r and o.value(r - 1) != S.CLOSED) + \
            sum(1 for o in st_r.observations if o.birth_round == r) if r > 1 else len(st_r.observations)
        got_r = sum(1 for c in comments if c.internal_id and (c.follow_up_round == r or (c.follow_up_round is None and
                    st_r.by_id().get(c.internal_id) and st_r.by_id()[c.internal_id].birth_round == r)))
        rep["word"].append({"round": r, "docx": d.name, "comments": len(comments), "gco_with_ref": sr.gco_comments,
                            "expected_v711_rule": v711_expected, "expected_v712_rule": sr.expected, "round_comments": got_r,
                            "reopened_without_followup": reopened if got_r < sr.expected else [],
                            "checks": sr.checks, "threaded_replies": threaded, "problems": sr.problems[:5]})
        rep["checks"].append((f"R{r}_WORD_REF_LABEL_STATUS", all(core.values()),
                              f"{sr.gco_comments} GCO comments with REF; " + "; ".join(f"{k}={v}" for k, v in core.items())))
        rep["checks"].append((f"R{r}_WORD_COUNT_V711_RULE", got_r == v711_expected,
                              f"round-{r} comments {got_r} = rows not closed at the start of the round plus new rows {v711_expected} (10.2 as issued in v7.11)"))
        # The two v7.12-rule checks below are expected to FAIL on v7.11 baseline Word files: those files were issued under
        # the v7.11 rule (no follow-up for a reopened row, no reply threads). The failure is classified as a
        # BASELINE_INPUT_LIMITATION of the input, not a defect of the v7.12 engine, and each is covered by a v7.12
        # regression test that proves the engine's own output satisfies the rule (TEST 12b threads, TEST 25 / test_e2e
        # reopened rows). The status is kept FAIL so that the limitation stays visible; it is never converted to PASS.
        v712_ok = got_r == sr.expected
        rep["checks"].append((f"R{r}_WORD_COUNT_V712_RULE", v712_ok,
                              f"v7.12 rule (16.1, AMB-164) expects {sr.expected}: reopened rows without a follow-up {reopened if got_r < sr.expected else []}"
                              + ("" if v712_ok else f"; {CLASS_BASELINE}: v7.11 baseline file issued under the v7.11 rule; "
                                 f"covering v7.12 tests {COVERING_V712_RULE}")))
        threads_ok = None if r == 1 else sr.checks.get("G-SYNC-9 follow-ups threaded")
        rep["checks"].append((f"R{r}_WORD_THREADS", threads_ok,
                              ("v7.11 file: follow-ups are top-level comments (threads are a v7.12 requirement, G-SYNC-9); "
                               f"{threaded} replies found" if r > 1 else "round 1 has no follow-ups")
                              + ("" if threads_ok in (True, None) else f"; {CLASS_BASELINE}: v7.11 baseline file has no reply threads; "
                                 f"covering v7.12 tests {COVERING_THREADS}")))
    # dynamic five-round dashboard: recalculate the round-5 register for every selected round
    from cdf_gco_crms.qa.recalc_verify import check_view
    last = states[rounds[-1]]
    work = ROOT / "build" / "lineage_verify"
    for r in rounds:
        vc = check_view(last, DashboardViewState(r, S.SCOPE_ALL, None, max(1, r - 1)), work)
        rep["dashboard"].append({"selected_round": r, "formulas": vc.formulas, "compared": vc.compared,
                                 "mismatches": len(vc.mismatches), "errors": len(vc.errors), "engine": vc.engine, "ok": vc.ok})
        rep["checks"].append((f"DASH_ROUND_{r}_RECALC", vc.ok, f"{vc.compared} formula results compared by {vc.engine}, {len(vc.mismatches)} mismatches, {len(vc.errors)} errors"))
    vc = check_view(last, DashboardViewState(2, S.SCOPE_ACTION, None, 1), work)
    rep["checks"].append(("DASH_ROUND_2_ACTION_SCOPE_RECALC", vc.ok, f"{vc.compared} compared, {len(vc.mismatches)} mismatches"))
    # external figures
    ext = None
    if external and external.exists():
        from openpyxl import load_workbook
        wb = load_workbook(external, data_only=True)
        ws = wb.worksheets[0]
        vals = {str(ws.cell(row=i, column=1).value): ws.cell(row=i, column=2).value for i in range(1, 8)}
        ext = {"file": external.name, "sha256": sha(external), "summary": vals}
        ext_rows = [row for row in wb["استجابات الإدارة"].iter_rows(min_row=2, values_only=True) if row[0] and "->" in str(row[0])]
        ext_set = {(str(r[0]).replace(" ", ""), str(r[1]), str(r[2])) for r in ext_rows}
        eng_set = {(r[0], r[1], r[2]) for r in owner_rows}
        ext["owner_change_rows"] = len(ext_rows)
        ext["owner_changes_only_external"] = sorted(ext_set - eng_set)[:10]
        ext["owner_changes_only_engine"] = sorted(eng_set - ext_set)[:10]
        ext["owner_change_duplicates_external"] = len(ext_rows) - len(ext_set)
        rep["checks"].append(("EXTERNAL_OWNER_CHANGES_MATCH", ext_set == eng_set,
                              f"external audit lists {len(ext_rows)} rows ({len(ext_set)} distinct); engine itemises {len(owner_rows)}; "
                              f"only external={ext['owner_changes_only_external'][:3]}; only engine={ext['owner_changes_only_engine'][:3]}"))
        ext_counts, started = {}, False
        def num(v):
            try:
                return int(str(v).strip())
            except (TypeError, ValueError):
                return None
        for row in ws.iter_rows(values_only=True):            # the first numeric block: "round | observations | last column"
            if row and num(row[0]) is not None and num(row[1]) is not None:
                ext_counts[num(row[0])] = num(row[1]); started = True
            elif started:
                break
        eng_counts = {r: rep["rounds"][r]["observations"] for r in rounds}
        rep["checks"].append(("EXTERNAL_COUNTS_MATCH", ext_counts == eng_counts, f"external {ext_counts}; engine {eng_counts}"))
    rep["external"] = ext
    rep["summary"] = {"checks": len(rep["checks"]), "pass": sum(1 for c in rep["checks"] if c[1] is True),
                      "fail": sum(1 for c in rep["checks"] if c[1] is False), "not_applicable": sum(1 for c in rep["checks"] if c[1] is None),
                      "fail_baseline_input_limitation": sum(1 for c in rep["checks"] if c[1] is False and CLASS_BASELINE in c[2]),
                      "fail_engine": sum(1 for c in rep["checks"] if c[1] is False and CLASS_BASELINE not in c[2])}
    rep["classification_note"] = (f"FAIL checks tagged {CLASS_BASELINE} are limitations of the v7.11 baseline input files (issued under the "
                                  "v7.11 rules), not defects of the v7.12 engine; each names the v7.12 regression tests that cover the rule "
                                  "on the engine's own output. They are reported as FAIL, never converted to PASS.")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "CDF-GCO-CRMS-v7.12-LINEAGE-VALIDATION.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    write_xlsx(rep, out_dir / "CDF-GCO-CRMS-v7.12-LINEAGE-VALIDATION.xlsx")
    return rep


def write_xlsx(rep: dict, path: Path):
    from cdf_gco_crms.qa.report_xlsx import SheetSpec, write_report
    t = rep["totals"]
    summary = [["Source directory", rep["source_dir"]], ["Rounds", len(rep["rounds"])],
               ["Checks", f"{rep['summary']['pass']} PASS, {rep['summary']['fail']} FAIL, {rep['summary']['not_applicable']} NOT_APPLICABLE of {rep['summary']['checks']}"],
               ["FAIL classification", f"{rep['summary'].get('fail_baseline_input_limitation', 0)} BASELINE_INPUT_LIMITATION (v7.11 input files), "
                                       f"{rep['summary'].get('fail_engine', 0)} engine"],
               ["Protected cells changed (fixed block, GCO cells, all pairs)", t["gco_cell_edits"]],
               ["Late owner edits of earlier rounds", t["late_owner_edits"]],
               ["Owner completions of the just-issued round (placeholder to response)", t["owner_completions_itemised"]],
               ["Other owner-cell changes", t["owner_other_changes"]],
               ["Format-only losses restored", t["format_losses"]]]
    if rep.get("external"):
        e = rep["external"]
        summary.append(["External audit compared", f"{e['file']} sha256 {e['sha256'][:16]}; {e['owner_change_rows']} owner-change rows listed "
                        f"({e['owner_change_duplicates_external']} duplicate rows); only external {e['owner_changes_only_external']}; only engine {e['owner_changes_only_engine']}"])
    rounds = [[r, v["observations"], v["current_round"], v["last_col"], v["data_sheet"], v["sha256"][:16], v["docx"] or ""] for r, v in rep["rounds"].items()]
    pairs = [[f"{p['from']} -> {p['to']}", p["owner_inputs"], p["late_owner_edits"], p["gco_cell_edits"], p["format_losses"],
              ", ".join(p["new_rows"]), "PASS" if p["not_raised_ok"] else "FAIL", ", ".join(p["missing_rows"])] for p in rep["pairs"]]
    word = [[w["round"], w["comments"], w["gco_with_ref"], w["round_comments"], w["expected_v711_rule"], w["expected_v712_rule"],
             ", ".join(w["reopened_without_followup"]), w["threaded_replies"],
             "; ".join(f"{k}={v}" for k, v in w["checks"].items())] for w in rep["word"]]
    dash = [[d["selected_round"], d["formulas"], d["compared"], d["mismatches"], d["errors"], d["engine"], "PASS" if d["ok"] else "FAIL"] for d in rep["dashboard"]]
    checks = [[c[0], "PASS" if c[1] is True else ("FAIL" if c[1] is False else "NOT_APPLICABLE"), c[2]] for c in rep["checks"]]
    write_report(path, "CDF–GCO–CRMS v7.12 – Five-round lineage validation", [
        SheetSpec("Summary", ["Item", "Value"], summary, [60, 90],
                  notes=["Independent re-derivation with the v7.12 engine from the original v7.11 round files (hashes recorded); "
                         "rows matched by Internal_ID; synthetic data throughout."]),
        SheetSpec("Rounds", ["Round", "Observations", "Current round read", "Last column", "Data sheet", "SHA-256 (16)", "Word file"], rounds, [7, 12, 14, 10, 34, 18, 60]),
        SheetSpec("Pairs", ["Pair", "Owner inputs (round r)", "Late owner edits (< r)", "Protected cells changed", "Format losses", "New rows in r+1", "Not-raised text", "Missing rows"], pairs,
                  [10, 14, 14, 16, 12, 40, 12, 20], status_col="Not-raised text"),
        SheetSpec("Owner changes", ["Pair", "Internal_ID", "Field", "Before", "After", "Class"], rep["owner_rows"], [8, 20, 10, 50, 50, 24], status_col="Class"),
        SheetSpec("Word", ["Round", "Comments", "GCO with REF", "Round comments", "Expected (v7.11 rule)", "Expected (v7.12 rule, 16.1)",
                           "Reopened without follow-up", "Threaded replies", "Checks"], word, [7, 10, 12, 12, 14, 16, 22, 12, 80]),
        SheetSpec("Dashboard recalculation", ["Selected round", "Formulas", "Compared", "Mismatches", "Errors", "Engine", "Result"], dash, [12, 10, 10, 11, 9, 28, 9], status_col="Result"),
        SheetSpec("Checks", ["Check", "Result", "Detail"], checks, [34, 14, 110], status_col="Result"),
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("round_dir")
    ap.add_argument("--external")
    ap.add_argument("--out", default=str(ROOT / "deliverables"))
    a = ap.parse_args(argv)
    t = time.time()
    rep = audit(Path(a.round_dir), Path(a.out), Path(a.external) if a.external else None)
    print(json.dumps({k: rep[k] for k in ("rounds", "totals", "summary")}, ensure_ascii=False, indent=1, default=str))
    for c in rep["checks"]:
        print(f"{c[0]:34} {'PASS' if c[1] is True else ('FAIL' if c[1] is False else 'N/A '):5} {c[2][:120]}")
    print(f"{time.time() - t:.1f} s")
    return 0 if rep["summary"]["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
