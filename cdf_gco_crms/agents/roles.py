"""The six roles (Article 03) over the isolated runner, with the deterministic engine as the fallback mode.

Each ``run_*`` function builds its purpose-limited payload, invokes the role in a fresh context and converts the
validated JSON into the engine's own objects (``Objection``, ``Advocacy``, ``Adjudication``) so that the
hash-chained record, the human-decision rules and the release gate apply unchanged. When no provider is
configured, the challenge roles fall back to ``assurance.challenge`` rules and say so (``mode=DETERMINISTIC``);
drafting has no deterministic fallback (``NOT_RUN``); editorial and final review have rule-based fallbacks.

Deterministic safeguards over probabilistic output:
  * an evidence id the registry does not hold is dropped and counted as ``hallucinated_refs``;
  * a DEFEND without admissible evidence becomes a CONCEDE flagged UNSUPPORTED_DEFENCE;
  * a REVISE without text becomes a CONCEDE flagged REVISION_WITHOUT_TEXT;
  * :func:`guard_disposition` re-applies the rule adjudicator's invariants to a live disposition
    (reserved → escalated, unresolved → escalated, no admissible defence → withheld, no verified basis → withheld).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..assurance import challenge as CH
from ..assurance.challenge import Adjudication, Advocacy, Objection, _gtext
from ..assurance.evidence import EvidenceRegistry
from ..assurance.personas import RecipientPersona
from ..model.entities import Observation, ReviewState, plain_text
from . import context_builder as CB
from .contracts import (
    MODE_DETERMINISTIC, NO_MATERIAL_OBJECTION, RELEASE_NOT_READY, RELEASE_READY, ROLE_ADJUDICATOR, ROLE_BLACK,
    ROLE_DRAFTING, ROLE_EDITORIAL, ROLE_FINAL, ROLE_RED, STATUS_NOT_RUN, STATUS_OK, AgentResponse,
)
from .runner import AgentRunner


@dataclass
class RoleOutcome:
    role: str
    mode: str
    status: str
    response: AgentResponse | None = None
    output: dict | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def failed(self) -> bool:
        """A provider failure, refusal or schema violation: the role produced nothing usable."""
        return self.status not in (STATUS_OK, STATUS_NOT_RUN)

    def to_dict(self) -> dict:
        return {"role": self.role, "mode": self.mode, "status": self.status, "notes": list(self.notes),
                "execution_id": self.response.execution_id if self.response else None,
                "context_id": self.response.context_id if self.response else None}


def _live(runner: AgentRunner | None) -> bool:
    return runner is not None and runner.available


def _admissible(registry: EvidenceRegistry, refs) -> tuple[list[str], list[str]]:
    good, bad = [], []
    for r in refs or []:
        (good if isinstance(r, str) and registry.has(r) else bad).append(r)
    return sorted(set(good)), sorted(set(map(str, bad)))


# ------------------------------------------------------------------ Agent A — drafting
def run_drafting(runner: AgentRunner | None, state: ReviewState, registry: EvidenceRegistry,
                 persona: RecipientPersona) -> tuple[list[dict], RoleOutcome]:
    """Proposed observations (never added to the register by this function)."""
    if not _live(runner):
        return [], RoleOutcome(ROLE_DRAFTING, MODE_DETERMINISTIC, STATUS_NOT_RUN, notes=["no provider: drafting has no deterministic fallback"])
    resp = runner.run(ROLE_DRAFTING, CB.SYSTEM[ROLE_DRAFTING], CB.drafting_payload(state, registry, persona), max_tokens=8192)
    if not resp.ok:
        return [], RoleOutcome(ROLE_DRAFTING, resp.mode, resp.status, resp, notes=[resp.error or ""])
    proposals = []
    for item in resp.output["observations"]:
        good, bad = _admissible(registry, item.get("evidence_refs"))
        anchor = registry.bind_clause(item.get("quote", ""))
        proposals.append({**item, "evidence_refs": good, "hallucinated_refs": bad, "quote_anchored": anchor is not None,
                          "status": "PROPOSED_FOR_HUMAN_REVIEW", "origin_execution_id": resp.execution_id})
    return proposals, RoleOutcome(ROLE_DRAFTING, resp.mode, resp.status, resp, resp.output)


# ------------------------------------------------------------------ Agent B — black team
def run_black_team(runner: AgentRunner | None, state: ReviewState, obs: Observation, registry: EvidenceRegistry,
                   persona: RecipientPersona, *, issued: bool, siblings=(), matter: str | None = None,
                   prior_exchange: list[dict] | None = None) -> tuple[list[Objection], RoleOutcome]:
    """First challenge (``prior_exchange`` empty) or a counter in a running debate (``prior_exchange`` given)."""
    if not _live(runner):
        objections = CH.black_team(obs, registry, persona, siblings=siblings, issued=issued, matter=matter)
        return objections, RoleOutcome(ROLE_BLACK, MODE_DETERMINISTIC, STATUS_OK, notes=["rule engine"])
    payload = CB.black_team_payload(state, obs, registry, persona, issued=issued, siblings=list(siblings),
                                    prior_exchange=prior_exchange)
    resp = runner.run(ROLE_BLACK, CB.SYSTEM[ROLE_BLACK], payload, observation_id=obs.internal_id)
    if not resp.ok:
        return [], RoleOutcome(ROLE_BLACK, resp.mode, resp.status, resp, notes=[resp.error or ""])
    out = resp.output
    outcome = RoleOutcome(ROLE_BLACK, resp.mode, resp.status, resp, out)
    if not out["material_objection"] or out["objection_kind"] == NO_MATERIAL_OBJECTION or not out["proposition"].strip():
        outcome.notes.append("NO_MATERIAL_OBJECTION")
        return [], outcome
    good, bad = _admissible(registry, out["evidence_refs"])
    if bad:
        outcome.notes.append(f"hallucinated_refs:{len(bad)}")
    reserved = None
    if CH.status_change_claim(plain_text(obs.comment)):
        reserved = "STATUS_CHANGE_OF_ISSUED" if issued else None
    objection = Objection(obs.internal_id, out["objection_kind"], out["proposition"].strip(), persona.addressee,
                          issued=issued, evidence_refs=good, material_consequence=out["material_consequence"],
                          detail={"origin": resp.mode, "execution_id": resp.execution_id, "context_id": resp.context_id,
                                  "requested_correction": out["requested_correction"], "confidence": out["confidence"],
                                  "existing_controls": out["existing_controls"], "hallucinated_refs": bad,
                                  "challenged_claim": out["challenged_claim"], "reserved": reserved,
                                  "scan_scope": {"mode": resp.mode}})
    return [objection], outcome


# ------------------------------------------------------------------ Agent C — red advocate
def run_red_advocate(runner: AgentRunner | None, state: ReviewState, obs: Observation, objection: Objection,
                     registry: EvidenceRegistry, persona: RecipientPersona, *, issued: bool,
                     prior_exchange: list[dict] | None = None) -> tuple[Advocacy | None, RoleOutcome]:
    if not _live(runner):
        return CH.red_advocate(objection, obs, registry), RoleOutcome(ROLE_RED, MODE_DETERMINISTIC, STATUS_OK, notes=["rule engine"])
    objection_view = {"challenge_id": objection.challenge_id, "objection_kind": objection.kind,
                      "proposition": objection.proposition, "material_consequence": objection.material_consequence,
                      "evidence_refs": list(objection.evidence_refs),
                      "requested_correction": objection.detail.get("requested_correction")}
    payload = CB.red_advocate_payload(state, obs, objection_view, registry, persona, issued=issued,
                                      prior_exchange=prior_exchange)
    resp = runner.run(ROLE_RED, CB.SYSTEM[ROLE_RED], payload, observation_id=obs.internal_id,
                      challenge_id=objection.challenge_id)
    if not resp.ok:
        return None, RoleOutcome(ROLE_RED, resp.mode, resp.status, resp, notes=[resp.error or ""])
    out = resp.output
    outcome = RoleOutcome(ROLE_RED, resp.mode, resp.status, resp, out)
    good, bad = _admissible(registry, out["evidence_refs"])
    if bad:
        outcome.notes.append(f"hallucinated_refs:{len(bad)}")
    stance, reasoning = out["stance"], out["reasoning"].strip() or "—"
    revised_comment = _gtext(out["revised_comment"]) if out.get("revised_comment") else None
    revised_quote = out.get("revised_quote") or None
    if stance == "DEFEND" and not good:
        outcome.notes.append("UNSUPPORTED_DEFENCE")
        stance = "CONCEDE"
        reasoning += " [الدفاع لم يحمل دليلاً مقبولاً في السجل؛ عُدّ تنازلاً]"
    if stance == "REVISE" and revised_comment is None and revised_quote is None:
        outcome.notes.append("REVISION_WITHOUT_TEXT")
        stance = "CONCEDE"
        reasoning += " [مراجعة بلا نص؛ عُدّت تنازلاً]"
    if out.get("escalate"):
        outcome.notes.append("ADVOCATE_ESCALATES")
    adv = Advocacy(objection.challenge_id, stance, reasoning, good, revised_comment=revised_comment,
                   revised_quote=revised_quote, route_to=out.get("route_to") or None)
    return adv, outcome


# ------------------------------------------------------------------ Agent D — adjudicator
def guard_disposition(objection: Objection, advocacy: Advocacy, adj: Adjudication, registry: EvidenceRegistry, *,
                      unresolved: bool) -> tuple[Adjudication, list[str]]:
    """Re-apply the rule adjudicator's invariants to any disposition (deterministic safeguards, Article 02)."""
    guards: list[str] = []
    refs = sorted(set(objection.evidence_refs) | set(advocacy.evidence_refs) | set(adj.evidence_refs))
    admissible = [r for r in refs if registry.has(r)]
    inadmissible = sorted(set(adj.inadmissible_refs) | {r for r in refs if not registry.has(r)})
    verified = [r for r in admissible if registry.resolve(r).authority_verified]
    disposition, open_q, reserved = adj.disposition, adj.open_question, adj.reserved_matter
    res = objection.detail.get("reserved") or ("ISSUED_OBSERVATION" if objection.issued else None)
    if res and disposition != "ESCALATED_TO_GCO_REVIEWER":
        disposition, reserved, open_q = "ESCALATED_TO_GCO_REVIEWER", res, open_q or "قرار مراجع GCO الموثق على المسألة المحجوزة"
        guards.append("RESERVED_MATTER")
    elif unresolved and disposition not in ("ESCALATED_TO_GCO_REVIEWER", "WITHHELD_FOR_EVIDENCE"):
        disposition, open_q = "ESCALATED_TO_GCO_REVIEWER", open_q or "اعتراض جوهري لم يُحسم عند حد الدورات"
        guards.append("UNRESOLVED_AT_BOUND")
    if advocacy.stance == "DEFEND" and not any(r in admissible for r in advocacy.evidence_refs) \
            and disposition in ("UPHELD_UNCHANGED", "UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE"):
        disposition, open_q = "WITHHELD_FOR_EVIDENCE", open_q or "ربط دليل الدفاع في سجل الأدلة"
        guards.append("DEFENCE_WITHOUT_ADMISSIBLE_EVIDENCE")
    if objection.kind in CH._AUTHORITY_KINDS and advocacy.stance == "DEFEND" and disposition == "UPHELD_UNCHANGED":
        sources = [registry.resolve(r) for r in advocacy.evidence_refs if registry.has(r)]
        if not [s for s in sources if s.kind != "DOCUMENT" and s.authority_verified]:
            disposition, open_q = "WITHHELD_FOR_EVIDENCE", open_q or "تقديم سجل اعتماد المصدر (02.9)"
            guards.append("AUTHORITY_SOURCE_NOT_APPROVED")
    if disposition in ("UPHELD_UNCHANGED", "UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE") and not verified:
        disposition, open_q = "WITHHELD_FOR_EVIDENCE", open_q or "إثبات الموضع في الوثيقة أو ربط مصدر معتمد"
        guards.append("NO_VERIFIED_BASIS")
    rationale = adj.rationale + (f" [guards: {', '.join(guards)}]" if guards else "")
    return Adjudication(adj.challenge_id, disposition, rationale, admissible, inadmissible, reserved_matter=reserved,
                        open_question=open_q), guards


