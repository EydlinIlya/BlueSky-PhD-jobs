"""Regression tests for HTML-safe JSON embedding in scripts/generate_seo_pages.py.

Position `message` is verbatim Bluesky post text, i.e. fully attacker-authored.
It gets embedded into <script> elements in docs/index.html and the per-job
pages. json.dumps does NOT escape `<`, `>` or `&`, so a post containing the
literal `</script>` used to terminate the element early and execute the rest of
the post as markup on phdsky.org (stored XSS -> Supabase session theft).
"""

import importlib.util
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The module reads SUPABASE_* at import time.
os.environ.setdefault("SUPABASE_URL", "https://example.invalid")
os.environ.setdefault("SUPABASE_KEY", "test-key")

_spec = importlib.util.spec_from_file_location(
    "generate_seo_pages", REPO / "scripts" / "generate_seo_pages.py"
)
gsp = importlib.util.module_from_spec(_spec)
sys.modules["generate_seo_pages"] = gsp
_spec.loader.exec_module(gsp)


BREAKOUT = '</script><img src=x onerror=alert(document.domain)>'


class _TagCollector(HTMLParser):
    """Collects elements the browser would actually construct."""

    def __init__(self):
        super().__init__()
        self.injected = []
        self._in_static = False
        self.static_payload = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("img", "svg", "iframe"):
            self.injected.append((tag, dict(attrs)))
        if tag == "script" and dict(attrs).get("id") == "static-positions":
            self._in_static = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_static = False

    def handle_data(self, data):
        if self._in_static:
            self.static_payload += data


def _position(message):
    return {
        "uri": "at://did:plc:test/app.bsky.feed.post/3testslug000",
        "created_at": "2026-08-07T11:00:00+00:00",
        "disciplines": ["Biology"],
        "country": "Ireland",
        "position_type": ["PhD Student"],
        "user_handle": "attacker.bsky.social",
        "message": message,
        "url": "https://bsky.app/profile/attacker.bsky.social/post/3testslug000",
    }


@pytest.mark.parametrize("payload", [
    BREAKOUT,
    "</SCRIPT ><svg onload=alert(1)>",
    "benign & normal <text> with angle brackets",
])
def test_json_for_script_removes_breakout_characters(payload):
    out = gsp.json_for_script({"positions": [{"message": payload}]})
    assert "<" not in out and ">" not in out and "&" not in out
    assert "</script" not in out.lower()


def test_json_for_script_is_lossless():
    """JSON.parse in the browser must recover the byte-identical original."""
    payload = BREAKOUT + " unicode: ’   emoji \U0001f9ea"
    restored = json.loads(gsp.json_for_script({"m": payload}))["m"]
    assert restored == payload


def test_index_html_does_not_let_post_text_become_markup(tmp_path, monkeypatch):
    """End-to-end: a malicious post must stay inert data inside the script tag."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.html").write_text(
        "<html><head></head><body>\n"
        "    <!-- App script -->\n"
        "</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(gsp, "DOCS_DIR", str(docs))

    message = f"Fully funded PhD position in Biology {BREAKOUT}"
    gsp.update_index_html([_position(message)], total_count=1)

    html = (docs / "index.html").read_text(encoding="utf-8")
    collector = _TagCollector()
    collector.feed(html)

    assert collector.injected == [], (
        f"post text escaped the script element and became real markup: {collector.injected}"
    )
    parsed = json.loads(collector.static_payload)
    assert parsed["positions"][0]["message"] == message


def test_job_posting_ld_json_is_script_safe():
    """The per-job page's JobPosting block is built from the same post text."""
    page = gsp.render_position_page(_position(f"Postdoc role {BREAKOUT}"), "3testslug000")
    collector = _TagCollector()
    collector.feed(page)
    assert collector.injected == []


# ── /positions listing: pagination, facets, internal linking ────────────────

def _corpus(n=45):
    """Synthetic corpus spanning two disciplines and two countries."""
    rows = []
    for i in range(n):
        rows.append({
            "uri": f"at://did:plc:test/app.bsky.feed.post/3slug{i:05d}",
            "created_at": f"2026-08-{(i % 28) + 1:02d}T10:00:00+00:00",
            "disciplines": ["Biology"] if i % 2 else ["Computer Science"],
            "country": "Germany" if i % 3 else "USA",
            "position_type": ["PhD Student"],
            "user_handle": "lab.bsky.social",
            "message": f"Position number {i}. " + "detail " * 30,
            "url": f"https://bsky.app/profile/lab.bsky.social/post/3slug{i:05d}",
        })
    return rows


