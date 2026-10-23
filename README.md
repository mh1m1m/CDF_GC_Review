<!-- Author: Mohammed Alsaleh | Last modified by: Mohammed Alsaleh | Company: صندوق التنمية الثقافي | Title: CDF–GCO–CRMS v7.12 source -->
# CDF–GCO–CRMS v7.12 — workbook engine

Builds the requester feedback workbook of the CDF–GCO–CRMS protocol with its executive dashboard
"لوحة المتابعة التنفيذية" (protocol Art. 10.4A) in the CDF brand library of Annex D.11 (v7.12), appends review
rounds, migrates v7.10 and v7.11 workbooks, writes Word follow-ups as native reply threads (G-SYNC-9),
reconciles with Word comments, carries the institutional reference index (02.6, D.13) and the adversarial
challenge engine (19A), and runs the G-DASH, G-UX and G-REF gates.

    python main.py --help                      # round1 | append | rebuild | migrate | verify | gates | inventory | ingest |
                                               # finalize-titles | build-excel | build-word | import-owner-return | audit-history |
                                               # qa | demo-e2e | release | review | challenge | adjudicate (codes 0/1/2/3/4)
    python -m pip install -r requirements-lock.txt   # exact versions of the release candidate (Python ≥ 3.11)
    python migrate_to_v712.py SRC OUTDIR        # v7.10 or v7.11 to v7.12 migration
    python -m pytest tests -q                  # TEST 01–20 (+12b, 19b), 25–27, 21 references, 22 assurance, 23 protocol, 24 brand,
                                               # 28 titles, 29 security, 30 Word lifecycle, 31 challenge, 32 end-to-end
    python tools/build_deliverables.py         # rebuild every deliverable from scratch (stages: demo migration verify render gates tests registers references results protocol decisions)
    python tools/baseline_audit.py EVIDENCE    # SHA-256 manifest of every authoritative input (V712-001)
    python tools/patch_status.py               # PATCH-STATUS.json/.md and the release-gate matrix from the evidence on disk
    python tools/build_rc.py                   # dist/CDF-GCO-CRMS-v7.12-PRODUCTION-RC-COMPLETE.zip (folders 01–10)
    python tools/write_docs.py                 # QA report and implementation guide from build/state.json

Layout: `cdf_gco_crms/` (engine), `tests/` (regression), `tools/` (build, render, docs, packaging),
`cdf_gco_crms/references/` (organisational structure and authority matrix index), `cdf_gco_crms/assurance/`
(reference verification, production guard, objection engine), `assets/` (supplied logo), `sources/` (v7.10 and v7.11 protocols, directives, design-guide pages, institutional references, earlier packages).
See CDF-GCO-CRMS-v7.12-IMPLEMENTATION-GUIDE.md for the Arabic operating guide.
