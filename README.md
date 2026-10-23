<!-- Author: Mohammed Alsaleh | Last modified by: Mohammed Alsaleh | Company: صندوق التنمية الثقافي | Title: CDF–GCO–CRMS v7.12 source -->
# CDF–GCO–CRMS v7.12 — workbook engine

Builds the requester feedback workbook of the CDF–GCO–CRMS protocol with its executive dashboard
"لوحة المتابعة التنفيذية" (protocol Art. 10.4A) in the CDF brand library of Annex D.11 (v7.12), appends review
rounds, migrates v7.10 and v7.11 workbooks, writes Word follow-ups as native reply threads (G-SYNC-9),
reconciles with Word comments, carries the authority reference index (02.6, D.13), runs the deterministic
pre-issue challenge (19A) and enforces a release authorisation gate (19A.9) on every issuing command.

This is the **public engineering repository**. It holds the engine, the tests, the build tools, the patch register
and the forensic audit harness. It holds **no** institutional document, reference PDF, review case, brand asset or
protocol text: `REPOSITORY-STRUCTURE.md` lists what is tracked and what is excluded by policy.

## Status (three dimensions, never merged into one claim)

| Dimension | Status |
|---|---|
| Deterministic engineering | COMPLETE — 60-patch register: 49 PASS, 8 NOT_VERIFIED, 3 BLOCKED_EXTERNAL (`PATCH-STATUS.md`) |
| Multi-agent AI | NOT_VERIFIED — the challenge roles are deterministic rules in one process; no live, isolated agents in the product (`AI_AGENT_FORENSIC_AUDIT/reports/`) |
| Institutional approval | PENDING — never granted by a tool; the `release` command and the gate only report |

## Quick start (fresh public clone)

    python -m pip install -r requirements-lock.txt   # exact versions (Python ≥ 3.11); LibreOffice optional (render/recalc tests skip without it)
    python -m pytest tests -q                        # the whole suite runs without institutional files:
                                                     # the reference layer falls back to the public SYNTHETIC fixture
    CDF_TEST_SYNTHETIC_REFERENCE=1 python -m pytest tests -q   # force the fixture even where the sources are on disk
    python main.py --help

Tests that need the institutional reference PDFs (`tests/test_references.py`, `tests/test_challenge.py`, parts of
`tests/test_assurance.py`) and the design-guide page render (one test in `tests/test_brand.py`) **skip** on a public
clone with the reason printed; everything else, including the end-to-end case, the challenge and the release gate,
runs on `cdf_gco_crms/references/synthetic_index.py` — a fictional organisation and matrix labelled
`SYNTHETIC_NOT_APPROVED` everywhere.

## Workflow and the release gate

    python main.py round1 INPUT.json OUT_DIR                        # → "<name> - WORKING-COPY.xlsx" (a draft is never issuable)
    python main.py review  WB.xlsx --docx CASE.docx [--synthetic-reference]   # 19A challenge → build/adversarial/*.json + gate record
    python main.py adjudicate WB.xlsx DECISIONS.json --docx CASE.docx --trust-store KEYS.json   # signed reviewer decisions only
    python main.py build-excel WB.xlsx OUT_DIR [--issue]            # issuable only when the gate record for THIS content is CLEAR
    python main.py build-word  WB.xlsx OUT.docx [--source CASE.docx]
    python main.py append RETURNED.xlsx ROUND.json OUT_DIR --delivered DELIVERED.xlsx   # → next-round WORKING-COPY

`cdf_gco_crms/release/authorization_gate.py` fingerprints the reviewed content (document, rounds, every
observation's text and cells; title decisions carry their own proof). `rebuild`, `finalize-titles`, `build-excel` and
`build-word` refuse (return code 3) while no CLEAR, unaltered review record exists for exactly that fingerprint;
`--working-copy` writes a marked, non-issuable working copy instead (file suffix ` - WORKING-COPY`, marker in the
package properties). A review run with `--synthetic-reference` never authorises a non-demo issue.
Return codes: 0 OK · 1 FAIL · 2 input error · 3 refused by policy · 4 NOT_VERIFIED.

## Build and evidence tools

    python tools/build_deliverables.py         # stages: demo migration verify render gates tests registers references results protocol decisions
    python tools/baseline_audit.py EVIDENCE    # SHA-256 manifest of every authoritative input (V712-001)
    python tools/patch_status.py               # PATCH-STATUS.json/.md and the release-gate matrix from the evidence on disk
    python tools/lineage_audit.py ROUND_DIR    # lineage of a v7.11 round series; baseline-input failures are classified, never hidden
    python tools/build_rc.py                   # dist/ release candidate (not published; see REPOSITORY-STRUCTURE.md)
    python tools/write_docs.py                 # QA report and implementation guide from build/state.json

Several tools need inputs that are excluded from the public repository (institutional sources, v7.11 round files,
the design guide); they report what is missing rather than fail silently.

## Layout

`cdf_gco_crms/` engine (config, model, ingestion, rounds, reconciliation, analytics, excel, word, guidance, branding,
migration, qa, regression, references incl. the synthetic fixture, assurance, release) · `tests/` regression suite
(TEST 01–34) · `tools/` build, docs, packaging, lineage, patch status · `AI_AGENT_FORENSIC_AUDIT/` read-only audit
harness and reports · `EVIDENCE/` baseline manifest (hashes only, not tracked in the public repository).
