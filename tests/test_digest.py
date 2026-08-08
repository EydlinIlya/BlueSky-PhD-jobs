"""Tests for subscription digest matching + formatting (pure helpers)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import send_subscription_digests as digest  # noqa: E402


def pos(**kw):
    base = {
        "uri": "at://x", "created_at": "2026-06-01T00:00:00+00:00",
        "disciplines": ["Biology"], "country": "Germany",
        "position_type": ["PhD Student"], "user_handle": "alice.bsky.social",
        "message": "Fully funded PhD in plant genomics", "url": "https://bsky.app/x",
    }
    base.update(kw)
    return base


def test_empty_subscription_matches_anything():
    sub = {"disciplines": [], "countries": [], "position_types": []}
    assert digest.position_matches(sub, pos()) is True


def test_discipline_filter_or_within():
    sub = {"disciplines": ["Computer Science", "Biology"]}
    assert digest.position_matches(sub, pos(disciplines=["Biology"])) is True
    assert digest.position_matches(sub, pos(disciplines=["Physics"])) is False


def test_country_and_type_and_across():
    sub = {"countries": ["Germany"], "position_types": ["Postdoc"]}
    assert digest.position_matches(sub, pos(country="Germany", position_type=["Postdoc"])) is True
    # country matches but type doesn't -> AND across fails
    assert digest.position_matches(sub, pos(country="Germany", position_type=["PhD Student"])) is False


def test_query_text_substring():
    sub = {"query_text": "genomics"}
    assert digest.position_matches(sub, pos()) is True
    assert digest.position_matches(sub, pos(message="quantum optics role")) is False


def test_hide_aggregators(monkeypatch):
    monkeypatch.setattr(digest, "AGGREGATORS", {"bot.bsky.social"})
    sub = {"hide_aggregators": True}
    assert digest.position_matches(sub, pos(user_handle="bot.bsky.social")) is False
    assert digest.position_matches(sub, pos(user_handle="alice.bsky.social")) is True


def test_subscription_label():
    assert digest.subscription_label({"disciplines": ["Biology"], "countries": ["Germany"]}) == "Biology · Germany"
    assert digest.subscription_label({}) == "all positions"


def test_format_digest_html_includes_count_and_link():
    sub = {"disciplines": ["Biology"]}
    body = digest.format_digest_html(sub, [pos(), pos(uri="at://y")])
    assert "2 new positions" in body
    assert "https://bsky.app/x" in body
    assert "Biology" in body


# ── Overflow disclosure + watermark semantics ───────────────────────────────

def test_digest_discloses_matches_beyond_the_display_cap():
    """The cap used to drop matches silently while the watermark advanced past
    them, so they were never emailed again. Now the overflow is stated."""
    n = digest.MAX_POSITIONS_PER_DIGEST + 12
    positions = [pos(uri=f"at://x{i}") for i in range(n)]
    body = digest.format_digest_html({"disciplines": ["Biology"]}, positions)

    assert f"{n} new positions" in body
    assert f"Showing the {digest.MAX_POSITIONS_PER_DIGEST} most recent" in body
    assert "Browse the other 12 on PhD Sky" in body
    # Only the capped number of entries are actually rendered.
    assert body.count("View position →") == digest.MAX_POSITIONS_PER_DIGEST


def test_no_overflow_note_when_everything_fits():
    body = digest.format_digest_html({}, [pos(), pos(uri="at://y")])
    assert "Showing the" not in body
    assert "Browse the other" not in body
    assert body.count("View position →") == 2


def test_watermark_falls_back_to_created_at():
    """A never-notified subscription reports positions since it was created,
    not the entire archive."""
    assert digest.subscription_watermark(
        {"last_notified_at": "2026-07-01T00:00:00+00:00",
         "created_at": "2026-01-01T00:00:00+00:00"}) == "2026-07-01T00:00:00+00:00"
    assert digest.subscription_watermark(
        {"last_notified_at": None,
         "created_at": "2026-01-01T00:00:00+00:00"}) == "2026-01-01T00:00:00+00:00"
    assert digest.subscription_watermark({}) is None
