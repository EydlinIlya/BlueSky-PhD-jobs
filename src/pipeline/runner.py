"""Pipeline runner: orchestrates the 4 stages with per-stage checkpointing.

A run is identified by run_date (today's date). On each invocation:
- If a stage's completed_at timestamp is already set in pipeline_runs, it is
  skipped entirely.
- This allows targeted restarts after mid-run failures without re-fetching or
  re-filtering from scratch.
"""

from src.logger import setup_logger
from src.pipeline.stages import fetch, filter as filter_stage, dedup, publish

logger = setup_logger()


def run_pipeline(run_date, sources: list[str], storage, classifier, args) -> None:
    """Run the 4-stage pipeline for run_date, skipping completed stages.

    Args:
        run_date: datetime.date for today's run (used as pipeline_runs key)
        sources: List of enabled source names (e.g. ['bluesky', 'scholarshipdb'])
        storage: SupabaseStorage instance
        classifier: JobClassifier instance, or None if --no-llm
        args: Parsed CLI args (query, limit, scholarshipdb_pages, full_sync, …)
    """
    run = storage.get_or_create_run(run_date)
    logger.info(f"Pipeline run {run_date} — current state: {run}")

    if not run.get("fetch_completed_at"):
        logger.info("\n" + "=" * 40)
        logger.info("Stage 1: Fetch")
        logger.info("=" * 40)
        fetch.run(run_date, sources, storage, args)
        run = storage.get_or_create_run(run_date)
    else:
        logger.info("Stage 1 (Fetch): already completed — skipping")

    if not run.get("filter_completed_at"):
        logger.info("\n" + "=" * 40)
        logger.info("Stage 2: Filter")
        logger.info("=" * 40)
        filter_stage.run(run_date, storage, classifier)
        run = storage.get_or_create_run(run_date)
    else:
        logger.info("Stage 2 (Filter): already completed — skipping")

    if not run.get("dedup_completed_at"):
        logger.info("\n" + "=" * 40)
        logger.info("Stage 3: Dedup")
        logger.info("=" * 40)
        llm = classifier.llm if classifier else None
        dedup.run(run_date, storage, llm)
        run = storage.get_or_create_run(run_date)
    else:
        logger.info("Stage 3 (Dedup): already completed — skipping")

    # Stage 4 always runs when stages 1-3 are done.
    # After a successful publish the pipeline_runs row is deleted, so the
    # next invocation on the same calendar day starts a completely fresh run.
    logger.info("\n" + "=" * 40)
    logger.info("Stage 4: Publish")
    logger.info("=" * 40)
    publish.run(run_date, storage, args)

    logger.info(f"\nPipeline for {run_date} complete.")
