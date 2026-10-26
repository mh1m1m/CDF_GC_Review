"""Review of an uploaded document: queue, worker steps and outputs.

A signed-in reviewer queues a review of a Word, PDF or Excel document they uploaded. A worker process
(``python -m cdf_gco_crms.documents.worker``) claims the job and runs the Article 06 pipeline of the engine:

1. **Read**: the document's text blocks (``documents.ingest``). A PDF or a spreadsheet is also written as a Word
   rendition whose paragraphs are exactly those blocks; that Word file is the review source the engine hashes,
   quotes and comments.
2. **Draft**: the GCO drafting agent reads the document in windows of ``WINDOW`` paragraphs (the engine's
   context limit) and proposes observations. Every proposal whose quote occurs in the document and which is not
   marked outside GCO's jurisdiction is adopted as a round-1 observation; the rest are kept in the report.
   Adoption is not approval: every observation stays a draft for the human calibration step.
3. **Challenge**: ``ReviewOrchestrator.execute`` runs the black team, red advocate, adjudicator, editorial agent and
   final reviewer on the adopted observations.
4. **Case**: the observations become an ``UPL-`` case owned by the uploader (calibration screens, timeline, executive
   dashboard), and the execution is captured for the dashboard.
5. **Outputs**, all ``INTERNAL_DRAFT__`` working copies: the document with the review comments (Word), the same as
   PDF, the original PDF with highlights and notes (PDF input), the original spreadsheet with cell comments
   (Excel input), the review tracker (Excel), and the executive dashboard (Word, Excel, PDF).

Nothing is issued: the release gate records SYNTHETIC_REFERENCE_NOT_ISSUABLE (the hosted deployment carries the
public reference fixture, not the institution's approved sources) and issuance stays a separate human act.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..calibration.store import AccessDenied, CalibrationError, ReviewerContext

LOG = logging.getLogger(__name__)
WINDOW = 60                      # paragraphs per drafting call (agents/context_builder.MAX_PARAGRAPHS)
MAX_OBSERVATIONS = 80
LEASE_SECONDS = 900
MAX_ATTEMPTS = 2
ACTIVE = ("QUEUED", "RUNNING")
SCHEMA = """
CREATE TABLE IF NOT EXISTS document_reviews (
    review_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    roles_json TEXT NOT NULL,
    options_json TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    error TEXT,
    case_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    worker TEXT,
    lease_until REAL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS document_reviews_queue ON document_reviews(status, created_at);
CREATE INDEX IF NOT EXISTS document_reviews_document ON document_reviews(document_id, created_at);
CREATE TABLE IF NOT EXISTS review_workers (
    worker_id TEXT PRIMARY KEY,
    seen_at REAL NOT NULL,
    info_json TEXT NOT NULL
);
"""
STAGES = ("QUEUED", "READING", "DRAFTING", "CHALLENGING", "RECORDING_CASE", "WRITING_OUTPUTS", "DONE")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewQueue:
    """The ``document_reviews`` table: one row per requested review, claimed by one worker at a time."""

    def __init__(self, store):
        self.store = store
        self.store.db.executescript(SCHEMA)

    @staticmethod
    def describe(row) -> dict:
        return {"review_id": row["review_id"], "document_id": row["document_id"], "status": row["status"],
                "stage": row["stage"], "detail": json.loads(row["detail_json"]), "error": row["error"],
                "case_id": row["case_id"], "attempts": int(row["attempts"]), "created_at": row["created_at"],
                "started_at": row["started_at"], "finished_at": row["finished_at"],
                "options": json.loads(row["options_json"])}

    def _row(self, owner, review_id):
        row = self.store.db.execute("SELECT * FROM document_reviews WHERE review_id=?", (str(review_id),)).fetchone()
        if row is None or row["owner_id"] != owner:
            raise AccessDenied("REVIEW_NOT_FOUND")
        return row

    def queue(self, reviewer: ReviewerContext, document: dict, *, department: str | None = None) -> dict:
        reviewer.require("CALIBRATION_ADMIN")       # a review creates a case, as the CLI and execution API require
        kind = document["kind"]
        if kind == "xlsx" and document["summary"].get("review_workbook"):
            raise CalibrationError("REVIEW_TRACKER_USE_NEXT_ROUND_TOOLS")
        if kind not in ("docx", "pdf", "xlsx"):
            raise CalibrationError("UNSUPPORTED_DOCUMENT_KIND")
        if document.get("action"):
            raise CalibrationError("GENERATED_FILES_ARE_NOT_REVIEWED")
        review_id = "REV-" + uuid.uuid4().hex
        options = {"department": (department or "").strip()[:120] or None}
        with self.store.transaction():
            busy = self.store.db.execute(
                "SELECT review_id FROM document_reviews WHERE document_id=? AND status IN ('QUEUED','RUNNING')",
                (document["document_id"],)).fetchone()
            if busy:
                raise CalibrationError("REVIEW_ALREADY_RUNNING")
            self.store.db.execute(
                "INSERT INTO document_reviews(review_id,document_id,owner_id,roles_json,options_json,status,stage,"
                "detail_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (review_id, document["document_id"], reviewer.reviewer_id, json.dumps(sorted(reviewer.roles)),
                 json.dumps(options, ensure_ascii=False), "QUEUED", "QUEUED", "{}", _now()))
        return self.get(reviewer.reviewer_id, review_id)

    def get(self, owner: str, review_id: str) -> dict:
        self.expire_stalled()
        return self.describe(self._row(owner, review_id))

    def for_document(self, owner: str, document_id: str) -> list[dict]:
        rows = self.store.db.execute(
            "SELECT * FROM document_reviews WHERE owner_id=? AND document_id=? ORDER BY created_at DESC",
            (owner, document_id)).fetchall()
        return [self.describe(r) for r in rows]

    def latest_by_document(self, owner: str) -> dict[str, dict]:
        self.expire_stalled()
        rows = self.store.db.execute(
            "SELECT * FROM document_reviews WHERE owner_id=? ORDER BY created_at", (owner,)).fetchall()
        return {r["document_id"]: self.describe(r) for r in rows}

    # -- worker side
    def heartbeat(self, worker_id: str, info: dict) -> None:
        with self.store.transaction():
            self.store.db.execute("DELETE FROM review_workers WHERE worker_id=?", (worker_id,))
            self.store.db.execute("INSERT INTO review_workers VALUES (?,?,?)",
                                  (worker_id, time.time(), json.dumps(info, ensure_ascii=False)))

    def worker_seen(self, within: float = 180.0) -> bool:
        """A worker polled recently, or one holds a live lease on a running review (long reviews poll nothing)."""
        now = time.time()
        row = self.store.db.execute("SELECT MAX(seen_at) AS seen FROM review_workers").fetchone()
        if row and row["seen"] and now - float(row["seen"]) <= within:
            return True
        return self.store.db.execute(
            "SELECT 1 FROM document_reviews WHERE status='RUNNING' AND lease_until > ? AND worker NOT LIKE 'website-%'",
            (now,)).fetchone() is not None

    def expire_stalled(self) -> None:
        """A website run cut off by the host's time limit leaves a RUNNING row with a lapsed lease: record it."""
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE document_reviews SET status='FAILED', stage='FAILED', error='WEBSITE_TIME_LIMIT_REACHED', "
                "finished_at=?, lease_until=NULL WHERE status='RUNNING' AND lease_until < ? AND worker LIKE 'website-%'",
                (_now(), time.time()))

    def claim_review(self, review_id: str, worker_id: str, lease_seconds: float):
        """Claim one specific queued review (the website runner works on the review its own request queued)."""
        with self.store.transaction():
            row = self.store.db.execute("SELECT * FROM document_reviews WHERE review_id=? AND status='QUEUED'",
                                        (review_id,)).fetchone()
            if row is None:
                return None
            self.store.db.execute(
                "UPDATE document_reviews SET status='RUNNING', stage='READING', worker=?, lease_until=?, "
                "attempts=attempts + 1, started_at=? WHERE review_id=? AND status='QUEUED'",
                (worker_id, time.time() + lease_seconds, _now(), review_id))
            return self.store.db.execute("SELECT * FROM document_reviews WHERE review_id=?", (review_id,)).fetchone()

    def claim(self, worker_id: str):
        now = time.time()
        with self.store.transaction():
            row = self.store.db.execute(
                "SELECT * FROM document_reviews WHERE status='QUEUED' OR (status='RUNNING' AND lease_until < ?) "
                "ORDER BY created_at LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            if int(row["attempts"]) >= MAX_ATTEMPTS:
                self.store.db.execute(
                    "UPDATE document_reviews SET status='FAILED', error=?, finished_at=? WHERE review_id=?",
                    ("WORKER_STOPPED_DURING_REVIEW", _now(), row["review_id"]))
                return None
            self.store.db.execute(
                "UPDATE document_reviews SET status='RUNNING', stage='READING', worker=?, lease_until=?, "
                "attempts=attempts + 1, started_at=? WHERE review_id=?",
                (worker_id, now + LEASE_SECONDS, _now(), row["review_id"]))
            return self.store.db.execute("SELECT * FROM document_reviews WHERE review_id=?",
                                         (row["review_id"],)).fetchone()

    def progress(self, review_id: str, stage: str, detail: dict) -> None:
        with self.store.transaction():
            # A worker's lease is extended at each step; a website run keeps the lease it was given (the host's limit).
            self.store.db.execute(
                "UPDATE document_reviews SET stage=?, detail_json=?, lease_until=CASE WHEN worker LIKE 'website-%' "
                "THEN lease_until ELSE ? END WHERE review_id=? AND status='RUNNING'",
                (stage, json.dumps(detail, ensure_ascii=False, default=str), time.time() + LEASE_SECONDS, review_id))

    def finish(self, review_id: str, status: str, detail: dict, *, error: str | None = None,
               case_id: str | None = None) -> None:
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE document_reviews SET status=?, stage=?, detail_json=?, error=?, case_id=COALESCE(?, case_id), "
                "finished_at=?, lease_until=NULL WHERE review_id=?",
                (status, "DONE" if status == "DONE" else status, json.dumps(detail, ensure_ascii=False, default=str),
                 error, case_id, _now(), review_id))


