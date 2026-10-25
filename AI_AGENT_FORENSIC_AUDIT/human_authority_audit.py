#!/usr/bin/env python3
"""PHASE 11 — human authorization and governance controls: bypass attempts in a synthetic environment (read-only on the product)."""
from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

from agent_contracts import HERE, engine_run, load_cases

RESULTS = []


def attempt(name, fn, must_reject=True):
    try:
        r = fn()
        rejected = bool(r.get("rejected")) and not r.get("applied") if isinstance(r, dict) else False
        RESULTS.append({"attempt": name, "raised": None, "result": r if isinstance(r, (dict, str, bool, int)) else str(r)[:300],
                        "rejected": rejected, "PASS": rejected == must_reject})
    except Exception as e:  # noqa: BLE001
        RESULTS.append({"attempt": name, "raised": f"{type(e).__name__}: {e}"[:200], "rejected": True, "PASS": must_reject})


def main():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cdf_gco_crms.assurance import challenge as CH
    from cdf_gco_crms.assurance.objection_engine import HumanDecision
    from cdf_gco_crms.config import round_schema as S
    from cdf_gco_crms.model.entities import GText, Observation, RoundCells, TitleEvidence
    from cdf_gco_crms.references.index import ReferenceIndex
    from cdf_gco_crms.rounds.round_expansion import TitleDecision, finalize_titles
    idx = ReferenceIndex.load()
    cases = {c["case_id"]: c for c in load_cases()}
    rec, entry, reg, persona = engine_run(cases["HIST-01"], idx)           # issued observation with a reserved blocker
    victim = entry.internal_id
    assert rec.blockers(), "fixture must start with a blocker"
    priv = Ed25519PrivateKey.generate()                                     # SYNTHETIC test key, labelled as such
    trust = {"SYNTHETIC_TEST_KEY": priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)}
    base = HumanDecision("D-AUD-1", victim, "ESCALATED_TO_GCO_REVIEWER", "م. مراجع تجريبي", "GCO reviewer", "DEC-AUD-1", "2026-10-23", "E-AUD-1",
                         "VERIFIED_HUMAN_RECORD", "SYNTHETIC_TEST_KEY", "")
    signed = replace(base, signature_b64=base64.b64encode(priv.sign(base.signature_payload())).decode())
    attempt("human_decision=True (boolean)", lambda: CH.apply_human_decisions(rec, [True], trust, registry=reg))
    attempt("dict pretending to be a decision", lambda: CH.apply_human_decisions(rec, [{"approved": True, "reviewer": "x"}], trust, registry=reg))
    attempt("fabricated reviewer name, unsigned", lambda: CH.apply_human_decisions(rec, [base], trust, registry=reg))
    attempt("invalid signature", lambda: CH.apply_human_decisions(rec, [replace(signed, signature_b64=base64.b64encode(b"\x00" * 64).decode())], trust, registry=reg))
    attempt("valid signature but key id absent from trust store", lambda: CH.apply_human_decisions(rec, [signed], {}, registry=reg))
    attempt("reuse of a valid approval for another observation", lambda: CH.apply_human_decisions(rec, [replace(signed, observation_id="GCO-AUD-R1-009")], trust, registry=reg))
    attempt("record modified after signing (decision field changed)", lambda: CH.apply_human_decisions(rec, [replace(signed, decision="UPHELD_UNCHANGED")], trust, registry=reg))
    attempt("verification_status NOT_VERIFIED with a valid signature", lambda: CH.apply_human_decisions(rec, [replace(signed, verification_status="NOT_VERIFIED")], trust, registry=reg))
    # expiry / revocation: no field or mechanism exists → the engine cannot reject; recorded as a control gap, not as a pass
    attempt("expired or revoked authorization (timestamp 2020-01-01, otherwise valid)", lambda: (lambda d: CH.apply_human_decisions(rec, [replace(d, signature_b64=base64.b64encode(priv.sign(d.signature_payload())).decode())], trust, registry=reg))(replace(base, timestamp="2020-01-01")), must_reject=True)
    # title approval without authorization
    def forged_title():
        return Observation("GCO-AUD-R1-001", "01", 1, "ص.1", "نص", "تعليق", cells={1: RoundCells(closure=S.OPEN)}, title="عنوان", title_status=S.TITLE_APPROVED)
    attempt("Observation constructed with title_status=APPROVED and no evidence", forged_title)
    st, target = __import__("agent_contracts").engine_state(cases["NOOBJ-01"])
    attempt("finalize_titles APPROVE with empty reviewer/date/ref", lambda: {"rejected": finalize_titles(st, [TitleDecision(target.internal_id, "APPROVE", "", "", "", title="x")])[1].refused, "applied": []})
    attempt("finalize_titles APPROVE with non-ISO date", lambda: {"rejected": finalize_titles(st, [TitleDecision(target.internal_id, "APPROVE", "م", "23/10/2026", "R", title="x")])[1].refused, "applied": []})
    # reversal of an issued GCO observation by the engine alone
    ob = rec.objection(entry.objections[0].challenge_id)
    attempt("engine decides WITHDRAWAL-type outcome on an issued observation without a human record", lambda: ob.decide("ROUTED_OUTSIDE_GCO", verifications=reg.verifications()))
    # the legitimate path, for contrast (must be applied) — on a FRESH record, because the stale-timestamp attempt above was accepted
    # by the engine and consumed the blocker (that acceptance is the control gap, not the control)
    rec_fresh, entry_fresh, reg_fresh, _ = engine_run(cases["HIST-01"], idx)
    attempt("CONTROL: valid signed record in trust store (expected to be applied)", lambda: CH.apply_human_decisions(rec_fresh, [signed], trust, registry=reg_fresh), must_reject=False)
    gaps = ["No expiry, revocation list or validity window exists for a HumanDecision: a stale but validly signed record is accepted (attempt 9).",
            "The trust store is a caller-supplied dict of raw Ed25519 public keys; no institution-managed key store, key ceremony or CA is connected. "
            "INSTITUTIONAL_HUMAN_AUTHORIZATION = NOT_VERIFIED.",
            "Signing keys used in every test and demo are ephemeral SYNTHETIC keys generated in-process; no CDF key material exists in the package."]
    out = {"schema": "CDF-AUDIT-HUMAN-AUTHORITY-1", "attempts": RESULTS, "passed": sum(r["PASS"] for r in RESULTS), "total": len(RESULTS),
           "institutional_human_authorization": "NOT_VERIFIED", "control_gaps": gaps}
    (HERE / "evidence" / "human_authority_audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for r in RESULTS:
        print(("PASS" if r["PASS"] else "FAIL"), "|", r["attempt"], "|", (r["raised"] or str(r["result"])[:110]))
    print(f"{out['passed']}/{out['total']} controls behaved as required; gaps: {len(gaps)}")


if __name__ == "__main__":
    main()
