"""Tests for the Google Gemini REST provider."""

import pytest
import requests

from src.llm.base import LLMUnavailableError
from src.llm.gemini import GeminiProvider


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


def test_classify_uses_default_gemma_rest_api(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse(
            body={"steps": [{"type": "model_output", "content": [{"type": "text", "text": "YES"}]}]}
        )

    monkeypatch.setattr("src.llm.gemini.requests.post", fake_post)
    monkeypatch.setattr("src.llm.gemini.REQUEST_COOLDOWN", 0)

    result = GeminiProvider("secret-key").classify("A PhD opening", "Classify it")

    assert result == "YES"
    assert captured["url"].endswith("/v1beta/interactions")
    assert captured["headers"]["x-goog-api-key"] == "secret-key"
    assert captured["json"]["model"] == "gemma-4-31b-it"
    assert captured["json"]["input"] == "Classify it\n\nText:\nA PhD opening"
    assert captured["json"]["store"] is False
    assert captured["json"]["generation_config"]["thinking_level"] == "minimal"


def test_gemini_override_uses_low_thinking(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse(
            body={"steps": [{"type": "model_output", "content": [{"type": "text", "text": "YES"}]}]}
        )

    monkeypatch.setattr("src.llm.gemini.requests.post", fake_post)
    monkeypatch.setattr("src.llm.gemini.REQUEST_COOLDOWN", 0)

    GeminiProvider("secret-key", model="gemini-3.8-flash").classify(
        "A PhD opening", "Classify it"
    )

    assert captured["json"]["generation_config"]["thinking_level"] == "low"


def test_rate_limit_retries_then_succeeds(monkeypatch):
    responses = iter(
        [
            FakeResponse(
                status_code=429,
                body={"error": {"message": "quota exceeded"}},
                headers={"Retry-After": "0"},
            ),
            FakeResponse(
                body={"steps": [{"type": "model_output", "content": [{"type": "text", "text": "NO"}]}]}
            ),
        ]
    )
    monkeypatch.setattr("src.llm.gemini.requests.post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr("src.llm.gemini.REQUEST_COOLDOWN", 0)
    monkeypatch.setattr("src.llm.gemini.time.sleep", lambda _: None)

    assert GeminiProvider("key").classify("text", "prompt") == "NO"


def test_non_transient_http_error_becomes_unavailable(monkeypatch):
    response = FakeResponse(
        status_code=400,
        body={"error": {"message": "invalid API key"}},
    )
    monkeypatch.setattr("src.llm.gemini.requests.post", lambda *args, **kwargs: response)

    with pytest.raises(LLMUnavailableError, match="invalid API key"):
        GeminiProvider("bad-key").classify("text", "prompt")


def test_missing_candidate_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(
        "src.llm.gemini.requests.post",
        lambda *args, **kwargs: FakeResponse(body={"steps": []}),
    )
    monkeypatch.setattr("src.llm.gemini.REQUEST_COOLDOWN", 0)

    with pytest.raises(LLMUnavailableError, match="no text output"):
        GeminiProvider("key").classify("text", "prompt")
