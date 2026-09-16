"""NVIDIA NIM provider using its OpenAI-compatible REST API."""

import requests

from .base import LLMProvider, LLMUnavailableError
from .config import NVIDIA_MAX_COMPLETION_TOKENS, NVIDIA_MODEL, REQUEST_TIMEOUT


class NvidiaNIMProvider(LLMProvider):
    """Text classifier backed by NVIDIA's hosted NIM API catalog."""

    name = "NVIDIA NIM"
    api_url = "https://integrate.api.nvidia.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or NVIDIA_MODEL

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
    def _response_text(data: dict) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, str) and content:
                return content
        except (KeyError, IndexError, TypeError):
            pass
        raise LLMUnavailableError(
            "NVIDIA NIM returned no text output; the response may have been blocked"
        )

    def classify(self, text: str, prompt: str) -> str:
        """Send one request, failing quickly to the next configured provider."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": f"{prompt}\n\nText:\n{text}"},
            ],
            "temperature": 0,
            "max_tokens": NVIDIA_MAX_COMPLETION_TOKENS,
            "stream": False,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return self._response_text(response.json())
        except requests.exceptions.HTTPError as error:
            raise LLMUnavailableError(
                f"NVIDIA NIM returned HTTP {response.status_code}: "
                f"{self._error_detail(response)}"
            ) from error
        except requests.exceptions.RequestException as error:
            raise LLMUnavailableError(f"NVIDIA NIM unavailable: {error}") from error
