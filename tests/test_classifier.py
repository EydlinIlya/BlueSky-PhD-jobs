"""Tests for the job classifier with metadata extraction."""

import json

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


class TestGetMetadata:
    def test_valid_json_single_position(self):
        response = json.dumps({
            "disciplines": ["Biology"],
            "country": "UK",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("PhD in Biology at Oxford")
        assert result["disciplines"] == ["Biology"]
        assert result["country"] == "UK"
        assert result["position_type"] == ["PhD Student"]

    def test_multiple_position_types(self):
        response = json.dumps({
            "disciplines": ["Physics"],
            "country": "USA",
            "position_type": ["PhD Student", "Postdoc"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("PhD and postdoc positions at MIT")
        assert result["position_type"] == ["PhD Student", "Postdoc"]

    def test_string_position_type_coerced_to_list(self):
        response = json.dumps({
            "disciplines": ["Biology"],
            "country": "UK",
            "position_type": "PhD Student"
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("PhD in Biology at Oxford")
        assert result["position_type"] == ["PhD Student"]

    def test_multiple_disciplines(self):
        response = json.dumps({
            "disciplines": ["Biology", "Computer Science"],
            "country": "USA",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("Bioinformatics PhD at MIT")
        assert result["disciplines"] == ["Biology", "Computer Science"]
        assert result["country"] == "USA"

    def test_three_disciplines(self):
        response = json.dumps({
            "disciplines": ["Biology", "Chemistry & Materials Science", "Medicine"],
            "country": "Germany",
            "position_type": ["Postdoc"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("Biomedical Chemistry postdoc")
        assert result["disciplines"] == ["Biology", "Chemistry & Materials Science", "Medicine"]

    def test_max_three_disciplines(self):
        response = json.dumps({
            "disciplines": ["Biology", "Chemistry & Materials Science", "Medicine", "Physics"],
            "country": "UK",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("Broad science PhD")
        assert len(result["disciplines"]) <= 3

    def test_default_on_invalid_json(self):
        llm = MockLLM(["This is not valid JSON"])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("PhD position")
        assert result["disciplines"] == ["Other"]
        assert result["country"] == "Unknown"
        assert result["position_type"] == ["PhD Student"]

    def test_default_on_empty_response(self):
        llm = MockLLM([""])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("PhD position")
        assert result["disciplines"] == ["Other"]
        assert result["country"] == "Unknown"
        assert result["position_type"] == ["PhD Student"]

    def test_fenced_json(self):
        response = '```json\n' + json.dumps({
            "disciplines": ["Physics"],
            "country": "Switzerland",
            "position_type": ["Postdoc"]
        }) + '\n```'
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("Postdoc at CERN")
        assert result["disciplines"] == ["Physics"]
        assert result["country"] == "Switzerland"
        assert result["position_type"] == ["Postdoc"]

    def test_fuzzy_position_match(self):
        response = json.dumps({
            "disciplines": ["Biology"],
            "country": "USA",
            "position_type": ["PhD Student position"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("PhD position in Biology")
        assert result["position_type"] == ["PhD Student"]

    def test_unknown_discipline_defaults_to_other(self):
        response = json.dumps({
            "disciplines": ["Underwater Basket Weaving"],
            "country": "Unknown",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("PhD in something weird")
        assert result["disciplines"] == ["Other"]

    def test_general_call(self):
        response = json.dumps({
            "disciplines": ["General call"],
            "country": "Germany",
            "position_type": ["PhD Student", "Postdoc"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("University-wide PhD program")
        assert result["disciplines"] == ["General call"]
        assert result["position_type"] == ["PhD Student", "Postdoc"]

    def test_no_duplicates(self):
        response = json.dumps({
            "disciplines": ["Biology", "Biology"],
            "country": "UK",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("Biology PhD")
        assert result["disciplines"] == ["Biology"]

    def test_no_duplicate_position_types(self):
        response = json.dumps({
            "disciplines": ["Biology"],
            "country": "UK",
            "position_type": ["Postdoc", "Postdoc"]
        })
        llm = MockLLM([response])
        classifier = JobClassifier(llm)
        result = classifier.get_metadata("Postdoc")
        assert result["position_type"] == ["Postdoc"]

    def test_all_position_types(self):
        for pt in ["PhD Student", "Postdoc", "Master Student", "Research Assistant"]:
            response = json.dumps({
                "disciplines": ["Other"],
                "country": "Unknown",
                "position_type": [pt]
            })
            llm = MockLLM([response])
            classifier = JobClassifier(llm)
            result = classifier.get_metadata("test")
            assert result["position_type"] == [pt]


class TestClassifyPost:
    def test_real_job_with_metadata(self):
        # First call: is_real_job -> YES, Second call: get_metadata -> JSON
        metadata_json = json.dumps({
            "disciplines": ["Biology", "Computer Science"],
            "country": "USA",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM(["YES", metadata_json])
        classifier = JobClassifier(llm)
        result = classifier.classify_post("Bioinformatics PhD position")
        assert result["is_verified_job"] is True
        assert result["disciplines"] == ["Biology", "Computer Science"]
        assert result["country"] == "USA"
        assert result["position_type"] == ["PhD Student"]

    def test_non_job(self):
        llm = MockLLM(["NO"])
        classifier = JobClassifier(llm)
        result = classifier.classify_post("Job searching is hard")
        assert result["is_verified_job"] is False
        assert result["disciplines"] is None
        assert result["country"] is None
        assert result["position_type"] is None

    def test_real_job_with_metadata_text(self):
        metadata_json = json.dumps({
            "disciplines": ["Physics"],
            "country": "Switzerland",
            "position_type": ["Postdoc"]
        })
        llm = MockLLM(["YES", metadata_json])
        classifier = JobClassifier(llm)
        result = classifier.classify_post(
            "Postdoc in physics",
            metadata_text="[Bio: CERN physicist]\n\nPostdoc in physics\n\n[Linked page - Apply here]"
        )
        assert result["is_verified_job"] is True
        assert result["disciplines"] == ["Physics"]
        assert result["country"] == "Switzerland"
        assert result["position_type"] == ["Postdoc"]

    def test_classify_uses_text_when_no_metadata_text(self):
        metadata_json = json.dumps({
            "disciplines": ["Biology"],
            "country": "UK",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM(["YES", metadata_json])
        classifier = JobClassifier(llm)
        result = classifier.classify_post("PhD in Biology at Oxford")
        assert result["is_verified_job"] is True
        assert result["disciplines"] == ["Biology"]

    def test_multiple_position_types_in_classify(self):
        metadata_json = json.dumps({
            "disciplines": ["Biology"],
            "country": "Turkey",
            "position_type": ["PhD Student", "Postdoc"]
        })
        llm = MockLLM(["YES", metadata_json])
        classifier = JobClassifier(llm)
        result = classifier.classify_post("Hiring PhD students and postdocs")
        assert result["is_verified_job"] is True
        assert result["position_type"] == ["PhD Student", "Postdoc"]
