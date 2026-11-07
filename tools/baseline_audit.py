#!/usr/bin/env python3
"""Immutable release baseline (patch V712-001): SHA-256 manifest of every authoritative input and of the
exploratory material kept apart from it, written to EVIDENCE/BASELINE-AUDIT.md and .json.

Authoritative inputs are the files the user supplied: the v7.11 package, the engineering batches 7–10,
the owner's round-4 register, the three institutional PDFs, the 87-page design guide and the execution kit.
The engine's own outputs are never part of the baseline.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT.parent / "uploads"
INPUTS = [
    ("v7.11 issued package (Claude Code engine, base of v7.12)", UP / "package.zip", "AUTHORITATIVE"),
    ("Engineering Batch 7 (ChatGPT, v7.12 adapter and protocol consolidation)", UP / "batch7.zip", "AUTHORITATIVE"),
    ("Engineering Batch 8 (ChatGPT)", UP / "batch8", "AUTHORITATIVE"),
    ("Engineering Batch 9 (ChatGPT, repaired 3-round demo)", UP / "batch9", "AUTHORITATIVE"),
    ("Engineering Batch 10 (ChatGPT) and its lineage audit", UP / "batch10", "AUTHORITATIVE"),
    ("Owner's issued register, round 4 (status fills of D.2, AMB-161)", UP / "register" / "register.xlsx", "AUTHORITATIVE"),
    ("Execution kit: 60-patch backlog and directive", UP / "kit", "AUTHORITATIVE"),
    ("CDF Design Guide, 87 pages", ROOT / "sources" / "CDF_Design_Guide.pdf", "AUTHORITATIVE"),
    ("Institutional reference PDFs (org structure, DoA matrix, brand applications)", ROOT / "sources" / "reference", "AUTHORITATIVE"),
    ("v7.11 consolidated protocol text (base of the v7.12 consolidation)", ROOT / "sources" / "CDF-GCO-CRMS-v7.11.txt", "AUTHORITATIVE"),
    ("Answered decisions workbook (100 decisions)", ROOT / "sources" / "v7.12" / "CDF-GCO-CRMS-v7.12-DECISIONS-ANSWERED-UNMODIFIED.xlsx", "AUTHORITATIVE"),
    ("ChatGPT v7.12 modules copied for validation (not on the production path)", ROOT / "sources" / "v7.12" / "chatgpt_cdf_v712", "EXPLORATORY"),
    ("Batch 11 read-only selector files", None, "NOT_SUPPLIED"),
]


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(path: Path) -> list[dict]:
    if path.is_file():
        return [{"file": str(path.relative_to(ROOT.parent)), "sha256": sha(path), "bytes": path.stat().st_size}]
    rows = []
    for p in sorted(path.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rows.append({"file": str(p.relative_to(ROOT.parent)), "sha256": sha(p), "bytes": p.stat().st_size})
    return rows


def main(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = {"schema": "CDF-v7.12-BASELINE-1", "date": str(date.today()), "authoritative_branch": "v7.12 (Claude Code engine, built on the v7.11 package)",
           "inputs": []}
    for label, path, cls in INPUTS:
        if path is None or not path.exists():
            rep["inputs"].append({"label": label, "class": cls if path is None else "MISSING", "files": []})
            continue
        files = manifest(path)
        rep["inputs"].append({"label": label, "class": cls, "path": str(path.relative_to(ROOT.parent)), "files": files,
                              "count": len(files), "bytes": sum(f["bytes"] for f in files)})
    (out_dir / "BASELINE-AUDIT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# BASELINE AUDIT — CDF–GCO–CRMS v7.12 (patch V712-001)", "",
             f"Date: {rep['date']}. Authoritative branch: {rep['authoritative_branch']}.", "",
             "Every input the engine was built from, hashed as received. AUTHORITATIVE inputs are the user's files; EXPLORATORY "
             "material is kept apart and is not on the production path; NOT_SUPPLIED inputs were named by the backlog but never "
             "received, so nothing derived from them exists.", "",
             "| Input | Class | Files | Bytes | SHA-256 (single file) or first file |", "|---|---|---|---|---|"]
    for i in rep["inputs"]:
        first = i["files"][0]["sha256"] if i["files"] else "—"
        lines.append(f"| {i['label']} | {i['class']} | {i.get('count', 0)} | {i.get('bytes', 0)} | `{first}` |")
    lines += ["", "## Full manifest", ""]
    for i in rep["inputs"]:
        if not i["files"]:
            continue
        lines.append(f"### {i['label']} ({i['class']})")
        lines.append("")
        for f in i["files"]:
            lines.append(f"- `{f['sha256']}`  {f['file']}  ({f['bytes']} B)")
        lines.append("")
    lines += ["## Overrides and diffs tracked", "",
              "- AMB-161 (owner decision, 23 Oct 2026): status fills on the dashboard equal the register's D.2 fills; overrides decisions 13–16 of the decisions workbook (recorded in D.15).",
              "- The v7.11 Word files of Batch 10 lack follow-ups for reopened rows (R4: #12, #20, #29; R5: #28) and reply threads; v7.12 adds them (G-SYNC-9).",
              "- The ChatGPT Batch 7–10 modules were validated against this engine (tools/lineage_audit.py) and ported where sound; no ChatGPT adapter runs on the production path.",
              ""]
    (out_dir / "BASELINE-AUDIT.md").write_text("\n".join(lines), encoding="utf-8")
    return rep


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "EVIDENCE"
    r = main(out)
    print(json.dumps({i["label"]: (i["class"], i.get("count", 0)) for i in r["inputs"]}, ensure_ascii=False, indent=1))
