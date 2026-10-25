#!/usr/bin/env python3
"""Evidence tiers for house-exemplar rows (protocol Annex F, v7.13 F.0) from forensic and calibration records.

Generic and content-free: it reads private inputs (the exemplar rows of a protocol file, an observation-evolution
register produced by ``ooxml_forensics.py`` and, optionally, a calibration export) and writes a private tier table.
Nothing it reads or writes belongs in the public repository.

Tiers, never merged into one claim:
  OBSERVED_FILE_CHANGE        the reviewed file shows this wording (an edit, an unchanged comment or a new comment)
  INFERRED_RATIONALE          a reason or routed class written by an agent or analyst; the files record no reason
  HUMAN_VALIDATED_RATIONALE   a human recorded the decision and its reason in the calibration workspace
  HUMAN_APPROVED_RULE         a separate rule review approved a general rule that cites this observation

An exemplar row whose original comment is absent from the reviewed file is ``ORIGINAL_ABSENT`` whatever the row
claims; when a different comment was created at the same passage it is ``ORIGINAL_ABSENT_NEW_COMMENT_AT_PASSAGE``.
Rows touching a material category (calibration.materiality) are flagged ``MATERIAL_PENDING_HUMAN_CALIBRATION`` until
a human decision exists.

Usage:
  python tools/mat_dna/annex_f_tiers.py --protocol PROTOCOL.txt --register REGISTER.json [--calibration CAL.json] --out TIERS.json
The calibration export is ``{"decisions": {observation_id: {"status", "decision", "rationale"}}, "approved_rules":
{rule_id: [observation_id, ...]}}`` (see ``export_calibration``).
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TIERS = ("OBSERVED_FILE_CHANGE", "INFERRED_RATIONALE", "HUMAN_VALIDATED_RATIONALE", "HUMAN_APPROVED_RULE")
ROW = re.compile(r"^(F\.[1-3]\.\d\d) \| (.*)$")
_NOISE = re.compile(r"الملاحظة\s*#\s*\d+|REF:\s*\S+|[ً-ْـ]")
KUNYA = re.compile(r"(?:الأخ|الاخ|الأخت|الاخت|الزميل|الزميلة)\s+(?:أبو|ابو|أبا|ابا|أم|ام)\s+[^\s،؟?.]+")
ROLE_PLACEHOLDER = "[الجهة المختصة]"


def _n(text: str) -> str:
    return re.sub(r"\s+", " ", _NOISE.sub("", text or "")).strip()


def normalise_register(reg) -> list[dict]:
    """Accept the forensic comparison output (``matches``, lower-case keys) or the evolution register (``rows``)."""
    if isinstance(reg, dict) and "matches" in reg:
        return [{"Observation_ID": m["observation_id"], "Original_Comment": m.get("original_text", ""),
                 "MAT_Comment": m.get("reviewed_text", ""), "Provenance": m.get("provenance", ""),
                 "Replaces_At_Same_Passage": m.get("replaces_at_same_passage", "")} for m in reg["matches"]]
    rows = reg.get("rows", []) if isinstance(reg, dict) else list(reg)
    return [dict(r) for r in rows]


def parse_rows(protocol_text: str) -> list[dict]:
    """Exemplar rows of sections F.1 (edited), F.2 (kept) and F.3 (absent) as {fid, section, cols}."""
    out = []
    for line in protocol_text.splitlines():
        m = ROW.match(line)
        if m:
            fid = m.group(1)
            out.append({"fid": fid, "section": fid[:3], "cols": [c.strip() for c in m.group(2).split(" | ")], "line": line})
    return out


def _before_text(row: dict) -> str:
    cols = row["cols"]
    before = cols[1] if len(cols) > 1 else ""
    if before in ("—", "-", "") and len(cols) > 2:          # a new comment row: the adopted text is the only text
        before = cols[2]
    return before


def match(row: dict, register_rows: list[dict]) -> tuple[dict | None, float]:
    probe = _n(_before_text(row))[:160]
    best, score = None, 0.0
    for r in register_rows:
        text = _n(r.get("Original_Comment") or r.get("MAT_Comment") or "")[:160]
        s = difflib.SequenceMatcher(None, probe, text).ratio()
        if s > score:
            best, score = r, s
    return best, round(score, 2)


def material_categories(text: str) -> list[str]:
    from cdf_gco_crms.calibration.materiality import material_review_flags
    return sorted(material_review_flags(text or "", None, absent=False))


def scrub_personal_references(text: str) -> tuple[str, int]:
    return KUNYA.subn(ROLE_PLACEHOLDER, text or "")


def tier_rows(rows: list[dict], register_rows: list[dict], calibration: dict | None = None, *, min_score: float = 0.8) -> list[dict]:
    calibration = calibration or {}
    decisions = calibration.get("decisions", {})
    rule_cites = {}
    for rule, obs_ids in (calibration.get("approved_rules") or {}).items():
        for oid in obs_ids:
            rule_cites.setdefault(oid, []).append(rule)
    by_passage: dict[str, list[dict]] = {}
    for r in register_rows:
        if r.get("Provenance") == "NEW_COMMENT":
            by_passage.setdefault(r.get("Observation_ID", ""), []).append(r)
    out = []
    for row in rows:
        reg, score = match(row, register_rows)
        oid = reg.get("Observation_ID") if reg and score >= min_score else None
        provenance = reg.get("Provenance") if oid else "UNMATCHED"
        absent = provenance == "ABSENT"
        new_at_passage = bool(oid and reg.get("Replaces_At_Same_Passage"))
        state = ("ORIGINAL_ABSENT_NEW_COMMENT_AT_PASSAGE" if absent and new_at_passage
                 else "ORIGINAL_ABSENT" if absent else provenance)
        decision = decisions.get(oid) if oid else None
        if oid in rule_cites:
            tier = "HUMAN_APPROVED_RULE"
        elif decision and decision.get("status") in ("SUBMITTED", "APPROVED") and (decision.get("rationale") or "").strip():
            tier = "HUMAN_VALIDATED_RATIONALE"
        elif row["section"] == "F.3" or absent:
            tier = "INFERRED_RATIONALE"                      # the files show the absence, never its reason
        else:
            tier = "OBSERVED_FILE_CHANGE"
        cats = material_categories(" ".join(row["cols"][1:3]))
        _, personal = scrub_personal_references(row["line"])
        out.append({"fid": row["fid"], "section": row["section"], "observation_id": oid, "match_score": score,
                    "provenance": provenance, "file_state": state, "tier": tier,
                    "row_claim_contradicted": bool(row["section"] == "F.1" and absent),
                    "material_categories": cats,
                    "material_flag": "MATERIAL_PENDING_HUMAN_CALIBRATION" if cats and tier in ("INFERRED_RATIONALE",) else
                                     ("MATERIAL" if cats else None),
                    "personal_references": personal,
                    "human_decision": decision, "approved_rules": rule_cites.get(oid, [])})
    return out


def export_calibration(store, case_id: str) -> dict:
    """Calibration export from a CalibrationStore: latest effective decision per observation and the observations
    cited by rules whose latest review is APPROVE (the input of ``tier_rows``)."""
    states = store.decision_states(case_id)
    rationale = {}
    for e in store._decision_events(case_id):
        rationale[e["event_hash"]] = e["payload"].get("rationale", "")
    decisions = {oid: {"status": s["status"], "decision": s["decision"], "rationale": rationale.get(s["decision_event_hash"], "")}
                 for oid, s in states.items()}
    latest_rule: dict[str, dict] = {}
    for r in store.db.execute("SELECT payload_json FROM events WHERE case_id=? AND event_type='DNA_RULE_REVIEW' ORDER BY event_id", (case_id,)):
        p = json.loads(r["payload_json"])
        latest_rule[p["rule_id"]] = p
    by_hash = {s["decision_event_hash"]: oid for oid, s in states.items()}
    approved = {rid: sorted({by_hash[h] for h in p["observation_event_hashes"] if h in by_hash})
                for rid, p in latest_rule.items() if p["action"] == "APPROVE"}
    return {"decisions": decisions, "approved_rules": approved}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--register", required=True, help="observation-evolution register JSON (rows)")
    ap.add_argument("--calibration", help="calibration export JSON (optional)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    register_rows = normalise_register(json.loads(Path(a.register).read_text(encoding="utf-8")))
    calibration = json.loads(Path(a.calibration).read_text(encoding="utf-8")) if a.calibration else None
    tiers = tier_rows(parse_rows(Path(a.protocol).read_text(encoding="utf-8")), register_rows, calibration)
    Path(a.out).write_text(json.dumps({"schema": "CDF-ANNEX-F-TIERS-v1", "rows": tiers}, ensure_ascii=False, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for t in tiers:
        counts[t["tier"]] = counts.get(t["tier"], 0) + 1
    print(json.dumps({"rows": len(tiers), "tiers": counts,
                      "row_claims_contradicted": [t["fid"] for t in tiers if t["row_claim_contradicted"]],
                      "material_pending": [t["fid"] for t in tiers if t["material_flag"] == "MATERIAL_PENDING_HUMAN_CALIBRATION"],
                      "personal_references": [t["fid"] for t in tiers if t["personal_references"]],
                      "unmatched": [t["fid"] for t in tiers if t["observation_id"] is None]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
