"""Evidence-aware calibration analytics, explicitly separating file changes from human decisions."""
from __future__ import annotations
from collections import Counter
from statistics import mean, median
import json

from .store import CalibrationStore, ReviewerContext

RECOMMENDATIONS = {"DIRECT_RECOMMENDATION", "CONDITIONAL_RECOMMENDATION", "PROPOSED_AMENDMENT"}
QUESTIONS = {"DIRECT_QUESTION", "INFORMATION_REQUEST"}
MIXED = {"QUESTION_WITH_RECOMMENDATION"}


def analyze(store: CalibrationStore, case_id: str, reviewer: ReviewerContext) -> dict:
    observations = store.observations(case_id, reviewer)
    events = store.events(case_id, reviewer)
    latest = {}
    for e in events:
        if e["event_type"] != "OBSERVATION_CALIBRATION":
            continue
        p = json.loads(e["payload_json"])
        if p.get("status") == "SUBMITTED":
            latest[e["observation_id"]] = p

    observed = Counter(o.get("observed_change", "UNKNOWN") for o in observations)
    decisions = Counter(e["decision"] for e in latest.values())
    original = Counter(o.get("primary_type_original", "UNCLASSIFIED") for o in observations
                       if o.get("original_text"))
    reviewed = Counter(o.get("primary_type_reviewed", "UNCLASSIFIED") for o in observations
                       if o.get("reviewed_text"))
    original_words = [len(o.get("original_text", "").split()) for o in observations if o.get("original_text")]
    reviewed_words = [len(o.get("reviewed_text", "").split()) for o in observations if o.get("reviewed_text")]
    def dist(counts):
        total = sum(counts.values())
        return {
            "denominator": total,
            "recommendation_count": sum(counts.get(x, 0) for x in RECOMMENDATIONS),
            "question_count": sum(counts.get(x, 0) for x in QUESTIONS),
            "mixed_count": sum(counts.get(x, 0) for x in MIXED),
            "by_class": dict(counts),
            "question_percent": round(100 * sum(counts.get(x, 0) for x in QUESTIONS) / total, 1) if total else None,
            "recommendation_percent": round(100 * sum(counts.get(x, 0) for x in RECOMMENDATIONS) / total, 1) if total else None,
            "mixed_percent": round(100 * sum(counts.get(x, 0) for x in MIXED) / total, 1) if total else None,
        }
    def lengths(values):
        return {"n": len(values), "mean_words": round(mean(values), 1) if values else None,
                "median_words": median(values) if values else None}
    return {
        "case_id": case_id,
        "evidence_scope": "SINGLE_CASE_DESCRIPTIVE_ONLY",
        "observation_units": len(observations),
        "observed_changes": dict(observed),
        "human_submitted_decisions": dict(decisions),
        "documented_withdrawals_from_file": sum(
            o.get("documented_withdrawal", False) is True for o in observations),
        "human_calibrated_withdrawals": decisions.get("WITHDRAW", 0),
        "unresolved_absences": sum(o.get("observed_change") == "REMOVED_FROM_VERSION"
                                   and o["observation_id"] not in latest for o in observations),
        "original_distribution": dist(original),
        "reviewed_distribution": dist(reviewed),
        "original_lengths": lengths(original_words),
        "reviewed_lengths": lengths(reviewed_words),
        "denominator_note": (
            "Distribution excludes missing/empty comment texts; every observation has one "
            "primary type per source version. File changes are NOT human approvals. "
            "Case-level percentages are descriptive, not MAT preference targets."),
    }
