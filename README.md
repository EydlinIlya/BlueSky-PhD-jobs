# PhD Position Finder

Aggregate PhD and academic position announcements from multiple sources into a unified database.

## Data Sources

- **Bluesky** - Social network posts via AT Protocol SDK with LLM filtering
- **ScholarshipDB** - Academic job listings from scholarshipdb.net (pre-classified)

## Features

- **Multi-source aggregation** - Combine positions from multiple sources
- **LLM filtering** - Mistral (Ministral 14B) with optional Gemini → NVIDIA NIM → Groq failover
- **Multi-discipline classification** - Categorize positions into 1-3 academic disciplines
- **Country detection** - Identifies position country from university, domain, or city names
- **Position type extraction** - PhD Student, Postdoc, Master Student, Research Assistant
- **Evidence-backed job metadata** - Exact title, employer, application URL,
  deadline, and location are extracted in the existing metadata call; uncertain
  values remain empty
- **Active-job search index** - Explicit deadlines override a 90-day fallback;
  only complete active jobs are indexed with `JobPosting`
- **Deduplication** - TF-IDF + LLM-based detection of reposted positions
- **Incremental sync** - Only fetch new positions since last run
- **4-stage persistent pipeline** - Supabase runs use checkpointed stages (fetch → filter → dedup → publish); a crash mid-filter resumes from the last unprocessed post on the next run
- **Telegram channel** - Auto-posts Biology + CS positions (bioinformatics)
- **Bluesky repost bot** - Quote-posts non-aggregator positions from a dedicated account, tagged with level, country, and subjects
- **GitHub Actions** - Automated daily updates

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate  # Windows
source .venv/bin/activate  # Unix
pip install -e .
```

## Configuration

Create a `.env` file:

```bash
# Required (for Bluesky source; also the account used by the repost bot)
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password

# Recommended - primary LLM filtering for Bluesky
MISTRAL_API_KEY=your-mistral-api-key
# Optional model override (default: ministral-14b-latest)
MISTRAL_MODEL=ministral-14b-latest

# Optional fallbacks
GEMINI_API_KEY=your-gemini-api-key
# Optional model override (default: gemma-4-31b-it)
GEMINI_MODEL=gemma-4-31b-it

# Optional intermediate fallback through NVIDIA NIM
NVIDIA_API_KEY=your-nvidia-api-key
# Optional model override (default: google/gemma-4-31b-it)
NVIDIA_MODEL=google/gemma-4-31b-it

# Optional final fallback (also works as the sole LLM provider)
GROQ_API_KEY=your-groq-api-key
# Optional model override (default: openai/gpt-oss-120b)
GROQ_MODEL=openai/gpt-oss-120b

# Optional - Supabase storage
SUPABASE_URL=https://xxx.supabase.co
# Server-side secret key used by ingestion and maintenance scripts; never expose it
SUPABASE_KEY=your-secret-key
# Optional dedicated alias for maintenance/email jobs
SUPABASE_SERVICE_KEY=your-secret-key

# Optional - Telegram channel
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHANNEL_ID=@your_channel
```

Get a Bluesky app password at Settings → App Passwords.
Create a key in [Mistral Studio](https://console.mistral.ai/api-keys), then put
it in the repository's local `.env` file as `MISTRAL_API_KEY`. For scheduled
ingest, also add the same name and value under GitHub repository
**Settings → Secrets and variables → Actions → New repository secret**. Never put
the key in `docs/` or browser-side JavaScript. The default is
`ministral-14b-latest`, selected against the checked-in 41-case benchmark. The
provider uses a stable prompt cache key so repeated filter and metadata
instructions can use Mistral's discounted cached-input pricing.

The provider order is Mistral → Gemini → NVIDIA NIM → Groq, skipping providers
that are not configured. Any provider can operate alone. Set `NVIDIA_API_KEY`
to use NVIDIA's hosted NIM endpoint with `google/gemma-4-31b-it`; Groq defaults
to `openai/gpt-oss-120b`.

Create a final-fallback key in the [GroqCloud console](https://console.groq.com/keys)
and set `GROQ_API_KEY`. A Gemini rate-limit response triggers immediate failover;
other terminal failures switch after their normal retries. The selected fallback
remains active for the rest of the running filter or dedup process. For scheduled
runs, add any fallback keys you want as GitHub Actions secrets.

### Model benchmark

The reproducible benchmark uses 41 hand-reviewed Bluesky posts and the real
production prompts/code path:

```bash
python scripts/benchmark_mistral_models.py
```

Reports are written under `.benchmarks/` and include filter precision/recall/F1,
metadata accuracy, latency, token usage, prompt-cache hits, and estimated
standard and Batch API costs. The fixture is
`tests/fixtures/llm_benchmark_cases.json`.

Before an SEO backfill, benchmark the five evidence-backed job fields on the
separate hand-reviewed fixture:

```bash
python scripts/benchmark_seo_enrichment.py --model ministral-14b-latest
```

The current Ministral 14B result is 30/30 accepted fields. The six-case run used
8,235 prompt tokens (7,680 cached) and 595 completion tokens.

## Usage

```bash
python bluesky_search.py [options]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--sources` | Comma-separated sources: `bluesky`, `scholarshipdb` | `bluesky` |
| `--storage` | Storage backend: `csv` or `supabase` | `csv` |
| `-q, --query` | Bluesky search query (repeatable) | 11 academic queries |
| `-l, --limit` | Max results per Bluesky query | 50 |
| `--scholarshipdb-pages` | Max pages per field for ScholarshipDB | 2 |
| `--no-llm` | Disable LLM filtering for Bluesky | LLM enabled if key set |
| `--full-sync` | Ignore previous sync state | Incremental |
| `-o, --output` | Output CSV filename | `phd_positions.csv` |

### Examples

```bash
# Bluesky only (default)
python bluesky_search.py

