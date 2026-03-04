"""Stage 4: Publish staging rows to phd_positions and clean up.

Reads all staging rows (verified + non-verified, canonical + duplicates),
upserts them into phd_positions, posts to Telegram, deletes staging rows,
and marks publish_completed_at on the pipeline_runs row.
"""

import sys

from src.logger import setup_logger

logger = setup_logger()


def _staging_to_save_dict(row: dict) -> dict:
    """Convert a staging row to the dict format expected by save_posts."""
    post = {
        "uri": row["uri"],
        "message": row.get("message", ""),
        "url": row.get("url", ""),
        "user": row.get("user_handle", ""),
        "created": row.get("created_at", ""),
        "disciplines": row.get("disciplines"),
        "country": row.get("country"),
        "position_type": row.get("position_type"),
        "is_verified_job": row.get("is_verified_job"),
        "duplicate_of": row.get("duplicate_of"),
    }
    if row.get("quoted_uri"):
        post["quoted_uri"] = row["quoted_uri"]
    if row.get("reply_parent_uri"):
        post["reply_parent_uri"] = row["reply_parent_uri"]
    return post


def run(run_date, storage, args) -> None:
    """Publish all staging rows to phd_positions, clean up, post to Telegram."""

    all_rows = storage.get_staging_all(run_date)

    if not all_rows:
        logger.info("No staging posts to publish")
        storage.delete_run(run_date)
        return

    logger.info(f"Publishing {len(all_rows)} posts to phd_positions...")

    posts_to_save = [_staging_to_save_dict(row) for row in all_rows]

    saved_count = storage.save_posts(posts_to_save)
    logger.info(f"Saved {saved_count} posts to phd_positions")

    # Post Biology + CS positions to Telegram
    from scripts.post_to_telegram import post_batch_to_telegram
    if not post_batch_to_telegram(posts_to_save):
        logger.error("Telegram posting failed")
        sys.exit(1)

    # Clean up: remove staging rows and the pipeline_runs checkpoint row.
    # Deleting the checkpoint allows subsequent runs on the same calendar day
    # to start fresh (each fetches only posts newer than the last publish).
    storage.delete_staging(run_date)
    storage.delete_run(run_date)
    logger.info(f"Stage 4 (Publish) complete: {saved_count} posts published")
