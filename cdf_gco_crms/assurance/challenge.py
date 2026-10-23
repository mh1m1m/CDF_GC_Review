"""Institutional challenge workflow (Art. 19A; gates G-ADV-01..13; patch register V712-037..046).

Three roles argue every drafted observation from evidence bound in an
:class:`~.evidence.EvidenceRegistry`:

* :func:`black_team` objects as the recipient department would
  (:class:`~.personas.RecipientPersona`), on the admitted grounds of 19A.4
  that this runtime can test by rule: clause not found, authority mismatch
  or unsupported, outside the recipient's mandate, unsupported breach claim,
  duplicate remedy (07.5), unclear action (R4 of 20.3), verbosity (Art. 07)
  and reserved decisions (14.4, 17.7). Zero objections is a valid, recorded
  result (decision 61);
* :func:`red_advocate` answers each objection with CONCEDE, DEFEND or REVISE,
  never defending without an evidence id (G-ADV-11);
* :func:`adjudicate` proposes exactly one disposition of 19A.6 from the
  admissible evidence only; it ignores any "expected" label and escalates
  every reserved matter to the GCO reviewer.

:func:`run_challenge` drives the six-productive-cycle loop of 19A.5 on the
hash-chained :class:`~.objection_engine.Objection` of the objection engine
and returns a :class:`ChallengeRecord`. :func:`apply_human_decisions` clears
a blocker only on a verified :class:`~.objection_engine.HumanDecision`;
:func:`confidentiality_scan` checks that nothing of the record reached a
requester-facing file (19A.9); :func:`held_out_cases` and
:func:`evaluate_held_out` give the synthetic regression set.

Independence, stated honestly (decision 6, 56; G-ADV-13): everything here
runs as rules in one process. No live model adjudicates and no isolated
agent instances exist, so ``independence`` is SINGLE_PROCESS_RULE_BASED and
``role_isolation`` is NOT_VERIFIED, never PASS. Synthetic cases are labelled
as such and never stand for the reference case of 00.8.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from ..model.entities import GText, Observation, ReviewState, plain_text
from ..references.authority_matrix import BODIES, ROLE_APPROVE
from ..references.textnorm import match_key, nfc
from .evidence import EvidenceItem, EvidenceRegistry, ID_PATTERN, content_words
from .objection_engine import MAX_CYCLES, OUTCOMES, HumanDecision, Objection as _EngineObjection, canon
from .personas import MATRIX_CAVEAT, OWNER_FALLBACK, RecipientPersona, matrix_citation, org_citation

# ------------------------------------------------------------------ constants
DISPOSITIONS = ("UPHELD_UNCHANGED", "UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE", "ROUTED_OUTSIDE_GCO",
                "WITHHELD_FOR_EVIDENCE", "ESCALATED_TO_GCO_REVIEWER")
assert set(DISPOSITIONS) == OUTCOMES
BLOCKING = ("WITHHELD_FOR_EVIDENCE", "ESCALATED_TO_GCO_REVIEWER")
STANCES = ("CONCEDE", "DEFEND", "REVISE")
KINDS = ("CLAUSE_NOT_FOUND", "AUTHORITY_MISMATCH", "AUTHORITY_UNSUPPORTED", "OUTSIDE_RECIPIENT_MANDATE",
         "CONTESTED_OWNERSHIP", "UNSUPPORTED_BREACH_CLAIM", "DUPLICATE_REMEDY", "UNCLEAR_ACTION", "VERBOSE",
         "RESERVED_DECISION")
RESERVED_MATTERS = ("STATUS_CHANGE_OF_ISSUED", "TITLE_APPROVAL", "WITHDRAWAL", "ISSUED_OBSERVATION")
INDEPENDENCE = "SINGLE_PROCESS_RULE_BASED"
ROLE_ISOLATION = "NOT_VERIFIED"
WORD_BUDGET = 120                      # engineering threshold on the whole comment body (Art. 07 ceilings are lower)
ACTION_LABELS = ("التوصية:", "المطلوب:")
RECORD_SCHEMA = "CDF-ADV-RECORD-v7.12"
MANDATE_OWN = 0.34                     # recipient task overlap at or above this: the recipient owns the task
MANDATE_OTHER = 0.5                    # another sector's task overlap at or above this: another unit owns it
MIN_MANDATE_WORDS = 3                  # shorter requested actions carry too little content for a mandate check
MOCK_NOTE = ("mock_vs_live: every result here comes from deterministic rules in one process on synthetic cases; "
             "no live agent, model or isolated instance was run (independence SINGLE_PROCESS_RULE_BASED, "
             "role isolation NOT_VERIFIED).")

_LABEL_RE = re.compile(r"(الملاحظة #\d+|متابعة الملاحظة #\d+|REF:[^\n]*|التوصية:|النص المقترح:|المطلوب:|شرط الإغلاق:|بالنص الآتي:)")
_DIACRITICS = re.compile("[ً-ْٰـ]")
_WORD = re.compile(r"[\w]+", re.UNICODE)
_ACTION_VERBS = ("نوصي", "نأمل", "نقترح", "نرجو", "نؤكد", "يُستبدل", "يستبدل", "يُحذف", "يحذف", "تُضاف", "تضاف",
                 "يُضاف", "يضاف", "يُعدل", "يُعدّل", "يُستكمل", "يُربط", "يوجد خطأ")
_APPROVAL_VERBS = ("يعتمد", "تعتمد", "يعتمدها", "تعتمدها", "اعتماد", "باعتماد", "يوافق", "توافق", "الموافقة",
                   "بموافقة", "يقر", "تقر", "إقرار", "يبت", "البت", "صلاحية", "من اختصاص", "يختص", "تختص")
_BREACH = ("يخالف", "تخالف", "مخالف", "مخالفة", "بالمخالفة", "خلافاً", "باطل", "باطلة", "يُبطل", "يبطل",
           "غير نافذ", "غير نافذة", "لا يجوز نظاماً", "يتعارض مع نظام", "يتعارض مع المادة", "مخالفاً")
_RISK_WORDING = (("بالمخالفة لـ", "على نحو قد لا يتسق مع"), ("بالمخالفة", "على نحو قد لا يتسق مع"),
                 ("يخالف", "قد لا يتسق مع"), ("تخالف", "قد لا تتسق مع"), ("مخالفاً", "على نحو قد لا يتسق مع"),
                 ("مخالفة", "عدم اتساق محتمل مع"), ("مخالف", "قد لا يتسق مع"), ("يُبطل", "قد يؤثر في نفاذ"),
                 ("يبطل", "قد يؤثر في نفاذ"), ("باطلة", "محل خطر على النفاذ"), ("باطل", "محل خطر على النفاذ"),
                 ("غير نافذة", "محل خطر على النفاذ"), ("غير نافذ", "محل خطر على النفاذ"),
                 ("لا يجوز نظاماً", "قد لا يتسق مع المتطلبات النظامية"), ("خلافاً", "على نحو قد لا يتسق مع"))
_STATUS_CHANGE = ("سُحبت الملاحظة", "تُسحب الملاحظة", "سحب الملاحظة", "تُغلق الملاحظة", "إغلاق الملاحظة",
                  "تغيير حالة الملاحظة", "تعديل حالة الملاحظة", "تُعد الملاحظة مغلقة", "تعتبر الملاحظة مغلقة",
                  "نعدل عن", "تراجعاً عن", "خلافاً لطلبنا", "تُلغى الملاحظة", "إلغاء الملاحظة")
_WITHDRAW = ("سُحبت الملاحظة", "تُسحب الملاحظة", "سحب الملاحظة", "تُلغى الملاحظة", "إلغاء الملاحظة", "نعدل عن", "تراجعاً عن")


# --------------------------------------------------------------- text helpers
def word_count(text: str) -> int:
    """Art. 07.7: words after removing diacritics, tatweel and the fixed labels."""
    t = _LABEL_RE.sub(" ", plain_text(text))
    t = _DIACRITICS.sub("", t)
    return len(_WORD.findall(t))


def recommendation_part(text: str) -> str:
    """The requested action: the text after the first action label, else the whole text."""
    t = plain_text(text)
    for label in ACTION_LABELS:
        if label in t:
            return t.split(label, 1)[1].strip()
    return t.strip()


def has_action_label(text: str) -> bool:
    return any(label in plain_text(text) for label in ACTION_LABELS)


def states_requested_action(text: str) -> tuple[bool, str]:
    """R4 of 20.3 by rule: a labelled action, a GCO action verb (07.3), an F5 substitution or a question."""
    t = plain_text(text)
    if has_action_label(t):
        return True, "ACTION_LABEL"
    if re.search(r"هل\s.+؟", t) or re.search(r"\bما هو\b.+؟", t):
        return True, "QUESTION_F6"
    if any(v in t for v in _ACTION_VERBS):
        return True, "ACTION_VERB"
    return False, "NONE"


def asserted_approver(text: str) -> tuple[str | None, str | None]:
    """(canonical matrix body, verb) when the text asserts who approves or decides; (None, None) otherwise.

    The requested action is read first (the body GCO asks for), the whole
    comment only when the action names no body.
    """
    whole = nfc(plain_text(text))
    for part in (nfc(recommendation_part(text)), whole):
        verb = next((v for v in _APPROVAL_VERBS if v in part), None)
        if verb is None:
            continue
        key = match_key(part)
        for body in sorted(BODIES, key=len, reverse=True):
            if match_key(body) in key:
                return body, verb
    verb = next((v for v in _APPROVAL_VERBS if v in whole), None)
    return None, verb


_CITED_ITEM = re.compile(r"مصفوفة الصلاحيات[^()\n]*?البند\s*\(?\s*(\d+(?:\.\d+)?)\s*\)?")
_CITATION = re.compile(r"\(?مصفوفة الصلاحيات الرئيسية[^()]*\)?")


def cited_matrix_item(text: str) -> str | None:
    """The matrix item number the comment itself cites in the 05.6 form, if any."""
    m = _CITED_ITEM.search(nfc(plain_text(text)))
    return m.group(1) if m else None


def strip_citation(text: str) -> str:
    """The comment without its matrix citation, so that the citation never passes for the matter."""
    return _CITATION.sub(" ", nfc(plain_text(text)))


def breach_claim(text: str) -> str | None:
    t = nfc(plain_text(text))
    return next((b for b in _BREACH if b in t), None)


def status_change_claim(text: str) -> str | None:
    t = nfc(plain_text(text))
    return next((p for p in _STATUS_CHANGE if p in t), None)


def four_grams(text: str) -> set[tuple[str, ...]]:
    words = [match_key(w) for w in nfc(recommendation_part(text)).split()]
    words = [w for w in words if w]
    return {tuple(words[i:i + 4]) for i in range(len(words) - 3)} if len(words) >= 4 else {tuple(words)}


def remedy_overlap(a: str, b: str) -> float:
    """P11: share of 4-word sequences of the shorter remedy that occur in the other."""
    ga, gb = four_grams(a), four_grams(b)
    if not ga or not gb:
        return 0.0
    small, large = (ga, gb) if len(ga) <= len(gb) else (gb, ga)
    return len(small & large) / len(small)


def _gtext(text: str) -> GText:
    """GText with the action label in bold where it opens a sentence (10.3 E)."""
    segs: list = []
    rest = text
    for label in ACTION_LABELS:
        if label in rest:
            before, after = rest.split(label, 1)
            if before:
                segs.append((before, False))
            segs.append((label, True))
            rest = after
            break
    segs.append((rest, False))
    return GText(segs)


def _body_in_text(text: str) -> str | None:
    key = match_key(plain_text(text))
    for body in sorted(BODIES, key=len, reverse=True):
        if match_key(body) in key:
            return body
    return None


# ------------------------------------------------------------------ records
@dataclass
class Objection(_EngineObjection):
    """An engine objection with the rule that raised it (``category``) and its structured detail."""
    material_consequence: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.category


@dataclass
class Advocacy:
    """The advocate's answer to one objection: CONCEDE, DEFEND (evidence mandatory) or REVISE (text given)."""
    challenge_id: str
    stance: str
    reasoning: str
    evidence_refs: list[str] = field(default_factory=list)
    revised_comment: Optional[GText] = None
    revised_quote: Optional[str] = None
    route_to: Optional[str] = None

    def __post_init__(self):
        if self.stance not in STANCES:
            raise ValueError(f"Unknown stance {self.stance!r}")
        self.evidence_refs = sorted(set(self.evidence_refs))
        if self.stance == "DEFEND" and not self.evidence_refs:
            raise ValueError("A defence without an evidence id is not a defence (G-ADV-11)")
        if self.stance == "REVISE" and self.revised_comment is None and self.revised_quote is None:
            raise ValueError("A revision must carry the revised text")
        if not canon(self.reasoning):
            raise ValueError("Empty reasoning")

    def to_dict(self) -> dict:
        return {"challenge_id": self.challenge_id, "stance": self.stance, "reasoning": self.reasoning,
                "evidence_refs": list(self.evidence_refs),
                "revised_comment": self.revised_comment.text if self.revised_comment else None,
                "revised_quote": self.revised_quote, "route_to": self.route_to}


