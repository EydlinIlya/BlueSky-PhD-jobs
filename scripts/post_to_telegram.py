"""Post Biology + Computer Science positions to the Telegram channel.

Two ways to invoke:

1. As a standalone digest job (preferred): `python scripts/post_to_telegram.py`
   Queries Supabase for Bio + CS positions where `posted_to_telegram_at IS NULL`,
   posts them, then marks the rows so they aren't re-posted. This decouples
   Telegram cadence from pipeline ingest cadence — runs separately on cron.

2. As a library, by importing `post_batch_to_telegram(positions)`. Kept for
   backward compatibility but no longer called from the pipeline. New code
   should use the standalone digest path.

Required env (digest mode): SUPABASE_URL, SUPABASE_KEY, TELEGRAM_BOT_TOKEN,
TELEGRAM_CHANNEL_ID. Schema requirement: `phd_positions.posted_to_telegram_at`
column (TIMESTAMPTZ, NULL = un-posted). See README for the migration SQL.
"""

import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_MAX_LENGTH = 4096
PAGES_URL = "https://phdsky.org/"
REPO_URL = "https://github.com/EydlinIlya/BlueSky-PhD-jobs"

_AGGREGATORS_FILE = Path(__file__).resolve().parent.parent / "docs" / "aggregators.json"
try:
    AGGREGATORS = set(json.loads(_AGGREGATORS_FILE.read_text(encoding="utf-8")).get("handles", []))
except (FileNotFoundError, json.JSONDecodeError):
    AGGREGATORS = set()

FOOTER = (
    "\n\n"
    f'<a href="{PAGES_URL}">Browse all positions</a> | '
    f'<a href="{REPO_URL}">GitHub</a>'
)

SEPARATOR = "\n\n━━━━━━━━━━━━━━━\n\n"

# Cap a single digest at this many positions so a backlog (e.g. after migration)
# doesn't dump hundreds of messages into the channel at once.
DIGEST_LIMIT = 50


def format_position(pos):
    """Format a single position as HTML for Telegram."""
    types = pos.get("position_type") or []
    type_tags = " | ".join(f"#{t.replace('&', '').replace('  ', ' ').replace(' ', '_')}" for t in types)

    chunks = []
    if type_tags:
        chunks.append(type_tags)

    country = pos.get("country") or ""
    if country and country != "Unknown":
        chunks.append(f"#{country.replace(' ', '_')}")

    if (pos.get("user_handle") or "") in AGGREGATORS:
        chunks.append("#Aggregator")

    header = " | ".join(chunks)

    message = pos.get("message") or ""
    if len(message) > 400:
        message = message[:397] + "..."
    message = html.escape(message)

    url = pos.get("url") or ""
    link = f'<a href="{html.escape(url)}">View Post</a>' if url else ""

    lines = []
    if header:
        lines.append(html.escape(header))
    lines.append("")
    lines.append(message)
    if link:
        lines.append("")
        lines.append(link)

    return "\n".join(lines)


def build_messages(positions):
    """Batch positions into messages under the Telegram character limit."""
    if not positions:
        return []

    formatted = [format_position(p) for p in positions]

    messages = []
    current = ""

    for block in formatted:
        candidate = block if not current else current + SEPARATOR + block

        if len(candidate) > TELEGRAM_MAX_LENGTH - len(FOOTER) - 10:
            if current:
                messages.append(current)
            current = block
        else:
            current = candidate

    if current:
        messages.append(current)

    if messages:
        messages[-1] += FOOTER

    return messages


def send_telegram_message(token, channel_id, html_text):
    """Send a message to a Telegram channel. Returns True on success."""
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": channel_id,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Telegram API error: {resp.status_code} {resp.text}")
        return False
    return True


def post_batch_to_telegram(all_results):
    """Post Biology + CS positions from a provided batch to Telegram.

    Kept for backward compatibility — the in-pipeline call site has been
    removed in favor of the standalone digest. New code paths should call
    run_digest() instead.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "")

    if not token or not channel_id:
        return True

    positions = [
        pos for pos in all_results
        if "Biology" in (pos.get("disciplines") or [])
        and "Computer Science" in (pos.get("disciplines") or [])
    ]

    if not positions:
        print("No Biology + CS positions in this batch")
        return True

    print(f"Posting {len(positions)} Biology + CS positions to Telegram...")

    messages = build_messages(positions)
    sent = 0
    for msg in messages:
        if send_telegram_message(token, channel_id, msg):
            sent += 1
        else:
            print("Failed to send Telegram message, stopping")
            return False

    print(f"Posted {len(positions)} positions in {sent} Telegram message(s)")
    return True


def fetch_unposted_bio_cs_positions(client, limit=DIGEST_LIMIT):
    """Pull Bio+CS positions from Supabase that haven't been posted yet.

    Filters: verified canonical posts only, both 'Biology' and 'Computer Science'
    in disciplines, posted_to_telegram_at IS NULL. Newest first, capped at limit.
    """
    result = (
        client.table("phd_positions")
        .select("uri, message, url, user_handle, created_at, disciplines, country, position_type")
        .eq("is_verified_job", True)
        .is_("duplicate_of", "null")
        .is_("posted_to_telegram_at", "null")
        .contains("disciplines", ["Biology"])
        .contains("disciplines", ["Computer Science"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def mark_positions_as_posted(client, uris, timestamp):
    """Set posted_to_telegram_at on the given URIs so the digest doesn't re-post them."""
    if not uris:
        return
    client.table("phd_positions").update(
        {"posted_to_telegram_at": timestamp}
    ).in_("uri", uris).execute()


def run_digest():
    """Standalone entry point: read un-posted Bio+CS rows, post them, mark them.

    Returns 0 on success (including 'nothing to post'), 1 on Telegram failure.
    The mark step is intentionally idempotent — failures during posting leave
    rows un-marked, so the next digest tries again.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "")
    if not token or not channel_id:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHANNEL_ID unset — skipping digest")
        return 0

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        print("SUPABASE_URL/SUPABASE_KEY unset — cannot run digest")
        return 1

    from supabase import create_client
    client = create_client(supabase_url, supabase_key)

    positions = fetch_unposted_bio_cs_positions(client)
    if not positions:
        print("No un-posted Biology + CS positions — nothing to do")
        return 0

    print(f"Posting {len(positions)} positions to Telegram...")
    messages = build_messages(positions)
    for msg in messages:
        if not send_telegram_message(token, channel_id, msg):
            print("Telegram send failed — leaving rows un-marked for retry on next digest")
            return 1

    timestamp = datetime.now(timezone.utc).isoformat()
    uris = [p["uri"] for p in positions]
    mark_positions_as_posted(client, uris, timestamp)
    print(f"Posted {len(positions)} positions in {len(messages)} message(s); marked as posted at {timestamp}")
    return 0


if __name__ == "__main__":
    sys.exit(run_digest())
