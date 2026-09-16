"""Current frontend smoke tests using the bundled ``?mock`` data path.

The suite is intentionally independent of Supabase and external listing state.
It exercises the selectors and interaction model that the v3 feed actually
ships instead of the removed card-grid UI.
"""

import socket
import subprocess
import sys
import time

import pytest


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", "docs"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    yield f"http://localhost:{port}/?mock"
    proc.terminate()
    proc.wait(timeout=5)


def open_feed(page, server_url):
    page.goto(server_url, wait_until="domcontentloaded")
    page.wait_for_selector("article.post", timeout=15000)


class TestFrontendLoads:
    def test_page_identity_and_visible_heading(self, server_url, page):
        open_feed(page, server_url)
        assert "PhD" in page.title()
        assert "Current PhD" in page.locator("h1").inner_text()

    def test_positions_render_from_mock_data(self, server_url, page):
        open_feed(page, server_url)
        assert page.locator("article.post").count() > 0

    def test_no_js_exceptions(self, server_url, page):
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        open_feed(page, server_url)
        page.wait_for_timeout(250)
        assert errors == []

    def test_post_has_explicit_content_and_actions(self, server_url, page):
        open_feed(page, server_url)
        first = page.locator("article.post").first
        assert first.locator(".p-head").count() == 1
        assert first.locator(".p-body").count() == 1
        assert first.locator(".p-actions a").count() >= 1
        assert first.locator("a.p-time[href^='/p/']").count() == 1

    def test_search_filters_feed(self, server_url, page):
        open_feed(page, server_url)
        initial_count = page.locator("article.post").count()
        page.locator("#cmd-input").fill("xyznonexistent12345")
        page.wait_for_timeout(350)
        assert page.locator("article.post").count() < initial_count
        assert page.locator(".feed-empty").count() == 1

    def test_filter_rail_and_count_are_present(self, server_url, page):
        open_feed(page, server_url)
        assert page.locator("#left-rail").count() == 1
        assert page.locator("#chips-level .chip").count() > 0
        assert page.locator("#tab-latest-ct").inner_text().strip()

    def test_archive_tab_loads_historical_positions(self, server_url, page):
        open_feed(page, server_url)
        page.locator('[data-tab="archive"]').click()
        page.wait_for_selector("article.post", timeout=15000)
        assert "Archived" in page.locator("#river-title").inner_text()
        assert "older than 90 days" in page.locator("#river-description").inner_text()
        assert page.locator('[data-tab="archive"]').get_attribute("aria-selected") == "true"

    def test_keyboard_shortcut_focuses_search(self, server_url, page):
        open_feed(page, server_url)
        page.keyboard.press("Control+k")
        assert page.locator("#cmd-input").evaluate("el => el === document.activeElement")
