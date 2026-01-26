"""Job filtering and discipline classification."""

from .base import LLMProvider

DISCIPLINES = [
    "Computer Science",
    "Biology",
    "Chemistry",
    "Physics",
    "Mathematics",
    "Engineering",
    "Medicine",
    "Psychology",
    "Economics",
    "Environmental Science",
    "Linguistics",
    "History",
    "Political Science",
    "Sociology",
    "Law",
    "Arts & Humanities",
    "Education",
    "Other",
]


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
        prompt = (
            "Is this a real PhD or academic job posting? "
            "A real job posting should advertise an actual position with application details. "
            "Exclude: jokes, complaints about job searching, news articles about academia, "
            "personal announcements (like someone accepting a position), or general discussions. "
            "Answer only YES or NO."
        )
        response = self.llm.classify(text, prompt)
        return "YES" in response.upper()

    def get_discipline(self, text: str) -> str:
        """Classify the job posting into an academic discipline.

        Args:
            text: The post text to analyze

        Returns:
            The discipline name from DISCIPLINES list
        """
        disciplines_str = ", ".join(DISCIPLINES)
        prompt = (
            f"Classify this academic job posting into one of these disciplines: "
            f"{disciplines_str}. "
            f"Answer with just the discipline name, nothing else."
        )
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