@dataclass
class Adjudication:
    """Exactly one disposition of 19A.6, with the rationale and the evidence ids relied on."""
    challenge_id: str
    disposition: str
    rationale: str
    evidence_refs: list[str] = field(default_factory=list)
    inadmissible_refs: list[str] = field(default_factory=list)
    reserved_matter: Optional[str] = None
    open_question: Optional[str] = None
    engine_recorded: bool = False

    def __post_init__(self):
        if self.disposition not in DISPOSITIONS:
            raise ValueError(f"Unknown disposition {self.disposition!r}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ObjectionRecord:
    challenge_id: str
    kind: str
    proposition: str
    material_consequence: str
    evidence_refs: list[str]
    events: list[dict]
    cycles: int
    advocacy: dict
    adjudication: dict
    engine_state: str
    chain_ok: bool
    human_decision: Optional[dict] = None
    resolved_by_human: bool = False

    @property
    def disposition(self) -> str:
        return self.adjudication["disposition"]

    def blocking(self) -> bool:
        return self.disposition in BLOCKING and not self.resolved_by_human


@dataclass
class ObservationEntry:
    internal_id: str
    reader_no: str
    issued: bool
    objections: list[ObjectionRecord]
    scan_scope: dict

    @property
    def no_objection(self) -> bool:
        return not self.objections


@dataclass
class ChallengeRecord:
    """Per-observation challenge results for one review state (internal register; never owner-facing)."""
    document_code: str
    round: int
    persona: dict
    entries: list[ObservationEntry]
    evidence: dict
    max_cycles: int
    independence: str = INDEPENDENCE
    role_isolation: str = ROLE_ISOLATION
    isolation_statement: str = ("Roles BLACK, RED_ADVOCATE and ADJUDICATOR ran in sequence as rules in one process; "
                                "no instance identifiers exist; G-ADV-13 is NOT_VERIFIED (19A.2).")
    human_decisions: list[dict] = field(default_factory=list)
    _objections: dict[str, Objection] = field(default_factory=dict, repr=False)

    # --------------------------------------------------------- derived
    @property
    def dispositions(self) -> dict[str, int]:
        c = Counter(o.disposition for e in self.entries for o in e.objections)
        return {d: c.get(d, 0) for d in DISPOSITIONS}

    @property
    def cycles_used(self) -> int:
        return sum(o.cycles for e in self.entries for o in e.objections)

    @property
    def chain_hash(self) -> str:
        hashes = [ev["event_hash"] for e in self.entries for o in e.objections for ev in o.events]
        return hashlib.sha256("|".join(hashes).encode()).hexdigest()

    def verify_chains(self) -> bool:
        return all(o.verify_chain() for o in self._objections.values())

    def blockers(self) -> list[dict]:
        """Observations held by WITHHELD_FOR_EVIDENCE or ESCALATED_TO_GCO_REVIEWER without a verified decision."""
        out = []
        for e in self.entries:
            for o in e.objections:
                if o.blocking():
                    out.append({"internal_id": e.internal_id, "challenge_id": o.challenge_id, "kind": o.kind,
                                "disposition": o.disposition, "open_question": o.adjudication.get("open_question")})
        return out

    def objection(self, challenge_id: str) -> Objection:
        return self._objections[challenge_id]

    def to_dict(self) -> dict:
        return {"schema": RECORD_SCHEMA, "document_code": self.document_code, "round": self.round,
                "independence": self.independence, "role_isolation": self.role_isolation,
                "isolation_statement": self.isolation_statement, "max_cycles": self.max_cycles,
                "cycles_used": self.cycles_used, "dispositions": self.dispositions,
                "chain_hash": self.chain_hash, "chains_verified": self.verify_chains(),
                "persona": self.persona, "entries": [self._entry_dict(e) for e in self.entries],
                "blockers": self.blockers(), "human_decisions": list(self.human_decisions),
                "evidence": self.evidence, "synthetic_note": "Synthetic inputs are labelled; they never stand for "
                                                              "the reference case of 00.8 (19A.8)."}

    @staticmethod
    def _entry_dict(e: ObservationEntry) -> dict:
        return {"internal_id": e.internal_id, "reader_no": e.reader_no, "issued": e.issued,
                "no_objection": e.no_objection, "scan_scope": e.scan_scope,
                "objections": [asdict(o) for o in e.objections]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)


# --------------------------------------------------------------- black team
def _anchor(observation: Observation, registry: EvidenceRegistry) -> EvidenceItem | None:
    return registry.bind_clause(observation.quote)


def _make(observation: Observation, persona: RecipientPersona, kind: str, proposition: str, consequence: str,
          refs: Iterable[str], detail: dict | None = None, *, issued: bool) -> Objection:
    return Objection(observation.internal_id, kind, proposition, persona.addressee, issued=issued,
                     evidence_refs=sorted(set(refs)), material_consequence=consequence, detail=detail or {})


def black_team(observation: Observation, registry: EvidenceRegistry, persona: RecipientPersona, *,
               siblings: Iterable[Observation] = (), issued: bool | None = None,
               matter: str | None = None) -> list[Objection]:
    """Rule-based recipient challenge of one drafted observation; an empty list is a valid result.

    Every objection names its evidence and its material consequence (G-ADV-01).
    ``siblings`` are the other observations of the same document (07.5);
    ``issued`` says the observation was issued in an earlier round (17.7);
    ``matter`` overrides the matrix matter detection for the authority check.
    """
    issued = bool(getattr(observation, "issued", False)) if issued is None else bool(issued)
    comment = plain_text(observation.comment)
    out: list[Objection] = []
    anchor = _anchor(observation, registry)
    anchor_refs = [anchor.id] if anchor else []
    scope = _scan_scope(registry, persona)

    # (8) reserved decisions first: they end the argument wherever they appear (14.4, 17.7, decision 22)
    change = status_change_claim(comment)
    if issued and change:
        reserved = "WITHDRAWAL" if change in _WITHDRAW else "STATUS_CHANGE_OF_ISSUED"
        out.append(_make(observation, persona, "RESERVED_DECISION",
                         f"النص يقترح تغيير حالة ملاحظة صادرة أو سحبها («{change}»)، وهو قرار محجوز لمراجع GCO (17.7).",
                         "تغيير ملاحظة صادرة دون سجل قرار بشري موثق", anchor_refs,
                         {"reserved": reserved, "phrase": change}, issued=issued))
    title_status = getattr(observation, "title_status", "NONE")
    if title_status == "APPROVED":
        out.append(_make(observation, persona, "RESERVED_DECISION",
                         "العنوان معروض بوصفه معتمداً دون سجل قرار بشري موثق في سجل التحدي (19A.9، القرار 22).",
                         "عرض عنوان كمعتمد قبل التحقق من قرار المراجع", anchor_refs,
                         {"reserved": "TITLE_APPROVAL", "title": getattr(observation, "title", None)},
                         issued=issued))

    # (1) the cited clause must occur in the reviewed document
    if anchor is None:
        whole = registry.bind_document()
        out.append(_make(observation, persona, "CLAUSE_NOT_FOUND",
                         "النص المقتبس في الملاحظة لم يُعثر عليه في الوثيقة محل المراجعة (بحث متسامح مع التطبيع والمسافات ولام-ألف).",
                         "لا يستطيع المستلم تحديد الموضع الذي تطلب الملاحظة تعديله", [whole.id] if whole else [],
                         {"quote": plain_text(observation.quote)[:200], "document": registry.document},
                         issued=issued))

    # (2) who approves / decides, against the matrix
    body, verb = asserted_approver(comment)
    caveat_present = MATRIX_CAVEAT in comment
    if verb is not None:
        cited = cited_matrix_item(comment)
        items = registry.matrix_items_for(matter) if matter else []
        if items:
            item = items[0]
        elif cited and registry.index is not None and registry.index.matrix.item(cited) is not None:
            item = registry.index.matrix.item(cited)
        else:
            item = registry.find_matter(strip_citation(comment))
        if body is not None:
            if item is None:
                out.append(_make(observation, persona, "AUTHORITY_UNSUPPORTED",
                                 f"الملاحظة تنسب الاعتماد إلى «{body}» ولا يحمل الفهرس المرجعي بنداً في مصفوفة الصلاحيات لهذه المسألة.",
                                 "تأكيد صلاحية لا يسندها المصدر المصنف (05.6، G-ADV-05)", anchor_refs,
                                 {"asserted_body": body, "verb": verb, "matrix_item": None,
                                  "caveat_present": caveat_present}, issued=issued))
            else:
                ev = registry.bind_matrix_item(item)
                approvers = list(item.bodies_with(ROLE_APPROVE))
                if body not in approvers:
                    named = "، ".join(approvers) if approvers else "لا جهة اعتماد مقروءة"
                    out.append(_make(observation, persona, "AUTHORITY_MISMATCH",
                                     f"الملاحظة تنسب الاعتماد إلى «{body}» بينما البند {item.number} من المصفوفة (ص.{item.page}) "
                                     f"يسمي: {named}؛ وحالة المصفوفة {ev.approval_status}.",
                                     "توجيه طلب اعتماد إلى غير الجهة التي يسميها المصدر المصنف", anchor_refs + [ev.id],
                                     {"asserted_body": body, "verb": verb, "matrix_item": item.number,
                                      "matrix_bodies": approvers, "caveat_present": caveat_present,
                                      "matrix_evidence": ev.id}, issued=issued))
                elif not caveat_present:
                    # the body is right; the citation must still carry the 05.6 caveat while UNVERIFIED
                    scope["matrix_item_confirmed"] = item.number
                    scope["caveat_missing"] = ev.approval_status not in ("APPROVED_CURRENT", "EXTERNAL_BINDING")
                else:
                    scope["matrix_item_confirmed"] = item.number
        elif item is not None and item.bodies_with(ROLE_APPROVE):
            scope["authority_assertion_without_matrix_body"] = verb
    # (3) the recommendation and the recipient's mandate (03A.5, G-ADV-04)
    rec = strip_citation(recommendation_part(comment))
    if persona.in_index and len(content_words(rec)) >= MIN_MANDATE_WORDS:
        own_score, own_task = persona.owns_task(rec)
        others = persona.other_owners(rec, MANDATE_OTHER)
        scope["mandate_overlap_recipient"] = round(own_score, 3)
        scope["mandate_overlap_other"] = [o[:3] for o in others[:3]]
        if others and own_score >= MANDATE_OWN:
            other = others[0]
            ev_other = registry.bind_mandate(other[0])
            ev_own = persona.mandate_evidence()
            out.append(_make(observation, persona, "CONTESTED_OWNERSHIP",
                             f"المهمة التي تخاطبها التوصية واردة أيضاً في مهام «{other[0]}» ({other[1]}، ص.{other[3]}) "
                             f"بدرجة لا تقل عن مهام المستلم؛ والمصدر مقترح غير معتمد فلا يحسم الملكية.",
                             "توجيه التوصية إلى غير الوحدة المالكة للمسألة", anchor_refs + [e.id for e in (ev_other, ev_own) if e],
                             {"other_unit": other[0], "other_sector": other[1], "other_score": other[2],
                              "recipient_score": round(own_score, 3), "other_evidence": ev_other.id if ev_other else None,
                              "recipient_evidence": ev_own.id if ev_own else None}, issued=issued))
        elif others and own_score < MANDATE_OWN:
            other = others[0]
            ev_other = registry.bind_mandate(other[0])
            ev_own = persona.mandate_evidence()
            out.append(_make(observation, persona, "OUTSIDE_RECIPIENT_MANDATE",
                             f"التوصية تخاطب مهمة من مهام «{other[0]}» ({other[1]}، ص.{other[3]}) لا من مهام "
                             f"«{persona.canonical_unit}» (ص.{persona.page})، {org_citation(other[3], persona.status_caveat)}.",
                             "لا يملك المستلم تنفيذ المطلوب؛ يُعاد توجيهه أو يُحوَّل إلى سؤال لمالك المسألة",
                             anchor_refs + [e.id for e in (ev_other, ev_own) if e],
                             {"other_unit": other[0], "other_sector": other[1], "other_score": other[2],
                              "recipient_score": round(own_score, 3), "other_evidence": ev_other.id if ev_other else None,
                              "recipient_evidence": ev_own.id if ev_own else None, "recipient_task": own_task},
                             issued=issued))
    # (4) a legal breach asserted without a bound policy or reference
    breach = breach_claim(comment)
    basis = registry.basis(observation.internal_id)
    if breach:
        bound = [b for b in basis if b.kind in ("POLICY", "REFERENCE_MATRIX", "REFERENCE_ORG")]
        supporting = [b for b in bound if b.authority_verified]
        scope["breach_basis"] = [(b.id, b.approval_status) for b in bound]
        if not supporting:
            why = ("دون دليل سياسة أو مرجع مربوط في السجل" if not bound else
                   f"وسندها المربوط من فئة غير معتمدة ({'، '.join(b.approval_status for b in bound)})")
            out.append(_make(observation, persona, "UNSUPPORTED_BREACH_CLAIM",
                             f"الملاحظة تقرر مخالفة («{breach}») {why} (05.1، 04.3، G-ADV-02).",
                             "حكم نظامي غير مسند قد يُفهم كحكم قاطع", anchor_refs + [b.id for b in bound],
                             {"phrase": breach, "basis": [b.id for b in bound]}, issued=issued))
    # (5) duplicate remedy on the same clause (07.5, P11)
    for other in siblings:
        if other.internal_id == observation.internal_id or other.reader_int >= observation.reader_int:
            continue
        other_anchor = registry.bind_clause(other.quote)
        same_clause = (anchor is not None and other_anchor is not None and anchor.page_or_paragraph == other_anchor.page_or_paragraph) \
            or (nfc(plain_text(other.location)) == nfc(plain_text(observation.location)) and plain_text(observation.location).strip())
        if not same_clause:
            continue
        ov = remedy_overlap(comment, plain_text(other.comment))
        if ov >= 0.25:
            refs = anchor_refs + ([other_anchor.id] if other_anchor else [])
            out.append(_make(observation, persona, "DUPLICATE_REMEDY",
                             f"المعالجة المطلوبة هي معالجة الملاحظة #{other.reader_no} على البند نفسه (تداخل {ov:.0%} في التسلسلات الرباعية).",
                             "طلبان بمعالجة واحدة يربكان المستلم ويخالفان وحدة المعالجة (07.5)", refs,
                             {"earlier_id": other.internal_id, "earlier_reader_no": other.reader_no, "overlap": round(ov, 3)},
                             issued=issued))
            break
    # (6) the requested action must be stated
    stated, how = states_requested_action(comment)
    scope["action_form"] = how
    if not stated:
        out.append(_make(observation, persona, "UNCLEAR_ACTION",
                         "لا تحمل الملاحظة جملة إجراء مطلوب («التوصية:» / «المطلوب:» أو فعل طلب أو سؤال)؛ لا يعرف المستلم ما يفعله (R4).",
                         "ملاحظة بلا إجراء قابل للتنفيذ أو للرد", anchor_refs, {}, issued=issued))
    # (7) concision budget
    words = word_count(comment)
    scope["word_count"] = words
    if words > WORD_BUDGET:
        out.append(_make(observation, persona, "VERBOSE",
                         f"جسم الملاحظة {words} كلمة ويتجاوز حد الإيجاز الهندسي ({WORD_BUDGET}) وسقوف المادة 07.",
                         "إطالة تضعف وضوح المطلوب وتخالف سقوف المادة 07", anchor_refs, {"words": words}, issued=issued))
    for o in out:
        o.detail.setdefault("scan_scope", scope)
    return out


def _scan_scope(registry: EvidenceRegistry, persona: RecipientPersona) -> dict:
    """What the black team looked at (decision 61: silence is never an unexecuted check)."""
    return {"checks": list(KINDS), "document": registry.document,
            "recipient": persona.canonical_unit or f"{persona.department_input} (NOT_IN_INDEX → {OWNER_FALLBACK})",
            "sources": {k: {"approval_status": v.approval_status, "hash": v.hash_status}
                        for k, v in (registry.index.sources.items() if registry.index else {})}}


# ------------------------------------------------------------- red advocate
def _alternative_anchor(observation: Observation, registry: EvidenceRegistry) -> tuple[EvidenceItem | None, str | None]:
    """A shorter fragment of the quote, or the location text, that does occur in the document."""
    q = plain_text(observation.quote)
    parts = [p.strip() for p in re.split(r"[،,.؛;:\n]", q) if len(p.split()) >= 3]
    parts.sort(key=lambda p: -len(p))
    for p in parts:
        ev = registry.bind_clause(p)
        if ev:
            return ev, p
    return None, None


def red_advocate(objection: Objection, observation: Observation, registry: EvidenceRegistry) -> Advocacy:
    """The GCO case for one objection: CONCEDE, DEFEND (with evidence only) or REVISE (with the new text)."""
    kind, d = objection.kind, objection.detail
    comment = plain_text(observation.comment)
    cid = objection.challenge_id
    anchor = registry.bind_clause(observation.quote)
    anchor_refs = [anchor.id] if anchor else []

    if kind == "RESERVED_DECISION":
        return Advocacy(cid, "CONCEDE", "المسألة محجوزة لمراجع GCO (14.4، 17.7)؛ لا يدافع المحرك عن تغيير ملاحظة صادرة أو عن اعتماد عنوان.",
                        anchor_refs)
    if kind == "CLAUSE_NOT_FOUND":
        ev, frag = _alternative_anchor(observation, registry)
        if ev:
            return Advocacy(cid, "REVISE", f"يوجد مرساة بديلة في الوثيقة (¶{ev.page_or_paragraph}): يُضيّق الاقتباس إلى «{frag}».",
                            [ev.id], revised_quote=frag)
        return Advocacy(cid, "CONCEDE", "لم يُعثر على النص المقتبس ولا على مرساة بديلة؛ تُحجب الملاحظة حتى يُثبت الموضع.", [])
    if kind == "AUTHORITY_MISMATCH":
        bodies = d.get("matrix_bodies") or []
        ev_id = d.get("matrix_evidence")
        if bodies and ev_id:
            new_body = bodies[0]
            cite = matrix_citation(d["matrix_item"], registry.resolve(ev_id).approval_status)
            revised = comment.replace(d["asserted_body"], new_body)
            if "ولم يُتحقق" not in revised and "البند" not in revised:
                revised = revised.rstrip(" .") + f" ({cite})."
            return Advocacy(cid, "REVISE", f"تُصحح الجهة إلى «{new_body}» كما يسميها البند {d['matrix_item']} مع قيد الحالة (05.6).",
                            anchor_refs + [ev_id], revised_comment=_gtext(revised))
        return Advocacy(cid, "CONCEDE", "البند لا يسمي جهة اعتماد مقروءة؛ لا يُسند تأكيد الصلاحية.", anchor_refs)
    if kind == "AUTHORITY_UNSUPPORTED":
        question = f"هل اعتماد ما ورد في البند المشار إليه من اختصاص «{d.get('asserted_body')}»، وما سند ذلك في مصفوفة الصلاحيات؟"
        if anchor:
            return Advocacy(cid, "REVISE", "المصفوفة صامتة؛ يُحوَّل التأكيد إلى سؤال للإدارة بصيغة F6 دون تسمية جهة اعتماد (05.6).",
                            anchor_refs, revised_comment=GText.plain(question))
        return Advocacy(cid, "CONCEDE", "لا سند في المصفوفة ولا مرساة في الوثيقة؛ تُحجب الملاحظة.", [])
    if kind == "OUTSIDE_RECIPIENT_MANDATE":
        other, ev_other = d.get("other_unit"), d.get("other_evidence")
        if other and ev_other:
            rec = recommendation_part(comment)
            cite = org_citation(registry.resolve(ev_other).page_or_paragraph.lstrip("p."), registry.resolve(ev_other).approval_status)
            question = f"التأكيد من قبل {other} على ما يلي: {rec.rstrip('.')}، ({cite})؟"
            return Advocacy(cid, "REVISE", f"تُضيَّق التوصية إلى طلب تأكيد موجه إلى مالك المسألة «{other}» بصيغة F6 (03A.2).",
                            anchor_refs + [ev_other], revised_comment=GText.plain(question), route_to=other)
        return Advocacy(cid, "CONCEDE", "لم تُحدد الوحدة المالكة؛ يُحال المطلوب إلى الإدارة صاحبة الطلب.", anchor_refs,
                        route_to=OWNER_FALLBACK)
    if kind == "CONTESTED_OWNERSHIP":
        ev_own = d.get("recipient_evidence")
        if ev_own:
            return Advocacy(cid, "DEFEND", f"مهام المستلم تشمل المهمة نفسها (ص.{registry.resolve(ev_own).page_or_paragraph.lstrip('p.')})؛ "
                                           "يبقى التوجيه إلى الإدارة صاحبة الوثيقة (03A.2).", [ev_own])
        return Advocacy(cid, "CONCEDE", "لا دليل على ملكية المستلم؛ يُحال التوجيه.", anchor_refs)
    if kind == "UNSUPPORTED_BREACH_CLAIM":
        approved = [b for b in registry.basis(observation.internal_id) if b.authority_verified and b.kind != "DOCUMENT"]
        if approved:
            return Advocacy(cid, "DEFEND", "دعوى المخالفة مسندة إلى مصدر من فئة معتمدة في السجل.", [b.id for b in approved])
        revised = comment
        for bad, good in _RISK_WORDING:
            revised = revised.replace(bad, good)
        if revised != comment:
            return Advocacy(cid, "REVISE", "تُصاغ المخالفة بوصفها خطراً لا حكماً قاطعاً (04.3)؛ يبقى الطلب كما هو.",
                            anchor_refs, revised_comment=_gtext(revised))
        return Advocacy(cid, "CONCEDE", "لا سند للمخالفة ولا صياغة بديلة؛ تُحجب حتى يُربط المرجع.", anchor_refs)
    if kind == "DUPLICATE_REMEDY":
        earlier = d.get("earlier_reader_no")
        revised = f"التوصية: كما في #{earlier}."
        return Advocacy(cid, "REVISE", f"تُوحَّد المعالجة تحت الملاحظة #{earlier} ويُترك إحالة موجزة (07.5، SC-48).",
                        anchor_refs, revised_comment=_gtext(revised))
    if kind == "UNCLEAR_ACTION":
        sentences = [s.strip() for s in re.split(r"(?<=[.؟!])\s+", comment) if s.strip()]
        for i, s in enumerate(sentences):
            if any(v in s for v in _ACTION_VERBS) or any(w in s for w in ("إضافة", "تعديل", "ربط", "قصر", "حذف", "إحلال", "استكمال")):
                sentences[i] = "التوصية: " + s
                return Advocacy(cid, "REVISE", "تُوسم جملة الإجراء بـ«التوصية:» حتى يتضح المطلوب من أول قراءة (07.1).",
                                anchor_refs, revised_comment=_gtext(" ".join(sentences)))
        return Advocacy(cid, "CONCEDE", "لا جملة إجراء يمكن وسمها؛ تُحجب حتى يحدد المحرر المطلوب.", anchor_refs)
    if kind == "VERBOSE":
        if has_action_label(comment):
            label = next(l for l in ACTION_LABELS if l in comment)
            reason, action = comment.split(label, 1)
            first = re.split(r"(?<=[.؟!])\s+", reason.strip())[0] if reason.strip() else ""
            action_only = label + " " + action.strip()
            for short, why in (((first + " " if first else "") + action_only, "تُختصر الملاحظة إلى جملة سبب واحدة والإجراء (07.1، 07.6)."),
                               (action_only, "تُحذف جملة السبب ويبقى الإجراء وحده؛ السبب يُقرأ من النص المرسى (07.1).")):
                if word_count(short) <= WORD_BUDGET and word_count(short) < word_count(comment):
                    return Advocacy(cid, "REVISE", why, anchor_refs, revised_comment=_gtext(short))
        return Advocacy(cid, "CONCEDE", "تجاوز الطول قائم ولا يختصره المحرك آلياً؛ يُعاد إلى المحرر للاختصار.", anchor_refs)
    raise ValueError(f"Unknown objection kind {kind!r}")


def _followups(objection: Objection, observation: Observation, registry: EvidenceRegistry,
               persona: RecipientPersona, first: Advocacy) -> list[tuple[str, list[str], Advocacy]]:
    """Later productive cycles: (black counter, its evidence, the advocate's reply), by kind."""
    if first.stance != "DEFEND":
        return []
    cid = objection.challenge_id
    org_status = registry.bind_source_status("org_structure")
    mat_status = registry.bind_source_status("authority_matrix")
    anchor = registry.bind_clause(observation.quote)
    anchor_refs = [anchor.id] if anchor else []
    if objection.kind == "CONTESTED_OWNERSHIP":
        d = objection.detail
        matter = registry.find_matter(recommendation_part(plain_text(observation.comment)))
        mat_ev = registry.bind_matrix_item(matter) if matter else None
        rows = []
        if org_status:
            rows.append((f"الهيكل التنظيمي مقترح غير معتمد ({org_status.approval_status})؛ ورود المهمة في صفحة الوحدة لا يحسم ملكية المسألة (19A.3).",
                         [org_status.id],
                         Advocacy(cid, "DEFEND", (f"البند {matter.number} من المصفوفة يسمي جهة الاعتماد للمسألة؛ يبقى توجيه الطلب إلى الإدارة صاحبة الوثيقة."
                                                  if mat_ev else "مهام الوحدة الأخرى ذاتها واردة في المصدر نفسه المقترح؛ لا أفضلية لطرف على طرف."),
                                  [mat_ev.id] if mat_ev else [d["other_evidence"]])))
        if mat_status:
            rows.append((f"المصفوفة غير متحقق من سريانها ({mat_status.approval_status}) ولا تسمي وحدة تنظيمية مالكة؛ الاعتراض قائم.",
                         [mat_status.id],
                         Advocacy(cid, "DEFEND", "قاعدة المخاطَب في 03A.2: الإدارة صاحبة الوثيقة ما لم يُسجل مالك آخر؛ الموضع ثابت في الوثيقة.",
                                  anchor_refs or [d["recipient_evidence"]])))
        return rows
    return []                                   # every other defended objection ends as it stands (19A.5)


# --------------------------------------------------------------- adjudicator
_TABLE: dict[str, dict[str, str]] = {
    "CLAUSE_NOT_FOUND": {"CONCEDE": "WITHHELD_FOR_EVIDENCE", "REVISE": "UPHELD_WITH_REVISION", "DEFEND": "UPHELD_UNCHANGED"},
    "AUTHORITY_MISMATCH": {"CONCEDE": "WITHHELD_FOR_EVIDENCE", "REVISE": "UPHELD_WITH_REVISION", "DEFEND": "UPHELD_UNCHANGED"},
    "AUTHORITY_UNSUPPORTED": {"CONCEDE": "WITHHELD_FOR_EVIDENCE", "REVISE": "UPHELD_WITH_REVISION", "DEFEND": "UPHELD_UNCHANGED"},
    "OUTSIDE_RECIPIENT_MANDATE": {"CONCEDE": "ROUTED_OUTSIDE_GCO", "REVISE": "NARROWED_TO_GCO_SCOPE", "DEFEND": "UPHELD_UNCHANGED"},
    "CONTESTED_OWNERSHIP": {"CONCEDE": "ROUTED_OUTSIDE_GCO", "REVISE": "NARROWED_TO_GCO_SCOPE", "DEFEND": "UPHELD_UNCHANGED"},
    "UNSUPPORTED_BREACH_CLAIM": {"CONCEDE": "WITHHELD_FOR_EVIDENCE", "REVISE": "NARROWED_TO_GCO_SCOPE", "DEFEND": "UPHELD_UNCHANGED"},
    "DUPLICATE_REMEDY": {"CONCEDE": "UPHELD_WITH_REVISION", "REVISE": "UPHELD_WITH_REVISION", "DEFEND": "UPHELD_UNCHANGED"},
    "UNCLEAR_ACTION": {"CONCEDE": "WITHHELD_FOR_EVIDENCE", "REVISE": "UPHELD_WITH_REVISION", "DEFEND": "UPHELD_UNCHANGED"},
    "VERBOSE": {"CONCEDE": "UPHELD_WITH_REVISION", "REVISE": "UPHELD_WITH_REVISION", "DEFEND": "UPHELD_UNCHANGED"},
    "RESERVED_DECISION": {"CONCEDE": "ESCALATED_TO_GCO_REVIEWER", "REVISE": "ESCALATED_TO_GCO_REVIEWER",
                          "DEFEND": "ESCALATED_TO_GCO_REVIEWER"},
}
_AUTHORITY_KINDS = ("AUTHORITY_MISMATCH", "AUTHORITY_UNSUPPORTED", "UNSUPPORTED_BREACH_CLAIM")


def adjudicate(objection: Objection, advocacy: Advocacy, registry: EvidenceRegistry, *,
               unresolved: bool = False) -> Adjudication:
    """One disposition of 19A.6 from admissible evidence only; reserved matters are escalated (17.7, 14.4).

    Anything stored on the objection or the advocacy under a name such as
    ``expected`` is not evidence and is not read. ``unresolved`` says the
    cycle bound was reached, or the objection stayed material and open.
    """
    cid = objection.challenge_id
    refs = sorted(set(objection.evidence_refs) | set(advocacy.evidence_refs))
    admissible = [r for r in refs if registry.has(r)]
    inadmissible = [r for r in refs if not registry.has(r)]
    verified = [r for r in admissible if registry.resolve(r).authority_verified]
    reserved = objection.detail.get("reserved")
    if reserved is None and objection.issued:
        reserved = "ISSUED_OBSERVATION"
    if reserved:
        return Adjudication(cid, "ESCALATED_TO_GCO_REVIEWER",
                            f"قرار محجوز للمراجع ({reserved}): لا يغير المحرك ملاحظة صادرة ولا يعتمد عنواناً؛ يلزم سجل قرار بشري موثق (17.7، 14.4، 19A.6).",
                            admissible, inadmissible, reserved_matter=reserved,
                            open_question="قرار مراجع GCO الموثق على المسألة المحجوزة")
    if unresolved:
        return Adjudication(cid, "ESCALATED_TO_GCO_REVIEWER",
                            "بقي الاعتراض جوهرياً دون حسم عند بلوغ حد الدورات المنتجة؛ لا يخترع المحرك توافقاً ولا يسحب الملاحظة (19A.5، G-ADV-12).",
                            admissible, inadmissible, open_question="حسم ملكية المسألة أو سند الصلاحية من مراجع GCO")
    if advocacy.stance == "DEFEND" and not any(r in admissible for r in advocacy.evidence_refs):
        return Adjudication(cid, "WITHHELD_FOR_EVIDENCE", "دفاع بلا دليل مقبول في السجل لا يُعتد به؛ تُحجب الملاحظة حتى يُربط الدليل.",
                            admissible, inadmissible, open_question="ربط دليل الدفاع في سجل الأدلة")
    disposition = _TABLE[objection.kind][advocacy.stance]
    rationale = f"{objection.kind} × {advocacy.stance}: {advocacy.reasoning}"
    open_q = None
    if objection.kind in _AUTHORITY_KINDS and advocacy.stance == "DEFEND":
        sources = [registry.resolve(r) for r in advocacy.evidence_refs if registry.has(r)]
        approved = [s for s in sources if s.kind != "DOCUMENT" and s.authority_verified]
        if not approved:
            disposition = "WITHHELD_FOR_EVIDENCE"
            rationale += " — المصدر المستند إليه ليس من فئة معتمدة؛ لا يُحتج به كمعتمد (G-ADV-02)."
            open_q = "تقديم سجل اعتماد المصدر (02.9) أو إعادة الصياغة بقيد الحالة"
    if disposition in ("UPHELD_UNCHANGED", "UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE") and not verified:
        disposition = "WITHHELD_FOR_EVIDENCE"
        rationale += " — لا مرساة متحققة في الوثيقة ولا مصدر معتمد؛ لا يُثبت أساس دون دليل متحقق."
        open_q = open_q or "إثبات الموضع في الوثيقة أو ربط مصدر معتمد"
    if objection.kind == "DUPLICATE_REMEDY" and disposition == "UPHELD_WITH_REVISION":
        open_q = f"توحيد المعالجة تحت الملاحظة #{objection.detail.get('earlier_reader_no')} في STEP 09a"
    if objection.kind == "VERBOSE" and advocacy.stance == "CONCEDE":
        open_q = "اختصار الملاحظة بيد المحرر ضمن سقوف المادة 07"
    if advocacy.route_to:
        rationale += f" — يُوجَّه إلى: {advocacy.route_to}"
    return Adjudication(cid, disposition, rationale, admissible, inadmissible, open_question=open_q)


# ------------------------------------------------------------- the workflow
def _argue(objection: Objection, observation: Observation, registry: EvidenceRegistry, persona: RecipientPersona,
           max_cycles: int) -> tuple[Advocacy, Adjudication]:
    """Six-cycle loop for one objection: BLACK, RED_ADVOCATE, counters while productive, then the decision."""
    objection.add("BLACK", objection.proposition, objection.evidence_refs)
    adv = red_advocate(objection, observation, registry)
    objection.add("RED_ADVOCATE", adv.reasoning, adv.evidence_refs)
    resolved = adv.stance in ("CONCEDE", "REVISE")
    pending = _followups(objection, observation, registry, persona, adv) if not resolved else []
    cap_hit = False
    while pending and not resolved:
        if objection.productive_cycles() >= max_cycles:
            cap_hit = True
            break
        claim, refs, reply = pending.pop(0)
        try:
            objection.add("BLACK", claim, refs)
        except ValueError:
            break                                   # unproductive: the objection ends as it stands
        if objection.productive_cycles() >= max_cycles:
            cap_hit = True
            break
        try:
            objection.add("RED_ADVOCATE", reply.reasoning, reply.evidence_refs)
        except ValueError:
            break
        adv = reply
        resolved = adv.stance in ("CONCEDE", "REVISE")
    last_black = objection.events[-1]["actor"] == "BLACK"
    unresolved = (not resolved) and (cap_hit or last_black or (objection.kind == "CONTESTED_OWNERSHIP" and adv.stance == "DEFEND"))
    adj = adjudicate(objection, adv, registry, unresolved=unresolved)
    for r in adv.evidence_refs:
        if registry.has(r) and r not in objection.evidence_refs:
            objection.evidence_refs.append(r)
    objection.evidence_refs.sort()
    if not objection.issued:
        objection.decide(adj.disposition, verifications=registry.verifications())
        adj.engine_recorded = True
    # an issued observation is only ever decided with a verified HumanDecision (17.7): see apply_human_decisions
    return adv, adj


def run_challenge(state: ReviewState, registry: EvidenceRegistry, persona: RecipientPersona, *,
                  max_cycles: int = MAX_CYCLES, issued_ids: Iterable[str] | None = None,
                  matters: dict[str, str] | None = None) -> ChallengeRecord:
    """Challenge every observation of ``state``: black team, cycle loop, adjudication, chained record.

    An observation born before the current round is issued (17.7) unless
    ``issued_ids`` says otherwise; ``matters`` maps Internal_ID to the matrix
    matter keyword when the drafter recorded one.
    """
    if not 1 <= max_cycles <= MAX_CYCLES:
        raise ValueError(f"max_cycles must be 1..{MAX_CYCLES}")
    current = state.current_round
    issued_set = set(issued_ids) if issued_ids is not None else {o.internal_id for o in state.observations
                                                                  if o.birth_round < current}
    entries: list[ObservationEntry] = []
    live: dict[str, Objection] = {}
    for obs in state.ordered():
        issued = obs.internal_id in issued_set
        objections = black_team(obs, registry, persona, siblings=state.observations, issued=issued,
                                matter=(matters or {}).get(obs.internal_id))
        # paraphrase / duplicate collapse: one Challenge_ID per proposition (19A.4)
        seen: dict[str, Objection] = {}
        for o in objections:
            seen.setdefault(o.challenge_id, o)
        records: list[ObjectionRecord] = []
        for o in seen.values():
            adv, adj = _argue(o, obs, registry, persona, max_cycles)
            live[o.challenge_id] = o
            records.append(ObjectionRecord(o.challenge_id, o.kind, o.proposition, o.material_consequence,
                                           list(o.evidence_refs), [dict(e) for e in o.events], o.productive_cycles(),
                                           adv.to_dict(), adj.to_dict(), o.state, o.verify_chain()))
        scope = objections[0].detail.get("scan_scope") if objections else _scan_scope(registry, persona)
        entries.append(ObservationEntry(obs.internal_id, obs.reader_no, issued, records, scope))
    return ChallengeRecord(state.document.code, current, persona.to_dict(), entries, registry.to_dict(), max_cycles,
                           _objections=live)


# ---------------------------------------------------------- human decisions
def apply_human_decisions(record: ChallengeRecord, decisions: list, trust_store: dict | None = None,
                          registry: EvidenceRegistry | None = None) -> dict:
    """Clear blockers for verified HumanDecision records only (17.7, 19A.9).

    A bare boolean, a dict or any other object is not a decision; a
    HumanDecision whose audit fields, verification status or signature fail
    ``validate`` is rejected and the blocker stays. An outcome that asserts an
    institutional basis (UPHELD_*, NARROWED_TO_GCO_SCOPE) is accepted only when
    the objection's bound evidence verifies it (``registry``); without a
    registry such an outcome is refused, so a reviewer cannot sign a basis that
    the record does not carry. The result lists what was applied and what was
    rejected, with the reason.
    """
    verifications = registry.verifications() if registry is not None else {}
    applied: list[dict] = []
    rejected: list[dict] = []
    for d in decisions:
        if not isinstance(d, HumanDecision):
            rejected.append({"item": repr(d)[:80], "reason": "NOT_A_HUMAN_DECISION_RECORD"})
            continue
        try:
            d.validate(trust_store)
        except PermissionError as exc:
            rejected.append({"decision_id": d.decision_id, "observation_id": d.observation_id, "reason": str(exc)})
            continue
        hit = False
        for e in record.entries:
            if e.internal_id != d.observation_id:
                continue
            for o in e.objections:
                if not o.blocking():
                    continue
                live = record.objection(o.challenge_id)
                outcome = d.decision if d.decision in OUTCOMES else None
                if live.adjudication is None and outcome:
                    try:
                        live.decide(outcome, verifications=verifications, human=d, trust_store=trust_store)
                        o.engine_state = live.state
                    except (ValueError, PermissionError) as exc:
                        rejected.append({"decision_id": d.decision_id, "challenge_id": o.challenge_id, "reason": str(exc)})
                        continue
                o.human_decision = {"decision_id": d.decision_id, "decision": d.decision, "reviewer": d.reviewer,
                                    "role": d.role, "reference": d.reference, "timestamp": d.timestamp,
                                    "evidence_ref": d.evidence_ref, "verification_status": d.verification_status,
                                    "signing_key_id": d.signing_key_id}
                o.resolved_by_human = True
                hit = True
        entry = {"decision_id": d.decision_id, "observation_id": d.observation_id, "decision": d.decision,
                 "reviewer": d.reviewer, "timestamp": d.timestamp, "reference": d.reference, "applied": hit}
        record.human_decisions.append(entry)
        (applied if hit else rejected).append(entry if hit else {**entry, "reason": "NO_OPEN_BLOCKER_FOR_OBSERVATION"})
    return {"applied": applied, "rejected": rejected, "remaining_blockers": record.blockers()}


# ---------------------------------------------------------- confidentiality
_SCAN_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("CHALLENGE_ID", re.compile(r"\bADV-[0-9A-F]{16}\b")),
    ("EVIDENCE_ID", ID_PATTERN),
    ("CHAIN_HASH", re.compile(r"\b[0-9a-f]{64}\b")),
    ("DISPOSITION", re.compile(r"\b(" + "|".join(DISPOSITIONS) + r")\b")),
    ("ROLE", re.compile(r"\b(BLACK_TEAM|RED_ADVOCATE|ADJUDICATOR|Black Team|Red Advocate)\b")),
    ("REGISTER_FIELD", re.compile(r"Challenge_ID|SINGLE_PROCESS_RULE_BASED|CDF-ADV-")),
    ("ARABIC_ROLE", re.compile("الفريق الأسود|الفريق الأحمر|المناظرة الداخلية|التحدي المؤسسي|محاكاة الإدارة المستلمة|سجل التحدي|المحكّم")),
)
_XLSX_PARTS = ("xl/sharedStrings.xml", "xl/worksheets/", "xl/comments/", "docProps/core.xml", "docProps/app.xml",
               "xl/charts/", "xl/drawings/")