# -- the review itself ----------------------------------------------------------------------------------------------

def _comment_text(finding: str, recommendation: str):
    from ..model.entities import GText, Segment

    finding, recommendation = (finding or "").strip(), (recommendation or "").strip()
    segments = [Segment(finding)]
    if recommendation:
        segments += [Segment("\n"), Segment("التوصية:", True), Segment(" " + recommendation)]
    return GText(segments)


def draft_windows(runner, state, registry, persona, on_window=None) -> tuple[list[dict], list[dict]]:
    """The drafting agent over the whole document, ``WINDOW`` paragraphs per call. Returns (proposals, calls)."""
    from ..agents import context_builder as CB
    from ..agents.contracts import ROLE_DRAFTING
    from ..agents.roles import _admissible

    paragraphs = registry.document_paragraphs()
    windows = [paragraphs[i:i + WINDOW] for i in range(0, len(paragraphs), WINDOW)] or [[]]
    proposals: list[dict] = []
    calls: list[dict] = []
    for number, window in enumerate(windows, 1):
        if on_window:
            on_window(number, len(windows))
        first = (number - 1) * WINDOW
        payload = CB.drafting_payload(state, registry, persona)
        payload["document_paragraphs"] = [{"paragraph": first + i + 1, "text": t} for i, t in enumerate(window)]
        payload["document_window"] = {"part": number, "of": len(windows)}
        resp = runner.run(ROLE_DRAFTING, CB.SYSTEM[ROLE_DRAFTING], payload, max_tokens=8192)
        calls.append({"part": number, "status": resp.status, "mode": resp.mode, "error": resp.error,
                      "execution_id": resp.execution_id})
        if not resp.ok:
            continue
        for item in resp.output["observations"]:
            good, bad = _admissible(registry, item.get("evidence_refs"))
            anchor = registry.bind_clause(item.get("quote", ""))
            proposals.append({**item, "evidence_refs": good, "hallucinated_refs": bad,
                              "quote_anchored": anchor is not None, "status": "PROPOSED_FOR_HUMAN_REVIEW",
                              "origin_execution_id": resp.execution_id, "window": number,
                              "gaps_not_drafted": None})
        if resp.output.get("gaps_not_drafted"):
            calls[-1]["gaps_not_drafted"] = resp.output["gaps_not_drafted"][:30]
    return proposals, calls


