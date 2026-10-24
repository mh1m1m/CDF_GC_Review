"""TEST 26 — release authorisation gate (19A.9; forensic finding A: issuance bypass).

Every issuing command must pass through ``cdf_gco_crms.release.authorization_gate``: a BLOCKED or absent review
can never produce an issuable requester file, a working copy is always marked, and a review run against the
public SYNTHETIC reference fixture never authorises an institutional issue. All inputs here are synthetic.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as CLI  # noqa: E402
from cdf_gco_crms.assurance import challenge as CH  # noqa: E402
from cdf_gco_crms.assurance.evidence import EvidenceRegistry  # noqa: E402
from cdf_gco_crms.assurance.personas import RecipientPersona  # noqa: E402
from cdf_gco_crms.config import round_schema as S  # noqa: E402
from cdf_gco_crms.excel.workbook_builder import build_workbook  # noqa: E402
from cdf_gco_crms.ingestion.workbook_reader import parse_workbook  # noqa: E402
from cdf_gco_crms.model.entities import Document, GText, TitleEvidence  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.regression import synthetic as SY  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import build_round1  # noqa: E402
from conftest import base_obs  # noqa: E402
from test_word_lifecycle import build_reviewed_doc  # noqa: E402

DEPT = "الحوكمة والامتثال"
N = 6


def _state(code="GTE", *, demo=False):
    doc = Document(name="وثيقة بوابة الإصدار", code=code, owning_department=DEPT, is_demo=demo)
    return build_round1(doc, base_obs(N), date="2026-02-15", document_version="الإصدار 0.1")


def _review(state, docx, *, omit=()):
    idx = synthetic_reference_index()
    reg = EvidenceRegistry()
    reg.add_document_text(docx)
    persona = RecipientPersona.from_index(idx, DEPT, reg)
    return CH.run_challenge(state, reg, persona)


# ------------------------------------------------------------------ fingerprint
def test_fingerprint_is_deterministic_and_content_bound():
    a, b = _state(), _state()
    assert G.state_fingerprint(a) == G.state_fingerprint(b)
    b.observations[2].comment = GText.plain("نص معدّل بعد المراجعة.")
    assert G.state_fingerprint(a) != G.state_fingerprint(b)
    c = _state()
    c.observations[0].title = "عنوان معتمد"
    c.observations[0].title_status = S.TITLE_APPROVED
    c.observations[0].title_evidence = TitleEvidence("مراجع تجريبي", "2026-02-16", "DEC-1")
    assert G.state_fingerprint(a) == G.state_fingerprint(c), "title decisions carry their own proof; they do not reopen the challenge"
    d = _state()
    d.rounds[0].date = "2026-03-01"
    assert G.state_fingerprint(a) != G.state_fingerprint(d)


# ------------------------------------------------------------------ authorize()
def test_no_record_means_no_authorization(tmp_path):
    auth = G.authorize(_state(), tmp_path / "gate")
    assert not auth.ok and auth.reasons == [G.R_NO_RECORD]


def test_clear_review_authorizes_only_the_same_content(tmp_path):
    st = _state(demo=True)
    docx = build_reviewed_doc(st, tmp_path / "base.docx")
    rec = _review(st, docx)
    assert rec.blockers() == []
    rec_path = tmp_path / "challenge.json"; rec_path.write_text(rec.to_json(), encoding="utf-8")
    gate = tmp_path / "gate"
    G.record_review(st, rec, rec_path, reference_mode="INSTITUTIONAL_SOURCES", gate_dir=gate)
    assert G.authorize(st, gate).ok
    other = _state(demo=True)
    other.observations[1].comment = GText.plain("ملاحظة أخرى لم تُراجع.")
    auth = G.authorize(other, gate)
    assert not auth.ok and auth.reasons == [G.R_NO_RECORD]


def test_blocked_review_never_authorizes(tmp_path):
    st = _state(demo=True)
    victim = st.ordered()[2].internal_id
    docx = build_reviewed_doc(st, tmp_path / "short.docx", omit=(victim,))
    rec = _review(st, docx)
    assert rec.blockers() and all(b["internal_id"] == victim for b in rec.blockers())
    rec_path = tmp_path / "challenge.json"; rec_path.write_text(rec.to_json(), encoding="utf-8")
    gate = tmp_path / "gate"
    G.record_review(st, rec, rec_path, reference_mode="INSTITUTIONAL_SOURCES", gate_dir=gate)
    auth = G.authorize(st, gate)
    assert not auth.ok and any(r.startswith(G.R_BLOCKERS) for r in auth.reasons)


def test_tampered_gate_or_challenge_record_is_refused(tmp_path):
    st = _state(demo=True)
    docx = build_reviewed_doc(st, tmp_path / "base.docx")
    rec = _review(st, docx)
    rec_path = tmp_path / "challenge.json"; rec_path.write_text(rec.to_json(), encoding="utf-8")
    gate = tmp_path / "gate"
    G.record_review(st, rec, rec_path, reference_mode="INSTITUTIONAL_SOURCES", gate_dir=gate)
    # (a) the challenge record on disk is altered after the gate record was written
    rec_path.write_text(rec.to_json().replace('"chains_verified": true', '"chains_verified": true ', 1), encoding="utf-8")
    auth = G.authorize(st, gate)
    assert not auth.ok and G.R_RECORD_FILE in auth.reasons
    # (b) the gate record is edited by hand to CLEAR while the challenge record still lists a blocker
    victim = st.ordered()[0].internal_id
    docx2 = build_reviewed_doc(st, tmp_path / "short.docx", omit=(victim,))
    rec2 = _review(st, docx2)
    rec_path.write_text(rec2.to_json(), encoding="utf-8")
    G.record_review(st, rec2, rec_path, reference_mode="INSTITUTIONAL_SOURCES", gate_dir=gate)
    p = G.gate_record_path(G.state_fingerprint(st), gate)
    d = json.loads(p.read_text(encoding="utf-8")); d["status"] = "CLEAR"; d["blockers"] = []
    d["challenge_record_sha256"] = G.sha256_file(rec_path)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    auth = G.authorize(st, gate)
    assert not auth.ok and G.R_RECORD_CONTENT in auth.reasons


def test_synthetic_reference_review_never_authorizes_an_institutional_issue(tmp_path):
    st = _state(demo=False)
    docx = build_reviewed_doc(st, tmp_path / "base.docx")
    rec = _review(st, docx)
    rec_path = tmp_path / "challenge.json"; rec_path.write_text(rec.to_json(), encoding="utf-8")
    gate = tmp_path / "gate"
    G.record_review(st, rec, rec_path, reference_mode="SYNTHETIC", gate_dir=gate)
    auth = G.authorize(st, gate)
    assert not auth.ok and auth.reasons == [G.R_SYNTHETIC]
    demo = _state(demo=True)
    docx_d = build_reviewed_doc(demo, tmp_path / "demo.docx")
    rec_d = _review(demo, docx_d)
    rec_path_d = tmp_path / "challenge_demo.json"; rec_path_d.write_text(rec_d.to_json(), encoding="utf-8")
    G.record_review(demo, rec_d, rec_path_d, reference_mode="SYNTHETIC", gate_dir=gate)
    assert G.authorize(demo, gate).ok, "a demo document may be built from a synthetic-reference review"


# ------------------------------------------------------------------ working-copy marking
def test_working_copy_marking_xlsx_and_docx(tmp_path):
    st = _state()
    wc = build_workbook(st, G.working_copy_name(tmp_path / "wb.xlsx"), working_copy=True).path
    assert G.is_working_copy_name(wc) and wc.name.startswith(G.WORKING_COPY_PREFIX) and G.xlsx_is_working_copy(wc)
    assert parse_workbook(wc).state.document.name == st.document.name     # the Title property is untouched (09.4)
    issued = build_workbook(st, tmp_path / "issued.xlsx").path
    assert not G.xlsx_is_working_copy(issued)
    docx = build_reviewed_doc(st, tmp_path / "doc.docx")
    before = {n for n in zipfile.ZipFile(docx).namelist()}
    assert not G.docx_is_working_copy(docx)
    G.mark_working_copy_docx(docx)
    assert G.docx_is_working_copy(docx)
    assert set(zipfile.ZipFile(docx).namelist()) >= before
    G.mark_working_copy_docx(docx)                                            # idempotent
    core = zipfile.ZipFile(docx).read("docProps/core.xml").decode("utf-8")
    assert core.count("<cp:category>") == 1 and core.count("<cp:keywords>") == 1


# ------------------------------------------------------------------ command line
def _spec(path, *, demo=False, n=N):
    obs = [{"location": o.location, "quote": o.quote, "comment": [[s.text, s.bold] for s in o.comment.segments]}
           for o in base_obs(n)]
    path.write_text(json.dumps({"document": {"name": "وثيقة بوابة الإصدار", "code": "GTE", "cover_version": "الإصدار 0.1",
                                             "owning_department": DEPT, "is_demo": demo},
                                "date": "2026-02-15", "observations": obs}, ensure_ascii=False), encoding="utf-8")
    return path


def _run(argv, capsys):
    rc = CLI.main(argv)
    out = capsys.readouterr().out
    try:
        payload = json.loads(out[out.index("{"):])
    except ValueError:
        payload = {}
    return rc if isinstance(rc, int) else 0, payload


def test_cli_round1_is_always_a_marked_working_copy(tmp_path, capsys):
    rc, rep = _run(["round1", str(_spec(tmp_path / "r1.json")), str(tmp_path / "out")], capsys)
    assert rc == 0 and rep["working_copy"] is True
    out = Path(rep["output"])
    assert out.is_file() and G.is_working_copy_name(out) and G.xlsx_is_working_copy(out)


def test_cli_issue_refused_without_review_and_marked_with_working_copy_flag(tmp_path, capsys):
    rc, rep = _run(["round1", str(_spec(tmp_path / "r1.json")), str(tmp_path / "out")], capsys)
    wb = rep["output"]
    gate = str(tmp_path / "gate")
    issue_dir = tmp_path / "issue"
    rc, rep = _run(["build-excel", wb, str(issue_dir), "--gate-dir", gate], capsys)
    assert rc == CLI.RC_REFUSED and rep["status"] == "REFUSED" and rep["reason"] == "RELEASE_NOT_AUTHORIZED"
    assert not issue_dir.exists() or not list(issue_dir.glob("*.xlsx")), "nothing may be written on refusal"
    rc, rep = _run(["build-excel", wb, str(issue_dir), "--gate-dir", gate, "--working-copy"], capsys)
    assert rc == 0 and rep["working_copy"] is True and not rep["release_authorized"]
    out = Path(rep["output"])
    assert G.is_working_copy_name(out) and G.xlsx_is_working_copy(out)
    assert [p.name for p in issue_dir.glob("*.xlsx")] == [out.name]
    rc, rep = _run(["build-excel", wb, str(issue_dir), "--gate-dir", gate, "--working-copy", "--issue"], capsys)
    assert rc == CLI.RC_REFUSED, "--issue (freeze titles as ISSUED) is an issue act; never on a working copy"
    rc, rep = _run(["build-excel", wb, str(issue_dir), "--gate-dir", gate, "--internal-draft"], capsys)
    assert rc == 0 and rep["working_copy"] is True, "--internal-draft (PR #2) is an alias of --working-copy"
    docx = tmp_path / "issue" / "r1.docx"
    rc, rep = _run(["build-word", wb, str(docx), "--gate-dir", gate], capsys)
    assert rc == CLI.RC_REFUSED and not docx.exists()
    rc, rep = _run(["build-word", wb, str(docx), "--gate-dir", gate, "--working-copy"], capsys)
    assert rc == 0 and rep["working_copy"] is True
    wdocx = Path(rep["output"])
    assert G.is_working_copy_name(wdocx) and G.docx_is_working_copy(wdocx)


def test_cli_blocked_review_cannot_issue_and_clear_review_can(tmp_path, capsys):
    """The forensic bypass scenario: review BLOCKED → build-excel/build-word must refuse; after the content is
    reviewed CLEAR (demo document, synthetic reference) the same commands issue, unmarked."""
    rc, rep = _run(["round1", str(_spec(tmp_path / "r1.json", demo=True)), str(tmp_path / "out")], capsys)
    wb = rep["output"]
    st = parse_workbook(wb).state
    gate = str(tmp_path / "gate")
    victim = st.ordered()[1].internal_id
    short = build_reviewed_doc(st, tmp_path / "short.docx", omit=(victim,))
    rc, rep = _run(["review", wb, "--docx", str(short), "--gate-dir", gate, "--synthetic-reference",
                    "--record", str(tmp_path / "rec_blocked.json")], capsys)
    assert rc == CLI.RC_FAIL and rep["status"] == "BLOCKED" and rep["reference_mode"] == "SYNTHETIC"
    assert Path(rep["gate_record"]).is_file()
    rc, rep = _run(["build-excel", wb, str(tmp_path / "issue"), "--gate-dir", gate], capsys)
    assert rc == CLI.RC_REFUSED and any(r.startswith(G.R_BLOCKERS) for r in rep["gate"]["reasons"])
    rc, rep = _run(["build-word", wb, str(tmp_path / "issue" / "r1.docx"), "--gate-dir", gate], capsys)
    assert rc == CLI.RC_REFUSED
    # the full document: the challenge is clean for exactly this content
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    rc, rep = _run(["review", wb, "--docx", str(full), "--gate-dir", gate, "--synthetic-reference",
                    "--record", str(tmp_path / "rec_clear.json")], capsys)
    assert rc == 0 and rep["status"] == "CLEAR"
    rc, rep = _run(["build-excel", wb, str(tmp_path / "issue"), "--gate-dir", gate], capsys)
    assert rc == 0 and rep["release_authorized"] and not rep["working_copy"]
    issued = Path(rep["output"])
    assert not G.is_working_copy_name(issued) and not G.xlsx_is_working_copy(issued)
    rc, rep = _run(["build-word", wb, str(tmp_path / "issue" / "r1.docx"), "--gate-dir", gate], capsys)
    assert rc == 0 and rep["release_authorized"] and not G.docx_is_working_copy(rep["output"])
    rc, rep = _run(["build-word", wb, str(tmp_path / "issue" / "r1_native.docx"), "--gate-dir", gate, "--source", str(full)], capsys)
    assert rc == 0 and rep["release_authorized"] and not G.docx_is_working_copy(rep["output"])
    # the issued workbook carries the same content: it is itself authorised (rebuild) …
    rc, rep = _run(["rebuild", str(issued), str(tmp_path / "rebuilt"), "--gate-dir", gate], capsys)
    assert rc == 0 and rep["release_authorized"]
    # … but content that was not reviewed is not, even with an identical file name
    spec2 = _spec(tmp_path / "r1b.json", demo=True, n=N + 1)
    rc, rep = _run(["round1", str(spec2), str(tmp_path / "out2")], capsys)
    rc, rep = _run(["build-excel", rep["output"], str(tmp_path / "issue2"), "--gate-dir", gate], capsys)
    assert rc == CLI.RC_REFUSED and rep["gate"]["reasons"] == [G.R_NO_RECORD]


def test_cli_synthetic_reference_review_never_issues_an_institutional_document(tmp_path, capsys):
    rc, rep = _run(["round1", str(_spec(tmp_path / "r1.json", demo=False)), str(tmp_path / "out")], capsys)
    wb = rep["output"]
    st = parse_workbook(wb).state
    gate = str(tmp_path / "gate")
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    rc, rep = _run(["review", wb, "--docx", str(full), "--gate-dir", gate, "--synthetic-reference"], capsys)
    assert rc == 0 and rep["status"] == "CLEAR"
    rc, rep = _run(["build-excel", wb, str(tmp_path / "issue"), "--gate-dir", gate], capsys)
    assert rc == CLI.RC_REFUSED and rep["gate"]["reasons"] == [G.R_SYNTHETIC]


def test_cli_review_without_sources_and_without_flag_refuses(tmp_path, capsys):
    from cdf_gco_crms.references.synthetic_index import real_sources_available
    if real_sources_available():
        pytest.skip("institutional sources are on disk; the refusal path needs a public clone")
    rc, rep = _run(["round1", str(_spec(tmp_path / "r1.json")), str(tmp_path / "out")], capsys)
    full = build_reviewed_doc(parse_workbook(rep["output"]).state, tmp_path / "full.docx")
    with pytest.raises(FileNotFoundError):
        CLI.main(["review", rep["output"], "--docx", str(full), "--gate-dir", str(tmp_path / "gate")])
