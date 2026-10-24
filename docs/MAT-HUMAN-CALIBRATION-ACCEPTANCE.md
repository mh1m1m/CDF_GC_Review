# CDF–GCO–CRMS v7.12 — MAT Human Calibration Acceptance Register

**Branch:** feature/v712-mat-human-calibration (Draft PR #5)  
**Purpose:** Controlled **synthetic local-development pilot**, NOT an institutional CDF deployment.

## Executable capabilities

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Case/observation persistence | SQLite `cdf_gco_crms/calibration/store.py`, append-only events | Synthetic pytest + API tests |
| Case permissions | Persisted explicit grants enforced by `CalibrationService` | Negative authorization tests |
| Material observation guard | Preserves original text; recorded WITHDRAW requires rationale/reasons/evidence or evidence gap | Synthetic pytest + Chromium E2E |
| Decision vs DNA rule separation | Separate event type, distinct role, requires submitted event hashes | Synthetic tests |
| Candidate profile versioning | `profile_compiler.py`, `profile_versions`, `active_profiles` | Synthetic tests; never produces binding profile |
| Profile load compatibility | Compiled fixture loads through MAT `load_profile` | Synthetic tests |
| DOCX comment forensics import | `importer.py`, using existing OOXML comparator | Synthetic DOCX tests |
| XLSX evolution import | `excel_importer.py`, strict identifiers, exception register | Synthetic XLSX tests |
| Quantitative analytics | `analytics.py` excludes missing/empty texts in per-version denominators | Synthetic tests |
| Arabic RTL web interface | React + TypeScript + Vite | CI TypeScript/build + Chromium browser interaction |
| HTTP API | Loopback-only FastAPI in `SYNTHETIC_LOCAL_DEV` mode | TestClient and browser interactions |
| Browser persistence | Save decision; reload page; reopen case; verify persisted record | Chromium E2E |
| Withdrawal fail-closed | Unsubstantiated material-withdrawal request rejected | Chromium E2E |

**Important:** GitHub Actions success is only evidence for the exact tested commit, not for later commits.

## Screens / user journeys

1. Cases dashboard and completion scorecards.
2. Original versus reviewed observation with bounded token-level red/green diff.
3. Record human decision, rationale, evidence and draft/submitted status.
4. Review potentially material withdrawals and missing observations.
5. Recommendations/questions analytics with per-version denominators.
6. Writing-DNA patterns from a versioned synthetic profile.
7. Review a DNA rule separately using existing submitted calibration evidence.
8. Compile, inspect, activate and revert a **provisional synthetic** profile version.
9. Append-only event-history viewer (local audit transparency).

## Local execution

Use only synthetic data.

```bash
python -m pip install -r requirements-calibration.txt
export CDF_CALIBRATION_MODE=SYNTHETIC_LOCAL_DEV
export CDF_CALIBRATION_DEV_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(36))')"
export CDF_CALIBRATION_DB=build/private/mat-calibration-dev.sqlite
python tools/mat_dna/seed_calibration_demo.py --db "$CDF_CALIBRATION_DB"
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8765
```

In a second terminal under `apps/web/`:

```bash
npm install
npm run dev
```

Open the loopback-only Vite URL. Paste the temporary developer token in the login panel.
**Do not use this service with institutional documents or expose it on the public internet.**

Run tests:

```bash
python -m pytest tests qa_public -q
cd apps/web && npm run build && npm run test:e2e
```

Browser test requires the API running, a seeded fictional case and Chromium installed.
The GitHub workflow provisions these prerequisites automatically.

## Limitations that prevent institutional production

1. **Institutional identity provider / SSO not configured.** Developer bearer token is an ephemeral synthetic identity, NOT production authentication or proof of MAT's signature.
2. No institutional case-level permission provisioning, segregation of human reviewers or organizational audit administrator.
3. Real CDF DOCX, XLSX, professional DNA and personal comments have **not** been copied to GitHub or sent to an external LLM provider.
4. No human-validated or institutionally attested MAT methodology rules. Synthetic approvals are always PROVISIONAL / NOT_APPROVED and cannot bind the agent.
5. Live LLM inference in PR #3 / PR #4 remains unverified; tests use synthetic MOCK/DETERMINISTIC paths.
6. Hash-chained SQLite events protect against incidental mutation, but **do not provide externally anchored tamper-proof evidence**. An operator with DB control can rewrite records.
7. Offline importers must be used within an authorized private workspace. The web API deliberately rejects unlabelled institutional file uploads.
8. Browser E2E covers a fictional local case, not a real user authentication or full professional DNA fidelity validation.
9. Formal data retention, backup/restore, encrypted institutional storage, penetration testing, performance testing and organizational acceptance are outstanding.

## Verdict

- **Synthetic local pilot:** capable of running, subject to passing browser + Python CI on the current commit.
- **Professional MAT DNA validation:** NOT_APPROVED, one source case (previous report), human calibration outstanding.
- **Institutional authorization:** NOT_AUTHORIZED.
- **Production readiness:** NOT_READY.
- **Merge policy:** PR #5 remains Draft; PR #3 and PR #4 remain untouched.

## Code/data boundary

Public: generic extraction, domain, API, React and tests, all fictional.  
Private: CDF Word agreements, actual comments, real reviewer approvals, private data, private profile files, database and evidence.

No artifact or database in the public Git repository constitutes a genuine MAT-approved profile.
