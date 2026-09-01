"""Email provider abstraction.

Mirrors the ``src/llm`` and ``src/storage`` pattern: an abstract base plus a
factory that picks a concrete provider from the environment. This keeps the
digest job decoupled from any single email vendor (Resend today, swappable
later via ``EMAIL_PROVIDER``).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class EmailProvider(ABC):
    """Sends transactional/digest email. Implementations must be idempotent-safe
    from the caller's perspective: a ``False`` return means "not sent, retry"."""

    @abstractmethod
    def send(self, to: str, subject: str, html: str, headers: dict | None = None) -> bool:
        """Send one email. Returns True on success, False on failure (no raise).

        ``headers`` carries optional extra SMTP headers (e.g. ``List-Unsubscribe``).
        """
        raise NotImplementedError


def get_email_provider(name: str | None = None) -> EmailProvider:
    """Factory. ``name`` overrides the ``EMAIL_PROVIDER`` env (default 'resend')."""
    provider = (name or os.environ.get("EMAIL_PROVIDER") or "resend").lower()
    if provider == "resend":
        from .resend_provider import ResendProvider
        return ResendProvider()
    raise ValueError(f"Unknown EMAIL_PROVIDER: {provider!r}")


def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    headers: dict | None = None,
    provider: EmailProvider | None = None,
) -> bool:
    """Convenience: send a single email using the configured provider."""
    return (provider or get_email_provider()).send(to, subject, html, headers=headers)
