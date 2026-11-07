# v7.15 diagnostic and finalization plan (repo, Supabase, Vercel)

Date: 2026-11-07. Base: `main` @ `0beff45`. Branch: `claude/v715-diagnostic`.
Scope: Phase 1 is read-only. Nothing in Supabase, Vercel or `main` was changed. Phase 2 is a plan that waits for the
protocol owner's approval.

This file cites article numbers only. It contains no protocol text, no Annex F/G text and no Fund document.

Marks: **VERIFIED** (with the command, file:line or tool result), **INFERRED**, **NOT_VERIFIED** (with what would
verify it).

## 0. Headline: the starting facts were wrong in one important way

The brief said the repo has no Supabase or Vercel setup. That is true of `main` only. Two open draft PRs that were not
part of the #14 merge carry it, and one of them is **live in production**:

| Item | State | Mark |
|---|---|---|
| PR #15 `fix/v712-audit-p0` | Open draft. Fixes audit D9–D14, D16–D18, redactions C4–C5, content-aware guard. Base is `claude/project-thread-gi42zn` (already merged to main by #14). | VERIFIED (GitHub `list_pull_requests`) |
| PR #16 `feature/hosted-vercel-supabase` | Open draft, stacked on #15. 30 commits ahead of main: `vercel.json`, `api/index.py`, `api/mcp.py`, Postgres storage, Supabase sign-in, document uploads, AI review, AI settings, mistral/deepseek/xai adapters. | VERIFIED (`git rev-list --count origin/main..origin/feature/hosted-vercel-supabase` = 30) |
| Vercel project `cdf_gc_review` | Production deployment READY, built from `feature/hosted-vercel-supabase` @ `8875617` (2026-10-26). | VERIFIED (Vercel `get_project`, `list_deployments`) |
| Production URL | Answers publicly without Vercel SSO: `/` 200, `/api/health` 200. Sign-in inside the app is limited to listed reviewers. | VERIFIED (`curl`, 2026-11-07) |
| Supabase project `CDF_GC_Review` | ACTIVE, eu-central-1. Schema `cdf` holds the hosted app's tables. | VERIFIED (Supabase `list_projects`, SQL on `pg_class`) |

So the target is not "build Supabase and Vercel". It is: **bring an existing, unmerged, live deployment into line with
v7.15 and with the 00A.4 data boundary**, and fold its code into `main`.

## 1. Engine versus kit 1.1.6

Method: unzipped `cdf-chat-kit-1.1.6.zip` outside the repo, compared every `.py` under `cdf_gco_crms/` and `shared/`
byte by byte against `main` and against `feature/hosted-vercel-supabase`. The kit was not executed.

| Compared with | Same | Differ | Kit only | Repo only | Mark |
|---|---|---|---|---|---|
| `main` | 93 | 45 | 19 | 0 | VERIFIED |
| `feature/hosted-vercel-supabase` (PR #16) | 134 | 21 | 2 | 0 | VERIFIED |

`main` has no code that differs from the merge base `5bc9e48`, and PR #16 contains it. So the chain is
**main ⊂ PR #15 ⊂ PR #16 ⊂ kit 1.1.6** for the engine. The kit was built from PR #16, not from main. (INFERRED from
the counts above.)

Classification of the 45 files that differ from `main` plus the 19 kit-only files:

