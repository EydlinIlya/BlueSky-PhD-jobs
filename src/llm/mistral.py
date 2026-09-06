"""Mistral API LLM provider (OpenAI-compatible chat completions).

Used as a fallback for NVIDIA when the primary is rate limited or unavailable.
"""

from .config import MISTRAL_BASE_URL, MISTRAL_MODEL
from .openai_compatible import OpenAICompatibleProvider


class MistralProvider(OpenAICompatibleProvider):
    """Mistral La Plateforme LLM provider."""

    name = "Mistral"
    api_url = f"{MISTRAL_BASE_URL}/v1/chat/completions"
    default_model = MISTRAL_MODEL
