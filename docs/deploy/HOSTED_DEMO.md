# Hosted synthetic demo: Vercel + Supabase

Status: **HOSTED_SYNTHETIC_DEMO**. It runs on fictional `SYN-` cases only. It has no institutional activation and no
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
