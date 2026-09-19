# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Important: Documentation Requirements

**Both README.md and AGENTS.md must be kept up to date and checked before every commit.**

When making changes:
1. Update README.md if user-facing features, options, or setup steps change
2. Update AGENTS.md if architecture, modules, or development practices change
3. Verify both files are current before committing

**README.md style guidelines:**
- Keep it compact — show only the final state, not migration history
- Users don't need to know about schema migrations or intermediate steps
- Focus on setup, usage, and current features

## Project Overview

PhD Sky aggregates public PhD and academic-position posts from **Bluesky** via
the AT Protocol and filters them with an LLM.

Features include:
- LLM-based filtering for Bluesky posts (Mistral/Ministral 14B → Gemini/Gemma → NVIDIA NIM → Groq failover)
- Single JSON classification and metadata extraction: verification, disciplines (1-3), country, position type, and evidence-backed SEO fields
- Incremental sync state for Bluesky collection
- Multiple storage backends (CSV, Supabase)
- Deduplication of reposted positions (normalized official application URL, then TF-IDF + LLM verification)
- GitHub Actions for automated daily updates
- GitHub Pages frontend for browsing positions
- Telegram channel for Biology + CS positions (bioinformatics)

## Development Setup

```bash
.venv/Scripts/activate  # Windows
source .venv/bin/activate  # Unix
pip install -e .
```

## Environment Variables

Required in `.env` (for Bluesky source). This is the bot account used for **both**
search and the Bluesky repost job (`scripts/repost_to_bluesky.py`):
```
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password
```

Optional:
```
MISTRAL_API_KEY=your-mistral-api-key  # Primary LLM for Bluesky filtering
MISTRAL_MODEL=ministral-14b-latest    # Optional Mistral model override
GEMINI_API_KEY=your-gemini-api-key    # For LLM filtering (Bluesky)
GEMINI_MODEL=gemma-4-31b-it           # Optional model override
NVIDIA_API_KEY=your-nvidia-api-key    # Optional NVIDIA NIM fallback
NVIDIA_MODEL=google/gemma-4-31b-it     # Optional NVIDIA model override
GROQ_API_KEY=your-groq-api-key        # Optional final fallback (or sole provider)
GROQ_MODEL=openai/gpt-oss-120b        # Optional Groq model override
SUPABASE_URL=https://xxx.supabase.co  # For Supabase storage
SUPABASE_KEY=your-secret-key          # Privileged backend key; never expose to frontend
TELEGRAM_BOT_TOKEN=your-bot-token     # For Telegram channel
TELEGRAM_CHANNEL_ID=@your_channel     # Telegram channel ID
SUPABASE_SERVICE_KEY=service-role-key # For subscription digest cron (bypasses RLS)
RESEND_API_KEY=your-resend-key        # For subscription email digests
EMAIL_FROM=PhD Sky <alerts@phdsky.org># Digest sender (verified Resend domain)
EMAIL_PROVIDER=resend                 # Email backend (default: resend)
DIGEST_RECIPIENT=you@example.com      # Sole recipient in manual operator mode
SUPABASE_ANON_KEY=your-anon-key       # Vercel unsubscribe function (public key)
```

## Running

```bash
# Default: Bluesky only, CSV storage
python bluesky_search.py

# Supabase storage
python bluesky_search.py --storage supabase

# Full sync (ignore previous state)
python bluesky_search.py --full-sync

# Disable LLM for Bluesky
python bluesky_search.py --no-llm
```

## Architecture

### Main Script (`bluesky_search.py`)
- `get_classifier()` - Creates LLM classifier if API key available
- `get_storage()` - Creates storage backend (CSV or Supabase)
- `main()` - Routes to 4-stage pipeline (Supabase) or simplified single-pass flow (CSV)

### Modules

**`src/sources/`** - Data source implementations
- `base.py` - `DataSource` ABC with `fetch_posts()` method, `Post` dataclass
  (includes raw/metadata text plus nullable title, employer, application URL,
  deadline, location, and enrichment timestamp fields)
- `bluesky.py` - Bluesky source; stores `raw_text`/`metadata_text` on Post; returns posts unclassified (`is_verified_job=None`)

