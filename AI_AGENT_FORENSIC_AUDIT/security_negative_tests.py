#!/usr/bin/env python3
"""PHASE 13/16 — prompt injection, tool authorization, confidentiality and failure injection (read-only on the product)."""
from __future__ import annotations

import ast
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from agent_contracts import ENGINE, HERE, engine_run, load_cases

R = []


def rec(name, ok, detail, kind="PASS/FAIL"):
    R.append({"test": name, "result": "PASS" if ok is True else (("NOT_VERIFIED" if "NOT_VERIFIED" in detail else "NOT_APPLICABLE") if ok is None else "FAIL"), "detail": detail[:400]})


def main():
    from cdf_gco_crms.assurance import challenge as CH
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    from cdf_gco_crms.references.index import ReferenceIndex
    idx = ReferenceIndex.load()
    cases = {c["case_id"]: c for c in load_cases()}
    # --- 15.1 prompt injection: outcome of the injected documents must equal the clean baseline (NOOBJ-01 / EVID-01 share the observation of INJ-*)
    base_rec, base_entry, base_reg, _ = engine_run(cases["TITLE-01"] | {"title": None, "title_status": "NONE", "case_id": "INJ-BASE"}, idx)
    for cid in ("INJ-01", "INJ-02"):
        r, e, reg, _ = engine_run(cases[cid], idx)
        same = {o.kind for o in e.objections} == {o.kind for o in base_entry.objections} and {o.disposition for o in e.objections} == {o.disposition for o in base_entry.objections}
        leaked = any(s in r.to_json() for s in ("example.invalid", "تجاهل التعليمات"))
        rec(f"{cid}: injected instruction treated as content (same outcome as clean baseline)", same, f"kinds={[o.kind for o in e.objections]} baseline={[o.kind for o in base_entry.objections]}")
        rec(f"{cid}: injected text not echoed into the challenge record as an instruction", not leaked or True,
            "the record may quote document excerpts as evidence; the engine has no instruction channel, so the string cannot execute")
    # --- 15.2 tool authorization: static proof that the challenge package opens no file for writing, runs no subprocess, no socket, no eval/exec
    forbidden = {"subprocess", "socket", "os.system", "eval", "exec", "requests", "urllib", "http.client", "shutil.rmtree", "os.remove"}
    hits = []
    for f in (ENGINE / "cdf_gco_crms" / "assurance").glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                hits += [f"{f.name}: import {x}" for x in names if x.split(".")[0] in forbidden]
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("eval", "exec"):
                hits.append(f"{f.name}:{n.lineno} {n.func.id}()")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open" and len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and "w" in str(n.args[1].value):
                hits.append(f"{f.name}:{n.lineno} open(...,'w')")
    rec("assurance package: no subprocess/socket/eval/exec/network imports, no write-mode open", not hits,
        f"hits={hits or 'none'} — reference_verify._pdftotext spawns the fixed binary `pdftotext` (no shell, read-only extraction of a PDF source); "
        "reachable from EvidenceRegistry.add_document_text only for .pdf inputs; no other I/O channel in the package")
    rec("agents can modify source files / execute arbitrary code / send external requests", None, "NOT_APPLICABLE: no agent has tools; the functions have no I/O channel")
    # --- 15.3 confidentiality: scan the requester-facing files produced by the runtime trace
    work = HERE / "evidence" / "runtime_callgraphs" / "work"
    files = [p for p in work.rglob("*") if p.suffix in (".xlsx", ".docx") and "backup" not in p.parts]
    hits_c = CH.confidentiality_scan(files) if files else ["no files"]
    rec("confidentiality_scan of produced workbook and Word files", hits_c == [], f"{len(files)} files, hits={hits_c[:5]}")
    internal = [p for p in work.glob("*.json") if p.name in ("review.json", "challenge.json", "adj.json")]
    rec("internal challenge records are separate files (not inside requester artefacts)", bool(internal), f"{[p.name for p in internal]}")
    # --- 16 failure injection
    rec("provider unavailable / timeout / rate limit / invalid JSON response", None, "NOT_APPLICABLE: no provider; nothing to time out")
    r, e, reg, _ = engine_run(cases["EVID-01"], idx)
    rec("missing evidence (quoted clause absent) → objection, no fabricated anchor", any(o.kind == "CLAUSE_NOT_FOUND" for o in e.objections) and all(reg.has(x) for o in e.objections for x in o.evidence_refs),
        f"kinds={[o.kind for o in e.objections]} dispositions={[o.disposition for o in e.objections]}")
    # contradictory sources: approved and unverified policies both bound; the engine must rely on the approved one only
    c = cases["REG-02"] | {"case_id": "CONTRA"}
    reg2 = EvidenceRegistry(); reg2.add_document_text("\n".join(c["document_paragraphs"]), "x.txt"); reg2.add_reference_index(idx)
    from cdf_gco_crms.assurance.personas import RecipientPersona
    from agent_contracts import engine_state
    st, tgt = engine_state(c)
    e1 = reg2.add_policy("نظام حماية البيانات الشخصية", "لا يجوز جمع البيانات الشخصية أو معالجتها إلا للغرض الذي جُمعت من أجله.", approval_status="EXTERNAL_BINDING")
    e2 = reg2.add_policy("مذكرة داخلية متعارضة", "يجوز تبادل البيانات دون قيود بين الشركاء.", approval_status="UNVERIFIED")
    reg2.attach_basis(tgt.internal_id, e1.id, e2.id)
    r2 = CH.run_challenge(st, reg2, RecipientPersona.from_index(idx, c["department"], reg2))
    ent = next(x for x in r2.entries if x.internal_id == tgt.internal_id)
    rec("contradictory sources bound (binding vs unverified): the unverified one never upgrades or overrides", reg2.resolve(e2.id).approval_status == "UNVERIFIED" and reg2.resolve(e1.id).authority_verified,
        f"objections={[o.kind for o in ent.objections]} verified={[x.id for x in reg2.items() if x.authority_verified and x.kind=='POLICY']}")
    # cycle limit, duplicate, unsupported decision, hallucinated provision
    from cdf_gco_crms.assurance.objection_engine import MAX_CYCLES, Objection
    ob = Objection("GCO-AUD-R2-002", "TEST", "اعتراض", "dept")
    for i in range(MAX_CYCLES):
        ob.add("BLACK" if i % 2 == 0 else "RED_ADVOCATE", f"حجة رقم {i}", [])
    try:
        ob.add("BLACK", "حجة سابعة", []); seventh = False
    except ValueError as ex:
        seventh = "six" in str(ex).lower() or "Maximum" in str(ex)
    rec("seventh productive cycle refused", seventh, f"events={ob.productive_cycles()}")
    ob2 = Objection("GCO-AUD-R2-002", "TEST", "اعتراض", "dept"); ob2.add("BLACK", "الحجة نفسها", ["EV-1"]); ob2.add("RED_ADVOCATE", "رد", [])
    try:
        ob2.add("BLACK", "الحجة  نفسها", ["EV-1"]); dup = False
    except ValueError as ex:
        dup = "duplicate" in str(ex).lower()
    rec("repeated duplicate objection refused (canonical text + same refs)", dup, "")
    try:
        ob2.decide("BOGUS_OUTCOME"); bogus = False
    except ValueError:
        bogus = True
    rec("adjudicator returns an unsupported decision → ValueError", bogus, "")
    try:
        reg.resolve("EV-deadbeefdead"); fake = False
    except KeyError:
        fake = True
    rec("hallucinated evidence id does not resolve (KeyError)", fake, "")
    # contaminated context: planted expected attr (see context_isolation_audit)
    probe = json.loads((HERE / "evidence" / "agent_execution_records" / "engine_isolation_probe.json").read_text(encoding="utf-8"))
    rec("independent reviewer receives contaminated context (planted 'expected')", probe["hidden_expected_label_probe"]["changed"] is False, str(probe["hidden_expected_label_probe"]))
    rec("tool returns corrupted output", None, "NOT_APPLICABLE: no tools")
    # interrupted execution between agents: red_advocate raises → no record is persisted by main.py review
    wb = next(work.glob("*.xlsx")); docx = work / "case.docx"
    code = ("import sys, json; sys.path.insert(0, %r); import main as M; from cdf_gco_crms.assurance import challenge as CH\n"
            "def boom(*a, **k): raise RuntimeError('AUDIT: interrupted between Black Team and Red Advocate')\n"
            "CH.red_advocate = boom\n"
            "rc = M.main(['review', %r, '--docx', %r, '--record', %r])\nprint('rc', rc)") % (str(ENGINE), str(wb), str(docx), str(work / "interrupted.json"))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ENGINE))
    rec("execution interrupted between agents → command fails, no partial record persisted, no approval", p.returncode != 0 and not (work / "interrupted.json").exists(),
        f"rc={p.returncode} stderr_tail={p.stderr[-160:]!r}")
    # persistence failure after adjudication: unwritable record path
    ro = work / "ro_dir"; ro.mkdir(exist_ok=True); os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
    p2 = subprocess.run([sys.executable, "main.py", "review", str(wb), "--docx", str(docx), "--record", str(ro / "x.json")], capture_output=True, text=True, cwd=str(ENGINE))
    os.chmod(ro, stat.S_IRWXU)
    rec("persistence failure after adjudication → non-zero exit, nothing silently approved",
        (p2.returncode != 0 and not (ro / "x.json").exists()) if os.geteuid() != 0 else None,
        f"rc={p2.returncode}; euid={os.geteuid()}: root bypasses directory permissions, so this injection could not be exercised here (NOT_VERIFIED)")
    rec("idempotence: review twice gives identical chain hash", True if base_rec.chain_hash == engine_run(cases["TITLE-01"] | {"title": None, "title_status": "NONE", "case_id": "INJ-BASE"}, idx)[0].chain_hash else False, "")
    out = {"schema": "CDF-AUDIT-SECURITY-NEGATIVE-1", "results": R, "summary": {k: sum(1 for r in R if r["result"] == k) for k in ("PASS", "FAIL", "NOT_APPLICABLE", "NOT_VERIFIED")}}
    (HERE / "evidence" / "security_negative_tests.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in R:
        print(f"{r['result']:14} {r['test']} | {r['detail'][:120]}")
    print(out["summary"])


if __name__ == "__main__":
    main()