def run_adjudicator(runner: AgentRunner | None, state: ReviewState, obs: Observation, objection: Objection,
                    advocacy: Advocacy, registry: EvidenceRegistry, *, issued: bool, exchange: list[dict] | None = None,
                    unresolved: bool = False) -> tuple[Adjudication | None, RoleOutcome, list[str]]:
    if not _live(runner):
        adj = CH.adjudicate(objection, advocacy, registry, unresolved=unresolved)
        return adj, RoleOutcome(ROLE_ADJUDICATOR, MODE_DETERMINISTIC, STATUS_OK, notes=["rule engine"]), []
    objection_view = {"challenge_id": objection.challenge_id, "objection_kind": objection.kind,
                      "proposition": objection.proposition, "material_consequence": objection.material_consequence,
                      "evidence_refs": list(objection.evidence_refs)}
    ev_ids = sorted(set(objection.evidence_refs) | set(advocacy.evidence_refs))
    payload = CB.adjudicator_payload(state, obs, objection_view, advocacy.to_dict(), registry, issued=issued,
                                     exchange=exchange, evidence_ids=ev_ids)
    resp = runner.run(ROLE_ADJUDICATOR, CB.SYSTEM[ROLE_ADJUDICATOR], payload, observation_id=obs.internal_id,
                      challenge_id=objection.challenge_id)
    if not resp.ok:
        return None, RoleOutcome(ROLE_ADJUDICATOR, resp.mode, resp.status, resp, notes=[resp.error or ""]), []
    out = resp.output
    good, bad = _admissible(registry, out["decisive_evidence"])
    raw = Adjudication(objection.challenge_id, out["disposition"], out["rationale"], good,
                       sorted(set(out["inadmissible_refs"]) | set(bad)), open_question=out.get("open_question"))
    adj, guards = guard_disposition(objection, advocacy, raw, registry, unresolved=unresolved or bool(out.get("escalate")))
    outcome = RoleOutcome(ROLE_ADJUDICATOR, resp.mode, resp.status, resp, out, notes=[f"guard:{g}" for g in guards])
    if bad:
        outcome.notes.append(f"hallucinated_refs:{len(bad)}")
    return adj, outcome, guards


