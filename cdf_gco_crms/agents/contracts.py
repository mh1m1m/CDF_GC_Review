"""Agent contracts (v7.12 live multi-agent runtime, Articles 03–05 of the activation directive).

Every role exchanges one JSON object with its provider, validated against the role's schema before anything
downstream reads it. The schemas are deliberately narrow: an agent states a finding, its evidence ids and its
reasoning; it never states an approval, a release decision or another role's private content.

Execution modes are kept apart at the type level: ``LIVE`` (a real model inference through a provider adapter),
``MOCK`` (scripted responses for tests), ``CACHED`` (replay of a recorded live response by prompt hash) and
``DETERMINISTIC`` (the rule engine of ``assurance.challenge``). A record never changes mode after the fact.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from ..assurance.challenge import DISPOSITIONS, KINDS, STANCES

SCHEMA_VERSION = "CDF-AGENT-CONTRACTS-v7.12.1"

ROLE_DRAFTING = "DRAFTING"
ROLE_BLACK = "BLACK_TEAM"
ROLE_RED = "RED_ADVOCATE"
ROLE_ADJUDICATOR = "ADJUDICATOR"
ROLE_EDITORIAL = "EDITORIAL"
ROLE_FINAL = "FINAL_REVIEWER"
ROLES = (ROLE_DRAFTING, ROLE_BLACK, ROLE_RED, ROLE_ADJUDICATOR, ROLE_EDITORIAL, ROLE_FINAL)

MODE_LIVE = "LIVE"
MODE_MOCK = "MOCK"
MODE_CACHED = "CACHED"
MODE_DETERMINISTIC = "DETERMINISTIC"
MODES = (MODE_LIVE, MODE_MOCK, MODE_CACHED, MODE_DETERMINISTIC)

STATUS_OK = "OK"
STATUS_PROVIDER_FAILURE = "PROVIDER_FAILURE"
STATUS_SCHEMA_INVALID = "SCHEMA_INVALID"
STATUS_REFUSED = "REFUSED"
STATUS_NOT_RUN = "NOT_RUN"

NO_MATERIAL_OBJECTION = "NO_MATERIAL_OBJECTION"
OBJECTION_KINDS = tuple(KINDS) + (NO_MATERIAL_OBJECTION,)
RELEASE_READY, RELEASE_NOT_READY, RELEASE_CONDITIONAL = "READY", "NOT_READY", "READY_WITH_CONDITIONS"


def _s(**kw) -> dict:
    return {"type": "string", **kw}


def _arr(items: dict, **kw) -> dict:
    return {"type": "array", "items": items, **kw}


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or sorted(properties),
            "additionalProperties": False}


_EVIDENCE_IDS = _arr(_s(pattern=r"^EV-[0-9a-f]{12}$"), description="evidence ids from the payload only")

DRAFTING_SCHEMA = _obj({
    "observations": _arr(_obj({
        "location": _s(), "quote": _s(), "finding": _s(), "recommendation": _s(),
        "proposed_wording": {"type": ["string", "null"]},
        "basis_type": _s(enum=["LEGAL_REQUIREMENT", "GOVERNANCE_IMPROVEMENT", "UNCERTAIN"]),
        "jurisdiction": _s(enum=["GCO", "OUTSIDE_GCO", "UNCERTAIN"]),
        "evidence_refs": _EVIDENCE_IDS,
        "evidence_sufficient": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    })),
    "gaps_not_drafted": _arr(_s(), description="material concerns left out because the evidence does not support them"),
    "reasoning_summary": _s(maxLength=1200),
})

BLACK_TEAM_SCHEMA = _obj({
    "material_objection": {"type": "boolean"},
    "objection_kind": _s(enum=list(OBJECTION_KINDS)),
    "challenged_claim": _s(),
    "proposition": _s(description="the objection as the receiving department would state it; empty when none"),
    "material_consequence": _s(),
    "evidence_refs": _EVIDENCE_IDS,
    "existing_controls": _arr(_s()),
    "requested_correction": _s(),
    "reasoning_summary": _s(maxLength=1200),
    "evidence_limitations": _s(),
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
})

RED_ADVOCATE_SCHEMA = _obj({
    "stance": _s(enum=list(STANCES)),
    "objection_accepted": {"type": "boolean"},
    "reasoning": _s(maxLength=1600),
    "evidence_refs": _EVIDENCE_IDS,
    "revised_comment": {"type": ["string", "null"]},
    "revised_quote": {"type": ["string", "null"]},
    "route_to": {"type": ["string", "null"]},
    "missing_evidence": _arr(_s()),
    "escalate": {"type": "boolean"},
    "new_argument": {"type": "boolean", "description": "false when the reply only repeats an earlier argument"},
})

ADJUDICATOR_SCHEMA = _obj({
    "disposition": _s(enum=list(DISPOSITIONS)),
    "objection_valid": {"type": "boolean"},
    "rationale": _s(maxLength=1600),
    "decisive_evidence": _EVIDENCE_IDS,
    "inadmissible_refs": _arr(_s()),
    "facts": _arr(_s()),
    "inferences": _arr(_s()),
    "unverified_assumptions": _arr(_s()),
    "remedy_assessment": _s(),
    "open_question": {"type": ["string", "null"]},
    "escalate": {"type": "boolean"},
})

EDITORIAL_SCHEMA = _obj({
    "revised_comment": _s(),
    "finding_part": _s(),
    "recommendation_part": _s(),
    "proposed_title": _s(maxLength=90),
    "changes": _arr(_s()),
    "preserved_references": _arr(_s()),
    "house_style": _obj({"finding_before_recommendation": {"type": "boolean"}, "no_accusation": {"type": "boolean"},
                         "action_labelled": {"type": "boolean"}, "within_word_ceiling": {"type": "boolean"}}),
    "requires_human_approval": {"type": "boolean", "enum": [True]},
})

FINAL_REVIEWER_SCHEMA = _obj({
    "release_recommendation": _s(enum=[RELEASE_READY, RELEASE_NOT_READY, RELEASE_CONDITIONAL]),
    "findings": _arr(_obj({"observation_id": _s(), "issue": _s(), "severity": _s(enum=["CRITICAL", "MAJOR", "MINOR"]),
                           "evidence_refs": _EVIDENCE_IDS})),
    "unresolved_critical_objections": _arr(_s()),
    "contradictions": _arr(_s()),
    "jurisdiction_consistent": {"type": "boolean"},
    "unsupported_or_excessive": _arr(_s()),
    "summary": _s(maxLength=1600),
})

SCHEMAS: dict[str, dict] = {ROLE_DRAFTING: DRAFTING_SCHEMA, ROLE_BLACK: BLACK_TEAM_SCHEMA, ROLE_RED: RED_ADVOCATE_SCHEMA,
                            ROLE_ADJUDICATOR: ADJUDICATOR_SCHEMA, ROLE_EDITORIAL: EDITORIAL_SCHEMA,
                            ROLE_FINAL: FINAL_REVIEWER_SCHEMA}


# ----------------------------------------------------------------- validation
def validate(schema: dict, value: Any, path: str = "$") -> list[str]:
    """A small JSON-schema validator for the subset the contracts use (type, enum, required, properties,
    additionalProperties, items, pattern, maxLength, minimum, maximum). Returns the list of violations."""
    errors: list[str] = []
    types = schema.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        if not any(_is_type(value, t) for t in allowed):
            return [f"{path}: expected {allowed}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    if isinstance(value, dict) and "properties" in schema:
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: missing")
        for key, sub in value.items():
            if key in schema["properties"]:
                errors.extend(validate(schema["properties"][key], sub, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unexpected property")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(validate(schema["items"], item, f"{path}[{i}]"))
    return errors


def _is_type(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "null":
        return value is None
    return False


# ----------------------------------------------------------------- hashing / ids
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


# ----------------------------------------------------------------- request / response
@dataclass
class AgentRequest:
    """One purpose-limited invocation: a role, its instructions, the payload it may see and the schema it must return."""
    role: str
    system: str
    payload: dict
    schema: dict
    agent_id: str = ""
    max_tokens: int = 4096
    model: str | None = None

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"unknown role {self.role!r}")
        if not self.agent_id:
            self.agent_id = f"AGENT-{self.role}"

    @property
    def user_text(self) -> str:
        return (f"PAYLOAD (the only material you may use):\n{json.dumps(self.payload, ensure_ascii=False, indent=1)}\n\n"
                f"Return exactly one JSON object that validates against this schema, and nothing else:\n"
                f"{json.dumps(self.schema, ensure_ascii=False)}")

    @property
    def prompt_hash(self) -> str:
        return sha256_text(canonical_json({"role": self.role, "system": self.system, "payload": self.payload,
                                           "schema": self.schema, "model": self.model}))

    @property
    def context_id(self) -> str:
        return "CTX-" + self.prompt_hash[:24]


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentResponse:
    role: str
    agent_id: str
    execution_id: str
    context_id: str
    mode: str
    provider: str
    model: str
    status: str
    output: dict | None
    prompt_hash: str
    response_hash: str
    invocation_id: str
    timestamp: str
    latency_ms: int
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    error: str | None = None
    schema_errors: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    execution_source: str = "FAILED"            # provenance.classify_adapter: derived from the adapter object, never declared
    provider_request_id: str | None = None      # provider-originated (HTTP request-id); None for anything not PROVIDER_API
    system_hash: str = ""                       # sha256 of the role instructions actually sent (role-context check)
    fingerprint: str | None = None              # review-state fingerprint the invocation served
    run_id: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and self.output is not None

    @property
    def is_live(self) -> bool:
        """A genuine provider inference: trusted execution source and a usable result — never a declared mode."""
        return self.execution_source == "PROVIDER_API" and self.status == STATUS_OK

    def to_record(self) -> dict:
        """Article 16 evidence record (sanitised: no prompt text, no payload, no credentials)."""
        return {"Agent_ID": self.agent_id, "Agent_Role": self.role, "Execution_ID": self.execution_id,
                "Context_ID": self.context_id, "Provider": self.provider, "Model": self.model, "Mode": self.mode,
                "Invocation_ID": self.invocation_id, "Timestamp": self.timestamp, "Prompt_Hash": self.prompt_hash,
                "Response_Hash": self.response_hash, "Token_Usage": self.token_usage.to_dict(), "Latency_ms": self.latency_ms,
                "Execution_Status": self.status, "Evidence_References": list(self.evidence_refs),
                "Error": self.error, "Schema_Errors": list(self.schema_errors),
                "Execution_Source": self.execution_source, "Provider_Request_ID": self.provider_request_id,
                "System_Hash": self.system_hash, "Review_State_Fingerprint": self.fingerprint, "Run_ID": self.run_id,
                "Provider_Originated": ["Invocation_ID", "Provider_Request_ID", "Model", "Token_Usage"],
                "Locally_Generated": ["Execution_ID", "Context_ID", "Prompt_Hash", "Response_Hash", "Timestamp", "Latency_ms"]}
