"""Send saved-search subscription digests by email.

The deployed GitHub workflow uses manual operator mode: it resolves exactly one
configured profile email, aggregates that profile's saved searches into one
message, and advances only its successful-match watermarks. Subscriber-wide
``run()`` remains available in code for a later consented rollout but is not
wired to any workflow or schedule.

Usage:
    python scripts/send_subscription_digests.py --operator-to owner@example.com
    python scripts/send_subscription_digests.py --test-to owner@example.com

Required env:
    SUPABASE_URL
    SUPABASE_SERVICE_KEY   service-role key (bypasses RLS to read all users' subs)
    RESEND_API_KEY, EMAIL_FROM   (see src/email/resend_provider.py)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.email import send_email  # noqa: E402

load_dotenv()

SITE_URL = os.environ.get("SITE_BASE_URL", "https://phdsky.org/")
MAX_POSITIONS_PER_DIGEST = 3
OPERATOR_LINE = "PhD Sky · operated by Eli Eydlin"
CONTACT_EMAIL = "eli.eydlin@gmail.com"
def unsubscribe_url(sub: dict, site_url: str = SITE_URL) -> str:
    """Human preference-page link carrying the subscription's secret token."""
    return f"{site_url}unsubscribe?token={sub.get('unsubscribe_token', '')}"


def one_click_unsubscribe_url(sub: dict, site_url: str = SITE_URL) -> str:
    """RFC 8058 endpoint used only by mailbox-provider POST requests."""
    return f"{site_url}api/unsubscribe?token={sub.get('unsubscribe_token', '')}"


