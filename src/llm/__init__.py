"""LLM integration for job filtering and classification."""

from .base import LLMProvider, LLMUnavailableError
from .classifier import JobClassifier
from .config import DISCIPLINES, POSITION_TYPES, DEFAULT_MODEL, MISTRAL_MODEL
from .nvidia import NvidiaProvider
from .mistral import MistralProvider
from .fallback import FallbackProvider

__all__ = [
    "LLMProvider",
    "LLMUnavailableError",
    "NvidiaProvider",
    "MistralProvider",
    "FallbackProvider",
    "JobClassifier",
    "DISCIPLINES",
    "POSITION_TYPES",
    "DEFAULT_MODEL",
    "MISTRAL_MODEL",
]
