"""Job filtering and discipline classification."""

from .base import LLMProvider
from .config import DISCIPLINES, IS_REAL_JOB_PROMPT, DISCIPLINE_PROMPT_TEMPLATE


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

    def get_disciplines(self, text: str) -> list[str]:
        """Classify the job posting into 1-3 academic disciplines.

        Args:
            text: The post text to analyze

        Returns:
            List of discipline names from DISCIPLINES list (max 3)
        """
        disciplines_str = ", ".join(DISCIPLINES)
        prompt = DISCIPLINE_PROMPT_TEMPLATE.format(disciplines=disciplines_str)
        response = self.llm.classify(text, prompt).strip()

        # Parse comma-separated response and validate each part
        matched = []
        for part in response.split(','):
            part = part.strip()
            for discipline in DISCIPLINES:
                if discipline.lower() in part.lower():
                    if discipline not in matched:
                        matched.append(discipline)
                    break

        # Limit to 3, default to ["Other"]
        return matched[:3] if matched else ["Other"]

    def classify_post(self, text: str) -> dict:
        """Classify a post, determining if it's a real job and its disciplines.

        Args:
            text: The post text to analyze

        Returns:
            Dict with 'is_verified_job' and 'disciplines' keys.
            Non-jobs have is_verified_job=False and disciplines=None.
        """
        is_job = self.is_real_job(text)

        if not is_job:
            return {
                "is_verified_job": False,
                "disciplines": None,
            }

        disciplines = self.get_disciplines(text)
        return {
            "is_verified_job": True,
            "disciplines": disciplines,
        }
