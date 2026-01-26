"""Gemini LLM provider implementation."""

import logging
import time

from google import genai
from google.genai import errors as genai_errors

from .base import LLMProvider
from .config import DEFAULT_MODEL, MAX_RETRIES, BASE_DELAY, MAX_DELAY, REQUEST_COOLDOWN

logger = logging.getLogger("bluesky_search")


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        """Initialize Gemini provider.

        Args:
            api_key: Google AI API key
            model: Model name to use (default: gemma-3-1b-it, has higher rate limits)
        """
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def classify(self, text: str, prompt: str) -> str:
        """Send a classification prompt to Gemini with retry logic.

        Args:
            text: The text to classify
            prompt: The classification prompt/instructions

        Returns:
            The model's response as a string
        """
        full_prompt = f"{prompt}\n\nText: {text}"

        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=full_prompt,
                )
                # Cooldown to stay within rate limits
                if REQUEST_COOLDOWN > 0:
                    time.sleep(REQUEST_COOLDOWN)
                return response.text

            except genai_errors.ClientError as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    # Calculate delay with exponential backoff
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(
                        f"Gemini rate limited (attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Waiting {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    # Non-rate-limit error, re-raise
                    raise

        # If we've exhausted all retries, raise the last error
        raise genai_errors.ClientError(
            429,
            {"error": {"message": f"Rate limit exceeded after {MAX_RETRIES} retries"}},
            None,
        )
