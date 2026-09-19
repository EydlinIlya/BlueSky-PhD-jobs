"""Shared lifecycle and SEO eligibility rules for position listings.

The rules in this module are deliberately conservative.  A social post stays
useful to visitors even when it is too incomplete for search indexing, but it
must not be represented to search engines as a verified ``JobPosting`` unless
the required facts are present and valid.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import urlparse


ACTIVE_FALLBACK_DAYS = 90
MIN_DESCRIPTION_CHARS = 100
UNKNOWN_COUNTRIES = {"", "unknown", "remote", "worldwide"}
MONTH_NAMES = (
    "jan(?:uary)?", "feb(?:ruary)?", "mar(?:ch)?", "apr(?:il)?", "may",
    "jun(?:e)?", "jul(?:y)?", "aug(?:ust)?", "sep(?:t(?:ember)?)?",
    "oct(?:ober)?", "nov(?:ember)?", "dec(?:ember)?",
)
DEADLINE_CONTEXT_RE = re.compile(
    r"\bdeadline\b|"
    r"\bclosing\s+date\b|"
    r"\b(?:applications?|submissions?)\s+(?:close|closes|closed|closing|due)\b|"
    r"\b(?:apply|submit)\b.{0,40}\b(?:by|before|no\s+later\s+than)\b|"
    r"\b(?:applications?|submissions?)\b.{0,32}\b(?:accepted|open)\b.{0,20}\buntil\b|"
    r"\bno\s+later\s+than\b|"
    r"[⏳⌛]|"
    "\N{LATIN SMALL LETTER A WITH CIRCUMFLEX}\udc8f\N{SUPERSCRIPT THREE}",
    flags=re.IGNORECASE | re.DOTALL,
)


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


def resolve_deadline_evidence(
    text: str,
    candidate: date,
    posted_at=None,
) -> date | None:
    """Resolve a candidate only when the source labels its month/day as a deadline.

    A source year wins when present. A genuinely yearless deadline may be
    anchored to the post year (or the next year when its month/day has passed).
    Publication dates, URL paths, and identifiers such as ``Job ID: 28/06/26``
    have no deadline context and therefore return ``None``.
    """
    source = re.sub(r"https?://\S+", " ", text or "", flags=re.IGNORECASE)
    day = str(candidate.day)
    month = str(candidate.month)
    month_name = MONTH_NAMES[candidate.month - 1]
    full_patterns = (
        rf"(?<!\d)(?P<year>\d{{4}})[./-]0?{month}[./-]0?{day}(?!\d)",
        rf"(?<!\d)0?{day}[./-]0?{month}[./-](?P<year>\d{{4}})(?!\d)",
        rf"(?<!\d)0?{month}[./-]0?{day}[./-](?P<year>\d{{4}})(?!\d)",
        rf"\b(?:{month_name})\.?\s+(?:the\s+)?0?{day}(?:st|nd|rd|th)?(?:,)?\s+(?P<year>\d{{4}})\b",
        rf"\b0?{day}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{month_name})\.?(?:,)?\s+(?P<year>\d{{4}})\b",
    )
    full_dates = []
    for pattern in full_patterns:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            nearby = source[max(0, match.start() - 96):match.end() + 96]
            if DEADLINE_CONTEXT_RE.search(nearby):
                try:
                    resolved = date(
                        int(match.group("year")), candidate.month, candidate.day
                    )
                except ValueError:
                    continue
                if resolved.year == candidate.year:
                    return resolved
                full_dates.append(resolved)
    if full_dates:
        return max(full_dates)

    short_year_patterns = (
        rf"(?<!\d)0?{day}[./-]0?{month}[./-](?P<year>\d{{2}})(?!\d)",
        rf"(?<!\d)0?{month}[./-]0?{day}[./-](?P<year>\d{{2}})(?!\d)",
    )
    for pattern in short_year_patterns:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            nearby = source[max(0, match.start() - 96):match.end() + 96]
            if DEADLINE_CONTEXT_RE.search(nearby):
                return date(2000 + int(match.group("year")), candidate.month, candidate.day)

    yearless_patterns = (
        rf"(?<![\d./-])0?{month}[./-]0?{day}(?![\d./-])",
        rf"(?<![\d./-])0?{day}[./-]0?{month}(?![\d./-])",
        rf"\b(?:{month_name})\.?\s+(?:the\s+)?0?{day}(?:st|nd|rd|th)?\b",
        rf"\b0?{day}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{month_name})\.?\b",
    )
    for pattern in yearless_patterns:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            nearby = source[max(0, match.start() - 96):match.end() + 96]
            if not DEADLINE_CONTEXT_RE.search(nearby):
                continue
            posted = parse_datetime(posted_at)
            if posted is None:
                return None
            year = posted.year
            if (candidate.month, candidate.day) < (posted.month, posted.day):
                year += 1
            try:
                return date(year, candidate.month, candidate.day)
            except ValueError:
                return None
    return None


def effective_deadline(position: dict) -> date | None:
    """Return a supported deadline, with a conservative legacy fallback."""
    deadline = parse_deadline(position.get("application_deadline"))
    if deadline is None:
        return None
    message = str(position.get("message") or "")
    resolved = resolve_deadline_evidence(
        message,
        deadline,
        position.get("created_at") or position.get("created"),
    )
    if resolved is not None:
        return resolved

    # Existing rows may have been enriched from a linked-page preview that is
    # no longer retained in the canonical message. Trust a plausible future
    # date from that extraction, but never a same-day/past value that could be
    # a publication date, event date, or job/reference identifier.
    created = parse_datetime(position.get("created_at") or position.get("created"))
    if created is not None and deadline > created.date():
        return deadline
    return None


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
