"""ScholarshipDB data source for PhD positions.

This source scrapes ScholarshipDB.net for PhD positions, querying each
academic field separately to get pre-classified discipline information.
"""

import hashlib
import re
import time
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from src.logger import setup_logger
from .base import DataSource, Post

logger = setup_logger()

# Rate limiting
REQUEST_DELAY = 2.0  # seconds between requests
REQUEST_TIMEOUT = 60.0  # seconds

# Discipline mapping from ScholarshipDB fields to our disciplines
DISCIPLINE_MAPPING = {
    "Computer Science": "Computer Science",
    "Medical Sciences": "Medicine",
    "Biology": "Biology",
    "Chemistry": "Chemistry & Materials Science",
    "Materials Science": "Chemistry & Materials Science",
    "Physics": "Physics",
    "Mathematics": "Mathematics",
    "Economics": "Economics",
    "Engineering": "Other",
    "Science": "General call",
    "Psychology": "Psychology",
    "Linguistics": "Linguistics",
    "History": "History",
    "Education": "Education",
    "Arts": "Arts & Humanities",
}

# Default fields to query
DEFAULT_FIELDS = [
    "Computer Science",
    "Biology",
    "Chemistry",
    "Physics",
    "Mathematics",
    "Medical Sciences",
    "Economics",
    "Psychology",
    "Engineering",
]


def parse_relative_date(date_str: str) -> str:
    """Convert relative date strings like '2 days ago' to ISO format.

    Examples:
    - "2 days ago" → "2026-02-06T00:00:00Z"
    - "about 3 hours ago" → "2026-02-08T05:00:00Z"
    - "1 week ago" → "2026-02-01T00:00:00Z"
    """
    now = datetime.utcnow()
    clean = re.sub(r"about|ago", "", date_str).strip().lower()

    match = re.match(r"(\d+)\s*(\w+)", clean)
    if not match:
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")

    num = int(match.group(1))
    unit = match.group(2)

    if "minute" in unit:
        delta = timedelta(minutes=num)
    elif "hour" in unit:
        delta = timedelta(hours=num)
    elif "day" in unit:
        delta = timedelta(days=num)
    elif "week" in unit:
        delta = timedelta(weeks=num)
    elif "month" in unit:
        delta = timedelta(days=num * 30)
    else:
        delta = timedelta(days=0)

    result = now - delta
    return result.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_uri(link: str) -> str:
    """Generate a unique URI for a ScholarshipDB listing.

    Format: scholarshipdb://{hash}
    """
    hash_value = hashlib.md5(link.encode()).hexdigest()[:16]
    return f"scholarshipdb://{hash_value}"


class ScholarshipDBSource(DataSource):
    """Data source for ScholarshipDB.net PhD positions."""

    def __init__(
        self,
        fields: list[str] | None = None,
        max_pages: int = 2,
    ):
        """Initialize ScholarshipDB source.

        Args:
            fields: Academic fields to search. Defaults to DEFAULT_FIELDS.
            max_pages: Maximum pages to fetch per field.
        """
        self.fields = fields or DEFAULT_FIELDS
        self.max_pages = max_pages

    @property
    def name(self) -> str:
        return "scholarshipdb"

    def _fetch_page(self, field: str, page: int) -> list[Post]:
        """Fetch a single page of PhD positions.

        Args:
            field: Academic field to search for
            page: Page number (1-indexed)

        Returns:
            List of Post objects
        """
        base_url = "https://scholarshipdb.net/scholarships/Program-PhD"
        url = f"{base_url}?page={page}&q={field.replace(' ', '%20')}"

        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            response = httpx.get(
                url, headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=True
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Error fetching {field} page {page}: {e}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        # Find job listings
        listings = soup.select(
            'h4 a[href*="/jobs-in-"], h4 a[href*="/scholarships-in-"]'
        )

        posts = []
        for listing in listings:
            title = listing.text.strip()
            href = listing.get("href", "")
            link = f"https://scholarshipdb.net{href}"

            # Find parent container for country and date
            parent = listing.find_parent("li") or listing.find_parent("div")
            if not parent:
                continue

            country_elem = parent.select_one("a.text-success")
            country = country_elem.text.strip() if country_elem else "Unknown"

            date_elem = parent.select_one("span.text-muted")
            date_raw = date_elem.text.strip() if date_elem else ""
            created_at = parse_relative_date(date_raw)

            # Map discipline
            discipline = DISCIPLINE_MAPPING.get(field, "Other")

            # Determine position type from URL pattern
            position_type = ["PhD Student"]
            if "/Postdoc" in href or "postdoc" in title.lower():
                position_type = ["Postdoc"]
            elif "/jobs-in-" in href:
                # Research jobs could be RA or other
                if "research assistant" in title.lower():
                    position_type = ["Research Assistant"]

            post = Post(
                uri=generate_uri(link),
                message=title,
                url=link,
                user_handle="scholarshipdb.net",
                created_at=created_at,
                source="scholarshipdb",
                country=country,
                disciplines=[discipline],
                position_type=position_type,
                is_verified_job=True,  # Pre-verified from job site
            )
            posts.append(post)

        return posts

    def fetch_posts(
        self,
        since_timestamp: str | None = None,
        existing_uris: set[str] | None = None,
    ) -> tuple[list[Post], set[str]]:
        """Fetch posts from ScholarshipDB.

        Args:
            since_timestamp: Only include posts newer than this ISO timestamp
            existing_uris: Set of URIs already processed (for deduplication)

        Returns:
            Tuple of (list of Post objects, set of all seen URIs)
        """
        results = []
        seen_uris = existing_uris.copy() if existing_uris else set()
        skipped_old = 0

        for field in self.fields:
            logger.info(f"Fetching ScholarshipDB: {field}")

            for page in range(1, self.max_pages + 1):
                posts = self._fetch_page(field, page)
                logger.debug(f"  Page {page}: {len(posts)} positions")

                for post in posts:
                    # Skip already seen posts
                    if post.uri in seen_uris:
                        continue
                    seen_uris.add(post.uri)

                    # Skip posts older than our last sync
                    if since_timestamp and post.created_at < since_timestamp:
                        skipped_old += 1
                        continue

                    results.append(post)

                # If we got fewer than expected, no more pages
                if len(posts) < 10:
                    break

                time.sleep(REQUEST_DELAY)

        if skipped_old > 0:
            logger.info(f"Skipped {skipped_old} posts older than last sync")

        logger.info(f"Found {len(results)} new positions from ScholarshipDB")
        return results, seen_uris
