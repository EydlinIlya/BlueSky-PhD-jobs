"""Tests for the mock storage backend."""

from tests.mock_storage import MockStorage


def make_post(uri="at://test/1", message="Test PhD position", disciplines=None, is_verified_job=True):
    """Helper to create a post dict."""
    post = {
        "uri": uri,
        "message": message,
        "url": f"https://bsky.app/profile/test/post/{uri.split('/')[-1]}",
        "user": "test.bsky.social",
        "created": "2025-01-15T10:00:00Z",
    }
    if disciplines is not None:
        post["disciplines"] = disciplines
    post["is_verified_job"] = is_verified_job
    return post


class TestMockStorage:
    def test_save_and_retrieve(self):
        storage = MockStorage()
        post = make_post(disciplines=["Biology", "Computer Science"])
        saved = storage.save_posts([post])
        assert saved == 1
        assert "at://test/1" in storage.get_existing_uris()

    def test_empty_save(self):
        storage = MockStorage()
        assert storage.save_posts([]) == 0

    def test_upsert_overwrites(self):
        storage = MockStorage()
        post1 = make_post(disciplines=["Biology"])
        post2 = make_post(disciplines=["Biology", "Chemistry & Materials Science"])

        storage.save_posts([post1])
        storage.save_posts([post2])

        record = storage.get_post("at://test/1")
        assert record["disciplines"] == ["Biology", "Chemistry & Materials Science"]

    def test_multiple_posts(self):
        storage = MockStorage()
        posts = [
            make_post(uri="at://test/1", disciplines=["Physics"]),
            make_post(uri="at://test/2", disciplines=["Biology", "Medicine"]),
            make_post(uri="at://test/3", disciplines=["Computer Science"]),
        ]
        saved = storage.save_posts(posts)
        assert saved == 3
        assert len(storage.get_existing_uris()) == 3

    def test_disciplines_array_stored(self):
        storage = MockStorage()
        post = make_post(disciplines=["Biology", "Computer Science", "Mathematics"])
        storage.save_posts([post])

        record = storage.get_post("at://test/1")
        assert isinstance(record["disciplines"], list)
        assert len(record["disciplines"]) == 3
        assert "Biology" in record["disciplines"]
        assert "Computer Science" in record["disciplines"]
        assert "Mathematics" in record["disciplines"]

    def test_get_last_timestamp(self):
        storage = MockStorage()
        assert storage.get_last_timestamp() is None

        posts = [
            make_post(uri="at://test/1"),
            make_post(uri="at://test/2"),
        ]
        # Override timestamps
        posts[0]["created"] = "2025-01-10T10:00:00Z"
        posts[1]["created"] = "2025-01-15T10:00:00Z"
        storage.save_posts(posts)

        assert storage.get_last_timestamp() == "2025-01-15T10:00:00Z"

    def test_clear(self):
        storage = MockStorage()
        storage.save_posts([make_post()])
        assert len(storage.get_existing_uris()) == 1
        storage.clear()
        assert len(storage.get_existing_uris()) == 0

    def test_get_all_posts(self):
        storage = MockStorage()
        posts = [
            make_post(uri="at://test/1"),
            make_post(uri="at://test/2"),
        ]
        storage.save_posts(posts)
        all_posts = storage.get_all_posts()
        assert len(all_posts) == 2

    def test_non_job_post(self):
        storage = MockStorage()
        post = make_post(is_verified_job=False, disciplines=None)
        storage.save_posts([post])

        record = storage.get_post("at://test/1")
        assert record["is_verified_job"] is False
        assert "disciplines" not in record
