"""Tests for scripts/repost_to_bluesky.py (no network)."""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.repost_to_bluesky import (
    sanitize_tag,
    build_tags,
    select_candidates,
    repost_position,
)


# --- sanitize_tag ---------------------------------------------------------

def test_sanitize_strips_spaces_and_punctuation():
    assert sanitize_tag("Computer Science") == "ComputerScience"
    assert sanitize_tag("PhD Student") == "PhDStudent"
    assert sanitize_tag("United Kingdom") == "UnitedKingdom"
    assert sanitize_tag("R&D") == "RD"


def test_sanitize_empty():
    assert sanitize_tag("") == ""
    assert sanitize_tag("   ") == ""
    assert sanitize_tag("&&&") == ""


# --- build_tags -----------------------------------------------------------

def test_build_tags_order_level_country_subjects():
    pos = {
        "position_type": ["PhD Student"],
        "country": "Norway",
        "disciplines": ["Biology", "Computer Science"],
    }
    assert build_tags(pos) == ["PhDStudent", "Norway", "Biology", "ComputerScience"]


def test_build_tags_drops_unknown_country():
    pos = {"position_type": ["Postdoc"], "country": "Unknown", "disciplines": ["Physics"]}
    assert build_tags(pos) == ["Postdoc", "Physics"]


def test_build_tags_dedupes():
    pos = {"position_type": ["Biology"], "country": "", "disciplines": ["Biology"]}
    assert build_tags(pos) == ["Biology"]


def test_build_tags_handles_missing_fields():
    assert build_tags({}) == []


# --- select_candidates ----------------------------------------------------

def _row(handle, uri="at://x"):
    return {"user_handle": handle, "uri": uri}


def test_select_excludes_aggregators():
    rows = [_row("agg.bsky.social", "u1"), _row("lab.bsky.social", "u2")]
    aggs = {"agg.bsky.social"}
    out = select_candidates(rows, aggs, limit=10)
    assert [r["uri"] for r in out] == ["u2"]


def test_select_caps_at_limit():
    rows = [_row(f"h{i}.bsky.social", f"u{i}") for i in range(10)]
    out = select_candidates(rows, set(), limit=3)
    assert len(out) == 3


def test_select_empty_when_all_aggregators():
    rows = [_row("agg.bsky.social", "u1")]
    assert select_candidates(rows, {"agg.bsky.social"}, limit=10) == []


# --- repost_position ------------------------------------------------------

def test_repost_dry_run_posts_nothing():
    pos = {"uri": "at://p1", "position_type": ["PhD Student"], "country": "Norway",
           "disciplines": ["Biology"]}
    text = repost_position(client=None, position=pos, dry_run=True)
    assert text == "#PhDStudent #Norway #Biology"


class _FakeClient:
    """Records send_post calls and returns a resolvable strong ref."""

    def __init__(self, cid="cid123", posts=True):
        self._cid = cid
        self._posts = posts
        self.sent = []

    def get_posts(self, uris):
        if not self._posts:
            return SimpleNamespace(posts=[])
        return SimpleNamespace(posts=[SimpleNamespace(uri=uris[0], cid=self._cid)])

    def send_post(self, text, embed=None):
        self.sent.append((text, embed))
        return SimpleNamespace(uri="at://repost", cid="rcid")


def test_repost_live_quote_posts_with_embed():
    client = _FakeClient()
    pos = {"uri": "at://orig", "position_type": ["Postdoc"], "country": "Germany",
           "disciplines": ["Physics"]}
    text = repost_position(client, pos, dry_run=False)
    assert text == "#Postdoc #Germany #Physics"
    assert len(client.sent) == 1
    _, embed = client.sent[0]
    # Embed points at the original's strong ref (uri + cid)
    assert embed.record.uri == "at://orig"
    assert embed.record.cid == "cid123"


def test_repost_skips_when_original_unavailable():
    client = _FakeClient(posts=False)
    pos = {"uri": "at://gone", "position_type": ["PhD Student"], "country": "Spain",
           "disciplines": ["Chemistry"]}
    assert repost_position(client, pos, dry_run=False) is None
    assert client.sent == []
