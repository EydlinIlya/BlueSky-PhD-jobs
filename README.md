# bluesky_search

Search Bluesky for PhD position announcements using the AT Protocol SDK.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate  # Windows
source .venv/bin/activate  # Unix
pip install -e .
```

## Configuration

Create a `.env` file with your Bluesky credentials:

```
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password
```

Create an app password at Settings → App Passwords in Bluesky.

## Usage

```bash
python bluesky_search.py
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `-q, --query` | Search query (repeatable) | PhD position, PhD call, doctoral position, PhD opportunity, PhD opening, PhD vacancy |
| `-o, --output` | Output CSV filename | `phd_positions.csv` |
| `-l, --limit` | Max results per query | 50 |

### Examples

```bash
# Custom search queries
python bluesky_search.py -q "postdoc position" -q "research fellow"

# Specify output file and limit
python bluesky_search.py -o results.csv -l 100
```

## Output

CSV file with columns: `message`, `url`, `user`, `created`

See [sample_output.csv](sample_output.csv) for example results.

## Dependencies

- [atproto](https://atproto.blue/) - AT Protocol SDK for Python
- python-dotenv - Environment variable management
