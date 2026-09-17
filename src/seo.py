"""Shared lifecycle and SEO eligibility rules for position listings.

The rules in this module are deliberately conservative.  A social post stays
useful to visitors even when it is too incomplete for search indexing, but it
must not be represented to search engines as a verified ``JobPosting`` unless
the required facts are present and valid.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse


ACTIVE_FALLBACK_DAYS = 90
MIN_DESCRIPTION_CHARS = 100
UNKNOWN_COUNTRIES = {"", "unknown", "remote", "worldwide"}


def parse_datetime(value) -> datetime | None:
    """Parse an ISO date/datetime as an aware UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_deadline(value) -> date | None:
    """Parse a stored ISO application deadline without guessing."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def effective_deadline(position: dict) -> date | None:
    """Return a usable deadline, rejecting years older than the source post.

    Yearless dates are intentionally stored as null by the extractor, but older
    model output sometimes attached a default year (notably 2024). A deadline
    from a prior calendar year cannot describe a newly advertised vacancy, so
    it must not force the position into the archive or appear in structured
    data. Same-year expired reposts remain archived.
    """
    deadline = parse_deadline(position.get("application_deadline"))
    if deadline is None:
        return None
    created = parse_datetime(position.get("created_at") or position.get("created"))
    if created is not None and deadline.year < created.year:
        return None
    return deadline


def normalize_http_url(value) -> str | None:
    """Return a valid absolute HTTP(S) URL, otherwise ``None``."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 2048:
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def is_position_active(position: dict, now: datetime | None = None) -> bool:
    """Return whether a position is active under the public 90-day policy.

    A valid explicit deadline overrides the age fallback.  A malformed deadline
    is ignored and the position falls back to its posting date rather than being
    kept open indefinitely.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    deadline = effective_deadline(position)
    if deadline is not None:
        return deadline >= current.date()

    created = parse_datetime(position.get("created_at") or position.get("created"))
    if created is None:
        return False
    return created >= current - timedelta(days=ACTIVE_FALLBACK_DAYS)


def is_archived(position: dict, now: datetime | None = None) -> bool:
    """Return the inverse of :func:`is_position_active`."""
    return not is_position_active(position, now=now)


def is_seo_eligible(position: dict, now: datetime | None = None) -> bool:
    """Return whether a position may be indexed with ``JobPosting`` markup."""
    if not is_position_active(position, now=now):
        return False
    if position.get("is_verified_job") is not True:
        return False

    required_text = (
        position.get("job_title"),
        position.get("hiring_organization"),
    )
    if any(not isinstance(value, str) or not value.strip() for value in required_text):
        return False

    country = position.get("country")
    if not isinstance(country, str) or country.strip().lower() in UNKNOWN_COUNTRIES:
        return False

    application_url = normalize_http_url(position.get("application_url"))
    if not application_url or "bsky.app" in urlparse(application_url).netloc.lower():
        return False

    description = position.get("message")
    if not isinstance(description, str) or len(" ".join(description.split())) < MIN_DESCRIPTION_CHARS:
        return False

    raw_deadline = position.get("application_deadline")
    if raw_deadline not in (None, "") and parse_deadline(raw_deadline) is None:
        return False

    return True


def lifecycle_state(position: dict, now: datetime | None = None) -> str:
    """Return ``eligible``, ``weak``, or ``archived`` for a position."""
    if not is_position_active(position, now=now):
        return "archived"
    return "eligible" if is_seo_eligible(position, now=now) else "weak"
