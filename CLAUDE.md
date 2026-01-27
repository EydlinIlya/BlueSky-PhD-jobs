# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important: Documentation Requirements

**Both README.md and CLAUDE.md must be kept up to date and checked before every commit.**

When making changes:
1. Update README.md if user-facing features, options, or setup steps change
2. Update CLAUDE.md if architecture, modules, or development practices change
3. Verify both files are current before committing

## Project Overview

BlueSky-PhD-jobs searches Bluesky social network for PhD position announcements using the AT Protocol SDK. Features include:
- LLM-based filtering to identify real job postings
- Multi-discipline classification (1-3 academic categories per post)
- Author bio enrichment for improved discipline classification
- Incremental updates (only fetch new posts)
- Multiple storage backends (CSV, Supabase)
- GitHub Actions for automated daily updates
- GitHub Pages frontend for browsing positions

## Development Setup

```bash
.venv/Scripts/activate  # Windows
source .venv/bin/activate  # Unix
pip install -e .
```

## Environment Variables

Required in `.env`:
```
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password
```

Optional:
```
GEMINI_API_KEY=your-gemini-api-key    # For LLM filtering
SUPABASE_URL=https://xxx.supabase.co  # For Supabase storage
SUPABASE_KEY=your-anon-key            # For Supabase storage
```

## Running

```bash
python bluesky_search.py                    # Default: CSV storage, LLM if key set
python bluesky_search.py --storage supabase # Use Supabase backend
python bluesky_search.py --no-llm           # Disable LLM filtering
python bluesky_search.py --full-sync        # Ignore previous sync state
```

## Architecture

### Main Script (`bluesky_search.py`)
- `get_client()` - Authenticates with Bluesky
- `get_classifier()` - Creates LLM classifier if API key available
- `get_storage()` - Creates storage backend (CSV or Supabase)
- `search_with_retry()` - Handles rate limits with exponential backoff
- `search_phd_calls()` - Runs queries, deduplicates, applies LLM filter
- `load_sync_state()` / `save_sync_state()` - Incremental update tracking

### Modules

**`src/logger.py`** - Logging configuration

**`src/llm/`** - LLM integration
- `config.py` - Model settings, prompts, and discipline list (edit this to tune behavior)
- `base.py` - Abstract `LLMProvider` class
- `gemini.py` - Google Gemini/Gemma implementation
- `classifier.py` - `JobClassifier` for filtering and discipline classification

**`src/storage/`** - Storage backends
- `base.py` - Abstract `StorageBackend` class
- `csv_storage.py` - Local CSV file storage
- `supabase.py` - Supabase PostgreSQL storage

### Data Flow
1. Fetch posts from Bluesky API (sorted by relevance, not date)
2. Deduplicate by URI
3. Filter by timestamp (incremental sync)
4. Fetch author bio (`post.author.description`) and prepend to message as `[Bio: ...]`
5. LLM classification (if enabled):
   - Job detection uses **raw post text only** (bio confuses the small model, causing false rejections)
   - Discipline classification uses **bio-enriched text** (bio provides critical discipline context, e.g. "Professor of Biology")
6. Save ALL posts to storage backend (non-jobs included for analysis)
7. Update sync state

Note: Frontend filters to show only is_verified_job=true posts.

## Testing

```bash
python -m pytest tests/ -v
```

Tests use a `MockStorage` backend (`tests/mock_storage.py`) that simulates Supabase-like behavior in memory (upsert semantics, disciplines as arrays). No external services needed.

Test files:
- `tests/test_classifier.py` - LLM classifier with mock LLM provider
- `tests/test_csv_storage.py` - CSV storage with disciplines array serialization
- `tests/test_mock_storage.py` - Mock storage backend behavior
- `tests/test_integration.py` - End-to-end classifier → storage pipeline

## Key Dependencies

- `atproto` - AT Protocol SDK
- `python-dotenv` - Environment variables
- `google-genai` - Gemini/Gemma API
- `supabase` - Supabase client

## Supabase Setup

1. Create project at https://supabase.com
2. Run this SQL to create the table:
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
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);
```
3. Get URL and anon key from Settings → API
4. Add to `.env`: `SUPABASE_URL` and `SUPABASE_KEY`

## GitHub Actions

The workflow at `.github/workflows/daily-update.yml` runs daily at 6 AM UTC.

Required secrets:
- `BLUESKY_HANDLE`, `BLUESKY_PASSWORD`
- `GEMINI_API_KEY`
- `SUPABASE_URL`, `SUPABASE_KEY`

## Frontend (`docs/`)

Static GitHub Pages site for browsing PhD positions:

**`docs/index.html`** - Main page with CDN imports:
- Tailwind CSS for styling
- AG Grid for data table
- Supabase JS SDK for data fetching

**`docs/styles.css`** - AG Grid theme customization

**`docs/app.js`** - Application logic:
- Initializes Supabase client (anon key)
- Fetches from `phd_positions` table
- Configures AG Grid columns with filters/sorting
- Column drag-to-hide disabled (`suppressDragLeaveHidesColumns`)

### RLS Policy Required

The frontend uses the public anon key, so RLS must be enabled:
```sql
ALTER TABLE phd_positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read" ON phd_positions FOR SELECT USING (true);
```

### Local Testing

Open `docs/index.html` directly in a browser (no server required).