**`src/sync_state.py`** - Bluesky sync-state management
- `SyncStateManager` class for incremental CSV-backend tracking

**`src/logger.py`** - Logging configuration

**`src/llm/`** - LLM integration (for Bluesky)
- `config.py` - Provider model settings, retry settings, prompts, discipline list (includes `Ecology`), and position types. The single `METADATA_PROMPT_TEMPLATE` classifies and extracts evidence-backed `job_title`, `hiring_organization`, `application_url`, `application_deadline`, and `location_text`; uncertain values must be null. It contains an explicit rule that remote-sensing-of-forests/crop-fields posts must be classified as Ecology primary (Biology / CS only as secondary tags).
- `base.py` - Abstract `LLMProvider` class + `LLMUnavailableError`
- `mistral.py` - `MistralProvider` calls Mistral Chat Completions. The default `ministral-14b-latest` was selected by the checked-in 41-case benchmark. Stable hash-based `prompt_cache_key` values keep filter/metadata instructions eligible for cached-input pricing without putting user data in cache keys.
- `gemini.py` - `GeminiProvider` calls the native Gemini Interactions REST API with model-compatible minimal/low reasoning, disabled server-side storage, timeout, transient-error retry, rate-limit backoff, and free-tier pacing. It raises `LLMUnavailableError` after retries are exhausted.
- `nvidia.py` - `NvidiaNIMProvider` calls NVIDIA's hosted OpenAI-compatible Chat Completions endpoint. The default `google/gemma-4-31b-it` matches the primary model for prompt/output consistency, uses deterministic sampling, a 512-token response cap, and fails quickly to Groq on API errors.
- `groq.py` - `GroqProvider` calls Groq's OpenAI-compatible Chat Completions REST API. The default `openai/gpt-oss-120b` uses low reasoning, excludes returned reasoning, caps completions at 512 tokens, and uses a 15-second cooldown for the 8k free-plan TPM limit.
- `fallback.py` - `FallbackProvider` composes the configured Mistral → Gemini → NVIDIA NIM → Groq chain. Failover is sticky for the process lifetime so a depleted provider is not retried for every row.
- `classifier.py` - `JobClassifier`; one structured provider response decides verification and metadata, with the source post date supplied for supported deadline anchoring.

`bluesky_search.py:get_classifier()` builds the configured Mistral → Gemini → NVIDIA NIM → Groq chain, skipping missing providers; any provider can operate alone. With none configured it returns `None` (no LLM). `MISTRAL_MODEL`, `GEMINI_MODEL`, `NVIDIA_MODEL`, and `GROQ_MODEL` override their respective defaults.

**Model benchmark:** `scripts/benchmark_mistral_models.py` runs the production
classifier against `tests/fixtures/llm_benchmark_cases.json` (41 hand-reviewed
posts; current policy labels 29 jobs / 12 non-jobs). Reports under `.benchmarks/`
include classification/metadata quality, latency, token usage, cache hits, and
estimated standard/batch cost. The 2026-09-16 run selected Ministral 14B: it tied
Mistral Medium 3.5 on filter quality while costing much less. Mistral's Batch API
offers a 50% discount, but the production pipeline currently uses synchronous
per-row calls so its checkpoint/resume semantics remain simple.

**`src/storage/`** - Storage backends
- `base.py` - Abstract `StorageBackend` class
- `csv_storage.py` - Local CSV file storage
- `supabase.py` - Supabase PostgreSQL storage; also contains pipeline support methods (`get_or_create_run`, `update_run`, `insert_staging`, `get_staging_*`, `update_staging_*`, `delete_staging`)

**`src/seo.py`** - Shared active/archive/eligibility policy. A valid explicit
deadline overrides the 90-day posting-age fallback. SEO eligibility additionally
requires a verified title, employer, external application URL, country, and a
substantive description. Invalid dates/URLs fail conservatively. This local
gate is necessary but not sufficient for Google Jobs: Google expects the visible
page to contain a complete vacancy description, so a short social post may pass
the schema gate while still being unsuitable for the job-search experience.
`effective_deadline()` accepts a stored deadline only when the source labels the
same month/day as a deadline, closing date, or apply-by date. Explicit years are
preserved; genuinely yearless deadlines are anchored to the posting year or,
when that month/day has passed, the next year. Dates found only in URLs,
publication text, event text, or job IDs are ignored. Existing rows may have
deadline evidence from a linked-page preview that was not retained in the
canonical message, so `effective_deadline()` continues to trust a stored date
strictly later than the post date; unsupported same-day or past values fall
back to the 90-day rule. The classifier uses stricter evidence before a new
deadline reaches storage and still requires an explicit year.

