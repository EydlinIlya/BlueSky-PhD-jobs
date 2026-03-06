"""Bluesky data source for PhD positions."""

import os
import time

from atproto import Client
from atproto_client.exceptions import InvokeTimeoutError, RequestException
from dotenv import load_dotenv

from src.logger import setup_logger
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
    "postdoctoral fellow",
    "PhD project",
    "hiring PhD",
    "recruiting PhD",
    "apply to phd",
    "funded phd",
    "funded postdoctoral",
    "funded postdoc",
    "hiring postdoc",
    "PhD program",
    "University is hiring"
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
        except InvokeTimeoutError:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_BACKOFF ** attempt
                logger.warning(f"Request timed out. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Timed out after {MAX_RETRIES} attempts")
                return None
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


def expand_shortened_links(text: str, facets) -> str:
    """Replace truncated link text with full URLs from facets.

    Bluesky truncates long URLs in post text (e.g. "example.com/very-lo...")
    but stores the full URL in the facet's Link feature. This replaces each
    truncated span with the actual URL.
    """
    if not facets:
        return text

    text_bytes = text.encode("utf-8")
    # Process facets in reverse order so byte offsets stay valid
    link_facets = []
    for facet in facets:
        for feature in facet.features:
            if hasattr(feature, "uri") and feature.uri is not None:
                link_facets.append((facet.index.byte_start, facet.index.byte_end, feature.uri))

    link_facets.sort(key=lambda x: x[0], reverse=True)

    for byte_start, byte_end, uri in link_facets:
        current_text = text_bytes[byte_start:byte_end].decode("utf-8", errors="replace")
        # Only replace if the text looks truncated (ends with ellipsis or differs from URI)
        if current_text != uri:
            text_bytes = text_bytes[:byte_start] + uri.encode("utf-8") + text_bytes[byte_end:]

    return text_bytes.decode("utf-8")


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


def extract_quote_post(post) -> dict | None:
    """Extract quoted post content from a quote post.

    Handles both record#view and recordWithMedia#view embed types.

    Returns:
        Dict with {"uri", "text", "author_handle"} or None if not a quote post.
    """
    embed = getattr(post, "embed", None)
    if embed is None:
        return None

    py_type = getattr(embed, "py_type", "") or ""
    record_view = None

    if "recordWithMedia" in py_type:
        # recordWithMedia#view: record is nested one level deeper
        inner = getattr(embed, "record", None)
        if inner:
            record_view = getattr(inner, "record", None)
    elif "record" in py_type:
        # record#view: record is directly on embed
        record_view = getattr(embed, "record", None)

    if record_view is None:
        return None

    # Check for deleted/blocked posts
    rv_type = getattr(record_view, "py_type", "") or ""
    if "ViewNotFound" in rv_type or "ViewBlocked" in rv_type:
        return None

    # Extract the value (the actual record content)
    value = getattr(record_view, "value", None)
    if value is None:
        return None

    text = getattr(value, "text", "") or ""
    if not text.strip():
        return None

    uri = getattr(record_view, "uri", None)
    author = getattr(record_view, "author", None)
    author_handle = getattr(author, "handle", "") if author else ""

    return {"uri": uri, "text": text, "author_handle": author_handle}


TENURETRACKER_HANDLE = "tenuretracker.bsky.social"


def _fetch_tt_reply(client: Client, root_uri: str) -> dict | None:
    """Fetch the first direct reply from tenuretracker to their own root post.

    Args:
        client: Authenticated atproto Client
        root_uri: AT URI of the root post

    Returns:
        Dict with {uri, text, created_at} or None if not found / on error.
    """
    try:
        response = client.app.bsky.feed.get_post_thread({"uri": root_uri, "depth": 1})
        thread = response.thread
        replies = getattr(thread, "replies", None) or []
        for reply_view in replies:
            reply_post = getattr(reply_view, "post", None)
            if reply_post is None:
                continue
            author = getattr(reply_post, "author", None)
            if getattr(author, "handle", "") == TENURETRACKER_HANDLE:
                record = getattr(reply_post, "record", None)
                text = getattr(record, "text", "") or ""
                created_at = getattr(record, "created_at", "") or ""
                time.sleep(REQUEST_DELAY)
                return {"uri": reply_post.uri, "text": text, "created_at": created_at}
        time.sleep(REQUEST_DELAY)
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch TT reply for {root_uri}: {e}")
        time.sleep(REQUEST_DELAY)
        return None


