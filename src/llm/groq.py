"""GroqCloud LLM provider using the OpenAI-compatible REST API."""

import logging
import time

import requests

from .base import LLMProvider, LLMUnavailableError
from .config import (
    BASE_DELAY,
    GROQ_MAX_COMPLETION_TOKENS,
    GROQ_MODEL,
    GROQ_REQUEST_COOLDOWN,
    MAX_DELAY,
    MAX_RETRIES,
    MAX_TIMEOUT_RETRIES,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger("bluesky_search")


class GroqProvider(LLMProvider):
    """Text classifier backed by Groq's Chat Completions REST API."""

    name = "Groq"
    api_url = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or GROQ_MODEL

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
            return max(
                0,
                min(float(response.headers.get("Retry-After", "")), MAX_DELAY),
            )
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
        raise LLMUnavailableError(
            "Groq API returned no text output; the response may have been blocked"
        )

    def classify(self, text: str, prompt: str) -> str:
        """Send a classification prompt, retrying transient API failures."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": f"{prompt}\n\nText:\n{text}"},
            ],
            "reasoning_effort": "low",
            "include_reasoning": False,
            "max_completion_tokens": GROQ_MAX_COMPLETION_TOKENS,
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
                        f"Groq API returned HTTP {response.status_code} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}). Retrying in {delay}s. "
                        f"Detail: {self._error_detail(response)}"
                    )
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                if GROQ_REQUEST_COOLDOWN > 0:
                    time.sleep(GROQ_REQUEST_COOLDOWN)
                return self._response_text(response.json())

            except requests.exceptions.Timeout as error:
                if attempt < MAX_TIMEOUT_RETRIES - 1:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        f"Groq API timeout "
                        f"(attempt {attempt + 1}/{MAX_TIMEOUT_RETRIES}). "
                        f"Retrying in {delay}s."
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"Groq API unreachable after "
                        f"{MAX_TIMEOUT_RETRIES} attempts: {error}"
                    ) from error
            except requests.exceptions.HTTPError as error:
                detail = self._error_detail(response)
                raise LLMUnavailableError(
                    f"Groq API returned HTTP {response.status_code}: {detail}"
                ) from error
            except requests.exceptions.RequestException as error:
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        f"Groq API request failed: {error}. Retrying in {delay}s."
                    )
                    time.sleep(delay)
                else:
                    raise LLMUnavailableError(
                        f"Groq API failed after {MAX_RETRIES} attempts: {error}"
                    ) from error

        raise LLMUnavailableError(
            f"Groq API unavailable after {MAX_RETRIES} retries"
        )
