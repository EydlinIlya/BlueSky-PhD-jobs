"""NVIDIA API LLM provider implementation (OpenAI-compatible chat completions)."""

import logging
import time

import requests

from .base import LLMProvider, LLMUnavailableError
from .config import MAX_RETRIES, MAX_TIMEOUT_RETRIES, BASE_DELAY, MAX_DELAY, REQUEST_COOLDOWN, REQUEST_TIMEOUT

logger = logging.getLogger("bluesky_search")

DEFAULT_NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


class NvidiaProvider(LLMProvider):
    """NVIDIA API LLM provider (Llama 4 Maverick via NVIDIA NIM)."""

    def __init__(self, api_key: str, model: str = DEFAULT_NVIDIA_MODEL):
        self.api_key = api_key
        self.model = model

    def classify(self, text: str, prompt: str) -> str:
        """Send a classification prompt via NVIDIA's chat completions API."""
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
                    NVIDIA_API_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                )

                if resp.status_code == 429:
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(
                        f"NVIDIA rate limited (attempt {attempt + 1}/{MAX_RETRIES}). "
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
                # Timeouts suggest the API is unreachable — use a shorter retry budget
                if attempt < MAX_TIMEOUT_RETRIES - 1:
                    delay = BASE_DELAY
                    logger.warning(
                        f"NVIDIA timeout (attempt {attempt + 1}/{MAX_TIMEOUT_RETRIES}). "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"NVIDIA API unreachable after {MAX_TIMEOUT_RETRIES} attempts: {e}"
                    ) from e

            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(f"NVIDIA request failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise

        raise RuntimeError(f"NVIDIA API failed after {MAX_RETRIES} retries")
