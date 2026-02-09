"""Tests for ScholarshipDB source."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.sources.scholarshipdb import (
    ScholarshipDBSource,
    parse_relative_date,
    generate_uri,
    DISCIPLINE_MAPPING,
)
from src.sources.base import Post


class TestParseRelativeDate:
    """Tests for relative date parsing."""

    def test_days_ago(self):
        """Test parsing 'X days ago' format."""
        result = parse_relative_date("2 days ago")
        expected = datetime.utcnow() - timedelta(days=2)
        # Check date matches (ignore time precision)
        assert result[:10] == expected.strftime("%Y-%m-%d")

    def test_hours_ago(self):
        """Test parsing 'X hours ago' format."""
        result = parse_relative_date("3 hours ago")
        expected = datetime.utcnow() - timedelta(hours=3)
        # Check date matches
        assert result[:10] == expected.strftime("%Y-%m-%d")

    def test_about_prefix(self):
        """Test parsing with 'about' prefix."""
        result = parse_relative_date("about 5 days ago")
        expected = datetime.utcnow() - timedelta(days=5)
        assert result[:10] == expected.strftime("%Y-%m-%d")

    def test_weeks_ago(self):
        """Test parsing 'X weeks ago' format."""
        result = parse_relative_date("1 week ago")
        expected = datetime.utcnow() - timedelta(weeks=1)
        assert result[:10] == expected.strftime("%Y-%m-%d")

    def test_months_ago(self):
        """Test parsing 'X months ago' format."""
        result = parse_relative_date("2 months ago")
        expected = datetime.utcnow() - timedelta(days=60)
        assert result[:10] == expected.strftime("%Y-%m-%d")

    def test_invalid_format(self):
        """Test handling of invalid format returns current time."""
        result = parse_relative_date("invalid")
        expected = datetime.utcnow()
        assert result[:10] == expected.strftime("%Y-%m-%d")


class TestGenerateUri:
    """Tests for URI generation."""

    def test_generates_unique_uri(self):
        """Test that different links generate different URIs."""
        uri1 = generate_uri("https://example.com/job1")
        uri2 = generate_uri("https://example.com/job2")
        assert uri1 != uri2

    def test_same_link_same_uri(self):
        """Test that same link generates same URI."""
        link = "https://example.com/job1"
        assert generate_uri(link) == generate_uri(link)

    def test_uri_format(self):
        """Test URI follows expected format."""
        uri = generate_uri("https://example.com/job1")
        assert uri.startswith("scholarshipdb://")
        assert len(uri) == len("scholarshipdb://") + 16  # 16 char hash


class TestDisciplineMapping:
    """Tests for discipline mapping."""

    def test_computer_science_maps_correctly(self):
        """Test Computer Science mapping."""
        assert DISCIPLINE_MAPPING["Computer Science"] == "Computer Science"

    def test_medical_sciences_maps_to_medicine(self):
        """Test Medical Sciences maps to Medicine."""
        assert DISCIPLINE_MAPPING["Medical Sciences"] == "Medicine"

    def test_chemistry_maps_correctly(self):
        """Test Chemistry maps to Chemistry & Materials Science."""
        assert DISCIPLINE_MAPPING["Chemistry"] == "Chemistry & Materials Science"
        assert DISCIPLINE_MAPPING["Materials Science"] == "Chemistry & Materials Science"


class TestScholarshipDBSource:
    """Tests for ScholarshipDBSource class."""

    def test_source_name(self):
        """Test source name property."""
        source = ScholarshipDBSource()
        assert source.name == "scholarshipdb"

    def test_default_fields(self):
        """Test default fields are set."""
        source = ScholarshipDBSource()
        assert len(source.fields) > 0
        assert "Computer Science" in source.fields

    def test_custom_fields(self):
        """Test custom fields can be set."""
        custom_fields = ["Physics", "Mathematics"]
        source = ScholarshipDBSource(fields=custom_fields)
        assert source.fields == custom_fields

    def test_max_pages(self):
        """Test max_pages parameter."""
        source = ScholarshipDBSource(max_pages=5)
        assert source.max_pages == 5

    @patch("src.sources.scholarshipdb.httpx.get")
    def test_fetch_page_parses_html(self, mock_get):
        """Test that _fetch_page correctly parses HTML."""
        # Mock HTML response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
        <body>
            <li>
                <h4><a href="/scholarships-in-Germany/Test-PhD=abc123.html">PhD in Test</a></h4>
                <a class="text-success">Germany</a>
                <span class="text-muted">2 days ago</span>
            </li>
        </body>
        </html>
        """
        mock_get.return_value = mock_response

        source = ScholarshipDBSource(fields=["Biology"])
        posts = source._fetch_page("Biology", 1)

        assert len(posts) == 1
        assert posts[0].message == "PhD in Test"
        assert posts[0].country == "Germany"
        assert posts[0].disciplines == ["Biology"]
        assert posts[0].is_verified_job is True

    @patch("src.sources.scholarshipdb.httpx.get")
    def test_fetch_page_handles_error(self, mock_get):
        """Test that _fetch_page handles HTTP errors gracefully."""
        import httpx
        mock_get.side_effect = httpx.HTTPError("Network error")

        source = ScholarshipDBSource(fields=["Biology"])
        posts = source._fetch_page("Biology", 1)

        assert posts == []

    def test_fetch_posts_deduplicates(self):
        """Test that fetch_posts deduplicates by URI."""
        source = ScholarshipDBSource(fields=["Biology"], max_pages=1)

        # Create mock posts with same URI
        mock_posts = [
            Post(
                uri="scholarshipdb://abc123",
                message="PhD Position",
                url="https://example.com/job1",
                user_handle="test",
                created_at="2026-01-01T00:00:00Z",
                source="scholarshipdb",
                is_verified_job=True,
            ),
        ]

        with patch.object(source, "_fetch_page", return_value=mock_posts):
            # First fetch
            posts1, uris1 = source.fetch_posts()
            assert len(posts1) == 1

            # Second fetch with existing URIs
            posts2, uris2 = source.fetch_posts(existing_uris=uris1)
            assert len(posts2) == 0  # Duplicates filtered

    def test_fetch_posts_filters_old(self):
        """Test that fetch_posts filters posts older than since_timestamp."""
        source = ScholarshipDBSource(fields=["Biology"], max_pages=1)

        mock_posts = [
            Post(
                uri="scholarshipdb://abc123",
                message="Old Position",
                url="https://example.com/job1",
                user_handle="test",
                created_at="2025-01-01T00:00:00Z",  # Old
                source="scholarshipdb",
                is_verified_job=True,
            ),
            Post(
                uri="scholarshipdb://def456",
                message="New Position",
                url="https://example.com/job2",
                user_handle="test",
                created_at="2026-02-01T00:00:00Z",  # New
                source="scholarshipdb",
                is_verified_job=True,
            ),
        ]

        with patch.object(source, "_fetch_page", return_value=mock_posts):
            posts, _ = source.fetch_posts(since_timestamp="2026-01-15T00:00:00Z")
            assert len(posts) == 1
            assert posts[0].message == "New Position"
