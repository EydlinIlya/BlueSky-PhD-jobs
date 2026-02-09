"""Bluesky data source for PhD positions."""

import os
import time

from atproto import Client
from atproto_client.exceptions import RequestException
from dotenv import load_dotenv

from src.logger import setup_logger
from src.llm import JobClassifier
from .base import DataSource, Post

load_dotenv()

logger = setup_logger()

# Rate limit: 3000 requests per 300 seconds (5 min)
REQUEST_DELAY = 0.5  # seconds between requests
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # exponential backoff multiplier

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


def uri_to_url(uri: str, handle: str) -> str:
    """Convert AT URI to Bluesky web URL."""
    # at://did:plc:xxx/app.bsky.feed.post/yyy -> https://bsky.app/profile/handle/post/yyy
    parts = uri.split("/")
    post_id = parts[-1]
    return f"https://bsky.app/profile/{handle}/post/{post_id}"


def extract_embed_context(post) -> str:
    """Extract title and description from a post's embedded link preview.

    Bluesky stores link preview metadata (title, description) in the post's
    embed field. This is free data from the API — no HTTP fetch needed.
    """
    embed = getattr(post.record, "embed", None)
    if not embed or not hasattr(embed, "external"):
        return ""
    ext = embed.external
    title = getattr(ext, "title", "") or ""
    desc = getattr(ext, "description", "") or ""
    if title or desc:
        return f"[Linked page - {title}: {desc}]"
    return ""


class BlueskySource(DataSource):
    """Data source for Bluesky posts."""

    def __init__(
        self,
        queries: list[str] | None = None,
        limit: int = 50,
        classifier: JobClassifier | None = None,
    ):
        """Initialize Bluesky source.

        Args:
            queries: Search queries to use. Defaults to DEFAULT_QUERIES.
            limit: Maximum results per query.
            classifier: Optional JobClassifier for LLM filtering.
        """
        self.queries = queries or DEFAULT_QUERIES
        self.limit = limit
        self.classifier = classifier
        self._client: Client | None = None

    @property
    def name(self) -> str:
        return "bluesky"

    def _get_client(self) -> Client:
        """Get or create authenticated client."""
        if self._client is None:
            self._client = get_client()
        return self._client

    def fetch_posts(
        self,
        since_timestamp: str | None = None,
        existing_uris: set[str] | None = None,
    ) -> tuple[list[Post], set[str]]:
        """Fetch posts from Bluesky.

        Args:
            since_timestamp: Only include posts newer than this ISO timestamp
            existing_uris: Set of URIs already processed (for deduplication)

        Returns:
            Tuple of (list of Post objects, set of all seen URIs)
        """
        client = self._get_client()
        results = []
        seen_uris = existing_uris.copy() if existing_uris else set()
        filtered_count = 0
        skipped_old = 0

        for query in self.queries:
            logger.info(f"Searching Bluesky: {query}")
            posts = search_with_retry(client, query, self.limit)

            if posts is None:
                continue

            for post in posts:
                # Skip already seen posts
                if post.uri in seen_uris:
                    continue
                seen_uris.add(post.uri)

                # Skip posts older than our last sync
                if since_timestamp and post.record.created_at < since_timestamp:
                    skipped_old += 1
                    continue

                # Prepend author bio for discipline context
                bio = getattr(post.author, "description", "") or ""
                raw_text = post.record.text
                message = f"[Bio: {bio.strip()}]\n\n{raw_text}" if bio else raw_text

                post_data = Post(
                    uri=post.uri,
                    message=message,
                    url=uri_to_url(post.uri, post.author.handle),
                    user_handle=post.author.handle,
                    created_at=post.record.created_at,
                    source="bluesky",
                )

                # Apply LLM classification if available
                if self.classifier:
                    embed_ctx = extract_embed_context(post)
                    metadata_text = f"{message}\n\n{embed_ctx}" if embed_ctx else message
                    classification = self.classifier.classify_post(
                        raw_text, metadata_text=metadata_text
                    )
                    post_data.is_verified_job = classification.get("is_verified_job")
                    post_data.disciplines = classification.get("disciplines", [])
                    post_data.country = classification.get("country")
                    post_data.position_type = classification.get("position_type", [])

                    if not post_data.is_verified_job:
                        filtered_count += 1
                        logger.debug(f"Non-job post: {raw_text[:50]}...")

                results.append(post_data)

            time.sleep(REQUEST_DELAY)

        if skipped_old > 0:
            logger.info(f"Skipped {skipped_old} posts older than last sync")
        if self.classifier and filtered_count > 0:
            logger.info(
                f"Classified {filtered_count} posts as non-jobs (still saved for analysis)"
            )

        return results, seen_uris
