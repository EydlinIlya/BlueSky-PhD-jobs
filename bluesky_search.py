"""Search Bluesky for PhD calls using the AT Protocol SDK."""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

from src.logger import setup_logger
from src.llm import GeminiProvider, JobClassifier

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

DEFAULT_QUERIES = [
    "PhD position",
    "PhD call",
    "doctoral position",
    "PhD opportunity",
    "PhD opening",
    "PhD vacancy",
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


def search_phd_calls(
    client: Client,
    queries: list[str],
    limit: int = 25,
    classifier: JobClassifier | None = None,
) -> list[dict]:
    """Search Bluesky for PhD-related posts.

    Args:
        client: Authenticated Bluesky client
        queries: List of search queries
        limit: Maximum results per query
        classifier: Optional JobClassifier for LLM filtering

    Returns:
        List of post dictionaries
    """
    results = []
    seen_uris = set()
    filtered_count = 0

    for query in queries:
        logger.info(f"Searching: {query}")
        posts = search_with_retry(client, query, limit)

        if posts is None:
            continue

        for post in posts:
            if post.uri in seen_uris:
                continue
            seen_uris.add(post.uri)

            post_data = {
                "uri": post.uri,
                "message": post.record.text,
                "url": uri_to_url(post.uri, post.author.handle),
                "user": post.author.handle,
                "created": post.record.created_at,
            }

            # Apply LLM classification if available
            if classifier:
                classification = classifier.classify_post(post.record.text)
                if classification is None:
                    filtered_count += 1
                    logger.debug(f"Filtered out: {post.record.text[:50]}...")
                    continue
                post_data.update(classification)

            results.append(post_data)

        time.sleep(REQUEST_DELAY)

    if classifier and filtered_count > 0:
        logger.info(f"Filtered out {filtered_count} non-job posts via LLM")

    return results


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
    extra_fields = ["discipline", "is_verified_job"]

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
    args = parser.parse_args()

    queries = args.query if args.query else DEFAULT_QUERIES

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
    results = search_phd_calls(client, queries, limit=args.limit, classifier=classifier)

    logger.info(f"Found {len(results)} unique positions")
    write_csv(results, args.output)


if __name__ == "__main__":
    main()
