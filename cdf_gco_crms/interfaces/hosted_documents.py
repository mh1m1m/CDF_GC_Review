"""Uploaded documents for the hosted deployment: Word and Excel files, run through the engine's own tools.

Off unless ``CDF_DOCUMENT_UPLOADS=PUBLIC``. Setting it records the owner's decision that every file uploaded to
this deployment is public material. The site then says so beside the upload box. Uploads never become
calibration cases: the ``SYN-`` case guards are unchanged, and uploaded files live in their own table.

What happens to a file:

* it must be ``.docx`` or ``.xlsx``, at most ``MAX_BYTES``, and pass the engine's package inspection
  (``ingestion.safe_open.inspect_package``: no macros, no external links, no oversized or unexpected parts);
* it is stored with its SHA-256 and a summary (a review workbook's rounds and observations, or a Word
  document's paragraphs, comments and tracked changes);
* the uploader alone can list, download, run tools on, or delete it;
* tools are the deterministic engine only; no file is sent to a model provider:
    - ``qa``             review workbook → quality gates;
    - ``word_report``    review workbook → Word review report (working copy);
    - ``excel_rebuild``  review workbook → rebuilt workbook (working copy);
    - ``comment``        Word document + review workbook → the document with the review comments anchored;
    - ``compare``        delivered Word document + returned Word document → changes the owner made.
  Each generated file is stored as a new document, labelled ``INTERNAL_DRAFT__`` (a working copy, never issued).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..calibration.store import AccessDenied, CalibrationError

MAX_BYTES = 4_000_000          # under Vercel's 4.5 MB request limit
KINDS = {".docx": "docx", ".xlsx": "xlsx"}
MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
ACTIONS = {"qa", "word_report", "excel_rebuild", "comment", "compare"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS uploaded_documents (
    document_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    content BLOB NOT NULL,
    summary_json TEXT NOT NULL,
    derived_from TEXT,
    action TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS uploaded_documents_owner ON uploaded_documents(owner_id, created_at);
CREATE TABLE IF NOT EXISTS uploaded_document_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    event TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
_ID = re.compile(r"^DOC-[a-f0-9]{32}$")


def uploads_enabled() -> bool:
    return os.getenv("CDF_DOCUMENT_UPLOADS", "") == "PUBLIC"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_filename(name: str) -> tuple[str, str]:
    """Return (safe file name, kind). Keeps Arabic and other letters; drops paths and control characters."""
    base = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C" and ch not in '<>:"|?*').strip(" .")
    suffix = Path(base).suffix.lower()
    if suffix not in KINDS:
        raise CalibrationError("ONLY_DOCX_OR_XLSX_ACCEPTED")
    stem = Path(base).stem.strip(" .")[:150] or "document"
    return stem + suffix, KINDS[suffix]


class DocumentLibrary:
    """Uploaded files of each signed-in reviewer, in the application's database (SQLite or Postgres)."""

    def __init__(self, store):
        self.store = store
        self.store.db.executescript(SCHEMA)

    # -- storage
    def _log(self, document_id, owner, event, detail):
        self.store.db.execute(
            "INSERT INTO uploaded_document_log(document_id,owner_id,event,detail_json,created_at) VALUES (?,?,?,?,?)",
            (document_id, owner, event, json.dumps(detail, ensure_ascii=False, sort_keys=True), _now()))

    def _row(self, owner, document_id):
        if not _ID.match(str(document_id or "")):
            raise CalibrationError("DOCUMENT_NOT_FOUND")
        row = self.store.db.execute("SELECT * FROM uploaded_documents WHERE document_id=?", (document_id,)).fetchone()
        if row is None or row["owner_id"] != owner:
            raise AccessDenied("DOCUMENT_NOT_FOUND")       # someone else's file looks the same as a missing one
        return row

    @staticmethod
    def describe(row) -> dict:
        return {"document_id": row["document_id"], "filename": row["filename"], "kind": row["kind"],
                "sha256": row["sha256"], "size": int(row["size"]), "created_at": row["created_at"],
                "derived_from": row["derived_from"], "action": row["action"],
                "summary": json.loads(row["summary_json"])}

    def _insert(self, owner, filename, kind, content, summary, derived_from=None, action=None):
        document_id = "DOC-" + uuid.uuid4().hex
        digest = hashlib.sha256(content).hexdigest()
        with self.store.transaction():
            self.store.db.execute(
                "INSERT INTO uploaded_documents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (document_id, owner, filename, kind, digest, len(content), content,
                 json.dumps(summary, ensure_ascii=False, sort_keys=True), derived_from, action, _now()))
            self._log(document_id, owner, "CREATED" if derived_from is None else "GENERATED",
                      {"filename": filename, "sha256": digest, "size": len(content), "from": derived_from,
                       "action": action})
        return self.describe(self._row(owner, document_id))

    # -- public operations (the caller holds the application lock)
    def upload(self, owner: str, filename: str, content: bytes) -> dict:
        name, kind = clean_filename(filename)
        if not content:
            raise CalibrationError("EMPTY_FILE")
        if len(content) > MAX_BYTES:
            raise CalibrationError("FILE_TOO_LARGE_MAX_4_MB")
        summary = inspect(content, kind)
        return self._insert(owner, name, kind, content, summary)

    def list(self, owner: str) -> list[dict]:
        rows = self.store.db.execute(
            "SELECT document_id,filename,kind,sha256,size,created_at,derived_from,action,summary_json,owner_id "
            "FROM uploaded_documents WHERE owner_id=? ORDER BY created_at DESC, document_id", (owner,)).fetchall()
        return [self.describe(r) for r in rows]

    def get(self, owner: str, document_id: str) -> dict:
        return self.describe(self._row(owner, document_id))

    def content(self, owner: str, document_id: str) -> tuple[dict, bytes]:
        row = self._row(owner, document_id)
        content = bytes(row["content"])
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise CalibrationError("DOCUMENT_INTEGRITY_FAILED")
        return self.describe(row), content

    def delete(self, owner: str, document_id: str) -> None:
        self._row(owner, document_id)
        with self.store.transaction():
            self.store.db.execute("DELETE FROM uploaded_documents WHERE document_id=? AND owner_id=?",
                                  (document_id, owner))
            self._log(document_id, owner, "DELETED", {})

    def prepare(self, owner: str, document_id: str, action: str, other_id: str | None = None):
        """Read what an action needs (under the lock). The engine then runs without the lock."""
        if action not in ACTIONS:
            raise CalibrationError("UNKNOWN_DOCUMENT_ACTION")
        first = self.content(owner, document_id)
        second = self.content(owner, other_id) if other_id else None
        return first, second

    def record(self, owner, source, action, result, output):
        """Store an action's generated file, if any, and log the run (under the lock)."""
        stored = None
        if output is not None:
            filename, kind, content, summary = output
            stored = self._insert(owner, filename, kind, content, summary, derived_from=source, action=action)
        with self.store.transaction():
            self._log(source, owner, "ACTION", {"action": action, "ok": result.get("ok"),
                                                 "output": stored["document_id"] if stored else None})
        return {"action": action, "result": result, "output": stored}


