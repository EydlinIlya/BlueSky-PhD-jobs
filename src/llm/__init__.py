"""LLM integration for job filtering and classification."""

from .base import LLMProvider, LLMUnavailableError
from .classifier import JobClassifier
from .config import (
    DISCIPLINES,
    GEMINI_MODEL,
    GROQ_MODEL,
    MISTRAL_MODEL,
    NVIDIA_MODEL,
    POSITION_TYPES,
)
from .fallback import FallbackProvider
from .gemini import GeminiProvider
from .groq import GroqProvider
from .mistral import MistralProvider
from .nvidia import NvidiaNIMProvider

__all__ = [
    "LLMProvider",
    "LLMUnavailableError",
    "FallbackProvider",
    "GeminiProvider",
    "GroqProvider",
    "MistralProvider",
    "NvidiaNIMProvider",
    "JobClassifier",
    "DISCIPLINES",
    "POSITION_TYPES",
    "GEMINI_MODEL",
    "GROQ_MODEL",
    "MISTRAL_MODEL",
    "NVIDIA_MODEL",
]
