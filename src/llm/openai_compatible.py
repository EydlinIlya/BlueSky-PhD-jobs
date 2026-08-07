"""Shared base for OpenAI-compatible chat-completions LLM providers.

NVIDIA (NIM) and Mistral both expose the same `/v1/chat/completions` shape,
so the retry / rate-limit / timeout handling lives here once. Subclasses only
set the endpoint, provider name, and default model.
"""

import logging
import time

import requests

from .base import LLMProvider, LLMUnavailableError
from .config import (
    MAX_RETRIES,
    MAX_TIMEOUT_RETRIES,
    BASE_DELAY,
    MAX_DELAY,
    REQUEST_COOLDOWN,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger("bluesky_search")


class OpenAICompatibleProvider(LLMProvider):
    """Base provider for OpenAI-compatible chat-completions APIs."""

    # Subclasses override these three.
    name = "LLM"
    api_url = ""
    default_model = ""

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or self.default_model

    def classify(self, text: str, prompt: str) -> str:
        """Send a classification prompt via a chat-completions API.

        Raises LLMUnavailableError when the provider stays rate limited or
        unreachable after all retries, so a FallbackProvider can fail over.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }

        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.post(
                    self.api_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                )

                if resp.status_code == 429:
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(
                        f"{self.name} rate limited (attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Waiting {delay}s..."
                    )
                    time.sleep(delay)
                    continue

                resp.raise_for_status()

                if REQUEST_COOLDOWN > 0:
                    time.sleep(REQUEST_COOLDOWN)

                data = resp.json()
                return data["choices"][0]["message"]["content"]

            except requests.exceptions.Timeout as e:
                if attempt < MAX_TIMEOUT_RETRIES - 1:
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(
                        f"{self.name} timeout (attempt {attempt + 1}/{MAX_TIMEOUT_RETRIES}). "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"{self.name} API unreachable after {MAX_TIMEOUT_RETRIES} attempts: {e}"
                    ) from e

            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(f"{self.name} request failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"{self.name} API failed after {MAX_RETRIES} attempts: {e}"
                    ) from e

        raise LLMUnavailableError(
            f"{self.name} API rate limited after {MAX_RETRIES} retries"
        )
