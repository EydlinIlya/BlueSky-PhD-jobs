"""Find aggregator candidates in phd_positions.

Lists Bluesky handles that have posted >= MIN_POSTS canonical positions
(duplicates excluded) and prints their bio from the most recent post.
A human then reviews the output and hand-edits ``docs/aggregators.json``
to add/remove entries.

Usage:
    python scripts/find_aggregator_candidates.py [--min-posts 5]

No writes, no LLM calls. Bio extraction uses the same regex as
``src/dedup.py:preprocess_text`` so the source of truth stays aligned.

Note: this classification affects ONLY the frontend filter in
``docs/app.js`` + ``docs/aggregators.json``. It never touches the
pipeline / dedup code — dedup already strips the ``[Bio: ...]`` prefix
before TF-IDF comparison, so aggregator status has no effect on
deduplication.
"""

import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BIO_PATTERN = re.compile(r"^\[Bio:(.*?)\]\s*", flags=re.DOTALL)


def extract_bio(message: str) -> str:
    """Pull the ``[Bio: ...]`` prefix out of a post's message, if any."""
    if not message:
        return ""
    m = BIO_PATTERN.match(message)
    return m.group(1).strip() if m else ""


def fetch_all_positions(supabase):
    """Fetch every canonical row's (handle, created_at, message)."""
    page_size = 1000
    all_rows = []
    start = 0
    while True:
        resp = (
            supabase.table("phd_positions")
            .select("user_handle,created_at,message")
            .is_("duplicate_of", "null")
            .order("created_at", desc=True)
            .range(start, start + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        start += page_size
    return all_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-posts",
        type=int,
        default=5,
        help="Minimum canonical post count to flag as a candidate (default: 5).",
    )
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set.", file=sys.stderr)
        sys.exit(1)

    supabase = create_client(url, key)
    rows = fetch_all_positions(supabase)

    by_handle = defaultdict(list)
    for r in rows:
        h = r.get("user_handle")
        if h:
            by_handle[h].append(r)

    candidates = [
        (h, posts) for h, posts in by_handle.items() if len(posts) >= args.min_posts
    ]
    candidates.sort(key=lambda x: -len(x[1]))

    print(f"# Aggregator candidates (>= {args.min_posts} canonical posts)")
    print(f"# Found {len(candidates)} handle(s). Review bios and add real aggregators")
    print(f"# to docs/aggregators.json by hand.\n")
    print(f"{'handle':<40} {'posts':>6}  bio")
    print("-" * 100)
    for handle, posts in candidates:
        # posts are ordered newest-first by the query
        bio = extract_bio(posts[0].get("message", ""))
        bio_compact = re.sub(r"\s+", " ", bio).strip()[:200]
        print(f"{handle:<40} {len(posts):>6}  {bio_compact}")


if __name__ == "__main__":
    main()