**SEO enrichment tools:**
- `scripts/benchmark_seo_enrichment.py` evaluates Ministral 14B against the
  hand-reviewed `tests/fixtures/seo_enrichment_cases.json` fixture. The
  2026-09-16 run scored 30/30 accepted fields (8,235 prompt tokens, 7,680 cached,
  595 completion tokens).
- `scripts/backfill_seo_metadata.py` uses one metadata call per active,
  canonical, unenriched row and persists each successful row immediately. It
  requires `MISTRAL_API_KEY`, `SUPABASE_URL`, and either
  `SUPABASE_SERVICE_KEY` or the existing privileged `SUPABASE_KEY`.
- `.github/workflows/seo-metadata-backfill.yml` exposes that script through a
  guarded manual dispatch. It defaults to a 20-row dry run; use `limit=0` with
  dry run disabled for the complete resumable backfill. It prefers the
  `SUPABASE_SERVICE_KEY` Actions secret and otherwise uses the existing
  `SUPABASE_KEY` Actions secret; it never reads plaintext Actions variables.
  Apply migration 008 first.

**`src/pipeline/`** - 4-stage persistent pipeline (Supabase only)
- `runner.py` - Orchestrates stages; skips already-completed ones using `pipeline_runs` checkpoints
- `checkpoint.py` - Documents `pipeline_runs` table schema
- `stages/fetch.py` - Stage 1: fetch raw posts into `phd_positions_staging` (scoped to today's `run_date`)
- `stages/filter.py` - Stage 2: LLM classification per row; tracks per-row completion via `filter_completed`
- `stages/dedup.py` - Stage 3: TF-IDF + LLM dedup against existing canonical posts
- `stages/publish.py` - Stage 4: upsert staging → `phd_positions`; delete staging. Telegram posting is handled out-of-band by `scripts/post_to_telegram.py`

**Drain-all semantics:** only **Fetch** is scoped to today's `run_date` (it decides "what's new to pull"). **Filter, Dedup, and Publish drain the whole pending staging queue across ALL run_dates** (`get_staging_*`/`delete_staging` accept `run_date=None`). So if a day crashes before Publish, the next successful run sweeps up its leftover staging rows, classifies/dedups/publishes them, and Publish then clears the **entire** staging table plus **all** `pipeline_runs` rows. This guarantees orphaned staging can never accumulate. Per-row write-backs (`update_staging_filter`/`_dedup`) are keyed by each row's own `run_date`.

Before a drain-all upsert, Publish collapses repeated `uri` values across run
dates to the newest staging row. Supabase write errors propagate, and a short
save count raises, so staging and checkpoints are cleared only after the full
unique batch succeeds. `tests/test_publish_stage.py` protects these invariants.

**`scripts/find_aggregator_candidates.py`** - One-shot helper that lists Bluesky handles with ≥ `--min-posts` (default 5) canonical posts plus the bio from each handle's most recent post. Pure read; does not touch the pipeline or dedup. A human reviews the output and hand-edits `docs/aggregators.json` to add/remove aggregator handles. The frontend's **"Hide aggregator reposts"** toggle reads that JSON and filters the grid + card views accordingly. Dedup is unaffected because `preprocess_text()` already strips `[Bio: ...]` prefixes before TF-IDF comparison.

**`scripts/post_to_telegram.py`** - Telegram channel posting (standalone digest)
- Runs as its own cron job (`.github/workflows/telegram-digest.yml`), 3×/day
- Queries `phd_positions` for rows where `posted_to_telegram_at IS NULL` AND
  disciplines contain both Biology and Computer Science (bioinformatics)
- Formats with hashtags (position type, country); batches under 4096-char TG limit
- After successful POST, sets `posted_to_telegram_at` so rows aren't re-posted
- On Telegram failure, leaves rows un-marked → next digest retries (idempotent)
- Decoupled from the ingest pipeline so the website can refresh more often
  than the channel cadence. The legacy `post_batch_to_telegram(positions)`
  function is still exported for backward compatibility but is no longer
  called from `stages/publish.py`.

**`scripts/repost_to_bluesky.py`** - Bluesky repost bot (standalone digest)
- Runs as its own cron job (`.github/workflows/bluesky-repost.yml`), every 6h
- Queries `phd_positions` for rows where `reposted_to_bluesky_at IS NULL` that are
  verified + canonical (`duplicate_of IS NULL`) and whose `user_handle` is **not**
  in `docs/aggregators.json` (aggregators filtered in Python)
- **Quote-posts** each original (native reposts can't carry text) with clickable
  hashtag facets for level (`position_type`), country, and subjects (`disciplines`),
  built via `atproto.client_utils.TextBuilder.tag()`. Reuses
  `src/sources/bluesky.py:get_client()` for auth.
- Sets `reposted_to_bluesky_at` per row on success (and on skip of a
  deleted/unavailable original) so it isn't retried forever; API errors leave the
  row un-marked → retried next run (idempotent). Capped at `REPOST_LIMIT` (20)/run.
- `--dry-run` prints the tag line + target URI without posting; `--limit N` overrides.
- The bot account is the **same** account used for search (`BLUESKY_HANDLE`/
  `BLUESKY_PASSWORD`); `BlueskySource.fetch_posts()` skips posts authored by that
  handle (captured as `self._self_handle` after login) so we never re-ingest our own
  reposts. **First-run:** pre-mark the existing backlog (see migration 006) so only
  positions ingested after launch are reposted.

**`src/dedup.py`** - Production deduplication helpers (used by `stages/dedup.py`)
- `preprocess_text()` - Cleans post text (strips bio, URLs, linked pages)
- `normalize_application_url()` - Removes fragments, transport noise, and tracking parameters while retaining vacancy-specific query parameters.
- `deduplicate_new_posts()` - First collapses exact normalized official application links, then uses TF-IDF similarity; auto-accepts >= 0.95, LLM-verifies the 0.25–0.95 zone.

### Data Flow (Supabase — 4-Stage Pipeline)

Each stage writes persistent state before proceeding. A restart on the same
`run_date` detects completed stages and skips them.

| Stage | Input | Output |
|-------|-------|--------|
| 1 Fetch | sync state (last_timestamp, existing_uris from `phd_positions`) | rows in `phd_positions_staging` |
| 2 Filter | unfiltered staging rows | classification plus the five nullable SEO metadata fields set in one model call |
| 3 Dedup | verified staging rows + existing canonical posts in `phd_positions` | `duplicate_of` set on staging rows |
| 4 Publish | all staging rows | upserted into `phd_positions`; staging + `pipeline_runs` row deleted |

The ingest workflow (`.github/workflows/scheduled-search.yml`) runs **4×/day**
(05:00, 11:00, 17:00, 23:00 UTC). Only the 05:00 UTC run regenerates and commits
the static site, limiting routine Vercel production deployments to one per day.
Manual non-recovery runs also regenerate it. After each successful publish the
`pipeline_runs` row is deleted, so later runs fetch only posts newer than the
last publish (incremental via `phd_positions.created_at`).

The Telegram digest runs separately on its own 3×/day schedule — see the post_to_telegram entry above.

**Bluesky Source (fetch stage):**
1. Fetch posts from Bluesky API (sorted by relevance)
2. Deduplicate by URI; filter by timestamp
3. Prepend author bio; build `raw_text` + `metadata_text`
4. Return all posts with `is_verified_job=None` (classification happens in Stage 2)

### Data Flow (CSV — Single-Pass)

1. Fetch Bluesky posts (BlueskySource returns unclassified posts)
2. Inline LLM classification per Bluesky post (if classifier available)
3. Save directly to CSV; update sync state

## Testing

```bash
python -m pytest tests/ -v
```

Test files:
- `tests/test_classifier.py` - LLM classifier with mock LLM provider
- `tests/test_dedup.py` - deterministic application-link deduplication and URL-normalization regressions
- `tests/test_mistral.py` - Mistral request, caching, retry, and usage behavior
- `tests/test_provider_selection.py` - Provider ordering and single-provider selection
- `tests/test_llm_benchmark_fixture.py` - Benchmark fixture schema and label counts
- `tests/test_csv_storage.py` - CSV storage with array serialization
- `tests/test_mock_storage.py` - Mock storage backend behavior
- `tests/test_integration.py` - End-to-end classifier → storage pipeline
- `tests/test_seo_lifecycle.py` - active/archive boundaries and strict eligibility
- `tests/test_seo_pipeline.py` - source-to-staging-to-publish SEO field contract
- `tests/test_seo_escaping.py` - generated pages, split sitemaps, indexing/schema invariants, and script safety
- `tests/test_e2e_frontend.py` - offline `?mock` Playwright smoke tests for the current feed selectors
- `tests/test_sync_state.py` - Incremental sync-state management

## Key Dependencies

- `atproto` - AT Protocol SDK (Bluesky)
- `python-dotenv` - Environment variables
- `requests` - Hosted LLM APIs and web requests
- `scikit-learn` - TF-IDF similarity (deduplication)
- `supabase` - Supabase client

## Supabase Setup

1. Create project at https://supabase.com
2. Run this SQL to create all required tables:
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
    seo_enriched_at TIMESTAMPTZ,
    posted_to_telegram_at TIMESTAMPTZ,  -- NULL = un-posted; set by Telegram digest
    reposted_to_bluesky_at TIMESTAMPTZ  -- NULL = un-reposted; set by Bluesky repost bot
);

-- Partial index keeps the digest's "find un-posted Bio+CS" query fast.
CREATE INDEX IF NOT EXISTS phd_positions_unposted_idx
  ON phd_positions (created_at DESC)
  WHERE posted_to_telegram_at IS NULL;

-- Partial index for the Bluesky repost bot's "find un-reposted" query.
CREATE INDEX IF NOT EXISTS phd_positions_unreposted_idx
  ON phd_positions (created_at)
  WHERE reposted_to_bluesky_at IS NULL;

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
```
3. Get the project URL and a server-side secret/service-role key from Settings → API
4. Add to `.env`: `SUPABASE_URL` and `SUPABASE_KEY`

**`duplicate_of` column:** `NULL` = canonical post (shown in UI). Contains URI of the newest (canonical) post in a duplicate group. When duplicates are detected, the older post gets `duplicate_of` set to the newer post's URI.

**`pipeline_runs` table:** One row per active run. Stores completion timestamps for stages 1–3. **All** rows are **deleted** after Stage 4 (Publish) succeeds (drain-all) so the next invocation starts fresh and any stale rows from previously crashed days are cleared. On crash mid-run the row survives, allowing the next invocation to resume from the last incomplete stage.

**`phd_positions_staging` table:** Transient work queue. Fetch inserts under today's `run_date`; Filter/Dedup/Publish process rows across **all** run_dates. A successful publish clears the **entire** table (not just today's rows), so leftovers from a crashed day are swept up and published on the next run rather than orphaned.

**`reposted_to_bluesky_at` column:** `NULL` = not yet reposted by the Bluesky repost bot. Added in migration `006_bluesky_repost.sql`, which also documents the one-time start-fresh `UPDATE` that pre-marks the existing backlog.

## GitHub Actions

The workflow at `.github/workflows/scheduled-search.yml` runs 4×/day
(05:00, 11:00, 17:00, and 23:00 UTC).
Its manual dispatch accepts `full_sync` plus a validated `fetch_limit` from 1
to 100. Use `full_sync=true` and `fetch_limit=100` only for recovery because it
re-fetches and reclassifies the deepest recent Bluesky search window. Recovery
runs skip static SEO generation so the separate enrichment rollout guard does
not turn a successful database rescue into a false workflow failure.
The Telegram digest (`telegram-digest.yml`) and the Bluesky repost bot
(`bluesky-repost.yml`, every 6h) run on their own separate schedules.

Required secrets:
- `BLUESKY_HANDLE`, `BLUESKY_PASSWORD` (the search + repost bot account)
- `MISTRAL_API_KEY` (primary filter/dedup provider)
- `GEMINI_API_KEY` (optional fallback)
- `NVIDIA_API_KEY` (optional — enables NVIDIA NIM before Groq)
- `GROQ_API_KEY` (optional — enables Groq fallback for filter and dedup)
- `SUPABASE_URL`, `SUPABASE_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` (optional — skipped if not set)
- Manual operator email workflow: `RESEND_API_KEY`, a verified `EMAIL_FROM`, and
  `DIGEST_RECIPIENT`; it reuses privileged `SUPABASE_KEY` when a separately named
  `SUPABASE_SERVICE_KEY` secret is absent. No plaintext Variable fallbacks.
- Vercel unsubscribe function: `SUPABASE_URL` and public `SUPABASE_ANON_KEY`.

## Frontend (`docs/`)

Static Vercel/GitHub Pages site for browsing PhD positions. The UI is a light
academic feed with explicit post actions. No build step; plain HTML + CSS +
vanilla JS.

**`docs/index.html`** - Single-page feed shell:
- Top bar (wordmark + desktop focus-expanding search bar + auth slot), left rail (streams +
  filter chips + subscriptions nudge), center river feed, right activity rail,
  post-detail flyout, auth modal container, toasts, sticky footer
- Supabase JS and CookieConsent load from jsDelivr; fonts load from Google Fonts.
  Vercel Analytics and GA4 are configured in the document head, with GA consent
  defaulting to denied until the stored cookie preference grants analytics.
- SEO injection sentinels preserved: `<!-- STATIC_DATA_START/END -->`
  (wraps `<script id="static-positions">`) and `<!-- SEO_NOSCRIPT_START/END -->`,
  both rewritten by `scripts/generate_seo_pages.py`

**Security invariant — embedding post text in HTML.** Position `message` is
verbatim Bluesky text, i.e. attacker-authored. `json.dumps` does *not* escape
`<`, `>` or `&`, so a post containing the literal `</script>` terminates the
element early and the rest executes as markup (stored XSS → Supabase session
theft from `localStorage`). Every `<script>` block built from position data must
go through `json_for_script()` in `scripts/generate_seo_pages.py`, never bare
`json.dumps`; every HTML-body interpolation goes through `escape_html()`
(Python) or `escapeHtml()` (`docs/app.js`). Covered by
`tests/test_seo_escaping.py`.

**`docs/colors_and_type.css`** - Light scientific-terminal tokens and the Fira
Code / Fira Sans type system. Loads before `styles.css`.

**Brand assets:** `docs/favicon.svg` is the mineral-paper open-book/sky-star
mark; `docs/site.webmanifest` carries matching theme metadata.

**`docs/styles.css`** - v3 feed styles (topbar, rails, river/post, flyout, modal,
onboarding, subscriptions page, toasts).

**`docs/app.js`** - Application logic:
- Initializes Supabase client (anon key); `?mock` loads `mock_data.json`
- 3-tier data loader: embedded `#static-positions` JSON → `positions.json`
  snapshot → live Supabase query (`is_verified_job=true`, `duplicate_of is null`);
  every production path applies the same deadline/90-day active filter
- Renders the feed with day separators + infinite scroll (IntersectionObserver,
  `BATCH_SIZE=30`); posts are non-interactive containers with explicit detail,
  permalink, and source actions
- The Archive tab lazy-loads `archive.json`, generated from expired/older
  canonical rows. It reuses feed filters and presentation while preserving the
  archive `noindex`/no-`JobPosting` policy.
- Filter chips: Level / Country (top-N dynamic) / Area, plus the "Hide aggregator
  reposts" toggle (`isAggregator()` against the inlined aggregator handle set)
- The repost/earlier-posts thread reuses the existing `duplicate_of` dedup graph
  (`duplicateMap`)
- Accounts via **Supabase Auth** (`supabase.auth`): email/password + Google +
  GitHub. The auth modal (signup/login tabs, provider buttons, email form),
  session restore (`getSession` + `onAuthStateChange`), and the profile menu
  (avatar → Feed / Subscriptions / Account & privacy / Sign out) are wired in `app.js`. Bluesky &
  ORCID provider buttons are **hidden** for now (kept in `PROVIDERS` with
  `soon:true`, filtered out at render) until the academic-OAuth branch.
- Saved searches create weekly email subscriptions (`cadence='weekly'`,
  `deliver_email=true`). The Subscriptions page lists, deletes, and edits alert
  filters under owner-only RLS. “Show matches” restores one subscription's
  keyword/area/country/level/aggregator filters and opens the Latest feed.
- **Follows** are live: "+ follow" on a post toggles an `account_follows` row;
  "follow" on a right-rail Top-area/country toggles a `topic_follows` row.
- Initial account chrome stays in a neutral `authReady=false` pending state
  until `getSession()` resolves, so reloads never flash logged-out controls for
  an authenticated visitor.
- The river's **Following** tab is a combined personalized feed:
  followed accounts ∪ followed topics ∪ saved-search subscriptions
  (`matchesFollowing()` / `subMatchesPosition()` in `app.js`). The left-rail
  "Following" link and the mobile bottom-nav "Following" select the same tab.

### Accounts / Auth (Supabase Auth)

`migrations/003_profiles.sql` adds a `profiles` table (one row per `auth.users`,
auto-created by an `on_auth_user_created` trigger) with owner-only RLS. Manual
dashboard setup (documented in the migration header): enable Email/Google/GitHub
providers, add OAuth client credentials, and register redirect URLs for
`https://phdsky.org` and `http://localhost`.

### Follows (account + topic)

`migrations/005_follows.sql` adds `account_follows` (followed Bluesky handles)
and `topic_follows` (followed disciplines/countries), both owner-only RLS. The
frontend reads/writes them via `supabaseClient` under the auth session;
`state.follows` / `state.topics` drive the Following stream and For-me tab.

### Subscriptions (saved-search email digests)

`migrations/004_subscriptions.sql` creates the owner-only table;
the frontend currently saves weekly email subscriptions and supports editing
their filters. Migration 007 adds the per-subscription unsubscribe token.
Backend pieces:

- **`src/email/`** — provider-agnostic email (`EmailProvider` ABC +
  `get_email_provider()`/`send_email()`, chosen by `EMAIL_PROVIDER`, default
  `resend`). Providers accept both HTML and optional plain-text bodies.
- **`scripts/send_subscription_digests.py`** — operator mode resolves exactly the
  profile matching `DIGEST_RECIPIENT`, aggregates its enabled saved searches into
  one message, displays at most three positions, and advances only that profile's
  matching subscription watermarks after a successful send. Zero new matches
  means no email and no write; failures leave watermarks unchanged.
- **`.github/workflows/subscription-digests.yml`** — manual dispatch only. There
  is no schedule and no subscriber-wide send path in the workflow. It reads only
  Actions secrets and calls `--operator-to "$DIGEST_RECIPIENT"`.
- Digest HTML uses the academic light palette and a **See more in your feed**
  button linking to `/#following`; `docs/app.js` resolves `/#following` and
  `/#subscriptions` after session restoration.
- Tests: `tests/test_email.py` (mock provider) + `tests/test_digest.py`
  (matching/formatting).

**Email unsubscribe:** migration 007 adds per-alert tokens and the
`unsubscribe_by_token` RPC. `docs/unsubscribe.html` reads the token from the URL
and invokes that RPC through the public Supabase client.

**Legal pages:** `docs/privacy.html` contains the applicable Section 11 collection
notice, controller/contact, purposes, recipients, international processing,
retention, and access/correction/export/deletion rights. `docs/terms.html`
identifies Eli Eydlin as operator and keeps the Israeli governing-law clause. Both
state that the service is free/non-commercial and has no sales, ads, profiling,
or account-data AI training. Both are linked from the footer; signup shows a
"By creating an account you agree to Terms & Privacy" line.

Deployment: verify `phdsky.org` in Resend (SPF/DKIM/DMARC), apply migrations
through 008, deploy the static UI, test the digest and unsubscribe flow, then
enable the digest workflow. The service-role key must never be exposed to
frontend code.

**`docs/aggregators.json`** - Hand-maintained list `{ "handles": [...] }` of Bluesky handles flagged as aggregator reposters. Source of truth for the UI filter. Updated via `scripts/find_aggregator_candidates.py`.

### Crawlable static surface (`scripts/generate_seo_pages.py`)

The board is a JS app, so everything a crawler indexes is generated as static
HTML next to it. Googlebot renders JS, which means `<noscript>` is **discarded** —
it is kept for non-rendering scrapers only and must never be the sole path to a
page.

| URL | File | Role |
|-----|------|------|
| `/p/<slug>` | `docs/p/<slug>.html` | One per active or archived position. Archived/weak pages are `noindex, follow`; only complete active jobs hold `JobPosting`. |
| `/positions`, `/positions/<n>` | `docs/positions.html`, `docs/positions/<n>.html` | Active positions only. Page one is indexable; later pages are `noindex, follow`. |
| `/area/<slug>`, `/country/<slug>` | `docs/area/*.html`, `docs/country/*.html` | Active-only facet hubs — the primary evergreen ranking targets. |
| `/sitemap.xml` | `docs/sitemap.xml` | Sitemap index pointing to the two child sitemaps. |
| `/sitemaps/core.xml` | `docs/sitemaps/core.xml` | Homepage, `/positions`, legal/about, and active hubs; no deep pagination. |
| `/sitemaps/jobs.xml` | `docs/sitemaps/jobs.xml` | SEO-eligible active job pages only. |

Two invariants worth preserving:

- **Every eligible `/p/` page needs an internal link.** Active listings and hubs
  provide those links; archived pages intentionally drop out of navigation and
  sitemaps while remaining available at their existing URL. The feed also
  `docs/app.js` `postHTML()` links each post's timestamp to its `/p/` permalink
  (`data-stop` keeps the flyout working). A previous redesign dropped that link
  and orphaned the corpus — `tests/test_seo_escaping.py` now guards it.
- **Listing pages use `CollectionPage` + `ItemList`**, not `Dataset` (wrong type,
  and it asserted a CC0 license over third-party posts). Hubs below
  `FACET_MIN_POSITIONS`, and catch-all labels in `FACET_EXCLUDE_DISCIPLINES`, are
  skipped so they don't become thin pages.

Generated directories are pruned each run, so a shrinking corpus doesn't leave
stale pages serving 200s.

The generator fetches the full canonical corpus to keep archive URLs alive, then
uses `src/seo.py` to derive active and eligible subsets. Active rows alone feed
the homepage snapshot, `positions.json`, listings, and hub counts. Detail titles
use the extracted role and employer; the primary CTA uses the verified
application URL and Bluesky remains a secondary source. JSON-LD descriptions
remain plain text identical to the visible source text.
The generator reports active rows with null `seo_enriched_at` but does not block
the whole site refresh. Existing eligibility rules keep those rows out of the
jobs sitemap and `JobPosting` markup until enrichment completes.

SEO rollout order: apply `008_seo_job_metadata.sql`; run the enrichment benchmark;
run the resumable active-row backfill; regenerate static output; deploy; delete
and resubmit `sitemap.xml` in Search Console; then inspect the homepage,
`/positions`, two hubs, and five eligible current job pages. Do not add the
Indexing API until the structured-data cohort is clean.

**`vercel.json`** - Static deploy config for Vercel (serves `docs/`). The site is canonical at **<https://phdsky.org/>** (Vercel from `main:/docs`). The legacy GitHub Pages URL redirects here from the `gh-pages` branch (its `docs/` contains only a meta-refresh + JS redirect to `phdsky.org`). `scripts/generate_seo_pages.py` defaults `BASE_URL` to `https://phdsky.org/`; override with `SITE_BASE_URL` env if you need a different host.

Vercel Deployment Retention is configured in the project dashboard, not in
`vercel.json`. Recommended Hobby policy: production 7 days, previews 3 days,
errored/cancelled 1 day. Remove merged remote branches so their latest preview
is no longer protected from retention.

### RLS Policy Required

The frontend uses the public anon key, so RLS must be enabled:
```sql
ALTER TABLE phd_positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read" ON phd_positions FOR SELECT USING (true);
```

### Local Testing

Serve `docs/` over HTTP and open it, e.g. `python -m http.server --directory docs`
then visit `http://localhost:8000/`. Live Supabase reads work from `localhost`
(public anon key + read RLS). Add `?mock` to load `docs/mock_data.json` offline.