# ------------------------------------------------------------------ Agent E — editorial
def run_editorial(runner: AgentRunner | None, state: ReviewState, obs: Observation, corrections: list[dict],
                  registry: EvidenceRegistry) -> tuple[dict, RoleOutcome]:
    """A revised candidate for human consideration; never applied by this function."""
    base = plain_text(obs.comment)
    if _live(runner):
        resp = runner.run(ROLE_EDITORIAL, CB.SYSTEM[ROLE_EDITORIAL], CB.editorial_payload(state, obs, corrections, registry),
                          observation_id=obs.internal_id)
        if resp.ok:
            cand = dict(resp.output)
            cand.update(_style_checks(cand["revised_comment"]))
            cand["candidate_status"] = "PROPOSED_FOR_HUMAN_REVIEW"
            return cand, RoleOutcome(ROLE_EDITORIAL, resp.mode, resp.status, resp, resp.output)
        outcome = RoleOutcome(ROLE_EDITORIAL, resp.mode, resp.status, resp, notes=[resp.error or "", "fallback: rule-based"])
    else:
        outcome = RoleOutcome(ROLE_EDITORIAL, MODE_DETERMINISTIC, STATUS_OK, notes=["rule-based: the authorised revision text is applied verbatim"])
    revised = base
    for c in corrections:
        if c.get("revised_comment"):
            revised = c["revised_comment"]
    cand = {"revised_comment": revised, "finding_part": revised.split("التوصية:")[0].strip() if "التوصية:" in revised else revised,
            "recommendation_part": CH.recommendation_part(revised), "proposed_title": "",
            "changes": [c.get("summary", c.get("disposition", "")) for c in corrections],
            "preserved_references": [plain_text(obs.location)], "requires_human_approval": True,
            "candidate_status": "PROPOSED_FOR_HUMAN_REVIEW"}
    cand.update(_style_checks(revised))
    return cand, outcome


