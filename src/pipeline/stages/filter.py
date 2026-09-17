"""Stage 2: LLM filtering and metadata extraction on staging rows.

Tracks completion *per row* via the filter_completed column so a mid-run
crash can resume from the exact post where it left off.

- Pending rows run through classifier.classify_post(); if no classifier
  (--no-llm), all are marked is_verified_job=True.
"""

from datetime import datetime, timezone

from src.llm.base import LLMUnavailableError
from src.logger import setup_logger

logger = setup_logger()


def run(run_date, storage, classifier) -> None:
    """Apply LLM filtering to unfiltered staging rows.

    Drains the whole pending queue: unfiltered rows from ANY run_date are
    classified, so leftovers from a previous day's crashed run get processed
    here. Each write-back is keyed by the row's own run_date.
    """

    # Drain every pending row, including any legacy row left by an interrupted
    # run before the current Bluesky-only source policy took effect.
    rows = storage.get_staging_unfiltered()

    if not rows:
        logger.info("No unfiltered rows to process")
    elif classifier is None:
        # --no-llm: accept pending posts without classification
        logger.info(f"No LLM — marking {len(rows)} rows as verified")
        for row in rows:
            storage.update_staging_filter(row["run_date"], row["uri"], {
                "is_verified_job": True,
                "disciplines": row.get("disciplines") or [],
                "country": row.get("country"),
                "position_type": row.get("position_type") or [],
                "job_title": row.get("job_title"),
                "hiring_organization": row.get("hiring_organization"),
                "application_url": row.get("application_url"),
                "application_deadline": row.get("application_deadline"),
                "location_text": row.get("location_text"),
                "seo_enriched_at": row.get("seo_enriched_at"),
            })
    else:
        logger.info(f"Classifying {len(rows)} rows...")
        for i, row in enumerate(rows, 1):
            raw_text = row.get("raw_text") or row.get("message", "")
            metadata_text = row.get("metadata_text") or raw_text
            try:
                result = classifier.classify_post(raw_text, metadata_text=metadata_text)
                if result.get("is_verified_job"):
                    result["seo_enriched_at"] = datetime.now(timezone.utc).isoformat()
            except LLMUnavailableError as e:
                logger.error(
                    f"LLM unavailable after {i - 1}/{len(rows)} rows classified. "
                    f"Pipeline will resume from this row on next run. Error: {e}"
                )
                raise
            storage.update_staging_filter(row["run_date"], row["uri"], result)
            if i % 10 == 0:
                logger.info(f"  Classified {i}/{len(rows)}")

    verified_count = len(storage.get_staging_verified())

    storage.update_run(
        run_date,
        filter_completed_at=datetime.now(timezone.utc).isoformat(),
        verified_count=verified_count,
    )
    logger.info(f"Stage 2 (Filter) complete: {verified_count} verified posts")
