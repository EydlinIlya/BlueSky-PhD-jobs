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

PhD Position Finder aggregates PhD position announcements from multiple sources:
- **Bluesky** - Social network posts via AT Protocol SDK with LLM filtering
- **ScholarshipDB** - Academic job listings via web scraping

Features include:
- Multi-source aggregation with unified data format
- LLM-based filtering for Bluesky posts (NVIDIA Llama 4 Maverick)
- Pre-classified positions from ScholarshipDB (no LLM needed)
- Single JSON metadata extraction: disciplines (1-3), country, and position type
- Per-source incremental sync state
- Multiple storage backends (CSV, Supabase)
- Deduplication of reposted positions (TF-IDF + LLM verification)
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
NVIDIA_API_KEY=your-nvidia-api-key    # For LLM filtering (Bluesky)
MISTRAL_API_KEY=your-mistral-api-key  # Fallback LLM when NVIDIA is rate limited
SUPABASE_URL=https://xxx.supabase.co  # For Supabase storage
SUPABASE_KEY=your-anon-key            # For Supabase storage
TELEGRAM_BOT_TOKEN=your-bot-token     # For Telegram channel
TELEGRAM_CHANNEL_ID=@your_channel     # Telegram channel ID
SUPABASE_SERVICE_KEY=service-role-key # For subscription digest cron (bypasses RLS)
RESEND_API_KEY=your-resend-key        # For subscription email digests
EMAIL_FROM=PhD Sky <alerts@phdsky.org># Digest sender (verified Resend domain)
EMAIL_PROVIDER=resend                 # Email backend (default: resend)
SUPABASE_ANON_KEY=your-anon-key       # Vercel unsubscribe function (public key)
```

## Running

```bash
# Default: Bluesky only, CSV storage
python bluesky_search.py

# Both sources
python bluesky_search.py --sources bluesky,scholarshipdb

# ScholarshipDB only
python bluesky_search.py --sources scholarshipdb --scholarshipdb-pages 5

# Supabase storage with both sources
python bluesky_search.py --storage supabase --sources bluesky,scholarshipdb

# Full sync (ignore previous state)
python bluesky_search.py --full-sync