@pytest.fixture
def generated(tmp_path, monkeypatch):
    monkeypatch.setattr(gsp, "DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(gsp, "POSITIONS_PER_PAGE", 20)
    rows = _corpus()
    urls = gsp.generate_positions_html(rows)
    return tmp_path, rows, urls


def _all_listing_html(root):
    files = [root / "positions.html"]
    for sub in ("positions", "area", "country"):
        files += sorted((root / sub).glob("*.html")) if (root / sub).is_dir() else []
    return files


def test_every_position_is_linked_from_a_listing_page(generated):
    """The whole point of paginating: no per-job page left sitemap-only."""
    root, rows, _ = generated
    linked = set()
    for f in _all_listing_html(root):
        linked |= set(re.findall(r'href="/p/([A-Za-z0-9_-]+)"', f.read_text(encoding="utf-8")))
    expected = {gsp.extract_slug(r["uri"]) for r in rows}
    assert expected - linked == set(), "some positions are reachable only via the sitemap"


def test_pagination_covers_corpus_with_prev_next(generated):
    root, rows, _ = generated
    pages = [root / "positions.html"] + sorted((root / "positions").glob("*.html"))
    assert len(pages) == 3  # 45 rows / 20 per page

    first = (root / "positions.html").read_text(encoding="utf-8")
    assert 'rel="next"' in first and 'rel="prev"' not in first
    assert 'rel="canonical" href="https://phdsky.org/positions"' in first

    last = (root / "positions" / "3.html").read_text(encoding="utf-8")
    assert 'rel="prev"' in last and 'rel="next"' not in last
    assert 'rel="canonical" href="https://phdsky.org/positions/3"' in last


def test_listing_uses_collectionpage_not_dataset(generated):
    """Dataset was the wrong type and asserted CC0 over posts we don't own."""
    root, _, _ = generated
    for f in _all_listing_html(root):
        html = f.read_text(encoding="utf-8")
        blocks = re.findall(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S
        )
        assert blocks, f"{f.name} has no JSON-LD"
        for block in blocks:
            data = json.loads(block)  # must parse after \uXXXX escaping
            assert data["@type"] == "CollectionPage"
            assert data["mainEntity"]["@type"] == "ItemList"
        assert '"Dataset"' not in html


def test_facet_hubs_skip_thin_and_junk_buckets(tmp_path, monkeypatch):
    monkeypatch.setattr(gsp, "DOCS_DIR", str(tmp_path))
    rows = _corpus()
    # One junk-label and one below-threshold bucket; neither should get a hub.
    rows.append({**rows[0], "uri": "at://x/y/3junk0", "disciplines": ["General call"]})
    rows.append({**rows[0], "uri": "at://x/y/3rare0", "disciplines": ["Underwater Basketry"]})
    gsp.generate_positions_html(rows)

    areas = {p.stem for p in (tmp_path / "area").glob("*.html")}
    assert "biology" in areas and "computer-science" in areas
    assert "general-call" not in areas, "catch-all label should not become a landing page"
    assert "underwater-basketry" not in areas, "below FACET_MIN_POSITIONS should be skipped"


def test_listing_pages_do_not_execute_post_text(tmp_path, monkeypatch):
    monkeypatch.setattr(gsp, "DOCS_DIR", str(tmp_path))
    rows = _corpus(10)
    rows[0]["message"] = f"Biology PhD {BREAKOUT}"
    gsp.generate_positions_html(rows)
    for f in _all_listing_html(tmp_path):
        collector = _TagCollector()
        collector.feed(f.read_text(encoding="utf-8"))
        assert collector.injected == [], f"markup injected into {f.name}"


def test_stale_pages_are_cleaned_up(tmp_path, monkeypatch):
    """A shrinking corpus must not leave orphaned pages serving 200s."""
    monkeypatch.setattr(gsp, "DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(gsp, "POSITIONS_PER_PAGE", 20)
    gsp.generate_positions_html(_corpus(45))
    assert (tmp_path / "positions" / "3.html").exists()

    gsp.generate_positions_html(_corpus(20))  # now fits on one page
    assert not (tmp_path / "positions" / "3.html").exists()


def test_sitemap_lists_hubs_without_duplicating_page_one(tmp_path, monkeypatch):
    monkeypatch.setattr(gsp, "DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(gsp, "POSITIONS_PER_PAGE", 20)
    urls = gsp.generate_positions_html(_corpus())
    gsp.generate_sitemap({"3slug00000": "2026-08-01"}, urls)

    xml = (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>(.*?)</loc>", xml)
    assert len(locs) == len(set(locs)), "duplicate <loc> entries in sitemap"
    assert "https://phdsky.org/positions" in locs
    assert "https://phdsky.org/positions/2" in locs
    assert any("/area/" in u for u in locs) and any("/country/" in u for u in locs)
