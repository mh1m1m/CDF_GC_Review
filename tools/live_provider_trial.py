#!/usr/bin/env python3
"""Public-safe live-provider validation procedure (PR #3 review, Directive 6).

Runs in three stages and stops at the first one that is blocked, reporting the exact reason and the next
configuration action. Nothing institutional is sent: every payload is the public synthetic holdout or the
synthetic regression fixtures, labelled SYNTHETIC_TEST_CASE. Credentials are never read or printed by this
script; the SDK resolves them from the environment.

  stage 1  configuration   CDF_AI_PROVIDER, model id, SDK import and version, SDK request surface
  stage 2  connectivity    one minimal live call (a schema-valid "no material objection") → receipt
  stage 3  evaluation      sealed holdout (24 cases) + one orchestrated pipeline on an unseen synthetic document,
                           with traces under build/evidence/live/

Usage:  python tools/live_provider_trial.py [--out build/evidence/live] [--skip-evaluation]
Exit:   0 all stages ran · 4 blocked (reason printed) · 1 a stage ran and failed
Costs:  stage 2 is one small request; stage 3 is roughly 24 × 3 + 10 requests. Both are paid external inference
        and run only when the operator has configured the provider deliberately.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cdf_gco_crms.agents import context_builder as CB  # noqa: E402
from cdf_gco_crms.agents import contracts as C  # noqa: E402
from cdf_gco_crms.agents.providers.base import ENV_DATA_AUTH, ENV_MODEL, ENV_PROVIDER, ProviderConfig, provider_from_env  # noqa: E402
from cdf_gco_crms.agents.runner import AgentRunner  # noqa: E402
from cdf_gco_crms.agents.tracing import TraceWriter  # noqa: E402

RC_OK, RC_FAIL, RC_BLOCKED = 0, 1, 4
SUPPORTED_MODEL_PREFIXES = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-sonnet-5", "claude-fable-5-1",
                            "claude-fable-5", "claude-haiku-5-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
                            "claude-sonnet-4-6", "claude-haiku-4-5")


def stage_configuration(report: dict) -> bool:
    cfg = ProviderConfig.from_env()
    st = {"provider": cfg.provider or "(unset)", "model": cfg.model, "data_authorization": cfg.data_authorization,
          "credential_env_present": any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))}
    report["configuration"] = st
    if cfg.provider != "anthropic":
        report["blocked"] = {"stage": "configuration", "reason": f"{ENV_PROVIDER} is {st['provider']!r}; the live trial needs 'anthropic'",
                             "next_action": f"export {ENV_PROVIDER}=anthropic and a credential the SDK resolves (ANTHROPIC_API_KEY or "
                                            f"ANTHROPIC_AUTH_TOKEN or `ant auth login`); optionally {ENV_MODEL}=claude-opus-5-5"}
        return False
    try:
        import anthropic
    except ImportError:
        report["blocked"] = {"stage": "configuration", "reason": "anthropic SDK not installed",
                             "next_action": "python -m pip install -r requirements-lock.txt"}
        return False
    st["sdk_version"] = anthropic.__version__
    params = inspect.signature(anthropic.Anthropic().messages.create.__wrapped__
                               if hasattr(anthropic.Anthropic().messages.create, "__wrapped__")
                               else anthropic.Anthropic().messages.create).parameters \
        if st["credential_env_present"] else {}
    st["sdk_supports_output_config"] = ("output_config" in params) if params else "not checked (no credential to build a client)"
    if not cfg.model.startswith(SUPPORTED_MODEL_PREFIXES):
        report["blocked"] = {"stage": "configuration", "reason": f"model id {cfg.model!r} is not a known Claude model id",
                             "next_action": f"set {ENV_MODEL} to a current model id, e.g. claude-opus-5-5"}
        return False
    if not st["credential_env_present"]:
        st["note"] = "no credential in the environment variables; the SDK may still resolve a CLI profile — stage 2 will tell"
    return True


def stage_connectivity(report: dict, out: Path) -> AgentRunner | None:
    provider = provider_from_env()
    runner = AgentRunner(provider, TraceWriter(out / "trial-trace.jsonl"))
    resp = runner.run(C.ROLE_BLACK, CB.SYSTEM[C.ROLE_BLACK] + " For this probe there is no material objection.",
                      {"label": "SYNTHETIC_TEST_CASE", "observation": {"comment": "probe"}, "evidence": []}, max_tokens=512)
    rec = resp.to_record()
    report["connectivity"] = {k: rec[k] for k in ("Execution_ID", "Context_ID", "Provider", "Model", "Mode", "Invocation_ID",
                                                  "Execution_Status", "Token_Usage", "Latency_ms", "Error")}
    if resp.status != C.STATUS_OK:
        kind = (resp.error or "").split(":")[0]
        nxt = {"AUTHENTICATION": "provide a credential (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login`)",
               "PERMISSION": "the credential lacks access to the model; use a key with Messages API access",
               "NOT_FOUND": f"the model id {report['configuration']['model']!r} is not served to this account; set {ENV_MODEL}",
               "RATE_LIMIT": "retry later or lower concurrency", "CONNECTION": "check outbound network / ANTHROPIC_BASE_URL / proxy CA",
               "TIMEOUT": "raise CDF_AI_TIMEOUT_SECONDS"}.get(kind, "inspect the error; the SDK response is recorded in the trace")
        report["blocked"] = {"stage": "connectivity", "reason": resp.error, "next_action": nxt}
        return None
    if resp.invocation_id and not resp.invocation_id.startswith("msg_"):
        report["connectivity"]["warning"] = "invocation id is not provider-shaped; receipts may not verify"
    return runner


def stage_evaluation(report: dict, runner: AgentRunner, out: Path) -> bool:
    import tempfile
    from cdf_gco_crms.agents import evaluator as E
    from cdf_gco_crms.agents.orchestrator import ReviewOrchestrator
    from cdf_gco_crms.references.synthetic_index import synthetic_reference_index
    rep = E.evaluate(runner, out_path=out / "holdout-live.json")
    report["holdout"] = rep["score"]
    sys.path.insert(0, str(ROOT / "tests"))
    from test_e2e_agents import _unseen_state
    from test_word_lifecycle import build_reviewed_doc
    st = _unseen_state()
    tmp = Path(tempfile.mkdtemp())
    docx = build_reviewed_doc(st, tmp / "case.docx")
    ex = ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=out / "gate").execute(st, docx, command="live-trial")
    (out / "pipeline-execution.json").write_text(json.dumps(ex.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    report["pipeline"] = {"status": ex.status, "independence": ex.record.independence, "independence_verified": ex.independence.get("verified"),
                          "independence_reasons": ex.independence.get("reasons"), "final_review": ex.final_review,
                          "provider_failures": ex.provider_failures, "trace": ex.trace_summary}
    ok = rep["score"]["provider_failures"] == 0 and ex.provider_failures == 0
    report["live_threshold_met"] = rep["score"]["live_threshold_met"]
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="build/evidence/live")
    ap.add_argument("--skip-evaluation", action="store_true", help="stop after the connectivity probe (one request)")
    a = ap.parse_args(argv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    report: dict = {"schema": "CDF-LIVE-PROVIDER-TRIAL-v7.12.1", "data": "SYNTHETIC_ONLY",
                    "note": "credentials are never read or printed by this script; the SDK resolves them from the environment"}
    rc = RC_OK
    try:
        if not stage_configuration(report):
            rc = RC_BLOCKED
        else:
            runner = stage_connectivity(report, out)
            if runner is None:
                rc = RC_BLOCKED
            elif not a.skip_evaluation and not stage_evaluation(report, runner, out):
                rc = RC_FAIL
    finally:
        (out / "live-provider-trial.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return rc


if __name__ == "__main__":
    sys.exit(main())
