"""Stage 1: Fetch posts from all enabled sources into phd_positions_staging."""

from datetime import datetime, timezone

from src.logger import setup_logger
from src.sources import BlueskySource, ScholarshipDBSource

logger = setup_logger()


def _bio_prefix(message: str) -> str:
    """Extract the '[Bio: ...]\\n\\n' prefix from a post message, if present."""
    if message.startswith("[Bio:"):
        end = message.find("]\n\n")
        if end >= 0:
            return message[: end + 3]
    return ""


def process_tenuretracker_posts(
    posts: list[dict],
    existing_uris: set[str],
    client,
    storage,
) -> tuple[list[dict], list[dict]]:
    """Merge tenuretracker root+reply pairs into a single canonical post.

    tenuretracker.bsky.social always posts a brief root then replies with
    full details. This function:
      - Detects root posts and fetches their reply (if any).
      - Detects reply posts and fetches their parent root.
      - Combines both into one post keyed by the root URI.
      - Updates existing DB entries when only one half is new.

    Args:
        posts: All newly-fetched posts (as dicts) for this run.
        existing_uris: URIs already in phd_positions.
        client: Authenticated atproto Client.
        storage: SupabaseStorage instance (for update_post_message / mark_duplicate).

    Returns:
        (merged_posts, db_updates) where db_updates is a list of
        {"old_uri": ..., "new_canonical_uri": ...} entries for existing
        DB rows that should be marked as duplicates.
    """
    from src.sources.bluesky import (
        TENURETRACKER_HANDLE,
        _fetch_tt_parent,
        _fetch_tt_reply,
        uri_to_url,
    )

    tt_posts = [p for p in posts if p.get("user_handle") == TENURETRACKER_HANDLE]
    other_posts = [p for p in posts if p.get("user_handle") != TENURETRACKER_HANDLE]

    seen_tt_uris: set[str] = set()
    result_posts: list[dict] = []
    db_updates: list[dict] = []

    for post in tt_posts:
        uri = post["uri"]
        if uri in seen_tt_uris:
            continue

        reply_parent_uri = post.get("reply_parent_uri")

        if reply_parent_uri:
            # ----------------------------------------------------------------
            # This post is a REPLY — try to find TT's root post
            # ----------------------------------------------------------------
            parent = _fetch_tt_parent(client, uri)
            if parent and parent["handle"] == TENURETRACKER_HANDLE:
                root_uri = parent["uri"]
                reply_raw = post.get("raw_text") or post.get("message", "")
                combined_raw = parent["text"] + "\n\n---\n" + reply_raw

                seen_tt_uris.add(uri)
                seen_tt_uris.add(root_uri)

                if root_uri in existing_uris:
                    # Root already in DB — enrich it with the reply text
                    logger.info(
                        f"[TT merge] Updating existing root {root_uri} with reply text"
                    )
                    storage.update_post_message(root_uri, combined_raw)
                    # If this reply is also already in DB, mark it as duplicate
                    if uri in existing_uris:
                        db_updates.append(
                            {"old_uri": uri, "new_canonical_uri": root_uri}
                        )
                    # Don't emit reply as a new staging row
                else:
                    # Root not yet in DB — emit a merged post under the root URI
                    logger.info(
                        f"[TT merge] Emitting merged root {root_uri} (reply was {uri})"
                    )
                    new_post = dict(post)
                    new_post["uri"] = root_uri
                    new_post["raw_text"] = combined_raw
                    new_post["message"] = combined_raw
                    new_post["metadata_text"] = combined_raw
                    new_post["url"] = uri_to_url(root_uri, TENURETRACKER_HANDLE)
                    new_post["created_at"] = parent["created_at"]
                    new_post["reply_parent_uri"] = None
                    result_posts.append(new_post)
            else:
                # Parent not from TT or fetch failed — emit reply as-is
                seen_tt_uris.add(uri)
                result_posts.append(post)

        else:
            # ----------------------------------------------------------------
            # This post is a ROOT — try to find TT's reply
            # ----------------------------------------------------------------
            reply = _fetch_tt_reply(client, uri)
            if reply:
                reply_uri = reply["uri"]
                root_raw = post.get("raw_text") or post.get("message", "")
                combined_raw = root_raw + "\n\n---\n" + reply["text"]

                seen_tt_uris.add(uri)
                seen_tt_uris.add(reply_uri)

                logger.info(
                    f"[TT merge] Root {uri} combined with reply {reply_uri}"
                )

                new_post = dict(post)
                bio = _bio_prefix(post.get("message", ""))
                new_post["raw_text"] = combined_raw
                new_post["message"] = bio + combined_raw
                new_post["metadata_text"] = bio + combined_raw
                new_post["reply_parent_uri"] = None

                if reply_uri in existing_uris:
                    # Reply already in DB — mark it as duplicate of root
                    db_updates.append(
                        {"old_uri": reply_uri, "new_canonical_uri": uri}
                    )

                result_posts.append(new_post)
            else:
                # No TT reply found — emit root as-is
                seen_tt_uris.add(uri)
                result_posts.append(post)

    return other_posts + result_posts, db_updates


