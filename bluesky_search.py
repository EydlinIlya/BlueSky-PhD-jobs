"""Search for PhD positions from multiple sources."""

import argparse
import os
import sys
from datetime import date

from src.logger import setup_logger
from src.llm import NvidiaProvider, JobClassifier, LLMUnavailableError
from src.storage import StorageBackend, CSVStorage, SupabaseStorage
from src.sync_state import SyncStateManager
from src.sources import BlueskySource, ScholarshipDBSource

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")

logger = setup_logger()

# Available sources
AVAILABLE_SOURCES = ["bluesky", "scholarshipdb"]


def get_classifier() -> JobClassifier | None:
    """Create a job classifier if API key is available."""
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        return None
    llm = NvidiaProvider(api_key)
    return JobClassifier(llm)


def get_storage(backend: str, output: str) -> StorageBackend:
    """Create a storage backend.

    Args:
        backend: Backend type ("csv" or "supabase")
        output: Output filename (for CSV backend)

    Returns:
        StorageBackend instance
    """
    if backend == "supabase":
        return SupabaseStorage()
    return CSVStorage(output)


def parse_sources(sources_arg: str | None) -> list[str]:
    """Parse and validate the sources argument.

    Args:
        sources_arg: Comma-separated list of sources, or None for default

    Returns:
        List of validated source names
    """
    if not sources_arg:
        return ["bluesky"]  # Default to Bluesky only

    sources = [s.strip().lower() for s in sources_arg.split(",")]
    invalid = [s for s in sources if s not in AVAILABLE_SOURCES]
    if invalid:
        raise ValueError(
            f"Invalid sources: {invalid}. Available: {AVAILABLE_SOURCES}"
        )
    return sources


def main():
    """Run PhD position search."""
    parser = argparse.ArgumentParser(
        description="Search for PhD positions from multiple sources"
    )
    parser.add_argument(
        "-q", "--query",
        action="append",
        help="Search query for Bluesky (can be specified multiple times).",
    )
    parser.add_argument(
        "-o", "--output",
        default="phd_positions.csv",
        help="Output CSV filename (default: phd_positions.csv)",
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=50,
        help="Max results per query for Bluesky (default: 50)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM filtering for Bluesky (uses NVIDIA_API_KEY)",
    )
    parser.add_argument(
        "--full-sync",
        action="store_true",
        help="Ignore last sync state and fetch all posts",
    )
    parser.add_argument(
        "--storage",
        choices=["csv", "supabase"],
        default="csv",
        help="Storage backend (default: csv)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=None,
        help=f"Comma-separated list of sources (default: bluesky). Available: {', '.join(AVAILABLE_SOURCES)}",
    )
    parser.add_argument(
        "--scholarshipdb-pages",
        type=int,
        default=2,
        help="Max pages to fetch per field from ScholarshipDB (default: 2)",
    )
    parser.add_argument(
        "--stage",
        choices=["fetch", "filter", "dedup", "publish", "all"],
        default="all",
        help="Run only up to this pipeline stage (Supabase only, default: all)",
    )
    args = parser.parse_args()

    # Parse sources
    try:
        sources = parse_sources(args.sources)
        logger.info(f"Using sources: {', '.join(sources)}")
    except ValueError as e:
        logger.error(str(e))
        return

    # Set up storage backend
    try:
        storage = get_storage(args.storage, args.output)
        logger.info(f"Using {args.storage} storage backend")
    except ValueError as e:
        logger.error(f"Storage setup failed: {e}")
        return

    # Set up classifier if LLM is enabled
    classifier = None
    if not args.no_llm:
        classifier = get_classifier()
        if classifier:
            logger.info("LLM filtering enabled (Llama)")
        else:
            logger.info("LLM filtering disabled (no NVIDIA_API_KEY)")

    # --- Supabase: use 4-stage persistent pipeline ---
    if args.storage == "supabase":
        from src.pipeline.runner import run_pipeline
        run_pipeline(
            run_date=date.today(),
            sources=sources,
            storage=storage,
            classifier=classifier,
            args=args,
        )
        return

    # --- CSV: simplified single-pass flow ---
    sync_manager = SyncStateManager()
    all_results = []
    all_sources_updated = {}

    for source_name in sources:
        logger.info(f"\n{'='*40}")
        logger.info(f"Fetching from {source_name}")
        logger.info("=" * 40)

        since_timestamp = None
        existing_uris: set = set()

        if not args.full_sync:
            source_state = sync_manager.get_source_state(source_name)
            since_timestamp = source_state.get("last_timestamp")
            existing_uris = source_state.get("seen_uris", set())
            if since_timestamp:
                logger.info(
                    f"Incremental sync from {since_timestamp} "
                    f"({len(existing_uris)} existing posts)"
                )
            else:
                logger.info("Full sync (no previous state)")
        else:
            logger.info("Full sync (--full-sync specified)")

        try:
            if source_name == "bluesky":
                source = BlueskySource(queries=args.query, limit=args.limit)
            elif source_name == "scholarshipdb":
                source = ScholarshipDBSource(max_pages=args.scholarshipdb_pages)
            else:
                logger.warning(f"Unknown source: {source_name}")
                continue

            posts, seen_uris = source.fetch_posts(
                since_timestamp=since_timestamp,
                existing_uris=existing_uris,
            )

            logger.info(f"Found {len(posts)} new positions from {source_name}")

            for post in posts:
                d = post.to_dict()
                # Inline LLM classification for Bluesky (CSV path only)
                if source_name == "bluesky" and classifier and d.get("is_verified_job") is None:
                    try:
                        result = classifier.classify_post(
                            d.get("raw_text") or d.get("message", ""),
                            metadata_text=d.get("metadata_text"),
                        )
                        d.update(result)
                    except LLMUnavailableError as e:
                        logger.error(f"LLM API unavailable: {e}")
                        logger.error("Stopping run — will retry tomorrow.")
                        sys.exit(0)
                all_results.append(d)

            if posts:
                newest_timestamp = max(p.created_at for p in posts)
                all_sources_updated[source_name] = {
                    "timestamp": newest_timestamp,
                    "uris": seen_uris,
                }

        except Exception as e:
            logger.error(f"Error fetching from {source_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    logger.info(f"\n{'='*40}")
    logger.info(f"Total: {len(all_results)} new positions")
    logger.info("=" * 40)

    if all_results:
        saved_count = storage.save_posts(all_results)
        logger.info(f"Saved {saved_count} positions to {args.storage}")

        from scripts.post_to_telegram import post_batch_to_telegram
        if not post_batch_to_telegram(all_results):
            logger.error("Telegram posting failed")
            sys.exit(1)

        for source_name, state in all_sources_updated.items():
            sync_manager.update_source_state(
                source_name,
                state["timestamp"],
                state["uris"],
            )
    else:
        logger.info("No new positions to save")


if __name__ == "__main__":
    main()
