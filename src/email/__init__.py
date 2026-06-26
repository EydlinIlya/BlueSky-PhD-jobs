"""Email delivery for subscription digests.

Provider-agnostic: a thin ``EmailProvider`` abstraction selected by the
``EMAIL_PROVIDER`` env var (default ``resend``). Swap providers without touching
the digest logic. See ``send_subscription_digests.py``.
"""

from .base import EmailProvider, get_email_provider, send_email

__all__ = ["EmailProvider", "get_email_provider", "send_email"]