| Class | Files | Where they live today |
|---|---|---|
| (a) v7.15 feature | 21 files that differ from PR #16, plus `excel/dash_layout.py`: version constants (`__init__.py`), one-sheet dashboard (`config/workbook_settings.py`, `excel/dashboard_writer.py`, `excel/helper_writer.py`, `excel/workbook_builder.py`, `analytics/dashboard_analytics.py`, `config/design_tokens.py`), gates (`qa/gates.py`, `qa/ux_gates.py`, `assurance/production_guard.py` TWO_SHEETS_ONLY / HELPER_RETIRED), required action (`model/entities.py`, `observations/text_derivation.py`, `rounds/round_expansion.py` `action_summary`), migration that drops the v7.14 helper sheet (`migration/migrate.py`), Word comments (`word/document_comments.py`, `word/word_sync.py`), regression registers, guidance entry `dash_jump` | kit only |
| (b) bug fix the repo lacks | 24 files: D9–D14, D16–D18 fixes, guard, provider list | PR #15 / #16, not main |
| (b) small fix | `excel/formula_registry.py` (`$B$13` = `B13` for cached values) | kit only |
| (c) kit-only adaptation | `cdfkit.py` (1,738 lines: composer, 07.2 checks, P-checks), `kit_stages.py` (19A stage packets), `kit_selftest.py`, `branding/icon_extract.py`, `shared/icons/*`, `shared/brand/cdf-wordmark-on-light.png` | kit only |
| (d) repo change the kit lacks | None in the engine. The kit lacks `tests/`, `apps/`, `api/`, `deploy/`, docs, CI, as expected. | — |

**Recommendation:** the repo is the single source of truth, and the kit is built from `main` by a script. Getting
there loses nothing because there is no class (d) in the engine. Order: land PR #15, then PR #16 (or the parts of it
the owner keeps), then port class (a) and the kit-side composer/checker into the package, then build the kit.

Caveat on class (c): `cdfkit.py` holds the only 07.2 / 07.4A comment checks that exist anywhere. They belong in the
engine (for example `cdf_gco_crms/comments/`), with `cdfkit.py` reduced to a thin CLI over them.

Brand caveat (C5): the kit ships `shared/brand/cdf-wordmark-on-light.png` and `branding/icon_extract.py` reads the
institutional design guide. PR #15 swaps the wordmark for a demo mark in synthetic outputs. Porting the kit's brand
files into this public repo needs the owner's C5 decision first.

## 2. v7.15 rule coverage

"Kit" line numbers refer to `cdfkit.py` in kit 1.1.6.

