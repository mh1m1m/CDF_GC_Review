# Repository structure — mh1m1m/CDF_GC_Review (PUBLIC)

Branch `development/v7.12-production-engineering` (draft PR to `main`, not merged). The repository is public by the
owner's decision; everything in it must be safe to publish. The complete local tree (250 files, including the
institutional inputs and the protocol texts) is preserved outside GitHub and is **never** pushed.

## Tracked (public, 142+ files)

- `main.py`, `migrate_to_v712.py`, `migrate_v710_to_v711.py`, `requirements.txt`, `requirements-lock.txt`, `README.md`
- `cdf_gco_crms/` — engine: config, model, ingestion, rounds, reconciliation, analytics, excel, word, guidance, branding,
  migration, qa, regression, references (parsers, index, **public SYNTHETIC fixture** `synthetic_index.py`), assurance,
  **release** (`authorization_gate.py`), protocol (`render.py` only)
- `tests/` — the regression suite that runs on a public clone: TEST 01–20 (+12b, 19b), 25–27, 24 brand (page render
  test skips), 28 titles, 29 security, 30 Word lifecycle, 32 end-to-end, **33 release gate**, **34 synthetic
  reference**; `conftest.py` provides the `reference_index` fixture (institutional sources when present, else the
  synthetic fixture; `CDF_TEST_SYNTHETIC_REFERENCE=1` forces the fixture)
- `tools/` — build, docs, packaging, lineage audit, patch status, baseline audit, RC build, smoke test (10 scripts)
- `PATCH-STATUS.json` / `PATCH-STATUS.md`, `RELEASE-GATE-MATRIX.xlsx`, `CHECKPOINT.md`, `REPOSITORY-STRUCTURE.md`, `.gitignore`
- `AI_AGENT_FORENSIC_AUDIT/` — read-only audit harness scripts and the nine reports, plus `REMEDIATION-STATUS.md`
  (what each finding's status is after this branch); no sealed cases, no live outputs, no execution records

## Excluded by policy (`.gitignore`; never in any pushed commit)

| Excluded | Why |
|---|---|
| `sources/` (reference PDFs and text extracts, `INSTITUTIONAL-SOURCE-STATUS.json`, decisions, kit, design-guide pages, v7.11 round files, issued register) | institutional records and policies not cleared for publication |
| `cdf_gco_crms/protocol/v711_amendments.py`, `v712_amendments.py`, `consolidate.py`, `tools/build_protocol.py`, `tools/decisions_traceability.py`, `tests/test_protocol.py` | carry or build the institutional protocol text |
| `tests/test_references.py`, `tests/test_challenge.py` | assert on passages of the institutional sources |
| `assets/` (logo), `sources/CDF_Design_Guide.pdf`, page renders | restricted brand assets |
| `EVIDENCE/` | baseline manifest names institutional files |
| `AI_AGENT_FORENSIC_AUDIT/cases/`, `evidence/agent_execution_records/`, `evidence/live_outputs/`, `live_prompts/`, `synthetic_case_generator.py`, `reports/STATUS-FORM.md` | sealed cases, live transcripts that quote mandate excerpts, internal status form |
| `deliverables/`, `build/`, `dist/` | regenerated outputs; the production RC ZIP and the audit-evidence backup are kept as downloadable artefacts outside the repository until every member is cleared |
| `*.env`, `*.key`, `*.pem`, `*.rejected.json`, caches, virtual environments | credentials and local state |

No licence file is included: a licence is assigned only on the owner's explicit authorisation.

## What a public clone can and cannot do

- Can: install from `requirements-lock.txt`, run the whole test suite (institutional-source tests skip with a printed
  reason; 1 brand render test skips), run every `main.py` command on synthetic inputs, run `review`/`challenge`/
  `adjudicate` with `--synthetic-reference`, exercise the release gate end to end.
- Cannot: reproduce the institutional reference index, the protocol consolidation, the lineage audit of the v7.11 round
  files, the brand page verification, or build the release candidate. Those need the excluded inputs, provisioned from
  the institution's authorised store at the paths the tools name — never from this repository.

## Remaining institutional metadata in public files (for the owner's review)

- Engine defaults name the two reference documents by title (`cdf_gco_crms/references/index.py`, `tests/test_assurance.py`
  paths, `tools/write_docs.py` wording) and one unit name appears in `AI_AGENT_FORENSIC_AUDIT/debate_audit.py`.
  Document titles only; no content. Say the word and they are replaced by placeholders.
- `cdf_gco_crms/config/workbook_settings.py` carries the author name used in the package properties (owner's own name).
