"""Job filtering and discipline classification."""

import json
import re

from .base import LLMProvider
from .config import DISCIPLINES, POSITION_TYPES, IS_REAL_JOB_PROMPT, METADATA_PROMPT_TEMPLATE


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
        """Extract disciplines, country, and position type from a job posting.

        Args:
            text: The post text to analyze (bio + post + embed context)

        Returns:
            Dict with 'disciplines' (list), 'country' (str), 'position_type' (list)
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
            return {
                "disciplines": ["Other"],
                "country": "Unknown",
                "position_type": ["PhD Student"],
            }

        # Validate and extract disciplines (limit input length to prevent memory issues)
        raw_disciplines = data.get("disciplines", [])
        if isinstance(raw_disciplines, str):
            raw_disciplines = raw_disciplines[:500]  # Limit string length
            raw_disciplines = [d.strip() for d in raw_disciplines.split(",")]
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

        return {
            "disciplines": disciplines,
            "country": country,
            "position_type": position_type,
        }

    def classify_post(self, text: str, metadata_text: str | None = None) -> dict:
        """Classify a post, determining if it's a real job and extracting metadata.

        Args:
            text: The raw post text (used for job detection)
            metadata_text: Enriched text with bio + embed context (used for metadata
                extraction). Falls back to text if not provided.

        Returns:
            Dict with 'is_verified_job', 'disciplines', 'country', 'position_type'.
            Non-jobs have is_verified_job=False and None for other fields.
        """
        is_job = self.is_real_job(text)

        if not is_job:
            return {
                "is_verified_job": False,
                "disciplines": None,
                "country": None,
                "position_type": None,
            }

        metadata = self.get_metadata(metadata_text or text)
        return {
            "is_verified_job": True,
            "disciplines": metadata["disciplines"],
            "country": metadata["country"],
            "position_type": metadata["position_type"],
        }
