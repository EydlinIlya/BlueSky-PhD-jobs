"""Tests for LLM provider failover."""

import pytest

from src.llm.base import LLMProvider, LLMUnavailableError
from src.llm.fallback import FallbackProvider


class StubProvider(LLMProvider):
    def __init__(self, name, responses):
        self.name = name
        self.responses = iter(responses)
        self.calls = 0

    def classify(self, text: str, prompt: str) -> str:
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_uses_primary_while_available():
    primary = StubProvider("Primary", ["YES"])
    fallback = StubProvider("Fallback", ["NO"])

    provider = FallbackProvider(primary, fallback)

    assert provider.classify("text", "prompt") == "YES"
    assert primary.calls == 1
    assert fallback.calls == 0


def test_failover_is_sticky_for_process_lifetime():
    primary = StubProvider(
        "Primary",
        [LLMUnavailableError("quota exhausted")],
    )
    fallback = StubProvider("Fallback", ["YES", "NO"])
    provider = FallbackProvider(primary, fallback)

    assert provider.classify("first", "prompt") == "YES"
    assert provider.classify("second", "prompt") == "NO"
    assert primary.calls == 1
    assert fallback.calls == 2


def test_reports_both_provider_failures():
    primary = StubProvider("Primary", [LLMUnavailableError("primary down")])
    fallback = StubProvider("Fallback", [LLMUnavailableError("fallback down")])
    provider = FallbackProvider(primary, fallback)

    with pytest.raises(
        LLMUnavailableError,
        match=r"Primary provider failed .*fallback provider failed",
    ):
        provider.classify("text", "prompt")
