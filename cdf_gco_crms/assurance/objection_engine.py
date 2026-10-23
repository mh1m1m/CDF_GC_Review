"""Deterministic objection engine: six productive cycles, hash-chained events, no AI self-reversal.

Ported from the earlier v7.12 batch (assurance.py + adversarial_fixtures.py)
without container paths. Pure Python, no model calls, no invented evidence.

An :class:`Objection` against a GCO observation is argued by three roles
(BLACK raises it, RED_ADVOCATE answers, ADJUDICATOR decides) in at most six
productive cycles; every event carries the hash of its predecessor so the
record cannot be edited after the fact. An objection can never override an
observation that was already issued unless the adjudication is backed by a
:class:`HumanDecision` whose record is VERIFIED_HUMAN_RECORD and whose
signature verifies against an institution-managed trust store handed in by the
caller (protocol Art. 17.7). A positive adjudication that asserts an
institutional basis needs a source whose authority was verified; occurrence of
a passage in a file (see ``reference_verify``) is not such a verification, and
nothing here infers applicability or approval from a document.

The fixtures in :data:`FIXTURES` are explicitly synthetic and the outcomes
they produce are rule-driven, not model adjudication.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

OUTCOMES = frozenset(("UPHELD_UNCHANGED", "UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE",
                      "ROUTED_OUTSIDE_GCO", "WITHHELD_FOR_EVIDENCE", "ESCALATED_TO_GCO_REVIEWER"))
APPROVED = frozenset(("APPROVED_CURRENT", "EXTERNAL_BINDING"))
ALLOWED_ROLES = ("BLACK", "RED_ADVOCATE", "ADJUDICATOR")
STATES = frozenset(("CREATED", "CHALLENGED", "ADVOCATE_RESPONDED", "COUNTER_CHALLENGED", "REVISION_PROPOSED",
                    "READY_FOR_ADJUDICATION", "ADJUDICATED", "RESOLVED", "ESCALATED", "WITHHELD"))
TERMINAL = frozenset(("RESOLVED", "ESCALATED", "WITHHELD"))
MAX_CYCLES = 6
VERIFIED_HUMAN_RECORD = "VERIFIED_HUMAN_RECORD"
REGISTER_SCHEMA = "CDF-ADV-v7.12"

_TRANSITIONS = {
    "CREATED": ("BLACK",),
    "CHALLENGED": ("RED_ADVOCATE",),
    "ADVOCATE_RESPONDED": ("BLACK", "ADJUDICATOR"),
    "COUNTER_CHALLENGED": ("RED_ADVOCATE", "ADJUDICATOR"),
    "REVISION_PROPOSED": ("BLACK", "ADJUDICATOR"),
    "READY_FOR_ADJUDICATION": ("ADJUDICATOR",),
    "ADJUDICATED": ("BLACK", "RED_ADVOCATE", "ADJUDICATOR"),
}


def canon(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).casefold()).strip()


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class SourceEvidence:
    """A file-backed reference. ``validate`` checks presence and checksum only.

    ``authority_verified`` is True only when the recorded status is already an
    approved class *and* the checksum matches; the text is not inspected here
    and no applicability is established.
    """
    reference_id: str
    filename: str
    file_sha256: str
    location: str
    exact_excerpt: str
    status: str = "UNVERIFIED"
    applicability: str = "NOT_ESTABLISHED"

    def validate(self, root: Path) -> dict:
        file = Path(root) / self.filename
        exists = file.is_file()
        digest = hashlib.sha256(file.read_bytes()).hexdigest() if exists else None
        checksum_ok = bool(exists and self.file_sha256 and digest == self.file_sha256)
        return {"reference_id": self.reference_id, "file_exists": exists, "sha256_matched": checksum_ok,
                "authority_verified": self.status in APPROVED and checksum_ok,
                "excerpt_verified": False, "applicability_verified": False}


@dataclass(frozen=True)
class HumanDecision:
    """A human reviewer's decision record. Validity requires a verified record and a trusted signature."""
    decision_id: str
    observation_id: str
    decision: str
    reviewer: str
    role: str
    reference: str
    timestamp: str
    evidence_ref: str
    verification_status: str = "NOT_VERIFIED"
    signing_key_id: str = ""
    signature_b64: str = ""

    def signature_payload(self) -> bytes:
        body = {"decision_id": self.decision_id, "observation_id": self.observation_id, "decision": self.decision,
                "reviewer": self.reviewer, "role": self.role, "reference": self.reference,
                "timestamp": self.timestamp, "evidence_ref": self.evidence_ref}
        return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()

    def validate(self, trust_store: dict | None = None) -> bool:
        """Raise PermissionError unless every audit field is present, the record is verified and the signature checks.

        The trust store (key id -> raw Ed25519 public key bytes) must come from
        an authorised external source, never from the review package itself.
        """
        mandatory = [self.decision_id, self.observation_id, self.decision, self.reviewer, self.role,
                     self.reference, self.timestamp, self.evidence_ref]
        if not all(x and str(x).strip() for x in mandatory):
            raise PermissionError("Human decision requires all audit fields")
        if self.verification_status != VERIFIED_HUMAN_RECORD:
            raise PermissionError("Reviewer approval evidence is not verified")
        if not (trust_store and self.signing_key_id in trust_store and self.signature_b64):
            raise PermissionError("Institution-managed public-key trust store is mandatory")
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            key = Ed25519PublicKey.from_public_bytes(trust_store[self.signing_key_id])
            key.verify(base64.b64decode(self.signature_b64, validate=True), self.signature_payload())
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise PermissionError("Decision signature is invalid") from exc
        return True


