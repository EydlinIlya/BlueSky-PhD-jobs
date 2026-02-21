"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod


class LLMUnavailableError(Exception):
    """Raised when the LLM API is unreachable after all retries."""


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def classify(self, text: str, prompt: str) -> str:
        """Send a classification prompt to the LLM.

        Args:
            text: The text to classify
            prompt: The classification prompt/instructions

        Returns:
            The LLM's response as a string
        """
        pass