def adopt(proposals: list[dict], source) -> tuple[list, list[dict], list[dict]]:
    """Proposals → round-1 observations. Returns (new observations, adopted proposals, set-aside proposals)."""
    from ..rounds.round_expansion import NewObservation
    from .annotate import find_block, key

    adopted, aside, seen = [], [], set()
    observations = []
    for proposal in proposals:
        quote = (proposal.get("quote") or "").strip()
        block = find_block(source, quote)
        reason = None
        if not quote or not proposal.get("quote_anchored") or block is None:
            reason = "QUOTE_NOT_FOUND_IN_DOCUMENT"
        elif proposal.get("jurisdiction") == "OUTSIDE_GCO":
            reason = "OUTSIDE_GCO_JURISDICTION"
        elif (key(quote), key(proposal.get("finding", ""))) in seen:
            reason = "DUPLICATE"
        elif len(observations) >= MAX_OBSERVATIONS:
            reason = "OBSERVATION_LIMIT_REACHED"
        if reason:
            aside.append({**proposal, "set_aside": reason})
            continue
        seen.add((key(quote), key(proposal.get("finding", ""))))
        observations.append(NewObservation(block.location, quote,
                                           _comment_text(proposal.get("finding", ""), proposal.get("recommendation", ""))))
        adopted.append({**proposal, "location": block.location})
    return observations, adopted, aside


