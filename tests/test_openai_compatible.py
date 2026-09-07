"""Failure-mode tests shared by NVIDIA and Mistral chat providers."""

import pytest
import requests

from src.llm.base import LLMUnavailableError
from src.llm.openai_compatible import OpenAICompatibleProvider


class ZeroRpmProvider(OpenAICompatibleProvider):
    name = "Mistral"
    api_url = "https://example.invalid/v1/chat/completions"
    default_model = "test-model"


def test_zero_rpm_rate_limit_fails_over_without_backoff(monkeypatch):
    response = requests.Response()
    response.status_code = 429
    response.url = "https://example.invalid/v1/chat/completions"
    response.headers["x-ratelimit-limit-req-minute"] = "0"
    response._content = b'{"message":"Rate limit exceeded"}'
    monkeypatch.setattr("src.llm.openai_compatible.requests.post", lambda *args, **kwargs: response)

    with pytest.raises(LLMUnavailableError, match="0 requests/minute allocation"):
        ZeroRpmProvider("test-key").classify("position", "classify it")
