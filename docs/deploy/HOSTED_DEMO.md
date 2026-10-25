# Hosted synthetic demo: Vercel + Supabase

Status: **HOSTED_SYNTHETIC_DEMO**. Its calibration cases are fictional `SYN-` cases only; uploaded documents, when
the owner turns them on, are treated as public (see "Document uploads"). It has no institutional activation and no
issuance, and it is not institutional SSO. Every guard of the public synthetic mode still applies; for example, the
database refuses any case whose ID does not start with `SYN-`.

## Architecture

| Layer | Where | What |
|---|---|---|
| Web app | Vercel static output (`apps/web/dist`) | The React app; sign-in through Supabase Auth (`apps/web/src/hosted.tsx`) |
| API | Vercel Python function `api/index.py`, region `fra1` | `apps/api/main.py` in `HOSTED_SYNTHETIC_DEMO` mode; `/api/*` is rewritten here |
| MCP | Vercel Python function `api/mcp.py` | `/mcp` (streamable HTTP, stateless) and `/.well-known/oauth-protected-resource` |
| Data | Supabase Postgres (eu-central-1), schema `cdf`, role `cdf_app` | `cdf_gco_crms/storage.py`: the SQLite engine's SQL translated for Postgres |
| Sign-in | Supabase Auth | `cdf_gco_crms/interfaces/hosted_auth.py`: only listed reviewers are admitted |
| Jobs | Inside the request (`CDF_JOB_RUNNER=inline`) | Serverless hosts kill detached processes |

How the pieces behave:

- **Database:** the API keeps its tables in schema `cdf`, which the Supabase Data API does not expose. It connects as
  `cdf_app`, a role with rights on that schema only (`supabase/migrations/`).
- **Tables:** the API creates them on first start.
- **Seed data:** the fictional demo cases are seeded once and granted to the listed reviewers
  (`cdf_gco_crms/interfaces/hosted_seed.py`).

## Environment variables (Vercel project `cdf_gc_review`)

| Name | Type | Purpose |
|---|---|---|
| `CDF_DATABASE_URL` | sensitive | Supabase session-pooler URL for `cdf_app`, listing both eu-central-1 pooler hosts; the first that accepts wins |
| `CDF_SUPABASE_URL` | plain | `https://<project-ref>.supabase.co` |
| `CDF_SUPABASE_PUBLISHABLE_KEY` | plain | Browser-safe key; the API uses it only to ask Supabase Auth to confirm a token |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | plain | Frontend sign-in, read at build time |
| `CDF_HOSTED_REVIEWERS` | sensitive | JSON list of `{"email", "principal_id": "SYN-HOSTED-…", "roles": [...]}` |
| `ANTHROPIC_API_KEY` | sensitive, optional | Live provider inference. Absent means jobs run with mock or deterministic executors, and are labelled so |
| `CDF_DOCUMENT_UPLOADS` | plain, optional | `PUBLIC` turns on document uploads (below). Any other value, or none, keeps them off |
| `VITE_SITE_IDENTITY` | plain, optional, build time | `CDF` shows the institution's logo in the masthead and removes the demo labels. Any other build keeps the neutral demo mark |

Never commit any of these values.

## Owner steps (only the owner can do these)

1. **Supabase Auth URL settings:** set the Site URL to the Vercel production URL, and add it to Redirect URLs.
   Otherwise the confirmation link in the sign-up email lands on `localhost`. The account is still confirmed; you
   can then sign in on the app.
2. **Sign-ups:** after the reviewers have signed up, turn off "Allow new users to sign up". Strangers are refused by
   the API anyway (`HOSTED_REVIEWER_NOT_LISTED`).
3. **Second reviewer:** add a second e-mail to `CDF_HOSTED_REVIEWERS`. A material withdrawal needs a second, different
   person. With Supabase's default e-mail sender, only project team members receive mail, so invite them to the
   project or configure SMTP.
4. **Live inference (optional):** add `ANTHROPIC_API_KEY` to the Vercel project. Synthetic cases only, until the
   institution authorises real documents.
5. **Claude connector (optional):** the `/mcp` endpoint names Supabase Auth as its OAuth authorization server.
   Claude's custom connector completes sign-in only if the Supabase project's OAuth server is enabled. Clients
   that accept a bearer header (Claude Code, the MCP SDKs) can connect now with a reviewer's access token.
6. **Rotate the database password:** rotate `cdf_app`'s password whenever needed:
   ```sql
   alter role cdf_app with password '<new>';
   ```
   Then update `CDF_DATABASE_URL` in Vercel.

## Document uploads (`CDF_DOCUMENT_UPLOADS=PUBLIC`)

Setting this variable records the owner's decision that every file uploaded to this deployment is public
material. The site then labels itself "UPLOADS ARE TREATED AS PUBLIC" and shows a Documents section to signed-in
reviewers. The calibration cases keep their `SYN-` guards; uploaded files never become cases.

| Step | What happens |
|---|---|
| Upload | `.docx` or `.xlsx`, at most 4 MB. The engine's package inspection refuses macros, external links, oversized or unexpected parts, and any XML that declares a DTD |
| Storage | Table `uploaded_documents` in the same schema, with the SHA-256 of each file; every create, run and delete is logged in `uploaded_document_log` |
| Access | Only the reviewer who uploaded a file can list, download, run tools on or delete it |
| Tools | The deterministic engine only; no file is sent to a model provider |

Tools:

| Tool | Input | Output |
|---|---|---|
| Quality checks | Review workbook | The dashboard and UX gates. Checks that need an earlier round or a returned file stay FAIL or NOT_VERIFIED |
| Word report | Review workbook | Review report `.docx`, checked against the workbook |
| Rebuild Excel | Review workbook | Rebuilt workbook |
| Insert review comments | Word document + review workbook | The document with each observation anchored as a comment (round 1) or a reply (later rounds) |
| Compare returned copy | Delivered `.docx` + returned `.docx` | Tracked changes, silent edits, review comments removed or altered, comments the owner added |

Every generated file is a working copy named `INTERNAL_DRAFT__…`; nothing is issued from the site.

API (signed-in reviewer): `GET /api/documents`, `POST /api/documents?filename=…` (raw file bytes),
`GET /api/documents/{id}`, `GET /api/documents/{id}/content`, `DELETE /api/documents/{id}`,
`POST /api/documents/{id}/actions/{qa|word_report|excel_rebuild|comment|compare}?other={id}`.

## CI/CD

- **Vercel deploys:** Vercel's Git integration deploys every pushed branch as a preview, and `main` to production.
- **CI checks:** `.github/workflows/hosted-demo.yml` runs on pull requests:
  - the whole public suite against Postgres 17 with the inline runner;
  - a smoke start of both functions, with only `requirements.txt` installed;
  - the hosted web build.
- **Schema changes:** add a file to `supabase/migrations/` and apply it to the project (Supabase CLI or
  dashboard). The API's own tables are created idempotently at start.

## Limits

- **Exports:** Word and Excel exports run in the function. PDF needs LibreOffice, which Vercel functions don't have,
  so a PDF job fails with a recorded error.
- **Backups:** the copilot's backup and restore actions are refused (`BACKUP_MANAGED_BY_DATABASE_PROVIDER`). Use
  Supabase backups.
- **Job length:** a job runs within one request, up to 300 s (`maxDuration`).