_DOCX_PARTS = ("word/document.xml", "word/comments.xml", "word/commentsExtended.xml", "word/footnotes.xml",
               "word/endnotes.xml", "word/header", "word/footer", "docProps/core.xml")


def _part_text(data: bytes) -> str:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return data.decode("utf-8", "replace")
    return " ".join(t for t in root.itertext() if t)


def confidentiality_scan(paths: list[Path]) -> list[str]:
    """Hits of challenge vocabulary, ids and hashes in requester-facing files (19A.9); [] means clean.

    Each hit is ``file:part:PATTERN:excerpt``. A missing file is reported as a hit
    (``MISSING``) so that an absent deliverable is never read as clean.
    """
    hits: list[str] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            hits.append(f"{p.name}::MISSING:")
            continue
        suffix = p.suffix.lower()
        texts: list[tuple[str, str]] = []
        if suffix in (".xlsx", ".docx", ".xlsm"):
            try:
                z = zipfile.ZipFile(p)
            except zipfile.BadZipFile:
                hits.append(f"{p.name}::BAD_PACKAGE:")
                continue
            wanted = _XLSX_PARTS if suffix != ".docx" else _DOCX_PARTS
            with z:
                for name in z.namelist():
                    if name.endswith(".xml") and any(name.startswith(w) for w in wanted):
                        texts.append((name, _part_text(z.read(name))))
        else:
            texts.append(("text", p.read_text(encoding="utf-8", errors="replace")))
        for part, text in texts:
            text = unicodedata.normalize("NFC", text)
            for label, pat in _SCAN_PATTERNS:
                for m in pat.finditer(text):
                    hits.append(f"{p.name}:{part}:{label}:{text[max(0, m.start() - 20):m.end() + 20].strip()}")
    return hits


