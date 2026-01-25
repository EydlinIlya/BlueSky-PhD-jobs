# bluesky_search

Search Bluesky for PhD position announcements using the AT Protocol SDK.

## Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate
.venv/Scripts/activate  # Windows
source .venv/bin/activate  # Unix

# Install
pip install -e .
```

## Configuration

Create a `.env` file with your Bluesky credentials:

```
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password
```

You can create an app password at Settings → App Passwords in Bluesky.

## Usage

```bash
# Default search (PhD position, PhD call, doctoral position, etc.)
python bluesky_search.py

# Custom search queries
python bluesky_search.py -q "postdoc position" -q "research fellow"

# Specify output file and limit
python bluesky_search.py -o results.csv -l 100
```

Outputs results to `phd_positions.csv` (default) with columns:
- `message` - Post text
- `url` - Link to the post on Bluesky
- `user` - Author handle
- `created` - Post timestamp

## Dependencies

- [atproto](https://atproto.blue/) - AT Protocol SDK for Python
- python-dotenv - Environment variable management
