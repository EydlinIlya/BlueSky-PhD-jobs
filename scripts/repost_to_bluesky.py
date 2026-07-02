"""Quote-post non-aggregator PhD/postdoc positions to a dedicated Bluesky account.

Standalone digest job (mirrors scripts/post_to_telegram.py): queries Supabase for
verified, canonical positions that (a) haven't been reposted yet and (b) come from
a non-aggregator handle, then quote-posts each original with clickable hashtags for
level (position_type), country, and subjects (disciplines). After a successful
post the row's `reposted_to_bluesky_at` is set so it isn't reposted again.

The bot account is the SAME account used for search (BLUESKY_HANDLE/PASSWORD); the
search source (src/sources/bluesky.py) excludes this handle so we never re-ingest
our own quote-posts.

Required env: BLUESKY_HANDLE, BLUESKY_PASSWORD, SUPABASE_URL, SUPABASE_KEY.
Schema requirement: phd_positions.reposted_to_bluesky_at (see migration 006).

Usage:
    python scripts/repost_to_bluesky.py                 # repost up to REPOST_LIMIT
    python scripts/repost_to_bluesky.py --dry-run       # show what it would post
    python scripts/repost_to_bluesky.py --limit 1       # cap this run
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Ensure the repo root is importable when run as `python scripts/repost_to_bluesky.py`
# (Python puts scripts/ on sys.path, not the repo root, so `import src...` fails otherwise).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

# How many rows to pull from Supabase before aggregator filtering (we over-fetch
# because aggregators are dropped in Python, not in the query).
FETCH_LIMIT = 100
# Cap on quote-posts per run so a backlog never floods the feed.
REPOST_LIMIT = 20
# Seconds between posts (matches the cadence convention in src/sources/bluesky.py).
REQUEST_DELAY = 0.5

_AGGREGATORS_FILE = Path(__file__).resolve().parent.parent / "docs" / "aggregators.json"
try:
    AGGREGATORS = set(json.loads(_AGGREGATORS_FILE.read_text(encoding="utf-8")).get("handles", []))
except (FileNotFoundError, json.JSONDecodeError):
    AGGREGATORS = set()


def sanitize_tag(value: str) -> str:
    """Turn a label into a valid single-word hashtag token (no leading '#').

    "Computer Science" -> "ComputerScience", "PhD Student" -> "PhDStudent",
    "R&D" -> "RD", "United Kingdom" -> "UnitedKingdom". Returns "" if nothing
    usable remains.
    """
    return re.sub(r"[^A-Za-z0-9]", "", value or "")


def build_tags(position: dict) -> list[str]:
    """Build the ordered, de-duplicated list of hashtag tokens for a position.

    Order: level (position_type) -> country -> subjects (disciplines).
    Drops empty/"Unknown" country and any label that sanitizes to "".
    """
    tokens: list[str] = []

    def add(label: str):
        tok = sanitize_tag(label)
        if tok and tok not in tokens:
            tokens.append(tok)

    for level in position.get("position_type") or []:
        add(level)

    country = position.get("country") or ""
    if country and country != "Unknown":
        add(country)

    for subject in position.get("disciplines") or []:
        add(subject)

    return tokens


def select_candidates(rows: list[dict], aggregators: set[str], limit: int) -> list[dict]:
    """Filter fetched rows to non-aggregator positions, capped at `limit`.

    Pure function (no network) so it can be unit-tested. Assumes `rows` are
    already verified + canonical + un-reposted (enforced by the query).
    """
    out = []
    for row in rows:
        if (row.get("user_handle") or "") in aggregators:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def fetch_candidates(client, limit: int = FETCH_LIMIT) -> list[dict]:
    """Pull un-reposted, verified, canonical positions (oldest first)."""
    result = (
        client.table("phd_positions")
        .select("uri, message, url, user_handle, created_at, disciplines, country, position_type")
        .eq("is_verified_job", True)
        .is_("duplicate_of", "null")
        .is_("reposted_to_bluesky_at", "null")
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data or []


def mark_reposted(client, uri: str, timestamp: str) -> None:
    """Set reposted_to_bluesky_at on a single URI so it isn't reposted again."""
    client.table("phd_positions").update(
        {"reposted_to_bluesky_at": timestamp}
    ).eq("uri", uri).execute()


def _build_text(tags: list[str]):
    """Build an atproto TextBuilder with one clickable hashtag per tag."""
    from atproto import client_utils

    tb = client_utils.TextBuilder()
    for i, tok in enumerate(tags):
        if i:
            tb.text(" ")
        tb.tag(f"#{tok}", tok)
    return tb


def _resolve_strong_ref(client, uri: str):
    """Return (uri, cid) for a post, or None if it can't be resolved (deleted)."""
    resp = client.get_posts([uri])
    posts = getattr(resp, "posts", None) or []
    if not posts:
        return None
    cid = getattr(posts[0], "cid", None)
    if not cid:
        return None
    return uri, cid


def repost_position(client, position: dict, dry_run: bool = False) -> str | None:
    """Quote-post one position. Returns the tag text on success, None on skip.

    Skips (returns None) when the original can't be resolved (e.g. deleted) or
    there are no usable tags. Raises on unexpected API errors so the caller can
    decide whether to stop.
    """
    uri = position["uri"]
    tags = build_tags(position)
    tag_text = " ".join(f"#{t}" for t in tags)

    if dry_run:
        print(f"[dry-run] {uri}\n          {tag_text or '(no tags)'}")
        return tag_text

    ref = _resolve_strong_ref(client, uri)
    if ref is None:
        print(f"  skip (original unavailable): {uri}")
        return None

    from atproto import models

    embed = models.AppBskyEmbedRecord.Main(
        record=models.ComAtprotoRepoStrongRef.Main(uri=ref[0], cid=ref[1])
    )
    client.send_post(_build_text(tags), embed=embed)
    return tag_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Quote-post positions to Bluesky.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be posted; post nothing, mark nothing.")
    parser.add_argument("--limit", type=int, default=REPOST_LIMIT,
                        help=f"Max positions to repost this run (default {REPOST_LIMIT}).")
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        print("SUPABASE_URL/SUPABASE_KEY unset — cannot run repost job")
        return 1

    from supabase import create_client
    supabase = create_client(supabase_url, supabase_key)

    rows = fetch_candidates(supabase)
    candidates = select_candidates(rows, AGGREGATORS, args.limit)
    if not candidates:
        print("No un-reposted non-aggregator positions — nothing to do")
        return 0

    if args.dry_run:
        print(f"[dry-run] {len(candidates)} position(s) would be reposted:")
        for pos in candidates:
            repost_position(None, pos, dry_run=True)
        return 0

    if not os.environ.get("BLUESKY_HANDLE") or not os.environ.get("BLUESKY_PASSWORD"):
        print("BLUESKY_HANDLE/BLUESKY_PASSWORD unset — cannot post")
        return 1

    from src.sources.bluesky import get_client
    client = get_client()

    reposted = 0
    for pos in candidates:
        try:
            result = repost_position(client, pos, dry_run=False)
        except Exception as e:  # noqa: BLE001 — leave row unmarked, retry next run
            print(f"  error reposting {pos['uri']}: {e}")
            continue

        timestamp = datetime.now(timezone.utc).isoformat()
        # Mark on success AND on skip (unavailable original) so we don't retry a
        # deleted post forever.
        mark_reposted(supabase, pos["uri"], timestamp)
        if result is not None:
            reposted += 1
            print(f"  reposted: {pos['uri']}  [{result}]")
        time.sleep(REQUEST_DELAY)

    print(f"Reposted {reposted} position(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
