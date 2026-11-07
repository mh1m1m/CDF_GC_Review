# Direct application CLI

Install `requirements-execution.txt` in an isolated Python 3.12 environment. No global `cdf` command is registered. Use a fresh ignored `build/public-demo/` database and provision a random development token through your process environment or secret manager; do not paste credentials into commands, logs or source control. The token must have at least 32 characters. Sessions default to one hour and are not silently refreshed by subsequent CLI invocations. A rotated token may be explicitly provisioned by restarting the local synthetic application; this is not institutional authentication.

```bash
export CDF_CALIBRATION_MODE=SYNTHETIC_LOCAL_DEV
export CDF_OPERATION_MODE=PUBLIC_SYNTHETIC_DEMO
export CDF_CALIBRATION_DB=build/public-demo/unified.sqlite
python -m cdf_gco_crms.cli --help
python -m cdf_gco_crms.cli init --json
python -m cdf_gco_crms.cli case create --source synthetic --case SYN-COOPERATION-001 --idempotency-key example-create-001
python -m cdf_gco_crms.cli review run --case SYN-COOPERATION-001 --executor deterministic --idempotency-key example-review-001 --timeout 120 --wait
python -m cdf_gco_crms.cli debate run --case SYN-COOPERATION-001 --executor mock --idempotency-key example-debate-001 --timeout 120 --wait
python -m cdf_gco_crms.cli debate trace --case SYN-COOPERATION-001
python -m cdf_gco_crms.cli authority check --case SYN-COOPERATION-001 --query تعاون
python -m cdf_gco_crms.cli organization check --case SYN-COOPERATION-001 --query تعاون
python -m cdf_gco_crms.cli calibration list --case SYN-COOPERATION-001
python -m cdf_gco_crms.cli gate --case SYN-COOPERATION-001
python -m cdf_gco_crms.cli report excel --case SYN-COOPERATION-001 --idempotency-key example-excel-001 --wait
```

`case create` atomically imports the fixed fictional DOCX; `case import` inspects that import rather than pretending to accept arbitrary files. `case status` returns source hash, observation IDs, run, calibration version, jobs and artifact metadata. `calibration save` requires the current evidence hash, an observation and rationale. Submitted calibration is a synthetic reviewer action, never an institutional signature.

Job operations: `job status/result/cancel --job JOB-...`; `job recover --case SYN-...` fails expired leases without inference replay and resumes unclaimed jobs. `--wait` polls persisted state; client timeout does not create another job. `artifact get --artifact ART-... --output /authorized/path/report.xlsx` downloads and verifies bytes. Use `--idempotency-key` when retrying mutations.

Exit codes: 0 accepted/success, 2 invalid input, 3 authorization denied, 4 terminal failed/cancelled/blocked job, 5 conflict. Accepted asynchronous jobs may later fail; inspect their terminal state. `--json` is supported; output is structured JSON even without it.

The separate Codex/Claude inference executors require explicit enablement and installed, normally authenticated official CLIs. They run on synthetic inputs only with restricted temporary workspaces. Do not read consumer login files or repurpose their credentials. Use the one-stage `executor probe --executor codex-cli --case ... --wait --timeout 60` for controlled verification after local acceptance. A successful application CLI command alone is not model inference.
