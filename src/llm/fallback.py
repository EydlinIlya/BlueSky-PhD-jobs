"""Failover composition for LLM providers."""

import logging

from .base import LLMProvider, LLMUnavailableError

logger = logging.getLogger("bluesky_search")


class FallbackProvider(LLMProvider):
    """Use a secondary provider after the primary provider becomes unavailable.

    Failover is sticky for the lifetime of this object. This avoids repeatedly
    waiting through the primary provider's retry cycle for every classification
    when its quota or service remains unavailable.
    """

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback
        self._using_fallback = False

    @property
    def name(self) -> str:
        return f"{self.primary.name} -> {self.fallback.name}"

    def classify(self, text: str, prompt: str) -> str:
        """Classify with the primary provider, switching permanently on failure."""
        if self._using_fallback:
            return self.fallback.classify(text, prompt)

        try:
            return self.primary.classify(text, prompt)
        except LLMUnavailableError as primary_error:
            self._using_fallback = True
            logger.warning(
                f"{self.primary.name} unavailable; switching to "
                f"{self.fallback.name} for this process. Error: {primary_error}"
            )
            try:
                return self.fallback.classify(text, prompt)
            except LLMUnavailableError as fallback_error:
                raise LLMUnavailableError(
                    f"Primary provider failed ({primary_error}); "
                    f"fallback provider failed ({fallback_error})"
                ) from fallback_error
