#!/usr/bin/env python3
"""PHASE 03 — actual runtime tracing of the production entry points (read-only on the product).

Runs main.py commands in-process on a SYNTHETIC case with (a) a profile hook that records every call between
functions of the engine package and (b) a socket guard that records and refuses any outbound connection.
Evidence: evidence/runtime_callgraphs/<command>.json and reports/ACTUAL-PRODUCTION-CALL-GRAPH.md,
reports/AGENT-RUNTIME-DEPENDENCY-GRAPH.json.
"""
from __future__ import annotations

import io
import json
import socket
import sys
import time
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))
WORK = HERE / "evidence" / "runtime_callgraphs"
WORK.mkdir(parents=True, exist_ok=True)
KEY = ("black_team", "red_advocate", "adjudicate", "run_challenge", "_argue", "apply_human_decisions", "confidentiality_scan",
       "build_workbook", "comment_document", "build_review_docx", "finalize_titles", "mark_titles_issued", "apply_round", "build_round1",
       "parse_workbook", "require_safe", "merge_returned", "bind_clause", "from_index", "decide", "validate", "evaluate_held_out")


class SocketGuard:
    """Refuses every outbound connection and records the attempt (proves no provider call happened)."""
    attempts: list = []

    def __enter__(self):
        self._connect, self._cc = socket.socket.connect, socket.create_connection

        def deny(*a, **k):
            SocketGuard.attempts.append({"when": time.time(), "args": [str(x)[:80] for x in a[1:]]})
            raise OSError("AUDIT SOCKET GUARD: outbound connection refused")
        socket.socket.connect = deny
        socket.create_connection = lambda *a, **k: deny(None, *a)
        return self

    def __exit__(self, *exc):
        socket.socket.connect, socket.create_connection = self._connect, self._cc