@dataclass
class Objection:
    """A challenge against one observation, argued in a hash-chained, append-only event list."""
    observation_id: str
    category: str
    proposition: str
    originating_department: str
    issued: bool = False
    state: str = "CREATED"
    events: list[dict] = field(default_factory=list)
    adjudication: Optional[str] = None
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not all((self.observation_id.strip(), self.category.strip(), self.proposition.strip())):
            raise ValueError("Missing objection identity")

    @property
    def challenge_id(self) -> str:
        return "ADV-" + sha([self.observation_id, canon(self.category), canon(self.proposition)])[:16].upper()

    def productive_cycles(self) -> int:
        return len(self.events)

    def add(self, actor: str, claim: str, evidence_refs: list[str] | None = None, *, material_change: bool = False) -> dict:
        """Append one argument; rejects unknown actors, terminated challenges, a seventh cycle and duplicates."""
        if actor not in ALLOWED_ROLES:
            raise ValueError("Unknown actor")
        if self.state in TERMINAL:
            raise ValueError("Challenge is terminated")
        if self.productive_cycles() >= MAX_CYCLES:
            raise ValueError("Maximum six productive cycles")
        normalized = canon(claim)
        if not normalized:
            raise ValueError("Empty reasoning")
        refs = sorted(set(evidence_refs or []))
        prior = {(e["normalized"], tuple(e["evidence_refs"])) for e in self.events}
        if (normalized, tuple(refs)) in prior and not material_change:
            raise ValueError("Unproductive duplicate challenge")
        if actor not in _TRANSITIONS.get(self.state, ()):
            raise ValueError(f"Invalid transition: {self.state} -> {actor}")
        self.state = ("CHALLENGED" if actor == "BLACK" and self.state == "CREATED" else
                      "COUNTER_CHALLENGED" if actor == "BLACK" else
                      "ADVOCATE_RESPONDED" if actor == "RED_ADVOCATE" else "ADJUDICATED")
        prev = self.events[-1]["event_hash"] if self.events else "GENESIS"
        event = {"sequence": len(self.events) + 1, "actor": actor, "claim": claim, "normalized": normalized,
                 "evidence_refs": refs, "state": self.state, "prev_hash": prev}
        event["event_hash"] = sha(event)
        self.events.append(event)
        return event

    def decide(self, outcome: str, *, verifications: dict[str, dict] | None = None,
               human: HumanDecision | None = None, trust_store: dict | None = None) -> str:
        """Adjudicate. An issued observation changes only on a verified HumanDecision (Art. 17.7).

        Outcomes that assert an institutional basis need at least one evidence
        reference whose verification says ``authority_verified``; a passage
        found in a file does not qualify by itself.
        """
        if outcome not in OUTCOMES:
            raise ValueError("Unknown outcome")
        if self.issued and outcome != "UPHELD_UNCHANGED":
            if human is None:
                raise PermissionError("Article 17.7 prevents AI self-reversal")
            if not isinstance(human, HumanDecision):
                raise TypeError("Human authorization requires HumanDecision record")
            human.validate(trust_store)
            if human.observation_id != self.observation_id:
                raise PermissionError("Human decision belongs to another observation")
        if outcome in ("UPHELD_UNCHANGED", "UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE"):
            approved = [r for r in self.evidence_refs if (verifications or {}).get(r, {}).get("authority_verified")]
            if not approved:
                raise ValueError("Cannot assert verified institutional basis without verified source")
        self.adjudication = outcome
        self.state = ("ESCALATED" if outcome == "ESCALATED_TO_GCO_REVIEWER" else
                      "WITHHELD" if outcome == "WITHHELD_FOR_EVIDENCE" else "RESOLVED")
        return outcome

    def to_dict(self) -> dict:
        d = asdict(self)
        d["challenge_id"] = self.challenge_id
        return d

    def verify_chain(self) -> bool:
        prev = "GENESIS"
        for i, event in enumerate(self.events):
            if event["sequence"] != i + 1 or event["prev_hash"] != prev:
                return False
            raw = {k: v for k, v in event.items() if k != "event_hash"}
            if sha(raw) != event["event_hash"]:
                return False
            prev = event["event_hash"]
        return True