def document_mock_script():
    """Explicit MOCK executor for tests: drafts from the first substantive paragraphs. Never a live substitute."""
    from ..agents import contracts as C
    from ..execution.synthetic import mock_script

    script = mock_script()

    def drafting(payload):
        out = []
        for item in payload["document_paragraphs"]:
            text = item["text"]
            if len(text) >= 25 and len(out) < 3:
                out.append({"location": f"الفقرة {item['paragraph']}", "quote": text[:60].rsplit(" ", 1)[0],
                            "finding": "MOCK: يحتاج النص إلى تحديد جهة الاعتماد وحدود المسؤولية.",
                            "recommendation": "MOCK: توثيق جهة الاعتماد وحدود الصلاحية قبل التنفيذ.",
                            "proposed_wording": None, "basis_type": "GOVERNANCE_IMPROVEMENT", "jurisdiction": "GCO",
                            "evidence_refs": [], "evidence_sufficient": False, "confidence": 0.0})
        return {"observations": out, "gaps_not_drafted": [], "reasoning_summary": "MOCK: اختبار معلن، لا استدلال حقيقي."}

    script[C.ROLE_DRAFTING] = drafting
    return script


def _executor(store=None):
    """The AI service for a review: the one chosen on the AI settings page (its model and saved key), else
    ``CDF_REVIEW_EXECUTOR`` with keys from the environment. ``mock`` is the labelled test executor."""
    from ..execution.providers import select_executor

    name = os.getenv("CDF_REVIEW_EXECUTOR", "anthropic")
    timeout = float(os.getenv("CDF_AI_TIMEOUT_SECONDS", "180") or 180)
    if name == "mock":
        from ..agents.providers.mock_adapter import MockAdapter

        return name, MockAdapter(script=document_mock_script())
    if store is not None:
        from ..interfaces.ai_settings import AISettings

        settings = AISettings(store)
        provider = settings.active()[0] or name
        return provider, settings.adapter(provider, timeout=timeout)
    return name, select_executor(name, timeout=timeout)