# Disable LLM for Bluesky
python bluesky_search.py --no-llm
```

## Architecture

### Main Script (`bluesky_search.py`)
- `get_classifier()` - Creates LLM classifier if API key available
- `get_storage()` - Creates storage backend (CSV or Supabase)
- `parse_sources()` - Validates source selection
- `main()` - Routes to 4-stage pipeline (Supabase) or simplified single-pass flow (CSV)

### Modules

**`src/sources/`** - Data source implementations
- `base.py` - `DataSource` ABC with `fetch_posts()` method, `Post` dataclass (includes `raw_text`, `metadata_text` fields)
- `bluesky.py` - Bluesky source; stores `raw_text`/`metadata_text` on Post; returns posts unclassified (`is_verified_job=None`)
- `scholarshipdb.py` - ScholarshipDB web scraper

**`src/sync_state.py`** - Multi-source sync state management
- `SyncStateManager` class for per-source state tracking (CSV backend only)

**`src/logger.py`** - Logging configuration

**`src/llm/`** - LLM integration (for Bluesky)
- `config.py` - Model settings, prompts, discipline list (includes `Ecology`), and position types. The `METADATA_PROMPT_TEMPLATE` contains an explicit rule that remote-sensing-of-forests/crop-fields posts must be classified as Ecology primary (Biology / CS only as secondary tags). Also holds `MISTRAL_MODEL` and `FALLBACK_COOLDOWN`.
- `base.py` - Abstract `LLMProvider` class + `LLMUnavailableError`
- `openai_compatible.py` - `OpenAICompatibleProvider` base with the shared `/v1/chat/completions` retry / rate-limit / timeout logic. Raises `LLMUnavailableError` once a provider is exhausted so a fallback can take over.
- `nvidia.py` - `NvidiaProvider` (Llama 4 Maverick via NVIDIA NIM); thin subclass of the OpenAI-compatible base
- `mistral.py` - `MistralProvider` (Mistral La Plateforme); fallback for NVIDIA, same base
- `fallback.py` - `FallbackProvider`: tries providers in priority order (NVIDIA → Mistral), failing over on `LLMUnavailableError`. A per-provider cooldown (`FALLBACK_COOLDOWN`, 1800s) skips a rate-limited/down primary so the per-post classify loop doesn't re-burn its retry budget on every post.
- `classifier.py` - `JobClassifier` for filtering and metadata extraction

`bluesky_search.py:get_classifier()` builds the provider from whichever keys are set: `NVIDIA_API_KEY` (primary) and/or `MISTRAL_API_KEY` (fallback). Both set → `FallbackProvider([NVIDIA, Mistral])`; one set → that provider alone; neither → `None` (no LLM).

**`src/storage/`** - Storage backends
- `base.py` - Abstract `StorageBackend` class
- `csv_storage.py` - Local CSV file storage
- `supabase.py` - Supabase PostgreSQL storage; also contains pipeline support methods (`get_or_create_run`, `update_run`, `insert_staging`, `get_staging_*`, `update_staging_*`, `delete_staging`)

**`src/pipeline/`** - 4-stage persistent pipeline (Supabase only)
- `runner.py` - Orchestrates stages; skips already-completed ones using `pipeline_runs` checkpoints
- `checkpoint.py` - Documents `pipeline_runs` table schema
- `stages/fetch.py` - Stage 1: fetch raw posts into `phd_positions_staging` (scoped to today's `run_date`)
- `stages/filter.py` - Stage 2: LLM classification per row; tracks per-row completion via `filter_completed`
- `stages/dedup.py` - Stage 3: TF-IDF + LLM dedup against existing canonical posts
- `stages/publish.py` - Stage 4: upsert staging → `phd_positions`; delete staging. Telegram posting is handled out-of-band by `scripts/post_to_telegram.py`

**Drain-all semantics:** only **Fetch** is scoped to today's `run_date` (it decides "what's new to pull"). **Filter, Dedup, and Publish drain the whole pending staging queue across ALL run_dates** (`get_staging_*`/`delete_staging` accept `run_date=None`). So if a day crashes before Publish, the next successful run sweeps up its leftover staging rows, classifies/dedups/publishes them, and Publish then clears the **entire** staging table plus **all** `pipeline_runs` rows. This guarantees orphaned staging can never accumulate. Per-row write-backs (`update_staging_filter`/`_dedup`) are keyed by each row's own `run_date`.

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
- `deduplicate_new_posts()` - TF-IDF similarity; auto-accepts >= 0.95, LLM-verifies 0.25–0.95 zone

### Data Flow (Supabase — 4-Stage Pipeline)

Each stage writes persistent state before proceeding. A restart on the same
`run_date` detects completed stages and skips them.

| Stage | Input | Output |
|-------|-------|--------|
| 1 Fetch | sync state (last_timestamp, existing_uris from `phd_positions`) | rows in `phd_positions_staging` |
| 2 Filter | unfiltered staging rows | `is_verified_job`, `disciplines`, `country`, `position_type` set per row |
| 3 Dedup | verified staging rows + existing canonical posts in `phd_positions` | `duplicate_of` set on staging rows |
| 4 Publish | all staging rows | upserted into `phd_positions`; staging + `pipeline_runs` row deleted |

The ingest workflow (`.github/workflows/scheduled-search.yml`) runs **4×/day** (07:00, 13:00, 19:00, 01:00 UTC). After each successful publish the `pipeline_runs` row is deleted, so subsequent runs within the same day fetch only posts newer than the last publish (incremental via `phd_positions.created_at`).

The Telegram digest runs separately on its own 3×/day schedule — see the post_to_telegram entry above.

**Bluesky Source (fetch stage):**
1. Fetch posts from Bluesky API (sorted by relevance)
2. Deduplicate by URI; filter by timestamp
3. Prepend author bio; build `raw_text` + `metadata_text`
4. Return all posts with `is_verified_job=None` (classification happens in Stage 2)

**ScholarshipDB Source (fetch stage):**
1. Query each discipline field separately
2. Parse HTML listings for title, country, date, link
3. All positions are `is_verified_job=True` (Stage 2 passes them through immediately)

### Data Flow (CSV — Single-Pass)

1. Fetch from all sources (BlueskySource returns unclassified posts)
2. Inline LLM classification per Bluesky post (if classifier available)
3. Save directly to CSV; update sync state

## Testing

```bash
python -m pytest tests/ -v
```

Test files:
- `tests/test_classifier.py` - LLM classifier with mock LLM provider
- `tests/test_csv_storage.py` - CSV storage with array serialization
- `tests/test_mock_storage.py` - Mock storage backend behavior
- `tests/test_integration.py` - End-to-end classifier → storage pipeline
- `tests/test_scholarshipdb_source.py` - ScholarshipDB source
- `tests/test_sync_state.py` - Multi-source sync state management

## Key Dependencies

- `atproto` - AT Protocol SDK (Bluesky)
- `httpx` - HTTP client (ScholarshipDB scraping)
- `beautifulsoup4` - HTML parsing
- `python-dotenv` - Environment variables
- `requests` - NVIDIA API
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
    duplicate_of TEXT,
    filter_completed BOOLEAN DEFAULT FALSE,
    staged_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_date, uri)
);
```
3. Get URL and anon key from Settings → API
4. Add to `.env`: `SUPABASE_URL` and `SUPABASE_KEY`

