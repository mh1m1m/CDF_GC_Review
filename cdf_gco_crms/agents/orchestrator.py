"""Mandatory review orchestration (Article 06).

  DOCUMENT INGESTION → EVIDENCE VERIFICATION → [GCO DRAFTING AGENT] → BLACK TEAM → RED ADVOCATE →
  INDEPENDENT ADJUDICATOR → GCO EDITORIAL AGENT → HUMAN AUTHORIZATION → INDEPENDENT FINAL REVIEWER →
  CENTRAL RELEASE GATE (record) → Word + Excel (only through the gated CLI commands)

One :class:`ReviewOrchestrator.execute` call produces a :class:`ReviewExecution`: the hash-chained
``ChallengeRecord`` the deterministic engine already defines (so ``apply_human_decisions``, the blockers rule and
the gate are unchanged), the per-objection exchanges, every role outcome with its execution identity, the
editorial candidates, the final review and the gate record. A provider failure anywhere is counted, escalates
the affected objection and blocks the gate record; it never produces an implicit approval.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..assurance import challenge as CH
from ..assurance.challenge import Adjudication, ChallengeRecord, ObjectionRecord, ObservationEntry
from ..assurance.evidence import EvidenceRegistry
from ..assurance.objection_engine import MAX_CYCLES, HumanDecision
from ..assurance.personas import RecipientPersona
from ..model.entities import Observation, ReviewState, plain_text
from ..release import attestation as ATT
from ..release.authorization_gate import (
    DEFAULT_GATE_DIR, PURPOSE_DEMO, PURPOSE_INSTITUTIONAL, attach_attestation, record_review, state_fingerprint,
)
from ..release.trust import TrustStore
from . import roles as R
from . import mat_advisor as MAT
from .contracts import MODE_DETERMINISTIC, MODE_LIVE, STATUS_OK, new_id
from .debate import Exchange, is_semantic_duplicate
from .runner import AgentRunner
from .tracing import TraceWriter, utc_now
from .mat_profile import LoadedProfile

INDEPENDENCE_LIVE = "ISOLATED_LIVE_CONTEXTS"
INDEPENDENCE_RULES = "SINGLE_PROCESS_RULE_BASED"
INDEPENDENCE_MIXED = "MIXED_LIVE_AND_RULES"
INDEPENDENCE_MOCK = "MOCK_SCRIPTED_CONTEXTS"
INDEPENDENCE_LIVE_UNVERIFIED = "LIVE_CLAIMED_NOT_VERIFIED"
ISOLATION_LIVE = "VERIFIED_PER_INVOCATION_CONTEXT"
ISOLATION_RULES = "NOT_VERIFIED"


@dataclass
class ReviewExecution:
    run_id: str
    fingerprint: str
    document_sha256: str
    state: ReviewState
    record: ChallengeRecord
    registry: EvidenceRegistry
    persona: RecipientPersona
    exchanges: dict[str, dict] = field(default_factory=dict)
    role_outcomes: list[dict] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)
    editorial_candidates: list[dict] = field(default_factory=list)
    final_review: dict | None = None
    final_outcome: dict | None = None
    human_decisions: list[dict] = field(default_factory=list)
    rejected_decisions: list[dict] = field(default_factory=list)
    provider_failures: int = 0
    guards_applied: Counter = field(default_factory=Counter)
    trace_summary: dict = field(default_factory=dict)
    gate_record: dict | None = None
    independence: dict = field(default_factory=dict)
    attestation: dict | None = None
    mat_advice: dict | None = None                       # MAT-01 drafting advice (candidates preserved)
    mat_state: dict[str, MAT.MatObservationState] = field(default_factory=dict)   # Article 15 audit state per observation
    mat_disclosure: dict | None = None
    started_utc: str = ""
    finished_utc: str = ""

    @property
    def blockers(self) -> list[dict]:
        return self.record.blockers()

    @property
    def status(self) -> str:
        return "BLOCKED" if (self.blockers or self.provider_failures) else "CLEAR"

    def modes(self) -> dict:
        return dict(Counter(o["mode"] for o in self.role_outcomes))

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, "fingerprint": self.fingerprint, "document_sha256": self.document_sha256,
                "status": self.status, "blockers": self.blockers, "provider_failures": self.provider_failures,
                "independence": self.record.independence, "role_isolation": self.record.role_isolation,
                "modes": self.modes(), "role_outcomes": self.role_outcomes, "exchanges": self.exchanges,
                "proposals": self.proposals, "editorial_candidates": self.editorial_candidates,
                "final_review": self.final_review, "final_outcome": self.final_outcome,
                "human_decisions": self.human_decisions, "rejected_decisions": self.rejected_decisions,
                "guards_applied": dict(self.guards_applied), "trace_summary": self.trace_summary,
                "independence_verification": self.independence, "attestation": self.attestation,
                "mat_advisor": {"disclosure": self.mat_disclosure, "drafting_advice": self.mat_advice,
                                "observation_state": {k: v.to_dict() for k, v in self.mat_state.items()}},
                "started_utc": self.started_utc, "finished_utc": self.finished_utc}


class ReviewOrchestrator:
    def __init__(self, index, *, runner: AgentRunner | None = None, gate_dir=DEFAULT_GATE_DIR, max_cycles: int = MAX_CYCLES,
                 mat_profile: LoadedProfile | None = None):
        self.index = index
        self.runner = runner
        self.gate_dir = Path(gate_dir)
        self.max_cycles = max_cycles
        # MAT strategic advisor: advisory stages only when a profile is loaded from an authorised location (Article 09)
        self.mat = MAT.MatAdvisor(mat_profile, runner) if mat_profile is not None else None

    @property
    def live(self) -> bool:
        return self.runner is not None and self.runner.available

    # ------------------------------------------------------------------ pipeline
    def execute(self, state: ReviewState, document, department: str | None = None, *, decisions: list | None = None,
                trust: TrustStore | None = None, draft: bool = False, record_path=None, command: str = "review",
                now: dt.datetime | None = None, attestation_key: tuple[bytes, str] | None = None,
                attestation_hours: int = ATT.DEFAULT_VALID_HOURS) -> ReviewExecution:
        started = utc_now()
        run_id = new_id("RUN")
        if self.runner is not None:
            self.runner.bind(run_id, state_fingerprint(state))
        # 1–3 execution record, state hash, evidence package
        registry = EvidenceRegistry()
        registry.add_document_text(document)
        registry.add_reference_index(self.index)
        dept = department or state.document.owning_department or ""
        persona = RecipientPersona.from_index(self.index, dept, registry)
        ex = ReviewExecution(run_id, state_fingerprint(state), registry.document["sha256"], state, None, registry, persona,
                             started_utc=started)
        # 3b optional drafting (proposals only)
        if draft:
            ex.proposals, out = R.run_drafting(self.runner, state, registry, persona)
            self._note(ex, out)
        current = state.current_round
        # 3c MAT-01 drafting advice over the candidates (register observations of this round + drafting proposals); advisory only
        if self.mat is not None:
            self._mat_drafting(ex, state, registry, persona, current)
        # 4–9 challenge every observation
        entries: list[ObservationEntry] = []
        live_objs: dict[str, CH.Objection] = {}
        for obs in state.ordered():
            issued = obs.birth_round < current
            objections, bt = R.run_black_team(self.runner, state, obs, registry, persona, issued=issued, siblings=state.observations)
            self._note(ex, bt, obs.internal_id)
            records: list[ObjectionRecord] = []
            if bt.failed:
                # the black team could not run: the observation cannot be cleared; one escalated objection stands for it
                o = CH.Objection(obs.internal_id, "RESERVED_DECISION", "تعذر تشغيل فريق التحدي (فشل المزود)؛ لا يمكن اعتبار الملاحظة خالية من اعتراض.",
                                 persona.addressee, issued=issued, material_consequence="لا تحدٍ مستقل للملاحظة", detail={"origin": "PROVIDER_FAILURE"})
                records.append(self._escalated_record(o, obs, registry, "BLACK_TEAM_PROVIDER_FAILURE"))
                live_objs[o.challenge_id] = o
            for o in self._consolidate(objections):
                rec, exchange = self._debate(ex, state, obs, o, registry, persona, issued=issued)
                records.append(rec)
                ex.exchanges[o.challenge_id] = exchange
                live_objs[o.challenge_id] = o
            scope = (objections[0].detail.get("scan_scope") if objections else CH._scan_scope(registry, persona)) or {}
            entries.append(ObservationEntry(obs.internal_id, obs.reader_no, issued, records, scope))
        independence, isolation, statement, ex.independence = self._independence(ex, registry)
        ex.record = ChallengeRecord(state.document.code, current, persona.to_dict(), entries, registry.to_dict(), self.max_cycles,
                                    independence=independence, role_isolation=isolation, isolation_statement=statement,
                                    _objections=live_objs)
        # 10–12 human authorisation (verified records only) and editorial candidates
        if decisions:
            self._apply_decisions(ex, decisions, trust, now=now)
        self._editorial(ex, state, registry)
        # 13 independent final reviewer (fresh context)
        self._final_review(ex, state, registry, persona)
        # 14 gate record (15: outputs only through the gated commands)
        ex.trace_summary = self.runner.trace.summary() if self.runner is not None else {"invocations": 0, "actual_live_inference_count": 0}
        rp = Path(record_path or self.gate_dir.parent / f"challenge_{state.document.code}_R{current}_{run_id[-8:]}.json")
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(ex.record.to_json(), encoding="utf-8")
        if self.mat is not None:                              # Article 15: every MAT state transition, next to the challenge record
            import json as _json
            rp.with_name(rp.stem + ".mat-state.json").write_text(_json.dumps(ex.to_dict()["mat_advisor"], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        trace_path = str(self.runner.trace.path) if (self.runner is not None and self.runner.trace.path) else None
        ex.gate_record = record_review(state, ex.record, rp, reference_mode=getattr(self.index, "mode", "INSTITUTIONAL_SOURCES"),
                                       gate_dir=self.gate_dir, decisions_applied=len(ex.human_decisions), command=command,
                                       provider_failures=ex.provider_failures, final_review=ex.final_review,
                                       human_decisions=ex.human_decisions, source_document_sha256=ex.document_sha256,
                                       execution_summary={"run_id": run_id, "modes": ex.modes(), "independence": independence,
                                                          "trace": ex.trace_summary, "guards": dict(ex.guards_applied),
                                                          "mat_advisor": self._mat_summary(ex)},
                                       role_execution_proofs=ex.independence.get("proofs", []), independence=ex.independence,
                                       trace_path=trace_path,
                                       trace_head_hash=self.runner.trace.head_hash if self.runner is not None else None)
        if attestation_key is not None:
            # Directive 4: the operator-held attestor key vouches for this record; the gate verifies it against the trust store
            key_bytes, key_id = attestation_key
            purpose = PURPOSE_DEMO if state.document.is_demo else PURPOSE_INSTITUTIONAL
            payload = ATT.build_payload(ex.gate_record, purpose=purpose, now=now, valid_hours=attestation_hours)
            ex.attestation = ATT.sign(payload, key_bytes, key_id).to_dict()
            ex.gate_record = attach_attestation(ex.fingerprint, ex.attestation, self.gate_dir)
        ex.finished_utc = utc_now()
        return ex

    # ------------------------------------------------------------------ helpers
    def _note(self, ex: ReviewExecution, outcome: R.RoleOutcome, observation_id: str | None = None, challenge_id: str | None = None):
        d = outcome.to_dict()
        d.update({"observation_id": observation_id, "challenge_id": challenge_id})
        ex.role_outcomes.append(d)
        if outcome.failed:
            ex.provider_failures += 1
        for n in outcome.notes:
            if n.startswith("guard:"):
                ex.guards_applied[n[6:]] += 1

    @staticmethod
    def _consolidate(objections: list[CH.Objection]) -> list[CH.Objection]:
        """One Challenge_ID per proposition; semantically repeated propositions collapse into the first."""
        out: list[CH.Objection] = []
        for o in objections:
            if any(x.challenge_id == o.challenge_id for x in out):
                continue
            dup, _ = is_semantic_duplicate(o.proposition, [x.proposition for x in out if x.kind == o.kind])
            if dup and out:
                continue
            out.append(o)
        return out

    def _escalated_record(self, o: CH.Objection, obs: Observation, registry: EvidenceRegistry, why: str) -> ObjectionRecord:
        o.add("BLACK", o.proposition, list(o.evidence_refs))
        adj = Adjudication(o.challenge_id, "ESCALATED_TO_GCO_REVIEWER", f"{why}: provider failure never clears an objection",
                           list(o.evidence_refs), [], open_question="إعادة تشغيل المراجعة بعد استعادة المزود أو قرار مراجع GCO")
        if not o.issued:
            o.decide(adj.disposition, verifications=registry.verifications())
        adv = {"challenge_id": o.challenge_id, "stance": "CONCEDE", "reasoning": why, "evidence_refs": [],
               "revised_comment": None, "revised_quote": None, "route_to": None}
        d = adj.to_dict(); d["observation_text_sha256"] = _h(plain_text(obs.comment))
        return ObjectionRecord(o.challenge_id, o.kind, o.proposition, o.material_consequence, list(o.evidence_refs),
                               [dict(e) for e in o.events], o.productive_cycles(), adv, d, o.state, o.verify_chain())

    def _debate(self, ex: ReviewExecution, state: ReviewState, obs: Observation, o: CH.Objection, registry: EvidenceRegistry,
                persona: RecipientPersona, *, issued: bool) -> tuple[ObjectionRecord, dict]:
        exchange = Exchange(o.challenge_id)
        if not self.live:
            mat_in = self._mat_interrogation(ex, state, obs, o, registry, persona, exchange, issued=issued)
            adv, adj = CH._argue(o, obs, registry, persona, self.max_cycles)       # the deterministic engine, unchanged
            for e in o.events:
                exchange.turns.append({"actor": e["actor"], "claim": e["claim"], "evidence_refs": list(e["evidence_refs"]),
                                       "stance": None, "execution_id": None, "cycle": e["sequence"]})
            self._mat_reassessment(ex, state, obs, o, registry, exchange, interrogation=mat_in, advocate=adv.to_dict(), issued=issued)
            d = adj.to_dict(); d["observation_text_sha256"] = _h(plain_text(obs.comment))
            return ObjectionRecord(o.challenge_id, o.kind, o.proposition, o.material_consequence, list(o.evidence_refs),
                                   [dict(e) for e in o.events], o.productive_cycles(), adv.to_dict(), d, o.state,
                                   o.verify_chain()), exchange.to_dict()
        exchange.add(o, "BLACK", o.proposition, list(o.evidence_refs), execution_id=o.detail.get("execution_id"))
        mat_in = self._mat_interrogation(ex, state, obs, o, registry, persona, exchange, issued=issued)
        adv, ro = R.run_red_advocate(self.runner, state, obs, o, registry, persona, issued=issued, prior_exchange=exchange.for_payload(),
                                     mat_advisory=exchange.advisory_view(MAT.STAGE_INTERROGATION))
        self._note(ex, ro, obs.internal_id, o.challenge_id)
        if adv is None:
            return self._provider_failure_record(o, obs, registry, "RED_ADVOCATE_PROVIDER_FAILURE"), exchange.to_dict()
        exchange.add(o, "RED_ADVOCATE", adv.reasoning, adv.evidence_refs, stance=adv.stance,
                     execution_id=ro.response.execution_id if ro.response else None)
        resolved = adv.stance in ("CONCEDE", "REVISE")
        # counters while productive: a fresh black-team context each time, with the exchange so far
        while not resolved and not exchange.cap_hit and len(exchange.turns) < self.max_cycles:
            counters, bo = R.run_black_team(self.runner, state, obs, registry, persona, issued=issued,
                                            siblings=state.observations, prior_exchange=exchange.for_payload())
            self._note(ex, bo, obs.internal_id, o.challenge_id)
            if bo.failed:
                return self._provider_failure_record(o, obs, registry, "BLACK_TEAM_COUNTER_PROVIDER_FAILURE"), exchange.to_dict()
            if not counters:
                break                                                            # the department has nothing more to say
            c = counters[0]
            if not exchange.add(o, "BLACK", c.proposition, list(c.evidence_refs), execution_id=c.detail.get("execution_id")):
                break                                                            # unproductive repeat: the objection ends as it stands
            reply, rr = R.run_red_advocate(self.runner, state, obs, o, registry, persona, issued=issued, prior_exchange=exchange.for_payload(),
                                           mat_advisory=exchange.advisory_view(MAT.STAGE_INTERROGATION))
            self._note(ex, rr, obs.internal_id, o.challenge_id)
            if reply is None:
                return self._provider_failure_record(o, obs, registry, "RED_ADVOCATE_PROVIDER_FAILURE"), exchange.to_dict()
            if not exchange.add(o, "RED_ADVOCATE", reply.reasoning, reply.evidence_refs, stance=reply.stance,
                                execution_id=rr.response.execution_id if rr.response else None):
                break
            adv = reply
            resolved = adv.stance in ("CONCEDE", "REVISE")
        last_black = bool(exchange.turns) and exchange.turns[-1]["actor"] == "BLACK"
        unresolved = (not resolved) and (exchange.cap_hit or last_black)
        self._mat_reassessment(ex, state, obs, o, registry, exchange, interrogation=mat_in, advocate=adv.to_dict(), issued=issued)
        adj, ao, guards = R.run_adjudicator(self.runner, state, obs, o, adv, registry, issued=issued,
                                            exchange=exchange.for_payload(), unresolved=unresolved,
                                            mat_advisory=self._mat_for_adjudicator(ex, obs, exchange))
        self._note(ex, ao, obs.internal_id, o.challenge_id)
        if self.mat is not None and ao.response is not None:
            self._mat_state(ex, state, obs).Adjudicator_Execution_ID.append(ao.response.execution_id)
        if adj is None:
            return self._provider_failure_record(o, obs, registry, "ADJUDICATOR_PROVIDER_FAILURE"), exchange.to_dict()
        for r in adv.evidence_refs:
            if registry.has(r) and r not in o.evidence_refs:
                o.evidence_refs.append(r)
        o.evidence_refs.sort()
        if not o.issued:
            try:
                o.decide(adj.disposition, verifications=registry.verifications())
            except ValueError:                                                  # the chain's own invariant: no basis without verified source
                adj = Adjudication(adj.challenge_id, "WITHHELD_FOR_EVIDENCE", adj.rationale + " [chain guard: no verified basis]",
                                   adj.evidence_refs, adj.inadmissible_refs, open_question=adj.open_question or "ربط مصدر متحقق")
                ex.guards_applied["CHAIN_NO_VERIFIED_BASIS"] += 1
                o.decide(adj.disposition, verifications=registry.verifications())
            adj.engine_recorded = True
        d = adj.to_dict(); d["observation_text_sha256"] = _h(plain_text(obs.comment)); d["guards"] = guards
        return ObjectionRecord(o.challenge_id, o.kind, o.proposition, o.material_consequence, list(o.evidence_refs),
                               [dict(e) for e in o.events], o.productive_cycles(), adv.to_dict(), d, o.state,
                               o.verify_chain()), exchange.to_dict()

    def _provider_failure_record(self, o: CH.Objection, obs: Observation, registry: EvidenceRegistry, why: str) -> ObjectionRecord:
        adj = Adjudication(o.challenge_id, "ESCALATED_TO_GCO_REVIEWER", f"{why}: a provider failure never produces an approval",
                           [r for r in o.evidence_refs if registry.has(r)], [], open_question="إعادة التشغيل بعد استعادة المزود أو قرار مراجع GCO")
        if not o.issued and o.state not in ("RESOLVED", "ESCALATED", "WITHHELD"):
            o.decide(adj.disposition, verifications=registry.verifications())
        adv = {"challenge_id": o.challenge_id, "stance": "CONCEDE", "reasoning": why, "evidence_refs": [],
               "revised_comment": None, "revised_quote": None, "route_to": None}
        d = adj.to_dict(); d["observation_text_sha256"] = _h(plain_text(obs.comment))
        return ObjectionRecord(o.challenge_id, o.kind, o.proposition, o.material_consequence, list(o.evidence_refs),
                               [dict(e) for e in o.events], o.productive_cycles(), adv, d, o.state, o.verify_chain())

    def _independence(self, ex: ReviewExecution, registry: EvidenceRegistry) -> tuple[str, str, str, dict]:
        """Classification from receipts (Directive 3): ISOLATED_LIVE_CONTEXTS only when every challenge role's
        outcome is backed by a verified live execution receipt in the trace, ids are unique and no substitution
        stands in; a run whose outcomes merely say mode=LIVE is LIVE_CLAIMED_NOT_VERIFIED."""
        challenge_roles = ("BLACK_TEAM", "RED_ADVOCATE", "ADJUDICATOR")
        challenge_modes = {o["mode"] for o in ex.role_outcomes if o["role"] in challenge_roles}
        trace_records = list(self.runner.trace.records) if self.runner is not None else []
        registry_ids = {e.id for e in registry.items()}
        verification = ATT.verify_live_roles(ex.role_outcomes, trace_records, registry_ids=registry_ids, run_id=ex.run_id,
                                             fingerprint=ex.fingerprint, expected_head=self.runner.trace.head_hash if self.runner else None)
        verification["execution_source"] = self.runner.execution_source if self.runner is not None else "DETERMINISTIC_RULES"
        if challenge_modes and challenge_modes <= {MODE_LIVE}:
            if verification["verified"]:
                return (INDEPENDENCE_LIVE, ISOLATION_LIVE,
                        f"Every challenge role ran as a separate model invocation in a fresh context ({verification['live_executions']} "
                        f"verified receipts, distinct Execution_IDs and Context_IDs); isolation verified per invocation, not across vendors.",
                        verification)
            return (INDEPENDENCE_LIVE_UNVERIFIED, ISOLATION_RULES,
                    f"Outcomes are labelled LIVE but the receipts do not verify: {', '.join(verification['reasons'])[:300]}", verification)
        if challenge_modes and challenge_modes <= {"MOCK", "CACHED"}:
            return (INDEPENDENCE_MOCK, "NOT_APPLICABLE_MOCK", "Challenge roles ran on scripted or replayed responses in separate contexts; no independence is claimed.", verification)
        if challenge_modes and MODE_LIVE in challenge_modes:
            return (INDEPENDENCE_MIXED, ISOLATION_RULES, "Some challenge roles ran live and some as rules; independence is not claimed for the run.", verification)
        return (INDEPENDENCE_RULES, ISOLATION_RULES, CH.ChallengeRecord.isolation_statement, verification)

    def _apply_decisions(self, ex: ReviewExecution, decisions: list, trust: TrustStore | None, *, now=None):
        institutional = not ex.state.document.is_demo
        accepted: list[HumanDecision] = []
        for d in decisions:
            if not isinstance(d, HumanDecision):
                ex.rejected_decisions.append({"item": repr(d)[:60], "reason": "NOT_A_HUMAN_DECISION_RECORD"})
                continue
            if trust is None:
                ex.rejected_decisions.append({"decision_id": d.decision_id, "reason": "TRUST_STORE_REQUIRED"})
                continue
            problems = trust.check_decision(d, now=now, fingerprint=ex.fingerprint, institutional=institutional)
            if problems:
                ex.rejected_decisions.append({"decision_id": d.decision_id, "reason": ",".join(problems)})
                continue
            accepted.append(d)
        if accepted:
            res = CH.apply_human_decisions(ex.record, accepted, trust.raw_keys(), registry=ex.registry)
            ex.rejected_decisions.extend(res["rejected"])
            applied_ids = {a["decision_id"] for a in res["applied"]}
            for d in accepted:
                if d.decision_id in applied_ids:
                    entry = trust.keys.get(d.signing_key_id)
                    ex.human_decisions.append({**{k: getattr(d, k) for k in HumanDecision.__dataclass_fields__},
                                               "synthetic_key": bool(entry and entry.is_synthetic)})
                    for st_ in ex.mat_state.values():
                        if d.challenge_id in st_.Black_Team_Challenge_ID:
                            st_.Human_Decision.append({"decision_id": d.decision_id, "challenge_id": d.challenge_id, "outcome": d.outcome})
                            st_.Final_Observation_State = f"HUMAN_DECISION:{d.outcome}"
                            st_.transition("HUMAN_DECISION", d.outcome, at=utc_now())

    def _editorial(self, ex: ReviewExecution, state: ReviewState, registry: EvidenceRegistry):
        by_id = state.by_id()
        for e in ex.record.entries:
            corrections = [{"challenge_id": o.challenge_id, "disposition": o.disposition,
                            "revised_comment": o.advocacy.get("revised_comment"), "revised_quote": o.advocacy.get("revised_quote"),
                            "summary": o.adjudication.get("rationale", "")[:200]}
                           for o in e.objections if o.disposition in ("UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE")
                           and (o.advocacy.get("revised_comment") or o.advocacy.get("revised_quote"))]
            if not corrections:
                continue
            cand, out = R.run_editorial(self.runner, state, by_id[e.internal_id], corrections, registry)
            self._note(ex, out, e.internal_id)
            ex.editorial_candidates.append({"internal_id": e.internal_id, "corrections": corrections, "candidate": cand,
                                            "status": "PROPOSED_FOR_HUMAN_REVIEW"})

    def _final_review(self, ex: ReviewExecution, state: ReviewState, registry: EvidenceRegistry, persona: RecipientPersona):
        finals = [{"internal_id": o.internal_id, "reader_no": o.reader_no, "location": plain_text(o.location),
                   "quote": plain_text(o.quote), "comment": plain_text(o.comment), "title": o.title, "title_status": o.title_status}
                  for o in state.ordered()]
        dispositions = [{"internal_id": e.internal_id, "challenge_id": o.challenge_id, "kind": o.kind, "disposition": o.disposition,
                         "resolved_by_human": o.resolved_by_human} for e in ex.record.entries for o in e.objections]
        out, ro = R.run_final_review(self.runner, state, finals, dispositions, registry, persona, blockers=ex.record.blockers())
        self._note(ex, ro)
        ex.final_outcome = out
        ex.final_review = {"recommendation": out["release_recommendation"], "mode": ro.mode, "status": ro.status,
                           "execution_id": ro.response.execution_id if ro.response else None,
                           "context_id": ro.response.context_id if ro.response else None,
                           "prompt_hash": ro.response.prompt_hash if ro.response else None,
                           "response_hash": ro.response.response_hash if ro.response else None,
                           "provider": ro.response.provider if ro.response else None,
                           "execution_source": ro.response.execution_source if ro.response else "DETERMINISTIC_RULES",
                           "provider_request_id": ro.response.provider_request_id if ro.response else None,
                           "fingerprint": ex.fingerprint,
                           "findings": len(out.get("findings", [])), "contradictions": len(out.get("contradictions", []))}

    # ------------------------------------------------------------------ MAT strategic advisor (advisory stages)
    def _mat_state(self, ex: ReviewExecution, state: ReviewState, obs: Observation) -> MAT.MatObservationState:
        st = ex.mat_state.get(obs.internal_id)
        if st is None:
            text = plain_text(obs.comment)
            st = MAT.MatObservationState(obs.internal_id, state.current_round, text, _h(text), self.mat.profile.version)
            ex.mat_state[obs.internal_id] = st
        return st

    def _mat_drafting(self, ex: ReviewExecution, state: ReviewState, registry: EvidenceRegistry, persona: RecipientPersona, current: int):
        candidates = [MAT.candidate_from_observation(o) for o in state.ordered() if o.birth_round >= current]
        candidates += [MAT.candidate_from_proposal(p, i + 1) for i, p in enumerate(ex.proposals)]
        res = self.mat.draft(state, candidates, registry, persona)
        self._note(ex, res.outcome)
        ex.role_outcomes[-1]["stage"] = res.stage
        ex.mat_advice = res.to_dict()
        ex.mat_disclosure = {"prior_drafting_involvement": True, "stage": MAT.STAGE_DRAFTING, "candidates_advised": [c["observation_id"] for c in candidates],
                             "profile_binding": self.mat.profile.binding(), "mode": res.outcome.mode, "execution_id": res.outcome.response.execution_id if res.outcome.response else None,
                             "note": "the advisor took part before the challenge; its material reaches other roles only as labelled advisory content"}
        by_id = state.by_id()
        for a in (res.output or {}).get("assessments", []):
            oid = a["observation_id"]
            if oid in by_id:
                st = self._mat_state(ex, state, by_id[oid])
                st.MAT_Drafting_Recommendation, st.MAT_Proposed_Text = a.get("recommendation"), a.get("proposed_text")
                st.MAT_DNA_Rules_Used = list(a.get("dna_rules_invoked", []))
                st.MAT_Drafting_Execution_ID = res.outcome.response.execution_id if res.outcome.response else None
                st.transition(MAT.STAGE_DRAFTING, a.get("recommendation", ""), execution_id=st.MAT_Drafting_Execution_ID, at=utc_now())

    def _mat_interrogation(self, ex, state, obs, o, registry, persona, exchange, *, issued) -> dict | None:
        if self.mat is None:
            return None
        st = self._mat_state(ex, state, obs)
        st.Black_Team_Challenge_ID.append(o.challenge_id)
        prior = None
        if ex.mat_advice:
            prior = next((a for a in ex.mat_advice["output"].get("assessments", []) if a["observation_id"] == obs.internal_id), None) if ex.mat_advice.get("output") else None
        res = self.mat.interrogate(state, obs, o, registry, persona, prior_advice=prior, prior_turns=exchange.advisory_turns(), issued=issued)
        self._note(ex, res.outcome, obs.internal_id, o.challenge_id)
        ex.role_outcomes[-1]["stage"] = res.stage
        if not res.ok:
            st.transition(MAT.STAGE_INTERROGATION, f"NOT_AVAILABLE:{res.outcome.status}", at=utc_now())
            return None
        exchange.advise(MAT.STAGE_INTERROGATION, res.output, execution_id=res.outcome.response.execution_id if res.outcome.response else None)
        eid = res.outcome.response.execution_id if res.outcome.response else None
        st.MAT_Interrogation_Execution_ID.append(eid)
        st.MAT_Interrogation_Response.append({"challenge_id": o.challenge_id, "decision": res.output["decision"], "guards": res.guards,
                                              "withdrawal_recommendation": res.output.get("withdrawal_recommendation")})
        st.transition(MAT.STAGE_INTERROGATION, res.output["decision"], execution_id=eid, at=utc_now())
        return res.output

    def _mat_reassessment(self, ex, state, obs, o, registry, exchange, *, interrogation, advocate, issued):
        if self.mat is None:
            return None
        st = self._mat_state(ex, state, obs)
        res = self.mat.reassess(state, obs, o, registry, interrogation=interrogation, advocate=advocate, exchange=exchange.for_payload(), issued=issued)
        self._note(ex, res.outcome, obs.internal_id, o.challenge_id)
        ex.role_outcomes[-1]["stage"] = res.stage
        if not res.ok:
            st.transition(MAT.STAGE_REASSESSMENT, f"NOT_AVAILABLE:{res.outcome.status}", at=utc_now())
            return None
        exchange.advise(MAT.STAGE_REASSESSMENT, res.output, execution_id=res.outcome.response.execution_id if res.outcome.response else None)
        eid = res.outcome.response.execution_id if res.outcome.response else None
        st.MAT_Reassessment_Execution_ID.append(eid)
        st.MAT_Final_Advisory_Position.append({"challenge_id": o.challenge_id, "decision": res.output["decision"], "position_changed": res.output.get("position_changed"),
                                               "change_reason": res.output.get("change_reason"), "guards": res.guards})
        st.Final_Observation_State = f"ADVISORY:{res.output['decision']}"
        st.transition(MAT.STAGE_REASSESSMENT, res.output["decision"] + (" (position changed)" if res.output.get("position_changed") else ""), execution_id=eid, at=utc_now())
        return res.output

    def _mat_for_adjudicator(self, ex, obs, exchange) -> dict | None:
        """What the adjudicator may see of MAT: the responses, explicitly labelled advisory, plus the disclosure (Article 13)."""
        if self.mat is None:
            return None
        return {"present": True, "status": "ADVISORY_ONLY_NOT_EVIDENCE", "disclosure": ex.mat_disclosure,
                "interrogation": exchange.advisory_view(MAT.STAGE_INTERROGATION), "reassessment": exchange.advisory_view(MAT.STAGE_REASSESSMENT)}

    def _mat_summary(self, ex) -> dict:
        if self.mat is None:
            return {"enabled": False}
        outs = [o for o in ex.role_outcomes if o["role"] == MAT.ROLE_MAT]
        return {"enabled": True, "profile": self.mat.profile.binding(), "disclosure": ex.mat_disclosure, "invocations": len(outs),
                "modes": dict(Counter(o["mode"] for o in outs)), "failed": sum(1 for o in outs if o["status"] not in (STATUS_OK, "NOT_RUN")),
                "advisory_only": True, "adjudicator_firewall": "MAT material reaches the adjudicator only as labelled advisory content; MAT never sees adjudicator output"}


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