# ------------------------------------------------------------- held-out set
SYNTHETIC_DOCUMENT = "\n".join([
    "مذكرة تفاهم تجريبية بين صندوق التنمية الثقافي وجهة شريكة افتراضية — بيانات تجريبية لأغراض الاختبار",
    "المادة (1) التعريفات",
    "1-1 يقصد بـ \"الصندوق\" صندوق التنمية الثقافي، ويقصد بـ \"الشريك\" الجهة الشريكة الافتراضية.",
    "المادة (3) نطاق التعاون",
    "3-1 يتعاون الطرفان في تطوير برامج التمويل الثقافي وفق خطة عمل سنوية يعدها الشريك.",
    "المادة (5) الصلاحيات والاعتماد",
    "5-1 تعتمد اللجنة التنفيذية نماذج العقود والاتفاقيات والوثائق الأخرى الملزمة الناشئة عن هذه المذكرة.",
    "5-2 تُعدَّل حدود الشراء المنصوص عليها في الملحق (أ) بإشعار كتابي من الصندوق.",
    "المادة (7) الميزانية والمناقلة",
    "7-1 يجوز للشريك المناقلة بين أبواب الميزانية المخصصة للبرامج دون حد أعلى.",
    "المادة (9) تعارض المصالح",
    "9-1 يفصح أعضاء لجنة التسيير عن أي تعارض في المصالح عند نشوئه.",
    "المادة (11) خطة استمرارية الأعمال",
    "11-1 يلتزم الشريك بإعداد خطة استمرارية الأعمال للمنصة وتحديثها سنوياً.",
    "المادة (12) الإنهاء",
    "12-1 يجوز لأي من الطرفين إنهاء المذكرة بإشعار كتابي لا تقل مدته عن ثلاثين يوماً.",
    "12-2 لا يخل الإنهاء بالالتزامات الناشئة قبل تاريخ نفاذه.",
])
SYNTHETIC_DEPARTMENT = "إدارة الحوكمة والامتثال"