def unsubscribe_headers(sub: dict, site_url: str = SITE_URL) -> dict[str, str] | None:
    """Return scanner-safe one-click headers for a tokenized subscription."""
    if not sub.get("unsubscribe_token"):
        return None
    endpoint = one_click_unsubscribe_url(sub, site_url)
    return {
        "List-Unsubscribe": f"<{endpoint}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def recipient_feed_url(site_url: str = SITE_URL) -> str:
    """Deep link to the authenticated recipient's personalized feed."""
    return f"{site_url.rstrip('/')}/#following"

_AGGREGATORS_FILE = Path(__file__).resolve().parent.parent / "docs" / "aggregators.json"
try:
    AGGREGATORS = set(json.loads(_AGGREGATORS_FILE.read_text(encoding="utf-8")).get("handles", []))
except (FileNotFoundError, json.JSONDecodeError):
    AGGREGATORS = set()


# ── Pure helpers (unit-tested in tests/test_digest.py) ──────────────────────

def position_matches(sub: dict, pos: dict) -> bool:
    """True if a position matches a subscription's saved filter.

    Array filters (disciplines/countries/position_types) are OR-within and
    AND-across; an empty array means "no constraint". ``query_text`` is a
    case-insensitive substring over message/handle/country/disciplines/types.
    """
    if sub.get("hide_aggregators") and pos.get("user_handle") in AGGREGATORS:
        return False

    discs = set(pos.get("disciplines") or [])
    types = set(pos.get("position_type") or [])
    country = pos.get("country")

    want_disc = set(sub.get("disciplines") or [])
    if want_disc and not (want_disc & discs):
        return False
    want_country = set(sub.get("countries") or [])
    if want_country and country not in want_country:
        return False
    want_type = set(sub.get("position_types") or [])
    if want_type and not (want_type & types):
        return False

    q = (sub.get("query_text") or "").strip().lower()
    if q:
        hay = " ".join([
            pos.get("message") or "",
            pos.get("user_handle") or "",
            country or "",
            " ".join(pos.get("disciplines") or []),
            " ".join(pos.get("position_type") or []),
        ]).lower()
        if q not in hay:
            return False
    return True


def subscription_label(sub: dict) -> str:
    """Human-readable summary of a subscription's filter, for subject lines."""
    parts = []
    parts += list(sub.get("disciplines") or [])
    parts += list(sub.get("position_types") or [])
    parts += list(sub.get("countries") or [])
    if sub.get("query_text"):
        parts.append(f'"{sub["query_text"]}"')
    return " · ".join(parts) if parts else "all positions"


def format_digest_html(
    sub: dict,
    positions: list[dict],
    site_url: str = SITE_URL,
    unsub_url: str | None = None,
) -> str:
    """Render a compact, email-client-safe digest with at most three jobs."""
    label = html.escape(subscription_label(sub))
    unsub_url = unsub_url or unsubscribe_url(sub, site_url)
    feed_url = recipient_feed_url(site_url)
    rows = []
    for p in positions[:MAX_POSITIONS_PER_DIGEST]:
        title = p.get("job_title") or " / ".join(p.get("position_type") or []) or "Research position"
        employer = p.get("hiring_organization") or ""
        disc = ", ".join(p.get("disciplines") or [])
        location = p.get("location_text") or p.get("country") or ""
        meta = " · ".join([x for x in (employer, disc, location) if x and x != "Unknown"])
        msg = (p.get("message") or "")[:220]
        url = p.get("application_url") or p.get("url") or feed_url
        rows.append(
            f'<div style="padding:18px 0;border-top:1px solid #c8d0cb">'
            f'<div style="font:600 16px Arial,sans-serif;color:#18201d">{html.escape(title)}</div>'
            f'<div style="font:13px Arial,sans-serif;color:#55625c;margin:5px 0 8px">{html.escape(meta)}</div>'
            f'<div style="font:14px Arial,sans-serif;color:#35423c;margin:0 0 9px;line-height:1.5">{html.escape(msg)}</div>'
            f'<a href="{html.escape(url)}" style="font:600 13px Arial,sans-serif;color:#18594a">View position</a>'
            f'</div>'
        )
    n = len(positions)
    return (
        f'<div style="margin:0;padding:28px 12px;background:#f3f5f2">'
        f'<div style="max-width:620px;margin:0 auto;background:#ffffff;padding:28px;border:1px solid #c8d0cb">'
        f'<div style="font:700 22px Georgia,serif;color:#18594a">PhD Sky</div>'
        f'<div style="font:14px Arial,sans-serif;color:#55625c;margin:8px 0 22px;line-height:1.5">'
        f'{n} new position{"s" if n != 1 else ""} matching <b style="color:#18201d">{label}</b></div>'
        f'{"".join(rows)}'
        f'<div style="margin:24px 0;text-align:center">'
        f'<a href="{html.escape(feed_url)}" style="display:inline-block;background:#18594a;color:#ffffff;text-decoration:none;padding:13px 22px;font:600 14px Arial,sans-serif">'
        f'See more in your feed</a></div>'
        f'<div style="font:12px Arial,sans-serif;color:#66736d;margin-top:22px;line-height:1.6">'
        f'You receive this because you created this saved search on '
        f'<a href="{html.escape(site_url)}" style="color:#315f78">PhD Sky</a>. '
        f'<a href="{html.escape(unsub_url)}" style="color:#315f78">Unsubscribe</a> or '
        f'<a href="{html.escape(site_url.rstrip("/"))}/#subscriptions" style="color:#315f78">manage your alerts</a>.'
        f'<br>{html.escape(OPERATOR_LINE)} · <a href="mailto:{CONTACT_EMAIL}" style="color:#315f78">{CONTACT_EMAIL}</a>'
        f'</div>'
        f'</div>'
        f'</div>'
    )


def format_digest_text(
    sub: dict,
    positions: list[dict],
    site_url: str = SITE_URL,
    unsub_url: str | None = None,
) -> str:
    """Plain-text alternative for the compact digest."""
    lines = [
        "PhD Sky",
        f"{len(positions)} new position(s) matching {subscription_label(sub)}",
        "",
    ]
    for p in positions[:MAX_POSITIONS_PER_DIGEST]:
        title = p.get("job_title") or " / ".join(p.get("position_type") or []) or "Research position"
        employer = p.get("hiring_organization") or ""
        location = p.get("location_text") or p.get("country") or ""
        url = p.get("application_url") or p.get("url") or recipient_feed_url(site_url)
        lines += [title, " · ".join(x for x in (employer, location) if x), url, ""]
    lines += [
        f"See more in your feed: {recipient_feed_url(site_url)}",
        f"Unsubscribe: {unsub_url or unsubscribe_url(sub, site_url)}",
        OPERATOR_LINE,
        CONTACT_EMAIL,
    ]
    return "\n".join(lines)


# ── DB / orchestration ──────────────────────────────────────────────────────

def get_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL / SUPABASE_SERVICE_KEY", file=sys.stderr)
        sys.exit(1)
    return create_client(url, key)


def fetch_candidate_positions(client, since: str | None) -> list[dict]:
    """Verified canonical positions newer than ``since`` (paginated)."""
    PAGE = 1000
    out, frm = [], 0
    while True:
        q = (client.table("phd_positions")
             .select("uri, created_at, disciplines, country, position_type, user_handle, message, url, job_title, hiring_organization, application_url, location_text")
             .eq("is_verified_job", True)
             .is_("duplicate_of", "null")
             .order("created_at", desc=True))
        if since:
            q = q.gt("created_at", since)
        data = q.range(frm, frm + PAGE - 1).execute().data or []
        out += data
        if len(data) < PAGE:
            break
        frm += PAGE
    return out


def user_email(client, user_id: str) -> str | None:
    rows = client.table("profiles").select("email").eq("id", user_id).limit(1).execute().data
    return (rows[0].get("email") if rows else None)


def subscription_watermark(sub: dict) -> str | None:
    """The 'new since' point for a subscription.

    Falls back to the row's creation time when ``last_notified_at`` is unset, so
    a never-notified subscription reports positions indexed since it was created
    rather than the entire archive.
    """
    return sub.get("last_notified_at") or sub.get("created_at")


def fetch_due_subscriptions(client, cadence: str) -> list[dict]:
    """All email subscriptions in this cadence bucket (paginated).

    PostgREST caps an unbounded select at 1000 rows, which would silently skip
    subscribers past that point.
    """
    PAGE = 1000
    out, frm = [], 0
    while True:
        data = (client.table("subscriptions")
                .select("*")
                .eq("cadence", cadence)
                .eq("deliver_email", True)
                .order("created_at")
                .range(frm, frm + PAGE - 1)
                .execute().data or [])
        out += data
        if len(data) < PAGE:
            break
        frm += PAGE
    return out


def fetch_operator_subscriptions(client, email: str) -> list[dict]:
    """Enabled subscriptions owned by exactly one configured operator email."""
    profiles = (
        client.table("profiles")
        .select("id")
        .eq("email", email)
        .limit(2)
        .execute()
        .data
        or []
    )
    if len(profiles) != 1:
        raise RuntimeError(
            f"Expected exactly one profile for operator recipient; found {len(profiles)}"
        )
    return (
        client.table("subscriptions")
        .select("*")
        .eq("user_id", profiles[0]["id"])
        .eq("deliver_email", True)
        .order("created_at")
        .execute()
        .data
        or []
    )


def run_operator(to: str) -> int:
    """Send one aggregate digest only to ``to`` and advance only its alerts.

    This is the production-safe temporary mode used by GitHub Actions. It never
    looks up or sends to any other profile email. With zero new matches it sends
    nothing and performs no writes.
    """
    if not report_email_config():
        return -1
    client = get_client()
    subs = fetch_operator_subscriptions(client, to)
    if not subs:
        print("No enabled subscriptions for the configured operator; no email sent.")
        return 0

    watermarks = [w for w in (subscription_watermark(s) for s in subs) if w]
    oldest = min(watermarks) if len(watermarks) == len(subs) else None
    candidates = fetch_candidate_positions(client, oldest)

    matches_by_sub: dict[str, list[dict]] = {}
    unique_matches: dict[str, dict] = {}
    for sub in subs:
        wm = subscription_watermark(sub)
        pool = [p for p in candidates if not wm or p["created_at"] > wm]
        matches = [p for p in pool if position_matches(sub, p)]
        if matches:
            matches_by_sub[str(sub["id"])] = matches
            for position in matches:
                unique_matches[position["uri"]] = position

    matches = sorted(
        unique_matches.values(), key=lambda p: p.get("created_at") or "", reverse=True
    )
    if not matches:
        print("No new positions match the operator's saved searches; no email sent.")
        return 0

    display_sub = subs[0] if len(subs) == 1 else {"disciplines": ["Your saved searches"]}
    first_token_sub = next((s for s in subs if s.get("unsubscribe_token")), subs[0])
    unsub = unsubscribe_url(first_token_sub)
    subject = f"{len(matches)} new: {subscription_label(display_sub)}"[:120]
    body = format_digest_html(display_sub, matches, unsub_url=unsub)
    text_body = format_digest_text(display_sub, matches, unsub_url=unsub)
    headers = unsubscribe_headers(first_token_sub)

    if not send_email(to, subject, body, headers=headers, text=text_body):
        print("Operator digest send failed; watermarks unchanged for retry.", file=sys.stderr)
        return -1

    for sub in subs:
        sub_matches = matches_by_sub.get(str(sub["id"]), [])
        if not sub_matches:
            continue
        newest = max(p["created_at"] for p in sub_matches)
        client.table("subscriptions").update(
            {"last_notified_at": newest}
        ).eq("id", sub["id"]).execute()
    print(
        f"Sent one operator digest to {to}: {len(matches)} matches, "
        f"{min(len(matches), MAX_POSITIONS_PER_DIGEST)} displayed."
    )
    return 1


def run(cadence: str) -> int:
    client = get_client()
    subs = fetch_due_subscriptions(client, cadence)
    if not subs:
        print(f"No '{cadence}' email subscriptions due.")
        return 0

    # Fetch once across all subs using the oldest watermark, then filter per-sub.
    watermarks = [w for w in (subscription_watermark(s) for s in subs) if w]
    oldest = min(watermarks) if len(watermarks) == len(subs) else None
    candidates = fetch_candidate_positions(client, oldest)
    print(f"{len(subs)} subscription(s), {len(candidates)} candidate position(s)")

    # Refuse to send without a working unsubscribe path. This keeps a requested
    # service alert easy to stop and supplies standards-based mailbox controls.
    # A missing token means migrations/007_unsubscribe_token.sql is not applied.
    if not any(s.get("unsubscribe_token") for s in subs):
        print("ABORT: no subscription has an unsubscribe_token — apply "
              "migrations/007_unsubscribe_token.sql in the Supabase SQL editor. "
              "Refusing to send mail with a dead unsubscribe link.", file=sys.stderr)
        return 0

    sent = 0
    for sub in subs:
        if not sub.get("unsubscribe_token"):
            print(f"  sub {sub['id']}: no unsubscribe_token, skipping")
            continue
        wm = subscription_watermark(sub)
        pool = [p for p in candidates if (not wm or p["created_at"] > wm)]
        matches = [p for p in pool if position_matches(sub, p)]
        if not matches:
            continue
        email = user_email(client, sub["user_id"])
        if not email:
            print(f"  sub {sub['id']}: no email on profile, skipping")
            continue
        subject = f"{len(matches)} new: {subscription_label(sub)}"[:120]
        unsub = unsubscribe_url(sub)
        body = format_digest_html(sub, matches, unsub_url=unsub)
        # Mailbox-provider one-click uses a POST-only endpoint. The visible body
        # link opens a separate confirmation page, so GET scanners cannot opt out.
        unsub_headers = unsubscribe_headers(sub)
        if send_email(email, subject, body, headers=unsub_headers):
            # Advances past every match, including any beyond the display cap —
            # those are disclosed in the email body with a link to the site.
            newest = max(p["created_at"] for p in matches)
            client.table("subscriptions").update(
                {"last_notified_at": newest}).eq("id", sub["id"]).execute()
            sent += 1
            capped = len(matches) - MAX_POSITIONS_PER_DIGEST
            note = f" ({capped} over the display cap, linked not listed)" if capped > 0 else ""
            print(f"  sub {sub['id']}: emailed {len(matches)} to {email}{note}")
        else:
            print(f"  sub {sub['id']}: send failed, watermark unchanged (will retry)")
    print(f"Done. Sent {sent} digest(s).")
    return sent


# ── Test send ───────────────────────────────────────────────────────────────
# Deliberately a separate function rather than a flag threaded through run().
# There is no code path here that can reach a real subscriber's address or write
# to the database, so a mistyped argument cannot mail your users or burn their
# watermarks.

TEST_BANNER = (
    '<div style="max-width:640px;margin:0 auto 10px;padding:10px 14px;'
    'background:#422006;border:1px solid #a16207;border-radius:8px;'
    'font:12px sans-serif;color:#fde68a">'
    '<b>TEST SEND</b> — delivery/formatting check. Not sent to any subscriber, '
    'and no subscription watermark was changed.</div>'
)


def check_email_config() -> tuple[list[str], list[str]]:
    """Inspect the email env. Returns (blocking, warnings).

    In GitHub Actions, Secrets and Variables are separate stores — ``secrets.X``
    resolves to an empty string when X was added under the Variables tab, which
    surfaces only as "not set". Naming the missing value beats a generic failure.
    """
    provider = (os.environ.get("EMAIL_PROVIDER") or "resend").lower()
    blocking, warnings = [], []
    if provider == "resend" and not os.environ.get("RESEND_API_KEY"):
        blocking.append("RESEND_API_KEY is empty — nothing can be sent")
    if not os.environ.get("EMAIL_FROM"):
        warnings.append("EMAIL_FROM is empty — falling back to Resend's shared "
                        "test domain, which is not your verified sender")
    return blocking, warnings


def report_email_config() -> bool:
    """Print config problems. False when sending cannot proceed."""
    blocking, warnings = check_email_config()
    for w in warnings:
        print(f"  WARNING: {w}")
    for b in blocking:
        print(f"  ERROR: {b}", file=sys.stderr)
    if blocking:
        print("  Set these as repository Secrets (Settings -> Secrets and "
              "variables -> Actions -> Secrets). A value added under the "
              "Variables tab is NOT visible to secrets.* in a workflow.",
              file=sys.stderr)
        return False
    return True


def fetch_recent_positions(client, limit: int = 200) -> list[dict]:
    """Most recent verified canonical positions, ignoring any watermark."""
    return (client.table("phd_positions")
            .select("uri, created_at, disciplines, country, position_type, user_handle, message, url, job_title, hiring_organization, application_url, location_text")
            .eq("is_verified_job", True)
            .is_("duplicate_of", "null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute().data or [])


def run_test(to: str, cadence: str = "weekly") -> int:
    """Send exactly one digest to ``to`` so delivery can be validated.

    Always sends, even when nothing new matches — that empty case is itself
    worth seeing. Uses a real subscription's filters when one exists (so the
    label and layout match production), otherwise a synthetic "all positions"
    one. Reads only; never updates last_notified_at.
    """
    print(f"TEST MODE — one email to {to}. No subscriber is mailed, nothing is written.")
    if not report_email_config():
        return 0
    client = get_client()

    subs = fetch_due_subscriptions(client, cadence)
    if subs:
        sub = dict(subs[0])
        print(f"  using subscription {sub.get('id')} ({subscription_label(sub)})")
    else:
        sub = {"disciplines": [], "countries": [], "position_types": [],
               "query_text": None, "hide_aggregators": False}
        print("  no subscriptions found — using a synthetic 'all positions' filter")

    # Ignore the watermark so the sample has content to render.
    recent = fetch_recent_positions(client)
    matches = [p for p in recent if position_matches(sub, p)]
    print(f"  {len(recent)} recent position(s), {len(matches)} matching")

    if not sub.get("unsubscribe_token"):
        print("  WARNING: no unsubscribe_token — the unsubscribe link in this "
              "email will be dead. Apply migrations/007_unsubscribe_token.sql. "
              "(Real digests refuse to send in this state; test sends do not.)")

    subject = f"[TEST] {len(matches)} new: {subscription_label(sub)}"[:120]
    unsub = unsubscribe_url(sub)
    body = TEST_BANNER + format_digest_html(sub, matches, unsub_url=unsub)
    headers = unsubscribe_headers(sub)

    text_body = format_digest_text(sub, matches, unsub_url=unsub)
    if send_email(to, subject, body, headers=headers, text=text_body):
        print(f"Sent test digest to {to}.")
        return 1
    print("Test send FAILED — the provider rejected it. Config looked complete, "
          "so check the provider response logged above (bad key, or EMAIL_FROM "
          "using a domain not verified in Resend).", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Send subscription email digests")
    ap.add_argument("--cadence", default="daily", choices=["instant", "daily", "weekly"],
                    help="which cadence bucket to send (default: daily)")
    ap.add_argument("--test-to", metavar="EMAIL",
                    help="TEST MODE: send one sample digest to EMAIL and exit. "
                         "Mails nobody else and writes nothing to the database.")
    ap.add_argument("--operator-to", metavar="EMAIL",
                    help="MANUAL OPERATOR MODE: send at most one new-position "
                         "digest only to this profile email, then advance only "
                         "that profile's subscription watermarks.")
    args = ap.parse_args()
    if args.operator_to:
        sys.exit(0 if run_operator(args.operator_to) >= 0 else 1)
    if args.test_to:
        sys.exit(0 if run_test(args.test_to, args.cadence) else 1)
    run(args.cadence)


if __name__ == "__main__":
    main()
