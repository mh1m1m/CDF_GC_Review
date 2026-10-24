"""Supervised official CLI invocation. CLI provenance is separate from API receipts."""

import json
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404
import tempfile

from ..contracts import MODE_LIVE, TokenUsage
from .base import ProviderAdapter, ProviderFailure, ProviderResult


class SupervisedCLIAdapter(ProviderAdapter):
    mode = MODE_LIVE

    def __init__(self, config, executor):
        super().__init__(config)
        if executor not in ("codex-cli", "claude-cli"):
            raise ValueError("UNSUPPORTED_CLI")
        self.executor = executor
        self.name = executor

    def complete(self, request):
        from ..security import payload_is_synthetic

        if not payload_is_synthetic(request.payload):
            raise ProviderFailure(
                "Consumer CLI institutional processing is disabled",
                kind="CLI_SYNTHETIC_ONLY",
            )
        if os.getenv("CDF_ENABLE_SUPERVISED_CLI") != "1":
            raise ProviderFailure(
                "Supervised CLI policy is disabled", kind="EXECUTION_POLICY_BLOCKED"
            )
        executable = shutil.which("codex" if self.executor == "codex-cli" else "claude")
        if not executable:
            raise ProviderFailure("Requested CLI is unavailable", kind="CLI_MISSING")
        from ...execution.jobs import kill_tree

        with tempfile.TemporaryDirectory(prefix="cdf-cli-stage-") as temp:
            root = Path(temp)
            schema = root / "schema.json"
            output = root / "output.json"
            schema.write_text(json.dumps(request.schema))
            if self.executor == "codex-cli":
                command = [
                    executable,
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--disable",
                    "shell_tool",
                    "--disable",
                    "unified_exec",
                    "--disable",
                    "multi_agent",
                    "--json",
                    "--color",
                    "never",
                    "--output-schema",
                    str(schema),
                    "--output-last-message",
                    str(output),
                    "-",
                ]
            else:
                command = [
                    executable,
                    "-p",
                    "--output-format",
                    "json",
                    "--json-schema",
                    json.dumps(request.schema),
                    "--tools",
                    "",
                ]
            env = os.environ.copy()
            env.pop("CDF_CALIBRATION_DEV_TOKEN", None)
            process = subprocess.Popen(
                command,  # nosec B603
                cwd=root,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(
                    request.system + "\n\n" + request.user_text,
                    timeout=self.config.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                kill_tree(process.pid)
                process.communicate()
                raise ProviderFailure(
                    "Supervised CLI timed out", kind="CLI_TIMEOUT"
                ) from exc
            if process.returncode:
                raise ProviderFailure(
                    "Supervised CLI failed; exit " + str(process.returncode),
                    kind="CLI_EXECUTION_FAILED",
                )
            if len(stdout) > 2_000_000:
                raise ProviderFailure(
                    "CLI receipt exceeded bounds", kind="CLI_OUTPUT_LIMIT"
                )
            if self.executor == "codex-cli":
                try:
                    events = [
                        json.loads(line) for line in stdout.splitlines() if line.strip()
                    ]
                except ValueError as exc:
                    raise ProviderFailure(
                        "CLI JSON events invalid", kind="CLI_RECEIPT_INVALID"
                    ) from exc
                thread = next(
                    (
                        e.get("thread_id")
                        for e in events
                        if e.get("type") == "thread.started"
                    ),
                    None,
                )
                turn = next(
                    (e for e in events if e.get("type") == "turn.completed"), None
                )
                if not thread or not turn or not output.is_file():
                    raise ProviderFailure(
                        "CLI completion receipt missing", kind="CLI_RECEIPT_MISSING"
                    )
                usage = turn.get("usage", {})
                return ProviderResult(
                    output.read_text(),
                    "CODEX:" + thread,
                    self.model,
                    TokenUsage(
                        usage.get("input_tokens", 0), usage.get("output_tokens", 0)
                    ),
                )
            try:
                result = json.loads(stdout)
            except ValueError as exc:
                raise ProviderFailure(
                    "Claude CLI result invalid", kind="CLI_RECEIPT_INVALID"
                ) from exc
            if (
                result.get("is_error")
                or not result.get("session_id")
                or not result.get("structured_output")
            ):
                raise ProviderFailure(
                    "Claude CLI completion receipt missing", kind="CLI_RECEIPT_MISSING"
                )
            usage = result.get("usage", {})
            return ProviderResult(
                json.dumps(result["structured_output"]),
                "CLAUDE:" + result["session_id"],
                self.model,
                TokenUsage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
            )
