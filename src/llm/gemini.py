"""Google Gemini Developer API provider."""

import logging
import time

import requests

from .base import LLMProvider, LLMUnavailableError
from .config import (
    BASE_DELAY,
    GEMINI_MODEL,
    MAX_DELAY,
    MAX_RETRIES,
    MAX_TIMEOUT_RETRIES,
    REQUEST_COOLDOWN,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger("bluesky_search")


class GeminiProvider(LLMProvider):
    """Text classifier backed by the Gemini Interactions REST API."""

    name = "Google Gemini"
    api_url = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or GEMINI_MODEL

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
    def _retry_delay(response: requests.Response, attempt: int) -> int:
        try:
            return max(
                0,
                min(int(float(response.headers.get("Retry-After", ""))), MAX_DELAY),
            )
        except ValueError:
            return min(BASE_DELAY * (2**attempt), MAX_DELAY)

    @staticmethod
    def _response_text(data: dict) -> str:
        try:
            text_parts = [
                content["text"]
                for step in data["steps"]
                if step.get("type") == "model_output"
                for content in step.get("content", [])
                if content.get("type") == "text" and content.get("text")
            ]
            if text_parts:
                return "".join(text_parts)
        except (KeyError, IndexError, TypeError):
            pass
        raise LLMUnavailableError(
            "Google Gemini API returned no text output; the response may have been blocked"
        )

    def classify(self, text: str, prompt: str) -> str:
        """Send a classification prompt, retrying transient API failures."""
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        # Gemma 4 exposes thinking as an on/off choice (minimal/high), while
        # Gemini models support the low level used by existing overrides.
        thinking_level = "minimal" if self.model.startswith("gemma-4-") else "low"
        payload = {
            "model": self.model,
            "input": f"{prompt}\n\nText:\n{text}",
            "store": False,
            "generation_config": {"thinking_level": thinking_level},
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
                        f"Google Gemini API returned HTTP {response.status_code} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}). Retrying in {delay}s. "
                        f"Detail: {self._error_detail(response)}"
                    )
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                if REQUEST_COOLDOWN > 0:
                    time.sleep(REQUEST_COOLDOWN)
                return self._response_text(response.json())

            except requests.exceptions.Timeout as error:
                if attempt < MAX_TIMEOUT_RETRIES - 1:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        f"Google Gemini API timeout "
                        f"(attempt {attempt + 1}/{MAX_TIMEOUT_RETRIES}). "
                        f"Retrying in {delay}s."
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"Google Gemini API unreachable after "
                        f"{MAX_TIMEOUT_RETRIES} attempts: {error}"
                    ) from error
            except requests.exceptions.HTTPError as error:
                detail = self._error_detail(response)
                raise LLMUnavailableError(
                    f"Google Gemini API returned HTTP {response.status_code}: {detail}"
                ) from error
            except requests.exceptions.RequestException as error:
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        f"Google Gemini API request failed: {error}. "
                        f"Retrying in {delay}s."
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"Google Gemini API failed after {MAX_RETRIES} attempts: {error}"
                    ) from error

        raise LLMUnavailableError(
            f"Google Gemini API unavailable after {MAX_RETRIES} retries"
        )