def trace(argv: list[str], label: str) -> dict:
    import main as M
    edges: Counter = Counter()
    order: list[tuple[float, str]] = []
    seen_first: set = set()
    root = str(ENGINE)

    def qual(frame):
        f = frame.f_code.co_filename
        if not f.startswith(root) or "/tests/" in f or "/AI_AGENT_FORENSIC_AUDIT/" in f:
            return None
        mod = f[len(root) + 1:].replace("/", ".").removesuffix(".py")
        return f"{mod}:{frame.f_code.co_name}"

    def prof(frame, event, arg):
        if event != "call":
            return
        callee = qual(frame)
        if not callee:
            return
        caller = qual(frame.f_back) if frame.f_back else None
        edges[(caller or "<external>", callee)] += 1
        name = frame.f_code.co_name
        if name in KEY and callee not in seen_first:
            seen_first.add(callee)
            order.append((time.time(), callee))
    out = io.StringIO()
    SocketGuard.attempts = []
    t0 = time.time()
    rc, err = None, None
    with SocketGuard():
        sys.setprofile(prof)
        try:
            with redirect_stdout(out):
                rc = M.main(argv)
        except SystemExit as e:
            rc = e.code
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        finally:
            sys.setprofile(None)
    rec = {"label": label, "argv": [a if not a.startswith("/") else Path(a).name for a in argv], "return_code": rc if isinstance(rc, (int, str, type(None))) else type(rc).__name__, "error": err,
           "seconds": round(time.time() - t0, 2), "socket_attempts": SocketGuard.attempts,
           "key_call_order": [c for _, c in order], "edge_count": sum(edges.values()),
           "edges": [{"caller": a, "callee": b, "n": n} for (a, b), n in sorted(edges.items(), key=lambda x: -x[1])][:400],
           "touches_challenge_engine": any("assurance.challenge" in b for (_, b) in edges),
           "touches_objection_engine": any("assurance.objection_engine" in b for (_, b) in edges),
           "touches_excel_builder": any(b.endswith("excel.workbook_builder:build_workbook") for (_, b) in edges),
           "touches_word_builder": any(b.endswith(("document_comments:comment_document", "word_sync:build_review_docx")) for (_, b) in edges),
           "stdout_tail": out.getvalue()[-600:]}
    (WORK / f"{label}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def synthetic_inputs(tmp: Path):
    """Round-1 JSON and a Word document from the sealed synthetic case DA-01 (no expected labels are read)."""
    from docx import Document as Docx
    c = json.loads((HERE / "cases" / "synthetic_inputs" / "DA-01.json").read_text(encoding="utf-8"))
    spec = {"document": {"name": "مذكرة تفاهم تجريبية للتدقيق", "code": "AUD", "owning_department": c["department"], "is_demo": True},
            "date": "2026-10-23", "observations": [{"location": c["observation"]["location"], "quote": c["observation"]["quote"],
                                                    "comment": c["observation"]["comment"], "title": "عنوان مقترح للتدقيق"}]}
    (tmp / "round1.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    d = Docx()
    for p in c["document_paragraphs"]:
        d.add_paragraph(p)
    d.save(tmp / "case.docx")
    return tmp / "round1.json", tmp / "case.docx"


def main():
    tmp = WORK / "work"
    tmp.mkdir(exist_ok=True)
    for old in tmp.glob("*"):
        if old.is_file():
            old.unlink()
    spec, docx = synthetic_inputs(tmp)
    recs = []
    recs.append(trace(["round1", str(spec), str(tmp)], "01_round1"))
    wb = next(tmp.glob("*.xlsx"))
    recs.append(trace(["build-excel", str(wb), str(tmp / "out_excel")], "02_build-excel"))
    recs.append(trace(["build-word", str(wb), str(tmp / "out.docx"), "--source", str(docx)], "03_build-word"))
    recs.append(trace(["review", str(wb), "--docx", str(docx), "--record", str(tmp / "review.json")], "04_review"))
    recs.append(trace(["challenge", str(wb), "--docx", str(docx), "--record", str(tmp / "challenge.json")], "05_challenge"))
    (tmp / "dec.json").write_text(json.dumps([{"decision_id": "D1", "observation_id": "GCO-AUD-R1-001", "decision": "UPHELD_UNCHANGED",
                                               "reviewer": "x", "role": "r", "reference": "ref", "timestamp": "2026-10-23", "evidence_ref": "e",
                                               "verification_status": "VERIFIED_HUMAN_RECORD", "signing_key_id": "K", "signature_b64": "AA=="}]), encoding="utf-8")
    recs.append(trace(["adjudicate", str(wb), str(tmp / "dec.json"), "--docx", str(docx), "--record", str(tmp / "adj.json")], "06_adjudicate"))
    (tmp / "titles.json").write_text(json.dumps({"decisions": [{"internal_id": "GCO-AUD-R1-001", "decision": "APPROVE", "reviewer": "م. مراجع تجريبي",
                                                                "date": "2026-10-23", "decision_ref": "AUD-DEC-1"}]}, ensure_ascii=False), encoding="utf-8")
    recs.append(trace(["finalize-titles", str(wb), str(tmp / "titles.json"), str(tmp / "out_titles"), "--issue"], "07_finalize-titles"))
    # the round-1 JSON carried a proposed title, but cmd_round1 does not pass it to NewObservation (audit finding F-07); the decision
    # therefore has to carry the wording itself for the command path to be exercised
    (tmp / "titles2.json").write_text(json.dumps({"decisions": [{"internal_id": "GCO-AUD-R1-001", "decision": "APPROVE", "title": "عنوان معتمد للتدقيق",
                                                                 "reviewer": "م. مراجع تجريبي", "date": "2026-10-23", "decision_ref": "AUD-DEC-1"}]}, ensure_ascii=False), encoding="utf-8")
    recs.append(trace(["finalize-titles", str(wb), str(tmp / "titles2.json"), str(tmp / "out_titles"), "--issue"], "08_finalize-titles-with-wording"))
    # summary
    summary = {"schema": "CDF-AUDIT-RUNTIME-DEPENDENCY-GRAPH-1", "entry_point": "main.py main(argv)", "commands": []}
    for r in recs:
        summary["commands"].append({k: r[k] for k in ("label", "return_code", "error", "seconds", "socket_attempts", "key_call_order",
                                                       "touches_challenge_engine", "touches_objection_engine", "touches_excel_builder", "touches_word_builder")})
    summary["findings"] = [
        "round1 does not carry the 'title' field of its JSON into NewObservation (07_finalize-titles refused: 'nothing to approve'); the proposal "
        "must be supplied again in the decision file (08).",
        "Every production build command (round1, build-excel, build-word, finalize-titles) completes WITHOUT any call into assurance.challenge: "
        "the challenge is not on the issuance path; it runs only when the operator invokes review/challenge/adjudicate separately.",
        "No command attempted an outbound socket connection: there is no provider call anywhere in the traced runtime.",
        "review/challenge/adjudicate call black_team → red_advocate → adjudicate inside one process on shared objects (no separate execution identity).",
    ]
    (HERE / "reports" / "AGENT-RUNTIME-DEPENDENCY-GRAPH.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# ACTUAL PRODUCTION CALL GRAPH — CDF–GCO–CRMS v7.12 (execution evidence, not an import graph)", "",
             "Traced in-process with `sys.setprofile` on the engine package while running `main.py` commands on the synthetic case DA-01; "
             "a socket guard refused and recorded any outbound connection. Raw edge lists: `evidence/runtime_callgraphs/*.json`.", "",
             "| Command | rc | Calls into assurance.challenge | Excel builder | Word builder | Socket attempts | First key calls (order) |", "|---|---|---|---|---|---|---|"]
    for r in recs:
        lines.append(f"| {r['label']} | {r['return_code']} | {'YES' if r['touches_challenge_engine'] else 'no'} | {'YES' if r['touches_excel_builder'] else 'no'} | "
                     f"{'YES' if r['touches_word_builder'] else 'no'} | {len(r['socket_attempts'])} | {' → '.join(c.split(':')[-1] for c in r['key_call_order'][:9])} |")
    lines += ["", "## Observations", ""] + [f"- {f}" for f in summary["findings"]] + ["", "## Caller → callee edges of the review command (top 40 by frequency)", ""]
    rev = next(r for r in recs if r["label"] == "04_review")
    for e in rev["edges"][:40]:
        lines.append(f"- `{e['caller']}` → `{e['callee']}` ×{e['n']}")
    (HERE / "reports" / "ACTUAL-PRODUCTION-CALL-GRAPH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary["commands"], ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
