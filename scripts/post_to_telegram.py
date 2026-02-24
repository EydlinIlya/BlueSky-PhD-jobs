"""Post Biology + Computer Science positions to Telegram channel.

Queries Supabase for positions indexed in the last 25 hours that are tagged
with BOTH Biology AND Computer Science disciplines, then posts them to a
Telegram channel via Bot API.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

TELEGRAM_MAX_LENGTH = 4096
PAGES_URL = "https://eydlinilya.github.io/BlueSky-PhD-jobs/"
REPO_URL = "https://github.com/EydlinIlya/BlueSky-PhD-jobs"

FOOTER = (
    "\n\n"
    f"[Browse all positions]({PAGES_URL}) \\| "
    f"[GitHub]({REPO_URL})"
)


def escape_md(text):
    """Escape MarkdownV2 special characters."""
    for ch in ["\\", "_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        text = text.replace(ch, f"\\{ch}")
    return text


def to_hashtag(text):
    """Convert text to a Telegram hashtag: spaces → underscores, remove &."""
    return "\\#" + text.replace("&", "").replace("  ", " ").replace(" ", "_")


def format_position(pos):
    """Format a single position as a Markdown block."""
    # Position type hashtags
    types = pos.get("position_type") or []
    type_tags = " \\| ".join(to_hashtag(t) for t in types)

    # Country hashtag
    country = pos.get("country") or ""
    country_tag = ""
    if country and country != "Unknown":
        country_tag = f" \\| {to_hashtag(country)}"

    header = f"{type_tags}{country_tag}" if type_tags else ""

    # User handle
    handle = pos.get("user_handle") or ""

    # Message text — truncate to ~400 chars
    message = pos.get("message") or ""
    if len(message) > 400:
        message = message[:397] + "..."

    message = escape_md(message)

    # Post URL
    url = pos.get("url") or ""
    link = f"[View Post]({url})" if url else ""

    lines = []
    if header:
        lines.append(header)
    if handle:
        lines.append(f"by {escape_md('@' + handle)}")
    lines.append("")
    lines.append(message)
    if link:
        lines.append("")
        lines.append(link)

    return "\n".join(lines)


SEPARATOR = "\n\n━━━━━━━━━━━━━━━\n\n"


def build_messages(positions):
    """Batch positions into messages under the Telegram character limit.

    Returns a list of message strings. The last message gets a footer.
    """
    if not positions:
        return []

    formatted = [format_position(p) for p in positions]

    messages = []
    current = ""

    for i, block in enumerate(formatted):
        candidate = block if not current else current + SEPARATOR + block

        # Check if adding this block (plus potential footer) exceeds limit
        if len(candidate) > TELEGRAM_MAX_LENGTH - len(FOOTER) - 10:
            if current:
                messages.append(current)
            current = block
        else:
            current = candidate

    if current:
        messages.append(current)

    # Add footer to last message
    if messages:
        messages[-1] += FOOTER

    return messages


def send_telegram_message(token, channel_id, text):
    """Send a message to a Telegram channel. Returns True on success."""
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": channel_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Telegram API error: {resp.status_code} {resp.text}")
        return False
    return True


def fetch_recent_positions(client):
    """Fetch positions indexed in the last 25 hours with Bio + CS disciplines."""
    since = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()

    result = (
        client.table("phd_positions")
        .select("uri, message, url, user_handle, created_at, disciplines, country, position_type")
        .eq("is_verified_job", True)
        .is_("duplicate_of", "null")
        .gte("indexed_at", since)
        .order("created_at", desc=True)
        .execute()
    )

    # Filter for positions with BOTH Biology AND Computer Science
    positions = []
    for pos in result.data:
        disciplines = pos.get("disciplines") or []
        if "Biology" in disciplines and "Computer Science" in disciplines:
            positions.append(pos)

    return positions


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: SUPABASE_URL and SUPABASE_KEY are required")
        sys.exit(1)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("Warning: TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID not set, skipping")
        sys.exit(0)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Fetching recent Biology + CS positions...")
    positions = fetch_recent_positions(client)
    print(f"Found {len(positions)} matching positions")

    if not positions:
        print("No new Biology + CS positions to post")
        return

    messages = build_messages(positions)
    print(f"Sending {len(messages)} message(s) to Telegram...")

    sent = 0
    for msg in messages:
        if send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, msg):
            sent += 1
        else:
            print("Failed to send message, stopping")
            sys.exit(1)

    print(f"Posted {len(positions)} positions in {sent} message(s)")


if __name__ == "__main__":
    main()