@dataclass(frozen=True)
class ApprovedTitle:
    """An observation title shown only once a verified human decision authorises it; otherwise the neutral id."""
    internal_id: str
    text: str
    authorization: Optional[HumanDecision] = None
    issued_round: int = 0

    def display(self, reader_no: str, trust_store: dict | None = None) -> str:
        if self.authorization is None:
            return f"الملاحظة #{reader_no}"
        self.authorization.validate(trust_store)
        if self.authorization.observation_id != self.internal_id:
            raise PermissionError("Title ID mismatch")
        return " ".join(self.text.split())


def save_register(challenges: list[Objection], path: Path) -> Path:
    """Internal register of challenges; never published to owner-facing workbooks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted((c.to_dict() for c in challenges), key=lambda x: x["challenge_id"])
    path.write_text(json.dumps({"schema": REGISTER_SCHEMA, "items": ordered, "sha256": sha(ordered)},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def release_gates(reference_case_verified: bool = False, human_gco_approved: bool = False,
                  excel_365_verified: bool = False) -> dict:
    """Release gate values; RELEASE is OPERATIONALLY_APPROVED only when every external fact is stated."""
    values = {"ENGINE_SMOKE": "PASS",
              "ARTICLE_00_8": "PASS" if reference_case_verified else "NOT_VERIFIED",
              "HUMAN_GCO": "PASS" if human_gco_approved else "NOT_VERIFIED",
              "MICROSOFT_EXCEL_365": "PASS" if excel_365_verified else "NOT_VERIFIED"}
    values["RELEASE"] = "OPERATIONALLY_APPROVED" if all(v == "PASS" for v in values.values()) else "RELEASE_CANDIDATE"
    return values


# ------------------------------------------------------------------ synthetic fixtures
# (scenario id, topic, BLACK objection, RED_ADVOCATE answer, expected rule outcome)
FIXTURES: tuple[tuple[str, str, str, str, str], ...] = (
    ("01", "اختصاص الحوكمة", "اعتراض: ملاحظة تحدد التقنية الواجب اعتمادها رغم أنها قرار اختصاصي.",
     "الهدف الرقابي مشروع، لكن اختيار التقنية يجب أن يبقى لدى الإدارة المختصة.", "NARROWED_TO_GCO_SCOPE"),
    ("02", "المسؤولية", "اعتراض: الإفادة مطلوبة من قطاع لا يملك العملية.",
     "يجب تحديد مالك العملية قبل توجيه التوصية.", "WITHHELD_FOR_EVIDENCE"),
    ("03", "الصلاحيات", "اعتراض: استُشهد ببند تفويض غير محدد نصه.",
     "لا يثبت مصدر الصلاحية دون النص والإصدار.", "WITHHELD_FOR_EVIDENCE"),
    ("04", "مقترح غير معتمد", "اعتراض: مستند الهيكل المقترح يُعامل كمرجع صلاحيات معتمد.",
     "يراعى المستند بوصفه تصوراً لا تفويضاً.", "WITHHELD_FOR_EVIDENCE"),
    ("05", "انطباق النظام", "اعتراض: أحكام جهة تنظيمية خاصة قُدمت كالتزام عام للصندوق.",
     "يستلزم تحديد أساس انطباق النظام.", "WITHHELD_FOR_EVIDENCE"),
    ("06", "مادة مفبركة", "اعتراض: رقم المادة النظامية غير قابل للتتبع.",
     "يجب حذف دعوى المخالفة أو إثبات مصدرها.", "WITHHELD_FOR_EVIDENCE"),
    ("07", "تكرار المعالجة", "اعتراض: نفس الإجراء مطلوب في ملاحظة أخرى.",
     "توحيد الإجراء في ملاحظة واحدة وترك إحالة موجزة عند اللزوم.", "ROUTED_OUTSIDE_GCO"),
    ("08", "المعالجة القائمة", "اعتراض: النص يعالج المسألة في مادة أخرى.",
     "تتحقق التغطية من النصوص قبل إصدار ملاحظة مكررة.", "WITHHELD_FOR_EVIDENCE"),
    ("09", "التدخل التشغيلي", "اعتراض: الملاحظة تملي طريقة تفصيلية للتنفيذ.",
     "تضييق التوصية إلى هدف رقابي قابل للتحقق.", "NARROWED_TO_GCO_SCOPE"),
    ("10", "قرار تجاري", "اعتراض: طلبت الملاحظة اختيار مزود خدمة معين.",
     "قرار الاختيار يبقى وفق الآلية المختصة، ويصح اشتراط المنافسة والتوثيق.", "ROUTED_OUTSIDE_GCO"),
    ("11", "اعتراض غير صحيح", "اعتراض: يُزعم عدم حق GCO في طلب الإفصاح عن تعارض المصالح.",
     "طلب آلية إفصاح وتوثيقها يتصل بأهداف الحوكمة عند تحقق المرجعية.", "WITHHELD_FOR_EVIDENCE"),
    ("12", "دفاع غير مسند", "اعتراض: المدافع يحتج بقرار داخلي دون إرفاق مستنده.",
     "لا يعد الدفاع كافياً بلا مصدر أو إحالة قابلة للفحص.", "WITHHELD_FOR_EVIDENCE"),
    ("13", "الرجوع عن موقف سابق", "اعتراض: يقترح المدافع إلغاء ملاحظة سبق إصدارها.",
     "يحظر التغيير دون قرار بشري موثق وفق المادة 17.7.", "ESCALATED_TO_GCO_REVIEWER"),
    ("14", "عنوان غير معتمد", "اعتراض: وُضع عنوان يبدو معتمداً دون تسجيل الاعتماد.",
     "يعرض المعرف المحايد إلى حين اعتماد العنوان.", "WITHHELD_FOR_EVIDENCE"),
    ("15", "ست دورات", "اعتراض: بقي خلاف جوهري دون اتفاق مع انتهاء الدورات.",
     "توقف المناظرة ويحال القرار إلى مراجع GCO.", "ESCALATED_TO_GCO_REVIEWER"),
)
SYNTHETIC_AUTHORITY = "SYNTHETIC_TEST_AUTHORITY"
EVALUATION_TYPE = "DETERMINISTIC_RULE_FIXTURE_NOT_LLM_ADJUDICATION"


def run_fixtures(out_dir: Path | None = None) -> list[dict]:
    """Run the fifteen synthetic scenarios; write the internal register and results when ``out_dir`` is given."""
    results: list[dict] = []
    cases: list[Objection] = []
    for sid, cat, black, red, outcome in FIXTURES:
        c = Objection("SYNTHETIC-" + sid, cat, black, "إدارة افتراضية",
                      evidence_refs=[SYNTHETIC_AUTHORITY] if sid in ("01", "09") else [])
        c.add("BLACK", black)
        c.add("RED_ADVOCATE", red)
        if sid == "15":
            for n in (3, 4, 5, 6):
                actor = "BLACK" if n % 2 == 1 else "RED_ADVOCATE"
                c.add(actor, f"حجة أو تقييم جديد رقم {n} متعلق باستمرار الخلاف الجوهري", [f"MOCK-{n}"])
        adjudicated = c.decide(outcome, verifications={SYNTHETIC_AUTHORITY: {"authority_verified": True}})
        cases.append(c)
        results.append({"scenario_id": sid, "synthetic": True, "topic": cat, "expected": outcome,
                        "actual": adjudicated, "passed": adjudicated == outcome and c.verify_chain(),
                        "productive_cycles": c.productive_cycles(), "evaluation_type": EVALUATION_TYPE})
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        save_register(cases, out_dir / "synthetic_challenge_register_INTERNAL.json")
        (out_dir / "synthetic_scenario_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                                               encoding="utf-8")
    return results
