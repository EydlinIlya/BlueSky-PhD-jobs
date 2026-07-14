"""Resend email provider (https://resend.com).

Uses the simple REST API over ``requests`` (already a project dependency) — no
extra SDK. Free tier: ~3,000/month, 100/day. Requires a verified sending domain
for ``EMAIL_FROM`` (SPF/DKIM DNS on phdsky.org); until then Resend's test domain
works for limited sends.

Env:
    RESEND_API_KEY   API key from the Resend dashboard.
    EMAIL_FROM       Sender, e.g. "PhD Sky <alerts@phdsky.org>".
"""

from __future__ import annotations

import os

import requests

from .base import EmailProvider

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "PhD Sky <onboarding@resend.dev>"  # works out-of-the-box for testing


class ResendProvider(EmailProvider):
    def __init__(self, api_key: str | None = None, sender: str | None = None):
        self.api_key = api_key or os.environ.get("RESEND_API_KEY")
        self.sender = sender or os.environ.get("EMAIL_FROM") or DEFAULT_FROM

    def send(self, to: str, subject: str, html: str, headers: dict | None = None) -> bool:
        if not self.api_key:
            print("ResendProvider: RESEND_API_KEY not set — skipping send")
            return False
        payload = {"from": self.sender, "to": [to], "subject": subject, "html": html}
        if headers:
            # Resend passes these through as email headers (e.g. List-Unsubscribe).
            payload["headers"] = headers
        try:
            resp = requests.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"ResendProvider: request failed: {e}")
            return False
        if resp.status_code >= 400:
            print(f"ResendProvider: send failed {resp.status_code}: {resp.text[:300]}")
            return False
        return True
