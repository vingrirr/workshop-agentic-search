"""A tiny OpenAI-compatible chat client built on ``requests``.

This replaces ``langchain_openai.ChatOpenAI``. It talks to any OpenAI-compatible
``/chat/completions`` endpoint - the same LiteLLM gateway the notebooks used -
and supports tool calling. Keeping it this small means the entire request /
response cycle is visible in the debugger.
"""

from __future__ import annotations

from typing import Any

import requests

from .config import Settings, load_settings


class LLMClient:
    """Minimal chat-completions client with tool-calling support."""

    def __init__(
        self,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        timeout: float = 120.0,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or load_settings()
        self.api_base = (api_base or settings.llm.api_base or "").rstrip("/")
        self.api_key = api_key or settings.llm.api_key
        self.model = model or settings.llm.small_model
        self.temperature = (
            settings.llm.temperature if temperature is None else temperature
        )
        self.timeout = timeout

        if not self.api_base:
            raise ValueError(
                "No LLM endpoint configured. Set LITELLM_API_BASE in your .env "
                "(see .env.example)."
            )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """Send one chat-completions request and return the assistant message.

        Returns the ``message`` object from the first choice, e.g.::

            {"role": "assistant", "content": "...", "tool_calls": [...]}
        """

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        response = requests.post(
            f"{self.api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]


def build_llm(model: str | None = None, **kwargs: Any) -> LLMClient:
    """Convenience factory mirroring the notebooks' ``ChatOpenAI(...)`` setup."""

    return LLMClient(model=model, **kwargs)
