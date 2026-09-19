"""Deterministic application-link deduplication tests."""

from src.dedup import deduplicate_new_posts, normalize_application_url


class StorageStub:
    def __init__(self, existing=None):
        self.existing = existing or []

    def get_canonical_posts(self):
        return list(self.existing)


def post(uri, created, application_url, message):
    return {
        "uri": uri,
        "created": created,
        "message": message,
        "application_url": application_url,
    }


def test_normalize_application_url_removes_transport_and_tracking_noise():
    left = "http://JOBS.EXAMPLE.EDU/vacancy/42/?utm_source=bsky#apply"
    right = "https://jobs.example.edu/vacancy/42"
    assert normalize_application_url(left) == normalize_application_url(right)


def test_same_application_link_deduplicates_batch_without_llm():
    older = post(
        "at://old", "2026-09-16T08:00:00Z",
        "https://jobs.example.edu/vacancy/42?utm_source=bsky",
        "Older wording for the ecology vacancy",
    )
    newer = post(
        "at://new", "2026-09-17T08:00:00Z",
        "https://jobs.example.edu/vacancy/42#apply",
        "Completely different wording for this opening",
    )

    saved, updates = deduplicate_new_posts([older, newer], StorageStub(), llm=None)

    assert saved[0]["duplicate_of"] == "at://new"
    assert saved[1].get("duplicate_of") is None
    assert updates == []


def test_newer_post_supersedes_existing_post_with_same_application_link():
    existing = [{
        "uri": "at://existing",
        "created_at": "2026-09-15T08:00:00Z",
        "message": "Original announcement",
        "application_url": "https://jobs.example.edu/vacancy/42",
    }]
    newer = post(
        "at://new", "2026-09-17T08:00:00Z",
        "https://jobs.example.edu/vacancy/42/",
        "A later repost with unrelated wording",
    )

    saved, updates = deduplicate_new_posts([newer], StorageStub(existing), llm=None)

    assert saved[0].get("duplicate_of") is None
    assert updates == [("at://existing", "at://new")]


def test_meaningful_application_query_parameter_is_preserved():
    first = post(
        "at://one", "2026-09-16T08:00:00Z",
        "https://recruit.example.edu/apply?vacancy=41",
        "Quantum optics doctoral opening",
    )
    second = post(
        "at://two", "2026-09-17T08:00:00Z",
        "https://recruit.example.edu/apply?vacancy=42",
        "Marine ecology postdoctoral opening",
    )

    saved, updates = deduplicate_new_posts([first, second], StorageStub(), llm=None)

    assert all(item.get("duplicate_of") is None for item in saved)
    assert updates == []