# Both sources
python bluesky_search.py --sources bluesky,scholarshipdb

# ScholarshipDB only, more pages
python bluesky_search.py --sources scholarshipdb --scholarshipdb-pages 5

# Both sources to Supabase
python bluesky_search.py --sources bluesky,scholarshipdb --storage supabase

# Full sync (reset incremental state)
python bluesky_search.py --full-sync

# Quick test without LLM
python bluesky_search.py --no-llm -l 10
```

## Output

CSV output also carries nullable `job_title`, `hiring_organization`,
`application_url`, `application_deadline`, `location_text`, and
`seo_enriched_at` fields when they are available.

- **Bluesky posts**: `message` includes author bio as `[Bio: ...]` prefix
- **ScholarshipDB**: `is_verified_job` is always `True` (pre-verified from job site)

Disciplines: Computer Science, Biology, Ecology, Chemistry & Materials Science, Physics, Mathematics, Medicine, Psychology, Economics, Linguistics, History, Sociology & Political Science, Arts & Humanities, Education, Other, General call

Remote-sensing-of-forests/crop-fields posts are classified as **Ecology** primary (Biology / Computer Science may appear as secondary tags).

Position types: PhD Student, Postdoc, Master Student, Research Assistant

## Supabase Setup

1. Create a project at https://supabase.com
2. Go to SQL Editor and run:

```sql
CREATE TABLE phd_positions (
    id SERIAL PRIMARY KEY,
    uri TEXT UNIQUE NOT NULL,
    message TEXT NOT NULL,
    url TEXT NOT NULL,
    user_handle TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    disciplines TEXT[],
    is_verified_job BOOLEAN DEFAULT TRUE,
    country TEXT,
    position_type TEXT[],
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    duplicate_of TEXT,
    job_title TEXT,
    hiring_organization TEXT,
    application_url TEXT,
    application_deadline DATE,
    location_text TEXT,
    seo_enriched_at TIMESTAMPTZ
);

CREATE TABLE pipeline_runs (
    id SERIAL PRIMARY KEY,
    run_date DATE UNIQUE NOT NULL,
    fetch_completed_at TIMESTAMPTZ,
    filter_completed_at TIMESTAMPTZ,
    dedup_completed_at TIMESTAMPTZ,
    raw_count INT DEFAULT 0,
    verified_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE phd_positions_staging (
    id SERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    uri TEXT NOT NULL,
    message TEXT,
    raw_text TEXT,
    metadata_text TEXT,
    url TEXT,
    user_handle TEXT,
    created_at TIMESTAMPTZ,
    source TEXT,
    quoted_uri TEXT,
    reply_parent_uri TEXT,
    is_verified_job BOOLEAN,
    disciplines TEXT[],
    country TEXT,
    position_type TEXT[],
    job_title TEXT,
    hiring_organization TEXT,
    application_url TEXT,
    application_deadline DATE,
    location_text TEXT,
    seo_enriched_at TIMESTAMPTZ,
    duplicate_of TEXT,
    filter_completed BOOLEAN DEFAULT FALSE,
    staged_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_date, uri)
);

-- Telegram digest tracking: NULL means un-posted; the digest job marks rows
-- after posting. Partial index keeps the digest query fast.
ALTER TABLE phd_positions ADD COLUMN IF NOT EXISTS posted_to_telegram_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS phd_positions_unposted_idx
  ON phd_positions (created_at DESC)
  WHERE posted_to_telegram_at IS NULL;