**`duplicate_of` column:** `NULL` = canonical post (shown in UI). Contains URI of the newest (canonical) post in a duplicate group. When duplicates are detected, the older post gets `duplicate_of` set to the newer post's URI.

**`pipeline_runs` table:** One row per active run. Stores completion timestamps for stages 1–3. **All** rows are **deleted** after Stage 4 (Publish) succeeds (drain-all) so the next invocation starts fresh and any stale rows from previously crashed days are cleared. On crash mid-run the row survives, allowing the next invocation to resume from the last incomplete stage.

**`phd_positions_staging` table:** Transient work queue. Fetch inserts under today's `run_date`; Filter/Dedup/Publish process rows across **all** run_dates. A successful publish clears the **entire** table (not just today's rows), so leftovers from a crashed day are swept up and published on the next run rather than orphaned.

**`reposted_to_bluesky_at` column:** `NULL` = not yet reposted by the Bluesky repost bot. Added in migration `006_bluesky_repost.sql`, which also documents the one-time start-fresh `UPDATE` that pre-marks the existing backlog.

## GitHub Actions

The workflow at `.github/workflows/scheduled-search.yml` runs daily at 8:30 AM UTC.
The Telegram digest (`telegram-digest.yml`) and the Bluesky repost bot
(`bluesky-repost.yml`, every 6h) run on their own separate schedules.

Required secrets:
- `BLUESKY_HANDLE`, `BLUESKY_PASSWORD` (the search + repost bot account)
- `NVIDIA_API_KEY`
- `MISTRAL_API_KEY` (optional — LLM fallback when NVIDIA is rate limited)
- `SUPABASE_URL`, `SUPABASE_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` (optional — skipped if not set)
- Weekly email workflow: `SUPABASE_SERVICE_KEY`, `RESEND_API_KEY`, and a verified
  `EMAIL_FROM`. These must be Actions secrets; there are no plaintext Variable fallbacks.
- Vercel unsubscribe function: `SUPABASE_URL` and public `SUPABASE_ANON_KEY`.

## Frontend (`docs/`)

Static Vercel/GitHub Pages site for browsing PhD positions. The UI is the light
**Research Library** feed: a chronological river with editorial source rules,
mineral-paper surfaces, restrained academic type, and explicit post actions.
No build step; plain HTML + CSS + vanilla JS.

**`docs/index.html`** - Single-page feed shell:
- Top bar (wordmark + command/search bar + auth slot), left rail (streams +
  filter chips + subscriptions nudge), center river feed, right activity rail,
  post-detail flyout, auth modal container, toasts, sticky footer
- Supabase JS, CookieConsent, Literata, Atkinson Hyperlegible, and IBM Plex Mono
  are self-hosted. GA4 and Vercel Analytics are dynamically inserted only after
  affirmative analytics consent and removed/disabled on withdrawal.
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

**`docs/colors_and_type.css`** - Research Library tokens: mineral paper, carbon
ink, library green, archival blue, signal vermilion, and self-hosted Literata /
Atkinson Hyperlegible / IBM Plex Mono. Loads before `styles.css`.

**`docs/styles.css`** - v3 feed styles (topbar, rails, river/post, flyout, modal,
onboarding, subscriptions page, toasts).

**`docs/app.js`** - Application logic:
- Initializes Supabase client (anon key); `?mock` loads `mock_data.json`
- 3-tier data loader: embedded `#static-positions` JSON → `positions.json`
  snapshot → live Supabase query (`is_verified_job=true`, `duplicate_of is null`)
- Renders the feed with day separators + infinite scroll (IntersectionObserver,
  `BATCH_SIZE=30`); posts are non-interactive containers with explicit detail,
  permalink, and source actions
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
- **Saved searches and weekly email are separate.** Search Enter only applies
  search. Saving inserts a row with `deliver_email=false`; a separate confirmation
  dialog shows the filters, recipient, and weekly frequency before recording
  versioned consent. The Subscriptions page (`#subscriptions`) lists, enables,
  disables, and deletes alerts under owner-only RLS.
- **Account controls** at `#account` support profile/email correction, JSON export,
  cookie settings, and typed-confirmation deletion via `delete_own_account()`.
- **Accessibility** includes semantic buttons/navigation, dialog focus trapping,
  Escape dismissal, focus restoration, background inertness, live statuses,
  visible focus rings, and 44px mobile targets.
