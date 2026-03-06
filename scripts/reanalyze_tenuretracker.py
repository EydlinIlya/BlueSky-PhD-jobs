#!/usr/bin/env python3
"""One-time script to reanalyze tenuretracker posts and pair root+reply posts.

tenuretracker.bsky.social posts job announcements as 2-post threads:
  1. Root post: brief "X is hiring" announcement
  2. Reply: detailed description (TT replies to their own root)

This script finds all such pairs in the DB / a backup JSON, proposes
combined messages, and optionally applies changes (update root message +
mark reply as duplicate).

Usage:
    # Dry-run against backup JSON
    python scripts/reanalyze_tenuretracker.py \\
        --input backup_phd_positions_20260225_172821.json \\
        --output tenuretracker_analysis.json

    # Read from DB, write analysis only
    python scripts/reanalyze_tenuretracker.py \\
        --from-db --output tenuretracker_analysis.json

    # Apply changes to DB (review the output JSON first!)
    python scripts/reanalyze_tenuretracker.py \\
        --from-db --output tenuretracker_analysis.json --apply
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Allow running from project root without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.logger import setup_logger
from src.sources.bluesky import TENURETRACKER_HANDLE, REQUEST_DELAY, get_client

logger = setup_logger()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_posts_from_file(input_path: str) -> list[dict]:
    with open(input_path, encoding="utf-8") as f:
        return json.load(f)


def load_posts_from_db() -> list[dict]:
    from src.storage.supabase import SupabaseStorage

    storage = SupabaseStorage()
    all_posts = []
    page_size = 1000
    offset = 0
    while True:
        response = (
            storage.client.table(storage.table)
            .select("*")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not response.data:
            break
        all_posts.extend(response.data)
        if len(response.data) < page_size:
            break
        offset += page_size
    return all_posts


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _post_text(record) -> str:
    return getattr(record, "text", "") or ""


def _post_created_at(record) -> str:
    return getattr(record, "created_at", "") or ""


def build_analysis(posts: list[dict], client, existing_uris: set[str]) -> dict:
    """Identify root+reply pairs among tenuretracker posts.

    For each post in the dataset, fetches the thread (depth=1, parentHeight=1)
    to discover its parent and/or direct replies from tenuretracker.

    Returns:
        Dict with keys: stats, pairs, proposed_changes
    """
    tt_posts = [p for p in posts if p.get("user_handle") == TENURETRACKER_HANDLE]
    logger.info(f"Found {len(tt_posts)} tenuretracker posts to analyze")

    processed_uris: set[str] = set()
    pairs: dict[str, dict] = {}   # root_uri -> pair info
    roots_only: list[str] = []
    replies_only: list[str] = []
    api_errors: list[str] = []

    for i, post in enumerate(tt_posts):
        uri = post["uri"]
        if uri in processed_uris:
            continue

        if i % 20 == 0:
            logger.info(f"  Processing {i}/{len(tt_posts)}...")

        try:
            response = client.app.bsky.feed.get_post_thread(
                {"uri": uri, "depth": 1, "parentHeight": 1}
            )
            thread = response.thread
        except Exception as e:
            logger.warning(f"API error for {uri}: {e}")
            api_errors.append(uri)
            processed_uris.add(uri)
            time.sleep(REQUEST_DELAY)
            continue

        time.sleep(REQUEST_DELAY)

        post_record = getattr(getattr(thread, "post", None), "record", None)
        post_text = _post_text(post_record)

        # ---- Check for a TT parent (this post is a reply) ----------------
        parent_view = getattr(thread, "parent", None)
        parent_post_obj = getattr(parent_view, "post", None) if parent_view else None
        parent_handle = (
            getattr(getattr(parent_post_obj, "author", None), "handle", "")
            if parent_post_obj
            else ""
        )

        if parent_post_obj and parent_handle == TENURETRACKER_HANDLE:
            root_uri = getattr(parent_post_obj, "uri", None)
            if root_uri:
                parent_record = getattr(parent_post_obj, "record", None)
                root_text = _post_text(parent_record)
                combined = root_text + "\n\n---\n" + post_text

                processed_uris.add(uri)
                processed_uris.add(root_uri)

                if root_uri not in pairs:
                    pairs[root_uri] = {
                        "root_uri": root_uri,
                        "reply_uri": uri,
                        "root_in_db": root_uri in existing_uris,
                        "reply_in_db": uri in existing_uris,
                        "root_message": root_text,
                        "reply_message": post_text,
                        "proposed_combined": combined,
                    }
                continue

        # ---- Check for a TT reply (this post is the root) ----------------
        replies = getattr(thread, "replies", None) or []
        tt_reply_view = None
        for reply_view in replies:
            reply_post_obj = getattr(reply_view, "post", None)
            if not reply_post_obj:
                continue
            if (
                getattr(getattr(reply_post_obj, "author", None), "handle", "")
                == TENURETRACKER_HANDLE
            ):
                tt_reply_view = reply_view
                break

        processed_uris.add(uri)

        if tt_reply_view:
            reply_post_obj = tt_reply_view.post
            reply_uri = reply_post_obj.uri
            reply_record = getattr(reply_post_obj, "record", None)
            reply_text = _post_text(reply_record)
            combined = post_text + "\n\n---\n" + reply_text

            processed_uris.add(reply_uri)

            if uri not in pairs:
                pairs[uri] = {
                    "root_uri": uri,
                    "reply_uri": reply_uri,
                    "root_in_db": uri in existing_uris,
                    "reply_in_db": reply_uri in existing_uris,
                    "root_message": post_text,
                    "reply_message": reply_text,
                    "proposed_combined": combined,
                }
        else:
            # Standalone
            if parent_view and parent_handle != TENURETRACKER_HANDLE:
                replies_only.append(uri)
            else:
                roots_only.append(uri)

    stats = {
        "total_tenuretracker": len(tt_posts),
        "pairs_found": len(pairs),
        "roots_only": len(roots_only),
        "replies_only": len(replies_only),
        "api_errors": len(api_errors),
    }

    # Build proposed changes
    proposed_changes: dict[str, list] = {
        "update_message": [],
        "mark_duplicate": [],
        "reclassify": [],
    }
    for root_uri, pair in pairs.items():
        if pair["root_in_db"]:
            proposed_changes["update_message"].append(
                {
                    "uri": root_uri,
                    "new_message": pair["proposed_combined"],
                    "reason": "add reply text",
                }
            )
            proposed_changes["reclassify"].append(
                {
                    "uri": root_uri,
                    "text_to_classify": pair["proposed_combined"],
                    "reason": "merged root+reply — reclassify with full context",
                }
            )
        if pair["reply_in_db"]:
            proposed_changes["mark_duplicate"].append(
                {
                    "uri": pair["reply_uri"],
                    "duplicate_of": root_uri,
                }
            )

    return {
        "stats": stats,
        "pairs": list(pairs.values()),
        "proposed_changes": proposed_changes,
    }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_changes(analysis: dict, storage) -> None:
    changes = analysis["proposed_changes"]

    updates = changes.get("update_message", [])
    logger.info(f"Applying {len(updates)} message updates...")
    for upd in updates:
        logger.info(f"  Updating {upd['uri']}")
        storage.update_post_message(upd["uri"], upd["new_message"])

    dups = changes.get("mark_duplicate", [])
    logger.info(f"Marking {len(dups)} duplicates...")
    for dup in dups:
        logger.info(f"  {dup['uri']} -> duplicate of {dup['duplicate_of']}")
        storage.mark_duplicate(dup["uri"], dup["duplicate_of"])

    reclassify = changes.get("reclassify", [])
    if reclassify:
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            logger.warning("NVIDIA_API_KEY not set — skipping reclassification of %d posts", len(reclassify))
        else:
            from src.llm.nvidia import NvidiaProvider
            from src.llm.classifier import JobClassifier
            from src.llm.config import DEFAULT_MODEL
            classifier = JobClassifier(NvidiaProvider(api_key, DEFAULT_MODEL))
            logger.info(f"Reclassifying {len(reclassify)} posts...")
            for i, entry in enumerate(reclassify):
                logger.info(f"  [{i + 1}/{len(reclassify)}] {entry['uri']}")
                try:
                    meta = classifier.get_metadata(entry["text_to_classify"])
                    storage.update_post_classification(
                        entry["uri"],
                        meta["disciplines"],
                        meta["country"],
                        meta["position_type"],
                    )
                    logger.info(f"    -> disciplines={meta['disciplines']} country={meta['country']} type={meta['position_type']}")
                except Exception as e:
                    logger.error(f"    Reclassification failed for {entry['uri']}: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reanalyze tenuretracker posts and pair root+reply threads"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Path to JSON backup file")
    input_group.add_argument(
        "--from-db", action="store_true", help="Load posts from Supabase DB"
    )
    parser.add_argument("--output", required=True, help="Path to write analysis JSON")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply proposed changes to DB (update messages, mark duplicates, reclassify)",
    )
    args = parser.parse_args()

    # Load posts
    if args.input:
        posts = load_posts_from_file(args.input)
        logger.info(f"Loaded {len(posts)} posts from {args.input}")
        existing_uris = {p["uri"] for p in posts}
    else:
        posts = load_posts_from_db()
        logger.info(f"Loaded {len(posts)} posts from DB")
        existing_uris = {p["uri"] for p in posts}

    # Connect to Bluesky
    logger.info("Authenticating with Bluesky...")
    client = get_client()

    # Build analysis
    logger.info("Analyzing tenuretracker posts (this makes many API calls)...")
    analysis = build_analysis(posts, client, existing_uris)

    # Write output
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Analysis written to {args.output}")

    # Print summary
    stats = analysis["stats"]
    logger.info("=" * 50)
    logger.info(f"Total tenuretracker posts : {stats['total_tenuretracker']}")
    logger.info(f"Pairs found               : {stats['pairs_found']}")
    logger.info(f"Roots only (no reply)     : {stats['roots_only']}")
    logger.info(f"Replies only (non-TT root): {stats['replies_only']}")
    logger.info(f"API errors                : {stats['api_errors']}")
    logger.info(
        f"Proposed message updates  : {len(analysis['proposed_changes']['update_message'])}"
    )
    logger.info(
        f"Proposed duplicate marks  : {len(analysis['proposed_changes']['mark_duplicate'])}"
    )
    logger.info(
        f"Proposed reclassifications: {len(analysis['proposed_changes']['reclassify'])}"
    )
    logger.info("=" * 50)

    if args.apply:
        from src.storage.supabase import SupabaseStorage

        storage = SupabaseStorage()
        logger.info("Applying changes to DB...")
        apply_changes(analysis, storage)
        logger.info("Done.")
    else:
        logger.info("Dry-run complete. Pass --apply to write changes to DB.")


if __name__ == "__main__":
    main()
