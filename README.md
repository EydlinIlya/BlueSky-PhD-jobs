# PhD Position Finder

Aggregate PhD and academic position announcements from multiple sources into a unified database.

## Data Sources

- **Bluesky** - Social network posts via AT Protocol SDK with LLM filtering
- **ScholarshipDB** - Academic job listings from scholarshipdb.net (pre-classified)

## Features

- **Multi-source aggregation** - Combine positions from multiple sources
- **LLM filtering** - Automatically filter out non-job posts from Bluesky
- **Multi-discipline classification** - Categorize positions into 1-3 academic disciplines
- **Country detection** - Identifies position country from university, domain, or city names
- **Position type extraction** - PhD Student, Postdoc, Master Student, Research Assistant
- **Deduplication** - TF-IDF + LLM-based detection of reposted positions
- **Incremental sync** - Only fetch new positions since last run
- **4-stage persistent pipeline** - Supabase runs use checkpointed stages (fetch → filter → dedup → publish); a crash mid-filter resumes from the last unprocessed post on the next run
- **Telegram channel** - Auto-posts Biology + CS positions (bioinformatics)
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
# Required (for Bluesky source)
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password

# Optional - LLM filtering (recommended for Bluesky)
NVIDIA_API_KEY=your-nvidia-api-key

# Optional - Supabase storage
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-anon-key

# Optional - Telegram channel
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHANNEL_ID=@your_channel
```

Get a Bluesky app password at Settings → App Passwords.
Get an NVIDIA API key at https://build.nvidia.com

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

CSV columns: `uri`, `message`, `url`, `user`, `created`, `disciplines`, `is_verified_job`, `country`, `position_type`

- **Bluesky posts**: `message` includes author bio as `[Bio: ...]` prefix
- **ScholarshipDB**: `is_verified_job` is always `True` (pre-verified from job site)

Disciplines: Computer Science, Biology, Chemistry & Materials Science, Physics, Mathematics, Medicine, Psychology, Economics, Linguistics, History, Sociology & Political Science, Arts & Humanities, Education, Other, General call

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
    duplicate_of TEXT
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
    duplicate_of TEXT,
    filter_completed BOOLEAN DEFAULT FALSE,
    staged_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_date, uri)
);
```

3. Go to Settings → API and copy:
   - Project URL → `SUPABASE_URL`
   - anon/public key → `SUPABASE_KEY`

4. Add to your `.env` file

## GitHub Actions

The included workflow runs **3 times a day** (08:00, 14:00, 20:00 UTC) so each run fetches only ~6 hours of new posts. To enable:

1. Push to GitHub
2. Go to Settings → Secrets and variables → Actions
3. Add secrets: `BLUESKY_HANDLE`, `BLUESKY_PASSWORD`, `NVIDIA_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`
4. (Optional) Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` for Telegram posting
4. The workflow will run automatically or trigger manually from Actions tab

## Telegram Channel

Positions tagged with both **Biology** and **Computer Science** (bioinformatics, computational biology) are automatically posted to a Telegram channel after each daily run.

### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) → save the token
2. Create a channel (e.g., `@bioinfo_phd_jobs`) and add the bot as admin
3. Add to `.env` or GitHub secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`

If the secrets are not set, the Telegram step is silently skipped.

## GitHub Pages Frontend

A web interface to browse PhD positions is available at the `/docs` folder.

### Setup

1. **Add RLS policy** to Supabase:
   ```sql
   ALTER TABLE phd_positions ENABLE ROW LEVEL SECURITY;
   CREATE POLICY "Allow public read" ON phd_positions FOR SELECT USING (true);
   ```

2. **Update `docs/app.js`** with your Supabase anon key

3. **Enable GitHub Pages**:
   - Go to repo Settings → Pages
   - Source: Deploy from branch
   - Branch: main, folder: /docs

## Dependencies

- [atproto](https://atproto.blue/) - AT Protocol SDK for Bluesky
- [httpx](https://www.python-httpx.org/) - HTTP client for ScholarshipDB
- [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) - HTML parsing
- [requests](https://requests.readthedocs.io/) - NVIDIA API
- [scikit-learn](https://scikit-learn.org/) - TF-IDF similarity for deduplication
- [supabase](https://supabase.com/docs/reference/python) - Supabase client

## License

Apache License 2.0
