"""Tests for the shared active/archive/SEO-eligibility policy."""

from datetime import datetime, timedelta, timezone

from src.seo import effective_deadline, is_position_active, is_seo_eligible, lifecycle_state


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


def test_deadline_before_source_post_is_ignored_as_impossible():
    row = position(
        created_at="2026-09-16T22:32:59+00:00",
        application_deadline="2024-10-16",
    )

    assert effective_deadline(row) is None
    assert is_position_active(row, now=NOW + timedelta(days=1))
    assert is_seo_eligible(row, now=NOW + timedelta(days=1))


def test_contextual_yearless_deadline_uses_posting_year():
    row = position(
        created_at="2026-09-16T22:32:59+00:00",
        application_deadline="2024-10-16",
        message=(
            "Applications close on October 16. We invite researchers to join "
            "this interdisciplinary project combining field observations, "
            "modelling, and collaborative scientific analysis."
        ),
    )

    assert effective_deadline(row).isoformat() == "2026-10-16"
    assert is_position_active(row, now=NOW + timedelta(days=1))


def test_contextual_yearless_deadline_rolls_to_next_year():
    row = position(
        created_at="2026-09-16T22:32:59+00:00",
        application_deadline="2026-02-15",
        message="Applications close on February 15.",
    )

    assert effective_deadline(row).isoformat() == "2027-02-15"


def test_job_id_date_is_not_a_deadline():
    row = position(
        created_at="2026-07-02T11:24:34+00:00",
        application_deadline="2026-06-28",
        message="Postdoctoral researcher in crop science. Job ID: 28/06/26.",
    )

    assert effective_deadline(row) is None
    assert is_position_active(row, now=datetime(2026, 9, 18, tzinfo=timezone.utc))


def test_contextual_two_digit_year_is_accepted():
    row = position(
        created_at="2026-08-25T06:13:54+00:00",
        application_deadline="2026-09-01",
        message="One more week to apply (deadline 01.09.26).",
    )

    assert effective_deadline(row).isoformat() == "2026-09-01"


def test_mojibake_hourglass_marker_is_deadline_context():
    row = position(
        created_at="2026-08-29T07:10:18+00:00",
        application_deadline="2026-09-11",
        message="Research Assistant\n\xe2\udc8f\xb3 11 Sep 2026 · salary listed",
    )

    assert effective_deadline(row).isoformat() == "2026-09-11"


def test_full_date_without_deadline_context_is_ignored_when_not_future():
    row = position(
        created_at="2026-09-16T22:32:59+00:00",
        application_deadline="2026-09-15",
        message="Vacancy announcement published September 15, 2026.",
    )

    assert effective_deadline(row) is None
    assert is_position_active(row, now=NOW + timedelta(days=1))


def test_future_stored_deadline_can_come_from_linked_preview():
    row = position(
        created_at="2026-09-02T10:00:00+00:00",
        application_deadline="2026-09-15",
        message="PhD position in plant ecology. See the official vacancy page.",
    )

    assert effective_deadline(row).isoformat() == "2026-09-15"
    assert not is_position_active(row, now=datetime(2026, 9, 18, tzinfo=timezone.utc))


def test_deadline_range_prefers_candidate_end_year():
    row = position(
        created_at="2026-07-23T09:00:36+00:00",
        application_deadline="2027-02-01",
        message=(
            "Open Call applications are accepted from 1 February 2024 "
            "to 1 February 2027."
        ),
    )

    assert effective_deadline(row).isoformat() == "2027-02-01"
    assert is_position_active(row, now=datetime(2026, 9, 18, tzinfo=timezone.utc))


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
