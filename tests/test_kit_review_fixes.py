"""Regressions from the code review of the v7.15 kit (2026-11-09)."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kit"))
import cdfkit as K  # noqa: E402
import kit_stages as KS  # noqa: E402
from cdf_gco_crms.documents.annotate import find_block  # noqa: E402
from cdf_gco_crms.documents.ingest import Block, SourceText  # noqa: E402


def _example():
    spec = json.loads((ROOT / "kit/examples/draft-round1.example.json").read_text(encoding="utf-8"))
    KS.ensure_ids(spec)                       # stage-packet numbers the observations
    return spec


def test_read_sample_must_name_comments_of_the_packet():
    meta = {"comments": [f"{i:02d}" for i in range(1, 9)], "critical": []}
    fake = [str(n) for n in range(91, 96)]
    result = {"sample": fake, "seed": 7,
              "scores": {s: {r: 1 for r in KS.THRESHOLDS} for s in fake}}
    probs = KS.validate("READ", result, {}, meta)
    assert any("not comments of this packet" in p for p in probs)
    assert any(p.startswith("sample of 0 < 5") for p in probs)


def test_gate_reports_an_observation_without_id_instead_of_crashing():
    spec = _example()
    spec["observations"].append({k: v for k, v in spec["observations"][0].items() if k != "id"})
    spec["stages"] = {"ADJUDICATE": {"dispositions": [{"id": o["id"], "disposition": "UPHELD"}
                                                      for o in spec["observations"] if o.get("id")]}}
    probs = KS.gate(spec, None, 1)
    assert any("observations without id" in p for p in probs)


def test_human_review_goes_stale_when_a_comment_changes():
    spec = _example()
    obs = spec["observations"]
    fps = {o["id"]: KS.obs_fingerprint(o) for o in obs}
    spec["stages"] = {"HUMAN-REVIEW": {"covers": "all", "meta": {"obs_fingerprints": fps}}}
    assert not any("HUMAN-REVIEW record is stale" in p for p in KS.gate(spec, None, 1))
    obs[0]["recommendation"] = obs[0].get("recommendation", "") + " مع تحديث المدة."
    assert any("HUMAN-REVIEW record is stale" in p for p in KS.gate(spec, None, 1))
    spec["stages"]["HUMAN-REVIEW"]["meta"] = {}                 # a record from before kit 1.2.0
    assert any("HUMAN-REVIEW record is stale" in p for p in KS.gate(spec, None, 1))


def test_a_prefix_shared_by_two_blocks_is_not_a_placement():
    head = "يلتزم الطرف الثاني بتقديم تقرير ربع سنوي عن سير الأعمال"
    src = SourceText("pdf", [Block(0, head + " إلى فريق العمل.", "p1"), Block(1, head + " إلى الصندوق.", "p2")])
    assert find_block(src, head + " إلى لجنة غير موجودة في النص") is None
    one = SourceText("pdf", [Block(0, head + " إلى فريق العمل.", "p1"), Block(1, "نص آخر لا علاقة له.", "p2")])
    assert find_block(one, head + " إلى فريق العمل وتستمر في الكتلة التالية") is one.blocks[0]


def test_xlsx_rendition_goes_to_a_new_folder_and_follows_a_revised_source(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    src = tmp_path / "plan.xlsx"

    def write(text):
        wb = openpyxl.Workbook()
        wb.active["A1"] = text
        wb.save(src)
    write("البند الأول من الخطة")
    out = K.review_docx(src, tmp_path / "new" / "folder")
    assert out.exists()
    first = out.read_bytes()
    import os
    import time
    write("البند الأول بعد التعديل")
    later = time.time() + 5
    os.utime(src, (later, later))
    assert K.review_docx(src, tmp_path / "new" / "folder").read_bytes() != first


def test_transcribed_mark_survives_the_delivered_word_file(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("نص منسوخ")
    d.core_properties.keywords = K.TRANSCRIBED_MARK
    path = tmp_path / "round.docx"
    d.save(path)
    K.set_docx_properties(path, "round", working_copy=True)
    assert K.is_transcribed(path)
    with zipfile.ZipFile(path) as z:
        from cdf_gco_crms.release.authorization_gate import WORKING_COPY_KEYWORD
        assert WORKING_COPY_KEYWORD in z.read("docProps/core.xml").decode("utf-8")
