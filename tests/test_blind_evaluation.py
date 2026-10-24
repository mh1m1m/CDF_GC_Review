"""TEST 38 — layer D: blind evaluation on the sealed public holdout.

Checks the seal and the isolation of the holdout (inputs carry no labels), scores the DETERMINISTIC engine as a
baseline (reported, never a pass), and proves with a scripted provider that the scorer separates modes, counts
hallucinated references and never grants the live threshold to a non-live run.
The LIVE score is produced by tests/test_agents_live.py when a provider is configured.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cdf_gco_crms.agents import AgentRunner, MockAdapter, TraceWriter  # noqa: E402
from cdf_gco_crms.agents import contracts as C  # noqa: E402
from cdf_gco_crms.agents import evaluator as E  # noqa: E402
from cdf_gco_crms.agents.security import ContextIsolationViolation  # noqa: E402


def test_holdout_is_sealed_isolated_and_reproducible(tmp_path):
    cases, expected = E.load_holdout()
    assert len(cases) == 24 and set(expected) == {c["case_id"] for c in cases}
    assert all(c["label"] == "SYNTHETIC_TEST_CASE" for c in cases)
    assert all("expected" not in json.dumps(c, ensure_ascii=False).lower() for c in cases)
    fams = {v["family"] for v in expected.values()}
    assert len(fams) == 8 and "CLEAN" in fams
    # regenerating with the same seed reproduces the sealed answers byte for byte
    info = E.write_holdout(tmp_path, n=24, seed=7)
    assert info["seal"] == (E.DEFAULT_HOLDOUT_DIR / "expected.sha256").read_text(encoding="utf-8").strip()
    # a tampered answer file is refused
    (tmp_path / "expected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        E.load_holdout(tmp_path)
    # the runner refuses a payload that carries an expected answer
    with pytest.raises(ContextIsolationViolation):
        AgentRunner(MockAdapter(), TraceWriter()).run(C.ROLE_BLACK, "s", {"label": "SYNTHETIC_TEST_CASE", "expected": "x"})


def test_deterministic_baseline_is_reported_not_passed(tmp_path):
    rep = E.evaluate(None, out_path=tmp_path / "det.json")
    s = rep["score"]
    assert s["mode"] == C.MODE_DETERMINISTIC and s["cases"] == 24 and s["provider_failures"] == 0
    assert s["false_objection_rate"] == 0.0 and s["objection_detection_exact"] >= 0.75
    assert s["classification"] == "DETERMINISTIC_BASELINE_NOT_A_PASS" and s["live_threshold_met"] is False
    assert s["baseline"]["deterministic_adjudicator_accuracy"] == 0.656, "the forensic baseline is carried for comparison"
    assert (tmp_path / "det.json").is_file()


def test_scripted_provider_scores_separately_and_counts_hallucinations():
    cases, expected = E.load_holdout()
    def black(p):
        return {"material_objection": True, "objection_kind": "UNCLEAR_ACTION", "challenged_claim": "x",
                "proposition": "التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ.", "material_consequence": "c",
                "evidence_refs": ["EV-000000000000"], "existing_controls": [], "requested_correction": "r",
                "reasoning_summary": "s", "evidence_limitations": "", "confidence": 0.5}
    script = {C.ROLE_BLACK: black,
              C.ROLE_RED: {"stance": "CONCEDE", "objection_accepted": True, "reasoning": "r", "evidence_refs": [], "revised_comment": None,
                           "revised_quote": None, "route_to": None, "missing_evidence": [], "escalate": False, "new_argument": True},
              C.ROLE_ADJUDICATOR: {"disposition": "WITHHELD_FOR_EVIDENCE", "objection_valid": True, "rationale": "r", "decisive_evidence": [],
                                   "inadmissible_refs": [], "facts": [], "inferences": [], "unverified_assumptions": [], "remedy_assessment": "",
                                   "open_question": None, "escalate": False}}
    rep = E.evaluate(AgentRunner(MockAdapter(script=script), TraceWriter()))
    s = rep["score"]
    assert s["mode"] == C.MODE_MOCK and s["classification"] == "MOCK_BASELINE_NOT_A_PASS" and s["live_threshold_met"] is False
    assert s["false_objection_rate"] == 1.0 and s["hallucinated_refs"] == 24
    assert s["adjudicator_accuracy"] < E.LIVE_ADJUDICATOR_THRESHOLD
    assert rep["trace"]["actual_live_inference_count"] == 0 and rep["trace"]["mock_inference_count"] > 0
