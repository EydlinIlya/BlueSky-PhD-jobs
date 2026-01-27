# BlueSky-PhD-jobs

Search Bluesky for PhD position announcements using the AT Protocol SDK.

## Features

- Search multiple PhD-related queries on Bluesky
- **LLM filtering** - Automatically filter out non-job posts (jokes, discussions, etc.)
- **Multi-discipline classification** - Categorize positions into 1-3 academic disciplines
- **Author bio enrichment** - Prepends author profile bio for better discipline classification
- **Embed link context** - Uses link preview metadata from shared URLs to improve classification
- **Incremental updates** - Only fetch new posts since last run
- **Multiple storage backends** - CSV (local) or Supabase (cloud PostgreSQL)
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
# Required - Bluesky credentials
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password

# Optional - LLM filtering (recommended)
GEMINI_API_KEY=your-gemini-api-key

# Optional - Supabase storage
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-anon-key
```

Get a Bluesky app password at Settings → App Passwords.
Get a Gemini API key at https://aistudio.google.com/apikey

## Usage

```bash
python bluesky_search.py
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `-q, --query` | Search query (repeatable) | 11 academic job queries |
| `-o, --output` | Output CSV filename | `phd_positions.csv` |
| `-l, --limit` | Max results per query | 50 |
| `--no-llm` | Disable LLM filtering | LLM enabled if key set |
| `--full-sync` | Ignore previous sync state | Incremental |
| `--storage` | Storage backend: `csv` or `supabase` | `csv` |

### Examples

```bash
# Basic search with LLM filtering
python bluesky_search.py

# Custom queries
python bluesky_search.py -q "postdoc position" -q "research fellow"

# Full sync to Supabase
python bluesky_search.py --storage supabase --full-sync

# Quick test without LLM
python bluesky_search.py --no-llm -l 10
```

## Output

CSV columns: `uri`, `message`, `url`, `user`, `created`, `disciplines`, `is_verified_job`

The `message` field includes the author's profile bio prepended as `[Bio: ...]` when available, followed by the post text. This provides discipline context (e.g. "Professor of Biology at MIT").

Each post can have 1-3 disciplines. In CSV output, `disciplines` is a JSON array (e.g. `["Biology", "Computer Science"]`).

Disciplines: Computer Science, Biology, Chemistry & Materials Science, Physics, Mathematics, Medicine, Psychology, Economics, Linguistics, History, Sociology & Political Science, Arts & Humanities, Education, Other, General call

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
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);
```

If upgrading from an existing table with a single `discipline` TEXT column, run the migration at `migrations/001_discipline_to_disciplines_array.sql`.

3. Go to Settings → API and copy:
   - Project URL → `SUPABASE_URL`
   - anon/public key → `SUPABASE_KEY`

4. Add to your `.env` file

## GitHub Actions

The included workflow runs daily at 6 AM UTC. To enable:

1. Push to GitHub
2. Go to Settings → Secrets and variables → Actions
3. Add secrets: `BLUESKY_HANDLE`, `BLUESKY_PASSWORD`, `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`
4. The workflow will run automatically or trigger manually from Actions tab

## GitHub Pages Frontend

A web interface to browse PhD positions is available at the `/docs` folder.

### Setup

1. **Add RLS policy** to Supabase (SQL Editor):
   ```sql
   ALTER TABLE phd_positions ENABLE ROW LEVEL SECURITY;
   CREATE POLICY "Allow public read" ON phd_positions FOR SELECT USING (true);
   ```

2. **Update `docs/app.js`** with your Supabase anon key (Settings → API → anon public)

3. **Enable GitHub Pages**:
   - Go to repo Settings → Pages
   - Source: Deploy from branch
   - Branch: main, folder: /docs
   - Save

4. Site will be live at: `https://eydlinilya.github.io/BlueSky-PhD-jobs/`

### Features

- Sortable columns (click headers)
- Filterable by date, discipline, and text
- Pagination (25/50/100 per page)
- Direct links to Bluesky posts

## Dependencies

- [atproto](https://atproto.blue/) - AT Protocol SDK for Python
- [google-genai](https://github.com/google-gemini/generative-ai-python) - Gemini/Gemma API
- [supabase](https://supabase.com/docs/reference/python) - Supabase client
- python-dotenv - Environment variable management

## License

Apache License 2.0
