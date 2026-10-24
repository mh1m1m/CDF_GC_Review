"""MAT professional-DNA profile: schema, loader and version binding (directive Articles 08–09).

The profile is a versioned, evidence-backed description of one reviewer's documented review method. It is
loaded from an authorised private location (``CDF_MAT_PROFILE`` or an explicit path) — never from the package —
and the public repository ships only the schema, this loader and a synthetic example under ``tests/fixtures/mat``.

Binding rule (Article 08): a rule becomes an instruction only when the profile is VALIDATED **and** the rule is
``mat_explicitly_approved``; everything else is advisory and is presented with its evidence status. A profile whose
``human_approval_status`` is NOT_APPROVED therefore binds nothing, whatever its rules say.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import canonical_json, validate

ENV_PROFILE = "CDF_MAT_PROFILE"
PROFILE_TYPE = "PROFESSIONAL_REVIEW_METHOD"
STATUS_PROVISIONAL, STATUS_VALIDATED = "PROVISIONAL", "VALIDATED"
APPROVAL_NOT, APPROVAL_YES = "NOT_APPROVED", "APPROVED"
RULE_CLASSES = ("VERIFIED", "SUPPORTED_INFERENCE", "ESTABLISHED_SINGLE_CASE", "HYPOTHESIS", "NOT_ESTABLISHED",
                "SYSTEM_CONSTRAINT", "DEFAULT_WHEN_UNDOCUMENTED")
WITHDRAWAL_GROUNDS = tuple(f"MAT-W{i:02d}" for i in range(1, 16))
GROUND_LABELS = {"MAT-W01": "CONTRADICTION", "MAT-W02": "INAPPLICABILITY", "MAT-W03": "OUTSIDE_GCO_SCOPE",
                 "MAT-W04": "EXISTING_ADEQUATE_CONTROL", "MAT-W05": "UNSUPPORTED_EVIDENCE", "MAT-W06": "DUPLICATION",
                 "MAT-W07": "DISPROPORTIONATE_REMEDY", "MAT-W08": "INCORRECT_AUTHORITY", "MAT-W09": "UNNECESSARY_OPERATIONAL_INTRUSION",
                 "MAT-W10": "LOW_MATERIALITY", "MAT-W11": "MISINTERPRETATION", "MAT-W12": "ADDRESSED_ELSEWHERE",
                 "MAT-W13": "SUPERSEDED_INFORMATION", "MAT-W14": "INEFFECTIVE_RECOMMENDATION", "MAT-W15": "UNKNOWN_REASON"}


def _s(**kw):
    return {"type": "string", **kw}


def _arr(items, **kw):
    return {"type": "array", "items": items, **kw}


_RULE = {"type": "object", "required": ["rule_id", "rule_type", "condition", "action", "classification", "confidence", "mat_explicitly_approved"],
         "properties": {"rule_id": _s(pattern=r"^[A-Z]{2,6}-[A-Z]\d{2}$"), "rule_type": _s(), "condition": _s(maxLength=600), "action": _s(maxLength=600),
                        "evidence": _arr(_s()), "counterexamples": _arr(_s()), "classification": _s(enum=list(RULE_CLASSES)),
                        "confidence": _s(enum=["HIGH", "MEDIUM", "LOW", "NONE", "NOT_ESTABLISHED"]), "scope": _s(),
                        "mat_explicitly_approved": {"type": "boolean"}}}
_GROUND = {"type": "object", "required": ["rule_id", "ground", "classification", "confidence", "mat_explicitly_approved"],
           "properties": {"rule_id": _s(enum=list(WITHDRAWAL_GROUNDS)), "ground": _s(), "rule_type": _s(), "observations_consistent_with_ground": _arr(_s()),
                          "sample_size": {"type": "integer"}, "classification": _s(enum=list(RULE_CLASSES)), "confidence": _s(),
                          "counterexamples": _arr(_s()), "human_validation": _s(), "mat_explicitly_approved": {"type": "boolean"}}}
_PATTERN = {"type": "object", "required": ["pattern_id", "text", "confidence"],
            "properties": {"pattern_id": _s(), "text": _s(maxLength=400), "confidence": _s(), "evidence": _arr(_s()), "counterexamples": _arr(_s()),
                           "validation_status": _s(), "mat_approved": {"type": "boolean"}}}
PROFILE_SCHEMA = {"type": "object",
                  "required": ["profile_id", "version", "profile_type", "status", "human_approval_status", "writing_patterns", "question_patterns",
                               "recommendation_patterns", "selection_rules", "withdrawal_rules"],
                  "properties": {"profile_id": _s(pattern=r"^[A-Z][A-Z0-9_]{2,40}$"), "version": _s(), "profile_type": _s(enum=[PROFILE_TYPE]),
                                 "person_reference": _s(), "status": _s(enum=[STATUS_PROVISIONAL, STATUS_VALIDATED]),
                                 "human_approval_status": _s(enum=[APPROVAL_NOT, APPROVAL_YES]), "generated_utc": _s(), "evidence_scope": _s(),
                                 "attribution_confidence": _s(), "corpus_hashes": _arr(_s()), "writing_patterns": _arr(_PATTERN),
                                 "question_patterns": _arr(_PATTERN), "recommendation_patterns": _arr(_PATTERN), "selection_rules": _arr(_RULE),
                                 "withdrawal_rules": _arr(_GROUND), "debate_patterns": _arr(_PATTERN), "guards": {"type": "object"},
                                 "supporting_evidence": _arr(_s()), "counterexamples": _arr(_s()), "validation_results": _arr({"type": "object"}),
                                 "distribution": {"type": "object"}, "synthetic": {"type": "boolean"}, "label": _s()}}


class ProfileNotConfigured(FileNotFoundError):
    """No MAT profile path was given and the environment names none."""


class ProfileInvalid(ValueError):
    """The profile file does not validate against the profile schema."""


@dataclass
class LoadedProfile:
    data: dict
    path: str
    sha256: str
    synthetic: bool = False

    @property
    def profile_id(self) -> str:
        return self.data["profile_id"]

    @property
    def version(self) -> str:
        return self.data["version"]

    @property
    def status(self) -> str:
        return self.data["status"]

    @property
    def approval(self) -> str:
        return self.data["human_approval_status"]

    @property
    def binding_allowed(self) -> bool:
        """Only a VALIDATED and APPROVED profile may bind any rule (Article 08)."""
        return self.status == STATUS_VALIDATED and self.approval == APPROVAL_YES

    def rules(self) -> dict[str, dict]:
        return {r["rule_id"]: r for r in self.data.get("selection_rules", []) + self.data.get("withdrawal_rules", [])}

    def rule_status(self, rule_id: str) -> dict:
        """How an invoked rule may be used: BINDING (validated + approved), ADVISORY (documented, not approved),
        NOT_ESTABLISHED (no evidence) or UNKNOWN_RULE (not in the profile)."""
        r = self.rules().get(rule_id)
        if r is None:
            return {"rule_id": rule_id, "use": "UNKNOWN_RULE", "classification": None, "confidence": None}
        if self.binding_allowed and r.get("mat_explicitly_approved"):
            use = "BINDING"
        elif r.get("classification") in ("NOT_ESTABLISHED",) or r.get("confidence") in ("NONE", "NOT_ESTABLISHED"):
            use = "NOT_ESTABLISHED"
        else:
            use = "ADVISORY"
        return {"rule_id": rule_id, "use": use, "classification": r.get("classification"), "confidence": r.get("confidence")}

    def binding(self) -> dict:
        """What every MAT output carries so that an output can be tied to the exact profile version it used."""
        return {"profile_id": self.profile_id, "profile_version": self.version, "profile_sha256": self.sha256,
                "status": self.status, "human_approval_status": self.approval, "binding_allowed": self.binding_allowed,
                "synthetic": self.synthetic}

    def view(self) -> dict:
        """The purpose-limited profile view a MAT invocation may see: rules and patterns with their evidence status,
        never source excerpts (the profile holds observation ids only) and never the corpus hashes."""
        def rule_view(r):
            return {k: r.get(k) for k in ("rule_id", "rule_type", "condition", "action", "classification", "confidence", "scope", "counterexamples")} | \
                   {"use": self.rule_status(r["rule_id"])["use"]}
        def ground_view(g):
            return {"rule_id": g["rule_id"], "ground": g["ground"], "classification": g["classification"], "confidence": g["confidence"],
                    "use": self.rule_status(g["rule_id"])["use"], "sample_size": g.get("sample_size", 0)}
        pat = lambda ps: [{"pattern_id": p["pattern_id"], "text": p["text"], "confidence": p["confidence"], "validation_status": p.get("validation_status")} for p in ps]
        return {"binding": self.binding(), "selection_rules": [rule_view(r) for r in self.data.get("selection_rules", [])],
                "withdrawal_grounds": [ground_view(g) for g in self.data.get("withdrawal_rules", [])],
                "writing_patterns": pat(self.data.get("writing_patterns", [])), "question_patterns": pat(self.data.get("question_patterns", [])),
                "recommendation_patterns": pat(self.data.get("recommendation_patterns", [])), "guards": dict(self.data.get("guards", {})),
                "use_note": "ADVISORY rules describe a documented preference and never override evidence, policy or law; "
                            "NOT_ESTABLISHED rules may be named but not relied on; only BINDING rules are instructions."}


def load_profile(path: str | os.PathLike | None = None, *, env: dict | None = None) -> LoadedProfile:
    env = os.environ if env is None else env
    p = Path(path) if path else (Path(env[ENV_PROFILE]) if env.get(ENV_PROFILE) else None)
    if p is None:
        raise ProfileNotConfigured(f"no MAT profile: pass a path or set {ENV_PROFILE}")
    if not p.is_file():
        raise ProfileNotConfigured(f"MAT profile not found: {p}")
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProfileInvalid(f"{p}: not JSON ({exc})") from exc
    errors = validate(PROFILE_SCHEMA, data)
    if errors:
        raise ProfileInvalid(f"{p}: " + "; ".join(errors[:8]))
    return LoadedProfile(data, str(p), hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest(),
                         synthetic=bool(data.get("synthetic")) or str(data.get("label", "")).upper().startswith("SYNTHETIC"))


def synthetic_fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mat" / "synthetic_mat_profile.json"