_Q_51 = "تعتمد اللجنة التنفيذية نماذج العقود والاتفاقيات والوثائق الأخرى الملزمة"
_Q_52 = "تُعدَّل حدود الشراء المنصوص عليها في الملحق (أ) بإشعار كتابي من الصندوق"
_Q_71 = "يجوز للشريك المناقلة بين أبواب الميزانية المخصصة للبرامج دون حد أعلى"
_Q_91 = "يفصح أعضاء لجنة التسيير عن أي تعارض في المصالح عند نشوئه"
_Q_111 = "يلتزم الشريك بإعداد خطة استمرارية الأعمال للمنصة وتحديثها سنوياً"
_Q_121 = "يجوز لأي من الطرفين إنهاء المذكرة بإشعار كتابي لا تقل مدته عن ثلاثين يوماً"
_C_CLEAN_51 = ("يسند البند اعتماد نماذج العقود إلى اللجنة التنفيذية. التوصية: ربط اعتماد نماذج العقود والاتفاقيات "
               "بالرئيس التنفيذي (مصفوفة الصلاحيات الرئيسية (30 أبريل 2024)، البند 20.1، ولم يُتحقق من سريانها الحالي).")
_C_GOV_EXCEPTION = ("التوصية: ربط أي استثناء من مصفوفة الصلاحيات المعتمدة بدراسة وتقييم إدارة الحوكمة ورفع التوصية "
                    "لصاحب الصلاحية للاعتماد.")
_C_PROCUREMENT = ("التوصية: إعداد خطة المشتريات السنوية للصندوق بالتنسيق مع الوحدات التنظيمية المعنية مع تحديد "
                  "الأولويات التشغيلية والمالية للمشتريات.")


@dataclass(frozen=True)
class Case:
    """A synthetic held-out case; the expected labels are hidden from the workflow (read by the evaluator only)."""
    case_id: str
    label: str
    quote: str
    comment: str
    location: str = "ص.1"
    issued: bool = False
    title: Optional[str] = None
    title_status: str = "NONE"
    basis_policy: Optional[tuple] = None          # (name, excerpt, approval_status)
    sibling: Optional[tuple] = None                # (quote, comment) of an earlier observation
    department: str = SYNTHETIC_DEPARTMENT
    matter: Optional[str] = None
    max_cycles: int = MAX_CYCLES
    _expected_kinds: frozenset = frozenset()
    _expected_disposition: Optional[str] = None
    synthetic: bool = True

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        d["note"] = "SYNTHETIC — expected labels hidden; never the reference case of 00.8"
        return d


def held_out_cases() -> list[Case]:
    K = frozenset
    return [
        Case("H01", "valid: clause absent", "يلتزم الشريك بفتح حساب مستقل باسم الصندوق لدى بنك محلي",
             "التوصية: تحديد البنك وصاحب صلاحية فتح الحساب.", _expected_kinds=K({"CLAUSE_NOT_FOUND"}),
             _expected_disposition="WITHHELD_FOR_EVIDENCE"),
        Case("H02", "valid: wrong approving body", _Q_51,
             "التوصية: ربط اعتماد نماذج العقود والاتفاقيات بمجلس الإدارة بوصفه صاحب الصلاحية.",
             _expected_kinds=K({"AUTHORITY_MISMATCH"}), _expected_disposition="UPHELD_WITH_REVISION"),
        Case("H03", "valid: outside recipient mandate", _Q_52, _C_PROCUREMENT,
             _expected_kinds=K({"OUTSIDE_RECIPIENT_MANDATE"}), _expected_disposition="NARROWED_TO_GCO_SCOPE"),
        Case("H04", "valid: unsupported breach", _Q_71,
             "البند يخالف اللائحة المالية. التوصية: تقييد المناقلة بسقف وبموافقة مسبقة من الصندوق.",
             _expected_kinds=K({"UNSUPPORTED_BREACH_CLAIM"}), _expected_disposition="NARROWED_TO_GCO_SCOPE"),
        Case("H05", "invalid: clause present, body correct (caveated)", _Q_51, _C_CLEAN_51,
             _expected_kinds=K(), _expected_disposition=None),
        Case("H06", "invalid: body correct, task within mandate", _Q_52, _C_GOV_EXCEPTION,
             _expected_kinds=K(), _expected_disposition=None),
        Case("H07", "no objection: plain F1 action", _Q_121, "التوصية: إضافة مدة إشعار مماثلة للصندوق.",
             _expected_kinds=K(), _expected_disposition=None),
        Case("H08", "duplicate remedy on the same clause", _Q_121,
             "التوصية: إضافة مدة إشعار مماثلة للصندوق لا تقل عن ثلاثين يوماً.",
             sibling=(_Q_121, "التوصية: إضافة مدة إشعار مماثلة للصندوق لا تقل عن ثلاثين يوماً."),
             _expected_kinds=K({"DUPLICATE_REMEDY"}), _expected_disposition="UPHELD_WITH_REVISION"),
        Case("H09", "six-cycle escalation: contested ownership", _Q_111,
             "التوصية: متابعة مدى التزام الشريك بكافة الأنظمة واللوائح الحكومية والتنظيمية ذات العلاقة بمجال عمله "
             "مع ضمان الامتثال للأنظمة واللوائح الحكومية عند تنفيذ العقود.",
             _expected_kinds=K({"CONTESTED_OWNERSHIP"}), _expected_disposition="ESCALATED_TO_GCO_REVIEWER"),
        Case("H10", "title-approval firewall", _Q_91, "التوصية: تحديد الجهة التي تتلقى الإفصاح وتبت فيه.",
             title="ضبط الإفصاح عن تعارض المصالح", title_status="APPROVED",
             _expected_kinds=K({"RESERVED_DECISION"}), _expected_disposition="ESCALATED_TO_GCO_REVIEWER"),
        Case("H11", "attempted silent status change of an issued observation", _Q_71,
             "سُحبت الملاحظة بعد إعادة التقييم. التوصية: لا إجراء.", issued=True,
             _expected_kinds=K({"RESERVED_DECISION"}), _expected_disposition="ESCALATED_TO_GCO_REVIEWER"),
        Case("H12", "valid: unclear action", _Q_91, "البند لا يحدد من يتلقى الإفصاح ولا أثره على عضوية اللجنة.",
             _expected_kinds=K({"UNCLEAR_ACTION"}), _expected_disposition="WITHHELD_FOR_EVIDENCE"),
        Case("H13", "valid: verbose", _Q_121,
             "ينص البند على جواز الإنهاء بإشعار كتابي مدته ثلاثون يوماً لأي من الطرفين، وهو ما قد يترك الصندوق أمام إنهاء "
             "مفاجئ في منتصف تنفيذ برنامج ممول، كما أن النص لا يعالج أثر الإنهاء على الالتزامات القائمة، ولا على المبالغ "
             "المدفوعة مقدماً، ولا على ملكية المخرجات التي أُنتجت حتى تاريخ الإنهاء، ولا على التزامات السرية التي تمتد بعد "
             "الإنهاء، ولا على آلية تسوية الحسابات، ولا على إعادة الوثائق، ولا على استمرار بعض البنود بعد الإنهاء، ولا على "
             "الإخطار المسبق للمستفيدين، ولا على الإنهاء للإخلال، ولا على مهلة التصحيح، ولا على حق الصندوق في الإنهاء "
             "الفوري عند الإخلال الجوهري، ولا على الإنهاء عند التصفية أو الإعسار، ولا على الإنهاء لمقتضيات المصلحة العامة، "
             "ولا على التعويض عند الإنهاء غير المبرر، ولا على الإشعار الإلكتروني. التوصية: إضافة بند يحدد آثار الإنهاء "
             "على الالتزامات القائمة والمبالغ المدفوعة مقدماً وملكية المخرجات.",
             _expected_kinds=K({"VERBOSE"}), _expected_disposition="UPHELD_WITH_REVISION"),
        Case("H14", "valid: matrix silent on the matter", _Q_52,
             "التوصية: ربط تعديل حدود الشراء بموافقة لجنة الاستثمار بوصفها صاحبة الصلاحية.",
             _expected_kinds=K({"AUTHORITY_UNSUPPORTED"}), _expected_disposition="UPHELD_WITH_REVISION"),
        Case("H15", "invalid: breach claim with a bound policy of approved class", _Q_71,
             "البند يخالف اللائحة المالية. التوصية: تقييد المناقلة بسقف وبموافقة مسبقة من الصندوق.",
             basis_policy=("اللائحة المالية (نسخة اختبار)", "لا تجوز المناقلة بين أبواب الميزانية إلا بموافقة صاحب الصلاحية.",
                           "APPROVED_CURRENT"),
             _expected_kinds=K(), _expected_disposition=None),
        Case("H16", "valid: breach claim whose bound policy is UNVERIFIED (never argued as approved)", _Q_71,
             "البند يخالف اللائحة المالية. التوصية: تقييد المناقلة بسقف وبموافقة مسبقة من الصندوق.",
             basis_policy=("اللائحة المالية (نسخة غير متحقق منها)", "لا تجوز المناقلة إلا بموافقة صاحب الصلاحية.", "UNVERIFIED"),
             _expected_kinds=K({"UNSUPPORTED_BREACH_CLAIM"}), _expected_disposition="NARROWED_TO_GCO_SCOPE"),
        Case("H17", "invalid: question form is a stated action", _Q_52,
             "هل اعتمد الصندوق آلية لتعديل حدود الشراء، ومن صاحب الصلاحية فيها؟",
             _expected_kinds=K(), _expected_disposition=None),
    ]


