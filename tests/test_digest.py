"""Subscription digest consent, matching, formatting, and watermark tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import send_subscription_digests as digest  # noqa: E402


def pos(**kw):
    base = {
        "uri": "at://x", "created_at": "2026-06-01T00:00:00+00:00",
        "disciplines": ["Biology"], "country": "Germany",
        "position_type": ["PhD Student"], "user_handle": "alice.bsky.social",
        "message": "Fully funded PhD in plant genomics", "url": "https://bsky.app/x",
        "is_verified_job": True, "duplicate_of": None,
    }
    base.update(kw)
    return base


def sub(**kw):
    base = {
        "id": "sub-1", "user_id": "user-1", "disciplines": ["Biology"],
        "countries": [], "position_types": [], "query_text": None,
        "hide_aggregators": False, "unsubscribe_token": "9ce173c1-0f68-4f8a-a742-bcbb5a434d18",
        "cadence": "weekly", "deliver_email": True,
        "email_consent_at": "2026-05-01T00:00:00+00:00",
        "created_at": "2026-05-01T00:00:00+00:00", "last_processed_at": None,
        "last_notified_at": None,
    }
    base.update(kw)
    return base


def test_matching_filters_and_query():
    assert digest.position_matches({}, pos()) is True
    assert digest.position_matches({"disciplines": ["Computer Science", "Biology"]}, pos()) is True
    assert digest.position_matches({"disciplines": ["Physics"]}, pos()) is False
    assert digest.position_matches({"countries": ["Germany"], "position_types": ["Postdoc"]}, pos(position_type=["Postdoc"])) is True
    assert digest.position_matches({"query_text": "genomics"}, pos()) is True
    assert digest.position_matches({"query_text": "quantum"}, pos()) is False


def test_hide_aggregators(monkeypatch):
    monkeypatch.setattr(digest, "AGGREGATORS", {"bot.bsky.social"})
    assert digest.position_matches({"hide_aggregators": True}, pos(user_handle="bot.bsky.social")) is False


def test_subscription_label_and_urls():
    row = sub(disciplines=["Biology"], countries=["Germany"])
    assert digest.subscription_label(row) == "Biology · Germany"
    assert digest.subscription_label({}) == "all positions"
    assert "/unsubscribe?token=" in digest.human_unsubscribe_url(row)
    assert "/api/unsubscribe?token=" in digest.machine_unsubscribe_url(row)


def test_digest_has_light_palette_plain_text_and_management_link():
    row = sub()
    positions = [pos(), pos(uri="at://y")]
    body = digest.format_digest_html(row, positions)
    text = digest.format_digest_text(row, positions)
    assert "#F3F5F2" in body and "#18594A" in body
    assert "2 new positions" in body
    assert "/#subscriptions" in body
    assert "operated by Eli Eydlin in Israel" in body
    assert "2 new positions" in text
    assert "Manage weekly alerts:" in text


def test_digest_escapes_every_listing_field():
    malicious = pos(
        message='<img src=x onerror="alert(1)">',
        position_type=['<script>bad()</script>'],
        country='"><svg/onload=alert(1)>',
        url='https://example.test/" onclick="alert(1)',
    )
    body = digest.format_digest_html(sub(), [malicious])
    assert "<script>bad()" not in body
    assert "<img src=x" not in body
    assert "&lt;script&gt;" in body
    assert "&quot; onclick=&quot;" in body


def test_digest_discloses_overflow():
    count = digest.MAX_POSITIONS_PER_DIGEST + 12
    body = digest.format_digest_html(sub(), [pos(uri=f"at://x{i}") for i in range(count)])
    assert f"{count} new positions" in body
    assert f"Showing the {digest.MAX_POSITIONS_PER_DIGEST} newest matches" in body
    assert "Browse 12 more on PhD Sky" in body
    assert body.count("View source") == digest.MAX_POSITIONS_PER_DIGEST


class FakeQuery:
    def __init__(self, client, table):
        self.client, self.table = client, table
        self.filters = []
        self.start, self.end = None, None
        self.payload = None

    def select(self, *args, **kwargs): return self
    def order(self, *args, **kwargs): return self
    def limit(self, count): self.start, self.end = 0, count - 1; return self
    def range(self, start, end): self.start, self.end = start, end; return self
    def eq(self, key, value): self.filters.append(("eq", key, value)); return self
    def is_(self, key, value): self.filters.append(("is", key, value)); return self
    def gt(self, key, value): self.filters.append(("gt", key, value)); return self
    def update(self, payload): self.payload = payload; return self

    def execute(self):
        rows = self.client.rows.setdefault(self.table, [])
        def matches(row):
            for operation, key, value in self.filters:
                current = row.get(key)
                if operation == "eq" and current != value: return False
                if operation == "is" and value == "null" and current is not None: return False
                if operation == "gt" and not (current and current > value): return False
            return True
        matching = [row for row in rows if matches(row)]
        if self.payload is not None:
            for row in matching: row.update(self.payload)
            self.client.writes.append({"table": self.table, "payload": self.payload, "count": len(matching)})
            return type("Result", (), {"data": matching})()
        if self.start is not None: matching = matching[self.start:self.end + 1]
        return type("Result", (), {"data": matching})()


class FakeClient:
    def __init__(self, rows):
        self.rows, self.writes = rows, []
    def table(self, name): return FakeQuery(self, name)


def fake_send(captured, succeed=True):
    def send(to, subject, html, headers=None, text=None):
        captured.append({"to": to, "subject": subject, "html": html, "headers": headers, "text": text})
        return succeed
    return send


def enable_test_config(monkeypatch):
    monkeypatch.setattr(digest, "check_email_config", lambda: ([], []))
    monkeypatch.setattr(digest, "report_email_config", lambda: True)


def test_only_explicitly_consented_subscriptions_are_due():
    client = FakeClient({"subscriptions": [
        sub(id="yes"),
        sub(id="legacy", email_consent_at=None),
        sub(id="paused", deliver_email=False),
        sub(id="daily", cadence="daily"),
    ]})
    assert [row["id"] for row in digest.fetch_due_subscriptions(client)] == ["yes"]


def test_no_match_advances_processing_not_notification(monkeypatch):
    enable_test_config(monkeypatch)
    client = FakeClient({
        "subscriptions": [sub()],
        "phd_positions": [pos(disciplines=["Physics"])],
        "profiles": [{"id": "user-1", "email": "current@example.com"}],
    })
    monkeypatch.setattr(digest, "get_client", lambda: client)
    monkeypatch.setattr(digest, "send_email", pytest.fail)
    assert digest.run() == 0
    payload = client.writes[-1]["payload"]
    assert payload == {"last_processed_at": "2026-06-01T00:00:00+00:00"}
    assert client.rows["subscriptions"][0]["last_notified_at"] is None


def test_failed_send_advances_neither_watermark(monkeypatch):
    enable_test_config(monkeypatch)
    client = FakeClient({
        "subscriptions": [sub()], "phd_positions": [pos()],
        "profiles": [{"id": "user-1", "email": "current@example.com"}],
    })
    monkeypatch.setattr(digest, "get_client", lambda: client)
    monkeypatch.setattr(digest, "send_email", fake_send([], succeed=False))
    assert digest.run() == 0
    assert client.writes == []


def test_success_uses_current_profile_email_text_and_exact_headers(monkeypatch):
    enable_test_config(monkeypatch)
    client = FakeClient({
        "subscriptions": [sub()], "phd_positions": [pos()],
        "profiles": [{"id": "user-1", "email": "current@example.com"}],
    })
    monkeypatch.setattr(digest, "get_client", lambda: client)
    captured = []
    monkeypatch.setattr(digest, "send_email", fake_send(captured))
    assert digest.run() == 1
    sent = captured[0]
    machine = digest.machine_unsubscribe_url(sub())
    assert sent["to"] == "current@example.com"
    assert sent["text"] and "PhD Sky" in sent["text"]
    assert sent["headers"] == {
        "List-Unsubscribe": f"<{machine}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    payload = client.writes[-1]["payload"]
    assert payload["last_processed_at"] == "2026-06-01T00:00:00+00:00"
    assert payload["last_notified_at"] == "2026-06-01T00:00:00+00:00"


def test_test_send_is_inert(monkeypatch):
    enable_test_config(monkeypatch)
    client = FakeClient({
        "subscriptions": [sub()], "phd_positions": [pos()],
        "profiles": [{"id": "user-1", "email": "subscriber@example.com"}],
    })
    monkeypatch.setattr(digest, "get_client", lambda: client)
    captured = []
    monkeypatch.setattr(digest, "send_email", fake_send(captured))
    assert digest.run_test("tester@example.com") == 1
    assert captured[0]["to"] == "tester@example.com"
    assert "subscriber@example.com" not in str(captured)
    assert client.writes == []


def test_watermark_prefers_last_processed():
    assert digest.subscription_watermark({
        "last_processed_at": "2026-07-01T00:00:00+00:00",
        "last_notified_at": "2026-06-01T00:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
    }) == "2026-07-01T00:00:00+00:00"
    assert digest.subscription_watermark({"created_at": "2026-01-01T00:00:00+00:00"}) == "2026-01-01T00:00:00+00:00"


def test_config_requires_service_key_verified_sender_and_no_fallback(monkeypatch):
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "RESEND_API_KEY", "EMAIL_FROM"):
        monkeypatch.delenv(key, raising=False)
    blocking, _ = digest.check_email_config()
    assert any("SUPABASE_SERVICE_KEY" in item for item in blocking)
    assert any("EMAIL_FROM" in item for item in blocking)
    monkeypatch.setenv("EMAIL_FROM", "PhD Sky <onboarding@resend.dev>")
    assert any("verified" in item for item in digest.check_email_config()[0])
