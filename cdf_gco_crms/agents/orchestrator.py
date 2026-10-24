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
from ..release.authorization_gate import DEFAULT_GATE_DIR, record_review, state_fingerprint
from ..release.trust import TrustStore
from . import roles as R
from .contracts import MODE_DETERMINISTIC, MODE_LIVE, STATUS_OK, new_id
from .debate import Exchange, is_semantic_duplicate
from .runner import AgentRunner
from .tracing import TraceWriter, utc_now

INDEPENDENCE_LIVE = "ISOLATED_LIVE_CONTEXTS"
INDEPENDENCE_RULES = "SINGLE_PROCESS_RULE_BASED"
INDEPENDENCE_MIXED = "MIXED_LIVE_AND_RULES"
INDEPENDENCE_MOCK = "MOCK_SCRIPTED_CONTEXTS"
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
                "started_utc": self.started_utc, "finished_utc": self.finished_utc}


class ReviewOrchestrator:
    def __init__(self, index, *, runner: AgentRunner | None = None, gate_dir=DEFAULT_GATE_DIR, max_cycles: int = MAX_CYCLES):
        self.index = index
        self.runner = runner
        self.gate_dir = Path(gate_dir)
        self.max_cycles = max_cycles

    @property
    def live(self) -> bool:
        return self.runner is not None and self.runner.available

    # ------------------------------------------------------------------ pipeline
    def execute(self, state: ReviewState, document, department: str | None = None, *, decisions: list | None = None,
                trust: TrustStore | None = None, draft: bool = False, record_path=None, command: str = "review",
                now: dt.datetime | None = None) -> ReviewExecution:
        started = utc_now()
        run_id = new_id("RUN")
        if self.runner is not None:
            self.runner.trace.run_id = run_id
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
        # 4–9 challenge every observation
        current = state.current_round
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
        independence, isolation, statement = self._independence(ex)
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
        ex.gate_record = record_review(state, ex.record, rp, reference_mode=getattr(self.index, "mode", "INSTITUTIONAL_SOURCES"),
                                       gate_dir=self.gate_dir, decisions_applied=len(ex.human_decisions), command=command,
                                       provider_failures=ex.provider_failures, final_review=ex.final_review,
                                       human_decisions=ex.human_decisions, source_document_sha256=ex.document_sha256,
                                       execution_summary={"run_id": run_id, "modes": ex.modes(), "independence": independence,
                                                          "trace": ex.trace_summary, "guards": dict(ex.guards_applied)})
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
            adv, adj = CH._argue(o, obs, registry, persona, self.max_cycles)       # the deterministic engine, unchanged
            for e in o.events:
                exchange.turns.append({"actor": e["actor"], "claim": e["claim"], "evidence_refs": list(e["evidence_refs"]),
                                       "stance": None, "execution_id": None, "cycle": e["sequence"]})
            d = adj.to_dict(); d["observation_text_sha256"] = _h(plain_text(obs.comment))
            return ObjectionRecord(o.challenge_id, o.kind, o.proposition, o.material_consequence, list(o.evidence_refs),
                                   [dict(e) for e in o.events], o.productive_cycles(), adv.to_dict(), d, o.state,
                                   o.verify_chain()), exchange.to_dict()
        exchange.add(o, "BLACK", o.proposition, list(o.evidence_refs), execution_id=o.detail.get("execution_id"))
        adv, ro = R.run_red_advocate(self.runner, state, obs, o, registry, persona, issued=issued, prior_exchange=exchange.for_payload())
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
            reply, rr = R.run_red_advocate(self.runner, state, obs, o, registry, persona, issued=issued, prior_exchange=exchange.for_payload())
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
        adj, ao, guards = R.run_adjudicator(self.runner, state, obs, o, adv, registry, issued=issued,
                                            exchange=exchange.for_payload(), unresolved=unresolved)
        self._note(ex, ao, obs.internal_id, o.challenge_id)
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

    def _independence(self, ex: ReviewExecution) -> tuple[str, str, str]:
        challenge_modes = {o["mode"] for o in ex.role_outcomes if o["role"] in ("BLACK_TEAM", "RED_ADVOCATE", "ADJUDICATOR")}
        execs = [o["execution_id"] for o in ex.role_outcomes if o["execution_id"]]
        if challenge_modes and challenge_modes <= {MODE_LIVE}:
            return (INDEPENDENCE_LIVE, ISOLATION_LIVE,
                    f"Every challenge role ran as a separate model invocation in a fresh context ({len(execs)} executions, "
                    f"{len(set(execs))} distinct Execution_IDs); isolation verified per invocation, not across vendors.")
        if challenge_modes and challenge_modes <= {"MOCK", "CACHED"}:
            return (INDEPENDENCE_MOCK, "NOT_APPLICABLE_MOCK", "Challenge roles ran on scripted or replayed responses in separate contexts; no independence is claimed.")
        if challenge_modes and MODE_LIVE in challenge_modes:
            return (INDEPENDENCE_MIXED, ISOLATION_RULES, "Some challenge roles ran live and some as rules; independence is not claimed for the run.")
        return (INDEPENDENCE_RULES, ISOLATION_RULES, CH.ChallengeRecord.isolation_statement)

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
                           "findings": len(out.get("findings", [])), "contradictions": len(out.get("contradictions", []))}


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
