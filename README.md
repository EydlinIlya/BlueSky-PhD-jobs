# PhD Sky

[PhD Sky](https://phdsky.org/) finds public PhD, postdoctoral, research-assistant,
and academic-faculty opportunities shared on Bluesky. A language model filters
and labels posts; the original post and official application page remain the
sources of truth.

The service is free, non-commercial, and operated as an independent project.

## What it does

- Searches Bluesky through the AT Protocol using academic-job queries.
- Filters and enriches likely vacancies in one Ministral 14B call, with optional provider fallbacks.
- Extracts disciplines, country, position type, role title, employer,
  application URL, deadline, and location without inventing missing facts.
- Deduplicates reposts using exact normalized official application links first, then TF-IDF plus model verification.
- Publishes an accessible feed with search, filters, saved searches, follows,
  weekly-alert controls, and a lazy-loaded archive.
- Generates crawlable job pages, active subject/country hubs, and split XML
  sitemaps.
- Can quote-post selected listings to Bluesky and publish a bioinformatics
  digest to Telegram.

## Architecture

```text
Bluesky
   │
   ▼
Fetch → classify and enrich → deduplicate → publish to Supabase
                                               │
                         ┌─────────────────────┴─────────────────────┐
                         ▼                                           ▼
               static site generator                         digest/repost jobs
                         │
                         ▼
                    Vercel /docs
```

Supabase ingestion is checkpointed by stage. A failed run resumes from stored
staging rows, and publishing clears staging only after the complete upsert
succeeds.

## Quick start

Requires Python 3.11.9 or newer.

```bash
python -m venv .venv

# Windows
.venv/Scripts/activate

# macOS/Linux
source .venv/bin/activate

pip install -e .
```

Create `.env`:

```dotenv
# Required for collection; use a Bluesky app password
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password

# Primary classifier
MISTRAL_API_KEY=your-mistral-api-key
MISTRAL_MODEL=ministral-14b-latest

# Optional fallbacks, used in this order
GEMINI_API_KEY=your-gemini-key
NVIDIA_API_KEY=your-nvidia-key
GROQ_API_KEY=your-groq-key

# Required for the production database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-server-side-secret

# Optional maintenance/email alias
SUPABASE_SERVICE_KEY=your-server-side-secret

# Manual operator digest
RESEND_API_KEY=your-resend-key
EMAIL_FROM=PhD Sky <alerts@phdsky.org>
DIGEST_RECIPIENT=you@example.com

# Optional channels
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHANNEL_ID=@your_channel
```

Never expose `SUPABASE_KEY` or `SUPABASE_SERVICE_KEY` in frontend code.

## Running the pipeline

```bash
# Local CSV run
python bluesky_search.py

# Supabase production pipeline
python bluesky_search.py --storage supabase

# Recovery: ignore the saved timestamp and fetch the deepest recent window
python bluesky_search.py --storage supabase --full-sync --limit 100

# Run through a specific checkpoint
python bluesky_search.py --storage supabase --stage fetch
python bluesky_search.py --storage supabase --stage filter
python bluesky_search.py --storage supabase --stage dedup
python bluesky_search.py --storage supabase --stage publish

# Small diagnostic run without model filtering
python bluesky_search.py --no-llm --limit 10
```

Useful options:

| Option | Purpose | Default |
| --- | --- | --- |
| `-q, --query` | Add a Bluesky search query; repeatable | built-in query set |
| `-l, --limit` | Results per query | `50` |
| `--storage` | `csv` or `supabase` | `csv` |
| `--stage` | Stop after one persistent stage | `all` |
| `--full-sync` | Ignore the incremental timestamp | off |
| `--no-llm` | Disable configured model providers | off |
| `-o, --output` | CSV output path | `phd_positions.csv` |

## Model providers and benchmarks

Provider order is Mistral → Gemini → NVIDIA NIM → Groq; missing providers are
skipped. Failover is sticky for the process so an unavailable provider is not
retried for every row.

The production prompt and hand-reviewed fixtures are benchmarked with:

```bash
python scripts/benchmark_mistral_models.py
python scripts/benchmark_seo_enrichment.py --model ministral-14b-latest
```

Reports under `.benchmarks/` include classification quality, metadata accuracy,
latency, token use, cache hits, and estimated standard/batch cost. Ministral 14B
is the current default because it matched the larger model on the checked-in
classification fixture at substantially lower cost.

## Frontend

The site is plain HTML, CSS, and JavaScript under `docs/`; there is no frontend
build step.

```bash
python -m http.server --directory docs
```

Open `http://localhost:8000/?mock` for the offline fixture. Production loading
uses the embedded snapshot, then `positions.json`, then the public Supabase read
API as a fallback.

The desktop search expands when focused. Saved subscriptions include **Show
matches**, which restores that subscription's search and filters in the feed.
The Archive tab lazy-loads `archive.json`; archived records do not appear in
active listings or the jobs sitemap.

Accounts use Supabase Auth. Apply migrations under `migrations/` in numeric
order and configure the redirect URLs documented in the migration headers.

## Search indexing and Google Jobs

`scripts/generate_seo_pages.py` creates:

| URL | Purpose |
| --- | --- |
| `/p/<slug>` | One position; weak/archived pages are `noindex` |
| `/positions` | Canonical current-position listing |
| `/positions/<n>` | Crawlable pagination, `noindex, follow` after page one |
| `/area/<slug>` | Active discipline hub |
| `/country/<slug>` | Active country hub |
| `/sitemap.xml` | Index for `core.xml` and `jobs.xml` |

A position remains active until its explicit deadline, or for 90 days when no
deadline is known. Our current schema gate requires an active verified listing,
title, employer, external application URL, known country, and substantive
visible description. Passing that gate makes a page eligible for markup; it
does not guarantee that Google will crawl, index, or show it.

Deadlines override the 90-day window only when the source labels the same
month/day as a deadline, closing date, or apply-by date. Explicit years are
preserved; genuinely yearless deadlines are anchored to the posting year or,
when that month/day has passed, the next year. Dates found only in URLs,
publication metadata, event text, or job IDs are ignored. For legacy rows whose
linked-page evidence was not retained, a stored deadline later than the source
post remains trusted; unsupported same-day or past dates fall back to the
90-day window and are omitted from generated snapshots and structured data.

Google Jobs additionally expects:

- one real vacancy on the detail page;
- `title`, `datePosted`, `description`, `hiringOrganization`, and a valid
  `jobLocation` (or correctly declared fully remote location);
- a visible description that completely represents responsibilities,
  qualifications, skills, education, experience, and other relevant details;
- a working way to apply without requiring login merely to read the vacancy;
- page content that exactly agrees with the structured data;
- prompt removal or expiration when applications close.

Most rejected PhD Sky candidates lack a verified application URL, exact title,
employer, or country. Even syntactically valid pages may not qualify because a
short social post is not a complete job description. Search Console's valid
item count also lags deployment while Google discovers and recrawls the jobs
sitemap.

Run the resumable enrichment before regenerating:

```bash
python scripts/backfill_seo_metadata.py --limit 20 --dry-run
python scripts/backfill_seo_metadata.py
python scripts/generate_seo_pages.py
```

After a substantial template change, validate representative URLs with Google's
Rich Results Test and inspect them in Search Console.

## Automation and deployment lifecycle

GitHub Actions separates data freshness from deployment frequency:

- `scheduled-search.yml` ingests at 05:00, 11:00, 17:00, and 23:00 UTC.
- Only the 05:00 UTC run regenerates and commits `docs/`, producing one routine
  Vercel production deployment per day. Manual non-recovery runs also deploy.
- `telegram-digest.yml` runs independently three times daily.
- `bluesky-repost.yml` runs every six hours.
- `subscription-digests.yml` is manual-only and sends at most three matching
  positions to `DIGEST_RECIPIENT`; it sends nothing when there are no matches.

For a Vercel Hobby project, configure **Project Settings → Security → Deployment
Retention**. A practical policy for this repository is seven days for production,
three days for previews, and one day for cancelled/errored deployments. Delete
merged remote branches so their latest preview is no longer retention-protected.
Vercel retention is a project setting; it is not defined in `vercel.json`.

The site is served from `docs/` on `main`. `vercel.json` supplies clean URLs,
security headers, and cache policy. The legacy GitHub Pages branch only redirects
to `https://phdsky.org/`.

## Maintenance commands

```bash
# Review prolific aggregator accounts before editing docs/aggregators.json
python scripts/find_aggregator_candidates.py --min-posts 5

# Preview Bluesky reposts without publishing
python scripts/repost_to_bluesky.py --dry-run --limit 3

# Run all tests
python -m pytest tests/ -v
```

## Required GitHub Actions secrets

- `BLUESKY_HANDLE`, `BLUESKY_PASSWORD`
- `MISTRAL_API_KEY`
- `SUPABASE_URL`, `SUPABASE_KEY`
- Optional fallbacks: `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY`
- Optional Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`
- Manual email: `SUPABASE_SERVICE_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`,
  `DIGEST_RECIPIENT`

## Tests

```bash
python -m pytest tests/ -v
```

The suite covers provider requests and fallback, persistent pipeline behavior,
deduplication, Bluesky ingestion, storage, lifecycle/eligibility rules, HTML and
JSON-LD escaping, sitemap invariants, email delivery, unsubscribe behavior, and
offline Playwright interaction/accessibility flows.

## License

Apache License 2.0