def _case_state(case: Case) -> tuple[ReviewState, Observation]:
    from ..model.entities import Document, ReviewRound, TitleEvidence
    doc = Document(name="مذكرة تفاهم تجريبية", code="HLD", owning_department=case.department, is_demo=True)
    kwargs = {}
    if case.title:
        kwargs = {"title": case.title, "title_status": case.title_status,
                  "title_evidence": TitleEvidence("Synthetic Reviewer", "2026-10-23", "SYN-TITLE-1")
                  if case.title_status in ("APPROVED", "ISSUED") else None}
    obs_list: list[Observation] = []
    if case.sibling:
        obs_list.append(Observation("GCO-HLD-R1-001", "1", 1, case.location, case.sibling[0], GText.plain(case.sibling[1])))
    birth = 1 if case.issued else 2
    target = Observation("GCO-HLD-R2-002" if not case.issued else "GCO-HLD-R1-002", "2", birth, case.location,
                         case.quote, GText.plain(case.comment), **kwargs)
    obs_list.append(target)
    rounds = [ReviewRound(1, "2026-09-15"), ReviewRound(2, "2026-10-15")]
    return ReviewState(doc, rounds, obs_list), target


def evaluate_held_out(index=None) -> dict:
    """Run every held-out case through the workflow; report per case, FP/FN, precision/recall and the mock note."""
    if index is None:
        from ..references.index import ReferenceIndex
        try:
            index = ReferenceIndex.load()
        except Exception as exc:              # reference PDFs or parser not available: cases still run on the document
            index = None
            index_error = repr(exc)
    results = []
    tp = fp = fn = 0
    for case in held_out_cases():
        registry = EvidenceRegistry()
        registry.add_document_text(SYNTHETIC_DOCUMENT, "synthetic-mou.txt")
        if index is not None:
            registry.add_reference_index(index)
            persona = RecipientPersona.from_index(index, case.department, registry)
        else:
            persona = RecipientPersona(case.department, None, None, None, (), "PROPOSED_NOT_APPROVED", "UNVERIFIED",
                                       registry=registry)
        state, target = _case_state(case)
        if case.basis_policy:
            ev = registry.add_policy(case.basis_policy[0], case.basis_policy[1], approval_status=case.basis_policy[2])
            registry.attach_basis(target.internal_id, ev.id)
        record = run_challenge(state, registry, persona, max_cycles=case.max_cycles,
                               matters={target.internal_id: case.matter} if case.matter else None)
        entry = next(e for e in record.entries if e.internal_id == target.internal_id)
        predicted = {o.kind for o in entry.objections}
        expected = set(case._expected_kinds)
        case_fp = sorted(predicted - expected)
        case_fn = sorted(expected - predicted)
        case_tp = sorted(predicted & expected)
        tp += len(case_tp)
        fp += len(case_fp)
        fn += len(case_fn)
        dispositions = {o.kind: o.disposition for o in entry.objections}
        disp_ok = (case._expected_disposition is None and not entry.objections) or \
            (case._expected_disposition is not None and any(d == case._expected_disposition for d in dispositions.values()))
        results.append({"case_id": case.case_id, "label": case.label, "synthetic": True,
                        "predicted_kinds": sorted(predicted), "expected_kinds": sorted(expected),
                        "false_positives": case_fp, "false_negatives": case_fn,
                        "dispositions": dispositions, "expected_disposition": case._expected_disposition,
                        "disposition_match": disp_ok,
                        "cycles": {o.kind: o.cycles for o in entry.objections},
                        "passed": not case_fp and not case_fn and disp_ok,
                        "no_objection_recorded": entry.no_objection})
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {"schema": "CDF-ADV-HELDOUT-v7.12", "cases": results, "case_count": len(results),
            "passed": sum(1 for r in results if r["passed"]), "true_positives": tp, "false_positives": fp,
            "false_negatives": fn, "precision": round(precision, 4), "recall": round(recall, 4),
            "reference_index": "loaded" if index is not None else f"unavailable: {index_error}",
            "independence": INDEPENDENCE, "role_isolation": ROLE_ISOLATION, "mock_vs_live": MOCK_NOTE,
            "evaluation_type": "DETERMINISTIC_RULE_FIXTURE_NOT_LLM_ADJUDICATION"}
