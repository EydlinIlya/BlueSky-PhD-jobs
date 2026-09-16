"""Tests for the Groq REST provider."""

import pytest
import requests

from src.llm.base import LLMUnavailableError
from src.llm.groq import GroqProvider


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}
        self.text = ""
        self.reason = ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)


def test_classify_uses_groq_chat_completions(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse(
            body={"choices": [{"message": {"content": "YES"}}]},
        )

    monkeypatch.setattr("src.llm.groq.requests.post", fake_post)
    monkeypatch.setattr("src.llm.groq.GROQ_REQUEST_COOLDOWN", 0)

    result = GroqProvider("secret-key").classify("A PhD opening", "Classify it")

    assert result == "YES"
    assert captured["url"].endswith("/openai/v1/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["model"] == "openai/gpt-oss-120b"
    assert captured["json"]["messages"] == [
        {"role": "user", "content": "Classify it\n\nText:\nA PhD opening"},
    ]
    assert captured["json"]["reasoning_effort"] == "low"
    assert captured["json"]["include_reasoning"] is False
    assert captured["json"]["max_completion_tokens"] == 512


def test_rate_limit_retries_then_succeeds(monkeypatch):
    responses = iter(
        [
            FakeResponse(
                status_code=429,
                body={"error": {"message": "rate limit exceeded"}},
                headers={"Retry-After": "0"},
            ),
            FakeResponse(body={"choices": [{"message": {"content": "NO"}}]}),
        ]
    )
    monkeypatch.setattr(
        "src.llm.groq.requests.post",
        lambda *args, **kwargs: next(responses),
    )
    monkeypatch.setattr("src.llm.groq.GROQ_REQUEST_COOLDOWN", 0)
    monkeypatch.setattr("src.llm.groq.time.sleep", lambda _: None)

    assert GroqProvider("key").classify("text", "prompt") == "NO"


def test_non_transient_http_error_becomes_unavailable(monkeypatch):
    response = FakeResponse(
        status_code=401,
        body={"error": {"message": "invalid API key"}},
    )
    monkeypatch.setattr(
        "src.llm.groq.requests.post",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(LLMUnavailableError, match="invalid API key"):
        GroqProvider("bad-key").classify("text", "prompt")


def test_missing_content_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(
        "src.llm.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(body={"choices": []}),
    )
    monkeypatch.setattr("src.llm.groq.GROQ_REQUEST_COOLDOWN", 0)

    with pytest.raises(LLMUnavailableError, match="no text output"):
        GroqProvider("key").classify("text", "prompt")
