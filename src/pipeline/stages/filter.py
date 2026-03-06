"""Stage 2: LLM filtering and metadata extraction on staging rows.

Tracks completion *per row* via the filter_completed column so a mid-run
crash can resume from the exact post where it left off.

- ScholarshipDB rows: already classified — marked filter_completed=True immediately.
- Bluesky rows: run through classifier.classify_post(); if no classifier
  (--no-llm), all are marked is_verified_job=True.
"""

from datetime import datetime, timezone

from src.llm.base import LLMUnavailableError
from src.logger import setup_logger

logger = setup_logger()


def run(run_date, storage, classifier) -> None:
    """Apply LLM filtering to unfiltered staging rows."""

    # Auto-complete ScholarshipDB rows (pre-verified, no LLM needed)
    scholarshipdb_rows = storage.get_staging_unfiltered(run_date, source="scholarshipdb")
    for row in scholarshipdb_rows:
        storage.update_staging_filter(run_date, row["uri"], {
            "is_verified_job": True,
            "disciplines": row.get("disciplines"),
            "country": row.get("country"),
            "position_type": row.get("position_type"),
        })
    if scholarshipdb_rows:
        logger.info(f"Auto-completed {len(scholarshipdb_rows)} ScholarshipDB rows")

    # Process Bluesky rows
    bluesky_rows = storage.get_staging_unfiltered(run_date, source="bluesky")

    if not bluesky_rows:
        logger.info("No unfiltered Bluesky rows to process")
    elif classifier is None:
        # --no-llm: accept all Bluesky posts without classification
        logger.info(f"No LLM — marking {len(bluesky_rows)} Bluesky rows as verified")
        for row in bluesky_rows:
            storage.update_staging_filter(run_date, row["uri"], {
                "is_verified_job": True,
                "disciplines": row.get("disciplines") or [],
                "country": row.get("country"),
                "position_type": row.get("position_type") or [],
            })
    else:
        logger.info(f"Classifying {len(bluesky_rows)} Bluesky rows...")
        for i, row in enumerate(bluesky_rows, 1):
            raw_text = row.get("raw_text") or row.get("message", "")
            metadata_text = row.get("metadata_text") or raw_text
            try:
                result = classifier.classify_post(raw_text, metadata_text=metadata_text)
            except LLMUnavailableError as e:
                logger.error(
                    f"LLM unavailable after {i - 1}/{len(bluesky_rows)} rows classified. "
                    f"Pipeline will resume from this row on next run. Error: {e}"
                )
                raise
            storage.update_staging_filter(run_date, row["uri"], result)
            if i % 10 == 0:
                logger.info(f"  Classified {i}/{len(bluesky_rows)}")

    verified_count = len(storage.get_staging_verified(run_date))

    storage.update_run(
        run_date,
        filter_completed_at=datetime.now(timezone.utc).isoformat(),
        verified_count=verified_count,
    )
    logger.info(f"Stage 2 (Filter) complete: {verified_count} verified posts")
