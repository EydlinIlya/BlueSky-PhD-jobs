"""Tests for selecting configured LLM providers."""

from bluesky_search import get_classifier
from src.llm import (
    FallbackProvider,
    GeminiProvider,
    GroqProvider,
    MistralProvider,
    NvidiaNIMProvider,
)


def test_no_api_keys_disables_classifier(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    assert get_classifier() is None


def test_gemini_only(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    classifier = get_classifier()

    assert isinstance(classifier.llm, GeminiProvider)


def test_groq_only(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    classifier = get_classifier()

    assert isinstance(classifier.llm, GroqProvider)


def test_mistral_then_gemini_then_nvidia_then_groq(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    classifier = get_classifier()

    assert isinstance(classifier.llm, FallbackProvider)
    assert isinstance(classifier.llm.primary, MistralProvider)
    assert isinstance(classifier.llm.fallback, FallbackProvider)
    assert isinstance(classifier.llm.fallback.primary, GeminiProvider)
    assert classifier.llm.fallback.primary.fail_fast_on_rate_limit is True
    assert isinstance(classifier.llm.fallback.fallback, FallbackProvider)
    assert isinstance(classifier.llm.fallback.fallback.primary, NvidiaNIMProvider)
    assert isinstance(classifier.llm.fallback.fallback.fallback, GroqProvider)


def test_mistral_only(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    classifier = get_classifier()

    assert isinstance(classifier.llm, MistralProvider)


def test_nvidia_can_operate_alone(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-key")

    classifier = get_classifier()

    assert isinstance(classifier.llm, NvidiaNIMProvider)
