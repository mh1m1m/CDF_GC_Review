"""19A.3A supplied sources and 19A.6A retention against the adjudication (v7.15)."""
import copy

import pytest

from cdf_gco_crms.protocol import stage_packets as SP

SRC = [{"instrument": "نظام افتراضي للمنافسة", "publication": "جريدة افتراضية، العدد 1", "status": "نافذ",
        "article": "المادة 5", "text": "يلتزم المتعاقد بتقديم ضمان نهائي خلال عشرة أيام.",
        "location": "SYN-EVIDENCE-01 ص 3"}]


def test_read_gets_no_sources_and_other_stages_carry_them_with_digest():
    assert SP.packet_sources("READ", SRC) == ([], {})
    srcs, meta = SP.packet_sources("CHALLENGE", SRC)
    assert srcs == SRC and meta["sources_sha256"] == SP.sources_sha256(SRC)
    assert SP.verify_packet_meta(meta, SRC)
    edited = copy.deepcopy(SRC)
    edited[0]["text"] += " "
    assert not SP.verify_packet_meta(meta, edited)


def test_digest_matches_the_chat_kit():
    import hashlib
    import json
    assert SP.sources_sha256(SRC) == hashlib.sha256(
        json.dumps(SRC, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def test_source_without_its_particulars_is_refused():
    bad = [dict(SRC[0], publication="")]
    assert SP.source_problems(bad) and "publication" in SP.source_problems(bad)[0]
    with pytest.raises(ValueError):
        SP.packet_sources("ADJUDICATE", bad)


def test_supplied_only_when_quoted_verbatim_in_the_packet():
    cite = {"instrument": "نظام افتراضي للمنافسة", "article": "المادة 5", "text": "تقديم ضمان نهائي خلال عشرة أيام"}
    assert SP.supply_status(cite, SRC) == SP.SUPPLIED
    assert SP.supply_status(dict(cite, article="المادة 6"), SRC) == SP.NOT_SUPPLIED
    assert SP.supply_status(dict(cite, text="ضمان ابتدائي"), SRC) == SP.NOT_SUPPLIED
    assert SP.supply_status(cite, []) == SP.NOT_SUPPLIED          # verified elsewhere is not supplied (19A.3A)


DISP = {"OBS-1": {"disposition": "ROUTED_OUTSIDE_GCO", "ground": "المسألة من اختصاص وحدة أخرى"},
        "OBS-2": {"disposition": "UPHELD"}}


def test_routed_observation_left_in_the_draft_blocks_issue():
    assert SP.retention_problems(["OBS-1", "OBS-2"], DISP, {})[0].startswith("OBS-1: ROUTED_OUTSIDE_GCO")


def test_recorded_retention_clears_it_and_lists_it_with_the_ground():
    dec = {"OBS-1": {"decision": "RETAIN", "reviewer_role": "مراجع إدارة الحوكمة والامتثال", "date": "2026-11-08"}}
    assert SP.retention_problems(["OBS-1", "OBS-2"], DISP, dec) == []
    note = SP.delivery_note_retained(DISP, dec)
    assert note == [{"id": "OBS-1", "adjudicator_disposition": "ROUTED_OUTSIDE_GCO",
                     "adjudicator_ground": "المسألة من اختصاص وحدة أخرى",
                     "retained_by": "مراجع إدارة الحوكمة والامتثال", "date": "2026-11-08"}]
    assert DISP["OBS-1"]["disposition"] == "ROUTED_OUTSIDE_GCO"     # the adjudication record is unchanged


@pytest.mark.parametrize("rec, rule", [
    ({"reviewer_role": "", "date": "2026-11-08"}, "reviewer_role missing"),
    ({"reviewer_role": "الأستاذ فلان", "date": "2026-11-08"}, "a role, not a person"),
    ({"reviewer_role": "مراجع", "date": "8/11/2026"}, "YYYY-MM-DD"),
    ({"reviewer_role": "مراجع", "date": "2026-11-08", "decision": "APPROVE"}, "must be RETAIN"),
])
def test_incomplete_retention_does_not_clear_the_gate(rec, rule):
    probs = SP.retention_problems(["OBS-1"], DISP, {"OBS-1": rec})
    assert probs and rule in probs[0]
    assert SP.delivery_note_retained(DISP, {"OBS-1": rec}) == []
