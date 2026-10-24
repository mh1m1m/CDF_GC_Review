# Executive intelligence architecture and metric contract

## Existing boundaries retained
The ReviewOrchestrator, independent role contexts, MAT advisor, evidence registry, productive-cycle cap, provenance receipts, trust/signature checks and release gate remain authoritative. The only orchestrator change adds the actual MAT stage to its recorded outcome. No workflow framework, database server, model evaluator or provider was introduced.

`IntelligenceService.capture` is an in-process adapter for a real `ReviewExecution`. It requires case grants/admin role, exact observation identities and the reviewed document hash matching intake. It persists a bounded Pydantic snapshot in the existing SQLite database and adds a case audit event. There is no HTTP endpoint that accepts fabricated execution claims. Stored snapshots are hash checked and bound to the case's source/evidence hashes on read.

`GET /api/cases/{case_id}/intelligence` uses the existing authenticated loopback/case-grant boundary. The API remains synthetic-only and refuses institutional run snapshots. Reference candidates are separately identified real public reference content, not synthetic case evidence or current institutional authority.

The actual trace chain/head/run/fingerprint are checked before provider-source counters are projected. Missing or broken receipts never become live inference merely because an outcome says LIVE. Local hash consistency is not provider cryptographic attestation or protection from an adversary who controls every local artifact. The dashboard is a recorded snapshot, not a fabricated live event stream.

## Read-model metrics
Every ratio carries numerator, denominator, value, unit, lineage, calculation time, case evidence hash, limitations, status, synthetic marker, and a null confidence/threshold field. Zero or missing denominators return null/NOT_ESTABLISHED. No aggregate readiness score can override a hard gate.

| Metric | Numerator | Denominator | Interpretation and limit |
|---|---|---|---|
| Reference evidence coverage | Distinct case observations with a bound non-DOCUMENT reference of APPROVED_CURRENT/EXTERNAL_BINDING class and APPLICABLE status | Case observations | A hashed quote anchor alone cannot establish authority; stricter than simple occurrence coverage |
| Objections resolved | Recorded adjudications with UPHELD_UNCHANGED, UPHELD_WITH_REVISION, NARROWED_TO_GCO_SCOPE or ROUTED_OUTSIDE_GCO | Recorded exchanges | Workflow disposition, not human approval or authority to issue |
| Repeat objections | Black actor attempts rejected for EXACT/NGRAM/JACCARD repeat | All recorded Black productive turns plus unsuccessful attempts | Existing engine detection only, not an independent linguistic quality score |
| MAT reversal | Reassessments whose recorded position_changed is true | Recorded MAT reassessments | Advisory self-correction, not fidelity to a person's methodology |
| Calibration coverage | Observations with a latest SUBMITTED calibration event | Case observations | Distinct observations, not event count; draft decisions excluded; local identities not institutional signatures |
| Human alignment | Unknown | Unknown | No independent validated human labels joined to model predictions; always NOT_ESTABLISHED here |
| Recorded authorization readiness | 0 when the actual INSTITUTIONAL_ISSUE gate check failed | 1 for an available captured check | A recorded passing check is not exposed as current authorization; issue-time revalidation remains mandatory |

Unresolved material findings are IDs with material categories and no submitted decision, or a submitted withdrawal/escalation/evidence request. The heatmap counts category membership and calibration status; it is not an invented probability/severity risk matrix. Multi-category observations may appear in multiple rows. The lifecycle combines observed file changes, recorded calibration and actual debate dispositions without turning missing comments into withdrawals.

## UI and observability
React Flow renders recorded role sources/states and actual adjacent execution relationships, with drill-downs and keyboard-accessible alternatives. It does not simulate agent activity. Evidence edges come only from registry.basis. The source explorer separately shows page-linked candidate authority/responsibility relationships, explicitly not binding. Graph node counts are bounded; source search and detail lists provide alternatives.

ECharts is modular, SVG-rendered and lazy loaded; gauges, family distributions and materiality counts read the backend contract. HTML tooltips are disabled in favor of rich-text rendering. CSS glass effects are creative digital extensions; reduced motion and high contrast use explicit media queries. Text alternatives expose chart numbers and lineage. Arabic Noto/Carlito are runtime font fallbacks, not a new claim of official typography.

OpenTelemetry API spans cover read-model projection only and include two allowlisted attributes: synthetic boolean and observation count. No exporter/SDK endpoint is configured. No prompt, source excerpt, reviewer identity, document name, case ID or provider credential is added to telemetry. Existing agent traces remain the execution source of truth.

## Draft exports and consistency
`GET /api/cases/{case_id}/intelligence/export/{docx|xlsx|pdf}` reuses the same read model and case access checks. These are permanently named INTERNAL_DRAFT and carry package/footer draft markers. No issuing flag exists. Word and Excel reuse the original unmodified light-background CDF wordmark. Word contains editable text/tables and explicitly static local-rendered gauge artwork. Excel contains native editable charts, cell formulas, filtering, conditional formatting, debate/timeline/observation lifecycle and provenance sheets. PDF uses the verified stable LibreOffice route. Spreadsheet text is stored as text to prevent formula injection.

These executive summaries do not replace the existing native-comment DOCX engine, round register or official gated exporters. Word artwork is static; Excel charts are native. Unknown measures remain unknown in all formats. Independent Calc reconciliation and PDF parsing validate the new exports.

## Run locally

```sh
python -m pip install -r requirements-visual.txt -r requirements-security.txt
python tools/seed_visual_demo.py --db build/private/mat-calibration-dev.sqlite
# Generate a random CDF_CALIBRATION_DEV_TOKEN (at least 32 characters), never commit it.
# Set CDF_CALIBRATION_MODE=SYNTHETIC_LOCAL_DEV and the matching CDF_CALIBRATION_DB.
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8765
# In another terminal:
npm --prefix apps/web ci
npm --prefix apps/web run dev
```

Automated synthetic browser acceptance: `python tools/run_visual_acceptance.py`. It creates a temporary database/token, starts the local API, and runs Playwright; no real institutional case is used. Browser traces are disabled to avoid recording bearer headers. Screenshot baselines mask credentials/timestamps and use a 2.5% cross-rendering pixel threshold; intentional updates require review, not automatic CI regeneration. The desktop/mobile screenshots are actual browser output.

## Security and operational limits
The public source guard, scoped Bandit boundary scan, npm advisory scan and PyPI audit are independent checks, not an exhaustive penetration test or DLP/history certification. Initial Pillow/pypdf advisories were resolved by tested lock updates. Gitleaks and independent model-evaluation suites are deferred with reasons in VISUAL_DEPENDENCIES.md. Provider execution, institutional identity/UAT, human-labelled methodology validation, source currency/approval and production deployment remain unverified or externally dependent. No new library grants institutional authority.
