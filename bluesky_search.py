"""Search Bluesky for PhD calls using the AT Protocol SDK."""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

from src.logger import setup_logger

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")

logger = setup_logger()

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


def search_phd_calls(client: Client, queries: list[str], limit: int = 25) -> list[dict]:
    """Search Bluesky for PhD-related posts."""
    results = []
    seen_uris = set()

    for query in queries:
        logger.info(f"Searching: {query}")
        posts = search_with_retry(client, query, limit)

        if posts is None:
            continue

        for post in posts:
            if post.uri in seen_uris:
                continue
            seen_uris.add(post.uri)

            results.append({
                "message": post.record.text,
                "url": uri_to_url(post.uri, post.author.handle),
                "user": post.author.handle,
                "created": post.record.created_at,
            })

        time.sleep(REQUEST_DELAY)

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

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["message", "url", "user", "created"])
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
    args = parser.parse_args()

    queries = args.query if args.query else DEFAULT_QUERIES

    logger.info("Connecting to Bluesky...")
    try:
        client = get_client()
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return

    logger.info(f"Searching with {len(queries)} queries...")
    results = search_phd_calls(client, queries, limit=args.limit)

    logger.info(f"Found {len(results)} unique positions")
    write_csv(results, args.output)


if __name__ == "__main__":
    main()
