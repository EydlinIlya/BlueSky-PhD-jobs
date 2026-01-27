"""LLM integration for job filtering and classification."""

from .base import LLMProvider
from .classifier import JobClassifier
from .config import DISCIPLINES, POSITION_TYPES, DEFAULT_MODEL
from .nvidia import NvidiaProvider

__all__ = ["LLMProvider", "NvidiaProvider", "JobClassifier", "DISCIPLINES", "POSITION_TYPES", "DEFAULT_MODEL"]
