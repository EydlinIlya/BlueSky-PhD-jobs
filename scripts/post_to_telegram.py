"""Post Biology + Computer Science positions to Telegram channel.

Called from bluesky_search.py with the current batch of positions.
Filters for positions with BOTH Biology AND Computer Science disciplines
(bioinformatics), formats them, and posts via Telegram Bot API.

Uses telegramify-markdown to convert plain Markdown to Telegram entities,
avoiding manual MarkdownV2 escaping issues.
"""

import os

import requests
from dotenv import load_dotenv
from telegramify_markdown import convert

load_dotenv()

TELEGRAM_MAX_LENGTH = 4096
PAGES_URL = "https://eydlinilya.github.io/BlueSky-PhD-jobs/"
REPO_URL = "https://github.com/EydlinIlya/BlueSky-PhD-jobs"

FOOTER = (
    "\n\n"
    f"[Browse all positions]({PAGES_URL}) | "
    f"[GitHub]({REPO_URL})"
)

SEPARATOR = "\n\n━━━━━━━━━━━━━━━\n\n"


def format_position(pos):
    """Format a single position as plain Markdown."""
    types = pos.get("position_type") or []
    type_tags = " | ".join(f"#{t.replace('&', '').replace('  ', ' ').replace(' ', '_')}" for t in types)

    country = pos.get("country") or ""
    country_tag = ""
    if country and country != "Unknown":
        country_tag = f" | #{country.replace(' ', '_')}"

    header = f"{type_tags}{country_tag}" if type_tags else ""

    handle = pos.get("user_handle") or ""

    message = pos.get("message") or ""
    if len(message) > 400:
        message = message[:397] + "..."

    url = pos.get("url") or ""
    link = f"[View Post]({url})" if url else ""

    lines = []
    if header:
        lines.append(header)
    if handle:
        lines.append(f"by @{handle}")
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


def send_telegram_message(token, channel_id, markdown_text):
    """Send a message to a Telegram channel using entities. Returns True on success."""
    text, entities = convert(markdown_text)
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": channel_id,
            "text": text,
            "entities": [e.to_dict() for e in entities],
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Telegram API error: {resp.status_code} {resp.text}")
        return False
    return True


def post_batch_to_telegram(all_results):
    """Post Biology + CS positions from the current batch to Telegram.

    Args:
        all_results: List of position dicts from the current search batch.

    Returns:
        True if posting succeeded (or was skipped), False on failure.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "")

    if not token or not channel_id:
        return True

    # Filter for bioinformatics: positions with BOTH Biology AND Computer Science
    positions = []
    for pos in all_results:
        disciplines = pos.get("disciplines") or []
        if "Biology" in disciplines and "Computer Science" in disciplines:
            positions.append(pos)

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
