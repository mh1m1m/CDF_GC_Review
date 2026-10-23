#!/usr/bin/env python3
"""Reproducible production release candidate (patch V712-060).

Assembles dist/rc/ with the ten folders the execution directive names, writes SHA256SUMS.txt, INSTALL.md and
RELEASE-NOTE.md, zips it to dist/CDF-GCO-CRMS-v7.12-PRODUCTION-RC-COMPLETE.zip, reopens the zip and checks every
member, and writes CHECKPOINT.md at the project root. The release note never says OPERATIONALLY_APPROVED: the
classification comes from PATCH-STATUS.json and the institutional blockers of the gate matrix.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "deliverables"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
RC = DIST / "rc"
ZIP = DIST / "CDF-GCO-CRMS-v7.12-PRODUCTION-RC-COMPLETE.zip"
EXCLUDE = ("__pycache__", ".pyc", ".pytest_cache", ".rejected.json")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy(src: Path, dst: Path):
    if not src.exists():
        return False
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.rejected.json"))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return True


def adversarial_samples(dst: Path):
    """Held-out evaluation and one challenge record on the demonstration workbook (internal records, 04 folder only)."""
    from cdf_gco_crms.assurance import challenge as CH
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    from cdf_gco_crms.assurance.personas import RecipientPersona
    from cdf_gco_crms.assurance.production_guard import evaluate_many
    from cdf_gco_crms.ingestion.workbook_reader import parse_workbook
    from cdf_gco_crms.references.index import ReferenceIndex
    dst.mkdir(parents=True, exist_ok=True)
    idx = ReferenceIndex.load()
    ev = CH.evaluate_held_out(idx)
    (dst / "HELD-OUT-EVALUATION.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    demo = OUT / "CDF-GCO-CRMS-v7.12-EXECUTIVE-DASHBOARD-DEMO.xlsx"
    docx = sorted((OUT / "demo_rounds").glob("*الخامسة*.docx")) or sorted((OUT / "demo_e2e").glob("*الخامسة*.docx"))
    if demo.exists() and docx:
        st = parse_workbook(demo).state
        reg = EvidenceRegistry(); reg.add_document_text(docx[0])
        persona = RecipientPersona.from_index(idx, st.document.owning_department or "الحوكمة والامتثال", reg)
        rec = CH.run_challenge(st, reg, persona)
        (dst / "CHALLENGE-RECORD-DEMO-R5.json").write_text(rec.to_json(), encoding="utf-8")
        scan = CH.confidentiality_scan([demo, docx[0]])
        (dst / "CONFIDENTIALITY-SCAN.json").write_text(json.dumps({"files": [str(demo.name), docx[0].name], "hits": scan}, ensure_ascii=False, indent=1), encoding="utf-8")
    files = [demo] + sorted((OUT / "migration_demo").rglob("*.xlsx"))
    evaluate_many([f for f in files if f.exists() and "backup" not in f.parts], dst / "PRODUCTION-GUARD.json", declared_institutional=False)


def assemble() -> dict:
    if RC.exists():
        shutil.rmtree(RC)
    RC.mkdir(parents=True)
    f = lambda name: RC / name  # noqa: E731
    # 01 protocol
    for n in ("CDF-GCO-CRMS-v7.12-FULL-CONSOLIDATED.docx", "CDF-GCO-CRMS-v7.12-FULL-CONSOLIDATED.md", "CDF-GCO-CRMS-v7.12-FULL-CONSOLIDATED.txt"):
        copy(OUT / n, f("01_PROTOCOL") / n)
    copy(ROOT / "sources" / "CDF-GCO-CRMS-v7.11.txt", f("01_PROTOCOL") / "baseline" / "CDF-GCO-CRMS-v7.11.txt")
    # 02 engine (source tree, install files)
    for n in ("main.py", "migrate_to_v712.py", "migrate_v710_to_v711.py", "README.md", "requirements.txt", "requirements-lock.txt"):
        copy(ROOT / n, f("02_ENGINE") / n)
    for d in ("cdf_gco_crms", "tests", "tools", "assets"):
        copy(ROOT / d, f("02_ENGINE") / d)
    copy(ROOT / "sources" / "v7.12", f("02_ENGINE") / "sources" / "v7.12")
    copy(ROOT / "sources" / "reference", f("02_ENGINE") / "sources" / "reference")
    copy(ROOT / "sources" / "CDF-GCO-CRMS-v7.11.txt", f("02_ENGINE") / "sources" / "CDF-GCO-CRMS-v7.11.txt")
    copy(ROOT / "sources" / "earlier_package", f("02_ENGINE") / "sources" / "earlier_package")
    # 03 executive excel
    copy(OUT / "CDF-GCO-CRMS-v7.12-EXECUTIVE-DASHBOARD-DEMO.xlsx", f("03_EXECUTIVE_EXCEL") / "CDF-GCO-CRMS-v7.12-EXECUTIVE-DASHBOARD-DEMO.xlsx")
    copy(OUT / "demo_rounds", f("03_EXECUTIVE_EXCEL") / "demo_rounds")
    copy(OUT / "demo_e2e", f("03_EXECUTIVE_EXCEL") / "demo_e2e")
    copy(OUT / "screenshots", f("03_EXECUTIVE_EXCEL") / "screenshots")
    copy(OUT / "CDF - Cell Guidance Dictionary.xlsx", f("03_EXECUTIVE_EXCEL") / "CDF - Cell Guidance Dictionary.xlsx")
    # 04 adversarial
    adversarial_samples(f("04_ADVERSARIAL_ASSURANCE"))
    # 05 branding
    for n in ("CDF - Brand Identity Verification.xlsx", "CDF - Excel UX Audit.xlsx", "CDF - 50 UX Innovations Implementation Matrix.xlsx"):
        copy(OUT / n, f("05_BRANDING") / n)
    for n in ("guide_page12.png", "guide_page21.png", "chatgpt_brand_tokens.json"):
        copy(ROOT / "sources" / "v7.12" / n, f("05_BRANDING") / n)
    # 06 migration
    copy(OUT / "migration_demo", f("06_MIGRATION") / "migration_demo")
    for n in ("migrate_to_v712.py", "migrate_v710_to_v711.py"):
        copy(ROOT / n, f("06_MIGRATION") / n)
    for n in ("CDF-GCO-CRMS-v7.12-LINEAGE-VALIDATION.xlsx", "CDF-GCO-CRMS-v7.12-LINEAGE-VALIDATION.json"):
        copy(OUT / n, f("06_MIGRATION") / n)
    # 07 QA
    for n in ("CDF-GCO-CRMS-v7.12-QA-REPORT.md", "CDF-GCO-CRMS-v7.12-REGRESSION-RESULTS.xlsx", "CDF-GCO-CRMS-v7.12-IMPLEMENTATION-GUIDE.md",
              "CDF-GCO-CRMS-v7.12-REFERENCE-INDEX.xlsx", "CDF - Cell Guidance Dictionary.json"):
        copy(OUT / n, f("07_QUALITY_ASSURANCE") / n)
    copy(BUILD / "junit.xml", f("07_QUALITY_ASSURANCE") / "junit.xml")
    st = json.loads((BUILD / "state.json").read_text(encoding="utf-8")) if (BUILD / "state.json").exists() else {}
    (f("07_QUALITY_ASSURANCE") / "GATES.json").write_text(json.dumps({"summary": st.get("gate_summary"), "gates": st.get("gates"), "views": st.get("views"),
                                                                     "perf": st.get("perf")}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    # 08 crosswalk
    copy(OUT / "CDF-GCO-CRMS-v711-v712-CROSSWALK.xlsx", f("08_CROSSWALK") / "CDF-GCO-CRMS-v711-v712-CROSSWALK.xlsx")
    copy(OUT / "CDF-GCO-CRMS-v7.12-DECISIONS-TRACEABILITY.xlsx", f("08_CROSSWALK") / "CDF-GCO-CRMS-v7.12-DECISIONS-TRACEABILITY.xlsx")
    copy(BUILD / "protocol_summary.json", f("08_CROSSWALK") / "protocol_summary.json")
    # 09 evidence
    copy(ROOT / "EVIDENCE", f("09_EVIDENCE"))
    for n in ("state.json", "protocol_summary.json", "package_check.json", "decisions_summary.json"):
        copy(BUILD / n, f("09_EVIDENCE") / "build" / n)
    copy(BUILD / "verify", f("09_EVIDENCE") / "verify")
    copy(BUILD / "perf", f("09_EVIDENCE") / "perf")
    copy(ROOT / "sources" / "v7.12" / "INSTITUTIONAL-SOURCE-STATUS.json", f("09_EVIDENCE") / "INSTITUTIONAL-SOURCE-STATUS.json")
    (f("09_EVIDENCE") / "ENVIRONMENT.json").write_text(json.dumps(__import__("cdf_gco_crms.config.environment", fromlist=["describe"]).describe(),
                                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    # 10 release
    for n in ("PATCH-STATUS.json", "PATCH-STATUS.md", "RELEASE-GATE-MATRIX.xlsx"):
        copy(ROOT / n, f("10_RELEASE") / n)
    copy(OUT / "CDF-GCO-CRMS-v7.12-IMPLEMENTATION-GUIDE.md", f("10_RELEASE") / "CDF-GCO-CRMS-v7.12-IMPLEMENTATION-GUIDE.md")
    (f("10_RELEASE") / "LIMITATIONS-AND-DEPENDENCIES.md").write_text(limitations_text(), encoding="utf-8")
    ps = json.loads((ROOT / "PATCH-STATUS.json").read_text(encoding="utf-8")) if (ROOT / "PATCH-STATUS.json").exists() else {}
    note = release_note(ps, st)
    (f("10_RELEASE") / "RELEASE-NOTE.md").write_text(note, encoding="utf-8")
    (f("10_RELEASE") / "EXECUTIVE-REPORT.md").write_text(executive_report(ps, st), encoding="utf-8")
    (f("10_RELEASE") / "INSTALL.md").write_text(install_text(), encoding="utf-8")
    # hashes
    rows = []
    for p in sorted(RC.rglob("*")):
        if p.is_file() and not any(x in str(p) for x in EXCLUDE):
            rows.append(f"{sha(p)}  {p.relative_to(RC).as_posix()}")
    (RC / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"files": len(rows), "patch_counts": ps.get("counts"), "classification": ps.get("release_classification")}


def release_note(ps: dict, st: dict) -> str:
    counts = ps.get("counts", {})
    return "\n".join([
        "# RELEASE NOTE — CDF–GCO–CRMS v7.12 production release candidate", "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}.", "",
        f"**Engineering status:** {ps.get('engineering_status', 'UNKNOWN')}  ",
        f"**Release classification:** {ps.get('release_classification', 'PRODUCTION_CANDIDATE_NOT_OPERATIONALLY_APPROVED')}", "",
        "Patch register (60 patches): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ".", "",
        "Engineering completion is not institutional approval. The candidate becomes OPERATIONALLY_APPROVED only when, outside this "
        "engine, the following are supplied and verified: the Article 00.8 reference-case replay, the signed and current delegation of "
        "authority, the department approval of the organisational mandates, the GCO reviewer sign-offs of titles and observations, "
        "Microsoft Excel 365 and Word desktop checks of the delivered files, and the GCO signatures of 23.1. None of these exists in "
        "this package and no file here claims them.", "",
        f"Gates: {json.dumps(st.get('gate_summary'), ensure_ascii=False)}; tests: {json.dumps(st.get('test_summary'), ensure_ascii=False)}.", "",
        "Do not circulate any file of folders 03 or 06 outside CDF while a blocker of 10_RELEASE/RELEASE-GATE-MATRIX.xlsx stands.", ""])


def limitations_text() -> str:
    return "\n".join([
        "# LIMITATIONS, HUMAN AND SOURCE DEPENDENCIES — v7.12", "",
        "## Not verifiable in this environment (NOT_VERIFIED)", "",
        "- Microsoft Excel 365 desktop: repair alerts, Notes, selector recalculation, navigation, print. Verified here with LibreOffice 24.2 only.",
        "- Microsoft Word desktop: rendering of native reply threads and comment anchors. Verified here with LibreOffice only.",
        "- Live independent agents: the 19A challenge is a deterministic rule engine in one process (independence SINGLE_PROCESS_RULE_BASED, "
        "role isolation NOT_VERIFIED, stated in every record and in 23.1). The held-out set (17 synthetic cases) is a regression set that tuned "
        "the rules, not an independent measurement.",
        "- Fresh-machine rebuild: the package was rebuilt and the whole suite run from a clean virtual environment on the build machine; no second machine.", "",
        "## Institutional inputs not supplied (BLOCKED_EXTERNAL)", "",
        "- Article 00.8 reference-case package of 20 October 2026 (no replay possible).",
        "- Signed and current delegation-of-authority matrix (the 28-page copy is recorded UNVERIFIED).",
        "- Department approval of the organisational mandates (the 92-page deck is recorded PROPOSED_NOT_APPROVED).",
        "- GCO reviewer sign-offs of observation titles and of challenge dispositions on real observations (every title in the demonstration "
        "files is PROPOSED or shown with the tag ملخص آلي غير معتمد).",
        "- GCO signatures and legal review of 23.1.", "",
        "## Engineering limitations recorded in code", "",
        "- Word anchors are run-granular; a quote spanning two paragraphs is not located; headers, footers and footnotes are preserved but not searched.",
        "- Anchor movement is judged from the current range markers and the quote only (Word keeps no range history).",
        "- Matter detection in the challenge relies on matrix title-word overlap; OCR-garbled matrix titles may yield AUTHORITY_UNSUPPORTED rather than MISMATCH.",
        "- Notes and validation lists of a migrated workbook are regenerated by the engine, not byte-copied; the data cells are byte-compared (0 differences).", ""])


def executive_report(ps: dict, st: dict) -> str:
    counts = ps.get("counts", {})
    rows = ps.get("patches", [])
    by_stream: dict[str, dict[str, int]] = {}
    for r in rows:
        by_stream.setdefault(r["stream"], {}).setdefault(r["status"], 0)
        by_stream[r["stream"]][r["status"]] += 1
    lines = ["# EXECUTIVE REPORT — CDF–GCO–CRMS v7.12 production release candidate", "",
             f"Release classification: **{ps.get('release_classification')}**. Operational approval: {ps.get('operational_approval')}.", "",
             "| Status | Patches |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(counts.items())] + ["",
             "| Stream | " + " | ".join(sorted(counts)) + " |", "|---|" + "---|" * len(counts)]
    for stream, c in sorted(by_stream.items()):
        lines.append(f"| {stream} | " + " | ".join(str(c.get(k, 0)) for k in sorted(counts)) + " |")
    lines += ["", f"Tests: {json.dumps(st.get('test_summary'), ensure_ascii=False)}. Gates: {json.dumps(st.get('gate_summary'), ensure_ascii=False)}. "
              f"Recalculated views: {len(st.get('views', []))}.", "",
              "## Decisions the institution still owns", "",
              "- Supply the Article 00.8 reference-case package and rerun `python tools/patch_status.py` after the replay.",
              "- Supply the signed DoA and the approved mandates; the reference index then records them APPROVED_CURRENT and the challenge's "
              "authority objections change class.",
              "- Record reviewer decisions on titles (`python main.py finalize-titles`) and on challenge blockers (`python main.py adjudicate`) "
              "with name, date, decision reference and signature; a boolean is refused.",
              "- Open the delivered workbook and Word file in Excel 365 and Word desktop and record the result against G-DASH-13 / G-UX-15 / TEST 30.", ""]
    return "\n".join(lines)


def install_text() -> str:
    return "\n".join([
        "# INSTALL — CDF–GCO–CRMS v7.12", "",
        "```", "python3 --version            # 3.11 or later (built with 3.13.16)",
        "cd 02_ENGINE", "python3 -m venv .venv && . .venv/bin/activate",
        "python -m pip install -r requirements-lock.txt",
        "# optional, for independent recalculation and rendering: LibreOffice 24.x (soffice on PATH)",
        "python -m pytest tests -q                       # full regression (TEST 01–32)",
        "python main.py --help                          # workflow commands and return codes",
        "python tools/build_deliverables.py             # rebuilds every deliverable into deliverables/",
        "python tools/baseline_audit.py EVIDENCE && python tools/patch_status.py && python tools/build_rc.py",
        "```", "",
        "Verify the package: `sha256sum -c SHA256SUMS.txt` from the root of the extracted archive.", ""])


def zip_and_check() -> dict:
    DIST.mkdir(exist_ok=True)
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(RC.rglob("*")):
            if p.is_file() and not any(x in str(p) for x in EXCLUDE):
                z.write(p, f"CDF-GCO-CRMS-v7.12-RC/{p.relative_to(RC).as_posix()}")
    with zipfile.ZipFile(ZIP) as z:
        bad = z.testzip()
        names = z.namelist()
        folders = sorted({n.split("/")[1] for n in names if n.count("/") >= 2})
    return {"zip": str(ZIP), "sha256": sha(ZIP), "bytes": ZIP.stat().st_size, "members": len(names), "corrupt": bad, "folders": folders}


def checkpoint(summary: dict, zinfo: dict):
    ps = json.loads((ROOT / "PATCH-STATUS.json").read_text(encoding="utf-8")) if (ROOT / "PATCH-STATUS.json").exists() else {}
    not_pass = [p for p in ps.get("patches", []) if p["status"] != "PASS"]
    lines = ["# CHECKPOINT — CDF–GCO–CRMS v7.12 production execution", "",
             f"Last update {datetime.now(timezone.utc).isoformat(timespec='seconds')} (UTC).", "",
             "## State", "",
             f"- Patch register: {json.dumps(ps.get('counts'), ensure_ascii=False)} → PATCH-STATUS.json / PATCH-STATUS.md",
             f"- Engineering status: {ps.get('engineering_status')}; release classification: {ps.get('release_classification')}",
             f"- Package: {zinfo['zip']} ({zinfo['members']} members, {zinfo['bytes']} bytes, sha256 {zinfo['sha256']}, corrupt member: {zinfo['corrupt']})",
             f"- Folders: {', '.join(zinfo['folders'])}", "",
             "## Patches not PASS (why)", ""] + [f"- {p['id']} {p['status']}: {p['note'] or p['evidence'][:120]}" for p in not_pass] + ["",
             "## Resume from here", "",
             "1. `python -m pytest tests -q` — must stay green (TEST 01–32).",
             "2. `python tools/build_deliverables.py` — rebuilds demos, migration, verification, gates, tests, protocol, decisions.",
             "3. `python tools/baseline_audit.py EVIDENCE && python tools/patch_status.py && python tools/build_rc.py`.",
             "4. Institutional inputs still missing (BLOCKED_EXTERNAL): Article 00.8 reference-case package, signed DoA, department approval "
             "of mandates, GCO reviewer sign-offs; Excel 365 / Word desktop checks (NOT_VERIFIED). Supply them outside the engine; "
             "re-run step 3 so PATCH-STATUS reflects the evidence.", ""]
    (ROOT / "CHECKPOINT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    s = assemble()
    z = zip_and_check()
    checkpoint(s, z)
    print(json.dumps({**s, **z}, ensure_ascii=False, indent=1))
