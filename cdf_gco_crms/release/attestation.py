"""Release attestation and execution receipts (PR #3 review, Directives 1, 3 and 4).

Three questions the gate must answer from evidence, not labels:

1. **Did the independent final review really run live?** A gate record saying ``mode=LIVE`` is a label. The
   receipt is the trace line written by the runner at invocation time: same Execution_ID, role FINAL_REVIEWER,
   mode LIVE, status OK, a known live provider, a provider-shaped invocation id and a non-empty response hash,
   bound to the review-state fingerprint the review examined (:func:`verify_execution_receipt`).
2. **Were the required roles executed independently?** :func:`verify_live_roles` checks every challenge role
   outcome against its receipt, requires distinct Execution_IDs and Context_IDs per invocation, refuses any
   MOCK / CACHED / DETERMINISTIC substitution, and refuses evidence ids the registry does not hold.
3. **Who vouches for the local gate record?** A :class:`ReleaseAttestation` is an Ed25519 signature, by a key the
   institutional trust store lists with the ``RELEASE_ATTESTOR`` role, over the review-state fingerprint, the
   source-document hash, the challenge-record hash, the role execution proofs, the final-review receipt, the
   human decision ids, a validity interval and the issuance purpose. The gate verifies it at issue time; a caller
   cannot grant itself institutional authority by writing a record it trusts.

Nothing here replaces institutional approval: an attestation says the review evidence is authentic and bound,
not that the institution has approved the issue.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .trust import STATUS_ACTIVE, TrustStore, parse_iso

ATTESTATION_SCHEMA = "CDF-RELEASE-ATTESTATION-v7.12.1"
ROLE_ATTESTOR = "RELEASE_ATTESTOR"
PURPOSE_INSTITUTIONAL = "INSTITUTIONAL_ISSUE"
PURPOSE_DEMO = "DEMO_OR_INTERNAL"
DEFAULT_VALID_HOURS = 72
CHALLENGE_ROLES = ("BLACK_TEAM", "RED_ADVOCATE", "ADJUDICATOR")
FINAL_ROLE = "FINAL_REVIEWER"
KNOWN_LIVE_PROVIDERS = ("anthropic",)
LIVE_INVOCATION_PREFIXES = ("msg_",)          # Anthropic Messages API ids
EMPTY_RESPONSE_HASH = hashlib.sha256(b"").hexdigest()

# receipt / independence reasons
R_RECEIPT_MISSING = "EXECUTION_RECEIPT_MISSING"
R_RECEIPT_ROLE = "EXECUTION_RECEIPT_ROLE_MISMATCH"
R_RECEIPT_NOT_LIVE = "EXECUTION_RECEIPT_NOT_LIVE"
R_RECEIPT_NOT_OK = "EXECUTION_RECEIPT_STATUS_NOT_OK"
R_RECEIPT_PROVIDER = "EXECUTION_RECEIPT_PROVIDER_NOT_LIVE"
R_RECEIPT_INVOCATION = "EXECUTION_RECEIPT_INVOCATION_ID_NOT_PROVIDER_SHAPED"
R_RECEIPT_RESPONSE = "EXECUTION_RECEIPT_RESPONSE_HASH_EMPTY"
R_RECEIPT_HASH_MISMATCH = "EXECUTION_RECEIPT_HASH_MISMATCH"
R_ROLE_NOT_LIVE = "ROLE_NOT_LIVE"
R_ROLE_MISSING = "REQUIRED_ROLE_NOT_EXECUTED"
R_IDS_NOT_UNIQUE = "EXECUTION_IDS_NOT_UNIQUE"
R_CONTEXTS_NOT_UNIQUE = "CONTEXT_IDS_NOT_UNIQUE"
R_EVIDENCE_UNKNOWN = "EVIDENCE_REFERENCE_NOT_IN_REGISTRY"
R_RECEIPT_SOURCE = "EXECUTION_RECEIPT_SOURCE_NOT_PROVIDER_API"
R_RECEIPT_REQUEST_ID = "EXECUTION_RECEIPT_PROVIDER_REQUEST_ID_MISSING"
R_RECEIPT_RUN = "EXECUTION_RECEIPT_FROM_OTHER_RUN"
R_RECEIPT_FINGERPRINT = "EXECUTION_RECEIPT_BOUND_TO_OTHER_REVIEW_STATE"
R_RECEIPT_SYSTEM = "EXECUTION_RECEIPT_ROLE_CONTEXT_MISMATCH"
R_TRACE_CHAIN = "EXECUTION_TRACE_CHAIN_BROKEN"
R_TRACE_HEAD = "EXECUTION_TRACE_HEAD_MISMATCH"
R_PROVIDER_IDS_NOT_UNIQUE = "PROVIDER_REQUEST_IDS_NOT_UNIQUE"
# attestation reasons
R_ATT_SCHEMA = "ATTESTATION_SCHEMA_UNKNOWN"
R_ATT_KEY_UNKNOWN = "ATTESTATION_KEY_UNKNOWN"
R_ATT_KEY_NOT_ATTESTOR = "ATTESTATION_KEY_NOT_RELEASE_ATTESTOR"
R_ATT_KEY_INACTIVE = "ATTESTATION_KEY_INACTIVE"
R_ATT_KEY_SYNTHETIC = "ATTESTATION_KEY_SYNTHETIC"
R_ATT_SIGNATURE = "ATTESTATION_SIGNATURE_INVALID"
R_ATT_EXPIRED = "ATTESTATION_EXPIRED"
R_ATT_NOT_YET_VALID = "ATTESTATION_NOT_YET_VALID"
R_ATT_FINGERPRINT = "ATTESTATION_FINGERPRINT_MISMATCH"
R_ATT_DOCUMENT = "ATTESTATION_DOCUMENT_HASH_MISMATCH"
R_ATT_RECORD = "ATTESTATION_CHALLENGE_RECORD_MISMATCH"
R_ATT_PURPOSE = "ATTESTATION_PURPOSE_MISMATCH"
R_ATT_FINAL_REVIEW = "ATTESTATION_FINAL_REVIEW_MISMATCH"
R_ATT_PROOFS = "ATTESTATION_ROLE_PROOFS_MISMATCH"
R_ATT_DECISIONS = "ATTESTATION_HUMAN_DECISIONS_MISMATCH"


# ------------------------------------------------------------------ receipts
def load_trace(path) -> list[dict]:
    p = Path(path) if path else None
    if p is None or not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def expected_system_hash(role: str) -> str:
    from ..agents import context_builder as CB
    from ..agents.provenance import system_hash
    return system_hash(CB.SYSTEM[role])


def receipt_problems(record: dict | None, *, role: str, response_hash: str | None = None, run_id: str | None = None,
                     fingerprint: str | None = None) -> list[str]:
    """Why a trace line is not an acceptable live execution receipt for ``role`` (empty = acceptable).

    The decisive field is ``Execution_Source`` (derived by the runner from the adapter object): only PROVIDER_API
    counts, and it must carry a provider-originated request id. A declared mode, a provider name or a
    provider-shaped invocation id written by a fixture satisfies none of this.
    """
    if record is None:
        return [R_RECEIPT_MISSING]
    out = []
    if record.get("Agent_Role") != role:
        out.append(R_RECEIPT_ROLE)
    if record.get("Mode") != "LIVE":
        out.append(R_RECEIPT_NOT_LIVE)
    if record.get("Execution_Source") != "PROVIDER_API":
        out.append(f"{R_RECEIPT_SOURCE}:{record.get('Execution_Source')}")
    if not record.get("Provider_Request_ID"):
        out.append(R_RECEIPT_REQUEST_ID)
    if run_id and record.get("Run_ID") != run_id:
        out.append(R_RECEIPT_RUN)
    if fingerprint and record.get("Review_State_Fingerprint") != fingerprint:
        out.append(R_RECEIPT_FINGERPRINT)
    if role in CHALLENGE_ROLES + (FINAL_ROLE,) and record.get("System_Hash") != expected_system_hash(role):
        out.append(R_RECEIPT_SYSTEM)
    if record.get("Execution_Status") != "OK":
        out.append(R_RECEIPT_NOT_OK)
    if str(record.get("Provider", "")).lower() not in KNOWN_LIVE_PROVIDERS:
        out.append(R_RECEIPT_PROVIDER)
    inv = str(record.get("Invocation_ID") or "")
    if not inv or not inv.startswith(LIVE_INVOCATION_PREFIXES):
        out.append(R_RECEIPT_INVOCATION)
    rh = record.get("Response_Hash")
    if not rh or rh == EMPTY_RESPONSE_HASH:
        out.append(R_RECEIPT_RESPONSE)
    if response_hash and rh and rh != response_hash:
        out.append(R_RECEIPT_HASH_MISMATCH)
    return out


def find_receipt(trace_records: list[dict], execution_id: str) -> dict | None:
    for r in trace_records:
        if r.get("Execution_ID") == execution_id:
            return r
    return None


def verify_execution_receipt(trace_records: list[dict], execution_id: str | None, role: str,
                             response_hash: str | None = None, run_id: str | None = None,
                             fingerprint: str | None = None) -> list[str]:
    if not execution_id:
        return [R_RECEIPT_MISSING]
    return receipt_problems(find_receipt(trace_records, execution_id), role=role, response_hash=response_hash,
                            run_id=run_id, fingerprint=fingerprint)


def verify_trace(trace_records: list[dict], expected_head: str | None) -> list[str]:
    """The trace must be an intact hash chain whose head is the one the gate record (and attestation) name."""
    from ..agents.provenance import verify_chain
    if not trace_records:
        return [R_RECEIPT_MISSING]
    ok, head, why = verify_chain(trace_records)
    if not ok:
        return [f"{R_TRACE_CHAIN}:{why}"]
    if expected_head and head != expected_head:
        return [R_TRACE_HEAD]
    return []


# ------------------------------------------------------------------ independence (Directive 3)
def verify_live_roles(role_outcomes: list[dict], trace_records: list[dict], *, required_roles=CHALLENGE_ROLES,
                      registry_ids: set[str] | None = None, run_id: str | None = None, fingerprint: str | None = None,
                      expected_head: str | None = None) -> dict:
    """Independence from evidence: every required role's outcomes carry a verified PROVIDER_API receipt (bound to
    this run and review state, with the role's own instructions), ids and provider request ids are unique, no
    MOCK / CACHED / SIMULATED / DETERMINISTIC result stands in, cited evidence exists in the registry, and the
    trace chain is intact. Separate identifiers alone never establish independence."""
    reasons: list[str] = []
    proofs: list[dict] = []
    seen_exec: list[str] = []
    seen_ctx: list[str] = []
    seen_req: list[str] = []
    chain = verify_trace(trace_records, expected_head)
    if chain:
        reasons.extend(chain)
    present = {o.get("role") for o in role_outcomes}
    for role in required_roles:
        if role not in present:
            reasons.append(f"{R_ROLE_MISSING}:{role}")
    for o in role_outcomes:
        if o.get("role") not in required_roles:
            continue
        if o.get("mode") != "LIVE":
            reasons.append(f"{R_ROLE_NOT_LIVE}:{o.get('role')}:{o.get('mode')}")
            continue
        rec = find_receipt(trace_records, o.get("execution_id"))
        problems = receipt_problems(rec, role=o["role"], run_id=run_id, fingerprint=fingerprint)
        if problems:
            reasons.extend(f"{p}:{o.get('execution_id')}" for p in problems)
            continue
        seen_exec.append(o["execution_id"])
        seen_ctx.append(rec.get("Context_ID"))
        seen_req.append(rec.get("Provider_Request_ID"))
        if registry_ids is not None:
            unknown = [r for r in rec.get("Evidence_References", []) if r not in registry_ids]
            if unknown:
                reasons.append(f"{R_EVIDENCE_UNKNOWN}:{o['execution_id']}:{len(unknown)}")
        proofs.append({"role": o["role"], "execution_id": o["execution_id"], "context_id": rec.get("Context_ID"),
                       "invocation_id": rec.get("Invocation_ID"), "provider_request_id": rec.get("Provider_Request_ID"),
                       "execution_source": rec.get("Execution_Source"), "provider": rec.get("Provider"), "model": rec.get("Model"),
                       "prompt_hash": rec.get("Prompt_Hash"), "response_hash": rec.get("Response_Hash"),
                       "observation_id": o.get("observation_id"), "challenge_id": o.get("challenge_id")})
    if len(seen_exec) != len(set(seen_exec)):
        reasons.append(R_IDS_NOT_UNIQUE)
    if len(seen_ctx) != len(set(seen_ctx)):
        reasons.append(R_CONTEXTS_NOT_UNIQUE)
    if len(seen_req) != len(set(seen_req)):
        reasons.append(R_PROVIDER_IDS_NOT_UNIQUE)
    return {"verified": not reasons and bool(proofs), "reasons": sorted(set(reasons)), "proofs": proofs,
            "live_executions": len(proofs)}


# ------------------------------------------------------------------ attestation (Directive 4)
def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _proof_digest(proofs: list[dict]) -> str:
    rows = sorted((p.get("role", ""), p.get("execution_id", ""), p.get("response_hash", "")) for p in proofs or [])
    return hashlib.sha256(canonical(rows)).hexdigest()


def build_payload(gate_record: dict, *, purpose: str, now: dt.datetime | None = None,
                  valid_hours: int = DEFAULT_VALID_HOURS) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    fr = gate_record.get("final_review") or {}
    return {"schema": ATTESTATION_SCHEMA, "purpose": purpose,
            "fingerprint": gate_record.get("fingerprint"),
            "document_sha256": gate_record.get("source_document_sha256"),
            "challenge_record_sha256": gate_record.get("challenge_record_sha256"),
            "role_proofs_digest": _proof_digest(gate_record.get("role_execution_proofs") or []),
            "role_proofs_count": len(gate_record.get("role_execution_proofs") or []),
            "trace_head_hash": gate_record.get("trace_head_hash"),
            "live_executions": (gate_record.get("independence") or {}).get("live_executions", 0),
            "note": "an attestation authenticates the record; it does not make unverified execution claims true",
            "final_review": {k: fr.get(k) for k in ("execution_id", "response_hash", "recommendation", "mode", "fingerprint")},
            "human_decision_ids": sorted(d.get("decision_id", "") for d in gate_record.get("human_decisions") or []),
            "run_id": (gate_record.get("execution_summary") or {}).get("run_id"),
            "document_code": gate_record.get("document_code"), "round": gate_record.get("round"),
            "valid_from": now.replace(microsecond=0).isoformat(),
            "valid_until": (now + dt.timedelta(hours=valid_hours)).replace(microsecond=0).isoformat()}


@dataclass
class ReleaseAttestation:
    payload: dict
    key_id: str
    signature_b64: str = ""

    def signing_bytes(self) -> bytes:
        return canonical({"payload": self.payload, "key_id": self.key_id})

    def to_dict(self) -> dict:
        return {"schema": ATTESTATION_SCHEMA, "payload": self.payload, "key_id": self.key_id, "signature_b64": self.signature_b64}

    @classmethod
    def from_dict(cls, d: dict) -> "ReleaseAttestation":
        return cls(dict(d.get("payload") or {}), str(d.get("key_id", "")), str(d.get("signature_b64", "")))


def sign(payload: dict, private_key_bytes: bytes, key_id: str) -> ReleaseAttestation:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    att = ReleaseAttestation(payload, key_id)
    att.signature_b64 = base64.b64encode(Ed25519PrivateKey.from_private_bytes(private_key_bytes).sign(att.signing_bytes())).decode()
    return att


def verify(att: dict | ReleaseAttestation | None, trust_store: TrustStore | None, *, now: dt.datetime | None = None,
           fingerprint: str, document_sha256: str | None, challenge_record_sha256: str | None, purpose: str,
           gate_record: dict | None = None) -> list[str]:
    """Reasons the attestation must not be relied on (empty = acceptable)."""
    if att is None:
        return ["ATTESTATION_MISSING"]
    a = att if isinstance(att, ReleaseAttestation) else ReleaseAttestation.from_dict(att)
    now = now or dt.datetime.now(dt.timezone.utc)
    reasons: list[str] = []
    p = a.payload
    if p.get("schema") != ATTESTATION_SCHEMA:
        reasons.append(R_ATT_SCHEMA)
    entry = trust_store.keys.get(a.key_id) if trust_store is not None else None
    if entry is None:
        reasons.append(R_ATT_KEY_UNKNOWN)
    else:
        if ROLE_ATTESTOR not in entry.roles:
            reasons.append(R_ATT_KEY_NOT_ATTESTOR)
        if entry.status != STATUS_ACTIVE:
            reasons.append(f"{R_ATT_KEY_INACTIVE}:{entry.status}")
        key_from, key_until = parse_iso(entry.valid_from), parse_iso(entry.valid_until)
        if ((entry.valid_from and key_from is None) or (entry.valid_until and key_until is None)
                or (key_from and key_until and key_from > key_until)):
            reasons.append("ATTESTATION_KEY_VALIDITY_INVALID")
        if key_from and now < key_from:
            reasons.append("ATTESTATION_KEY_NOT_YET_VALID")
        if key_until and now > key_until:
            reasons.append("ATTESTATION_KEY_EXPIRED")
        if entry.is_synthetic and purpose == PURPOSE_INSTITUTIONAL:
            reasons.append(R_ATT_KEY_SYNTHETIC)
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(entry.public_key).verify(base64.b64decode(a.signature_b64, validate=True), a.signing_bytes())
        except Exception:                      # InvalidSignature, bad base64, bad key
            reasons.append(R_ATT_SIGNATURE)
    vf, vu = parse_iso(p.get("valid_from")), parse_iso(p.get("valid_until"))
    if vf is None or vu is None or now > vu:
        reasons.append(R_ATT_EXPIRED)
    elif now < vf:
        reasons.append(R_ATT_NOT_YET_VALID)
    if p.get("fingerprint") != fingerprint:
        reasons.append(R_ATT_FINGERPRINT)
    if not document_sha256 or p.get("document_sha256") != document_sha256:
        reasons.append(R_ATT_DOCUMENT)
    if not challenge_record_sha256 or p.get("challenge_record_sha256") != challenge_record_sha256:
        reasons.append(R_ATT_RECORD)
    if p.get("purpose") != purpose:
        reasons.append(R_ATT_PURPOSE)
    if gate_record is not None:
        fr = gate_record.get("final_review") or {}
        pf = p.get("final_review") or {}
        if any(pf.get(k) != fr.get(k) for k in ("execution_id", "response_hash", "recommendation", "mode", "fingerprint")):
            reasons.append(R_ATT_FINAL_REVIEW)
        if p.get("role_proofs_digest") != _proof_digest(gate_record.get("role_execution_proofs") or []):
            reasons.append(R_ATT_PROOFS)
        if sorted(p.get("human_decision_ids") or []) != sorted(d.get("decision_id", "") for d in gate_record.get("human_decisions") or []):
            reasons.append(R_ATT_DECISIONS)
        if p.get("trace_head_hash") != gate_record.get("trace_head_hash"):
            reasons.append(R_TRACE_HEAD)
    return sorted(set(reasons))


def load_private_key(path) -> bytes:
    """Raw 32-byte Ed25519 private key from a file holding base64 text or raw bytes (operator-held; never in git)."""
    data = Path(path).read_bytes()
    if len(data) == 32:
        return data
    return base64.b64decode(data.strip())
