"""TEST 34 — public SYNTHETIC reference fixture (forensic finding B: the public repository must be testable in full).

These tests run from a fresh public clone: they exercise the reference layer (02.6, D.13), the recipient persona
(03A) and the grounded challenge (19A) on ``cdf_gco_crms.references.synthetic_index`` alone. The fixture is
fictional throughout and is labelled SYNTHETIC in every status it carries.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdf_gco_crms.assurance import challenge as CH  # noqa: E402
from cdf_gco_crms.assurance.evidence import EvidenceRegistry  # noqa: E402
from cdf_gco_crms.assurance.personas import RecipientPersona  # noqa: E402
from cdf_gco_crms.model.entities import Document  # noqa: E402
from cdf_gco_crms.references import synthetic_index as SX  # noqa: E402
from cdf_gco_crms.references.authority_matrix import ROLE_APPROVE, ROLE_PREPARE  # noqa: E402
from cdf_gco_crms.references.index import APPLICABILITY, ReferenceIndex  # noqa: E402
from cdf_gco_crms.references.org_structure import Unit  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import build_round1  # noqa: E402
from conftest import base_obs  # noqa: E402
from test_word_lifecycle import build_reviewed_doc  # noqa: E402

DEPT = "الحوكمة والامتثال"


@pytest.fixture(scope="module")
def syn() -> ReferenceIndex:
    return SX.synthetic_reference_index()


# ------------------------------------------------------------------ labelling and shape
def test_fixture_is_labelled_synthetic_everywhere(syn):
    assert syn.mode == SX.MODE_SYNTHETIC and SX.is_synthetic(syn)
    for key in ("org_structure", "authority_matrix"):
        src = syn.sources[key]
        assert src.approval_status == SX.SYNTHETIC_APPROVAL and src.hash_status == SX.HASH_SYNTHETIC
        assert src.file.startswith("SYNTHETIC-") and src.recorded_sha256 is None and src.applicability == APPLICABILITY
        assert "SYNTHETIC" in src.approval_evidence
    assert SX.SYNTHETIC_LABEL in syn.org.title and SX.SYNTHETIC_LABEL in syn.matrix.title
    rep = syn.sources_report()
    assert rep["mode"] == SX.MODE_SYNTHETIC
    assert not SX.is_synthetic(None)


def test_fixture_is_deterministic_and_round_trips(tmp_path):
    a, b = SX.synthetic_reference_index(), SX.synthetic_reference_index()
    assert a.org.to_dict() == b.org.to_dict() and a.matrix.to_dict() == b.matrix.to_dict()
    assert a.sources["org_structure"].computed_sha256 == b.sources["org_structure"].computed_sha256
    a.export_json(tmp_path)
    back = ReferenceIndex.from_export(tmp_path)
    assert back.mode == SX.MODE_SYNTHETIC and back.org.to_dict() == a.org.to_dict()
    assert back.sources["authority_matrix"].hash_status == SX.HASH_SYNTHETIC


def test_coverage_and_queries(syn):
    cov = syn.coverage()
    assert cov["org_structure"]["units_with_tasks"] == cov["org_structure"]["units"] >= 7
    assert cov["authority_matrix"]["items_partial_confidence"] == 0 and cov["authority_matrix"]["items_with_decision_owner"] >= 6
    assert DEPT in syn.org.departments()
    ok, canonical, _ = syn.validate_department("إدارة " + DEPT)
    assert ok and canonical == DEPT
    ok, canonical, cands = syn.validate_department("وحدة لا وجود لها")
    assert not ok and canonical is None and cands == []
    m = syn.org.mandate(DEPT)
    assert m and m.page == syn.org.unit(DEPT).page and len(m.tasks) >= 5
    chain = syn.matrix.chain("2.1")
    assert chain[0][0] == ROLE_PREPARE and chain[-1][0] == ROLE_APPROVE
    assert syn.matrix.decision_owner("2.2") == SX.B_CEO
    assert [it.number for it in syn.matrix.find_items("مذكرات التفاهم")] == ["2.1"]


# ------------------------------------------------------------------ loader policy
def test_loader_policy(monkeypatch):
    assert SX.load_reference_index(synthetic="always").mode == SX.MODE_SYNTHETIC
    with pytest.raises(ValueError):
        SX.load_reference_index(synthetic="sometimes")
    monkeypatch.setattr(SX, "real_sources_available", lambda *a, **k: False)
    assert SX.load_reference_index(synthetic="if-missing").mode == SX.MODE_SYNTHETIC
    with pytest.raises(FileNotFoundError):
        SX.load_reference_index(synthetic="never")


# ------------------------------------------------------------------ persona and challenge on the fixture
def test_persona_from_fixture_carries_the_synthetic_caveat(syn):
    reg = EvidenceRegistry()
    p = RecipientPersona.from_index(syn, "إدارة " + DEPT, reg)
    assert p.in_index and p.canonical_unit == DEPT and p.page == syn.org.unit(DEPT).page
    assert p.status_caveat == SX.SYNTHETIC_APPROVAL and p.matrix_status == SX.SYNTHETIC_APPROVAL
    ev = p.mandate_evidence()
    assert ev is not None and ev.approval_status == SX.SYNTHETIC_APPROVAL and ev.file.startswith("SYNTHETIC-")
    q = RecipientPersona.from_index(syn, "وحدة لا وجود لها", EvidenceRegistry())
    assert not q.in_index and q.canonical_unit is None


def test_challenge_runs_clean_on_the_fixture_and_blocks_on_a_missing_clause(tmp_path, syn):
    doc = Document(name="وثيقة اختبار المرجع الافتراضي", code="SYN", owning_department=DEPT, is_demo=True)
    st = build_round1(doc, base_obs(6), date="2026-02-15", document_version="الإصدار 0.1")
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    reg = EvidenceRegistry(); reg.add_document_text(full)
    rec = CH.run_challenge(st, reg, RecipientPersona.from_index(syn, DEPT, reg))
    assert rec.verify_chains() and rec.blockers() == []
    assert rec.persona["source_versions"]["org_structure"]["approval_status"] == SX.SYNTHETIC_APPROVAL
    victim = st.ordered()[4].internal_id
    short = build_reviewed_doc(st, tmp_path / "short.docx", omit=(victim,))
    reg2 = EvidenceRegistry(); reg2.add_document_text(short)
    rec2 = CH.run_challenge(st, reg2, RecipientPersona.from_index(syn, DEPT, reg2))
    blk = rec2.blockers()
    assert blk and {b["internal_id"] for b in blk} == {victim} and "CLAUSE_NOT_FOUND" in {b["kind"] for b in blk}


def test_mandate_rules_fire_on_a_modified_fixture():
    """OUTSIDE_RECIPIENT_MANDATE / CONTESTED_OWNERSHIP need another sector whose task overlaps the recommendation;
    the default fixture keeps the sectors lexically apart, so the test adds such a unit itself."""
    idx = SX.synthetic_reference_index()
    idx.org.units.append(Unit("حماية البيانات", "قطاع الخدمات المساندة", 12,
                              ("تحديد مدة الاحتفاظ بالبيانات وآلية إتلافها بعد انتهائها",)))
    reg = EvidenceRegistry()
    p = RecipientPersona.from_index(idx, DEPT, reg)
    others = p.other_owners("نوصي بتحديد مدة الاحتفاظ بالبيانات وآلية إتلافها بعد انتهائها.", 0.5)
    assert others and others[0][0] == "حماية البيانات" and others[0][1] == "قطاع الخدمات المساندة"
    own, _ = p.owns_task("نوصي بتحديد مدة الاحتفاظ بالبيانات وآلية إتلافها بعد انتهائها.")
    assert 0.0 <= own <= 1.0


def test_public_clone_runs_the_reference_tests_without_institutional_files():
    """Documentation check: the institutional sources are not required by this module."""
    assert "CDF_TEST_SYNTHETIC_REFERENCE" in Path(ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert os.environ.get("CDF_TEST_SYNTHETIC_REFERENCE", "0") in ("0", "1")
