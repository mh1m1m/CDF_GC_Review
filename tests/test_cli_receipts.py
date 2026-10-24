"""Real local pipes test diagnostic capture; these are not model executions."""

import json
import subprocess
import sys
import pytest
from cdf_gco_crms.agents.providers.cli_receipts import collect
from cdf_gco_crms.agents.providers.base import ProviderFailure
from cdf_gco_crms.execution.jobs import kill_tree


def child(code):
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def test_partial_errors_survive_timeout_without_raw_secret_or_replay():
    records = []
    p = child(
        'import sys,time;sys.stdin.read();print(\'{"type":"thread.started","thread_id":"fixture"}\',flush=True);print(\'{"type":"error","message":"403 connection SYNTHETIC_SECRET_DO_NOT_RECORD"}\',flush=True);time.sleep(20)'
    )
    with pytest.raises(ProviderFailure) as e:
        collect(
            p,
            "synthetic",
            executor="codex-cli",
            timeout=0.5,
            kill=kill_tree,
            observer=records.append,
        )
    assert e.value.kind == "CLI_UPSTREAM_ACCESS_DENIED" and p.poll() is not None
    assert records[-1]["phase"] == "UPSTREAM_ACCESS_DENIED_OUTCOME_UNVERIFIED"
    assert "HTTP_403" in records[-1]["error_categories"]
    assert records[-1]["event_counts"]["thread.started"] == 1
    assert "SYNTHETIC_SECRET_DO_NOT_RECORD" not in json.dumps(records)
    assert records[-1]["inference_verified"] is False


def test_bounded_pipes_reject_oversize_and_nonreading_child():
    p = child(
        'import sys;sys.stdin.read();sys.stdout.write("x"*2100000);sys.stdout.flush()'
    )
    with pytest.raises(ProviderFailure) as e:
        collect(p, "synthetic", executor="codex-cli", timeout=5, kill=kill_tree)
    assert e.value.kind == "CLI_OUTPUT_LIMIT"
    p = child("import time;time.sleep(20)")
    with pytest.raises(ProviderFailure) as e:
        collect(p, "x" * 500000, executor="codex-cli", timeout=0.2, kill=kill_tree)
    assert e.value.kind == "CLI_TIMEOUT" and p.poll() is not None


def test_completion_metadata_does_not_itself_assert_verified_inference():
    p = child(
        'import sys;sys.stdin.read();print(\'{"type":"turn.completed","usage":{"input_tokens":1}}\')'
    )
    output, receipt = collect(
        p, "synthetic", executor="codex-cli", timeout=5, kill=kill_tree
    )
    assert json.loads(output)["type"] == "turn.completed"
    assert receipt["completion_observed"] is True
    assert receipt["inference_verified"] is False


def test_codex_contract_selects_model_and_disables_daemon_without_exposing_session(
    tmp_path, monkeypatch
):
    from cdf_gco_crms.agents.providers.cli_adapter import SupervisedCLIAdapter
    from cdf_gco_crms.agents.providers.base import ProviderConfig
    from cdf_gco_crms.agents.contracts import AgentRequest, ROLE_DRAFTING, SCHEMAS

    argsfile = tmp_path / "args.json"
    binary = tmp_path / "fake-local-cli"
    binary.write_text(
        "#!"
        + sys.executable
        + "\nimport sys,json,os\nfrom pathlib import Path\nsys.stdin.read()\nPath("
        + repr(str(argsfile))
        + ').write_text(json.dumps({"args":sys.argv[1:],"dev_token_present":bool(os.getenv("CDF_CALIBRATION_DEV_TOKEN"))}))\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps({"observations":[],"gaps_not_drafted":[],"reasoning_summary":"SYNTHETIC LOCAL CONTRACT ONLY"}))\nprint(json.dumps({"type":"thread.started","thread_id":"LOCAL_FAKE_ONLY"}))\nprint(json.dumps({"type":"turn.completed","usage":{"input_tokens":0,"output_tokens":0}}))\n'
    )
    binary.chmod(0o700)
    monkeypatch.setattr("shutil.which", lambda _: str(binary))
    monkeypatch.setenv("CDF_ENABLE_SUPERVISED_CLI", "1")
    monkeypatch.setenv("CDF_CLI_MODEL", "fixture-model")
    monkeypatch.setenv(
        "CDF_CALIBRATION_DEV_TOKEN", "SYNTHETIC_SECRET_MUST_NOT_REACH_CHILD"
    )
    adapter = SupervisedCLIAdapter(
        ProviderConfig(model="fixture-model", timeout_seconds=5, max_retries=0),
        "codex-cli",
    )
    adapter.client_injected = (
        True  # This fake process is never trusted live/API provenance.
    )
    result = adapter.complete(
        AgentRequest(
            ROLE_DRAFTING, "Synthetic", {"label": "SYNTHETIC"}, SCHEMAS[ROLE_DRAFTING]
        )
    )
    observed = json.loads(argsfile.read_text())
    assert observed["args"][:4] == ["--model", "fixture-model", "--no-daemon", "exec"]
    assert (
        "--ignore-user-config" in observed["args"] and "--sandbox" in observed["args"]
    )
    assert observed["dev_token_present"] is False
    assert result.invocation_id == "CODEX:LOCAL_FAKE_ONLY"
