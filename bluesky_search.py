"""Search Bluesky for PhD calls using the AT Protocol SDK."""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from src.logger import setup_logger
from src.llm import GeminiProvider, JobClassifier
from src.storage import StorageBackend, CSVStorage, SupabaseStorage

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")

logger = setup_logger()


def get_classifier() -> JobClassifier | None:
    """Create a job classifier if API key is available."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    llm = GeminiProvider(api_key)
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


SYNC_STATE_FILE = "last_sync.json"


def load_sync_state(state_file: str = SYNC_STATE_FILE) -> dict:
    """Load the last sync state from file.

    Returns:
        Dict with 'last_timestamp', 'seen_uris' keys
    """
    if Path(state_file).exists():
        try:
            with open(state_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load sync state: {e}")
    return {"last_timestamp": None, "seen_uris": []}


def save_sync_state(
    last_timestamp: str | None,
    seen_uris: list[str],
    state_file: str = SYNC_STATE_FILE,
):
    """Save the sync state to file.

    Args:
        last_timestamp: ISO timestamp of the most recent post
        seen_uris: List of all processed post URIs
        state_file: Path to state file
    """
    state = {
        "last_timestamp": last_timestamp,
        "seen_uris": seen_uris,
        "updated_at": datetime.now().isoformat(),
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    logger.debug(f"Saved sync state with {len(seen_uris)} URIs")


DEFAULT_QUERIES = [
    "PhD position",
    "PhD call",
    "doctoral position",
    "PhD opportunity",
    "PhD opening",
    "PhD vacancy",
    "postdoc position",
    "call for postdocs",
    "join my lab",
    "call for master students",
    "research assistant position",
]

from atproto import Client
from atproto_client.exceptions import RequestException
from dotenv import load_dotenv

load_dotenv()

# Rate limit: 3000 requests per 300 seconds (5 min)
REQUEST_DELAY = 0.5  # seconds between requests
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # exponential backoff multiplier


def get_client() -> Client:
    """Create and authenticate a Bluesky client."""
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_PASSWORD")

    if not handle or not password:
        raise ValueError(
            "Set BLUESKY_HANDLE and BLUESKY_PASSWORD environment variables"
        )

    client = Client()
    client.login(handle, password)
    return client


def search_with_retry(client: Client, query: str, limit: int = 25) -> list | None:
    """Search with retry logic and rate limit handling."""
    for attempt in range(MAX_RETRIES):
        try:
            response = client.app.bsky.feed.search_posts({"q": query, "limit": limit})
            return response.posts
        except RequestException as e:
            error_msg = str(e)
            if "429" in error_msg or "RateLimitExceeded" in error_msg:
                wait_time = RETRY_BACKOFF ** (attempt + 2)
                logger.warning(f"Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
            elif attempt < MAX_RETRIES - 1:
                wait_time = RETRY_BACKOFF ** attempt
                logger.warning(f"Request failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed after {MAX_RETRIES} attempts: {e}")
                return None
    return None


def extract_embed_context(post) -> str:
    """Extract title and description from a post's embedded link preview.

    Bluesky stores link preview metadata (title, description) in the post's
    embed field. This is free data from the API — no HTTP fetch needed.
    """
    embed = getattr(post.record, 'embed', None)
    if not embed or not hasattr(embed, 'external'):
        return ""
    ext = embed.external
    title = getattr(ext, 'title', '') or ''
    desc = getattr(ext, 'description', '') or ''
    if title or desc:
        return f"[Linked page - {title}: {desc}]"
    return ""


def search_phd_calls(
    client: Client,
    queries: list[str],
    limit: int = 25,
    classifier: JobClassifier | None = None,
    since_timestamp: str | None = None,
    existing_uris: set[str] | None = None,
) -> tuple[list[dict], set[str]]:
    """Search Bluesky for PhD-related posts.

    Args:
        client: Authenticated Bluesky client
        queries: List of search queries
        limit: Maximum results per query
        classifier: Optional JobClassifier for LLM filtering
        since_timestamp: Only include posts newer than this ISO timestamp
        existing_uris: Set of URIs already processed (for deduplication)

    Returns:
        Tuple of (list of post dictionaries, set of all seen URIs)
    """
    results = []
    seen_uris = existing_uris.copy() if existing_uris else set()
    filtered_count = 0
    skipped_old = 0

    for query in queries:
        logger.info(f"Searching: {query}")
        posts = search_with_retry(client, query, limit)

        if posts is None:
            continue

        for post in posts:
            # Skip already seen posts
            if post.uri in seen_uris:
                continue
            seen_uris.add(post.uri)

            # Skip posts older than our last sync
            if since_timestamp and post.record.created_at <= since_timestamp:
                skipped_old += 1
                continue

            # Prepend author bio for discipline context
            bio = getattr(post.author, 'description', '') or ''
            raw_text = post.record.text
            message = f"[Bio: {bio.strip()}]\n\n{raw_text}" if bio else raw_text

            post_data = {
                "uri": post.uri,
                "message": message,
                "url": uri_to_url(post.uri, post.author.handle),
                "user": post.author.handle,
                "created": post.record.created_at,
            }

            # Apply LLM classification if available
            # Use raw text for job detection (bio confuses the small model)
            # Use bio + embed context for discipline classification (improves accuracy)
            if classifier:
                is_job = classifier.is_real_job(raw_text)
                if is_job:
                    embed_ctx = extract_embed_context(post)
                    disc_text = f"{message}\n\n{embed_ctx}" if embed_ctx else message
                    disciplines = classifier.get_disciplines(disc_text)
                    classification = {"is_verified_job": True, "disciplines": disciplines}
                else:
                    classification = {"is_verified_job": False, "disciplines": None}
                post_data.update(classification)
                if not classification["is_verified_job"]:
                    filtered_count += 1
                    logger.debug(f"Non-job post: {raw_text[:50]}...")

            results.append(post_data)

        time.sleep(REQUEST_DELAY)

    if skipped_old > 0:
        logger.info(f"Skipped {skipped_old} posts older than last sync")
    if classifier and filtered_count > 0:
        logger.info(f"Classified {filtered_count} posts as non-jobs (still saved for analysis)")

    return results, seen_uris


def uri_to_url(uri: str, handle: str) -> str:
    """Convert AT URI to Bluesky web URL."""
    # at://did:plc:xxx/app.bsky.feed.post/yyy -> https://bsky.app/profile/handle/post/yyy
    parts = uri.split("/")
    post_id = parts[-1]
    return f"https://bsky.app/profile/{handle}/post/{post_id}"


def write_csv(results: list[dict], filename: str = "phd_positions.csv"):
    """Write results to CSV file."""
    if not results:
        logger.warning("No results to write.")
        return

    # Determine fieldnames based on what fields are present
    base_fields = ["message", "url", "user", "created"]
    extra_fields = ["disciplines", "is_verified_job"]

    # Check if any result has extra fields
    fieldnames = base_fields.copy()
    if results and any(f in results[0] for f in extra_fields):
        fieldnames.extend([f for f in extra_fields if f in results[0]])

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    logger.info(f"Wrote {len(results)} positions to {filename}")


def main():
    """Run PhD call search."""
    parser = argparse.ArgumentParser(description="Search Bluesky for PhD positions")
    parser.add_argument(
        "-q", "--query",
        action="append",
        help="Search query (can be specified multiple times). Defaults to PhD-related queries.",
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
        help="Max results per query (default: 50)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM filtering (uses GEMINI_API_KEY env var when enabled)",
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
        help="Storage backend (default: csv). Supabase requires SUPABASE_URL and SUPABASE_KEY env vars.",
    )
    args = parser.parse_args()

    queries = args.query if args.query else DEFAULT_QUERIES

    # Set up storage backend
    try:
        storage = get_storage(args.storage, args.output)
        logger.info(f"Using {args.storage} storage backend")
    except ValueError as e:
        logger.error(f"Storage setup failed: {e}")
        return

    # Load sync state for incremental updates
    since_timestamp = None
    existing_uris = set()

    if not args.full_sync:
        if args.storage == "supabase":
            # For Supabase, get state from the database
            since_timestamp = storage.get_last_timestamp()
            existing_uris = storage.get_existing_uris()
            if since_timestamp:
                logger.info(f"Incremental sync from {since_timestamp} ({len(existing_uris)} existing posts)")
            else:
                logger.info("Full sync (no posts in database)")
        else:
            # For CSV, use the local sync state file
            sync_state = load_sync_state()
            if sync_state.get("last_timestamp"):
                since_timestamp = sync_state["last_timestamp"]
                existing_uris = set(sync_state.get("seen_uris", []))
                logger.info(f"Incremental sync from {since_timestamp}")
            else:
                logger.info("Full sync (no previous state)")
    else:
        logger.info("Full sync (--full-sync specified)")

    # Set up classifier if LLM is enabled
    classifier = None
    if not args.no_llm:
        classifier = get_classifier()
        if classifier:
            logger.info("LLM filtering enabled (Gemini)")
        else:
            logger.info("LLM filtering disabled (no GEMINI_API_KEY)")

    logger.info("Connecting to Bluesky...")
    try:
        client = get_client()
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return

    logger.info(f"Searching with {len(queries)} queries...")
    results, all_uris = search_phd_calls(
        client,
        queries,
        limit=args.limit,
        classifier=classifier,
        since_timestamp=since_timestamp,
        existing_uris=existing_uris,
    )

    logger.info(f"Found {len(results)} new positions")

    if results:
        saved_count = storage.save_posts(results)
        logger.info(f"Saved {saved_count} positions to {args.storage}")

        # Update local sync state for CSV backend
        if args.storage == "csv":
            newest_timestamp = max(r["created"] for r in results)
            save_sync_state(newest_timestamp, list(all_uris))
    else:
        logger.info("No new positions to save")


if __name__ == "__main__":
    main()