- **Follows** are live: "+ follow" on a post toggles an `account_follows` row;
  "follow" on a right-rail Top-area/country toggles a `topic_follows` row.
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
`migrations/008_subscription_compliance.sql` makes it weekly-only, defaults
`deliver_email` to false, records versioned consent/unsubscribe/processing times,
prevents normalized duplicate filters, and pauses legacy delivery until reconfirmed.
Backend pieces:

- **`src/email/`** — provider-agnostic email (`EmailProvider` ABC +
  `get_email_provider()`/`send_email()`, chosen by `EMAIL_PROVIDER`, default
  `resend`). Providers accept both HTML and optional plain-text bodies.
- **`scripts/send_subscription_digests.py`** — standalone cron (mirrors
  `post_to_telegram.py`). It requires `SUPABASE_SERVICE_KEY`, matches from
  `last_processed_at`, advances successful no-match scans, and advances neither
  watermark on send failure. Successful messages include escaped HTML, plain text,
  verified sender identity, and exact RFC 8058 one-click headers.
- **`.github/workflows/subscription-digests.yml`** — weekly only, Monday at
  09:00 UTC. It reads privileged/email configuration only from GitHub Secrets.
- Tests: `tests/test_email.py` (mock provider) + `tests/test_digest.py`
  (matching/formatting).

**Email unsubscribe:** migration 007 adds per-alert tokens; migration 008 replaces
the legacy RPC with idempotent current-alert and all-alert scopes. Vercel function
`api/unsubscribe.js` mutates only on POST; GET returns 405. Machine POST responses
are neutral. The human `docs/unsubscribe.html` page never mutates on load and
requires confirmation for either one alert or all weekly email.

**Legal pages:** `docs/privacy.html` contains the Israel Section 11 collection
notice, controller/contact, purposes, recipients, international processing,
retention, and access/correction/export/deletion rights. `docs/terms.html`
identifies Eli Eydlin as the Israel-based operator and uses Israeli law. Both
state that the service is free/non-commercial and has no sales, ads, profiling,
or account-data AI training. Both are linked from the footer; signup shows a
"By creating an account you agree to Terms & Privacy" line.

Deployment: verify `phdsky.org` in Resend (SPF/DKIM/DMARC), apply migration 008,
deploy the API/static UI, test HTML/text plus both unsubscribe scopes, then enable
the weekly workflow. Vercel needs `SUPABASE_URL` and public `SUPABASE_ANON_KEY`;
the service-role key must never be exposed to frontend or function code.

**`docs/aggregators.json`** - Hand-maintained list `{ "handles": [...] }` of Bluesky handles flagged as aggregator reposters. Source of truth for the UI filter. Updated via `scripts/find_aggregator_candidates.py`.

### Crawlable static surface (`scripts/generate_seo_pages.py`)

The board is a JS app, so everything a crawler indexes is generated as static
HTML next to it. Googlebot renders JS, which means `<noscript>` is **discarded** —
it is kept for non-rendering scrapers only and must never be the sole path to a
page.

| URL | File | Role |
|-----|------|------|
| `/p/<slug>` | `docs/p/<slug>.html` | One per position; holds the `JobPosting` markup that drives Google Jobs eligibility |
| `/positions`, `/positions/<n>` | `docs/positions.html`, `docs/positions/<n>.html` | Paginated over the **whole** corpus (`POSITIONS_PER_PAGE`) |
| `/area/<slug>`, `/country/<slug>` | `docs/area/*.html`, `docs/country/*.html` | Facet hubs — the actual ranking targets |

Two invariants worth preserving:

- **Every `/p/` page needs an internal link.** Sitemaps drive discovery; internal
  links drive crawl priority. The paginated listing exists to guarantee this, and
  `docs/app.js` `postHTML()` links each post's timestamp to its `/p/` permalink
  (`data-stop` keeps the flyout working). A previous redesign dropped that link
  and orphaned the corpus — `tests/test_seo_escaping.py` now guards it.
- **Listing pages use `CollectionPage` + `ItemList`**, not `Dataset` (wrong type,
  and it asserted a CC0 license over third-party posts). Hubs below
  `FACET_MIN_POSITIONS`, and catch-all labels in `FACET_EXCLUDE_DISCIPLINES`, are
  skipped so they don't become thin pages.

Generated directories are pruned each run, so a shrinking corpus doesn't leave
stale pages serving 200s.

**`vercel.json`** - Static deploy config for Vercel (serves `docs/`). The site is canonical at **<https://phdsky.org/>** (Vercel from `main:/docs`). The legacy GitHub Pages URL redirects here from the `gh-pages` branch (its `docs/` contains only a meta-refresh + JS redirect to `phdsky.org`). `scripts/generate_seo_pages.py` defaults `BASE_URL` to `https://phdsky.org/`; override with `SITE_BASE_URL` env if you need a different host.

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
