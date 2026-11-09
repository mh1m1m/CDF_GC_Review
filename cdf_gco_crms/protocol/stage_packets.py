"""Stage packets of protocol v7.15: supplied sources (19A.3A) and retention against the adjudication (19A.6A).

19A.3A: a provision counts as supplied to a stage only when its verbatim text is in the stage packet with the
particulars of 19A.7 (instrument, publication, status, article, text, location of the evidence). The drafting agent
records such extracts in the round file under ``sources``; every stage packet except READ carries them, and the stage
meta records their SHA-256. Anything not quoted there stays NOT_SUPPLIED.

19A.6A: where the adjudicator proposes ROUTED_OUTSIDE_GCO or WITHHELD_FOR_EVIDENCE for a drafted observation, the GCO
reviewer may retain it before issue. The decision is recorded under the observation's id with the reviewer's role and
date; the adjudication record stays unchanged beside it; the delivery note lists the retained observations with the
adjudicator's ground. The issue gate then accepts the recorded decision instead of moving the observation to
``routed`` or ``withdrawn``.

The digest is the same as chat kit 1.1.2+ (canonical JSON, sorted keys, UTF-8), so a packet built by either side
verifies on the other.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

SUPPLIED, NOT_SUPPLIED = "SUPPLIED", "NOT_SUPPLIED"
SOURCE_FIELDS = ("instrument", "publication", "status", "article", "text", "location")
NO_SOURCES_STAGES = ("READ",)
RETAINABLE = ("ROUTED_OUTSIDE_GCO", "WITHHELD_FOR_EVIDENCE")
RETAIN = "RETAIN"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERSONAL = re.compile(r"(الأخ|الأستاذ|أبو |Mr\.|Ms\.|Mrs\.|Dr\.)")


# ------------------------------------------------------------------------------------------------ 19A.3A
def source_problems(sources: list[dict]) -> list[str]:
    """Each supplied extract carries every particular of 19A.7, with non-empty verbatim text."""
    p = []
    for i, s in enumerate(sources or []):
        missing = [k for k in SOURCE_FIELDS if not str((s or {}).get(k) or "").strip()]
        if missing:
            p.append(f"19A.3A source {i + 1}: missing {', '.join(missing)} (19A.7)")
    return p


def sources_sha256(sources: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sources, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def packet_sources(stage: str, sources: list[dict]) -> tuple[list[dict], dict]:
    """(sources for the packet, meta). READ gets none; every other stage gets all, with their digest."""
    if stage in NO_SOURCES_STAGES or not sources:
        return [], {}
    bad = source_problems(sources)
    if bad:
        raise ValueError("; ".join(bad))
    return list(sources), {"sources_sha256": sources_sha256(sources)}


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def supply_status(citation: dict, packet: list[dict]) -> str:
    """SUPPLIED when the packet quotes the cited provision verbatim (same instrument and article, the quoted text
    contained in the extract); NOT_SUPPLIED otherwise, however well the citation was verified elsewhere."""
    for s in packet or []:
        if _norm(s.get("instrument")) != _norm(citation.get("instrument")):
            continue
        if _norm(s.get("article")) != _norm(citation.get("article")):
            continue
        quoted = _norm(citation.get("text"))
        if quoted and quoted in _norm(s.get("text")):
            return SUPPLIED
    return NOT_SUPPLIED


def verify_packet_meta(meta: dict, sources: list[dict]) -> bool:
    """The stage meta digest matches the sources the packet carried (a later edit is detected)."""
    want = meta.get("sources_sha256")
    return (not sources and not want) or want == sources_sha256(sources)


# ------------------------------------------------------------------------------------------------ 19A.6A
@dataclass(frozen=True)
class RetentionDecision:
    observation_id: str
    reviewer_role: str
    date: str
    decision: str = RETAIN

    @classmethod
    def from_dict(cls, observation_id: str, d: dict) -> "RetentionDecision":
        return cls(observation_id, str(d.get("reviewer_role") or ""), str(d.get("date") or ""),
                   str(d.get("decision") or RETAIN))

    def problems(self) -> list[str]:
        p = []
        if self.decision != RETAIN:
            p.append(f"{self.observation_id}: decision must be {RETAIN} (19A.6A)")
        if not self.reviewer_role.strip():
            p.append(f"{self.observation_id}: reviewer_role missing (19A.6A)")
        elif _PERSONAL.search(self.reviewer_role):
            p.append(f"{self.observation_id}: reviewer_role must be a role, not a person (G-MAT-05)")
        if not _DATE.match(self.date):
            p.append(f"{self.observation_id}: date must be YYYY-MM-DD (19A.6A)")
        return p


def retention_problems(drafted_ids: list[str], dispositions: dict[str, dict], decisions: dict[str, dict]) -> list[str]:
    """Issue-gate problems for drafted observations the adjudicator proposed to route or withhold. A valid recorded
    retention clears the observation; the adjudication record itself is never rewritten."""
    p = []
    for oid in drafted_ids:
        kind = (dispositions.get(oid) or {}).get("disposition")
        if kind not in RETAINABLE:
            continue
        rec = (decisions or {}).get(oid)
        if not rec:
            p.append(f"{oid}: {kind} but still in the draft: move it to 'routed' or 'withdrawn', or record the "
                     "GCO reviewer's decision to retain it (19A.6A)")
            continue
        p += RetentionDecision.from_dict(oid, rec).problems()
    return p


def delivery_note_retained(dispositions: dict[str, dict], decisions: dict[str, dict]) -> list[dict]:
    """The delivery note's list of retained observations, each with the adjudicator's ground beside the decision."""
    out = []
    for oid, rec in sorted((decisions or {}).items()):
        d = dispositions.get(oid) or {}
        if d.get("disposition") in RETAINABLE and not RetentionDecision.from_dict(oid, rec).problems():
            out.append({"id": oid, "adjudicator_disposition": d["disposition"],
                        "adjudicator_ground": d.get("ground") or d.get("reason") or "",
                        "retained_by": rec["reviewer_role"], "date": rec["date"]})
    return out
