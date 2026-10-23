#!/usr/bin/env python3
"""CDF–GCO–CRMS v7.12 workbook engine – command line.

Commands
  round1   INPUT.json OUT_DIR                 build the round-1 requester workbook
  append   RETURNED.xlsx INPUT.json OUT_DIR [--delivered DELIVERED.xlsx]
                                              read the workbook the owner returned, keep the owner's
                                              entries, restore GCO cells from the delivered copy, append
                                              the next round and rebuild the dashboard
  rebuild  WORKBOOK.xlsx OUT_DIR              rebuild helper sheet and dashboard from the data sheet
  migrate  V710.xlsx OUT_DIR                  v7.10 or v7.11 to v7.12 migration (see migrate_to_v712.py)
  verify   WORKBOOK.xlsx                      recalculate every round's view in LibreOffice and compare
  gates    WORKBOOK.xlsx [--previous P.xlsx] [--docx D.docx]
                                              run the G-DASH and G-UX gates and print the results

v7.12 workflow commands (patch V712-003; every command prints JSON and returns a code)
  inventory FILE... [--json OUT]             SHA-256 manifest and safe-ingestion report of every input (15A.6)
  ingest    WORKBOOK.xlsx [--json OUT]        safe-open and parse a workbook; schema, warnings, integrity flags
  finalize-titles WORKBOOK.xlsx DECISIONS.json OUT_DIR [--issue]
                                              apply recorded reviewer decisions on titles (10.4A.16, 19A.9)
  build-excel WORKBOOK.xlsx OUT_DIR [--issue] rebuild the workbook from its data sheet; --issue freezes approved titles
  build-word  WORKBOOK.xlsx OUT.docx [--round N] [--source CASE.docx]
                                              Word file with native GCO comments (threads for follow-ups, G-SYNC-9)
  import-owner-return DELIVERED.xlsx RETURNED.xlsx [--docx-delivered D.docx --docx-returned R.docx] [--json OUT]
                                              delta of the owner's return: owner inputs, GCO cells restored, tampering
  audit-history ROUND_DIR OUT_DIR [--external AUDIT.xlsx]
                                              lineage audit of a round series (16.1 / G-HIST)
  qa        WORKBOOK.xlsx [--previous P] [--docx D] [--verify] [--json OUT]
                                              gates as JSON; code 1 on any FAIL (gates whose input is not supplied FAIL)
  demo-e2e  OUT_DIR [--rounds N]              synthetic round 1 → owner return → rounds 2..N with Word files
  release   FILE.xlsx... [--json OUT]         production guard; never OPERATIONALLY_APPROVED from this command
  review    WORKBOOK.xlsx --docx CASE.docx [--department NAME] [--record OUT.json]
                                              19A challenge of every drafted observation; code 1 while a blocker stands
  challenge WORKBOOK.xlsx --docx CASE.docx    review + confidentiality scan of the files that would be issued (19A.9)
  adjudicate WORKBOOK.xlsx DECISIONS.json --docx CASE.docx [--trust-store KEYS.json]
                                              apply signed reviewer decision records to the blockers; booleans are refused

Return codes: 0 OK · 1 gate or check FAIL · 2 input/schema error · 3 refused by policy · 4 NOT_VERIFIED / BLOCKED_EXTERNAL

JSON input (UTF-8)
  round1: {"document": {"name": "...", "code": "PL", "cover_version": "...", "owning_department": "..."},
           "date": "2026-10-23",
           "observations": [{"location": "ص.3، المادة (2) – البند (2-1)", "quote": "…",
                             "comment": [["سبب.", false], ["\\nالتوصية:", true], [" الإجراء.", false]]}]}
  append: {"round": 2, "date": "2026-11-10", "document_version": "الإصدار 0.2",
           "assessments": [{"internal_id": "GCO-PL-R1-001", "status": "مغلقة",
                            "feedback": [["عُدّل النص.", false]], "closure_basis": "VERIFIED_TEXT"}],
           "new_observations": [{"location": "…", "quote": "…", "comment": "…", "reason": "…"}]}
  A comment or feedback is either a string or a list of [text, bold] runs (labels such as "التوصية:" bold).
  Every row that is not مغلقة at the start of the round needs an assessment; rows already closed are
  carried forward automatically (10.2). Dates and versions are written only when supplied.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdf_gco_crms.assurance.issuance_gate import (  # noqa: E402
    DRAFT_CLASSIFICATION, IssuanceDenied, authorize_cli_export,
)
from cdf_gco_crms.config import workbook_settings as W  # noqa: E402
from cdf_gco_crms.model.entities import Document, GText, RoundAssessment, Segment  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import NewObservation, RoundInput, apply_round, build_round1  # noqa: E402


def _text(v):
    if v is None:
        return None
    if isinstance(v, str):
        return GText.plain(v)
    return GText([Segment(t, bool(b)) for t, b in v])


def _new(o):
    return NewObservation(o["location"], o["quote"], _text(o["comment"]), o.get("reason"))


def _draft_output(path, a):
    return authorize_cli_export(path, internal_draft=getattr(a, 'internal_draft', False),
                                issuance_requested=getattr(a, 'issue', False))


def cmd_round1(a):
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    spec = json.loads(Path(a.input).read_text(encoding="utf-8"))
    d = spec["document"]
    doc = Document(name=d["name"], code=d["code"], cover_version=d.get("cover_version"),
                   owning_department=d.get("owning_department"), is_demo=bool(d.get("is_demo")))
    st = build_round1(doc, [_new(o) for o in spec["observations"]], date=spec.get("date"),
                      document_version=d.get("cover_version"))
    out = _draft_output(Path(a.out_dir) / f"{W.file_stem(doc.name, 1)}.xlsx", a)
    res = build_workbook(st, out)
    print(out)
    return res


def _load_state(path, a=None):
    from cdf_gco_crms.ingestion.workbook_reader import parse_workbook
    overrides = {}
    if a is not None and getattr(a, "name", None):
        overrides["name"] = a.name
    return parse_workbook(path, overrides=overrides)


def cmd_append(a):
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.reconciliation.historical import merge_returned, view_sheet_edits
    spec = json.loads(Path(a.input).read_text(encoding="utf-8"))
    returned = _load_state(a.returned, a)
    state = returned.state
    report = {}
    if a.delivered:
        delivered = _load_state(a.delivered, a).state
        state, intake = merge_returned(delivered, returned.state)
        report = {"gco_cell_edits_restored": [f"{d.internal_id}:{d.key}" for d in intake.gco_cell_edits],
                  "format_losses_restored": [f"{d.internal_id}:{d.key}" for d in intake.format_losses],
                  "late_owner_edits_kept": [f"{d.internal_id}:{d.key}" for d in intake.late_owner_edits],
                  "missing_rows_restored": intake.missing_rows, "owner_inputs": intake.owner_inputs,
                  "notes": intake.notes}
        vedits, vmissing = view_sheet_edits(a.delivered, a.returned)
        report["dashboard_or_helper_edits_channel_x"] = [f"{e.sheet}!{e.coordinate}: {e.returned!r}" for e in vedits]
        report["dashboard_or_helper_missing"] = vmissing
    n = int(spec["round"])
    rin = RoundInput(n, spec.get("date"), spec.get("document_version"),
                     [RoundAssessment(x["internal_id"], n, x["status"], _text(x.get("feedback")), x.get("closure_basis"))
                      for x in spec.get("assessments", [])],
                     [_new(o) for o in spec.get("new_observations", [])])
    new_state, rep = apply_round(state, rin)
    out = _draft_output(Path(a.out_dir) / f"{W.file_stem(new_state.document.name, new_state.current_round)}.xlsx", a)
    build_workbook(new_state, out)
    report.update({"action": rep.action, "carried_closed": len(rep.carried_closed), "assessed": len(rep.assessed),
                   "reopened": rep.reopened, "new": rep.new_ids, "output": str(out)})
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_rebuild(a):
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    pw = _load_state(a.workbook, a)
    out = _draft_output(Path(a.out_dir) / Path(a.workbook).name, a)
    if out.resolve() == Path(a.workbook).resolve():
        sys.exit("the output must not overwrite the input")
    build_workbook(pw.state, out)
    print(out)


def cmd_verify(a):
    from cdf_gco_crms.model.entities import DashboardViewState
    from cdf_gco_crms.qa.recalc_verify import check_view, standard_views
    pw = _load_state(a.workbook, a)
    ok = True
    for vs in standard_views(pw.state):
        vc = check_view(pw.state, vs, Path(a.workdir))
        ok &= vc.ok
        print(("OK  " if vc.ok else "BAD ") + vc.view, vc.message)
    sys.exit(0 if ok else 1)


def cmd_gates(a):
    from cdf_gco_crms.qa.gates import GateContext, run_dash_gates
    from cdf_gco_crms.qa.ux_gates import run_ux_gates
    ctx = GateContext(xlsx=Path(a.workbook), previous_xlsx=Path(a.previous) if a.previous else None,
                      docx=Path(a.docx) if a.docx else None,
                      logo_source=Path(__file__).resolve().parent / "assets" / "cdf_logo_horizontal_source.jpg")
    dash = run_dash_gates(ctx)
    for g in dash + run_ux_gates(ctx, dash):
        print(f"{g.gate:10} {g.status:13} {g.name}: {g.actual[:120]}")


# ============================================================================ v7.12 commands
RC_OK, RC_FAIL, RC_INPUT, RC_REFUSED, RC_NOT_VERIFIED = 0, 1, 2, 3, 4


def _emit(obj, path=None):
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")
    print(text)


def cmd_inventory(a):
    from cdf_gco_crms.ingestion.safe_open import inspect_package, sha256_file
    rows = []
    worst = RC_OK
    for f in a.files:
        p = Path(f)
        if not p.is_file():
            rows.append({"file": f, "status": "MISSING"}); worst = max(worst, RC_INPUT); continue
        row = {"file": f, "sha256": sha256_file(p), "bytes": p.stat().st_size}
        kind = "xlsx" if p.suffix.lower() in (".xlsx", ".xlsm") else "docx" if p.suffix.lower() == ".docx" else None
        if kind:
            rep = inspect_package(p, kind)
            row.update({"kind": kind, "safe": rep.ok, "findings": rep.findings, "members": rep.members})
            if not rep.ok:
                worst = max(worst, RC_REFUSED)
        rows.append(row)
    _emit({"schema": "CDF-v7.12-INVENTORY-1", "files": rows}, a.json)
    return worst


def cmd_ingest(a):
    from cdf_gco_crms.rounds.round_parser import SchemaError
    try:
        pw = _load_state(a.workbook, a)
    except SchemaError as e:
        _emit({"status": "REFUSED" if e.code == "UNSAFE_INPUT" else "SCHEMA_ERROR", "code": e.code, "detail": str(e)}, a.json)
        return RC_REFUSED if e.code == "UNSAFE_INPUT" else RC_INPUT
    st = pw.state
    _emit({"status": "OK", "kind": pw.kind, "document": st.document.name, "code": st.document.code,
           "rounds": [r.number for r in st.rounds], "observations": len(st.observations),
           "titles": {k: sum(1 for o in st.observations if o.title_status == k) for k in
                      ("NONE", "DRAFT", "PROPOSED", "APPROVED", "ISSUED")},
           "unkeyed_rows": pw.unkeyed_rows, "extra_sheets": pw.extra_sheets, "warnings": pw.warnings}, a.json)
    return RC_FAIL if any(w.startswith("FORMULA_IN_DATA") for w in pw.warnings) else RC_OK


def cmd_finalize_titles(a):
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.rounds.round_expansion import TitleDecision, finalize_titles, mark_titles_issued
    pw = _load_state(a.workbook, a)
    spec = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
    items = spec["decisions"] if isinstance(spec, dict) else spec
    decisions = []
    for d in items:
        if not isinstance(d, dict) or isinstance(d.get("decision"), bool):
            _emit({"status": "REFUSED", "detail": "a decision is a record (reviewer, date, decision_ref), not a boolean (19A.9)"})
            return RC_REFUSED
        decisions.append(TitleDecision(d.get("internal_id", ""), str(d.get("decision", "")), d.get("reviewer", ""),
                                       d.get("date", ""), d.get("decision_ref", ""), d.get("title")))
    new, rep = finalize_titles(pw.state, decisions)
    if rep.refused and not a.allow_partial:
        _emit({"status": "REFUSED", "refused": rep.refused, "detail": "no output written; use --allow-partial to apply the accepted decisions"})
        return RC_REFUSED
    issued = mark_titles_issued(new) if a.issue else 0
    out = _draft_output(Path(a.out_dir) / Path(a.workbook).name, a)
    if out.resolve() == Path(a.workbook).resolve():
        sys.exit("the output must not overwrite the input")
    build_workbook(new, out)
    _emit({"status": "OK", "approved": rep.approved, "rejected": rep.rejected, "withdrawn": rep.withdrawn,
           "refused": rep.refused, "issued": issued, "output": str(out)})
    return RC_OK


def cmd_build_excel(a):
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.rounds.round_expansion import mark_titles_issued
    pw = _load_state(a.workbook, a)
    out = _draft_output(Path(a.out_dir) / Path(a.workbook).name, a)
    if out.resolve() == Path(a.workbook).resolve():
        sys.exit("the output must not overwrite the input")
    issued = mark_titles_issued(pw.state) if a.issue else 0
    build_workbook(pw.state, out)
    _emit({"status": "OK", "output": str(out), "issued_titles": issued, "warnings": pw.warnings})
    return RC_OK


def cmd_build_word(a):
    pw = _load_state(a.workbook, a)
    out = _draft_output(Path(a.out), a)
    out.parent.mkdir(parents=True, exist_ok=True)
    if a.source:
        try:
            from cdf_gco_crms.word.document_comments import comment_document
        except ImportError:
            _emit({"status": "NOT_AVAILABLE", "detail": "cdf_gco_crms.word.document_comments is not installed"})
            return RC_INPUT
        rep = comment_document(a.source, pw.state, out, round_no=a.round)
        _emit({"status": "OK", "output": str(out), "report": getattr(rep, "__dict__", rep)})
        return RC_OK
    from cdf_gco_crms.word.word_sync import build_review_docx, reconcile
    build_review_docx(pw.state, out, round_no=a.round)
    sync = reconcile(out, a.workbook, round_no=a.round)
    _emit({"status": "OK" if sync.ok else "FAIL", "output": str(out), "checks": getattr(sync, "checks", None)})
    return RC_OK if sync.ok else RC_FAIL


def cmd_import_owner_return(a):
    from cdf_gco_crms.reconciliation.historical import merge_returned, view_sheet_edits
    delivered = _load_state(a.delivered, a)
    returned = _load_state(a.returned, a)
    merged, intake = merge_returned(delivered.state, returned.state)
    vedits, vmissing = view_sheet_edits(a.delivered, a.returned)
    tampering = [f"{d.internal_id}:{d.key}" for d in intake.gco_cell_edits]
    rep = {"status": "TAMPERED" if tampering else "OK",
           "owner_inputs": intake.owner_inputs,
           "gco_cell_edits_restored": tampering,
           "format_losses_restored": [f"{d.internal_id}:{d.key}" for d in intake.format_losses],
           "late_owner_edits_kept": [f"{d.internal_id}:{d.key}" for d in intake.late_owner_edits],
           "missing_rows_restored": intake.missing_rows, "notes": intake.notes,
           "dashboard_or_helper_edits_channel_x": [f"{e.sheet}!{e.coordinate}: {e.returned!r}" for e in vedits],
           "dashboard_or_helper_missing": vmissing,
           "formula_flags": [w for w in returned.warnings if w.startswith("FORMULA_IN_DATA")]}
    if a.docx_delivered and a.docx_returned:
        try:
            from cdf_gco_crms.word.document_comments import diff_returned
            rep["word"] = diff_returned(a.docx_delivered, a.docx_returned)
        except ImportError:
            rep["word"] = "document_comments not available"
    _emit(rep, a.json)
    return RC_FAIL if tampering or rep["formula_flags"] else RC_OK


def cmd_audit_history(a):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
    from lineage_audit import audit
    rep = audit(Path(a.round_dir), Path(a.out_dir), Path(a.external) if a.external else None)
    _emit({"status": "OK" if rep["summary"]["fail"] == 0 else "FAIL", "summary": rep["summary"], "totals": rep.get("totals")})
    return RC_OK if rep["summary"]["fail"] == 0 else RC_FAIL


def cmd_qa(a):
    from cdf_gco_crms.qa.gates import GateContext, run_dash_gates
    from cdf_gco_crms.qa.ux_gates import run_ux_gates
    vcs = []
    if a.verify:
        from cdf_gco_crms.qa.recalc_verify import check_view, standard_views
        pw = _load_state(a.workbook, a)
        vcs = [check_view(pw.state, vs, Path(a.workdir)) for vs in standard_views(pw.state)]
    ctx = GateContext(xlsx=Path(a.workbook), previous_xlsx=Path(a.previous) if a.previous else None,
                      docx=Path(a.docx) if a.docx else None, view_checks=vcs,
                      refresh={"before": a.previous, "after": a.workbook} if a.previous else None,
                      logo_source=Path(__file__).resolve().parent / "assets" / "cdf_logo_horizontal_source.jpg")
    dash = run_dash_gates(ctx)
    res = dash + run_ux_gates(ctx, dash)
    rows = [{"gate": g.gate, "status": g.status, "name": g.name, "actual": g.actual} for g in res]
    counts = {}
    for g in res:
        counts[g.status] = counts.get(g.status, 0) + 1
    _emit({"workbook": a.workbook, "counts": counts, "gates": rows}, a.json)
    if counts.get("FAIL"):
        return RC_FAIL
    return RC_NOT_VERIFIED if counts.get("NOT_VERIFIED") else RC_OK


def cmd_demo_e2e(a):
    from cdf_gco_crms.regression import synthetic as SY
    from cdf_gco_crms.word.word_sync import build_review_docx, reconcile
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    h = SY.demo_history(out, rounds=a.rounds)
    rep = {"status": "OK", "rounds": {}, "note": "synthetic demonstration (is_demo); never an institutional deliverable"}
    ok = True
    for r, f in sorted(h.files.items()):
        docx = out / (f.stem + ".docx")
        build_review_docx(h.states[r], docx, round_no=r)
        sync = reconcile(docx, f, round_no=r)
        ok &= sync.ok
        rep["rounds"][r] = {"xlsx": str(f), "docx": str(docx), "word_sync": "OK" if sync.ok else "FAIL",
                            "observations": len(h.states[r].observations)}
    rep["status"] = "OK" if ok else "FAIL"
    _emit(rep, out / "demo-e2e.json")
    return RC_OK if ok else RC_FAIL


def cmd_release(a):
    from cdf_gco_crms.assurance.production_guard import evaluate_many
    results = evaluate_many(a.files, a.json or "build/release-guard.json", declared_institutional=not a.demo)
    statuses = {r["status"] for r in results}
    _emit({"results": results, "note": "a release decision is a human institutional act; this command only reports gates"})
    if any("INCOMPLETE" in s for s in statuses):
        return RC_FAIL
    return RC_NOT_VERIFIED


def _challenge_record(a):
    from cdf_gco_crms.assurance import challenge as CH
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    from cdf_gco_crms.assurance.personas import RecipientPersona
    from cdf_gco_crms.references.index import ReferenceIndex
    pw = _load_state(a.workbook, a)
    st = pw.state
    reg = EvidenceRegistry()
    reg.add_document_text(a.docx)
    dept = a.department or st.document.owning_department or ""
    persona = RecipientPersona.from_index(ReferenceIndex.load(), dept, reg)
    return CH, st, reg, CH.run_challenge(st, reg, persona)


def cmd_review(a):
    """19A pre-issue challenge of every drafted observation; the record stays internal (build/adversarial)."""
    CH, st, reg, rec = _challenge_record(a)
    out = Path(a.record or f"build/adversarial/challenge_{st.document.code}_R{st.current_round}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rec.to_json(), encoding="utf-8")
    blockers = rec.blockers()
    _emit({"status": "BLOCKED" if blockers else "CLEAR", "record": str(out), "independence": rec.independence,
           "role_isolation": rec.role_isolation, "chains_verified": rec.verify_chains(), "dispositions": rec.dispositions,
           "cycles_used": rec.cycles_used, "blockers": blockers,
           "note": "an issue is refused while a blocker stands; only a verified reviewer decision record clears it (19A.9)"})
    return RC_FAIL if blockers else RC_OK


def cmd_challenge(a):
    """Review + confidentiality scan of the requester-facing files that would be issued (19A.9)."""
    rc = cmd_review(a)
    from cdf_gco_crms.assurance.challenge import confidentiality_scan
    hits = confidentiality_scan([Path(a.workbook), Path(a.docx)])
    _emit({"confidentiality_scan": hits})
    return RC_REFUSED if hits else rc


def cmd_adjudicate(a):
    """Apply recorded, signed reviewer decisions to the blockers of a re-run challenge (deterministic ids)."""
    import base64
    from cdf_gco_crms.assurance.objection_engine import HumanDecision
    CH, st, reg, rec = _challenge_record(a)
    items = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
    items = items["decisions"] if isinstance(items, dict) else items
    decisions = []
    for d in items:
        if not isinstance(d, dict) or isinstance(d.get("decision"), bool):
            _emit({"status": "REFUSED", "detail": "a decision is a signed record, not a boolean (19A.9)"})
            return RC_REFUSED
        decisions.append(HumanDecision(**{k: d.get(k, "") for k in ("decision_id", "observation_id", "decision", "reviewer", "role",
                                                                     "reference", "timestamp", "evidence_ref", "verification_status",
                                                                     "signing_key_id", "signature_b64")}))
    trust = {}
    if a.trust_store:
        trust = {k: base64.b64decode(v) for k, v in json.loads(Path(a.trust_store).read_text(encoding="utf-8")).items()}
    res = CH.apply_human_decisions(rec, decisions, trust, registry=reg)
    out = Path(a.record or f"build/adversarial/challenge_{st.document.code}_R{st.current_round}_adjudicated.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rec.to_json(), encoding="utf-8")
    _emit({"status": "CLEAR" if not res["remaining_blockers"] else "BLOCKED", "record": str(out), **res})
    return RC_OK if not res["remaining_blockers"] else RC_FAIL


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("round1"); p.add_argument("input"); p.add_argument("out_dir"); p.add_argument("--internal-draft", action="store_true")
    p = sub.add_parser("append"); p.add_argument("returned"); p.add_argument("input"); p.add_argument("out_dir")
    p.add_argument("--delivered"); p.add_argument("--name"); p.add_argument("--internal-draft", action="store_true")
    p = sub.add_parser("rebuild"); p.add_argument("workbook"); p.add_argument("out_dir"); p.add_argument("--name"); p.add_argument("--internal-draft", action="store_true")
    p = sub.add_parser("migrate"); p.add_argument("source"); p.add_argument("out_dir"); p.add_argument("--internal-draft", action="store_true")
    p = sub.add_parser("verify"); p.add_argument("workbook"); p.add_argument("--workdir", default="build/verify_cli")
    p.add_argument("--name")
    p = sub.add_parser("gates"); p.add_argument("workbook"); p.add_argument("--previous"); p.add_argument("--docx")
    # v7.12
    p = sub.add_parser("inventory"); p.add_argument("files", nargs="+"); p.add_argument("--json")
    p = sub.add_parser("ingest"); p.add_argument("workbook"); p.add_argument("--json"); p.add_argument("--name")
    p = sub.add_parser("finalize-titles"); p.add_argument("workbook"); p.add_argument("decisions"); p.add_argument("out_dir")
    p.add_argument("--issue", action="store_true"); p.add_argument("--allow-partial", action="store_true"); p.add_argument("--name"); p.add_argument("--internal-draft", action="store_true")
    p = sub.add_parser("build-excel"); p.add_argument("workbook"); p.add_argument("out_dir")
    p.add_argument("--issue", action="store_true"); p.add_argument("--name"); p.add_argument("--internal-draft", action="store_true")
    p = sub.add_parser("build-word"); p.add_argument("workbook"); p.add_argument("out"); p.add_argument("--round", type=int)
    p.add_argument("--source"); p.add_argument("--name"); p.add_argument("--internal-draft", action="store_true")
    p = sub.add_parser("import-owner-return"); p.add_argument("delivered"); p.add_argument("returned")
    p.add_argument("--docx-delivered"); p.add_argument("--docx-returned"); p.add_argument("--json"); p.add_argument("--name")
    p = sub.add_parser("audit-history"); p.add_argument("round_dir"); p.add_argument("out_dir"); p.add_argument("--external")
    p = sub.add_parser("qa"); p.add_argument("workbook"); p.add_argument("--previous"); p.add_argument("--docx"); p.add_argument("--json")
    p.add_argument("--verify", action="store_true", help="recalculate the standard views in LibreOffice first")
    p.add_argument("--workdir", default="build/verify_cli"); p.add_argument("--name")
    p = sub.add_parser("demo-e2e"); p.add_argument("out_dir"); p.add_argument("--rounds", type=int, default=5)
    p = sub.add_parser("release"); p.add_argument("files", nargs="+"); p.add_argument("--json"); p.add_argument("--demo", action="store_true")
    for name in ("review", "challenge", "adjudicate"):
        p = sub.add_parser(name); p.add_argument("workbook"); p.add_argument("--docx", required=True)
        p.add_argument("--department"); p.add_argument("--record"); p.add_argument("--name")
        if name == "adjudicate":
            p.add_argument("decisions"); p.add_argument("--trust-store", help="JSON {key_id: base64 raw Ed25519 public key}")
    a = ap.parse_args(argv)
    # Central CLI preflight: no input parsing or output creation before the gate.
    # This does not replace the institutional authorization service required for
    # production; it makes every regular exporting CLI command fail closed now.
    export_commands = {"round1", "append", "rebuild", "migrate", "finalize-titles",
                       "build-excel", "build-word"}
    if a.cmd in export_commands:
        try:
            authorize_cli_export(Path("preflight.xlsx"),
                                 internal_draft=getattr(a, "internal_draft", False),
                                 issuance_requested=getattr(a, "issue", False))
        except IssuanceDenied as exc:
            _emit({"status": "REFUSED", "detail": str(exc),
                   "classification": DRAFT_CLASSIFICATION, "no_output_generated": True})
            return RC_REFUSED
    if a.cmd == "migrate":
        try:
            authorize_cli_export(Path(a.out_dir) / "migration.xlsx", internal_draft=a.internal_draft)
        except IssuanceDenied as exc:
            _emit({"status": "REFUSED", "detail": str(exc)})
            return RC_REFUSED
        from migrate_to_v712 import main as mig
        return mig([a.source, str(Path(a.out_dir) / "INTERNAL_DRAFT_ONLY")])
    if a.cmd in ("review", "challenge", "adjudicate"):
        return {"review": cmd_review, "challenge": cmd_challenge, "adjudicate": cmd_adjudicate}[a.cmd](a)
    fn = {"round1": cmd_round1, "append": cmd_append, "rebuild": cmd_rebuild, "verify": cmd_verify, "gates": cmd_gates,
          "inventory": cmd_inventory, "ingest": cmd_ingest, "finalize-titles": cmd_finalize_titles,
          "build-excel": cmd_build_excel, "build-word": cmd_build_word, "import-owner-return": cmd_import_owner_return,
          "audit-history": cmd_audit_history, "qa": cmd_qa, "demo-e2e": cmd_demo_e2e, "release": cmd_release}[a.cmd]
    try:
        return fn(a)
    except IssuanceDenied as exc:
        _emit({"status": "REFUSED", "classification": DRAFT_CLASSIFICATION,
               "detail": str(exc), "no_output_generated": True})
        return RC_REFUSED


if __name__ == "__main__":
    rc = main()
    sys.exit(rc if isinstance(rc, int) else 0)
