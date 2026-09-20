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

    def test_auth_pending_state_never_renders_signed_out_actions(self, server_url, page):
        open_feed(page, server_url)
        page.evaluate("""() => {
          state.user = null;
          state.authReady = false;
          renderTopbar();
          renderRailSubs();
        }""")
        assert page.locator("#top-account").get_attribute("aria-busy") == "true"
        assert page.locator("#top-account .auth-placeholder").count() == 1
        assert page.locator("#top-account .btn-signin").count() == 0
        assert page.locator("#top-account .btn-signup").count() == 0
        assert page.locator("#rail-subs-section .rail-nudge").count() == 0

    def test_impossible_old_deadline_falls_back_to_post_age(self, server_url, page):
        open_feed(page, server_url)
        active = page.evaluate("""() => isActivePosition({
          created_at: '2026-09-16T22:32:59.414+00:00',
          application_deadline: '2024-10-16',
          message: 'Applications close on October 16.'
        }, new Date('2026-09-17T12:00:00Z'))""")
        assert active is True

    def test_only_contextual_deadlines_override_post_age(self, server_url, page):
        open_feed(page, server_url)
        result = page.evaluate("""() => ({
          jobIdDate: isActivePosition({
            created_at: '2026-07-02T11:24:34Z',
            application_deadline: '2026-06-28',
            message: 'Postdoctoral researcher. Job ID: 28/06/26.'
          }, new Date('2026-09-18T12:00:00Z')),
          explicitDeadline: isActivePosition({
            created_at: '2026-07-02T11:24:34Z',
            application_deadline: '2026-06-28',
            message: 'Application deadline: June 28, 2026.'
          }, new Date('2026-09-18T12:00:00Z')),
          shortYearDeadline: isActivePosition({
            created_at: '2026-08-25T06:13:54Z',
            application_deadline: '2026-09-01',
            message: 'One more week to apply (deadline 01.09.26).'
          }, new Date('2026-09-18T12:00:00Z')),
          mojibakeHourglass: isActivePosition({
            created_at: '2026-08-29T07:10:18Z',
            application_deadline: '2026-09-11',
            message: String.fromCharCode(0x00e2, 0xdc8f, 0x00b3) + ' 11 Sep 2026'
          }, new Date('2026-09-18T12:00:00Z')),
          linkedPreviewDeadline: isActivePosition({
            created_at: '2026-09-02T10:00:00Z',
            application_deadline: '2026-09-15',
            message: 'PhD position. See the official vacancy page.'
          }, new Date('2026-09-18T12:00:00Z')),
          deadlineRange: isActivePosition({
            created_at: '2026-07-23T09:00:36Z',
            application_deadline: '2027-02-01',
            message: 'Applications are accepted from 1 February 2024 to 1 February 2027.'
          }, new Date('2026-09-18T12:00:00Z'))
        })""")
        assert result == {
            "jobIdDate": True,
            "explicitDeadline": False,
            "shortYearDeadline": False,
            "mojibakeHourglass": False,
            "linkedPreviewDeadline": False,
            "deadlineRange": True,
        }

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

    def test_archive_tab_count_respects_the_current_filters(self, server_url, page):
        open_feed(page, server_url)
        page.locator('[data-tab="archive"]').click()
        page.wait_for_selector("article.post", timeout=15000)
        total = page.locator("#tab-archive-ct").inner_text().strip()
        page.evaluate("""() => {
          state.search = 'this-string-matches-no-archive-position';
          renderFeedReset();
        }""")
        assert total != "0"
        assert page.locator("#tab-archive-ct").inner_text().strip() == "0"

    def test_keyboard_shortcut_focuses_search(self, server_url, page):
        open_feed(page, server_url)
        page.keyboard.press("Control+k")
        assert page.locator("#cmd-input").evaluate("el => el === document.activeElement")

    def test_desktop_search_expands_when_focused(self, server_url, page):
        page.set_viewport_size({"width": 1440, "height": 900})
        open_feed(page, server_url)
        search = page.locator(".command-bar")
        before = search.bounding_box()
        page.locator("#cmd-input").focus()
        page.wait_for_timeout(300)
        after = search.bounding_box()
        assert before is not None and after is not None
        assert after["width"] >= before["width"] + 150

    def test_subscription_show_matches_restores_saved_filters(self, server_url, page):
        open_feed(page, server_url)
        page.evaluate("""() => {
          state.user = {id: 'test-user', email: 'reader@example.com'};
          state.subs = [{
            id: 'sub-1', query_text: 'Machine Learning',
            disciplines: ['Computer Science'], countries: [], position_types: [],
            hide_aggregators: false, cadence: 'weekly'
          }];
          setView('subs');
        }""")
        page.locator('[data-view-sub="sub-1"]').click()
        page.wait_for_timeout(250)
        assert page.locator("#cmd-input").input_value() == "Machine Learning"
        assert page.locator('[data-tab="latest"]').get_attribute("aria-selected") == "true"
        assert "on" in page.locator('#chips-area .chip[data-area="Computer Science"]').get_attribute("class")
        assert page.locator("article.post").count() > 0

    def test_paused_subscription_can_be_turned_back_on(self, server_url, page):
        open_feed(page, server_url)
        page.evaluate("""() => {
          state.user = {id: 'test-user', email: 'reader@example.com'};
          state.subs = [{
            id: 'sub-paused', query_text: 'israel', disciplines: [], countries: [],
            position_types: [], hide_aggregators: false, cadence: 'off',
            deliver_email: false
          }];
          updateSub = async (id, fields) => {
            Object.assign(state.subs.find(item => item.id === id), fields);
            renderRailSubs();
            renderSubsPage();
            return true;
          };
          setView('subs');
        }""")
        assert page.locator(".sub-email-status").inner_text() == "Email paused"
        page.locator('[data-toggle-sub-email="sub-paused"]').click()
        page.wait_for_timeout(100)
        assert page.locator(".sub-email-status").inner_text() == "Email on"
        assert page.locator('[data-toggle-sub-email="sub-paused"]').inner_text() == "Pause email"
        state = page.evaluate("""() => ({
          deliver_email: state.subs[0].deliver_email,
          cadence: state.subs[0].cadence,
          last_notified_at: state.subs[0].last_notified_at
        })""")
        assert state["deliver_email"] is True
        assert state["cadence"] == "weekly"
        assert state["last_notified_at"]

    def test_unsubscribe_page_waits_for_confirmation(self, server_url, page):
        requests = []

        def respond(route, request):
            requests.append({"method": request.method, "url": request.url})
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

        page.route("**/api/unsubscribe?**", respond)
        root = server_url.split("/?", 1)[0]
        token = "4e162b33-229b-441a-b655-1fd560765037"
        page.goto(f"{root}/unsubscribe.html?token={token}", wait_until="domcontentloaded")
        page.wait_for_timeout(200)
        assert requests == []
        assert page.locator("#card-title").inner_text() == "Stop this weekly email?"
        page.locator("#confirm-unsubscribe").click()
        page.wait_for_selector("text=Weekly email stopped.")
        assert requests == [{
            "method": "POST",
            "url": f"{root}/api/unsubscribe?token={token}",
        }]
        assert page.locator('a[href="/#subscriptions"]').count() == 1
