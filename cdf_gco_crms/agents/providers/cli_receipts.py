"""Bounded CLI pipes and metadata-only progress; never persist raw stderr/prompts."""

import hashlib
import json
import os
import selectors
import subprocess  # nosec B404
import time

from .base import ProviderFailure

EVENTS = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "error",
    "item.started",
    "item.completed",
    "item.updated",
}


def collect(process, prompt, *, executor, timeout, kill, observer=None):
    started = time.monotonic()
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    pending = bytearray()
    diagnostic = {
        "schema": "CDF-CLI-DIAGNOSTIC-1",
        "executor": executor,
        "phase": "PROCESS_STARTED",
        "event_counts": {},
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "error_categories": [],
        "completion_observed": False,
        "inference_verified": False,
    }

    def publish():
        diagnostic["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        if observer:
            observer(json.loads(json.dumps(diagnostic)))

    def examine(raw):
        # Classify errors without copying any content, URLs or credentials.
        value = raw.decode("utf-8", errors="replace").lower()
        for marker, category in [
            ("403", "HTTP_403"),
            ("401", "HTTP_401"),
            ("429", "HTTP_429"),
            ("connection", "CONNECTION"),
            ("timed out", "UPSTREAM_TIMEOUT"),
            ("certificate", "TLS"),
            ("policy", "POLICY"),
            ("reconnect", "RECONNECT"),
        ]:
            if marker in value and category not in diagnostic["error_categories"]:
                diagnostic["error_categories"].append(category)

    publish()
    try:
        payload = prompt.encode()
        if len(payload) > 1_000_000:
            raise ProviderFailure(
                "CLI prompt exceeded bounds",
                kind="CLI_INPUT_LIMIT",
                diagnostics=diagnostic,
            )
        offset = 0
        os.set_blocking(process.stdin.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                if time.monotonic() - started >= timeout:
                    diagnostic["phase"] = "TIMEOUT_OUTCOME_UNKNOWN"
                    publish()
                    raise ProviderFailure(
                        "Supervised CLI timed out; no automatic replay",
                        kind="CLI_TIMEOUT",
                        diagnostics=diagnostic,
                    )
                for key, _ in selector.select(
                    timeout=min(0.2, max(0.01, timeout - (time.monotonic() - started)))
                ):
                    if key.data == "stdin":
                        try:
                            offset += os.write(
                                process.stdin.fileno(), payload[offset : offset + 8192]
                            )
                        except BrokenPipeError:
                            offset = len(payload)
                        if offset >= len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                        continue
                    chunk = key.fileobj.read1(8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    name = key.data
                    streams[name].extend(chunk)
                    diagnostic[name + "_bytes"] += len(chunk)
                    if len(streams[name]) > 2_000_000:
                        diagnostic["phase"] = "OUTPUT_LIMIT"
                        publish()
                        raise ProviderFailure(
                            "CLI receipt exceeded bounds",
                            kind="CLI_OUTPUT_LIMIT",
                            diagnostics=diagnostic,
                        )
                    if name == "stderr":
                        examine(chunk)
                    else:
                        pending.extend(chunk)
                        while b"\n" in pending:
                            line, _, rest = pending.partition(b"\n")
                            pending[:] = rest
                            try:
                                event = json.loads(line)
                            except (ValueError, UnicodeError):
                                continue
                            kind = (
                                event.get("type") if isinstance(event, dict) else None
                            )
                            if kind in EVENTS:
                                diagnostic["event_counts"][kind] = (
                                    diagnostic["event_counts"].get(kind, 0) + 1
                                )
                                diagnostic["phase"] = kind.upper().replace(".", "_")
                                if kind in ("error", "turn.failed"):
                                    examine(line)
                                    if (
                                        "HTTP_403" in diagnostic["error_categories"]
                                        or "HTTP_401" in diagnostic["error_categories"]
                                    ):
                                        diagnostic["phase"] = (
                                            "UPSTREAM_ACCESS_DENIED_OUTCOME_UNVERIFIED"
                                        )
                                        publish()
                                        raise ProviderFailure(
                                            "CLI upstream access denied; operator reconciliation required",
                                            kind="CLI_UPSTREAM_ACCESS_DENIED",
                                            diagnostics=diagnostic,
                                        )
                                if kind == "turn.completed":
                                    diagnostic["completion_observed"] = True
                    publish()
        process.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
    except subprocess.TimeoutExpired as exc:
        diagnostic["phase"] = "TIMEOUT_OUTCOME_UNKNOWN"
        raise ProviderFailure(
            "CLI exited pipes without completion before deadline",
            kind="CLI_TIMEOUT",
            diagnostics=diagnostic,
        ) from exc
    finally:
        if process.poll() is None:
            kill(process.pid)
            process.wait(timeout=5)
        diagnostic["exit_code"] = process.returncode
        for name, raw in streams.items():
            diagnostic[name + "_sha256"] = hashlib.sha256(raw).hexdigest()
        publish()
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
    return streams["stdout"].decode("utf-8", errors="replace"), diagnostic
