"""Search for PhD positions from multiple sources."""

import argparse
import csv
import os
import sys
from datetime import datetime

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

    # Set up classifier if LLM is enabled (for Bluesky)
    classifier = None
    if not args.no_llm and "bluesky" in sources:
        classifier = get_classifier()
        if classifier:
            logger.info("LLM filtering enabled (Llama)")
        else:
            logger.info("LLM filtering disabled (no NVIDIA_API_KEY)")

    # Initialize sync state manager
    sync_manager = SyncStateManager()

    # Aggregate results from all sources
    all_results = []
    all_sources_updated = {}

    for source_name in sources:
        logger.info(f"\n{'='*40}")
        logger.info(f"Fetching from {source_name}")
        logger.info("="*40)

        # Get sync state for this source
        since_timestamp = None
        existing_uris = set()

        if not args.full_sync:
            if args.storage == "supabase":
                # For Supabase, get state from the database
                # Filter by source if possible
                since_timestamp = storage.get_last_timestamp()
                existing_uris = storage.get_existing_uris()
                if since_timestamp:
                    logger.info(f"Incremental sync from {since_timestamp}")
            else:
                # For CSV, use per-source sync state
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

        # Create and run the source
        try:
            if source_name == "bluesky":
                source = BlueskySource(
                    queries=args.query,
                    limit=args.limit,
                    classifier=classifier,
                )
            elif source_name == "scholarshipdb":
                source = ScholarshipDBSource(
                    max_pages=args.scholarshipdb_pages,
                )
            else:
                logger.warning(f"Unknown source: {source_name}")
                continue

            posts, seen_uris = source.fetch_posts(
                since_timestamp=since_timestamp,
                existing_uris=existing_uris,
            )

            logger.info(f"Found {len(posts)} new positions from {source_name}")

            # Convert Post objects to dicts for storage
            for post in posts:
                all_results.append(post.to_dict())

            # Track state for later update
            if posts:
                newest_timestamp = max(p.created_at for p in posts)
                all_sources_updated[source_name] = {
                    "timestamp": newest_timestamp,
                    "uris": seen_uris,
                }

        except LLMUnavailableError as e:
            logger.error(f"LLM API unavailable: {e}")
            logger.error("Stopping run — no posts classified today. Will retry tomorrow.")
            sys.exit(0)

        except Exception as e:
            logger.error(f"Error fetching from {source_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Save results
    logger.info(f"\n{'='*40}")
    logger.info(f"Total: {len(all_results)} new positions")
    logger.info("="*40)

    if all_results:
        saved_count = storage.save_posts(all_results)
        logger.info(f"Saved {saved_count} positions to {args.storage}")

        # Mark old duplicates of newly saved posts (Supabase only)
        if args.storage == "supabase":
            from src.dedup import mark_old_duplicates
            mark_old_duplicates(
                all_results,
                storage,
                classifier.llm if classifier else None,
            )

        # Update sync state for CSV backend
        if args.storage == "csv":
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
