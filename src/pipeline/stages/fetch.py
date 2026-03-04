"""Stage 1: Fetch posts from all enabled sources into phd_positions_staging."""

from datetime import datetime, timezone

from src.logger import setup_logger
from src.sources import BlueskySource, ScholarshipDBSource

logger = setup_logger()


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

    if all_posts:
        storage.insert_staging(run_date, all_posts)
        logger.info(f"Inserted {len(all_posts)} posts into staging")

    storage.update_run(
        run_date,
        fetch_completed_at=datetime.now(timezone.utc).isoformat(),
        raw_count=len(all_posts),
    )
    logger.info(f"Stage 1 (Fetch) complete: {len(all_posts)} raw posts")
