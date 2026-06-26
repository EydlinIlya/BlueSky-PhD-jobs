"""Send saved-search subscription digests by email.

Standalone cron job (mirrors scripts/post_to_telegram.py). For each due
subscription it finds newly-indexed positions matching the saved filter, emails
the user a digest, and advances the subscription's ``last_notified_at`` watermark
so the same position is never emailed twice. Idempotent on failure: if the email
send fails, the watermark is not advanced and the next run retries.

Usage:
    python scripts/send_subscription_digests.py --cadence daily
    python scripts/send_subscription_digests.py --cadence weekly
    python scripts/send_subscription_digests.py --cadence instant   # hourly batch

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
MAX_POSITIONS_PER_DIGEST = 40

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


def format_digest_html(sub: dict, positions: list[dict], site_url: str = SITE_URL) -> str:
    """Render the digest email body (simple, email-client-safe inline styles)."""
    label = html.escape(subscription_label(sub))
    rows = []
    for p in positions[:MAX_POSITIONS_PER_DIGEST]:
        title = " / ".join(p.get("position_type") or []) or "Position"
        disc = ", ".join(p.get("disciplines") or [])
        country = p.get("country") or ""
        meta = " · ".join([x for x in (disc, country) if x and x != "Unknown"])
        msg = (p.get("message") or "")[:280]
        url = p.get("url") or site_url
        rows.append(
            f'<div style="padding:14px 0;border-bottom:1px solid #334155">'
            f'<div style="font:600 14px sans-serif;color:#e2e8f0">{html.escape(title)}'
            f'{(" — " + html.escape(meta)) if meta else ""}</div>'
            f'<div style="font:13px sans-serif;color:#a8b8c8;margin:6px 0;line-height:1.5">{html.escape(msg)}</div>'
            f'<a href="{html.escape(url)}" style="font:12px sans-serif;color:#3b82f6">View position →</a>'
            f'</div>'
        )
    n = len(positions)
    return (
        f'<div style="max-width:640px;margin:0 auto;background:#0f172a;padding:24px;border-radius:10px">'
        f'<div style="font:700 18px monospace;color:#e2e8f0">&gt; PhD_Positions</div>'
        f'<div style="font:13px sans-serif;color:#a8b8c8;margin:8px 0 18px">'
        f'{n} new position{"s" if n != 1 else ""} matching <b style="color:#e2e8f0">{label}</b></div>'
        f'{"".join(rows)}'
        f'<div style="font:12px sans-serif;color:#64748b;margin-top:20px">'
        f'You receive this because you subscribed on <a href="{html.escape(site_url)}" style="color:#3b82f6">PhD Sky</a>. '
        f'Manage or unsubscribe from your account.</div>'
        f'</div>'
    )


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
             .select("uri, created_at, disciplines, country, position_type, user_handle, message, url")
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


def run(cadence: str) -> int:
    client = get_client()
    subs = (client.table("subscriptions")
            .select("*")
            .eq("cadence", cadence)
            .eq("deliver_email", True)
            .execute().data or [])
    if not subs:
        print(f"No '{cadence}' email subscriptions due.")
        return 0

    # Fetch once across all subs using the oldest watermark, then filter per-sub.
    watermarks = [s.get("last_notified_at") for s in subs if s.get("last_notified_at")]
    oldest = min(watermarks) if len(watermarks) == len(subs) and watermarks else None
    candidates = fetch_candidate_positions(client, oldest)
    print(f"{len(subs)} subscription(s), {len(candidates)} candidate position(s)")

    sent = 0
    for sub in subs:
        wm = sub.get("last_notified_at")
        pool = [p for p in candidates if (not wm or p["created_at"] > wm)]
        matches = [p for p in pool if position_matches(sub, p)]
        if not matches:
            continue
        email = user_email(client, sub["user_id"])
        if not email:
            print(f"  sub {sub['id']}: no email on profile, skipping")
            continue
        subject = f"{len(matches)} new: {subscription_label(sub)}"[:120]
        body = format_digest_html(sub, matches)
        if send_email(email, subject, body):
            newest = max(p["created_at"] for p in matches)
            client.table("subscriptions").update(
                {"last_notified_at": newest}).eq("id", sub["id"]).execute()
            sent += 1
            print(f"  sub {sub['id']}: emailed {len(matches)} to {email}")
        else:
            print(f"  sub {sub['id']}: send failed, watermark unchanged (will retry)")
    print(f"Done. Sent {sent} digest(s).")
    return sent


def main():
    ap = argparse.ArgumentParser(description="Send subscription email digests")
    ap.add_argument("--cadence", default="daily", choices=["instant", "daily", "weekly"],
                    help="which cadence bucket to send (default: daily)")
    args = ap.parse_args()
    run(args.cadence)


if __name__ == "__main__":
    main()
