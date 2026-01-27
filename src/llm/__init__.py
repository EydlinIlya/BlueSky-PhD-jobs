"""LLM integration for job filtering and classification."""

from .base import LLMProvider
from .classifier import JobClassifier
from .config import DISCIPLINES, POSITION_TYPES, DEFAULT_MODEL
from .gemini import GeminiProvider
from .nvidia import NvidiaProvider

__all__ = ["LLMProvider", "GeminiProvider", "NvidiaProvider", "JobClassifier", "DISCIPLINES", "POSITION_TYPES", "DEFAULT_MODEL"]
