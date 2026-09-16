"""Tests for the NVIDIA NIM REST provider."""

import pytest
import requests

from src.llm.base import LLMUnavailableError
from src.llm.nvidia import NvidiaNIMProvider


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = ""
        self.reason = ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)


def test_classify_uses_hosted_nim_chat_api(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse(body={"choices": [{"message": {"content": "YES"}}]})

    monkeypatch.setattr("src.llm.nvidia.requests.post", fake_post)

    result = NvidiaNIMProvider("secret-key").classify(
        "A PhD opening", "Classify it"
    )

    assert result == "YES"
    assert captured["url"] == (
        "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["model"] == "google/gemma-4-31b-it"
    assert captured["json"]["messages"] == [
        {"role": "user", "content": "Classify it\n\nText:\nA PhD opening"},
    ]
    assert captured["json"]["temperature"] == 0
    assert captured["json"]["max_tokens"] == 512
    assert captured["json"]["stream"] is False


def test_http_error_becomes_unavailable(monkeypatch):
    response = FakeResponse(
        status_code=401,
        body={"error": {"message": "invalid API key"}},
    )
    monkeypatch.setattr(
        "src.llm.nvidia.requests.post",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(LLMUnavailableError, match="invalid API key"):
        NvidiaNIMProvider("bad-key").classify("text", "prompt")


def test_connection_error_becomes_unavailable(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr("src.llm.nvidia.requests.post", fail)

    with pytest.raises(LLMUnavailableError, match="connection refused"):
        NvidiaNIMProvider("key").classify("text", "prompt")


def test_missing_content_becomes_unavailable(monkeypatch):
    monkeypatch.setattr(
        "src.llm.nvidia.requests.post",
        lambda *args, **kwargs: FakeResponse(body={"choices": []}),
    )

    with pytest.raises(LLMUnavailableError, match="no text output"):
        NvidiaNIMProvider("key").classify("text", "prompt")
