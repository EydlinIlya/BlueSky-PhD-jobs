"""Tests for the job classifier with multi-discipline support."""

from src.llm.base import LLMProvider
from src.llm.classifier import JobClassifier


class MockLLM(LLMProvider):
    """Mock LLM that returns predetermined responses."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = responses or []
        self._call_index = 0

    def classify(self, text: str, prompt: str) -> str:
        if self._call_index < len(self._responses):
            response = self._responses[self._call_index]
            self._call_index += 1
            return response
        return ""


class TestIsRealJob:
    def test_yes(self):
        llm = MockLLM(["YES"])
        classifier = JobClassifier(llm)
        assert classifier.is_real_job("PhD position in Biology") is True

    def test_no(self):
        llm = MockLLM(["NO"])
        classifier = JobClassifier(llm)
        assert classifier.is_real_job("I hate job searching") is False

    def test_case_insensitive(self):
        llm = MockLLM(["yes"])
        classifier = JobClassifier(llm)
        assert classifier.is_real_job("PhD position") is True

    def test_partial_match(self):
        llm = MockLLM(["YES, this is a real job posting"])
        classifier = JobClassifier(llm)
        assert classifier.is_real_job("PhD position") is True


class TestGetDisciplines:
    def test_single_discipline(self):
        llm = MockLLM(["Biology"])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("PhD in Biology")
        assert result == ["Biology"]

    def test_multiple_disciplines(self):
        llm = MockLLM(["Biology, Computer Science"])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("Bioinformatics PhD")
        assert result == ["Biology", "Computer Science"]

    def test_three_disciplines(self):
        llm = MockLLM(["Biology, Chemistry & Materials Science, Medicine"])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("Biomedical Chemistry PhD")
        assert result == ["Biology", "Chemistry & Materials Science", "Medicine"]

    def test_max_three_disciplines(self):
        llm = MockLLM(["Biology, Chemistry & Materials Science, Medicine, Physics"])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("Broad science PhD")
        assert len(result) <= 3

    def test_default_to_other(self):
        llm = MockLLM(["Unknown Field"])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("PhD in something weird")
        assert result == ["Other"]

    def test_general_call(self):
        llm = MockLLM(["General call"])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("University-wide PhD program")
        assert result == ["General call"]

    def test_no_duplicates(self):
        llm = MockLLM(["Biology, Biology"])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("Biology PhD")
        assert result == ["Biology"]

    def test_empty_response(self):
        llm = MockLLM([""])
        classifier = JobClassifier(llm)
        result = classifier.get_disciplines("PhD position")
        assert result == ["Other"]


class TestClassifyPost:
    def test_real_job_with_disciplines(self):
        # First call: is_real_job -> YES, Second call: get_disciplines -> Biology, CS
        llm = MockLLM(["YES", "Biology, Computer Science"])
        classifier = JobClassifier(llm)
        result = classifier.classify_post("Bioinformatics PhD position")
        assert result["is_verified_job"] is True
        assert result["disciplines"] == ["Biology", "Computer Science"]

    def test_non_job(self):
        llm = MockLLM(["NO"])
        classifier = JobClassifier(llm)
        result = classifier.classify_post("Job searching is hard")
        assert result["is_verified_job"] is False
        assert result["disciplines"] is None

    def test_real_job_single_discipline(self):
        llm = MockLLM(["YES", "Physics"])
        classifier = JobClassifier(llm)
        result = classifier.classify_post("PhD in quantum physics")
        assert result["is_verified_job"] is True
        assert result["disciplines"] == ["Physics"]