def _style_checks(text: str) -> dict:
    return {"house_style": {"finding_before_recommendation": not text.strip().startswith(("التوصية:", "المطلوب:")),
                            "no_accusation": CH.breach_claim(text) is None,
                            "action_labelled": CH.has_action_label(text) or CH.states_requested_action(text)[0],
                            "within_word_ceiling": CH.word_count(text) <= CH.WORD_BUDGET}}


# ------------------------------------------------------------------ Agent F — independent final reviewer
def run_final_review(runner: AgentRunner | None, state: ReviewState, final_observations: list[dict],
                     dispositions: list[dict], registry: EvidenceRegistry, persona: RecipientPersona,
                     *, blockers: list[dict]) -> tuple[dict, RoleOutcome]:
    """Fresh-context final review; the rule-based fallback is explicit about what it can and cannot check."""
    if _live(runner):
        resp = runner.run(ROLE_FINAL, CB.SYSTEM[ROLE_FINAL],
                          CB.final_reviewer_payload(state, final_observations, dispositions, registry, persona),
                          agent_id="AGENT-FINAL_REVIEWER-FRESH", max_tokens=8192)
        if resp.ok:
            out = dict(resp.output)
            if blockers and out["release_recommendation"] == RELEASE_READY:
                out["release_recommendation"] = RELEASE_NOT_READY           # a blocker is never overridden by a reviewer
                out["unresolved_critical_objections"] = sorted(set(out["unresolved_critical_objections"]) |
                                                               {b["challenge_id"] for b in blockers})
            return out, RoleOutcome(ROLE_FINAL, resp.mode, resp.status, resp, resp.output)
        return {"release_recommendation": RELEASE_NOT_READY, "findings": [], "contradictions": [],
                "unresolved_critical_objections": [b["challenge_id"] for b in blockers], "jurisdiction_consistent": False,
                "unsupported_or_excessive": [], "summary": f"final review failed: {resp.error}"}, \
            RoleOutcome(ROLE_FINAL, resp.mode, resp.status, resp, notes=[resp.error or ""])
    findings, contradictions = [], []
    texts = {o["internal_id"]: o["comment"] for o in final_observations}
    ids = list(texts)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if CH.remedy_overlap(CH.recommendation_part(texts[a]), CH.recommendation_part(texts[b])) >= 0.6:
                contradictions.append(f"{a} and {b} request the same remedy")
    challenged = {(d["internal_id"], d["kind"]) for d in dispositions}
    for iid, text in texts.items():
        claim = CH.breach_claim(text)
        if claim and (iid, "UNSUPPORTED_BREACH_CLAIM") not in challenged:
            # the challenge did not examine this breach wording: a reviewer must, so the file is not ready
            findings.append({"observation_id": iid, "issue": f"breach wording «{claim}» not examined by the challenge",
                             "severity": "MAJOR", "evidence_refs": []})
        if CH.word_count(text) > CH.WORD_BUDGET:
            findings.append({"observation_id": iid, "issue": "exceeds the word ceiling", "severity": "MINOR", "evidence_refs": []})
    critical = [b["challenge_id"] for b in blockers]
    rec = RELEASE_NOT_READY if (critical or any(f["severity"] in ("CRITICAL", "MAJOR") for f in findings)) else RELEASE_READY
    out = {"release_recommendation": rec, "findings": findings, "contradictions": contradictions,
           "unresolved_critical_objections": critical, "jurisdiction_consistent": True,
           "unsupported_or_excessive": [f["observation_id"] for f in findings if f["severity"] == "MAJOR"],
           "summary": "rule-based final check (no live reviewer): blockers, duplicate remedies, unexamined breach wording, "
                      "word ceiling; it is not the independent Article 20 review"}
    return out, RoleOutcome(ROLE_FINAL, MODE_DETERMINISTIC, STATUS_OK, notes=["rule-based fallback; an Article 20 live review was not run"])
