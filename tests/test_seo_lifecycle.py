"""Tests for the shared active/archive/SEO-eligibility policy."""

from datetime import datetime, timedelta, timezone

from src.seo import is_position_active, is_seo_eligible, lifecycle_state


NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def position(**overrides):
    row = {
        "created_at": (NOW - timedelta(days=10)).isoformat(),
        "application_deadline": None,
        "is_verified_job": True,
        "job_title": "Postdoctoral Fellow in Coastal Ecology",
        "hiring_organization": "University of Haifa",
        "application_url": "https://jobs.example.edu/postings/123",
        "country": "Israel",
        "message": "We invite applications for a postdoctoral fellow in coastal ecology. "
        "The researcher will combine field observations, modelling, and collaborative analysis.",
    }
    row.update(overrides)
    return row


def test_no_deadline_is_active_on_90_day_boundary():
    assert is_position_active(position(created_at=(NOW - timedelta(days=90)).isoformat()), now=NOW)


def test_no_deadline_is_archived_after_90_day_boundary():
    assert not is_position_active(
        position(created_at=(NOW - timedelta(days=90, seconds=1)).isoformat()), now=NOW
    )


def test_explicit_deadline_overrides_post_age():
    old = (NOW - timedelta(days=200)).isoformat()
    assert is_position_active(position(created_at=old, application_deadline="2026-09-16"), now=NOW)
    assert not is_position_active(position(created_at=old, application_deadline="2026-09-15"), now=NOW)


def test_malformed_deadline_falls_back_to_post_age():
    assert is_position_active(position(application_deadline="September sometime"), now=NOW)
    assert not is_position_active(
        position(
            created_at=(NOW - timedelta(days=100)).isoformat(),
            application_deadline="31/31/2026",
        ),
        now=NOW,
    )


def test_missing_or_malformed_post_date_is_archived():
    assert not is_position_active(position(created_at=None), now=NOW)
    assert not is_position_active(position(created_at="not-a-date"), now=NOW)


def test_complete_active_position_is_eligible():
    assert is_seo_eligible(position(), now=NOW)
    assert lifecycle_state(position(), now=NOW) == "eligible"


def test_eligibility_rejects_unverified_or_incomplete_rows():
    assert not is_seo_eligible(position(is_verified_job=False), now=NOW)
    assert not is_seo_eligible(position(job_title=None), now=NOW)
    assert not is_seo_eligible(position(hiring_organization=""), now=NOW)
    assert not is_seo_eligible(position(country="Unknown"), now=NOW)
    assert not is_seo_eligible(position(message="Short post"), now=NOW)


def test_eligibility_rejects_bad_or_social_application_urls():
    assert not is_seo_eligible(position(application_url="javascript:alert(1)"), now=NOW)
    assert not is_seo_eligible(
        position(application_url="https://bsky.app/profile/lab/post/abc"), now=NOW
    )


def test_active_but_incomplete_is_weak_and_expired_is_archived():
    assert lifecycle_state(position(job_title=None), now=NOW) == "weak"
    assert lifecycle_state(position(application_deadline="2026-09-15"), now=NOW) == "archived"
