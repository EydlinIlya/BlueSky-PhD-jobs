# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important: Documentation Requirements

**Both README.md and CLAUDE.md must be kept up to date and checked before every commit.**

When making changes:
1. Update README.md if user-facing features, options, or setup steps change
2. Update CLAUDE.md if architecture, modules, or development practices change
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
- GitHub Actions for automated daily updates
- GitHub Pages frontend for browsing positions

## Development Setup

```bash
.venv/Scripts/activate  # Windows
source .venv/bin/activate  # Unix
pip install -e .
```

## Environment Variables

Required in `.env` (for Bluesky source):
```
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password
```

Optional:
```
NVIDIA_API_KEY=your-nvidia-api-key    # For LLM filtering (Bluesky)
SUPABASE_URL=https://xxx.supabase.co  # For Supabase storage
SUPABASE_KEY=your-anon-key            # For Supabase storage
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
- `main()` - Orchestrates multi-source fetching and aggregation

### Modules

**`src/sources/`** - Data source implementations
- `base.py` - `DataSource` ABC with `fetch_posts()` method, `Post` dataclass
- `bluesky.py` - Bluesky source using AT Protocol SDK
- `scholarshipdb.py` - ScholarshipDB web scraper

**`src/sync_state.py`** - Multi-source sync state management
- `SyncStateManager` class for per-source state tracking
- Automatic migration from v1 (single-source) to v2 (multi-source) format
- Legacy functions for backward compatibility

**`src/logger.py`** - Logging configuration

**`src/llm/`** - LLM integration (for Bluesky)
- `config.py` - Model settings, prompts, discipline list, and position types
- `base.py` - Abstract `LLMProvider` class
- `nvidia.py` - NVIDIA API (Llama 4 Maverick) implementation
- `classifier.py` - `JobClassifier` for filtering and metadata extraction

**`src/storage/`** - Storage backends
- `base.py` - Abstract `StorageBackend` class
- `csv_storage.py` - Local CSV file storage
- `supabase.py` - Supabase PostgreSQL storage

### Data Flow

**Bluesky Source:**
1. Fetch posts from Bluesky API (sorted by relevance)
2. Deduplicate by URI
3. Filter by timestamp (incremental sync)
4. Prepend author bio for context
5. LLM classification: job detection + metadata extraction
6. Return Post objects

**ScholarshipDB Source:**
1. Query each discipline field separately (Computer Science, Biology, etc.)
2. Parse HTML listings for title, country, date, link
3. Map site disciplines to our discipline list
4. All positions are `is_verified_job=True` (pre-verified from job site)
5. Return Post objects

**Aggregation:**
1. Collect posts from all enabled sources
2. Convert Post objects to dicts
3. Save to storage backend
4. Update per-source sync state

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
    country TEXT,
    position_type TEXT[],
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);
```
3. Get URL and anon key from Settings → API
4. Add to `.env`: `SUPABASE_URL` and `SUPABASE_KEY`

## GitHub Actions

The workflow at `.github/workflows/scheduled-search.yml` runs daily at 8:30 AM UTC.

Required secrets:
- `BLUESKY_HANDLE`, `BLUESKY_PASSWORD`
- `NVIDIA_API_KEY`
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
- Filters by discipline, country, and position type
- Configures AG Grid columns with filters/sorting

### RLS Policy Required

The frontend uses the public anon key, so RLS must be enabled:
```sql
ALTER TABLE phd_positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read" ON phd_positions FOR SELECT USING (true);
```

### Local Testing

Open `docs/index.html` directly in a browser (no server required).
