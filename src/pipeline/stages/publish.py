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
        "job_title": row.get("job_title"),
        "hiring_organization": row.get("hiring_organization"),
        "application_url": row.get("application_url"),
        "application_deadline": row.get("application_deadline"),
        "location_text": row.get("location_text"),
        "seo_enriched_at": row.get("seo_enriched_at"),
    }
    if row.get("quoted_uri"):
        post["quoted_uri"] = row["quoted_uri"]
    if row.get("reply_parent_uri"):
        post["reply_parent_uri"] = row["reply_parent_uri"]
    return post


def _row_recency_key(row: dict) -> tuple[str, str, int]:
    """Return a deterministic recency key for repeated staging URIs."""
    return (
        str(row.get("run_date") or ""),
        str(row.get("staged_at") or ""),
        int(row.get("id") or 0),
    )


def _deduplicate_staging_rows(rows: list[dict]) -> list[dict]:
    """Keep only the newest staging row for each canonical URI.

    The staging uniqueness constraint is ``(run_date, uri)``, so a drain-all
    publish can contain the same URI from multiple interrupted run dates.
    PostgreSQL rejects such a multi-row upsert because one statement cannot
    update the same constrained row twice.
    """
    by_uri: dict[str, dict] = {}
    for row in rows:
        uri = row["uri"]
        current = by_uri.get(uri)
        if current is None or _row_recency_key(row) > _row_recency_key(current):
            by_uri[uri] = row
    return list(by_uri.values())


def run(run_date, storage, args) -> None:
    """Publish all staging rows to phd_positions, clean up, post to Telegram."""

    # Drain the entire staging table (all run_dates), so leftovers from a
    # previous day's crashed run are published here too.
    all_rows = storage.get_staging_all()

    if not all_rows:
        logger.info("No staging posts to publish")
        storage.delete_run()
        return

    unique_rows = _deduplicate_staging_rows(all_rows)
    duplicate_count = len(all_rows) - len(unique_rows)
    if duplicate_count:
        logger.warning(
            "Collapsed %s repeated staging rows before publish", duplicate_count
        )

    logger.info(f"Publishing {len(unique_rows)} posts to phd_positions...")

    posts_to_save = [_staging_to_save_dict(row) for row in unique_rows]

    saved_count = storage.save_posts(posts_to_save)
    logger.info(f"Saved {saved_count} posts to phd_positions")

    if saved_count != len(posts_to_save):
        raise RuntimeError(
            f"Publish incomplete: expected {len(posts_to_save)} saved rows, "
            f"received {saved_count}; staging was preserved for retry"
        )

    # Clean up: clear the ENTIRE staging table and ALL pipeline_runs checkpoints.
    # After a successful drain-all publish nothing is in flight, so this also
    # removes any stale rows from previously crashed days. Deleting the
    # checkpoints lets subsequent runs on the same calendar day start fresh
    # (each fetches only posts newer than the last publish).
    storage.delete_staging()
    storage.delete_run()
    logger.info(f"Stage 4 (Publish) complete: {saved_count} posts published")
