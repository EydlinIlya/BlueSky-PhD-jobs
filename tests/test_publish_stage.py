"""Regression tests for atomic, drain-all publishing."""

import pytest

from src.pipeline.stages import publish


def staging_row(uri: str, *, row_id: int, run_date: str, message: str) -> dict:
    return {
        "id": row_id,
        "run_date": run_date,
        "staged_at": f"{run_date}T12:00:00+00:00",
        "uri": uri,
        "message": message,
        "url": "https://example.test/job",
        "user_handle": "lab.example",
        "created_at": f"{run_date}T09:00:00+00:00",
        "is_verified_job": True,
    }


class PublishStorage:
    def __init__(self, rows: list[dict], *, saved_count: int | None = None):
        self.rows = rows
        self.saved_count = saved_count
        self.saved_posts: list[dict] = []
        self.staging_deleted = False
        self.runs_deleted = False

    def get_staging_all(self):
        return self.rows

    def save_posts(self, posts):
        self.saved_posts = posts
        return len(posts) if self.saved_count is None else self.saved_count

    def delete_staging(self):
        self.staging_deleted = True

    def delete_run(self):
        self.runs_deleted = True


def test_publish_collapses_repeated_uri_and_keeps_newest_row():
    rows = [
        staging_row("at://same", row_id=1, run_date="2026-09-15", message="old"),
        staging_row("at://other", row_id=2, run_date="2026-09-15", message="other"),
        staging_row("at://same", row_id=3, run_date="2026-09-16", message="new"),
    ]
    storage = PublishStorage(rows)

    publish.run("2026-09-16", storage, None)

    assert len(storage.saved_posts) == 2
    assert {post["uri"] for post in storage.saved_posts} == {
        "at://same",
        "at://other",
    }
    assert next(post for post in storage.saved_posts if post["uri"] == "at://same")[
        "message"
    ] == "new"
    assert storage.staging_deleted is True
    assert storage.runs_deleted is True


def test_publish_preserves_staging_when_save_count_is_short():
    storage = PublishStorage(
        [staging_row("at://one", row_id=1, run_date="2026-09-16", message="one")],
        saved_count=0,
    )

    with pytest.raises(RuntimeError, match="staging was preserved"):
        publish.run("2026-09-16", storage, None)

    assert storage.staging_deleted is False
    assert storage.runs_deleted is False


def test_publish_preserves_staging_when_save_raises():
    class FailingStorage(PublishStorage):
        def save_posts(self, posts):
            raise RuntimeError("database unavailable")

    storage = FailingStorage(
        [staging_row("at://one", row_id=1, run_date="2026-09-16", message="one")]
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        publish.run("2026-09-16", storage, None)

    assert storage.staging_deleted is False
    assert storage.runs_deleted is False
