"""Static launch-safety invariants for legal copy, consent, UI, and deployment."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_legal_identity_jurisdiction_and_section_11_notice_are_complete():
    terms = read("docs/terms.html")
    privacy = read("docs/privacy.html")
    combined = terms + privacy
    assert "Eli Eydlin" in terms and "State of Israel" in terms
    assert "[your country" not in combined and "set your jurisdiction" not in combined
    assert "fair-use/public" not in combined
    for phrase in (
        "Providing account, profile, saved-search, follow, and email-alert information is voluntary",
        "If you do not provide an email",
        "database controller",
        "Purposes",
        "Recipients and international processing",
        "Access, correction, export, deletion, and objection",
    ):
        assert phrase in privacy


def test_product_and_legal_claims_match():
    terms = read("docs/terms.html")
    privacy = read("docs/privacy.html")
    app = read("docs/app.js")
    assert "Saving a search does <strong>not</strong> subscribe" in terms
    assert "Saving a search does not turn on email" in privacy
    assert "deliver_email: false" in app
    assert "email_consent_at" in app
    assert "Start weekly emails" in app
    assert "does not sell this data or use it to train AI models" in app


def test_no_preconsent_analytics_or_third_party_asset_cdns_in_document():
    index = read("docs/index.html")
    tokens = read("docs/colors_and_type.css")
    assert "googletagmanager.com" not in index
    assert "/_vercel/insights/script.js" not in index
    assert "cdn.jsdelivr.net" not in index
    assert "fonts.googleapis.com" not in tokens
    assert "fonts.gstatic.com" not in tokens
    assert "phdsky_consent" in read("docs/app.js")


def test_account_routes_and_controls_are_real():
    index = read("docs/index.html")
    app = read("docs/app.js")
    assert 'id="view-account"' in index
    assert "delete_own_account" in app
    assert "Download JSON export" in app
    assert "Type DELETE to confirm" in app
    assert "showPreferences" in app
    searchable = "\n".join(read(path) for path in (
        "docs/index.html", "docs/about.html", "docs/privacy.html", "docs/terms.html",
        "docs/unsubscribe.html", "scripts/send_subscription_digests.py",
    ))
    assert 'href="/account"' not in searchable


def test_search_enter_does_not_save_or_subscribe():
    app = read("docs/app.js")
    enter_block = app[app.index("if (e.key === 'Enter')"):app.index("// hide-aggregator chip")]
    assert "saveCurrentSearch" not in enter_block
    assert "openAuth" not in enter_block
    assert "Search applied" in enter_block


def test_unsubscribe_page_is_confirmation_only_and_endpoint_is_post_only():
    page = read("docs/unsubscribe.html")
    endpoint = read("api/unsubscribe.js")
    assert "Opening this page has not changed" in page
    assert "Unsubscribe this alert" in page and "Stop all weekly emails" in page
    assert "method: 'POST'" in page
    assert "window.supabase" not in page
    assert 'request.method !== "POST"' in endpoint
    assert "sendJson(response, 405" in endpoint
    assert "List-Unsubscribe=One-Click" in read("scripts/send_subscription_digests.py")


def test_migration_and_weekly_workflow_contract():
    migration = read("migrations/008_subscription_compliance.sql")
    workflow = read(".github/workflows/subscription-digests.yml")
    for field in ("email_consent_at", "email_consent_version", "unsubscribed_at", "last_processed_at"):
        assert field in migration
    assert "subscriptions_unique_normalized_filter_idx" in migration
    assert "unsubscribe_subscription_by_token" in migration
    assert "unsubscribe_all_by_token" in migration
    assert "delete_own_account" in migration
    assert 'cron: "0 9 * * 1"' in workflow
    assert "daily" not in workflow.lower() and "instant" not in workflow.lower()
    assert "vars." not in workflow and "SUPABASE_KEY:" not in workflow


def test_research_library_assets_and_semantics_are_present():
    tokens = read("docs/colors_and_type.css")
    styles = read("docs/styles.css")
    index = read("docs/index.html")
    for color in ("#F3F5F2", "#FFFFFF", "#18201D", "#55625C", "#C8D0CB", "#18594A", "#315F78", "#B54632"):
        assert color in tokens
    assert "Literata" in tokens and "Atkinson Hyperlegible" in tokens and "IBM Plex Mono" in tokens
    assert "linear-gradient" not in styles
    assert 'role="dialog"' in index and 'aria-live="polite"' in index
    assert ":focus-visible" in styles
    for asset in ("docs/favicon.svg", "docs/favicon-16.png", "docs/favicon-32.png", "docs/apple-touch-icon.png", "docs/site.webmanifest"):
        assert (ROOT / asset).is_file()
