"""Tests for the Mistral REST provider."""

import pytest
import requests

from src.llm.base import LLMUnavailableError
from src.llm.mistral import MistralProvider


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


def test_classify_uses_prompt_cache_and_ministral_14b(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse(body={"choices": [{"message": {"content": "YES"}}]})

    monkeypatch.setattr("src.llm.mistral.requests.post", fake_post)

    result = MistralProvider("secret-key").classify("A PhD opening", "Classify it")

    assert result == "YES"
    assert captured["url"] == "https://api.mistral.ai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["model"] == "ministral-14b-latest"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "Classify it"},
        {"role": "user", "content": "A PhD opening"},
    ]
    assert captured["json"]["prompt_cache_key"].startswith("phdsky-")
    assert "A PhD opening" not in captured["json"]["prompt_cache_key"]
    assert captured["json"]["temperature"] == 0
    assert captured["json"]["max_tokens"] == 256


def test_same_prompt_gets_same_cache_key():
    assert MistralProvider._cache_key("prompt") == MistralProvider._cache_key("prompt")
    assert MistralProvider._cache_key("prompt") != MistralProvider._cache_key("other")


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
        "src.llm.mistral.requests.post", lambda *args, **kwargs: next(responses)
    )
    monkeypatch.setattr("src.llm.mistral.time.sleep", lambda _: None)

    assert MistralProvider("key").classify("text", "prompt") == "NO"


def test_non_transient_http_error_becomes_unavailable(monkeypatch):
    response = FakeResponse(
        status_code=401,
        body={"error": {"message": "invalid API key"}},
    )
    monkeypatch.setattr(
        "src.llm.mistral.requests.post", lambda *args, **kwargs: response
    )

    with pytest.raises(LLMUnavailableError, match="invalid API key"):
        MistralProvider("bad-key").classify("text", "prompt")


def test_missing_content_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(
        "src.llm.mistral.requests.post",
        lambda *args, **kwargs: FakeResponse(body={"choices": []}),
    )

    with pytest.raises(LLMUnavailableError, match="no text output"):
        MistralProvider("key").classify("text", "prompt")
