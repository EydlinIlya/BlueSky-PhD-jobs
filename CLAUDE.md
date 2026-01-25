# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

bluesky_search searches Bluesky social network for PhD position announcements using the AT Protocol SDK.

## Development Setup

```bash
.venv/Scripts/activate  # Windows
source .venv/bin/activate  # Unix
pip install -e .
```

## Running

```bash
# Requires .env file with BLUESKY_HANDLE and BLUESKY_PASSWORD
python bluesky_search.py
```

Outputs `phd_positions.csv` with columns: message, url, user, created.

## Architecture

Single-file script (`bluesky_search.py`):
- `get_client()` - Authenticates with Bluesky using env credentials
- `search_with_retry()` - Handles rate limits and retries with exponential backoff
- `search_phd_calls()` - Runs multiple queries, deduplicates results
- `write_csv()` - Outputs results to CSV

## Key Dependencies

- `atproto` - AT Protocol SDK (requires auth for search_posts)
- `python-dotenv` - Loads credentials from .env
