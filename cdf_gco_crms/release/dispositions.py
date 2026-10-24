"""Controlled application of adjudicated dispositions to the review register (Article 08).

``apply_dispositions`` is the only path by which a challenge outcome changes an observation's text. It applies
a revision only when a verified, in-date, state-bound human decision authorises it; it never touches an
observation whose current text differs from the text the challenge examined (conflict); it keeps the original
wording in an append-only ledger with full provenance; and it returns the new state fingerprint. Rollback
restores the ledgered original. No AI output reaches the register except through this function and a
human decision.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..assurance.objection_engine import HumanDecision
from ..model.entities import GText, ReviewState, plain_text
from .authorization_gate import state_fingerprint
from .trust import TrustStore

LEDGER_SCHEMA = "CDF-DISPOSITION-LEDGER-v7.12.1"
TEXT_CHANGING = ("UPHELD_WITH_REVISION", "NARROWED_TO_GCO_SCOPE")
NO_TEXT_CHANGE = ("UPHELD_UNCHANGED", "ROUTED_OUTSIDE_GCO", "WITHHELD_FOR_EVIDENCE", "ESCALATED_TO_GCO_REVIEWER")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ApplyResult:
    state: ReviewState
    previous_fingerprint: str
    new_fingerprint: str
    applied: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    ledger_entries: list[dict] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.new_fingerprint != self.previous_fingerprint

    def to_dict(self) -> dict:
        return {"previous_fingerprint": self.previous_fingerprint, "new_fingerprint": self.new_fingerprint,
                "applied": self.applied, "rejected": self.rejected, "conflicts": self.conflicts,
                "ledger_entries": len(self.ledger_entries)}


def _entry_for(record, internal_id: str, challenge_id: str | None):
    for e in record.entries:
        if e.internal_id != internal_id:
            continue
        for o in e.objections:
            if challenge_id is None or o.challenge_id == challenge_id:
                return e, o
    return None, None


def apply_dispositions(state: ReviewState, record, decisions: list, trust: TrustStore, *,
                       expected_fingerprint: str | None = None, now: dt.datetime | None = None,
                       institutional: bool | None = None, ledger_path=None, challenge_map: dict | None = None) -> ApplyResult:
    """Apply human-authorised dispositions of ``record`` to a copy of ``state``.

    ``decisions`` are HumanDecision records; ``challenge_map`` maps decision_id → challenge_id when a decision
    addresses one objection of several on the same observation (otherwise the first blocking or text-changing
    objection of that observation is taken). ``expected_fingerprint`` is the fingerprint the record was made
    for; a different current fingerprint is a conflict and nothing is applied.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    institutional = (not state.document.is_demo) if institutional is None else institutional
    before_fp = state_fingerprint(state)
    result = ApplyResult(state, before_fp, before_fp)
    if expected_fingerprint and expected_fingerprint != before_fp:
        result.conflicts.append({"reason": "STATE_CHANGED_SINCE_CHALLENGE", "expected": expected_fingerprint, "current": before_fp})
        return result
    new_state = copy.deepcopy(state)
    by_id = new_state.by_id()
    for d in decisions:
        if not isinstance(d, HumanDecision):
            result.rejected.append({"item": repr(d)[:60], "reason": "NOT_A_HUMAN_DECISION_RECORD"})
            continue
        reasons = trust.check_decision(d, now=now, fingerprint=before_fp, institutional=institutional)
        if reasons:
            result.rejected.append({"decision_id": d.decision_id, "reason": ",".join(reasons)})
            continue
        obs = by_id.get(d.observation_id)
        if obs is None:
            result.rejected.append({"decision_id": d.decision_id, "reason": "OBSERVATION_NOT_IN_STATE"})
            continue
        entry, objection = _entry_for(record, d.observation_id, (challenge_map or {}).get(d.decision_id))
        if objection is None:
            result.rejected.append({"decision_id": d.decision_id, "reason": "NO_CHALLENGE_FOR_OBSERVATION"})
            continue
        if d.decision not in TEXT_CHANGING + NO_TEXT_CHANGE:
            result.rejected.append({"decision_id": d.decision_id, "reason": "UNKNOWN_OUTCOME"})
            continue
        before_comment, before_quote = plain_text(obs.comment), plain_text(obs.quote)
        entry_text_hash = (objection.adjudication or {}).get("observation_text_sha256") or objection.advocacy.get("observation_text_sha256")
        if entry_text_hash and entry_text_hash != _h(before_comment):
            result.conflicts.append({"decision_id": d.decision_id, "internal_id": obs.internal_id,
                                     "reason": "OBSERVATION_TEXT_CHANGED_SINCE_CHALLENGE"})
            continue
        after_comment, after_quote = before_comment, before_quote
        if d.decision in TEXT_CHANGING:
            rc, rq = objection.advocacy.get("revised_comment"), objection.advocacy.get("revised_quote")
            if not rc and not rq:
                result.rejected.append({"decision_id": d.decision_id, "reason": "NO_AUTHORISED_REVISION_TEXT_IN_RECORD"})
                continue
            if rc:
                obs.comment = GText.plain(rc) if "\n" not in rc else GText([(p, False) for p in [rc]])
                after_comment = rc
            if rq:
                obs.quote = rq
                after_quote = rq
        ledger = {"schema": LEDGER_SCHEMA, "applied_utc": now.replace(microsecond=0).isoformat(),
                  "internal_id": obs.internal_id, "challenge_id": objection.challenge_id, "decision_id": d.decision_id,
                  "disposition": d.decision, "reviewer": d.reviewer, "role": d.role, "reference": d.reference,
                  "decision_timestamp": d.timestamp, "signing_key_id": d.signing_key_id,
                  "before": {"comment": before_comment, "quote": before_quote, "comment_sha256": _h(before_comment)},
                  "after": {"comment": after_comment, "quote": after_quote, "comment_sha256": _h(after_comment)},
                  "text_changed": after_comment != before_comment or after_quote != before_quote,
                  "previous_fingerprint": before_fp, "origin_adjudication": objection.adjudication.get("disposition"),
                  "issued_observation": bool(entry.issued)}
        result.ledger_entries.append(ledger)
        result.applied.append({"decision_id": d.decision_id, "internal_id": obs.internal_id, "disposition": d.decision,
                               "text_changed": ledger["text_changed"]})
    result.state = new_state
    result.new_fingerprint = state_fingerprint(new_state)
    for e in result.ledger_entries:
        e["new_fingerprint"] = result.new_fingerprint
    if ledger_path and result.ledger_entries:
        p = Path(ledger_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for e in result.ledger_entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return result


def rollback(state: ReviewState, ledger_entry: dict) -> tuple[ReviewState, bool]:
    """Restore the ledgered original text when the current text is the ledgered 'after'; returns (state, done)."""
    new_state = copy.deepcopy(state)
    obs = new_state.by_id().get(ledger_entry["internal_id"])
    if obs is None or plain_text(obs.comment) != ledger_entry["after"]["comment"]:
        return state, False
    obs.comment = GText.plain(ledger_entry["before"]["comment"])
    obs.quote = ledger_entry["before"]["quote"]
    return new_state, True


def read_ledger(path) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
