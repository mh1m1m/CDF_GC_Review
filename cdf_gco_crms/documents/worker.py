"""Review worker: ``python -m cdf_gco_crms.documents.worker``.

Runs next to the website (any container host), connected to the same database. It claims queued reviews one at a
time, runs them (``documents.review``) and records the result; the website shows progress and the outputs.

Environment (see docs/deploy/REVIEW_WORKER.md):

* ``CDF_DATABASE_URL`` and ``CDF_DATABASE_SCHEMA=cdf``: the website's database (omit both for a local SQLite file).
* ``CDF_DOCUMENT_UPLOADS=PUBLIC``: the owner's switch; the worker refuses to start without it.
* ``CDF_REVIEW_EXECUTOR``: ``anthropic`` (default) or ``mock`` (labelled test runs only).
* ``ANTHROPIC_API_KEY``, ``CDF_ENABLE_PROVIDER_API=1`` and ``CDF_AI_DATA_AUTHORIZATION=INSTITUTIONAL_AUTHORIZED:<ref>``
  for live reviews; ``CDF_AI_MODEL`` optionally; ``CDF_AI_TIMEOUT_SECONDS`` (default 180).
* ``PORT``: when set, a tiny health endpoint listens there (hosts that require an open port).
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = logging.getLogger("cdf.review.worker")
POLL_SECONDS = 5.0
STATE = {"started": time.time(), "reviews": 0, "last": None, "busy": False}


def _health_server(port: int) -> None:
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            body = json.dumps({"status": "OK", "worker": "cdf-review", **STATE}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Health)  # nosec B104 - container health port, no data served
    threading.Thread(target=server.serve_forever, daemon=True).start()


def build():
    from ..calibration.store import CalibrationStore
    from ..execution.service import ApplicationService
    from ..interfaces.hosted_documents import DocumentLibrary
    from .policy import uploads_public
    from .review import ReviewQueue

    if not uploads_public():
        raise SystemExit("CDF_DOCUMENT_UPLOADS=PUBLIC is required: the owner has not switched document reviews on")
    if os.getenv("CDF_DATABASE_URL"):
        os.environ.setdefault("CDF_DATABASE_SCHEMA", "cdf")
    path = Path(os.getenv("CDF_CALIBRATION_DB") or Path(tempfile.gettempdir()) / "cdf-review-worker" / "public-demo" /
                "worker.sqlite")
    store = CalibrationStore(path)
    application = ApplicationService(store=store, token="")  # nosec B106 - no bearer token: the worker serves no API
    return application, DocumentLibrary(store), ReviewQueue(store)


def main(argv=None) -> int:
    from .review import process_next

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    application, library, queue = build()
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    if os.getenv("PORT"):
        _health_server(int(os.environ["PORT"]))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    once = argv == ["--once"]
    LOG.info("review worker %s started (executor=%s)", worker_id, os.getenv("CDF_REVIEW_EXECUTOR", "anthropic"))
    while not stop.is_set():
        queue.heartbeat(worker_id, {"executor": os.getenv("CDF_REVIEW_EXECUTOR", "anthropic"),
                                    "busy": STATE["busy"], "reviews": STATE["reviews"]})
        STATE["busy"] = True
        try:
            review = process_next(application, library, queue, worker_id)
        except Exception:                                       # the database was unreachable: wait and retry
            LOG.exception("worker loop error")
            review = None
        STATE["busy"] = False
        if review is not None:
            STATE["reviews"] += 1
            STATE["last"] = {"review_id": review["review_id"], "status": review["status"]}
            LOG.info("review %s finished: %s %s", review["review_id"], review["status"], review.get("error") or "")
            continue
        if once:
            break
        stop.wait(POLL_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
