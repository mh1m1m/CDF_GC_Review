"""MAT_STRATEGIC_GRC_ADVISOR — an advisory role at three points of the review protocol (directive Articles 09–15).

  MAT-01 drafting advice   after the GCO drafting agent, before the Black Team: for every candidate observation a
                           recommendation (KEEP … PROPOSE_WITHDRAWAL … ESCALATE) with the profile rules invoked and
                           their evidence status. The candidate is never removed: both the candidate and the advice
                           are preserved and a human can restore anything the advice filtered.
  MAT-02 interrogation     after a Black Team objection: the advisor answers the objection (DEFEND_WITH_EVIDENCE …
                           PROPOSE_WITHDRAWAL … ESCALATE_TO_HUMAN). The advisor's prior drafting involvement is
                           disclosed in the payload and in the record; a defence without admissible evidence is
                           downgraded by rule.
  MAT-03 reassessment      after the Red Advocate: in a fresh context the advisor says whether its reasoning still
                           holds, whether the objection found a genuine deficiency and whether the position changes.
                           An evidence-based reversal is recorded as a desirable outcome, never penalised.

Firewall: the advisor never adjudicates, never approves and never sees adjudicator deliberations. Its outputs reach the
adjudicator only as ``mat_advisory`` material explicitly labelled as the opinion of a participant. Advisory turns are
recorded on the exchange but never appended to the objection's hash chain, so the six-productive-cycle limit per
objection is untouched (Article 14).

Execution: the same isolated runner as every other role (fresh context per invocation, schema validation, hash-chained
trace). Without a provider the advisor runs a documented rule-based fallback labelled ``DETERMINISTIC`` and never
presented as the reviewer's judgment. Every output carries the profile binding (id, version, sha256, approval).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..assurance import challenge as CH
from ..assurance.evidence import EvidenceRegistry
from ..assurance.personas import RecipientPersona
from ..model.entities import Observation, ReviewState, plain_text
from . import context_builder as CB
from .contracts import MODE_DETERMINISTIC, ROLE_MAT, STATUS_NOT_RUN, STATUS_OK, _arr, _obj, _s
from .debate import is_semantic_duplicate
from .mat_profile import GROUND_LABELS, WITHDRAWAL_GROUNDS, LoadedProfile
from .roles import RoleOutcome, _admissible, _live
from .runner import AgentRunner

STAGE_DRAFTING, STAGE_INTERROGATION, STAGE_REASSESSMENT = "MAT-01_DRAFTING", "MAT-02_INTERROGATION", "MAT-03_REASSESSMENT"
AGENT_IDS = {STAGE_DRAFTING: "AGENT-MAT_ADVISOR-DRAFTING", STAGE_INTERROGATION: "AGENT-MAT_ADVISOR-INTERROGATION",
             STAGE_REASSESSMENT: "AGENT-MAT_ADVISOR-REASSESSMENT-FRESH"}

DRAFT_DECISIONS = ("KEEP", "REVISE", "STRENGTHEN", "SOFTEN", "CONVERT_TO_QUESTION", "CONVERT_TO_RECOMMENDATION", "NARROW",
                   "MERGE", "REQUEST_EVIDENCE", "PROPOSE_WITHDRAWAL", "ESCALATE")
DEBATE_DECISIONS = ("DEFEND_WITH_EVIDENCE", "ACCEPT_OBJECTION", "REVISE_RECOMMENDATION", "CONVERT_TO_QUESTION", "NARROW_SCOPE",
                    "MERGE_OBSERVATIONS", "REQUEST_ADDITIONAL_EVIDENCE", "PROPOSE_WITHDRAWAL", "ESCALATE_TO_HUMAN")
FRAMINGS = ("DIRECT_RECOMMENDATION", "DIRECT_QUESTION", "QUESTION_WITH_RECOMMENDATION", "CONDITIONAL_RECOMMENDATION",
            "PROPOSED_AMENDMENT", "INFORMATION_REQUEST", "DEFECT_FLAG")
TRI = ("YES", "NO", "UNCERTAIN")

# Article 11.3 — interrogation questions, selected by objection kind (never all of them mechanically)
INTERROGATION_QUESTIONS = {
    "IQ01": "What precise governance requirement does this observation address?",
    "IQ02": "Which document provision supports the finding?",
    "IQ03": "What material risk arises if the observation is not adopted?",
    "IQ04": "Which authorized party is responsible?",
    "IQ05": "Does the agreement already contain an adequate safeguard?",
    "IQ06": "Is the proposed remedy proportionate?",
    "IQ07": "Is the issue within GCO's remit?",
    "IQ08": "Is the observation duplicative?",
    "IQ09": "Does it conflict with another comment?",
    "IQ10": "Why is this framed as a recommendation rather than a question?",
    "IQ11": "Does the advisor's inferred writing preference apply to this situation?",
    "IQ12": "What evidence would cause the advisor to change position?",
    "IQ13": "Would a narrower recommendation resolve the issue?",
    "IQ14": "Under what conditions should the observation be withdrawn?",
    "IQ15": "Is the recommendation supported by an actual requirement or merely professional preference?",
}
QUESTIONS_BY_KIND = {
    "CLAUSE_NOT_FOUND": ["IQ02", "IQ12", "IQ14"], "AUTHORITY_MISMATCH": ["IQ04", "IQ01", "IQ15"], "AUTHORITY_UNSUPPORTED": ["IQ04", "IQ15", "IQ12"],
    "OUTSIDE_RECIPIENT_MANDATE": ["IQ07", "IQ04", "IQ13"], "CONTESTED_OWNERSHIP": ["IQ04", "IQ07"], "UNSUPPORTED_BREACH_CLAIM": ["IQ02", "IQ15", "IQ10"],
    "DUPLICATE_REMEDY": ["IQ08", "IQ09", "IQ13"], "UNCLEAR_ACTION": ["IQ03", "IQ06", "IQ13"], "VERBOSE": ["IQ06", "IQ13", "IQ11"],
    "RESERVED_DECISION": ["IQ07", "IQ14"],
}

_RULE_IDS = _arr(_s(pattern=r"^[A-Z]{2,6}-[A-Z]\d{2}$"))
_APPLICABILITY = _arr(_obj({"rule_id": _s(), "applicable": {"type": "boolean"}, "reason": _s(maxLength=300)}))
_GROUND = {"type": ["string", "null"], "enum": list(WITHDRAWAL_GROUNDS) + [None]}
_CONF = {"type": "number", "minimum": 0, "maximum": 1}

MAT_DRAFTING_SCHEMA = _obj({
    "assessments": _arr(_obj({
        "observation_id": _s(), "should_be_formal_observation": {"type": "boolean"}, "material": {"type": "boolean"},
        "within_gco_jurisdiction": _s(enum=list(TRI)), "evidence_sufficient": {"type": "boolean"},
        "covered_elsewhere_by": _arr(_s()), "contradicts": _arr(_s()),
        "recommendation": _s(enum=list(DRAFT_DECISIONS)), "framing": _s(enum=list(FRAMINGS)),
        "proposed_text": {"type": ["string", "null"]}, "rationale": _s(maxLength=900),
        "dna_rules_invoked": _RULE_IDS, "dna_rule_applicability": _APPLICABILITY, "withdrawal_ground": _GROUND,
        "proportionate_and_implementable": {"type": "boolean"}, "evidence_refs": CB._EVIDENCE_IDS if hasattr(CB, "_EVIDENCE_IDS") else _arr(_s()),
        "confidence": _CONF,
    })),
    "reasoning_summary": _s(maxLength=1200),
})
MAT_INTERROGATION_SCHEMA = _obj({
    "challenge_id": _s(), "observation_id": _s(), "original_position": _s(maxLength=600), "black_team_objection": _s(maxLength=600),
    "accepted_facts": _arr(_s()), "disputed_facts": _arr(_s()), "verified_evidence": _arr(_s()), "unverified_assumptions": _arr(_s()),
    "mat_dna_rules_invoked": _RULE_IDS, "mat_dna_rule_applicability": _APPLICABILITY,
    "response": _s(maxLength=1600), "decision": _s(enum=list(DEBATE_DECISIONS)), "revised_position": _s(maxLength=600),
    "proposed_wording": {"type": ["string", "null"]}, "withdrawal_recommendation": {"type": "boolean"}, "withdrawal_ground": _GROUND,
    "confidence": _CONF, "escalation_required": {"type": "boolean"}, "new_argument": {"type": "boolean"},
})
MAT_REASSESSMENT_SCHEMA = _obj({
    "challenge_id": _s(), "previous_reasoning_valid": {"type": "boolean"}, "black_team_identified_genuine_deficiency": {"type": "boolean"},
    "red_advocate_addressed_deficiency": {"type": "boolean"}, "revised_comment_necessary": {"type": "boolean"},
    "decision": _s(enum=list(DEBATE_DECISIONS)), "final_advisory_position": _s(maxLength=1600), "proposed_wording": {"type": ["string", "null"]},
    "withdrawal_recommendation": {"type": "boolean"}, "withdrawal_ground": _GROUND, "new_evidence_required": _arr(_s()),
    "position_changed": {"type": "boolean"}, "change_reason": _s(maxLength=600), "evidence_refs": _arr(_s()), "confidence": _CONF,
})
SCHEMAS_BY_STAGE = {STAGE_DRAFTING: MAT_DRAFTING_SCHEMA, STAGE_INTERROGATION: MAT_INTERROGATION_SCHEMA, STAGE_REASSESSMENT: MAT_REASSESSMENT_SCHEMA}

_MAT_COMMON = CB.COMMON_RULES + (
    " ROLE: MAT STRATEGIC GRC ADVISOR. You advise from a documented professional review method given in the payload as "
    "'profile'. Every profile rule carries a 'use' value: BINDING rules are instructions; ADVISORY rules describe a documented "
    "preference that never overrides the document's evidence, institutional policy or law; NOT_ESTABLISHED rules may be named "
    "but never relied on. Name every rule you invoke and say whether it applies to this case and why. You never approve, never "
    "adjudicate, never decide a disposition, and never refer to any person by name — refer to units by role. A proposed "
    "withdrawal is a recommendation to humans: the candidate observation is preserved and restorable. A regulatory-compliance "
    "safeguard (anti-money-laundering, regulator or auditor access, mandatory reporting) is never proposed for withdrawal; "
    "escalate it instead.")
SYSTEM_MAT = {
    STAGE_DRAFTING: _MAT_COMMON + (
        " STAGE: DRAFTING ADVICE. For every candidate decide: should it become a formal observation; is it material; within GCO "
        "jurisdiction; is the evidence sufficient; is it covered elsewhere or contradicted by a sibling; should it be a question "
        "or a recommendation; should it be narrowed, merged, strengthened, softened or withdrawn; is the wording proportionate "
        "and implementable. Give proposed_text only when you change the wording."),
    STAGE_INTERROGATION: _MAT_COMMON + (
        " STAGE: INTERROGATION. You took part in advising on this candidate (disclosed in the payload). Answer the Black Team's "
        "objection on the selected interrogation questions: separate accepted from disputed facts, cite verified evidence ids "
        "only, list your unverified assumptions, and choose one decision. Do not defend the observation because you helped "
        "draft it; DEFEND_WITH_EVIDENCE needs evidence ids that actually support it. Set new_argument=false if you would only "
        "repeat an earlier advisory turn shown in the payload."),
    STAGE_REASSESSMENT: _MAT_COMMON + (
        " STAGE: REASSESSMENT (fresh context). You see the observation, the objection, your earlier response, the Red "
        "Advocate's independent analysis and the evidence. State whether your earlier reasoning still holds, whether the "
        "objection identified a genuine deficiency, whether the advocate addressed it, whether a revised comment is needed, "
        "whether withdrawal or new evidence is warranted, and give your final advisory position. A reversal supported by "
        "evidence is the right outcome when the evidence calls for it."),
}
CB.SYSTEM.setdefault(ROLE_MAT, SYSTEM_MAT[STAGE_DRAFTING])

# ------------------------------------------------------------------ deterministic markers (documented, hamza-insensitive)
_FORMAL = ("ترقيم", "تنسيق", "املائي", "نحوي", "عنوان الماده", "صفحه الغلاف", "في سطر مستقل", "يرفع المضاف", "خطا مطبعي")
_REGULATORY = ("غسل الاموال", "مكافحه", "اعرف عميلك", "الجهات الرقابيه", "الجهه الرقابيه", "الرقابيه المختصه", "المراجعين الخارجيين", "الابلاغ الالزامي")
_SANCTION = ("يسال عنه", "تعديا", "لا يستحق", "اخلالا جوهريا", "مسؤولا عن اي خساره", "يرده ان كان", "غرامه", "تعويض", "يتحمل تكاليف")
_AUTHORITY = ("صاحب الصلاحيه", "مصفوفه الصلاحيات", "من يملك صلاحيه")
_APPRAISAL = ("والاقرب ان", "يبطل", "باطل", "لا يغني عنه")
_PERSON = re.compile(r"(?:(?<!\w))(?:الاخ|الأخ|الاخت|الأخت|ابو|أبو|ام|أم|الزميل|الزميله|الزميلة|الأستاذ|الاستاذ|الدكتور|المهندس)\s+\S+", re.U)
_UNIT_PLACEHOLDER = "[الوحدة المختصة]"
_NUMBER = re.compile(r"\d|[٠-٩]")


_DIACRITICS = re.compile("[\u064b-\u0652\u0670\u0640]")


def _n(text: str) -> str:
    """Hamza-, ta-marbuta- and diacritic-insensitive form (quickly typed comments spell نامل / اضافة / التاكيد)."""
    t = _DIACRITICS.sub("", text or "")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", t).strip().lower()


def _has(text: str, markers) -> bool:
    t = _n(text)
    return any(_n(m) in t for m in markers)


def strip_person_references(text: str | None) -> tuple[str | None, int]:
    """Replace honorific + name references by a role placeholder (Article 17 guard, applies to every MAT output)."""
    if not text:
        return text, 0
    out, n = _PERSON.subn(_UNIT_PLACEHOLDER, text)
    return out, n


def is_regulatory_safeguard(text: str) -> bool:
    return _has(text, _REGULATORY)


@dataclass
class MatResult:
    stage: str
    output: dict | None
    outcome: RoleOutcome
    guards: list[str] = field(default_factory=list)
    binding: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.output is not None

    def to_dict(self) -> dict:
        return {"stage": self.stage, "output": self.output, "role_outcome": self.outcome.to_dict(), "guards": list(self.guards),
                "profile_binding": dict(self.binding), "mode": self.outcome.mode, "status": self.outcome.status,
                "execution_id": self.outcome.response.execution_id if self.outcome.response else None}


class MatAdvisor:
    """The advisor bound to one loaded profile and one runner (or none: rule-based fallback)."""

    def __init__(self, profile: LoadedProfile, runner: AgentRunner | None = None):
        self.profile = profile
        self.runner = runner

    @property
    def live(self) -> bool:
        return _live(self.runner)

    # -------------------------------------------------------------- shared helpers
    def _rule_checks(self, invoked: list[str]) -> tuple[list[str], list[dict], list[str]]:
        """Keep only rules the profile holds; report each rule's permitted use; count unknown ids."""
        kept, uses, unknown = [], [], []
        for rid in invoked or []:
            st = self.profile.rule_status(rid)
            if st["use"] == "UNKNOWN_RULE":
                unknown.append(rid)
                continue
            kept.append(rid)
            uses.append(st)
        return kept, uses, unknown

    def _invoke(self, stage: str, payload: dict, *, max_tokens: int = 4096, **trace_extra):
        return self.runner.run(ROLE_MAT, SYSTEM_MAT[stage], payload, schema=SCHEMAS_BY_STAGE[stage], agent_id=AGENT_IDS[stage],
                               max_tokens=max_tokens, mat_stage=stage, **trace_extra)

    # -------------------------------------------------------------- MAT-01 drafting advice
    def draft(self, state: ReviewState, candidates: list[dict], registry: EvidenceRegistry, persona: RecipientPersona) -> MatResult:
        """``candidates``: dicts with observation_id, location, quote, comment (and optional title, origin)."""
        payload = {"label": CB._label(state), "stage": STAGE_DRAFTING, "profile": self.profile.view(), "recipient": CB._persona(persona),
                   "candidates": [{k: c.get(k) for k in ("observation_id", "origin", "location", "quote", "comment", "title")} for c in candidates],
                   "evidence": CB._evidence_items(registry), "document_paragraphs": CB._paragraphs(registry),
                   "context_isolation": "no Black Team, advocate or adjudicator material; profile rules carry their evidence status"}
        if self.live:
            resp = self._invoke(STAGE_DRAFTING, payload, max_tokens=8192)
            if resp.ok:
                out, guards = self._guard_drafting(dict(resp.output), candidates, registry)
                return MatResult(STAGE_DRAFTING, out, RoleOutcome(ROLE_MAT, resp.mode, resp.status, resp, out, notes=[f"guard:{g}" for g in guards]), guards, self.profile.binding())
            return MatResult(STAGE_DRAFTING, None, RoleOutcome(ROLE_MAT, resp.mode, resp.status, resp, notes=[resp.error or ""]), [], self.profile.binding())
        out = self._rule_based_drafting(candidates, registry)
        out, guards = self._guard_drafting(out, candidates, registry)
        return MatResult(STAGE_DRAFTING, out, RoleOutcome(ROLE_MAT, MODE_DETERMINISTIC, STATUS_OK, None, out,
                                                           notes=["rule-based fallback: documented markers, not the reviewer's judgment"] + [f"guard:{g}" for g in guards]),
                         guards, self.profile.binding())

    def _rule_based_drafting(self, candidates: list[dict], registry: EvidenceRegistry) -> dict:
        rules = self.profile.rules()
        by_cond = {r["rule_id"]: r for r in rules.values()}
        def find(*words):
            for rid, r in by_cond.items():
                c = (r.get("condition") or "").lower()
                if all(w in c for w in words):
                    return rid
            return None
        r_formal, r_sanction, r_money = find("formal"), find("sanction"), find("money")
        r_question, r_appraisal, r_regulatory = find("suitability"), find("appraisal"), find("regulatory")
        remedies = {c["observation_id"]: CH.recommendation_part(plain_text(c.get("comment") or "")) for c in candidates}
        out = []
        for c in candidates:
            text = plain_text(c.get("comment") or ""); oid = c["observation_id"]
            anchor = registry.bind_clause(c.get("quote") or "") if c.get("quote") else None
            dup = [o for o, rem in remedies.items() if o != oid and rem and remedies[oid] and CH.remedy_overlap(remedies[oid], rem) >= 0.6]
            rec, framing, ground, rules_used, proposed, why = "KEEP", "DIRECT_RECOMMENDATION", None, [], None, "no documented marker applies; kept as drafted"
            if is_regulatory_safeguard(text):
                rec, why, rules_used = "ESCALATE", "regulatory-compliance safeguard: no withdrawal rule exists; human decision required", [r for r in (r_regulatory,) if r]
            elif dup:
                rec, ground, why, rules_used = "MERGE", "MAT-W06", f"remedy overlaps {', '.join(dup)}", ["MAT-W06"] if "MAT-W06" in rules else []
            elif _has(text, _FORMAL):
                rec, framing, ground, why = "PROPOSE_WITHDRAWAL", "DEFECT_FLAG", "MAT-W10", "formal/typographic item: documented preference is a flag without a prescribed fix"
                rules_used = [r for r in (r_formal, "MAT-W10") if r and r in rules]
                proposed = "يوجد خطأ شكلي في هذا الموضع."
            elif _has(text, _SANCTION):
                rec, why, rules_used = "SOFTEN", "the control is kept; the sanction / liability clause is dropped (documented preference)", [r for r in (r_sanction,) if r]
                proposed = _drop_sanction(text)
            elif _has(text, _AUTHORITY) and _NUMBER.search(text):
                rec, framing, why, rules_used = "CONVERT_TO_QUESTION", "DIRECT_QUESTION", "commercial parameter tied to the authority matrix: documented preference is a suitability question to the owning unit", [r for r in (r_question,) if r]
                proposed = "هل الحدود الواردة في هذا البند مناسبة من وجهة نظر الوحدة المختصة؟"
            elif _has(text, _APPRAISAL):
                rec, why, rules_used = "REVISE", "the drafter's own legal/Sharia appraisal is removed; the fact and the referral to the competent body stay", [r for r in (r_appraisal,) if r]
            elif anchor is None and c.get("quote"):
                rec, ground, why, rules_used = "REQUEST_EVIDENCE", "MAT-W05", "the quoted passage is not found in the document text", ["MAT-W05"] if "MAT-W05" in rules else []
            elif r_money and _has(text, ("حساب", "رسم", "حصيله", "اموال", "مبلغ")):
                rules_used, why = [r_money], "money-flow control: documented preference is to keep it"
            kept, uses, _ = self._rule_checks(rules_used)
            out.append({"observation_id": oid, "should_be_formal_observation": rec not in ("PROPOSE_WITHDRAWAL",), "material": rec != "PROPOSE_WITHDRAWAL",
                        "within_gco_jurisdiction": "UNCERTAIN", "evidence_sufficient": anchor is not None or not c.get("quote"),
                        "covered_elsewhere_by": dup, "contradicts": [], "recommendation": rec, "framing": framing, "proposed_text": proposed,
                        "rationale": why, "dna_rules_invoked": kept,
                        "dna_rule_applicability": [{"rule_id": u["rule_id"], "applicable": u["use"] != "NOT_ESTABLISHED", "reason": f"use={u['use']}, {u['classification']}, {u['confidence']}"} for u in uses],
                        "withdrawal_ground": ground if rec in ("PROPOSE_WITHDRAWAL", "MERGE", "REQUEST_EVIDENCE") else None,
                        "proportionate_and_implementable": rec != "SOFTEN", "evidence_refs": [anchor.id] if anchor else [], "confidence": 0.3})
        return {"assessments": out, "reasoning_summary": "rule-based fallback over documented markers (formal, sanction, authority+number, appraisal, regulatory, duplicate remedy); not a reviewer judgment"}

    def _guard_drafting(self, out: dict, candidates: list[dict], registry: EvidenceRegistry) -> tuple[dict, list[str]]:
        guards: list[str] = []
        texts = {c["observation_id"]: plain_text(c.get("comment") or "") for c in candidates}
        seen = set()
        for a in out.get("assessments", []):
            seen.add(a["observation_id"])
            a["candidate_preserved"], a["restorable_by_human"] = True, True
            a["proposed_text"], n = strip_person_references(a.get("proposed_text"))
            a["rationale"], m = strip_person_references(a.get("rationale"))
            if n or m:
                guards.append("PERSON_REFERENCE_REMOVED")
            kept, uses, unknown = self._rule_checks(a.get("dna_rules_invoked", []))
            if unknown:
                guards.append("UNKNOWN_RULE_DROPPED"); a["dna_rules_invoked"] = kept
            a["dna_rule_use"] = uses
            proposed_removal = a["recommendation"] in ("PROPOSE_WITHDRAWAL", "MERGE")
            if proposed_removal and is_regulatory_safeguard(texts.get(a["observation_id"], "")):
                a["recommendation"], a["withdrawal_ground"] = "ESCALATE", None; guards.append("REGULATORY_SAFEGUARD_GUARD")
            if proposed_removal and any(u["use"] == "NOT_ESTABLISHED" for u in uses):
                guards.append("NOT_ESTABLISHED_RULE_CANNOT_SUPPORT_WITHDRAWAL")
                if a["recommendation"] != "ESCALATE":
                    a["recommendation"], a["withdrawal_ground"] = "ESCALATE", None
            if a["recommendation"] == "PROPOSE_WITHDRAWAL" and not a.get("withdrawal_ground"):
                a["withdrawal_ground"] = "MAT-W15"; guards.append("WITHDRAWAL_GROUND_DEFAULTED_TO_W15")
            good, bad = _admissible(registry, a.get("evidence_refs"))
            a["evidence_refs"] = good
            if bad:
                guards.append("HALLUCINATED_REFS_DROPPED")
            if a.get("withdrawal_ground"):
                a["withdrawal_ground_label"] = GROUND_LABELS.get(a["withdrawal_ground"])
                a["withdrawal_ground_use"] = self.profile.rule_status(a["withdrawal_ground"])["use"]
        missing = [c["observation_id"] for c in candidates if c["observation_id"] not in seen]
        for oid in missing:
            guards.append("CANDIDATE_NOT_ASSESSED")
            out.setdefault("assessments", []).append({"observation_id": oid, "recommendation": "ESCALATE", "framing": "DIRECT_RECOMMENDATION",
                                                      "rationale": "the advisor returned no assessment for this candidate", "dna_rules_invoked": [],
                                                      "dna_rule_applicability": [], "dna_rule_use": [], "withdrawal_ground": None, "proposed_text": None,
                                                      "evidence_refs": [], "candidate_preserved": True, "restorable_by_human": True, "confidence": 0.0})
        return out, sorted(set(guards))

    # -------------------------------------------------------------- MAT-02 interrogation
    def interrogate(self, state: ReviewState, obs: Observation, objection: CH.Objection, registry: EvidenceRegistry, persona: RecipientPersona,
                    *, prior_advice: dict | None, prior_turns: list[dict] | None = None, issued: bool = False) -> MatResult:
        questions = QUESTIONS_BY_KIND.get(objection.kind, ["IQ01", "IQ02", "IQ12"])
        ev_ids = sorted(set(CB.bind_observation_evidence(registry, obs, persona)) | set(objection.evidence_refs))
        disclosure = {"prior_drafting_involvement": prior_advice is not None, "prior_advice": prior_advice,
                      "note": "the advisor is a participant, not a neutral adjudicator"}
        payload = {"label": CB._label(state), "stage": STAGE_INTERROGATION, "profile": self.profile.view(), "recipient": CB._persona(persona),
                   "observation": CB._observation(obs, issued=issued), "disclosure": disclosure,
                   "objection": {"challenge_id": objection.challenge_id, "objection_kind": objection.kind, "proposition": objection.proposition,
                                 "material_consequence": objection.material_consequence, "evidence_refs": list(objection.evidence_refs),
                                 "existing_controls": objection.detail.get("existing_controls", []),
                                 "requested_correction": objection.detail.get("requested_correction")},
                   "interrogation_questions": [{"id": q, "question": INTERROGATION_QUESTIONS[q]} for q in questions],
                   "prior_advisory_turns": list(prior_turns or []), "evidence": CB._evidence_items(registry, ev_ids),
                   "evidence_verification": {eid: {"authority_verified": bool(v.get("authority_verified")), "approval_status": v.get("approval_status")}
                                             for eid, v in registry.verifications(ev_ids).items()},
                   "context_isolation": "no advocate or adjudicator material; the advisor's own drafting advice is disclosed"}
        if self.live:
            resp = self._invoke(STAGE_INTERROGATION, payload, observation_id=obs.internal_id, challenge_id=objection.challenge_id)
            if resp.ok:
                out, guards = self._guard_debate(dict(resp.output), registry, objection, stage=STAGE_INTERROGATION)
                return MatResult(STAGE_INTERROGATION, out, RoleOutcome(ROLE_MAT, resp.mode, resp.status, resp, out, notes=[f"guard:{g}" for g in guards]), guards, self.profile.binding())
            return MatResult(STAGE_INTERROGATION, None, RoleOutcome(ROLE_MAT, resp.mode, resp.status, resp, notes=[resp.error or ""]), [], self.profile.binding())
        out = self._rule_based_interrogation(obs, objection, registry, questions, prior_advice)
        out, guards = self._guard_debate(out, registry, objection, stage=STAGE_INTERROGATION)
        return MatResult(STAGE_INTERROGATION, out, RoleOutcome(ROLE_MAT, MODE_DETERMINISTIC, STATUS_OK, None, out,
                                                                notes=["rule-based fallback: not the reviewer's judgment"] + [f"guard:{g}" for g in guards]), guards, self.profile.binding())

    def _rule_based_interrogation(self, obs: Observation, objection: CH.Objection, registry: EvidenceRegistry, questions: list[str], prior_advice: dict | None) -> dict:
        text = plain_text(obs.comment)
        verified = [r for r in objection.evidence_refs if registry.has(r) and registry.resolve(r).authority_verified]
        anchor = registry.bind_clause(obs.quote)
        own = [anchor.id] if anchor else []
        kind = objection.kind
        if kind in CH._AUTHORITY_KINDS:
            decision, why = "REQUEST_ADDITIONAL_EVIDENCE", "an authority claim needs an approved non-document source; none is bound to this observation"
            if kind == "UNSUPPORTED_BREACH_CLAIM":
                decision, why = "REVISE_RECOMMENDATION", "the breach wording is replaced by the control objective (documented preference: no accusatory wording)"
        elif kind == "DUPLICATE_REMEDY":
            decision, why = "MERGE_OBSERVATIONS", "the same remedy is requested elsewhere"
        elif kind in ("OUTSIDE_RECIPIENT_MANDATE", "CONTESTED_OWNERSHIP"):
            decision, why = "NARROW_SCOPE", "narrow to what the recipient owns; route the rest"
        elif kind == "CLAUSE_NOT_FOUND":
            decision, why = ("DEFEND_WITH_EVIDENCE", "the quoted passage is anchored in the document text") if anchor else ("ACCEPT_OBJECTION", "the passage is not in the document text")
        elif kind == "RESERVED_DECISION":
            decision, why = "ESCALATE_TO_HUMAN", "reserved matter"
        elif kind in ("UNCLEAR_ACTION", "VERBOSE"):
            decision, why = "REVISE_RECOMMENDATION", "state the single requested action in the documented short form"
        else:
            decision, why = "ESCALATE_TO_HUMAN", "no documented rule covers this objection"
        if objection.detail.get("existing_controls") and decision == "DEFEND_WITH_EVIDENCE":
            decision, why = "ACCEPT_OBJECTION", "an existing control is named by the objection and nothing in the evidence rebuts it"
        proposed = None
        if decision == "REVISE_RECOMMENDATION":
            proposed = CH.recommendation_part(text) or text
            proposed = _drop_sanction(proposed)
        return {"challenge_id": objection.challenge_id, "observation_id": obs.internal_id, "original_position": text[:600],
                "black_team_objection": objection.proposition[:600], "accepted_facts": [], "disputed_facts": [],
                "verified_evidence": sorted(set(verified) | set(own)), "unverified_assumptions": ["rule-based fallback: no reasoning beyond the documented markers"],
                "mat_dna_rules_invoked": [], "mat_dna_rule_applicability": [], "response": f"[{', '.join(questions)}] {why}",
                "decision": decision, "revised_position": why[:600], "proposed_wording": proposed,
                "withdrawal_recommendation": False, "withdrawal_ground": None, "confidence": 0.3,
                "escalation_required": decision == "ESCALATE_TO_HUMAN", "new_argument": True}

    # -------------------------------------------------------------- MAT-03 reassessment (fresh context)
    def reassess(self, state: ReviewState, obs: Observation, objection: CH.Objection, registry: EvidenceRegistry, *,
                 interrogation: dict | None, advocate: dict, exchange: list[dict] | None = None, issued: bool = False) -> MatResult:
        ev_ids = sorted(set(objection.evidence_refs) | set(advocate.get("evidence_refs") or []) | set((interrogation or {}).get("verified_evidence") or []))
        payload = {"label": CB._label(state), "stage": STAGE_REASSESSMENT, "profile": self.profile.view(),
                   "observation": CB._observation(obs, issued=issued),
                   "objection": {"challenge_id": objection.challenge_id, "objection_kind": objection.kind, "proposition": objection.proposition,
                                 "material_consequence": objection.material_consequence, "evidence_refs": list(objection.evidence_refs)},
                   "own_interrogation_response": {k: (interrogation or {}).get(k) for k in ("decision", "response", "verified_evidence", "proposed_wording", "withdrawal_recommendation")},
                   "red_advocate_response": {k: advocate.get(k) for k in ("stance", "reasoning", "evidence_refs", "revised_comment", "revised_quote", "route_to", "missing_evidence")},
                   "exchange": list(exchange or []), "evidence": CB._evidence_items(registry, ev_ids),
                   "evidence_verification": {eid: {"authority_verified": bool(v.get("authority_verified")), "approval_status": v.get("approval_status")}
                                             for eid, v in registry.verifications(ev_ids).items()},
                   "context_isolation": "fresh context: no adjudicator material; drafting advice withheld"}
        if self.live:
            resp = self._invoke(STAGE_REASSESSMENT, payload, observation_id=obs.internal_id, challenge_id=objection.challenge_id)
            if resp.ok:
                out, guards = self._guard_debate(dict(resp.output), registry, objection, stage=STAGE_REASSESSMENT, interrogation=interrogation)
                return MatResult(STAGE_REASSESSMENT, out, RoleOutcome(ROLE_MAT, resp.mode, resp.status, resp, out, notes=[f"guard:{g}" for g in guards]), guards, self.profile.binding())
            return MatResult(STAGE_REASSESSMENT, None, RoleOutcome(ROLE_MAT, resp.mode, resp.status, resp, notes=[resp.error or ""]), [], self.profile.binding())
        out = self._rule_based_reassessment(obs, objection, registry, interrogation, advocate)
        out, guards = self._guard_debate(out, registry, objection, stage=STAGE_REASSESSMENT, interrogation=interrogation)
        return MatResult(STAGE_REASSESSMENT, out, RoleOutcome(ROLE_MAT, MODE_DETERMINISTIC, STATUS_OK, None, out,
                                                               notes=["rule-based fallback: not the reviewer's judgment"] + [f"guard:{g}" for g in guards]), guards, self.profile.binding())

    def _rule_based_reassessment(self, obs: Observation, objection: CH.Objection, registry: EvidenceRegistry, interrogation: dict | None, advocate: dict) -> dict:
        prev = (interrogation or {}).get("decision")
        stance = advocate.get("stance")
        adv_refs = [r for r in (advocate.get("evidence_refs") or []) if registry.has(r)]
        new_refs = sorted(set(adv_refs) - set((interrogation or {}).get("verified_evidence") or []))
        if stance == "CONCEDE":
            decision, genuine, addressed, why = "ACCEPT_OBJECTION", True, False, "the advocate conceded; nothing in the evidence rebuts the objection"
        elif stance == "REVISE":
            decision, genuine, addressed, why = "REVISE_RECOMMENDATION", True, True, "the advocate's revised text answers the objection"
        elif stance == "DEFEND" and adv_refs:
            decision, genuine, addressed, why = "DEFEND_WITH_EVIDENCE", False, True, "the advocate's defence is supported by admissible evidence"
        else:
            decision, genuine, addressed, why = "REQUEST_ADDITIONAL_EVIDENCE", True, False, "a defence without admissible evidence does not resolve the objection"
        changed = prev is not None and prev != decision
        reason = ("new admissible evidence " + ", ".join(new_refs) if new_refs and changed else ("position revised in the light of the independent analysis" if changed else ""))
        return {"challenge_id": objection.challenge_id, "previous_reasoning_valid": not changed, "black_team_identified_genuine_deficiency": genuine,
                "red_advocate_addressed_deficiency": addressed, "revised_comment_necessary": decision == "REVISE_RECOMMENDATION",
                "decision": decision, "final_advisory_position": why, "proposed_wording": advocate.get("revised_comment") if decision == "REVISE_RECOMMENDATION" else None,
                "withdrawal_recommendation": False, "withdrawal_ground": None, "new_evidence_required": [] if decision != "REQUEST_ADDITIONAL_EVIDENCE" else ["approved source for the claimed requirement"],
                "position_changed": changed, "change_reason": reason, "evidence_refs": adv_refs, "confidence": 0.3}

    def _guard_debate(self, out: dict, registry: EvidenceRegistry, objection: CH.Objection, *, stage: str, interrogation: dict | None = None) -> tuple[dict, list[str]]:
        guards: list[str] = []
        for key in ("response", "revised_position", "proposed_wording", "final_advisory_position", "change_reason"):
            if key in out:
                out[key], n = strip_person_references(out[key])
                if n:
                    guards.append("PERSON_REFERENCE_REMOVED")
        refs_key = "verified_evidence" if stage == STAGE_INTERROGATION else "evidence_refs"
        good, bad = _admissible(registry, out.get(refs_key))
        verified = [r for r in good if registry.resolve(r).authority_verified]
        out[refs_key] = good
        if bad:
            guards.append("HALLUCINATED_REFS_DROPPED")
        if out.get("decision") == "DEFEND_WITH_EVIDENCE" and not verified:
            out["decision"] = "REQUEST_ADDITIONAL_EVIDENCE"; guards.append("UNSUPPORTED_DEFENCE_DOWNGRADED")
        if out.get("decision") in ("REVISE_RECOMMENDATION", "CONVERT_TO_QUESTION") and not out.get("proposed_wording"):
            out["decision"] = "REQUEST_ADDITIONAL_EVIDENCE"; guards.append("REVISION_WITHOUT_TEXT")
        if out.get("decision") == "PROPOSE_WITHDRAWAL":
            out["withdrawal_recommendation"] = True
            if not out.get("withdrawal_ground"):
                out["withdrawal_ground"] = "MAT-W15"; guards.append("WITHDRAWAL_GROUND_DEFAULTED_TO_W15")
            if is_regulatory_safeguard(objection.proposition) or is_regulatory_safeguard(out.get("original_position") or ""):
                out["decision"], out["withdrawal_recommendation"], out["withdrawal_ground"] = "ESCALATE_TO_HUMAN", False, None
                guards.append("REGULATORY_SAFEGUARD_GUARD")
        if stage == STAGE_INTERROGATION:
            kept, uses, unknown = self._rule_checks(out.get("mat_dna_rules_invoked", []))
            out["mat_dna_rules_invoked"], out["mat_dna_rule_use"] = kept, uses
            if unknown:
                guards.append("UNKNOWN_RULE_DROPPED")
        if stage == STAGE_REASSESSMENT and interrogation is not None:
            # a reversal is recorded, never penalised; an unexplained reversal is flagged for the record only
            if out.get("position_changed") and not (out.get("change_reason") or "").strip():
                out["change_reason"] = "position changed without a stated reason"; guards.append("REVERSAL_WITHOUT_REASON")
            if interrogation.get("decision") != out.get("decision") and not out.get("position_changed"):
                out["position_changed"] = True; guards.append("POSITION_CHANGE_RECORDED")
        out["advisory_only"] = True
        out["binding_disposition"] = None          # the advisor never issues a disposition
        return out, sorted(set(guards))


