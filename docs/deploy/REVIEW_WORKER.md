# Review worker: AI review of uploaded documents

The website (Vercel) stores uploads and shows progress and results. The review itself runs in a separate small
service, the **review worker**. It can run for as long as a review needs (a long document can take 10–30 minutes),
and it carries LibreOffice for the PDF outputs. Both share the same Supabase database.

## What a review does

On the Documents page, choose **مراجعة المستند** (review document) for a Word, PDF or Excel file. The worker then:

1. **Reads** the document. A PDF is read with right-to-left repair for Arabic. A scanned PDF with no text layer is
   refused, because there is no OCR.
2. **Drafts.** The GCO drafting agent reads the document 60 paragraphs at a time and proposes observations: a
   finding, then «التوصية:».
   - A proposal is adopted only if its quote is found in the document and it is not marked outside GCO's
     jurisdiction.
   - The others are listed in the review details.
3. **Challenges.** The black team, red advocate, independent adjudicator, editorial agent and final reviewer work
   through every adopted observation (Article 06).
4. **Records a case** `UPL-…` owned by you. It opens the existing calibration screens and the executive dashboard.
5. **Writes outputs.** They appear under the original document, each named `INTERNAL_DRAFT__…`:
   - the document with the review comments (Word);
   - the same document as PDF, with the comments in the margin;
   - for a PDF original: the original PDF with highlights and sticky notes;
   - for an Excel original: the original spreadsheet with cell comments;
   - the review tracker (Excel);
   - the executive dashboard (Word, Excel, PDF).

Every output is a working copy. Adopted observations are drafts for your calibration decisions. Nothing is
issued.

The hosted deployment carries the public reference fixture, not CDF's approved policy sources. The adjudicator
therefore treats legal or authority claims as unverified, and the release gate records
`SYNTHETIC_REFERENCE_NOT_ISSUABLE`.

## Two ways to run reviews

- **On the website** (`CDF_REVIEW_RUNNER=website` on Vercel). With no worker online, the page that queues a review
  asks the site to run it within the same request.
  - It suits short and medium documents, because the whole review must finish within the host's limit:
    `CDF_REVIEW_WEBSITE_SECONDS`, default 270 s, under Vercel's 300 s.
  - A longer document stops with a clear message, as does a run the host cuts off.
  - Vercel has no LibreOffice, so the "document with comments as PDF" and the dashboard PDF are not produced. The
    original PDF with highlights and notes still is.
  - On Vercel, set `ANTHROPIC_API_KEY` (or your own name for it plus `CDF_ANTHROPIC_KEY_VAR`), `CDF_ENABLE_PROVIDER_API=1`
    and `CDF_AI_DATA_AUTHORIZATION`.
- **On the review worker** (below). It has no time limit and produces every output. Whenever a worker is online,
  the website leaves queued reviews to it.

## Run the worker (Railway, recommended)

1. Create a project at railway.com: **New Project → Deploy from GitHub repo → `mh1m1m/CDF_GC_Review`**.
   - Choose branch `feature/hosted-vercel-supabase` until it is merged.
2. Under **Variables**, add everything in the table below, including `RAILWAY_DOCKERFILE_PATH=Dockerfile.worker`.
3. Deploy. The log shows `review worker … started (executor=anthropic)`.
   - On the website, a queued review starts within seconds.
   - If no worker is running, the website says so and the review waits.

**Other hosts** (Google Cloud Run, Fly.io, Render, a server with Docker) work the same way:

```
docker build -f Dockerfile.worker -t cdf-review-worker .
```

Run it with the same variables. On a host that requires an open port, set `PORT`; the worker then answers health
checks there. One worker handles one review at a time; run two for two parallel reviews.

## Variables (set on the worker host, never in the repository)

| Name | Value |
|---|---|
| `CDF_DATABASE_URL` | Same as Vercel: `postgresql://cdf_app.jeseeznffxlxmcljpmiu:<PASSWORD>@aws-0-eu-central-1.pooler.supabase.com:5432,aws-1-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require&connect_timeout=8` |
| `CDF_DOCUMENT_UPLOADS` | `PUBLIC`, the same owner switch as the website. The worker refuses to start without it |
| `ANTHROPIC_API_KEY` | Your Anthropic API key (console.anthropic.com) |
| `CDF_ANTHROPIC_KEY_VAR` | Optional. If you stored the key under another name, put that name here. The value is used only if it looks like an Anthropic key (`sk-ant-…`) |
| `CDF_ENABLE_PROVIDER_API` | `1` |
| `CDF_AI_DATA_AUTHORIZATION` | `INSTITUTIONAL_AUTHORIZED:<reference>`, your recorded permission for uploaded documents to go to Claude (see below) |
| `CDF_SITE_IDENTITY` | `CDF`: the exported tracker and dashboard carry the CDF wordmark |
| `CDF_AI_MODEL` | Optional. The engine's default model is used when unset |
| `CDF_REVIEW_EXECUTOR` | Optional: `anthropic` (default) or `mistral`, the AI service that reviews documents |
| `MISTRAL_API_KEY` | With `CDF_REVIEW_EXECUTOR=mistral`: your Mistral API key (console.mistral.ai). Stored under another name? Put that name in `CDF_MISTRAL_KEY_VAR` |
| `CDF_MISTRAL_MODEL` | Optional, default `mistral-large-latest` |
| `CDF_AI_TIMEOUT_SECONDS` | Optional, default `180` |
| `CDF_AI_EFFORT` | Optional: `low`, `medium`, `high`, `xhigh` or `max`. Unset uses the model's default |
| `CDF_AI_MIN_MAX_TOKENS` | Optional, default `16000`. Current models think before answering, and thinking counts against this budget |
| `RAILWAY_DOCKERFILE_PATH` | `Dockerfile.worker` (Railway only) |

**Database password.** Vercel stores `CDF_DATABASE_URL` as a sensitive value that cannot be read back. To give
the worker the same URL, set a new password for the app's database role in the Supabase SQL editor:

```sql
alter role cdf_app with password '<new strong password>';
```

Then put the URL above, with that password, in both Vercel (`CDF_DATABASE_URL`, then redeploy) and the worker.
This also completes the pending password rotation.

**Mistral.** With `CDF_REVIEW_EXECUTOR=mistral` every agent runs on Mistral's chat completions with the role
schema as a strict JSON response format. On Mistral's free plan, requests may be used to train Mistral's models
unless the training toggle is turned off in the Mistral console (Admin → Privacy); the free plan also has low
rate limits, so the adapter waits briefly when told to slow down.

**Data authorisation.** The engine refuses to send any non-sample document to a model provider unless
`CDF_AI_DATA_AUTHORIZATION` names an authorisation. Uploaded content keeps its true label (`INSTITUTIONAL_CONTENT`)
and is never relabelled as sample data. Use a reference that identifies the decision, for example
`INSTITUTIONAL_AUTHORIZED:owner-decision-2026-10-25-uploads-public`. Removing the variable stops all AI reviews:
they then fail with a clear message on the website.

## Checks

- **CI:** `review-worker-image` builds this image and runs one full review inside it with the labelled MOCK
  executor, checking that the Word, PDF and Excel outputs are produced.
- **Unit tests:** `tests/test_document_review.py` and `tests/test_document_ingest.py`.
- **Live check:** once the worker is running with your key, upload a short document and review it. The dashboard's
  execution sources must show `PROVIDER_API` calls, never `MOCK_SCRIPT`.