| v7.15 item | `main` | Kit 1.1.6 | Test | Gap | Mark |
|---|---|---|---|---|---|
| Version constants | `cdf_gco_crms/__init__.py:14-16` = 7.12 / 7.12.0 / `.../7.12` | 7.15 / `.../7.15` | none checks the value | bump; ENGINE_VERSION choice (7.15.0) | VERIFIED |
| 07.1 one reason sentence | none | `cdfkit.py:563-564` "07.1 reason is more than one sentence" | none in repo | port + test | VERIFIED |
| 07.2 ceilings (35 / 30 / 60; whole 100 with proposed text, else 70) | none at part level; `assurance/challenge.py:66` `WORD_BUDGET = 120` on the whole body | `cdfkit.py:536-559` implements all five | none in repo | port; lower or split `WORD_BUDGET` (120 is above both 100 and 70) | VERIFIED |
| 07.4A opener "نوصي بـ" (gap) / "نقترح" (improvement) | none | `_OPENER_EXEMPT` (`cdfkit.py:373`) exempts openers, including the question word "هل", from the repetition check; nothing requires the right opener per Observation_Type | none | add check | VERIFIED |
| 07.4A no questions; unseen document becomes a conditional recommendation | `assurance/challenge.py:124` returns `QUESTION_F6`; `challenge.py:606` Red Advocate turns a silent matrix into an F6 question | F6 still a valid form; `cdfkit.py:505-506` G-SUB-12 still demands an F6 question | none | change both to the conditional form; keep F6 only for historical comments (00.2 carve-out) | VERIFIED |
| G-SUB-12 accepts the conditional form | absent | wrong (v7.14 wording, above) | none | rewrite | VERIFIED |
| P14 (more than one reason sentence, or a part above its ceiling) | absent | `cdfkit.py:476-481` still the v7.14 "explanation load" (≤ 50 % reasons, median ≤ 40), WARN only | none | rewrite as v7.15 | VERIFIED |
| R2, R3 of 20.3 amended | no detector named R2/R3 in the engine | none | none | NOT_VERIFIED: the amended R2/R3 need to be mapped to code; owner to confirm which checks they are | NOT_VERIFIED |
| 00.8(3) tests 07.2 ceilings, not the 37-word median | no 00.8(3) runner | none | none | add to the regression run | VERIFIED |
| 08.2A expected closing action | none | `cdfkit.py:297, 333-335` label "الإجراء المتوقع للإغلاق:" | none | port | VERIFIED |
| 08.2B improvement label, not counted in ceilings | none | `cdfkit.py:300, 311-312`; whole-count subtracts one label word only | none | port; confirm the label is excluded from the 07.2 count | VERIFIED |
| 10.4A.17 dashboard required action, approved titles | `observations/text_derivation.py:85`, `ACTION_MAX = 75` (`config/workbook_settings.py:33`) | `action_summary` override (kit 1.1.3) | none | port | VERIFIED |
| 10.4A.2–.12 one-sheet dashboard, calculation block from column R | v7.14 helper sheet `config/workbook_settings.py:7`; `assurance/production_guard.py:105-111` requires it present and hidden | `CALC_FIRST_COL = 18`, TWO_SHEETS_ONLY, HELPER_RETIRED | 9 tests read the helper sheet: `tests/test_regression.py:58,147,260,278,433`, `tests/test_titles.py:92,106`, `tests/test_assurance.py:141,167` | port; change those tests to the calculation block | VERIFIED |
| G-DASH-01/07/08/18/20–24, G-UX-01/02/14/21/22 PASS when met | `qa/gates.py` covers G-DASH-01…20 (v7.11 docstring, line 1); 21–24 absent | `AMENDMENT_DEPENDENT = ()` | none | port gates 21–24 and the UX gates | VERIFIED |
| 19A.3A supplied sources, 19A.6A retaining an observation against adjudication | none in engine | `kit_stages.py:221-223` (supplied sources), `:405-409` (GCO decision on a disposition) | none | port as engine stage contracts | VERIFIED |
| 00A.6 providers anthropic, openai, mistral, deepseek, xai | `agents/provenance.py:44-47` has anthropic and openai only | five, from PR #16 | PR #16 tests | lands with PR #16 | VERIFIED |
| Annex G advisory (PROVISIONAL / NOT_APPROVED) | profiles are PROVISIONAL / NOT_APPROVED (AGENTS.md) | same | existing | keep; do not mark done | INFERRED |

## 3. Tests and CI

| Run | Result | Mark |
|---|---|---|
| `pip install -r requirements-execution.txt -r requirements-security.txt -r requirements-calibration.txt hypothesis` then `python -m pytest tests qa_public -q -p no:cacheprovider -rs` on `main` @ `0beff45`, Python 3.13 | **363 passed, 11 skipped**, 10 subtests (3 live-provider, 7 reference PDFs, 1 design-guide render: all expected) | VERIFIED |
| Same suite after installing only `requirements-lock.txt` + `requirements-calibration.txt` (the AGENTS.md instruction) | 4 collection errors: `httpx` and `hypothesis` missing, `mcp` 2.x installed (FastMCP renamed). AGENTS.md's install line is incomplete; CI uses `requirements-execution.txt`, which pins `mcp==1.30.0`. | VERIFIED |
| Kit selftest (`kit_selftest.py`) | NOT_RUN. Running the uploaded kit is blocked in this environment; the repo has no selftest of its own. Plan step 2 adds one that runs from repo code in CI. | NOT_VERIFIED |
| PR #15 / #16 suites | NOT_RUN here | NOT_VERIFIED |
| UI build `apps/web` | NOT_RUN | NOT_VERIFIED |

Tests that encode v7.14 behaviour and must change (never be deleted) in plan step 1: the 9 helper-sheet references
listed in section 2. No test encodes the 70-word ceiling, F6 questions or NOT_VERIFIED amendment gates, because the
repo has no implementation of them.