def run(run_date, sources: list[str], storage, args) -> None:
    """Fetch posts from all enabled sources and insert into staging.

    Uses Supabase as the source of truth for sync state (last timestamp and
    existing URIs). Inserts raw Post dicts into phd_positions_staging, then
    marks fetch_completed_at on the pipeline_runs row.
    """
    since_timestamp = None
    existing_uris: set[str] = set()

    if not args.full_sync:
        since_timestamp = storage.get_last_timestamp()
        existing_uris = storage.get_existing_uris()
        if since_timestamp:
            logger.info(f"Incremental sync from {since_timestamp}")
        else:
            logger.info("Full sync (no previous state)")
    else:
        logger.info("Full sync (--full-sync specified)")

    all_posts: list[dict] = []

    for source_name in sources:
        logger.info(f"\n{'='*40}")
        logger.info(f"Fetching from {source_name}")
        logger.info("=" * 40)

        try:
            if source_name == "bluesky":
                source = BlueskySource(
                    queries=args.query,
                    limit=args.limit,
                )
            elif source_name == "scholarshipdb":
                source = ScholarshipDBSource(
                    max_pages=args.scholarshipdb_pages,
                )
            else:
                logger.warning(f"Unknown source: {source_name}")
                continue

            posts, _ = source.fetch_posts(
                since_timestamp=since_timestamp,
                existing_uris=existing_uris,
            )
            # Add source field for posts that may not set it
            post_dicts = []
            for p in posts:
                d = p.to_dict()
                d.setdefault("source", source_name)
                post_dicts.append(d)

            logger.info(f"Fetched {len(post_dicts)} posts from {source_name}")
            all_posts.extend(post_dicts)

        except Exception as e:
            logger.error(f"Error fetching from {source_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Merge tenuretracker root+reply pairs before inserting into staging
    if "bluesky" in sources:
        try:
            from src.sources.bluesky import get_client
            tt_client = get_client()
            all_posts, db_updates = process_tenuretracker_posts(
                all_posts, existing_uris, tt_client, storage
            )
            logger.info(
                f"[TT merge] After merging: {len(all_posts)} posts, "
                f"{len(db_updates)} DB duplicate updates"
            )
            for upd in db_updates:
                storage.mark_duplicate(upd["old_uri"], upd["new_canonical_uri"])
        except Exception as e:
            logger.error(f"[TT merge] Failed: {e}")
            import traceback
            traceback.print_exc()

    if all_posts:
        storage.insert_staging(run_date, all_posts)
        logger.info(f"Inserted {len(all_posts)} posts into staging")

    storage.update_run(
        run_date,
        fetch_completed_at=datetime.now(timezone.utc).isoformat(),
        raw_count=len(all_posts),
    )
    logger.info(f"Stage 1 (Fetch) complete: {len(all_posts)} raw posts")
