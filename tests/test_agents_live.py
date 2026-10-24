"""TEST 37 — layer C: live inference tests. They run only when a LIVE provider is configured
(``CDF_AI_PROVIDER=anthropic`` and a credential the SDK can resolve); otherwise every test is SKIPPED with the
reason printed, so that a run without a provider is never counted as a live pass.

Only synthetic, unseen cases are sent; the data-handling guard refuses anything else. Every live call is
recorded in a trace (hashes, ids, token usage, latency) under build/evidence/live/.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdf_gco_crms.agents import AgentRunner, TraceWriter  # noqa: E402
from cdf_gco_crms.agents import contracts as C  # noqa: E402
from cdf_gco_crms.agents import evaluator as E  # noqa: E402
from cdf_gco_crms.agents.orchestrator import INDEPENDENCE_LIVE, ReviewOrchestrator  # noqa: E402
from cdf_gco_crms.agents.providers import provider_from_env  # noqa: E402
from cdf_gco_crms.model.entities import Document  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import build_round1  # noqa: E402
from conftest import base_obs  # noqa: E402
from test_word_lifecycle import build_reviewed_doc  # noqa: E402

EVIDENCE = ROOT / "build" / "evidence" / "live"
DEPT = "الحوكمة والامتثال"


def _live_runner(name: str) -> AgentRunner:
    provider = provider_from_env()
    if provider is None or provider.mode != C.MODE_LIVE:
        pytest.skip("no LIVE provider configured (set CDF_AI_PROVIDER=anthropic and a credential); live tests are not run")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    runner = AgentRunner(provider, TraceWriter(EVIDENCE / f"{name}.jsonl"))
    probe = runner.run(C.ROLE_BLACK, "Return the schema-valid JSON for: no material objection.",
                       {"label": "SYNTHETIC_TEST_CASE", "observation": {"comment": "probe"}}, max_tokens=512)
    if probe.status == C.STATUS_PROVIDER_FAILURE and "AUTHENTICATION" in (probe.error or ""):
        pytest.skip(f"LIVE provider configured but no credential resolved: {probe.error}")
    return runner


pytestmark = pytest.mark.live


def test_live_black_team_returns_schema_valid_json_with_real_invocation_ids():
    runner = _live_runner("black-team")
    st = build_round1(Document(name="حالة حية افتراضية", code="LIV", owning_department=DEPT, is_demo=True), base_obs(2),
                      date="2026-02-15", document_version="الإصدار 0.1")
    from cdf_gco_crms.agents import context_builder as CB
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    from cdf_gco_crms.assurance.personas import RecipientPersona
    idx = synthetic_reference_index()
    reg = EvidenceRegistry(); reg.add_document_text("\n".join(E._DOC), "live.txt"); reg.add_reference_index(idx)
    persona = RecipientPersona.from_index(idx, DEPT, reg)
    resp = runner.run(C.ROLE_BLACK, CB.SYSTEM[C.ROLE_BLACK], CB.black_team_payload(st, st.ordered()[0], reg, persona, issued=False))
    assert resp.mode == C.MODE_LIVE and resp.status in (C.STATUS_OK, C.STATUS_REFUSED, C.STATUS_SCHEMA_INVALID)
    assert resp.invocation_id and resp.execution_id and resp.token_usage.input_tokens > 0
    assert resp.status == C.STATUS_OK, resp.schema_errors or resp.error


def test_live_pipeline_runs_separate_contexts_and_records_trace(tmp_path):
    runner = _live_runner("pipeline")
    st = build_round1(Document(name="حالة حية افتراضية", code="LIV", owning_department=DEPT, is_demo=True), base_obs(3),
                      date="2026-02-15", document_version="الإصدار 0.1")
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    ex = ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=tmp_path / "gate").execute(st, full)
    live_roles = [o for o in ex.role_outcomes if o["mode"] == C.MODE_LIVE]
    assert live_roles and len({o["execution_id"] for o in live_roles}) == len(live_roles)
    assert ex.trace_summary["actual_live_inference_count"] >= len(st.observations)
    assert ex.record.independence in (INDEPENDENCE_LIVE, "MIXED_LIVE_AND_RULES")
    (EVIDENCE / "pipeline-execution.json").write_text(json.dumps(ex.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    auth = G.authorize(st, tmp_path / "gate")
    assert auth.ok == (ex.status == "CLEAR" and ex.final_review["recommendation"] == "READY")


def test_live_blind_holdout_scores_and_threshold():
    runner = _live_runner("holdout")
    rep = E.evaluate(runner, out_path=EVIDENCE / "holdout-live.json")
    s = rep["score"]
    assert s["mode"] == C.MODE_LIVE and s["cases"] == 24
    assert s["hallucinated_refs"] == 0, "a live agent cited an evidence id that does not exist"
    assert s["provider_failures"] == 0
    assert s["adjudicator_accuracy"] is not None and s["adjudicator_accuracy"] >= E.LIVE_ADJUDICATOR_THRESHOLD, s