# -- inspection and summaries (no lock, no database) -------------------------------------------------------

def _scratch(content: bytes, name: str, directory: Path) -> Path:
    path = directory / name
    path.write_bytes(content)
    return path


def _refuse_dtd(path: Path) -> None:
    """Office files never declare a DTD; one in an uploaded part is an entity-expansion or XXE attempt."""
    import zipfile

    with zipfile.ZipFile(path) as package:
        for info in package.infolist():
            if info.filename.lower().endswith((".xml", ".rels", ".vml")):
                head = package.read(info.filename)
                if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
                    raise CalibrationError("UNSAFE_FILE_REFUSED: DTD_IN_" + info.filename[:80])


def inspect(content: bytes, kind: str) -> dict:
    from ..ingestion.safe_open import inspect_package

    with tempfile.TemporaryDirectory(prefix="cdf-upload-") as tmp:
        path = _scratch(content, "upload." + kind, Path(tmp))
        try:
            report = inspect_package(path, kind)
        except Exception as exc:                               # not a zip, or a broken package
            raise CalibrationError("NOT_A_VALID_" + kind.upper() + "_FILE") from exc
        if not report.ok:
            raise CalibrationError("UNSAFE_FILE_REFUSED: " + "; ".join(map(str, report.findings))[:400])
        _refuse_dtd(path)
        summary = {"package": {"safe": True, "parts": report.members}}
        summary.update(_workbook_summary(path) if kind == "xlsx" else _word_summary(path))
        return summary


def _workbook_summary(path: Path) -> dict:
    from ..ingestion.workbook_reader import parse_workbook

    try:
        parsed = parse_workbook(path, overrides={})
    except Exception as exc:
        return {"review_workbook": False, "reason": getattr(exc, "code", None) or type(exc).__name__}
    state = parsed.state
    titles = {}
    for observation in state.observations:
        titles[observation.title_status] = titles.get(observation.title_status, 0) + 1
    return {"review_workbook": True, "layout": parsed.kind, "document": state.document.name,
            "code": state.document.code, "rounds": [r.number for r in state.rounds],
            "observations": len(state.observations), "titles": titles, "warnings": parsed.warnings[:20]}


def _word_summary(path: Path) -> dict:
    from ..word.document_comments import _load_doc, _tracked_changes
    from ..word.word_sync import extract_comments

    doc, _parts = _load_doc(path)
    paragraphs = [p.text for p in doc.paras if p.text.strip()]
    comments = extract_comments(path)
    return {"paragraphs": len(paragraphs), "words": sum(len(t.split()) for t in paragraphs),
            "comments": len(comments), "review_comments": sum(1 for c in comments if c.internal_id),
            "tracked_changes": len(_tracked_changes(doc)),
            "opening": [t[:160] for t in paragraphs[:3]]}


def _working_name(name: str, suffix: str, label: str) -> str:
    from ..release.authorization_gate import working_copy_name

    return working_copy_name(Path(Path(name).stem + " - " + label + suffix)).name


