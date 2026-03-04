"""Stage 3: Deduplication of verified staging posts against existing DB posts.

Ports the logic from src/dedup.py, working on staging rows instead of an
in-memory list. On crash/restart, dedup reruns from scratch on today's
verified posts (acceptable — the batch is small and TF-IDF is fast).
"""

from datetime import datetime, timezone

from src.dedup import deduplicate_new_posts
from src.logger import setup_logger

logger = setup_logger()


def run(run_date, storage, llm) -> None:
    """Deduplicate verified staging posts against existing canonical DB posts."""

    verified_rows = storage.get_staging_verified(run_date)

    if not verified_rows:
        logger.info("No verified staging posts to dedup")
        storage.update_run(
            run_date,
            dedup_completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return

    logger.info(f"Deduplicating {len(verified_rows)} verified staging posts...")

    # Convert staging rows to the dict format expected by deduplicate_new_posts
    posts_for_dedup = []
    for row in verified_rows:
        post = {
            "uri": row["uri"],
            "message": row.get("message", ""),
            "url": row.get("url", ""),
            "user": row.get("user_handle", ""),
            "created": row.get("created_at", ""),
            "source": row.get("source", ""),
            "disciplines": row.get("disciplines"),
            "country": row.get("country"),
            "position_type": row.get("position_type"),
            "is_verified_job": row.get("is_verified_job"),
            "quoted_uri": row.get("quoted_uri"),
            "reply_parent_uri": row.get("reply_parent_uri"),
        }
        posts_for_dedup.append(post)

    posts_with_dedup, db_updates = deduplicate_new_posts(
        posts_for_dedup,
        storage,
        llm,
    )

    # Write duplicate marks back to staging rows
    for post in posts_with_dedup:
        if post.get("duplicate_of"):
            storage.update_staging_dedup(run_date, post["uri"], post["duplicate_of"])

    # Mark existing DB posts as duplicates (older posts that were superseded)
    if db_updates:
        storage.mark_duplicates_batch(db_updates)
        logger.info(f"Marked {len(db_updates)} existing DB posts as duplicates")

    storage.update_run(
        run_date,
        dedup_completed_at=datetime.now(timezone.utc).isoformat(),
    )
    logger.info("Stage 3 (Dedup) complete")
