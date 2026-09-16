"""Job filtering and discipline classification."""

import json
import re
from urllib.parse import urlparse

from .base import LLMProvider
from .config import DISCIPLINES, POSITION_TYPES, IS_REAL_JOB_PROMPT, METADATA_PROMPT_TEMPLATE
from src.seo import normalize_http_url, parse_deadline


def _default_metadata() -> dict:
    """Return a fresh, safe metadata fallback for malformed model output."""
    return {
        "disciplines": ["Other"],
        "country": "Unknown",
        "position_type": ["PhD Student"],
        "job_title": None,
        "hiring_organization": None,
        "application_url": None,
        "application_deadline": None,
        "location_text": None,
    }


def _nullable_text(value, max_length: int = 300) -> str | None:
    """Accept a bounded, non-empty string and normalize all other values to null."""
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value[:max_length] or None


class JobClassifier:
    """Classifier for filtering and categorizing academic job postings."""

    def __init__(self, llm: LLMProvider):
        """Initialize the classifier.

        Args:
            llm: An LLM provider instance for making classifications
        """
        self.llm = llm

    def is_real_job(self, text: str) -> bool:
        """Check if the text is a real PhD/academic job posting.

        Args:
            text: The post text to analyze

        Returns:
            True if this appears to be a real job posting, False otherwise
        """
        response = self.llm.classify(text, IS_REAL_JOB_PROMPT)
        return "YES" in response.upper()

    def get_metadata(self, text: str) -> dict:
        """Extract classification and evidence-backed SEO metadata.

        Args:
            text: The post text to analyze (bio + post + embed context)

        Returns:
            Dict containing the classification fields plus nullable title,
            employer, application URL, deadline, and location fields.
        """
        disciplines_str = ", ".join(DISCIPLINES)
        prompt = METADATA_PROMPT_TEMPLATE.format(disciplines=disciplines_str)
        response = self.llm.classify(text, prompt).strip()

        # Strip markdown fences if present
        response = re.sub(r'^```(?:json)?\s*', '', response)
        response = re.sub(r'\s*```$', '', response)

        # Parse JSON
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, ValueError):
            return _default_metadata()

        # Some models occasionally wrap the requested object in a one-item
        # JSON array. Accept that harmless shape, but fail safely for arbitrary
        # arrays or JSON scalars instead of calling dict methods on them.
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
            data = data[0]
        if not isinstance(data, dict):
            return _default_metadata()

        # Validate and extract disciplines (limit input length to prevent memory issues)
        raw_disciplines = data.get("disciplines", [])
        if isinstance(raw_disciplines, str):
            raw_disciplines = raw_disciplines[:500]  # Limit string length
            raw_disciplines = [d.strip() for d in raw_disciplines.split(",")]
        elif not isinstance(raw_disciplines, list):
            raw_disciplines = []
        raw_disciplines = raw_disciplines[:20]  # Limit array length
        matched = []
        for part in raw_disciplines:
            if isinstance(part, str):
                part = part.strip()
                for discipline in DISCIPLINES:
                    if discipline.lower() in part.lower():
                        if discipline not in matched:
                            matched.append(discipline)
                        break
        disciplines = matched[:3] if matched else ["Other"]

        # Validate country
        country = data.get("country", "Unknown")
        if not isinstance(country, str) or not country.strip():
            country = "Unknown"
        else:
            country = country.strip()

        # Validate position_type as array with fuzzy matching per element
        raw_position = data.get("position_type", ["PhD Student"])
        if isinstance(raw_position, str):
            raw_position = [raw_position]
        if not isinstance(raw_position, list) or not raw_position:
            raw_position = ["PhD Student"]

        position_type = []
        for rp in raw_position:
            if not isinstance(rp, str):
                continue
            rp_lower = rp.strip().lower()
            matched_pt = None
            # Exact match first
            for pt in POSITION_TYPES:
                if pt.lower() == rp_lower:
                    matched_pt = pt
                    break
            # Fuzzy fallback
            if matched_pt is None:
                for pt in POSITION_TYPES:
                    if pt.lower() in rp_lower:
                        matched_pt = pt
                        break
            if matched_pt and matched_pt not in position_type:
                position_type.append(matched_pt)

        if not position_type:
            position_type = ["PhD Student"]

        job_title = _nullable_text(data.get("job_title"))
        hiring_organization = _nullable_text(data.get("hiring_organization"))
        location_text = _nullable_text(data.get("location_text"))

        application_url = normalize_http_url(data.get("application_url"))
        if application_url and "bsky.app" in urlparse(application_url).netloc.lower():
            application_url = None

        deadline = parse_deadline(data.get("application_deadline"))
        application_deadline = deadline.isoformat() if deadline else None

        return {
            "disciplines": disciplines,
            "country": country,
            "position_type": position_type,
            "job_title": job_title,
            "hiring_organization": hiring_organization,
            "application_url": application_url,
            "application_deadline": application_deadline,
            "location_text": location_text,
        }

    def classify_post(self, text: str, metadata_text: str | None = None) -> dict:
        """Classify a post, determining if it's a real job and extracting metadata.

        Args:
            text: The raw post text (used for job detection)
            metadata_text: Enriched text with bio + embed context (used for metadata
                extraction). Falls back to text if not provided.

        Returns:
            Dict with classification and SEO metadata. Non-jobs have
            is_verified_job=False and None for all metadata fields.
        """
        is_job = self.is_real_job(text)

        if not is_job:
            return {
                "is_verified_job": False,
                "disciplines": None,
                "country": None,
                "position_type": None,
                "job_title": None,
                "hiring_organization": None,
                "application_url": None,
                "application_deadline": None,
                "location_text": None,
            }

        metadata = self.get_metadata(metadata_text or text)
        return {
            "is_verified_job": True,
            "disciplines": metadata["disciplines"],
            "country": metadata["country"],
            "position_type": metadata["position_type"],
            "job_title": metadata["job_title"],
            "hiring_organization": metadata["hiring_organization"],
            "application_url": metadata["application_url"],
            "application_deadline": metadata["application_deadline"],
            "location_text": metadata["location_text"],
        }
