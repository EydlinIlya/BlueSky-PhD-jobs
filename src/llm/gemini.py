"""Gemini LLM provider implementation."""

from google import genai

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        """Initialize Gemini provider.

        Args:
            api_key: Google AI API key
            model: Model name to use (default: gemini-2.0-flash)
        """
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def classify(self, text: str, prompt: str) -> str:
        """Send a classification prompt to Gemini.

        Args:
            text: The text to classify
            prompt: The classification prompt/instructions

        Returns:
            The model's response as a string
        """
        full_prompt = f"{prompt}\n\nText: {text}"
        response = self.client.models.generate_content(
            model=self.model,
            contents=full_prompt,
        )
        return response.text