CI branch coverage: on `main` only `issuance-policy.yml` and `libreoffice-stable.yml` run for PRs into `main`.
`phase2-copilot.yml`, `remote-connectivity-security.yml` and `unified-execution.yml` list only old `codex/*` branches,
so **they never run for a PR into `main`**. PR #16 adds `hosted-demo.yml`. Plan step 0 fixes the lists. (VERIFIED,
`.github/workflows/*.yml`.)

## 4. Supabase

| Project | Status | Linked to this app | Mark |
|---|---|---|---|
| `CDF_GC_Review` (eu-central-1, Postgres 17) | ACTIVE_HEALTHY | Yes: Vercel env `CDF_SUPABASE_URL`, `CDF_DATABASE_URL` (role `cdf_app`, schema `cdf`) | VERIFIED |
| `CDF Case Management's Project` (ap-northeast-1) | INACTIVE (paused) | No evidence | NOT_VERIFIED: tables cannot be listed while paused; restoring it is the owner's call |

`CDF_GC_Review` project:

- Migrations: `20261025084144 cdf_hosted_demo_role_and_schema` (schema `cdf`, least-privilege role `cdf_app`, no
  rights for `anon`/`authenticated`) and `20261026012044 cdf_ai_keys_vault` (AI keys in Supabase Vault, functions
  callable by `cdf_app` only). These migrations are **not in the repo**; the app creates its own tables at start
  (`cdf_gco_crms/storage.py` on PR #16). VERIFIED.
- Schema `cdf`: 32 tables, RLS off on all of them. Only `postgres` and `cdf_app` have USAGE on the schema, and it is not
  exposed through the Data API, so RLS off is not an open door today. It becomes one if the schema is ever exposed.
  VERIFIED (`has_schema_privilege`).
- Schema `cdf_notifications_v13`: 17 tables with RLS on, from a different app (Vercel project
  `cdf_notification_generator`). One database serves two apps. VERIFIED (table list) / INFERRED (ownership).
- Edge functions: none. Storage buckets: none. Auth users: 1. Vault AI keys: 1. VERIFIED.
- `cdf.runtime_mode` = `PUBLIC_SYNTHETIC_DEMO`. Of 3 calibration cases, 2 are `SYN-`. VERIFIED (counts only).
- Uploaded documents are present in `cdf.uploaded_documents` and were sent for AI review (rows in
  `cdf.document_reviews`). Whether they are synthetic or Fund documents was **not** checked from content, by design.
  The specific counts and markers were reported to the owner privately. NOT_VERIFIED: the owner confirms.
- Advisors: security, 1 WARN (leaked-password protection off). Performance, 18 unindexed foreign keys and 9 unused
  indexes (INFO). VERIFIED.

**What Supabase replaces:** on PR #16 it already replaces the SQLite calibration store and job store (Postgres via
`CDF_DATABASE_URL`), the case grants of the hosted MCP, and sign-in (Supabase Auth for listed reviewers). INFERRED from
PR #16's file list and `docs/deploy/HOSTED_DEMO.md`.

## 5. Vercel

Team `malsalehs-projects`: six projects. Only `cdf_gc_review` deploys this repo (deployments carry
`githubRepo: CDF_GC_Review`). The others (`cdf`, `cdf-investigations`, `cdf-whistleblowing`, `cdf-vhie`,
`cdf_notification_generator`) are separate apps and out of scope. VERIFIED.

`cdf_gc_review`:

- Framework none; Vite static build of `apps/web` plus Python functions `api/index.py` and `api/mcp.py`, region `fra1`,
  from PR #16's `vercel.json`. VERIFIED.
- Last 10 deployments: all READY, all `target: production`, all from `feature/hosted-vercel-supabase`. Production
  follows a feature branch, not `main`. VERIFIED.
- Protection: SSO protection `all_except_custom_domains`, so the production alias is public. `/api/health` reports
  `HOSTED_SYNTHETIC_DEMO`, `SYNTHETIC_CASES_ONLY`, `document_uploads: PUBLIC`, sign-in `SUPABASE_AUTH_LISTED_REVIEWERS_ONLY`.
  VERIFIED (`curl`).
