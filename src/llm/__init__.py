"""LLM integration for job filtering and classification."""

from .base import LLMProvider, LLMUnavailableError
from .classifier import JobClassifier
from .config import DISCIPLINES, GEMINI_MODEL, POSITION_TYPES
from .gemini import GeminiProvider

__all__ = [
    "LLMProvider",
    "LLMUnavailableError",
    "GeminiProvider",
    "JobClassifier",
    "DISCIPLINES",
    "POSITION_TYPES",
    "GEMINI_MODEL",
]