def _docx_to_pdf(path: Path, outdir: Path) -> Path | None:
    """Word → PDF with LibreOffice, review comments printed in the margin. None when LibreOffice is absent."""
    import subprocess  # nosec B404 - fixed LibreOffice command, no shell, no user-controlled arguments

    from ..qa.lo_engine import _env, _profile, available

    if not available():
        return None
    outdir.mkdir(parents=True, exist_ok=True)
    options = json.dumps({"ExportNotes": {"type": "boolean", "value": "false"},
                          "ExportNotesInMargin": {"type": "boolean", "value": "true"}})
    with tempfile.TemporaryDirectory(prefix="cdf-review-lo-") as tmp:
        subprocess.run(["soffice", "--headless",  # nosec B603 B607 - soffice from PATH as in qa.lo_engine
                        "--norestore", f"-env:UserInstallation={_profile(tmp, False)}",
                        "--convert-to", f"pdf:writer_pdf_Export:{options}", "--outdir", str(outdir), str(path)],
                       capture_output=True, timeout=300, env=_env())
    pdf = outdir / (path.stem + ".pdf")
    return pdf if pdf.exists() else None


def run_review(application, library, queue: ReviewQueue, row, *, deadline: float | None = None) -> dict:
    """Run one claimed review. Returns the final detail; raises on failure (the caller records it)."""
    from ..agents import AgentRunner, TraceWriter
    from ..agents.contracts import new_id
    from ..agents.orchestrator import ReviewOrchestrator
    from ..assurance.evidence import EvidenceRegistry
    from ..assurance.personas import RecipientPersona
    from ..excel.workbook_builder import build_workbook
    from ..model.entities import Document, plain_text
    from ..references.synthetic_index import synthetic_reference_index
    from ..release.authorization_gate import mark_working_copy_docx, state_fingerprint, working_copy_name
    from ..rounds.round_expansion import build_round1
    from ..word.document_comments import comment_document
    from .annotate import Comment, annotate_pdf, annotate_xlsx
    from .ingest import extract, to_docx

    review_id, owner = row["review_id"], row["owner_id"]
    reviewer = ReviewerContext(owner, frozenset(json.loads(row["roles_json"])), True)
    options = json.loads(row["options_json"])
    detail: dict = {"review_id": review_id}

    def in_time(needed: float) -> None:
        if deadline is not None and time.time() + needed > deadline:
            raise CalibrationError("WEBSITE_TIME_LIMIT_DOCUMENT_TOO_LONG")

    def step(stage, **extra):
        detail.update(extra)
        detail["stage"] = stage
        queue.progress(review_id, stage, detail)

    meta, content = library.content(owner, row["document_id"])
    kind, stem = meta["kind"], Path(meta["filename"]).stem
    with tempfile.TemporaryDirectory(prefix="cdf-review-") as tmp:
        work = Path(tmp)
        original = work / ("original." + kind)
        original.write_bytes(content)
        step("READING")
        source = extract(original, kind)
        if not source.blocks:
            raise CalibrationError("NO_TEXT_FOUND" + ("_SCANNED_PDF_NEEDS_OCR" if kind == "pdf" else ""))
        review_docx = work / "review-source.docx"
        if kind == "docx":
            review_docx.write_bytes(content)
        else:
            to_docx(source, stem, review_docx)
        step("READING", source=source.summary())

        executor, provider = _executor(application.store)
        trace = TraceWriter()
        runner = AgentRunner(provider, trace) if provider is not None else None
        if runner is None:
            raise CalibrationError("REVIEW_NEEDS_A_MODEL_PROVIDER")
        index = synthetic_reference_index()
        document = Document(name=stem[:60] or "مستند", code="UPL", owning_department=options.get("department"),
                            is_demo=False)
        empty = build_round1(document, [], date=datetime.now(timezone.utc).date().isoformat(),
                             document_version=meta["sha256"][:12])
        registry = EvidenceRegistry()
        registry.add_document_text(review_docx)
        registry.add_reference_index(index)
        persona = RecipientPersona.from_index(index, options.get("department") or "", registry)
        runner.bind(new_id("RUN"), state_fingerprint(empty))
        proposals, calls = draft_windows(runner, empty, registry, persona,
                                         on_window=lambda n, of: (in_time(90), step("DRAFTING", drafting_window=f"{n}/{of}")))
        if calls and not any(c["status"] == "OK" for c in calls):
            raise CalibrationError("DRAFTING_FAILED: " + str(calls[0].get("error") or calls[0]["status"])[:300])
        new_observations, adopted, aside = adopt(proposals, source)
        step("DRAFTING", executor=executor, drafting_calls=calls, drafting_trace_records=len(trace.records),
             drafting_live_calls=sum(1 for r in trace.records if r.get("Execution_Source") == "PROVIDER_API"),
             proposals=len(proposals), adopted=len(adopted),
             set_aside=[{"quote": p.get("quote", "")[:120], "reason": p["set_aside"]} for p in aside][:60])
        if not new_observations:
            return {**detail, "outcome": "NO_OBSERVATIONS_ADOPTED"}

        state = build_round1(document, new_observations, date=datetime.now(timezone.utc).date().isoformat(),
                             document_version=meta["sha256"][:12])
        in_time(120)
        step("CHALLENGING", observations=len(state.observations))
        # The challenge pass gets its own trace: the dashboard verifies one run's hash chain from its first record.
        trace = TraceWriter()
        runner = AgentRunner(provider, trace)
        engine = ReviewOrchestrator(index, runner=runner, gate_dir=work / "gate")
        execution = engine.execute(state, review_docx, options.get("department"), draft=False, command="upload-review")

        step("RECORDING_CASE", execution_status=execution.status,
             provider_failures=int(execution.provider_failures or 0),
             live_calls=execution.trace_summary.get("actual_live_inference_count", 0))
        case_id = "UPL-" + uuid.uuid4().hex[:16].upper()
        review_bytes = review_docx.read_bytes()
        source_hash = hashlib.sha256(review_bytes).hexdigest()
        by_id = {o.internal_id: o for o in state.observations}
        proposals_by_quote = {p["quote"]: p for p in adopted}
        evidence = []
        for internal_id, o in by_id.items():
            quote = plain_text(o.quote)
            proposal = proposals_by_quote.get(quote, {})
            evidence.append({"observation_id": internal_id, "original_text": plain_text(o.comment),
                             "reviewed_text": None, "observed_change": "INITIAL_REVIEW", "material_categories": [],
                             "quote": quote, "location": str(o.location),
                             "analysis_source": "DRAFTING_AGENT_" + executor.upper(),
                             "basis_type": proposal.get("basis_type"), "jurisdiction": proposal.get("jurisdiction"),
                             "confidence": proposal.get("confidence")})
        calibration = application.calibration
        calibration.import_case(case_id, source_hash, evidence, reviewer)
        with application.store.transaction():
            application.store.db.execute("INSERT INTO app_cases VALUES (?,?,?,?,?)",
                                         (case_id, source_hash, review_bytes, "uploaded-document", _now()))
            application.store.db.execute("INSERT INTO app_case_grants VALUES (?,?)", (case_id, owner))
        application.intelligence.capture(case_id, execution, trace.records, reviewer, gate_dir=work / "gate")
        detail["case_id"] = case_id

        step("WRITING_OUTPUTS", case_id=case_id)
        outputs: list[tuple[str, str, bytes]] = []          # (filename, kind, bytes)

        def named(label: str, suffix: str) -> str:
            return working_copy_name(Path(f"{stem} - {label}{suffix}")).name

        commented = work / "commented.docx"
        report = comment_document(review_docx, state, commented)
        mark_working_copy_docx(commented)
        outputs.append((named("ملاحظات الجولة 1", ".docx"), "docx", commented.read_bytes()))
        pdf = _docx_to_pdf(commented, work / "pdf")
        if pdf is not None:
            outputs.append((named("ملاحظات الجولة 1", ".pdf"), "pdf", pdf.read_bytes()))
        comments = [Comment(o.internal_id, plain_text(o.quote), plain_text(o.comment)) for o in state.ordered()]
        placement = None
        if kind == "pdf":
            annotated = work / "annotated.pdf"
            placement = annotate_pdf(original, source, comments, annotated).summary()
            outputs.append((named("الأصل مع الملاحظات", ".pdf"), "pdf", annotated.read_bytes()))
        elif kind == "xlsx":
            annotated = work / "annotated.xlsx"
            placement = annotate_xlsx(original, source, comments, annotated).summary()
            outputs.append((named("الأصل مع الملاحظات", ".xlsx"), "xlsx", annotated.read_bytes()))
        tracker = work / "tracker.xlsx"
        from ..intelligence.exports import brand_wordmark_path
        from .policy import site_identity

        brand = brand_wordmark_path() if site_identity() == "CDF" and brand_wordmark_path().exists() else None
        build_workbook(state, tracker, working_copy=True, logo_path=brand)
        outputs.append((named("سجل المراجعة", ".xlsx"), "xlsx", tracker.read_bytes()))
        from ..intelligence.exports import export_dashboard

        dashboard = application.intelligence.dashboard(case_id, reviewer)
        for dash_kind in ("docx", "xlsx", "pdf"):
            try:
                outputs.append((named("لوحة المتابعة", "." + dash_kind), dash_kind, export_dashboard(dashboard, dash_kind)))
            except (RuntimeError, TimeoutError, OSError) as exc:     # PDF needs LibreOffice
                detail.setdefault("output_warnings", []).append(f"dashboard {dash_kind}: {type(exc).__name__}")
        stored = []
        for filename, out_kind, data in outputs:
            stored.append(library.store_generated(owner, filename, out_kind, data, row["document_id"], "review"))
        detail.update({"outputs": [{"document_id": s["document_id"], "filename": s["filename"], "kind": s["kind"]}
                                   for s in stored],
                       "comments": report.summary(), "placement": placement,
                       "observations": len(state.observations), "outcome": "REVIEWED",
                       "release": "WORKING_COPY_ONLY"})
        return detail