def _drop_sanction(text: str) -> str:
    """Remove a trailing sanction / liability clause from a proposed text (deterministic, conservative)."""
    parts = re.split(r"[،,؛;]\s*(?=(?:ويُعد|ويعد|ويكون البنك مسؤولاً|ولا يستحق|ويتحمل))", text)
    return parts[0].rstrip(" .،") + "." if len(parts) > 1 else text


def candidate_from_observation(obs: Observation, *, origin: str = "GCO_REGISTER") -> dict:
    return {"observation_id": obs.internal_id, "origin": origin, "location": plain_text(obs.location), "quote": plain_text(obs.quote),
            "comment": plain_text(obs.comment), "title": obs.title}


def candidate_from_proposal(p: dict, n: int) -> dict:
    comment = (p.get("finding") or "") + ("\nالتوصية: " + p["recommendation"] if p.get("recommendation") else "")
    return {"observation_id": f"PROP-{n:03d}", "origin": "DRAFTING_AGENT", "location": p.get("location"), "quote": p.get("quote"),
            "comment": comment, "title": None}


# ------------------------------------------------------------------ Article 15 audit state
@dataclass
class MatObservationState:
    Observation_ID: str
    Review_Round: int
    Original_GCO_Text: str
    Original_GCO_Text_SHA256: str
    MAT_DNA_Profile_Version: str
    MAT_Drafting_Recommendation: str | None = None
    MAT_Proposed_Text: str | None = None
    MAT_DNA_Rules_Used: list[str] = field(default_factory=list)
    MAT_Drafting_Execution_ID: str | None = None
    Black_Team_Challenge_ID: list[str] = field(default_factory=list)
    MAT_Interrogation_Execution_ID: list[str] = field(default_factory=list)
    MAT_Interrogation_Response: list[dict] = field(default_factory=list)
    Red_Advocate_Execution_ID: list[str] = field(default_factory=list)
    MAT_Reassessment_Execution_ID: list[str] = field(default_factory=list)
    MAT_Final_Advisory_Position: list[dict] = field(default_factory=list)
    Adjudicator_Execution_ID: list[str] = field(default_factory=list)
    Human_Decision: list[dict] = field(default_factory=list)
    Final_Observation_State: str = "CANDIDATE_PRESERVED"
    transitions: list[dict] = field(default_factory=list)

    def transition(self, stage: str, detail: str, *, execution_id: str | None = None, at: str = "") -> None:
        self.transitions.append({"seq": len(self.transitions) + 1, "stage": stage, "detail": detail, "execution_id": execution_id, "at": at})

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
