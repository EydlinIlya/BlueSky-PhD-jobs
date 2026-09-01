"""Send explicitly requested weekly saved-search alerts.

The job reads only subscriptions with current email consent. Successful scans
advance ``last_processed_at`` even when there are no matches. Failed sends
advance neither processing nor notification watermarks.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.email import send_email  # noqa: E402

load_dotenv()

SITE_URL = os.environ.get("SITE_BASE_URL", "https://phdsky.org/").rstrip("/") + "/"
MAX_POSITIONS_PER_DIGEST = 40
EMAIL_CONSENT_VERSION = "weekly-alert-v1"
OPERATOR_LINE = "PhD Sky · operated by Eli Eydlin in Israel"
CONTACT_EMAIL = "eli.eydlin@gmail.com"


def human_unsubscribe_url(sub: dict, site_url: str = SITE_URL) -> str:
    token = str(sub.get("unsubscribe_token") or "")
    return f"{site_url.rstrip('/')}/unsubscribe?{urlencode({'token': token})}"


def machine_unsubscribe_url(sub: dict, site_url: str = SITE_URL) -> str:
    token = str(sub.get("unsubscribe_token") or "")
    return f"{site_url.rstrip('/')}/api/unsubscribe?{urlencode({'token': token})}"


# Backward-compatible name used by older tests and integrations: this is the
# human confirmation page, never the mutating endpoint.
unsubscribe_url = human_unsubscribe_url

_AGGREGATORS_FILE = Path(__file__).resolve().parent.parent / "docs" / "aggregators.json"
try:
    AGGREGATORS = set(json.loads(_AGGREGATORS_FILE.read_text(encoding="utf-8")).get("handles", []))
except (FileNotFoundError, json.JSONDecodeError):
    AGGREGATORS = set()


def position_matches(sub: dict, pos: dict) -> bool:
    """Return whether a position matches an AND-across/OR-within saved filter."""
    if sub.get("hide_aggregators") and pos.get("user_handle") in AGGREGATORS:
        return False

    disciplines = set(pos.get("disciplines") or [])
    position_types = set(pos.get("position_type") or [])
    country = pos.get("country")
    wanted_disciplines = set(sub.get("disciplines") or [])
    wanted_countries = set(sub.get("countries") or [])
    wanted_types = set(sub.get("position_types") or [])

    if wanted_disciplines and not wanted_disciplines.intersection(disciplines):
        return False
    if wanted_countries and country not in wanted_countries:
        return False
    if wanted_types and not wanted_types.intersection(position_types):
        return False

    query = (sub.get("query_text") or "").strip().casefold()
    if query:
        haystack = " ".join([
            pos.get("message") or "",
            pos.get("user_handle") or "",
            country or "",
            " ".join(pos.get("disciplines") or []),
            " ".join(pos.get("position_type") or []),
        ]).casefold()
        if query not in haystack:
            return False
    return True


def subscription_label(sub: dict) -> str:
    parts = []
    parts.extend(sub.get("disciplines") or [])
    parts.extend(sub.get("position_types") or [])
    parts.extend(sub.get("countries") or [])
    if sub.get("query_text"):
        parts.append(f'“{sub["query_text"]}”')
    return " · ".join(str(part) for part in parts) if parts else "all positions"


def _display_rows(positions: list[dict]) -> list[dict]:
    return positions[:MAX_POSITIONS_PER_DIGEST]


def format_digest_html(
    sub: dict,
    positions: list[dict],
    site_url: str = SITE_URL,
    unsub_url: str | None = None,
) -> str:
    """Render a light, email-client-safe HTML alternative with escaped data."""
    label = html.escape(subscription_label(sub))
    unsub_url = unsub_url or human_unsubscribe_url(sub, site_url)
    manage_url = f"{site_url.rstrip('/')}/#subscriptions"
    browse_url = f"{site_url.rstrip('/')}/positions"
    rows = []
    for position in _display_rows(positions):
        title = " / ".join(str(v) for v in (position.get("position_type") or [])) or "PhD position"
        disciplines = ", ".join(str(v) for v in (position.get("disciplines") or []))
        country = str(position.get("country") or "")
        metadata = " · ".join(v for v in (disciplines, country) if v and v != "Unknown")
        message = str(position.get("message") or "")[:280]
        url = str(position.get("url") or site_url)
        rows.append(
            '<div style="padding:18px 0;border-top:2px solid #18594A">'
            f'<div style="font:700 16px Georgia,serif;color:#18201D">{html.escape(title)}</div>'
            f'<div style="font:12px ui-monospace,monospace;color:#55625C;margin:5px 0 9px">{html.escape(metadata)}</div>'
            f'<div style="font:15px Arial,sans-serif;color:#18201D;line-height:1.55;margin-bottom:9px">{html.escape(message)}</div>'
            f'<a href="{html.escape(url, quote=True)}" style="font:700 14px Arial,sans-serif;color:#18594A">View source</a>'
            '</div>'
        )

    count = len(positions)
    overflow = max(0, count - MAX_POSITIONS_PER_DIGEST)
    overflow_note = ""
    if overflow:
        overflow_note = (
            '<p style="font:14px Arial,sans-serif;color:#55625C">'
            f'Showing the {MAX_POSITIONS_PER_DIGEST} newest matches. '
            f'<a href="{html.escape(browse_url, quote=True)}" style="color:#18594A">Browse {overflow} more on PhD Sky</a>.</p>'
        )

    return (
        '<div style="margin:0;background:#F3F5F2;padding:28px 14px">'
        '<div style="max-width:640px;margin:0 auto;background:#FFFFFF;border:1px solid #C8D0CB;padding:28px">'
        '<div style="font:700 24px Georgia,serif;color:#18201D">PhD Sky</div>'
        '<div style="width:54px;border-top:4px solid #B54632;margin:10px 0 20px"></div>'
        f'<p style="font:16px Arial,sans-serif;color:#18201D;line-height:1.5">{count} new position{"s" if count != 1 else ""} matching <strong>{label}</strong>.</p>'
        f'{overflow_note}{"".join(rows)}'
        '<div style="border-top:1px solid #C8D0CB;margin-top:18px;padding-top:18px;font:13px Arial,sans-serif;color:#55625C;line-height:1.6">'
        'You are receiving this non-promotional service message because you explicitly requested a weekly alert. '
        f'<a href="{html.escape(unsub_url, quote=True)}" style="color:#18594A">Unsubscribe this alert</a> or '
        f'<a href="{html.escape(manage_url, quote=True)}" style="color:#18594A">manage weekly alerts</a>.'
        f'<br>{OPERATOR_LINE}<br><a href="mailto:{CONTACT_EMAIL}" style="color:#18594A">{CONTACT_EMAIL}</a>'
        '</div></div></div>'
    )


def format_digest_text(
    sub: dict,
    positions: list[dict],
    site_url: str = SITE_URL,
    unsub_url: str | None = None,
) -> str:
    """Render the same digest as a readable plain-text alternative."""
    unsub_url = unsub_url or human_unsubscribe_url(sub, site_url)
    lines = [
        "PhD Sky",
        "=======",
        f"{len(positions)} new position{'s' if len(positions) != 1 else ''} matching {subscription_label(sub)}.",
        "",
    ]
    for position in _display_rows(positions):
        title = " / ".join(str(v) for v in (position.get("position_type") or [])) or "PhD position"
        metadata = " · ".join(v for v in [
            ", ".join(str(d) for d in (position.get("disciplines") or [])),
            str(position.get("country") or ""),
        ] if v and v != "Unknown")
        lines.extend([
            title,
            metadata,
            str(position.get("message") or "")[:280],
            str(position.get("url") or site_url),
            "",
        ])
    overflow = len(positions) - MAX_POSITIONS_PER_DIGEST
    if overflow > 0:
        lines.extend([f"Browse {overflow} more: {site_url.rstrip('/')}/positions", ""])
    lines.extend([
        "You requested this weekly, non-promotional saved-search alert.",
        f"Unsubscribe this alert: {unsub_url}",
        f"Manage weekly alerts: {site_url.rstrip('/')}/#subscriptions",
        "",
        OPERATOR_LINE,
        CONTACT_EMAIL,
    ])
    return "\n".join(lines)


def get_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
    return create_client(url, key)


def fetch_candidate_positions(client, since: str | None) -> list[dict]:
    page_size = 1000
    output, start = [], 0
    while True:
        query = (client.table("phd_positions")
                 .select("uri, created_at, disciplines, country, position_type, user_handle, message, url")
                 .eq("is_verified_job", True)
                 .is_("duplicate_of", "null")
                 .order("created_at", desc=True))
        if since:
            query = query.gt("created_at", since)
        page = query.range(start, start + page_size - 1).execute().data or []
        output.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return output


def user_email(client, user_id: str) -> str | None:
    rows = client.table("profiles").select("email").eq("id", user_id).limit(1).execute().data or []
    return rows[0].get("email") if rows else None


def subscription_watermark(sub: dict) -> str | None:
    return sub.get("last_processed_at") or sub.get("created_at")


def fetch_due_subscriptions(client, cadence: str = "weekly") -> list[dict]:
    if cadence != "weekly":
        return []
    page_size = 1000
    output, start = [], 0
    while True:
        page = (client.table("subscriptions")
                .select("*")
                .eq("cadence", "weekly")
                .eq("deliver_email", True)
                .order("created_at")
                .range(start, start + page_size - 1)
                .execute().data or [])
        output.extend(sub for sub in page if sub.get("email_consent_at"))
        if len(page) < page_size:
            break
        start += page_size
    return output


def _unsubscribe_headers(sub: dict) -> dict[str, str]:
    machine_url = machine_unsubscribe_url(sub)
    return {
        "List-Unsubscribe": f"<{machine_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def run(cadence: str = "weekly") -> int:
    if cadence != "weekly":
        raise ValueError("Weekly is the only supported email cadence")
    blocking, _ = check_email_config()
    if blocking:
        for problem in blocking:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 0

    client = get_client()
    subscriptions = fetch_due_subscriptions(client)
    if not subscriptions:
        print("No consented weekly email subscriptions due.")
        return 0
    if any(not sub.get("unsubscribe_token") for sub in subscriptions):
        print("ABORT: migration 008 is required before sending weekly alerts.", file=sys.stderr)
        return 0

    watermarks = [subscription_watermark(sub) for sub in subscriptions]
    oldest = min(watermarks) if all(watermarks) else None
    candidates = fetch_candidate_positions(client, oldest)
    print(f"{len(subscriptions)} subscription(s), {len(candidates)} candidate position(s)")

    sent = 0
    for sub in subscriptions:
        watermark = subscription_watermark(sub)
        pool = [position for position in candidates if not watermark or position["created_at"] > watermark]
        if not pool:
            continue
        newest_processed = max(position["created_at"] for position in pool)
        matches = [position for position in pool if position_matches(sub, position)]
        if not matches:
            client.table("subscriptions").update(
                {"last_processed_at": newest_processed}
            ).eq("id", sub["id"]).execute()
            print(f"  sub {sub['id']}: no matches; processing watermark advanced")
            continue

        recipient = user_email(client, sub["user_id"])
        if not recipient:
            print(f"  sub {sub['id']}: no current account email; retrying next week")
            continue
        subject = f"{len(matches)} new: {subscription_label(sub)}"[:120]
        human_url = human_unsubscribe_url(sub)
        html_body = format_digest_html(sub, matches, unsub_url=human_url)
        text_body = format_digest_text(sub, matches, unsub_url=human_url)
        if send_email(
            recipient,
            subject,
            html_body,
            text=text_body,
            headers=_unsubscribe_headers(sub),
        ):
            newest_notified = max(position["created_at"] for position in matches)
            client.table("subscriptions").update({
                "last_processed_at": newest_processed,
                "last_notified_at": newest_notified,
            }).eq("id", sub["id"]).execute()
            sent += 1
            print(f"  sub {sub['id']}: emailed {len(matches)} to {recipient}")
        else:
            print(f"  sub {sub['id']}: send failed; watermarks unchanged")
    print(f"Done. Sent {sent} digest(s).")
    return sent


TEST_BANNER = (
    '<div style="max-width:640px;margin:0 auto 10px;padding:10px 14px;'
    'background:#FFF7E8;border:1px solid #B54632;font:13px Arial,sans-serif;color:#18201D">'
    '<strong>TEST SEND</strong> — no subscriber was contacted and no watermark was changed.</div>'
)


def check_email_config() -> tuple[list[str], list[str]]:
    blocking = []
    if not os.environ.get("SUPABASE_URL"):
        blocking.append("SUPABASE_URL is required")
    if not os.environ.get("SUPABASE_SERVICE_KEY"):
        blocking.append("SUPABASE_SERVICE_KEY is required; no public-key fallback is allowed")
    if not os.environ.get("RESEND_API_KEY"):
        blocking.append("RESEND_API_KEY is required")
    sender = os.environ.get("EMAIL_FROM") or ""
    if not sender:
        blocking.append("EMAIL_FROM is required and must use a verified sending domain")
    elif "onboarding@resend.dev" in sender.casefold():
        blocking.append("EMAIL_FROM must use the verified PhD Sky sending domain")
    return blocking, []


def report_email_config() -> bool:
    blocking, warnings = check_email_config()
    for warning in warnings:
        print(f"WARNING: {warning}")
    for problem in blocking:
        print(f"ERROR: {problem}", file=sys.stderr)
    return not blocking


def fetch_recent_positions(client, limit: int = 200) -> list[dict]:
    return (client.table("phd_positions")
            .select("uri, created_at, disciplines, country, position_type, user_handle, message, url")
            .eq("is_verified_job", True)
            .is_("duplicate_of", "null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute().data or [])


def run_test(to: str, cadence: str = "weekly") -> int:
    if cadence != "weekly":
        raise ValueError("Weekly is the only supported email cadence")
    print(f"TEST MODE — one email to {to}. No subscriber is mailed and nothing is written.")
    if not report_email_config():
        return 0
    client = get_client()
    subscriptions = fetch_due_subscriptions(client)
    sub = dict(subscriptions[0]) if subscriptions else {
        "disciplines": [], "countries": [], "position_types": [],
        "query_text": None, "hide_aggregators": False,
    }
    recent = fetch_recent_positions(client)
    matches = [position for position in recent if position_matches(sub, position)]
    subject = f"[TEST] {len(matches)} new: {subscription_label(sub)}"[:120]
    human_url = human_unsubscribe_url(sub)
    html_body = TEST_BANNER + format_digest_html(sub, matches, unsub_url=human_url)
    text_body = format_digest_text(sub, matches, unsub_url=human_url)
    if send_email(to, subject, html_body, text=text_body, headers=_unsubscribe_headers(sub)):
        print(f"Sent test digest to {to}.")
        return 1
    print("Test send failed; check the provider response.", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send weekly saved-search alerts")
    parser.add_argument("--cadence", default="weekly", choices=["weekly"],
                        help="retained for automation compatibility; only weekly is supported")
    parser.add_argument("--test-to", metavar="EMAIL",
                        help="send one sample without contacting subscribers or writing watermarks")
    args = parser.parse_args()
    result = run_test(args.test_to) if args.test_to else run()
    if args.test_to:
        raise SystemExit(0 if result else 1)


if __name__ == "__main__":
    main()
