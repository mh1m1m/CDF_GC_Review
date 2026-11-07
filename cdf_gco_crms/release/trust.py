"""Institutional trust store and decision lifecycle (Article 13.3).

A trust store is a JSON document supplied from an authorised institutional source — never from the review
package. Two formats are accepted:

  legacy   ``{key_id: "<base64 raw Ed25519 public key>"}``  (every key ACTIVE, roles unrestricted, flagged legacy)
  v2       ``{"schema": "CDF-TRUST-STORE-v7.12.1", "keys": {key_id: {"public_key_b64": ..., "status": "ACTIVE" |
           "REVOKED" | "SUSPENDED", "roles": ["GCO reviewer", ...], "holder": ..., "valid_from": ISO,
           "valid_until": ISO | null, "synthetic": bool, "revoked_at": ISO | null}}}``

:func:`check_decision` evaluates one HumanDecision against the store and the review state: key status,
key validity window, reviewer role, decision validity period, observation binding and review-state binding.
A key whose id starts with ``SYNTHETIC`` or whose entry says ``synthetic`` can never authorise an
institutional (non-demo) issue.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

TRUST_SCHEMA = "CDF-TRUST-STORE-v7.12.1"
DECISION_VALIDITY_DAYS = 30
STATUS_ACTIVE, STATUS_REVOKED, STATUS_SUSPENDED = "ACTIVE", "REVOKED", "SUSPENDED"
REVIEWER_ROLES = ("GCO reviewer", "GCO Reviewer", "مراجع GCO", "GCO_REVIEWER")

R_KEY_UNKNOWN = "KEY_UNKNOWN"
R_KEY_REVOKED = "KEY_REVOKED"
R_KEY_SUSPENDED = "KEY_SUSPENDED"
R_KEY_NOT_YET_VALID = "KEY_NOT_YET_VALID"
R_KEY_EXPIRED = "KEY_EXPIRED"
R_ROLE_NOT_PERMITTED = "REVIEWER_ROLE_NOT_PERMITTED"
R_DECISION_EXPIRED = "DECISION_EXPIRED"
R_DECISION_TIMESTAMP = "DECISION_TIMESTAMP_INVALID"
R_OBSERVATION_BINDING = "DECISION_OBSERVATION_BINDING_MISMATCH"
R_STATE_BINDING = "DECISION_NOT_BOUND_TO_REVIEW_STATE"
R_SYNTHETIC_KEY = "SYNTHETIC_KEY_NOT_INSTITUTIONAL"
R_SIGNATURE = "SIGNATURE_INVALID"


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    v = str(value).strip()
    if len(v) == 10:
        v += "T00:00:00+00:00"
    v = v.replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


@dataclass
class KeyEntry:
    key_id: str
    public_key: bytes
    status: str = STATUS_ACTIVE
    roles: tuple[str, ...] = ()
    holder: str = ""
    valid_from: str | None = None
    valid_until: str | None = None
    synthetic: bool = False
    revoked_at: str | None = None
    legacy: bool = False

    @property
    def is_synthetic(self) -> bool:
        return self.synthetic or self.key_id.upper().startswith("SYNTHETIC")


@dataclass
class TrustStore:
    keys: dict[str, KeyEntry] = field(default_factory=dict)
    source: str = ""

    # ----------------------------------------------------------- loading
    @classmethod
    def from_dict(cls, data: dict, source: str = "") -> "TrustStore":
        store = cls(source=source)
        if isinstance(data, dict) and data.get("schema") == TRUST_SCHEMA:
            for kid, e in (data.get("keys") or {}).items():
                store.keys[kid] = KeyEntry(kid, base64.b64decode(e["public_key_b64"]), e.get("status", STATUS_ACTIVE),
                                           tuple(e.get("roles") or ()), e.get("holder", ""), e.get("valid_from"),
                                           e.get("valid_until"), bool(e.get("synthetic", False)), e.get("revoked_at"))
        else:                                                      # legacy {key_id: b64}
            for kid, b64 in (data or {}).items():
                store.keys[kid] = KeyEntry(kid, base64.b64decode(b64), legacy=True)
        return store

    @classmethod
    def load(cls, path) -> "TrustStore":
        p = Path(path)
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")), source=str(p))

    @classmethod
    def from_raw(cls, raw: dict[str, bytes], *, synthetic: bool = False, roles: tuple[str, ...] = ()) -> "TrustStore":
        store = cls()
        for kid, key in raw.items():
            store.keys[kid] = KeyEntry(kid, key, roles=roles, synthetic=synthetic)
        return store

    def to_dict(self) -> dict:
        return {"schema": TRUST_SCHEMA, "keys": {k: {"public_key_b64": base64.b64encode(e.public_key).decode(),
                                                     "status": e.status, "roles": list(e.roles), "holder": e.holder,
                                                     "valid_from": e.valid_from, "valid_until": e.valid_until,
                                                     "synthetic": e.synthetic, "revoked_at": e.revoked_at}
                                                 for k, e in self.keys.items()}}

    def raw_keys(self, *, include_inactive: bool = False) -> dict[str, bytes]:
        """The ``{key_id: bytes}`` mapping HumanDecision.validate expects; inactive keys are left out."""
        return {k: e.public_key for k, e in self.keys.items() if include_inactive or e.status == STATUS_ACTIVE}

    def revoke(self, key_id: str, at: str | None = None) -> None:
        e = self.keys[key_id]
        e.status, e.revoked_at = STATUS_REVOKED, at or dt.datetime.now(dt.timezone.utc).isoformat()

    # ----------------------------------------------------------- checks
    def check_decision(self, decision, *, now: dt.datetime | None = None, fingerprint: str | None = None,
                       institutional: bool = True, observation_id: str | None = None,
                       validity_days: int = DECISION_VALIDITY_DAYS) -> list[str]:
        """Reasons the decision must not be relied on (empty list = acceptable). Signature is checked last."""
        now = now or dt.datetime.now(dt.timezone.utc)
        reasons: list[str] = []
        e = self.keys.get(getattr(decision, "signing_key_id", ""))
        if e is None:
            return [R_KEY_UNKNOWN]
        if e.status == STATUS_REVOKED:
            reasons.append(R_KEY_REVOKED)
        elif e.status != STATUS_ACTIVE:
            reasons.append(R_KEY_SUSPENDED)
        vf, vu = parse_iso(e.valid_from), parse_iso(e.valid_until)
        ts = parse_iso(decision.timestamp)
        if ts is None:
            reasons.append(R_DECISION_TIMESTAMP)
        else:
            if vf and ts < vf:
                reasons.append(R_KEY_NOT_YET_VALID)
            if vu and now > vu:
                reasons.append(R_KEY_EXPIRED)
            until = parse_iso(getattr(decision, "valid_until", "") or None) or (ts + dt.timedelta(days=validity_days))
            if now > until:
                reasons.append(R_DECISION_EXPIRED)
        if e.roles and not e.legacy and decision.role not in e.roles:
            reasons.append(R_ROLE_NOT_PERMITTED)
        if decision.role not in REVIEWER_ROLES and not e.legacy:
            reasons.append(R_ROLE_NOT_PERMITTED)
        if observation_id and decision.observation_id != observation_id:
            reasons.append(R_OBSERVATION_BINDING)
        bound = getattr(decision, "review_state_fingerprint", "") or ""
        if institutional and (not bound or (fingerprint and bound != fingerprint)):
            reasons.append(R_STATE_BINDING)
        elif bound and fingerprint and bound != fingerprint:
            reasons.append(R_STATE_BINDING)
        if institutional and e.is_synthetic:
            reasons.append(R_SYNTHETIC_KEY)
        try:
            decision.validate(self.raw_keys(include_inactive=True))
        except PermissionError:
            reasons.append(R_SIGNATURE)
        return sorted(set(reasons))
