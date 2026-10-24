# MAT Human Calibration — engineering slice 1

This branch introduces a **private-data-only calibration domain store** and synthetic tests. It is an incremental work-in-progress, **not a completed human-calibration interface** or institutional authentication service.

## What is implemented

- Explicit case import with source SHA-256, per-observation evidence digest, duplicate observation checks.
- Distinction between `REMOVED_FROM_VERSION` and a verified human withdrawal.
- Append-only calibration event history with reviewer, rationale, source binding, timestamp and hash linkage.
- Fail-closed reviewer-context checks and separate `CALIBRATION_REVIEWER`, `CALIBRATION_ADMIN` and `DNA_RULE_APPROVER` permissions.
- Material withdrawal requires a reason and either evidence references or an explicit evidence-gap reference; original observation is not deleted.
- DNA-rule review is separately authorized and must refer to an existing calibration event.
- Progress counters, source-binding checks and audit-chain verification.
- Synthetic unit tests.

## Not implemented / not authorized

- **No web UI, API endpoints, SSO, institutional identity provider, or hardened deployment.**
- ReviewerContext is a trusted-server input contract **not an identity proof**. Never populate it directly from a user-supplied HTTP request.
- SQLite is for local/private prototyping only; the hash chain is tamper-evident against casual edits but is **not cryptographically anchored outside its operator**.
- No MAT DNA rules have been human approved by this implementation.
- No external AI provider has been called; no institutional source file or comment is committed.
- No automated profile compilation, rollback UI, export or dashboard yet.

## Remaining next steps

1. Implement authenticated service boundary and per-case authorization, with CSRF protections and secure session handling.
2. Create a private-only API and Arabic RTL mobile-friendly calibration UI.
3. Implement forensic importer and match verification for real original/reviewed DOCX and XLSX without retaining restricted source data in repository.
4. Separate decision submission, supervisory verification and rule approval using actual institutional identities and policy.
5. Add profile compile/rollback workflow, material-preservation guard checks and API/browser e2e/security tests.
6. Measure calibration on independent source cases before generalizing writing or withdrawal rules.
7. Run live-provider trials only on synthetic material with operator credentials and explicit provider controls.

## Data security

This repository is public. Store all professional comments, institutional agreements, observations, calibrated decisions, database files and personal profile documents **outside Git and in authorized private storage**. Do not expose the SQLite database on a public server.

## Running tests

`python -m pytest tests/test_mat_calibration.py -q`

For all public-safe tests: `python -m pytest tests qa_public -q`.

## Local synthetic end-to-end trial (new)

This is a developer-only pilot. It does **not** contain CDF review comments, does not configure
institutional SSO, and does not issue institutional documents.

1. Install the Python backend environment:
   `python -m pip install -r requirements-calibration.txt`.
2. Generate a fresh random development token with Python's `secrets.token_urlsafe(36)` and set
   `CDF_CALIBRATION_DEV_TOKEN` to it. Set `CDF_CALIBRATION_MODE=SYNTHETIC_LOCAL_DEV`.
   Do not commit these environment values.
3. Seed fictional data:
   `python tools/mat_dna/seed_calibration_demo.py --db build/private/mat-calibration-dev.sqlite`.
4. Start the backend **bound to loopback**:
   `python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8765`.
5. In `apps/web`, run `npm install`, then `npm run dev`.
6. Open the loopback-only Vite URL, paste the temporary developer token into the login
   field, select `SYN-MAT-DEMO-001`, review a fictional observation, submit a decision,
   and inspect the updated audit events and dashboard.
7. Stop the processes and remove temporary developer credentials when finished.

**Limitations:** The user-facing interface is an integrated prototype, not production-authenticated,
and currently implements dashboard, comparison panels, decision form, materiality warning,
summary metrics, history and preliminary rule review. It does not yet render token-level diffs,
import private DOCX through the browser, compile/rollback profiles, or provide independent
institutional rule approvals. The developer token authenticates only a local synthetic
identity and must never be used outside an isolated developer machine. Frontend and API
must not be internet-exposed. The UI stores the token only in component memory.

Run additional API tests using:
`python -m pytest tests/test_mat_calibration.py tests/test_mat_calibration_api.py -q`.

The documentation deliberately does not classify the system PILOT_READY until the
end-to-end workflow is actually executed and security acceptance is demonstrated.