- Environment variable names (values not read): `CDF_DATABASE_URL`, `CDF_SUPABASE_URL`,
  `CDF_SUPABASE_PUBLISHABLE_KEY`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `CDF_HOSTED_REVIEWERS`,
  `CDF_DOCUMENT_UPLOADS`, `CDF_AI_DATA_AUTHORIZATION`, `CDF_ENABLE_PROVIDER_API`, `CDF_REVIEW_RUNNER`,
  `CDF_REVIEW_EXECUTOR`, `CDF_AI_TIMEOUT_SECONDS`, `CDF_ANTHROPIC_KEY_VAR`, an Anthropic key variable, `MISTRAL_API_KEY`,
  `VITE_SITE_IDENTITY`. VERIFIED.
- `VITE_SITE_IDENTITY=CDF` shows the institution's logo and removes the demo labels on the public site. This is the C5
  question in a live setting. VERIFIED (variable and its comment).
- `CDF_DOCUMENT_UPLOADS=PUBLIC` and `CDF_AI_DATA_AUTHORIZATION=INSTITUTIONAL_AUTHORIZED:<owner decision 2026-10-25>`
  let signed-in reviewers upload Word/Excel/PDF files and send them to Mistral or Claude. VERIFIED.
- Runtime errors and build logs: NOT_VERIFIED (all builds READY; runtime logs not pulled).
- Protocol text on a public URL: none found on `/` and the health endpoints. NOT_VERIFIED for the whole bundle.

**Conflict with v7.15:** 00A.4, confirmed 2026-11-07, keeps the web application to synthetic `SYN-` cases and processes
real Fund documents only in a chat assistant under a recorded authorisation. The live upload-and-review path predates
v7.15 and rests on an owner decision of 2026-10-25 recorded only in a Vercel variable. Under v7.15 it is a protocol
question for the owner (decision 1 below), not something to fix silently.

## 6. Repository hygiene from earlier audits

| Item | On `main` | Fixed where | Blocks public deployment? |
|---|---|---|---|
| D9–D14 calibration gate | OPEN (`docs/codex/OPEN_ISSUES.md:45`) | PR #15 | Yes for any hosted calibration (concurrency, second review, audit chain) |
| D16–D18 transport | OPEN | PR #15 | D18 (MCP port on internal network) yes |
| C1 DoA extraction in public history | OWNER DECISION | not fixable without history rewrite | Not for Vercel; yes for the public repo itself |
| C2 public Drive links | OWNER DECISION | — | No |
| C4 handoff real-case forensics | OWNER DECISION | PR #15 redacts | Yes while the repo is public |
| C5 real wordmark on synthetic outputs | OWNER DECISION | PR #15 uses a demo mark; production overrides with `VITE_SITE_IDENTITY=CDF` | Yes for a public site |

All marks VERIFIED from `docs/codex/OPEN_ISSUES.md` on `main` and on PR #15/#16.

## 7. Decisions for the owner

1. **DECIDED 2026-11-07: keep uploads; 00A.4 to be amended.** The owner chose to keep document uploads on the hosted site and to amend 00A.4 so the web application may process uploaded documents. Until the amendment is issued, the site runs ahead of the protocol text. Original question: **Hosted uploads of real documents.** The live site accepts uploads and sends them to an AI provider. v7.15 00A.4
   keeps real Fund documents in a chat assistant.
   *Recommendation:* turn uploads off on the hosted site (`CDF_DOCUMENT_UPLOADS` unset, redeploy) and remove the stored
   uploads after you confirm what they are. *Consequence:* the site goes back to synthetic cases only; document review
   moves to the chat kit. The alternative is a protocol amendment to 00A.4.
2. **Public or protected site.** *Recommendation:* turn on Vercel protection for all deployments (or Supabase sign-in
   in front of every page) until C5 is decided. *Consequence:* the URL stops being public.
3. **C5 on the hosted site.** *Recommendation:* remove `VITE_SITE_IDENTITY=CDF` so synthetic outputs carry the demo
   mark. *Consequence:* no institutional logo on the hosted site.