def process_next(application, library, queue: ReviewQueue, worker_id: str | None = None) -> dict | None:
    """Claim and run one queued review; record DONE or FAILED. Returns the review, or None when idle."""
    worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
    row = queue.claim(worker_id)
    if row is None:
        return None
    return _run_claimed(application, library, queue, row)


def run_on_website(application, library, queue: ReviewQueue, owner: str, review_id: str) -> dict:
    """The website runner (CDF_REVIEW_RUNNER=website): run the review this request queued, within the host's limit.

    A short or medium document finishes inside one request. A longer one stops with WEBSITE_TIME_LIMIT_… and is
    reviewed by the review worker instead; a run cut off by the host is recorded the same way (expire_stalled).
    """
    queue.get(owner, review_id)                                   # ownership
    budget = float(os.getenv("CDF_REVIEW_WEBSITE_SECONDS", "270") or 270)
    row = queue.claim_review(review_id, "website-" + uuid.uuid4().hex[:8], budget + 30)
    if row is None:
        return queue.get(owner, review_id)
    return _run_claimed(application, library, queue, row, deadline=time.time() + budget)


def _run_claimed(application, library, queue: ReviewQueue, row, *, deadline: float | None = None) -> dict:
    try:
        detail = run_review(application, library, queue, row, deadline=deadline)
        queue.finish(row["review_id"], "DONE", detail, case_id=detail.get("case_id"))
    except Exception as exc:                                     # recorded for the reviewer, then the next job
        LOG.exception("review %s failed", row["review_id"])
        from ..agents.providers.base import ProviderFailure

        if isinstance(exc, (CalibrationError, AccessDenied)):
            code = str(exc)
        elif isinstance(exc, ProviderFailure):              # adapter messages carry fixed reason codes, no API text
            code = f"ProviderFailure: {exc.kind}: {exc}"
        else:
            code = type(exc).__name__
        queue.finish(row["review_id"], "FAILED", {"review_id": row["review_id"]}, error=code[:500])
    return queue.get(row["owner_id"], row["review_id"])
