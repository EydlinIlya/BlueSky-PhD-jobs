"""Resend email provider (https://resend.com).

Uses the simple REST API over ``requests`` (already a project dependency) — no
extra SDK. Production and test sends both require ``EMAIL_FROM`` on a verified
sending domain (SPF/DKIM/DMARC for phdsky.org).

Env:
    RESEND_API_KEY   API key from the Resend dashboard.
    EMAIL_FROM       Sender, e.g. "PhD Sky <alerts@phdsky.org>".
"""

from __future__ import annotations

import os

import requests

from .base import EmailProvider

RESEND_API_URL = "https://api.resend.com/emails"
class ResendProvider(EmailProvider):
    def __init__(self, api_key: str | None = None, sender: str | None = None):
        self.api_key = api_key or os.environ.get("RESEND_API_KEY")
        self.sender = sender or os.environ.get("EMAIL_FROM")

    def send(
        self,
        to: str,
        subject: str,
        html: str,
        headers: dict | None = None,
        text: str | None = None,
    ) -> bool:
        if not self.api_key or not self.sender:
            print("ResendProvider: RESEND_API_KEY and EMAIL_FROM are required — skipping send")
            return False
        payload = {"from": self.sender, "to": [to], "subject": subject, "html": html}
        if text is not None:
            payload["text"] = text
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
