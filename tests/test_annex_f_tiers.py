"""Synthetic checks for the Annex F evidence-tier tool (no institutional text)."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("annex_f_tiers", ROOT / "tools" / "mat_dna" / "annex_f_tiers.py")
tiers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tiers)

PROTOCOL = "\n".join([
    "F.1.01 | E1 | يرجى توضيح آلية احتساب الغرامة في العقد الاصطناعي | نص معدل",
    "F.2.01 | K1 | يرجى إضافة تعريف للطرف الثاني في المسودة | —",
    "F.3.01 | A1 | يرجى حذف البند المكرر في الملحق التجريبي | Inferred: duplicate",
])
REGISTER = {"matches": [
    {"observation_id": "OBS-1", "original_text": "يرجى توضيح آلية احتساب الغرامة في العقد الاصطناعي", "provenance": "ABSENT",
     "replaces_at_same_passage": "OBS-9"},
    {"observation_id": "OBS-2", "original_text": "يرجى إضافة تعريف للطرف الثاني في المسودة", "provenance": "UNCHANGED"},
    {"observation_id": "OBS-3", "original_text": "يرجى حذف البند المكرر في الملحق التجريبي", "provenance": "ABSENT"},
]}


def test_tiers_never_promote_absence_to_a_reason():
    rows = tiers.tier_rows(tiers.parse_rows(PROTOCOL), tiers.normalise_register(REGISTER))
    by = {r["fid"]: r for r in rows}
    assert by["F.1.01"]["file_state"] == "ORIGINAL_ABSENT_NEW_COMMENT_AT_PASSAGE"
    assert by["F.1.01"]["row_claim_contradicted"] is True
    assert by["F.1.01"]["tier"] == "INFERRED_RATIONALE"
    assert by["F.2.01"]["tier"] == "OBSERVED_FILE_CHANGE"
    assert by["F.3.01"]["tier"] == "INFERRED_RATIONALE"


def test_human_records_raise_the_tier():
    cal = {"decisions": {"OBS-3": {"status": "SUBMITTED", "decision": "WITHDRAW", "rationale": "مكرر في الملحق"}},
           "approved_rules": {"R-1": ["OBS-2"]}}
    rows = {r["fid"]: r for r in tiers.tier_rows(tiers.parse_rows(PROTOCOL), tiers.normalise_register(REGISTER), cal)}
    assert rows["F.3.01"]["tier"] == "HUMAN_VALIDATED_RATIONALE"
    assert rows["F.2.01"]["tier"] == "HUMAN_APPROVED_RULE"
    draft = {"decisions": {"OBS-3": {"status": "DRAFT", "decision": "WITHDRAW", "rationale": "x"}}}
    rows = {r["fid"]: r for r in tiers.tier_rows(tiers.parse_rows(PROTOCOL), tiers.normalise_register(REGISTER), draft)}
    assert rows["F.3.01"]["tier"] == "INFERRED_RATIONALE"


def test_personal_reference_scrub():
    honorific, kunya = "الزميل", "أبو"
    text, n = tiers.scrub_personal_references(f"تواصل مع {honorific} {kunya} سالم بخصوص البند")
    assert n == 1 and tiers.ROLE_PLACEHOLDER in text and "سالم" not in text
