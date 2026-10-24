"""Blind adversarial evaluation (Article 11, layer D) on a public, sealed holdout.

The holdout is generated from templates over the public SYNTHETIC reference fixture; every case is fictional.
The agents never see the expected answers: ``build_case_state`` feeds only the case inputs, the security layer
refuses any payload that carries an ``expected`` key, and the expected answers live in a separate sealed file
whose SHA-256 is checked before scoring.

Scoring follows the forensic baseline (``AI_AGENT_FORENSIC_AUDIT``): objection detection on covered
categories, false-objection rate on clean cases, adjudicator accuracy against the expected disposition.
Results are reported per execution mode (DETERMINISTIC / MOCK / LIVE) and never pooled. The 80 % adjudicator
threshold is a release criterion for the LIVE mode only; a deterministic score is a baseline, not a pass.

Nothing in this module tunes any role against the sealed answers.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from ..assurance.evidence import EvidenceRegistry
from ..assurance.personas import RecipientPersona
from ..model.entities import Document, GText, Observation, ReviewRound, ReviewState
from ..references.synthetic_index import synthetic_reference_index
from . import roles as R
from .contracts import MODE_LIVE, NO_MATERIAL_OBJECTION, canonical_json
from .debate import Exchange
from .runner import AgentRunner

HOLDOUT_SCHEMA = "CDF-PUBLIC-HOLDOUT-v7.12.1"
DEFAULT_HOLDOUT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "holdout"
LIVE_ADJUDICATOR_THRESHOLD = 0.80
BASELINE = {"sealed_cases": 32, "deterministic_adjudicator_accuracy": 0.656, "covered_objection_detection": 0.765,
            "false_objection_rate": 0.091, "source": "AI_AGENT_FORENSIC_AUDIT/reports (MODE A)"}
DEPT = "الحوكمة والامتثال"

# ------------------------------------------------------------------ templates (fictional)
_DOC = [
    "المادة (1): تهدف هذه الاتفاقية إلى تنظيم التعاون بين الطرفين في مجال البرامج الثقافية المشتركة.",
    "المادة (2): يتولى الطرفان تنفيذ المبادرات المشتركة وفق ما يتفقان عليه كتابةً.",
    "المادة (3): يجوز لأي من الطرفين إضافة مبادرات جديدة بإشعار الطرف الآخر قبل ثلاثين يوماً.",
    "المادة (4): يلتزم الطرفان بتبادل البيانات اللازمة لتنفيذ المبادرات مع مراعاة سريتها.",
    "المادة (5): يشكل الطرفان فريق عمل مشتركاً لمتابعة التنفيذ ويرفع تقاريره كل ثلاثة أشهر.",
    "المادة (6): لا تترتب على هذه الاتفاقية التزامات مالية إلا باتفاق مستقل يُعتمد وفق الصلاحيات.",
    "المادة (7): يلتزم الطرفان بالمحافظة على سرية المعلومات المتبادلة لمدة خمس سنوات بعد انتهائها.",
    "المادة (8): تكون حقوق الملكية الفكرية للمخرجات المشتركة للطرفين بالتساوي ما لم يُتفق على غير ذلك.",
    "المادة (9): تسري هذه الاتفاقية لمدة سنتين قابلة للتجديد باتفاق كتابي.",
    "المادة (10): تخضع هذه الاتفاقية للأنظمة المعمول بها ويُحال أي خلاف إلى التسوية الودية أولاً.",
]
_CLAUSE = {i + 1: _DOC[i] for i in range(len(_DOC))}
_QUOTE = {i: t.split(": ", 1)[1] for i, t in _CLAUSE.items()}


@dataclass
class HoldoutCase:
    case_id: str
    kind: str                          # the design family (not shown to agents)
    clause: int
    quote: str
    comment: str
    issued: bool = False
    sibling: tuple[str, str] | None = None
    department: str = DEPT
    document: list[str] = field(default_factory=lambda: list(_DOC))

    def inputs(self) -> dict:
        return {"case_id": self.case_id, "label": "SYNTHETIC_TEST_CASE", "department": self.department,
                "document_paragraphs": self.document, "issued": self.issued,
                "observation": {"location": f"المادة ({self.clause})", "quote": self.quote, "comment": self.comment},
                "sibling": list(self.sibling) if self.sibling else None}


def _templates() -> list[tuple[str, dict]]:
    """(family, expected) with the design rationale of each expected answer."""
    return [
        ("CLEAN", {"objection": NO_MATERIAL_OBJECTION, "disposition": None}),
        ("CLAUSE_NOT_FOUND", {"objection": "CLAUSE_NOT_FOUND", "disposition": "WITHHELD_FOR_EVIDENCE"}),
        ("UNSUPPORTED_BREACH_CLAIM", {"objection": "UNSUPPORTED_BREACH_CLAIM", "disposition": "NARROWED_TO_GCO_SCOPE"}),
        ("UNCLEAR_ACTION", {"objection": "UNCLEAR_ACTION", "disposition": "WITHHELD_FOR_EVIDENCE"}),
        ("VERBOSE", {"objection": "VERBOSE", "disposition": "UPHELD_WITH_REVISION"}),
        ("DUPLICATE_REMEDY", {"objection": "DUPLICATE_REMEDY", "disposition": "UPHELD_WITH_REVISION"}),
        ("RESERVED_DECISION", {"objection": "RESERVED_DECISION", "disposition": "ESCALATED_TO_GCO_REVIEWER"}),
        ("AUTHORITY_MISMATCH", {"objection": "AUTHORITY_MISMATCH", "disposition": "UPHELD_WITH_REVISION"}),
    ]


_CLEAN_COMMENTS = [
    "لا يحدد البند الجهة المختصة باعتماد المبادرات الجديدة.\nالتوصية: نوصي بربط اعتماد المبادرات بصاحب الصلاحية وفق مصفوفة الصلاحيات المعتمدة.",
    "نوصي بتحديد مدة الاحتفاظ بالبيانات المتبادلة وآلية إتلافها بعد انتهاء الغرض منها.",
    "نأمل تحديد دورية تقارير فريق العمل والجهة التي تُرفع إليها داخل الصندوق.",
    "نوصي بالنص على أن أي التزام مالي لاحق يخضع لاتفاقية مستقلة تُعتمد وفق الصلاحيات المالية.",
]
_BREACH = "البند يخالف سياسة حماية البيانات المعتمدة صراحةً.\nالتوصية: تقييد المشاركة بالبيانات اللازمة لتنفيذ المبادرة المعتمدة."
_UNCLEAR = "البند عام في صياغته ويحتمل أكثر من تفسير في التطبيق العملي."
_VERBOSE = ("يلاحظ أن البند الحالي قد جاء بصياغة مطولة ومتشعبة تتناول عدة مسائل في آن واحد، " * 8 +
            "\nالتوصية: نوصي بإعادة صياغة البند وتقسيمه إلى فقرات مستقلة لكل مسألة، مع تحديد الجهة المسؤولة عن كل فقرة، "
            "وتحديد مدة زمنية واضحة للتنفيذ، وربط كل التزام بصاحب الصلاحية المختص وفق مصفوفة الصلاحيات المعتمدة لدى الصندوق.")
_DUP_SIB = "نوصي بتحديد تشكيل فريق العمل وصلاحياته وآلية رفع تقاريره إلى الجهة المختصة."
_DUP = "نوصي بتحديد تشكيل فريق العمل وصلاحياته وآلية رفع تقاريره إلى الجهة المختصة بصورة دورية."
_RESERVED = "في ضوء الرد الوارد تُغلق الملاحظة وتُعد منتهية.\nالتوصية: لا إجراء."
_AUTH = "يعتمد رئيس المراجعة الداخلية مذكرات التفاهم واتفاقيات التعاون.\nالتوصية: نوصي بإحالة الاتفاقية إلى رئيس المراجعة الداخلية لاعتمادها."


def generate_holdout(n: int = 24, seed: int = 7) -> tuple[list[HoldoutCase], dict]:
    """Deterministic holdout of ``n`` cases balanced over the families; returns (cases, expected-by-case)."""
    rng = random.Random(seed)
    cases, expected = [], {}
    fams = _templates()
    for i in range(n):
        fam, exp = fams[i % len(fams)]
        clause = rng.choice([2, 3, 4, 5, 6, 7, 8])
        cid = f"HO-{i + 1:02d}"
        if fam == "CLEAN":
            c = HoldoutCase(cid, fam, clause, _QUOTE[clause], rng.choice(_CLEAN_COMMENTS))
        elif fam == "CLAUSE_NOT_FOUND":
            c = HoldoutCase(cid, fam, clause, "يلتزم الطرف الأول وحده بتحمل كافة التكاليف التشغيلية غير المتوقعة.", rng.choice(_CLEAN_COMMENTS))
        elif fam == "UNSUPPORTED_BREACH_CLAIM":
            c = HoldoutCase(cid, fam, 4, _QUOTE[4], _BREACH)
        elif fam == "UNCLEAR_ACTION":
            c = HoldoutCase(cid, fam, clause, _QUOTE[clause], _UNCLEAR)
        elif fam == "VERBOSE":
            c = HoldoutCase(cid, fam, clause, _QUOTE[clause], _VERBOSE)
        elif fam == "DUPLICATE_REMEDY":
            c = HoldoutCase(cid, fam, 5, _QUOTE[5], _DUP, sibling=(_QUOTE[5], _DUP_SIB))
        elif fam == "RESERVED_DECISION":
            c = HoldoutCase(cid, fam, clause, _QUOTE[clause], _RESERVED, issued=True)
        else:
            c = HoldoutCase(cid, fam, 2, _QUOTE[2], _AUTH)
        cases.append(c)
        expected[cid] = {"family": fam, **exp}
    return cases, expected


def write_holdout(out_dir=DEFAULT_HOLDOUT_DIR, n: int = 24, seed: int = 7) -> dict:
    """Write cases.json (inputs only) and expected.json + expected.sha256 (sealed answers) side by side."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases, expected = generate_holdout(n, seed)
    inputs = {"schema": HOLDOUT_SCHEMA, "note": "public synthetic holdout; inputs only — the sealed answers are in expected.json",
              "cases": [c.inputs() for c in cases]}
    (out / "cases.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=1), encoding="utf-8")
    exp_text = json.dumps({"schema": HOLDOUT_SCHEMA, "expected": expected}, ensure_ascii=False, indent=1, sort_keys=True)
    (out / "expected.json").write_text(exp_text, encoding="utf-8")
    seal = hashlib.sha256(exp_text.encode("utf-8")).hexdigest()
    (out / "expected.sha256").write_text(seal + "\n", encoding="utf-8")
    return {"cases": len(cases), "seal": seal, "dir": str(out)}


def load_holdout(holdout_dir=DEFAULT_HOLDOUT_DIR) -> tuple[list[dict], dict]:
    d = Path(holdout_dir)
    inputs = json.loads((d / "cases.json").read_text(encoding="utf-8"))
    text = (d / "expected.json").read_text(encoding="utf-8")
    seal = (d / "expected.sha256").read_text(encoding="utf-8").strip()
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != seal:
        raise ValueError("holdout expected answers were modified after sealing")
    for c in inputs["cases"]:
        if "expected" in canonical_json(c).lower():
            raise ValueError(f"{c['case_id']}: agent input carries a label")
    return inputs["cases"], json.loads(text)["expected"]


# ------------------------------------------------------------------ running
def build_case_state(case: dict) -> tuple[ReviewState, Observation]:
    doc = Document(name="حالة تقييم افتراضية", code="HLD", owning_department=case["department"], is_demo=True)
    obs: list[Observation] = []
    if case.get("sibling"):
        obs.append(Observation("GCO-HLD-R1-001", "1", 1, case["observation"]["location"], case["sibling"][0], GText.plain(case["sibling"][1])))
    birth = 1 if case["issued"] else 2
    target = Observation("GCO-HLD-R1-002" if case["issued"] else "GCO-HLD-R2-002", "2", birth, case["observation"]["location"],
                         case["observation"]["quote"], GText.plain(case["observation"]["comment"]))
    obs.append(target)
    return ReviewState(doc, [ReviewRound(1, "2026-09-15"), ReviewRound(2, "2026-10-15")], obs), target


def run_case(case: dict, runner: AgentRunner | None, index=None) -> dict:
    """Black team → advocate → adjudicator on one case; returns what the agents decided (never the expected)."""
    index = index or synthetic_reference_index()
    registry = EvidenceRegistry()
    registry.add_document_text("\n".join(case["document_paragraphs"]), f"{case['case_id']}.txt")
    registry.add_reference_index(index)
    persona = RecipientPersona.from_index(index, case["department"], registry)
    state, target = build_case_state(case)
    objections, bo = R.run_black_team(runner, state, target, registry, persona, issued=case["issued"], siblings=state.observations)
    result = {"case_id": case["case_id"], "mode": bo.mode, "black_status": bo.status, "objection": NO_MATERIAL_OBJECTION,
              "disposition": None, "provider_failure": bo.failed, "hallucinated_refs": 0, "unsupported_defence": False}
    if bo.failed or not objections:
        return result
    o = objections[0]
    result["objection"] = o.kind
    result["hallucinated_refs"] += len(o.detail.get("hallucinated_refs", []))
    ex = Exchange(o.challenge_id)
    ex.add(o, "BLACK", o.proposition, list(o.evidence_refs))
    adv, ro = R.run_red_advocate(runner, state, target, o, registry, persona, issued=case["issued"], prior_exchange=ex.for_payload())
    if adv is None:
        result["provider_failure"] = True
        return result
    result["unsupported_defence"] = "UNSUPPORTED_DEFENCE" in ro.notes
    ex.add(o, "RED_ADVOCATE", adv.reasoning, adv.evidence_refs, stance=adv.stance)
    adj, ao, guards = R.run_adjudicator(runner, state, target, o, adv, registry, issued=case["issued"], exchange=ex.for_payload())
    if adj is None:
        result["provider_failure"] = True
        return result
    result.update({"disposition": adj.disposition, "guards": guards, "stance": adv.stance})
    return result


def score(results: list[dict], expected: dict) -> dict:
    """Detection on covered categories, false objections on CLEAN cases, adjudicator accuracy on objected cases."""
    covered = [r for r in results if expected[r["case_id"]]["objection"] != NO_MATERIAL_OBJECTION]
    clean = [r for r in results if expected[r["case_id"]]["objection"] == NO_MATERIAL_OBJECTION]
    detected = [r for r in covered if r["objection"] == expected[r["case_id"]]["objection"]]
    any_objection = [r for r in covered if r["objection"] != NO_MATERIAL_OBJECTION]
    false_obj = [r for r in clean if r["objection"] != NO_MATERIAL_OBJECTION]
    adjudicated = [r for r in covered if r["disposition"] is not None]
    correct = [r for r in adjudicated if r["disposition"] == expected[r["case_id"]]["disposition"]]
    modes = sorted({r["mode"] for r in results})
    out = {"cases": len(results), "modes": modes, "mode": modes[0] if len(modes) == 1 else "MIXED",
           "covered_cases": len(covered), "clean_cases": len(clean),
           "objection_detection_exact": round(len(detected) / len(covered), 3) if covered else None,
           "objection_detection_any": round(len(any_objection) / len(covered), 3) if covered else None,
           "false_objection_rate": round(len(false_obj) / len(clean), 3) if clean else None,
           "adjudicator_accuracy": round(len(correct) / len(adjudicated), 3) if adjudicated else None,
           "adjudicated_cases": len(adjudicated), "provider_failures": sum(1 for r in results if r["provider_failure"]),
           "hallucinated_refs": sum(r.get("hallucinated_refs", 0) for r in results),
           "unsupported_defences": sum(1 for r in results if r.get("unsupported_defence")),
           "per_family": {}, "baseline": BASELINE}
    fams = sorted({expected[r["case_id"]]["family"] for r in results})
    for f in fams:
        rs = [r for r in results if expected[r["case_id"]]["family"] == f]
        exp = expected[rs[0]["case_id"]]
        out["per_family"][f] = {"n": len(rs), "objection_match": sum(1 for r in rs if r["objection"] == exp["objection"]),
                                "disposition_match": sum(1 for r in rs if r["disposition"] == exp["disposition"])}
    out["live_threshold_met"] = (out["mode"] == MODE_LIVE and out["adjudicator_accuracy"] is not None
                                 and out["adjudicator_accuracy"] >= LIVE_ADJUDICATOR_THRESHOLD and out["provider_failures"] == 0
                                 and out["hallucinated_refs"] == 0)
    out["classification"] = ("LIVE_HOLDOUT_PASS" if out["live_threshold_met"] else
                             "LIVE_HOLDOUT_BELOW_THRESHOLD" if out["mode"] == MODE_LIVE else f"{out['mode']}_BASELINE_NOT_A_PASS")
    return out


def evaluate(runner: AgentRunner | None, holdout_dir=DEFAULT_HOLDOUT_DIR, index=None, out_path=None) -> dict:
    cases, expected = load_holdout(holdout_dir)
    results = [run_case(c, runner, index) for c in cases]
    rep = {"schema": HOLDOUT_SCHEMA, "holdout": str(holdout_dir), "results": results, "score": score(results, expected),
           "trace": runner.trace.summary() if runner is not None else None}
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep
