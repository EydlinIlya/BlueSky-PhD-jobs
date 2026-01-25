# bluesky_search

Search Bluesky for PhD position announcements using the AT Protocol SDK.

## Features

- Search multiple PhD-related queries on Bluesky
- **LLM filtering** - Automatically filter out non-job posts (jokes, discussions, etc.)
- **Discipline classification** - Categorize positions into 18 academic disciplines
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
| `-q, --query` | Search query (repeatable) | PhD position, PhD call, etc. |
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

CSV columns: `uri`, `message`, `url`, `user`, `created`, `discipline`, `is_verified_job`

Disciplines: Computer Science, Biology, Chemistry, Physics, Mathematics, Engineering, Medicine, Psychology, Economics, Environmental Science, Linguistics, History, Political Science, Sociology, Law, Arts & Humanities, Education, Other

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
    discipline TEXT,
    is_verified_job BOOLEAN DEFAULT TRUE,
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);
```

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

## Dependencies

- [atproto](https://atproto.blue/) - AT Protocol SDK for Python
- [google-genai](https://github.com/google-gemini/generative-ai-python) - Gemini/Gemma API
- [supabase](https://supabase.com/docs/reference/python) - Supabase client
- python-dotenv - Environment variable management

## License

Apache License 2.0