def _fetch_tt_parent(client: Client, reply_uri: str) -> dict | None:
    """Fetch the parent post of a tenuretracker reply.

    Args:
        client: Authenticated atproto Client
        reply_uri: AT URI of the reply post

    Returns:
        Dict with {uri, text, handle, created_at} or None if not found / on error.
    """
    try:
        response = client.app.bsky.feed.get_post_thread(
            {"uri": reply_uri, "depth": 0, "parentHeight": 1}
        )
        thread = response.thread
        parent_view = getattr(thread, "parent", None)
        if parent_view is None:
            time.sleep(REQUEST_DELAY)
            return None
        parent_post = getattr(parent_view, "post", None)
        if parent_post is None:
            time.sleep(REQUEST_DELAY)
            return None
        author = getattr(parent_post, "author", None)
        record = getattr(parent_post, "record", None)
        handle = getattr(author, "handle", "") or ""
        text = getattr(record, "text", "") or ""
        created_at = getattr(record, "created_at", "") or ""
        time.sleep(REQUEST_DELAY)
        return {"uri": parent_post.uri, "text": text, "handle": handle, "created_at": created_at}
    except Exception as e:
        logger.warning(f"Failed to fetch TT parent for {reply_uri}: {e}")
        time.sleep(REQUEST_DELAY)
        return None


class BlueskySource(DataSource):
    """Data source for Bluesky posts."""

    def __init__(
        self,
        queries: list[str] | None = None,
        limit: int = 50,
    ):
        """Initialize Bluesky source.

        Args:
            queries: Search queries to use. Defaults to DEFAULT_QUERIES.
            limit: Maximum results per query.
        """
        self.queries = queries or DEFAULT_QUERIES
        self.limit = limit
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

                # Check if this is a reply
                reply_ref = getattr(post.record, "reply", None)
                reply_parent_uri = None
                if reply_ref:
                    parent = getattr(reply_ref, "parent", None)
                    if parent:
                        reply_parent_uri = getattr(parent, "uri", None)

                # Check if this is a quote post
                quoted = extract_quote_post(post)
                quoted_uri = None

                if quoted and quoted["uri"]:
                    quoted_uri = quoted["uri"]
                    # If the quoted post is already being processed, skip
                    if quoted_uri in seen_uris:
                        quoted = None
                    else:
                        seen_uris.add(quoted_uri)

                if quoted:
                    # Use quoted post's text for classification
                    raw_text = quoted["text"]
                    wrapper_text = expand_shortened_links(
                        post.record.text,
                        getattr(post.record, "facets", None),
                    )
                else:
                    # Regular post: expand truncated links
                    raw_text = expand_shortened_links(
                        post.record.text,
                        getattr(post.record, "facets", None),
                    )
                    wrapper_text = None

                # Prepend author bio for discipline context
                bio = getattr(post.author, "description", "") or ""
                message = f"[Bio: {bio.strip()}]\n\n{raw_text}" if bio else raw_text

                # Build metadata_text with embed context and quote wrapper
                embed_ctx = extract_embed_context(post)
                if wrapper_text:
                    extra = f"\n\n[Quote wrapper: {wrapper_text}]"
                    metadata_text = f"{message}{extra}"
                    if embed_ctx:
                        metadata_text = f"{metadata_text}\n\n{embed_ctx}"
                else:
                    metadata_text = f"{message}\n\n{embed_ctx}" if embed_ctx else message

                post_data = Post(
                    uri=post.uri,
                    message=message,
                    url=uri_to_url(post.uri, post.author.handle),
                    user_handle=post.author.handle,
                    created_at=post.record.created_at,
                    source="bluesky",
                    quoted_uri=quoted_uri if quoted else None,
                    reply_parent_uri=reply_parent_uri,
                    raw_text=raw_text,
                    metadata_text=metadata_text,
                )

                results.append(post_data)

            time.sleep(REQUEST_DELAY)

        if skipped_old > 0:
            logger.info(f"Skipped {skipped_old} posts older than last sync")

        return results, seen_uris
