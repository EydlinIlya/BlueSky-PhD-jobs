"""Fallback LLM provider: try providers in priority order, fail over on outage.

Wraps an ordered list of providers (e.g. [NVIDIA, Mistral]). Each call tries
the highest-priority provider that isn't in cooldown. When a provider raises
LLMUnavailableError (rate limited / unreachable after its own retries), it is
put in cooldown for FALLBACK_COOLDOWN seconds and the next provider is tried.

The cooldown matters because classification runs per-post in a tight loop: once
NVIDIA is rate limited we don't want to burn its full retry/backoff budget on
every single post before falling to Mistral — we skip it for a while instead.
"""

import logging
import time

from .base import LLMProvider, LLMUnavailableError
from .config import FALLBACK_COOLDOWN

logger = logging.getLogger("bluesky_search")


class FallbackProvider(LLMProvider):
    """Try providers in order; fail over to the next on LLMUnavailableError."""

    def __init__(self, providers: list[LLMProvider], cooldown_seconds: int = FALLBACK_COOLDOWN):
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider")
        self.providers = list(providers)
        self.cooldown_seconds = cooldown_seconds
        self._disabled_until: dict[int, float] = {}

    def classify(self, text: str, prompt: str) -> str:
        now = time.monotonic()
        # Prefer providers not in cooldown (preserving priority order); if every
        # provider is cooling down, fall through and try them all anyway.
        available = [i for i in range(len(self.providers)) if self._disabled_until.get(i, 0.0) <= now]
        candidates = available or list(range(len(self.providers)))

        last_error: Exception | None = None
        for i in candidates:
            provider = self.providers[i]
            try:
                return provider.classify(text, prompt)
            except LLMUnavailableError as e:
                last_error = e
                self._disabled_until[i] = time.monotonic() + self.cooldown_seconds
                remaining = [j for j in candidates if j > i]
                if remaining:
                    next_name = getattr(self.providers[remaining[0]], "name", "next provider")
                    logger.warning(
                        f"{getattr(provider, 'name', 'provider')} unavailable, "
                        f"failing over to {next_name}: {e}"
                    )
                else:
                    logger.error(f"All LLM providers unavailable. Last error: {e}")

        raise last_error or LLMUnavailableError("No LLM providers available")