4. **Source of truth.** *Recommendation:* the repo, with the kit built from `main`. *Consequence:* kit changes go
   through PRs and CI.
5. **PR #15 and #16.** *Recommendation:* retarget #15 to `main` and merge it, then retarget #16 and merge only after
   decisions 1–3. *Consequence:* production then deploys from `main`.
6. **Hosted database.** *Recommendation:* keep the existing Supabase project, synthetic data only, schema moved into
   `supabase/migrations/`, and a separate project or schema for the notification app. *Consequence:* no new project.
7. **Annex G.** *Recommendation:* stays advisory (PROVISIONAL / NOT_APPROVED) until MAT confirms. *Consequence:*
   G-MAT gates stay advisory.
8. **R2 and R3 of 20.3.** Confirm which engine checks they map to, so the amended rules can be implemented.

## 8. Finalization plan (Phase 2)

Each step is one small PR into `main`, CI-green before the next. Nothing runs until the owner approves this plan.
Steps marked **owner go-ahead** touch production, the database or live settings.

| # | Branch / PR | Files | Proof | Approval |
|---|---|---|---|---|
| 0 | `claude/ci-branch-lists` | `.github/workflows/*.yml`: add `main` and `claude/**` to every `pull_request.branches`; AGENTS.md install line → `requirements-execution.txt -r requirements-security.txt -r requirements-calibration.txt`; bump `pypdf` 6.21.2 → 6.21.4 in `requirements-execution*.txt` (7 CVEs, pip-audit red on `main` since 2026-11-07) | all five workflows run on the PR; `visual-security` green | plan approval |
| 1 | PR #15 retargeted to `main` | as is | its CI + full suite | owner says merge |
| 2 | Hosted settings (no code) | Uploads stay on (decision 1). Vercel: per decisions 2–3, enable protection and unset `VITE_SITE_IDENTITY`; record the upload authorisation in the repo docs, not only in a Vercel variable; Supabase: enable leaked-password protection | site needs sign-in; authorisation reference matches the amended 00A.4 | **owner go-ahead** |
| 3 | PR #16 retargeted to `main` | add `supabase/migrations/` with the two existing migrations, RLS enabled (deny-all) on schema `cdf`; `docs/deploy/HOSTED_DEMO.md` env names | `hosted-demo.yml`, Postgres suite, Supabase advisors clean | owner says merge; RLS change is **owner go-ahead** |
| 4 | `claude/engine-v715` | version constants 7.15 / 7.15.0 / `.../7.15`; port the 21 class (a) files + `dash_layout.py`; migration that removes a v7.14 helper sheet; change the 9 helper-sheet tests to the calculation block; gates G-DASH-21–24, G-UX-21/22 | full suite; new tests for TWO_SHEETS_ONLY, HELPER_RETIRED, migration of a v7.14 workbook | plan approval |
| 5 | `claude/comments-v715` | new `cdf_gco_crms/comments/` (composer + checks from `cdfkit.py`): 07.1, 07.2 ceilings, 07.4A openers and no-question rule, conditional form, G-SUB-12, P14, 08.2A, 08.2B; `assurance/challenge.py` drops F6 conversion for new comments and `WORD_BUDGET` follows 07.2 | one negative test per rule; 00.2 carve-out test (historical F6 comment stays valid) | plan approval; R2/R3 after decision 8 |
| 6 | `claude/stage-packets` | engine contracts for 19A.3A and 19A.6A from `kit_stages.py` | stage-record validation tests | plan approval |
| 7 | `claude/kit-build` | `tools/build_chat_kit.py` builds `cdf-chat-kit-<version>.zip` from `main` (engine + thin `cdfkit.py` + `kit_stages.py` + `kit_selftest.py`; brand files only per C5); CI job runs the selftest from repo code | CI artifact; byte-compare with kit 1.1.6 for unchanged files | plan approval |
| 8 | Vercel production from `main` | Vercel production branch → `main`; previews per PR | preview of `main` READY | **owner go-ahead** (promotion) |
| 9 | `claude/docs-v715` | README, `REPOSITORY-STRUCTURE.md`, AGENTS logs; record 00.8 regression NOT_VERIFIED until the reference-case package arrives | public guard PASS | plan approval |