-- Backfill once, the first time you run this migration: mark all existing
-- rows as already-posted so the digest doesn't dump the historical Bio+CS
-- backlog into the channel. Safe to skip if you want to re-post the backlog.
UPDATE phd_positions SET posted_to_telegram_at = NOW() WHERE posted_to_telegram_at IS NULL;

-- Bluesky repost bot tracking: NULL means un-reposted. Partial index keeps the
-- bot's query fast. (See migration 006.)
ALTER TABLE phd_positions ADD COLUMN IF NOT EXISTS reposted_to_bluesky_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS phd_positions_unreposted_idx
  ON phd_positions (created_at)
  WHERE reposted_to_bluesky_at IS NULL;

-- Start fresh once: pre-mark the existing backlog so the bot only reposts
-- positions ingested after launch (avoids flooding the feed).
UPDATE phd_positions SET reposted_to_bluesky_at = NOW() WHERE reposted_to_bluesky_at IS NULL;
```

3. Go to Settings → API and copy:
   - Project URL → `SUPABASE_URL`
   - secret/service-role key → `SUPABASE_KEY` (server-side only)

4. Add to your `.env` file

Existing projects should apply all SQL files under `migrations/` through
`008_seo_job_metadata.sql` before deploying the updated ingest or generator.

## GitHub Actions

Two workflows run on cron:

- **`scheduled-search.yml`** — ingests new Bluesky posts and regenerates the
  static frontend snapshot. Runs **4×/day** (05:00, 11:00, 17:00, 23:00 UTC)
  for fresh website data.
- **`telegram-digest.yml`** — pulls Bio + CS positions where
  `posted_to_telegram_at IS NULL` and posts them to the channel, then marks
  them as posted. Runs **3×/day** (08:00, 14:00, 20:00 UTC). Decoupled from
  ingest so the website can refresh more often without spamming the channel.
- **`bluesky-repost.yml`** — quote-posts non-aggregator positions where
  `reposted_to_bluesky_at IS NULL` from a dedicated account, tagged with level,
  country, and subjects. Runs **every 6h**. Uses the same `BLUESKY_HANDLE`/
  `BLUESKY_PASSWORD` account as search (which excludes its own reposts).

To enable:

1. Push to GitHub
2. Go to Settings → Secrets and variables → Actions
3. Add secrets: `BLUESKY_HANDLE`, `BLUESKY_PASSWORD`, `MISTRAL_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`
4. (Optional) Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` for Telegram posting
5. The workflows run automatically or can be triggered manually from the Actions tab

## Telegram Channel

Positions tagged with both **Biology** and **Computer Science** (bioinformatics, computational biology) are posted to a Telegram channel by the `telegram-digest.yml` workflow, which runs separately from the ingest pipeline.

### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) → save the token
2. Create a channel (e.g., `@bioinfo_phd_jobs`) and add the bot as admin
3. Add to `.env` or GitHub secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`

If the secrets are not set, the Telegram step is silently skipped.

## Bluesky Repost Bot

A dedicated Bluesky account quote-posts **non-aggregator** positions (verified,
canonical, `user_handle` not in `docs/aggregators.json`) with clickable hashtags
for level, country, and subjects. Run by the `bluesky-repost.yml` workflow, every
6h, decoupled from ingest.

The bot account is the **same** account used for search
(`BLUESKY_HANDLE`/`BLUESKY_PASSWORD`); the search source skips posts authored by
that handle so we never re-ingest our own reposts.

### Setup

1. Create a new Bluesky account + an **app password**; set `BLUESKY_HANDLE` /
   `BLUESKY_PASSWORD` (locally and as GitHub secrets) to it.
2. Run migration 006 (adds `reposted_to_bluesky_at`) **including** the one-time
   start-fresh `UPDATE` so the historical backlog isn't reposted.
3. Test safely before enabling the cron:
   ```bash
   python scripts/repost_to_bluesky.py --dry-run --limit 3   # prints, posts nothing
   python scripts/repost_to_bluesky.py --limit 1             # posts one
   ```

## Frontend

The browse-positions site is at **<https://phdsky.org/>** (Vercel, served from
`/docs` on `main`). The legacy GitHub Pages URL
(`eydlinilya.github.io/BlueSky-PhD-jobs/`) now serves a 0-second redirect to
`phdsky.org` from the `gh-pages` branch.

The UI is a light academic **feed**: a chronological river of active positions
with day separators and infinite scroll, a left rail of filter chips
(Level / Country / Area + "Hide aggregator reposts"), a command/search bar, and a
post-detail flyout. Saved subscriptions can be edited in place without recreating
them. Plain HTML + CSS + vanilla JS, no build step. Data loads from
an embedded snapshot → `positions.json` → live Supabase. Open it locally with
`python -m http.server --directory docs` (add `?mock` to use bundled sample data).
The About and Terms pages identify the service's operator, non-commercial status,
listing limitations, acceptable use, and governing law.

### Setup

1. **Add RLS policy** to Supabase:
   ```sql
   ALTER TABLE phd_positions ENABLE ROW LEVEL SECURITY;
   CREATE POLICY "Allow public read" ON phd_positions FOR SELECT USING (true);
   ```

2. **Update `docs/app.js`** with your Supabase anon key.

## Maintenance

### Aggregator list (hide-reposts filter)

Some Bluesky accounts act as re-posting channels. The frontend ships with a
**"Hide aggregator reposts"** toggle that filters out positions from handles
listed in `docs/aggregators.json`. The list is hand-maintained:

```bash
python scripts/find_aggregator_candidates.py --min-posts 5
```

The script prints every handle that has posted ≥ 5 canonical positions along
with the bio from their most recent post. No writes, no LLM calls — review the
output and add real aggregator handles to `docs/aggregators.json`:

```json
{ "handles": ["handle1.bsky.social", "handle2.bsky.social"], "note": "..." }
```

The filter is purely a frontend concern; it does **not** affect ingestion or
deduplication (dedup strips the `[Bio: ...]` prefix before TF-IDF comparison).

## Hosting

- **Primary:** `phdsky.org` — Vercel, deploys from `/docs` on `main`.
  `vercel.json` configures cleanUrls + cache headers; no build step.
- **Legacy:** `eydlinilya.github.io/BlueSky-PhD-jobs/` — GitHub Pages,
  sourced from the `gh-pages` branch. That branch only contains a redirect
  page so old inbound links forward to `phdsky.org`.
- `scripts/generate_seo_pages.py` defaults `BASE_URL` to `https://phdsky.org/`.
  Override with the `SITE_BASE_URL` env var if you ever need to regenerate
  for a different domain.

### Static pages for search engines

The interactive board is a JS app, so the crawlable surface is generated
alongside it by `scripts/generate_seo_pages.py`:

| URL | What it is |
| --- | --- |
| `/p/<slug>` | Detail page for an active or archived position. Archived/incomplete pages are `noindex`; only complete active pages carry `JobPosting`. |
| `/positions`, `/positions/<n>` | Active positions only. Page one is indexable; later pagination is `noindex, follow`. |
| `/area/<slug>` | Active positions for one discipline, e.g. `/area/biology`. |
| `/country/<slug>` | Active positions for one country, e.g. `/country/germany`. |
| `/sitemap.xml` | Sitemap index for `/sitemaps/core.xml` and `/sitemaps/jobs.xml`. |

Listing and hub pages use `CollectionPage` + `ItemList` structured data and link
to the `/p/` pages. Hubs are skipped for buckets below `FACET_MIN_POSITIONS`, and
for catch-all discipline labels, so they don't become thin pages.

An explicit application deadline controls activity. Without one, a position is
active for 90 days from its source-post date. A page is SEO-eligible only when
it is active and has a verified title, employer, external application URL,
country, and a substantive description. Run the one-time enrichment after the
schema update:

```bash
python scripts/backfill_seo_metadata.py --limit 20 --dry-run
python scripts/backfill_seo_metadata.py
python scripts/generate_seo_pages.py
```

The generator refuses to overwrite the static site while any active canonical
row still has a null `seo_enriched_at`, preventing a partial or empty jobs
sitemap from being deployed.

The manual **SEO Metadata Backfill** workflow accepts the existing privileged
`SUPABASE_KEY` Actions secret. If present, a separately named
`SUPABASE_SERVICE_KEY` takes precedence. Both names must be stored as Actions
secrets, never plaintext variables. The dispatch defaults to a 20-row dry run;
rerun with dry run disabled and `limit=0` to process all remaining active rows.
The operation is resumable.

After deploying regenerated output, remove and resubmit `sitemap.xml` in Google
Search Console, then inspect the homepage, `/positions`, two hubs, and several
current eligible job URLs. The generator deliberately does not use the Google
Indexing API yet.

## Dependencies

- [atproto](https://atproto.blue/) - AT Protocol SDK for Bluesky
- [httpx](https://www.python-httpx.org/) - HTTP client for ScholarshipDB
- [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) - HTML parsing
- [requests](https://requests.readthedocs.io/) - Hosted LLM APIs and web requests
- [scikit-learn](https://scikit-learn.org/) - TF-IDF similarity for deduplication
- [supabase](https://supabase.com/docs/reference/python) - Supabase client

## License

Apache License 2.0