def run_action(action: str, first: tuple[dict, bytes], second: tuple[dict, bytes] | None):
    """Run one engine tool. Returns (result, output) where output is (filename, kind, bytes, summary) or None."""
    meta, content = first
    with tempfile.TemporaryDirectory(prefix="cdf-action-") as tmp:
        directory = Path(tmp)
        if action in ("qa", "word_report", "excel_rebuild"):
            if meta["kind"] != "xlsx" or not meta["summary"].get("review_workbook"):
                raise CalibrationError("REVIEW_WORKBOOK_REQUIRED")
            return _workbook_action(action, meta, _scratch(content, "workbook.xlsx", directory), directory)
        if second is None:
            raise CalibrationError("SECOND_DOCUMENT_REQUIRED")
        other_meta, other = second
        if action == "comment":
            pair = {meta["kind"]: (meta, content), other_meta["kind"]: (other_meta, other)}
            if set(pair) != {"docx", "xlsx"} or not pair["xlsx"][0]["summary"].get("review_workbook"):
                raise CalibrationError("WORD_DOCUMENT_AND_REVIEW_WORKBOOK_REQUIRED")
            return _comment(pair["docx"], pair["xlsx"], directory)
        if meta["kind"] != "docx" or other_meta["kind"] != "docx":
            raise CalibrationError("TWO_WORD_DOCUMENTS_REQUIRED")
        return _compare(meta, content, other_meta, other, directory)


def _workbook_action(action, meta, workbook: Path, directory: Path):
    from ..ingestion.workbook_reader import parse_workbook
    from ..release.authorization_gate import mark_working_copy_docx
    from ..word.word_sync import build_review_docx, reconcile

    state = parse_workbook(workbook, overrides={}).state
    if action == "excel_rebuild":
        from ..excel.workbook_builder import build_workbook

        out = directory / "rebuilt.xlsx"
        build_workbook(state, out, working_copy=True)
        content = out.read_bytes()
        name = _working_name(meta["filename"], ".xlsx", "إعادة بناء")
        return ({"ok": True, "observations": len(state.observations)},
                (name, "xlsx", content, inspect(content, "xlsx")))
    report = directory / "report.docx"
    build_review_docx(state, report)
    mark_working_copy_docx(report)
    sync = reconcile(report, workbook)
    if action == "word_report":
        content = report.read_bytes()
        name = _working_name(meta["filename"], ".docx", "تقرير المراجعة")
        return ({"ok": bool(sync.ok), "word_matches_workbook": bool(sync.ok)},
                (name, "docx", content, inspect(content, "docx")))
    from ..qa.gates import GateContext, run_dash_gates
    from ..qa.ux_gates import run_ux_gates

    root = Path(__file__).resolve().parents[2]
    context = GateContext(xlsx=workbook, previous_xlsx=None, docx=report, view_checks=[], refresh=None,
                          logo_source=root / "assets" / "cdf_logo_horizontal_source.jpg")
    dash = run_dash_gates(context)
    gates = dash + run_ux_gates(context, dash)
    counts = {}
    for gate in gates:
        counts[gate.status] = counts.get(gate.status, 0) + 1
    return ({"ok": not counts.get("FAIL"), "counts": counts,
             "note": "Checks that compare with an earlier round or a returned file stay NOT_VERIFIED or FAIL "
                     "when that file is not supplied.",
             "gates": [{"gate": g.gate, "name": g.name, "status": g.status, "actual": str(g.actual)[:300]}
                       for g in gates]}, None)


def _comment(docx, xlsx, directory: Path):
    from ..ingestion.workbook_reader import parse_workbook
    from ..release.authorization_gate import mark_working_copy_docx
    from ..word.document_comments import comment_document

    (doc_meta, doc_bytes), (wb_meta, wb_bytes) = docx, xlsx
    source = _scratch(doc_bytes, "document.docx", directory)
    state = parse_workbook(_scratch(wb_bytes, "workbook.xlsx", directory), overrides={}).state
    out = directory / "commented.docx"
    report = comment_document(source, state, out)
    mark_working_copy_docx(out)
    content = out.read_bytes()
    name = _working_name(doc_meta["filename"], ".docx", "مع ملاحظات الجولة " + str(report.round))
    result = {"ok": report.ok, **report.summary(),
              "unanchored_detail": report.unanchored[:50], "warnings_detail": report.warnings[:50],
              "workbook": wb_meta["document_id"]}
    return result, (name, "docx", content, inspect(content, "docx"))


def _compare(meta, content, other_meta, other, directory: Path):
    from dataclasses import asdict

    from ..word.document_comments import diff_returned

    delivered = _scratch(content, "delivered.docx", directory)
    returned = _scratch(other, "returned.docx", directory)
    diff = diff_returned(delivered, returned)
    detail = asdict(diff)
    for key, value in list(detail.items()):
        if isinstance(value, list):
            detail[key] = value[:50]
    return ({"ok": diff.clean, "delivered": meta["document_id"], "returned": other_meta["document_id"],
             "summary": diff.summary(), "detail": detail}, None)
