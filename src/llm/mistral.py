"""Mistral chat-completions provider with prompt-cache support."""

import hashlib
import logging
import threading
import time

import requests

from .base import LLMProvider, LLMUnavailableError
from .config import (
    BASE_DELAY,
    MAX_DELAY,
    MAX_RETRIES,
    MAX_TIMEOUT_RETRIES,
    MISTRAL_MAX_COMPLETION_TOKENS,
    MISTRAL_MODEL,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger("bluesky_search")


class MistralProvider(LLMProvider):
    """Classifier backed by Mistral's OpenAI-compatible REST API."""

    name = "Mistral"
    api_url = "https://api.mistral.ai/v1/chat/completions"

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or MISTRAL_MODEL
        self.usage_totals = {
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
        }
        self._usage_lock = threading.Lock()

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error", body)
                if isinstance(error, dict):
                    return str(error.get("message") or error)
                return str(error)
        except ValueError:
            pass
        return response.text[:500] or response.reason

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        try:
            retry_after = float(response.headers.get("Retry-After", ""))
            return max(0, min(retry_after, MAX_DELAY))
        except ValueError:
            return min(BASE_DELAY * (2**attempt), MAX_DELAY)

    @staticmethod
    def _response_text(data: dict) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, str) and content:
                return content
        except (KeyError, IndexError, TypeError):
            pass
        raise LLMUnavailableError("Mistral returned no text output")

    @staticmethod
    def _cache_key(prompt: str) -> str:
        """Keep repeated instructions cacheable without putting user data in the key."""
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return f"phdsky-{digest}"

    def _record_usage(self, data: dict) -> None:
        usage = data.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        with self._usage_lock:
            self.usage_totals["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
            self.usage_totals["cached_tokens"] += details.get("cached_tokens", 0) or 0
            self.usage_totals["completion_tokens"] += (
                usage.get("completion_tokens", 0) or 0
            )

    def classify(self, text: str, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "prompt_cache_key": self._cache_key(prompt),
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "max_tokens": MISTRAL_MAX_COMPLETION_TOKENS,
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    delay = self._retry_delay(response, attempt)
                    logger.warning(
                        "Mistral returned HTTP %s (attempt %s/%s); retrying in %ss. %s",
                        response.status_code,
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                        self._error_detail(response),
                    )
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                data = response.json()
                self._record_usage(data)
                return self._response_text(data)
            except requests.exceptions.Timeout as error:
                if attempt < MAX_TIMEOUT_RETRIES - 1:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        "Mistral timeout (attempt %s/%s); retrying in %ss.",
                        attempt + 1,
                        MAX_TIMEOUT_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        "Mistral unreachable after "
                        f"{MAX_TIMEOUT_RETRIES} attempts: {error}"
                    ) from error
            except requests.exceptions.HTTPError as error:
                raise LLMUnavailableError(
                    f"Mistral returned HTTP {response.status_code}: "
                    f"{self._error_detail(response)}"
                ) from error
            except requests.exceptions.RequestException as error:
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        "Mistral request failed: %s; retrying in %ss.", error, delay
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"Mistral failed after {MAX_RETRIES} attempts: {error}"
                    ) from error

        raise LLMUnavailableError(f"Mistral unavailable after {MAX_RETRIES} retries")
