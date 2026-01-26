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

    def get_discipline(self, text: str) -> str:
        """Classify the job posting into an academic discipline.

        Args:
            text: The post text to analyze

        Returns:
            The discipline name from DISCIPLINES list
        """
        disciplines_str = ", ".join(DISCIPLINES)
        prompt = DISCIPLINE_PROMPT_TEMPLATE.format(disciplines=disciplines_str)
        response = self.llm.classify(text, prompt).strip()

        # Validate response is in our list
        for discipline in DISCIPLINES:
            if discipline.lower() in response.lower():
                return discipline

        return "Other"

    def classify_post(self, text: str) -> dict:
        """Classify a post, determining if it's a real job and its discipline.

        Args:
            text: The post text to analyze

        Returns:
            Dict with 'is_verified_job' and 'discipline' keys.
            Non-jobs have is_verified_job=False and discipline=None.
        """
        is_job = self.is_real_job(text)

        if not is_job:
            return {
                "is_verified_job": False,
                "discipline": None,
            }

        discipline = self.get_discipline(text)
        return {
            "is_verified_job": True,
            "discipline": discipline,
        }
