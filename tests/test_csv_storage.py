"""Tests for CSV storage with multi-discipline support."""

import csv
import json
import os
import tempfile

from src.storage.csv_storage import CSVStorage


def make_post(uri="at://test/1", disciplines=None, is_verified_job=True,
              country=None, position_type=None):
    """Helper to create a post dict."""
    post = {
        "uri": uri,
        "message": "PhD position in testing",
        "url": "https://bsky.app/profile/test/post/1",
        "user": "test.bsky.social",
        "created": "2025-01-15T10:00:00Z",
    }
    if disciplines is not None:
        post["disciplines"] = disciplines
    post["is_verified_job"] = is_verified_job
    if country is not None:
        post["country"] = country
    if position_type is not None:
        post["position_type"] = position_type
    return post


class TestCSVStorage:
    def setup_method(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        )
        self.tmpfile.close()
        self.storage = CSVStorage(self.tmpfile.name)

    def teardown_method(self):
        os.unlink(self.tmpfile.name)

    def test_save_with_disciplines_array(self):
        post = make_post(disciplines=["Biology", "Computer Science"])
        self.storage.save_posts([post])

        with open(self.tmpfile.name, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        # Disciplines should be JSON-serialized
        assert rows[0]["disciplines"] == '["Biology", "Computer Science"]'

    def test_save_single_discipline(self):
        post = make_post(disciplines=["Physics"])
        self.storage.save_posts([post])

        with open(self.tmpfile.name, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        parsed = json.loads(rows[0]["disciplines"])
        assert parsed == ["Physics"]

    def test_save_no_disciplines(self):
        post = make_post(disciplines=None)
        del post["is_verified_job"]
        self.storage.save_posts([post])

        with open(self.tmpfile.name, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert "disciplines" not in rows[0]

    def test_get_existing_uris(self):
        posts = [
            make_post(uri="at://test/1"),
            make_post(uri="at://test/2"),
        ]
        self.storage.save_posts(posts)
        uris = self.storage.get_existing_uris()
        assert uris == {"at://test/1", "at://test/2"}

    def test_get_last_timestamp(self):
        posts = [
            make_post(uri="at://test/1"),
            make_post(uri="at://test/2"),
        ]
        posts[0]["created"] = "2025-01-10T10:00:00Z"
        posts[1]["created"] = "2025-01-15T10:00:00Z"
        self.storage.save_posts(posts)

        assert self.storage.get_last_timestamp() == "2025-01-15T10:00:00Z"

    def test_empty_save_returns_zero(self):
        assert self.storage.save_posts([]) == 0

    def test_three_disciplines(self):
        post = make_post(disciplines=["Biology", "Chemistry & Materials Science", "Medicine"])
        self.storage.save_posts([post])

        with open(self.tmpfile.name, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        parsed = json.loads(rows[0]["disciplines"])
        assert len(parsed) == 3
        assert "Biology" in parsed
        assert "Chemistry & Materials Science" in parsed
        assert "Medicine" in parsed

    def test_country_and_position_type_roundtrip(self):
        post = make_post(
            disciplines=["Physics"],
            country="Switzerland",
            position_type=["Postdoc"]
        )
        self.storage.save_posts([post])

        with open(self.tmpfile.name, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["country"] == "Switzerland"
        assert json.loads(rows[0]["position_type"]) == ["Postdoc"]
        assert json.loads(rows[0]["disciplines"]) == ["Physics"]

    def test_multiple_position_types_roundtrip(self):
        post = make_post(
            disciplines=["Biology"],
            country="Turkey",
            position_type=["PhD Student", "Postdoc"]
        )
        self.storage.save_posts([post])

        with open(self.tmpfile.name, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert json.loads(rows[0]["position_type"]) == ["PhD Student", "Postdoc"]

    def test_country_and_position_type_absent(self):
        post = make_post(disciplines=["Biology"])
        self.storage.save_posts([post])

        with open(self.tmpfile.name, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert "country" not in rows[0]
        assert "position_type" not in rows[0]