## 9. Gaps against the drafted 00A.4(2) conditions (v7.16 draft, pending approval)

Decision 1 led to a draft amendment that allows hosted document review only while six conditions hold, checked by a
new gate G-ENG-4 (a missing record is FAIL). Existing uploads must meet them or be deleted before any further hosted
review (00A.4(5)). Checked against PR #16 @ `8875617` and the live settings:

| Condition | Today | Gap | Mark |
|---|---|---|---|
| (a) INSTITUTIONAL_AUTHORIZED reference on the deployment, decision in Annex B | `CDF_AI_DATA_AUTHORIZATION` is set in Vercel; uploads are refused without `CDF_DOCUMENT_UPLOADS=PUBLIC` (`documents/policy.py`) | No Annex B row for the 2026-10-25 decision; the reference lives only in a Vercel variable; uploads are gated on `CDF_DOCUMENT_UPLOADS`, not on the reference | VERIFIED |
| (b) Upload, view and review need a listed reviewer signed in | Supabase sign-in limited to `CDF_HOSTED_REVIEWERS` (`interfaces/hosted_auth.py:8-56`); a file is visible only to its uploader (`docs/deploy/HOSTED_DEMO.md`) | No test proves every document and review endpoint refuses an unsigned or unlisted caller; the site shell is public | INFERRED (met) / NOT_VERIFIED (endpoint coverage) |
| (c) Only providers the owner confirmed exclude content from training | All five providers selectable (`interfaces/ai_settings.py:33-44`); production runs Mistral | No allow-list and no refusal of unconfirmed providers; Mistral's plan terms on training not recorded | VERIFIED (gap) / NOT_VERIFIED (Mistral terms) |
| (d) Each upload records role, time, SHA-256, declared classification, executor, model | `uploaded_documents` has `owner_id`, `sha256`, `created_at`; `document_reviews` has `roles_json`, `worker`, `detail_json` | No declared-classification field; role and model are not on the upload record; model recorded only if inside `detail_json` | VERIFIED (columns) / NOT_VERIFIED (model in `detail_json`) |
| (e) Kept only in the deployment's database, not public, deleted after retention | Schema `cdf` not exposed through the Data API; only `postgres` and `cdf_app` have USAGE | No retention period or deletion job; RLS off on all 32 tables | VERIFIED |
| (f) Outputs are working copies until issued, executor PROVIDER_API | Outputs are `INTERNAL_DRAFT__` working copies (`interfaces/hosted_documents.py:20, 296-377`) | Executor not labelled `PROVIDER_API` on outputs | VERIFIED |
| 00A.4(5) existing uploads | Uploaded files and reviews are stored (count reported privately) | Must be brought under (a)–(f) or deleted before further hosted review | VERIFIED |

Plan additions (after v7.16 is approved; until then the conditions are a draft):

| # | Branch / PR | Files | Proof | Approval |
|---|---|---|---|---|
| 2a | `claude/hosted-00a4` on top of PR #16 | upload gate on the authorisation reference (a); endpoint auth tests (b); provider allow-list `CDF_TRAINING_EXCLUDED_PROVIDERS`, refuse others (c); `declared_classification`, `uploader_role`, `executor`, `model` columns (d); retention setting and a scheduled purge (e); `PROVIDER_API` executor label on outputs (f); G-ENG-4 gate over all six | one negative test per condition; G-ENG-4 FAIL on a missing record | plan approval |
| 2b | Live settings | Vercel: allow-list value, retention value; Supabase: apply the column migration; hold further hosted review until G-ENG-4 passes | `/api/health` reports G-ENG-4 PASS | **owner go-ahead** |
| 2c | Existing uploads | bring each stored upload under (a)–(f) (declare classification, record model) or delete it | G-ENG-4 PASS on every stored upload | **owner go-ahead** (deletion is irreversible) |
