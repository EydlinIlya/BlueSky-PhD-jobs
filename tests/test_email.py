"""Tests for the email provider abstraction (src/email)."""

from src.email import send_email, get_email_provider
from src.email.base import EmailProvider
from src.email.resend_provider import ResendProvider


class MockProvider(EmailProvider):
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.sent = []

    def send(self, to, subject, html, headers=None):
        self.sent.append({"to": to, "subject": subject, "html": html, "headers": headers})
        return self.succeed


def test_send_email_dispatches_to_provider():
    mock = MockProvider()
    ok = send_email("a@b.com", "Hi", "<p>x</p>", provider=mock)
    assert ok is True
    assert len(mock.sent) == 1
    assert mock.sent[0]["to"] == "a@b.com"


def test_send_email_reports_failure():
    mock = MockProvider(succeed=False)
    assert send_email("a@b.com", "Hi", "<p>x</p>", provider=mock) is False


def test_factory_returns_resend_by_default():
    assert isinstance(get_email_provider("resend"), ResendProvider)


def test_unknown_provider_raises():
    import pytest
    with pytest.raises(ValueError):
        get_email_provider("smoke-signals")


def test_resend_returns_false_without_api_key(monkeypatch):
    # No network call should happen when the key is missing. Clear any key that a
    # loaded .env may have put in the environment so the test is deterministic.
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    provider = ResendProvider(api_key=None)
    assert provider.send("a@b.com", "Hi", "<p>x</p>") is False
