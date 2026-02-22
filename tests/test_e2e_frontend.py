"""End-to-end tests for the frontend using Playwright.

These tests verify the frontend loads correctly and displays position data.
They require network access to Supabase (the duplicate_of column must exist).

Run:
    python -m pytest tests/test_e2e_frontend.py -v

Requires:
    pip install pytest-playwright
    playwright install chromium
"""

import subprocess
import socket
import time

import pytest


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    """Start a local HTTP server serving docs/."""
    port = _free_port()
    proc = subprocess.Popen(
        ["python", "-m", "http.server", str(port), "--directory", "docs"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    yield f"http://localhost:{port}"
    proc.terminate()
    proc.wait(timeout=5)


class TestFrontendLoads:
    """Test that the frontend loads and displays data from Supabase."""

    def test_page_title(self, server_url, page):
        page.goto(server_url)
        assert "PhD" in page.title()

    def test_positions_load(self, server_url, page):
        """Verify positions load from Supabase and cards are rendered."""
        page.goto(server_url)
        page.wait_for_selector(".position-card, #error:not(.hidden)", timeout=15000)
        cards = page.query_selector_all(".position-card")
        assert len(cards) > 0, "No position cards rendered"

    def test_no_error_message(self, server_url, page):
        """Verify no error message is shown."""
        page.goto(server_url)
        page.wait_for_selector(".position-card, #error:not(.hidden)", timeout=15000)
        error_el = page.query_selector("#error")
        if error_el:
            assert "hidden" in (error_el.get_attribute("class") or ""), \
                "Error message is visible — data failed to load"

    def test_no_js_exceptions(self, server_url, page):
        """Verify no uncaught JS exceptions."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(server_url)
        page.wait_for_selector(".position-card, #error:not(.hidden)", timeout=15000)
        assert errors == [], f"JS exceptions: {errors}"

    def test_card_has_required_elements(self, server_url, page):
        """Verify cards have the expected structure."""
        page.goto(server_url)
        page.wait_for_selector(".position-card", timeout=15000)
        first_card = page.query_selector(".position-card")
        assert first_card.query_selector(".card-header"), "Card missing header"
        assert first_card.query_selector(".card-message"), "Card missing message"
        assert first_card.query_selector(".card-actions"), "Card missing actions"

    def test_search_filters_cards(self, server_url, page):
        """Verify search input filters the displayed cards."""
        page.goto(server_url)
        page.wait_for_selector(".position-card", timeout=15000)
        initial_count = len(page.query_selector_all(".position-card"))
        assert initial_count > 0

        page.fill("#global-search", "xyznonexistent12345")
        page.click("button:has-text('Search')")
        page.wait_for_timeout(500)

        filtered_count = len(page.query_selector_all(".position-card"))
        assert filtered_count < initial_count, "Search did not filter cards"

    def test_filter_panel_visible(self, server_url, page):
        """Verify filter panel is present."""
        page.goto(server_url)
        page.wait_for_selector(".position-card", timeout=15000)
        assert page.query_selector("#filter-panel"), "Filter panel not found"

    def test_card_count_displayed(self, server_url, page):
        """Verify the card count text is shown."""
        page.goto(server_url)
        page.wait_for_selector(".position-card", timeout=15000)
        count_el = page.query_selector("#card-count")
        assert count_el, "Card count element not found"
        text = count_el.text_content()
        assert "positions" in text.lower(), f"Unexpected count text: {text}"
