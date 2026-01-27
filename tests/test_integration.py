"""Integration tests: classifier -> storage pipeline with metadata extraction."""

import json

from src.llm.base import LLMProvider
from src.llm.classifier import JobClassifier
from tests.mock_storage import MockStorage


class MockLLM(LLMProvider):
    """Mock LLM that returns predetermined responses."""

    def __init__(self, responses: list[str]):
        self._responses = responses
        self._call_index = 0

    def classify(self, text: str, prompt: str) -> str:
        if self._call_index < len(self._responses):
            response = self._responses[self._call_index]
            self._call_index += 1
            return response
        return ""


class TestClassifierToStoragePipeline:
    """Test the full flow: classify a post, then save to mock storage."""

    def test_job_with_metadata_saved(self):
        metadata_json = json.dumps({
            "disciplines": ["Biology", "Computer Science"],
            "country": "USA",
            "position_type": ["PhD Student"]
        })
        llm = MockLLM(["YES", metadata_json])
        classifier = JobClassifier(llm)
        storage = MockStorage()

        text = "PhD position in Bioinformatics at MIT"
        classification = classifier.classify_post(text)

        post = {
            "uri": "at://did:plc:abc/app.bsky.feed.post/xyz",
            "message": text,
            "url": "https://bsky.app/profile/test/post/xyz",
            "user": "test.bsky.social",
            "created": "2025-01-15T10:00:00Z",
        }
        post.update(classification)
        storage.save_posts([post])

        record = storage.get_post("at://did:plc:abc/app.bsky.feed.post/xyz")
        assert record is not None
        assert record["disciplines"] == ["Biology", "Computer Science"]
        assert record["is_verified_job"] is True
        assert record["country"] == "USA"
        assert record["position_type"] == ["PhD Student"]

    def test_non_job_not_classified_for_metadata(self):
        llm = MockLLM(["NO"])
        classifier = JobClassifier(llm)
        storage = MockStorage()

        text = "Job searching is so frustrating"
        classification = classifier.classify_post(text)

        post = {
            "uri": "at://did:plc:abc/app.bsky.feed.post/xyz2",
            "message": text,
            "url": "https://bsky.app/profile/test/post/xyz2",
            "user": "test.bsky.social",
            "created": "2025-01-15T10:00:00Z",
        }
        post.update(classification)
        storage.save_posts([post])

        record = storage.get_post("at://did:plc:abc/app.bsky.feed.post/xyz2")
        assert record["is_verified_job"] is False
        assert "disciplines" not in record  # None values not stored
        assert "country" not in record
        assert "position_type" not in record

    def test_batch_classification_and_storage(self):
        """Simulate processing multiple posts like bluesky_search.py does."""
        storage = MockStorage()

        # Simulate 3 posts: 2 real jobs, 1 non-job
        posts_data = [
            {
                "uri": "at://test/1",
                "message": "PhD in Biology",
                "url": "https://bsky.app/profile/a/post/1",
                "user": "a.bsky.social",
                "created": "2025-01-10T10:00:00Z",
                "is_verified_job": True,
                "disciplines": ["Biology"],
                "country": "UK",
                "position_type": ["PhD Student"],
            },
            {
                "uri": "at://test/2",
                "message": "Bioinformatics PhD with ML",
                "url": "https://bsky.app/profile/b/post/2",
                "user": "b.bsky.social",
                "created": "2025-01-12T10:00:00Z",
                "is_verified_job": True,
                "disciplines": ["Biology", "Computer Science"],
                "country": "USA",
                "position_type": ["PhD Student"],
            },
            {
                "uri": "at://test/3",
                "message": "Job market is tough",
                "url": "https://bsky.app/profile/c/post/3",
                "user": "c.bsky.social",
                "created": "2025-01-14T10:00:00Z",
                "is_verified_job": False,
                "disciplines": None,
                "country": None,
                "position_type": None,
            },
        ]

        storage.save_posts(posts_data)

        assert len(storage.get_existing_uris()) == 3

        # Check multi-discipline post with metadata
        bio_cs = storage.get_post("at://test/2")
        assert bio_cs["disciplines"] == ["Biology", "Computer Science"]
        assert bio_cs["country"] == "USA"
        assert bio_cs["position_type"] == ["PhD Student"]

        # Check single discipline post
        bio = storage.get_post("at://test/1")
        assert bio["disciplines"] == ["Biology"]
        assert bio["country"] == "UK"
        assert bio["position_type"] == ["PhD Student"]

        # Check non-job
        non_job = storage.get_post("at://test/3")
        assert non_job["is_verified_job"] is False

    def test_upsert_updates_metadata(self):
        """Simulate re-classifying a post with updated metadata."""
        storage = MockStorage()

        # First save: single discipline
        post_v1 = {
            "uri": "at://test/1",
            "message": "Bioinformatics PhD",
            "url": "https://bsky.app/profile/test/post/1",
            "user": "test.bsky.social",
            "created": "2025-01-15T10:00:00Z",
            "is_verified_job": True,
            "disciplines": ["Biology"],
            "country": "Unknown",
            "position_type": ["PhD Student"],
        }
        storage.save_posts([post_v1])
        assert storage.get_post("at://test/1")["disciplines"] == ["Biology"]
        assert storage.get_post("at://test/1")["country"] == "Unknown"

        # Second save: re-classified with more disciplines and country
        post_v2 = {
            "uri": "at://test/1",
            "message": "Bioinformatics PhD",
            "url": "https://bsky.app/profile/test/post/1",
            "user": "test.bsky.social",
            "created": "2025-01-15T10:00:00Z",
            "is_verified_job": True,
            "disciplines": ["Biology", "Computer Science"],
            "country": "USA",
            "position_type": ["PhD Student"],
        }
        storage.save_posts([post_v2])

        record = storage.get_post("at://test/1")
        assert record["disciplines"] == ["Biology", "Computer Science"]
        assert record["country"] == "USA"
        assert record["position_type"] == ["PhD Student"]
        # Should still be only 1 record (upsert)
        assert len(storage.get_existing_uris()) == 1
