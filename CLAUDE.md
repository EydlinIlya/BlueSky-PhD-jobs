# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important: Documentation Requirements

**Both README.md and CLAUDE.md must be kept up to date and checked before every commit.**

When making changes:
1. Update README.md if user-facing features, options, or setup steps change
2. Update CLAUDE.md if architecture, modules, or development practices change
3. Verify both files are current before committing

## Project Overview

bluesky_search searches Bluesky social network for PhD position announcements using the AT Protocol SDK. Features include:
- LLM-based filtering to identify real job postings
- Discipline classification (18 academic categories)
- Incremental updates (only fetch new posts)
- Multiple storage backends (CSV, Supabase)
- GitHub Actions for automated daily updates

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
- `base.py` - Abstract `LLMProvider` class
- `gemini.py` - Google Gemini/Gemma implementation (default: gemma-3-1b-it)
- `classifier.py` - `JobClassifier` for filtering and discipline classification

**`src/storage/`** - Storage backends
- `base.py` - Abstract `StorageBackend` class
- `csv_storage.py` - Local CSV file storage
- `supabase.py` - Supabase PostgreSQL storage

### Data Flow
1. Fetch posts from Bluesky API
2. Deduplicate by URI
3. Filter by timestamp (incremental sync)
4. LLM classification (if enabled): filter non-jobs, assign discipline
5. Save to storage backend
6. Update sync state

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
    discipline TEXT,
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
