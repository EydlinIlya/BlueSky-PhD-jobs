"""Stage 4: Publish staging rows to phd_positions and clean up.

Reads all staging rows (verified + non-verified, canonical + duplicates),
upserts them into phd_positions, deletes staging rows, and marks
publish_completed_at on the pipeline_runs row.

Telegram posting is no longer wired in here — see scripts/post_to_telegram.py
which runs as a separate cron job querying un-posted rows by
posted_to_telegram_at IS NULL. This decouples ingest cadence from channel
cadence.
"""

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

    # Drain the entire staging table (all run_dates), so leftovers from a
    # previous day's crashed run are published here too.
    all_rows = storage.get_staging_all()

    if not all_rows:
        logger.info("No staging posts to publish")
        storage.delete_run()
        return

    logger.info(f"Publishing {len(all_rows)} posts to phd_positions...")

    posts_to_save = [_staging_to_save_dict(row) for row in all_rows]

    saved_count = storage.save_posts(posts_to_save)
    logger.info(f"Saved {saved_count} posts to phd_positions")

    # Clean up: clear the ENTIRE staging table and ALL pipeline_runs checkpoints.
    # After a successful drain-all publish nothing is in flight, so this also
    # removes any stale rows from previously crashed days. Deleting the
    # checkpoints lets subsequent runs on the same calendar day start fresh
    # (each fetches only posts newer than the last publish).
    storage.delete_staging()
    storage.delete_run()
    logger.info(f"Stage 4 (Publish) complete: {saved_count} posts published")
