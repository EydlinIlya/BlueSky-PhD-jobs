"""Playwright checks for the current ?mock feed, keyboard, dialogs, and layout.

Run with:
    python -m pytest tests/test_e2e_frontend.py -v
"""

import socket
import subprocess
import sys
import time

import pytest

pytest.importorskip("playwright.sync_api")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", "docs"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    yield f"http://localhost:{port}/?mock"
    process.terminate()
    process.wait(timeout=5)


def open_mock(page, server_url):
    page.goto(server_url)
    page.wait_for_selector("article.post", timeout=15_000)
    necessary = page.get_by_role("button", name="Necessary only")
    if necessary.is_visible():
        necessary.click()


def test_current_feed_loads_without_console_errors(page, server_url):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    open_mock(page, server_url)
    assert "PhD" in page.title()
    assert page.locator("article.post").count() > 0
    assert errors == []


def test_search_enter_applies_but_does_not_subscribe(page, server_url):
    open_mock(page, server_url)
    page.locator("#cmd-input").fill("xyznonexistent12345")
    page.locator("#cmd-input").press("Enter")
    page.wait_for_selector(".feed-empty")
    assert not page.locator("#modal-auth").evaluate("element => element.classList.contains('open')")
    assert "not been saved or subscribed" in page.locator("#toast-wrap").inner_text()


def test_keyboard_filter_and_dialog_focus_restoration(page, server_url):
    open_mock(page, server_url)
    chip = page.locator("button.chip[data-level]").first
    chip.focus()
    page.keyboard.press("Enter")
    assert chip.get_attribute("aria-pressed") == "true"
    page.keyboard.press("Enter")
    assert chip.get_attribute("aria-pressed") == "false"

    body = page.locator("article.post .p-body").first
    body.click()
    assert page.locator("#flyout").get_attribute("aria-hidden") == "true"

    details = page.locator("article.post .p-actions button[data-detail]").first
    details.focus()
    details.press("Enter")
    assert page.locator("#flyout").get_attribute("aria-hidden") == "false"
    assert page.evaluate("document.activeElement.id") == "flyout-close"
    page.keyboard.press("Shift+Tab")
    assert page.locator("#flyout").evaluate("(root) => root.contains(document.activeElement)")
    page.keyboard.press("Escape")
    assert page.locator("#flyout").get_attribute("aria-hidden") == "true"
    assert details.evaluate("element => element === document.activeElement")


def test_account_deletion_requires_typed_confirmation(page, server_url):
    open_mock(page, server_url)
    page.evaluate("""
      state.user = {id:'mock-user', email:'researcher@example.edu', created_at:'2026-01-01', user_metadata:{full_name:'Researcher'}};
      state.profile = {id:'mock-user', email:'researcher@example.edu', display_name:'Researcher', handle:'lab'};
      setView('account');
    """)
    delete_button = page.locator("#delete-account")
    assert delete_button.is_disabled()
    page.locator("#delete-confirm").fill("delete")
    assert delete_button.is_disabled()
    page.locator("#delete-confirm").fill("DELETE")
    assert delete_button.is_enabled()


def test_optional_analytics_absent_before_consent_and_withdrawal_deletes_ga_cookie(page, server_url):
    open_mock(page, server_url)
    assert page.locator('script[src*="googletagmanager"]').count() == 0
    assert page.locator('script[src="/_vercel/insights/script.js"]').count() == 0
    page.evaluate("document.cookie = '_ga_test=abc; path=/'; withdrawOptionalAnalytics()")
    assert all(cookie["name"] != "_ga_test" for cookie in page.context.cookies())


@pytest.mark.parametrize("width", [375, 768, 1024, 1440])
def test_responsive_layout_and_core_contrast(page, server_url, width):
    page.set_viewport_size({"width": width, "height": 900})
    open_mock(page, server_url)
    metrics = page.evaluate(r"""
      () => {
        const rgb = value => value.match(/\d+/g).slice(0,3).map(Number);
        const lum = value => rgb(value).map(v => v/255).map(v => v <= .03928 ? v/12.92 : ((v+.055)/1.055)**2.4)
          .reduce((sum, v, i) => sum + v * [.2126,.7152,.0722][i], 0);
        const ratio = (a,b) => { const x=lum(a), y=lum(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); };
        const style = getComputedStyle(document.body);
        const inputStyle = getComputedStyle(document.querySelector('#cmd-input'));
        return {
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          contrast: ratio(style.color, style.backgroundColor),
          inputFont: parseFloat(inputStyle.fontSize),
          firstButtonHeight: document.querySelector('.mnav-btn') ? document.querySelector('.mnav-btn').getBoundingClientRect().height : 0,
        };
      }
    """)
    assert metrics["overflow"] <= 1
    assert metrics["contrast"] >= 4.5
    assert metrics["inputFont"] >= 16
    if width <= 768:
        assert metrics["firstButtonHeight"] >= 44
