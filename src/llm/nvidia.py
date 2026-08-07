"""NVIDIA API LLM provider implementation (OpenAI-compatible chat completions)."""

from .config import DEFAULT_MODEL
from .openai_compatible import OpenAICompatibleProvider

# Single source of truth is config.DEFAULT_MODEL (llama-4-maverick: ~1s/call,
# stable on the free tier). The old llama-3.3-70b default stalled >30s under
# free-tier queuing and tripped REQUEST_TIMEOUT.
DEFAULT_NVIDIA_MODEL = DEFAULT_MODEL


class NvidiaProvider(OpenAICompatibleProvider):
    """NVIDIA API LLM provider (Llama 4 Maverick via NVIDIA NIM)."""

    name = "NVIDIA"
    api_url = "https://integrate.api.nvidia.com/v1/chat/completions"
    default_model = DEFAULT_NVIDIA_MODEL
