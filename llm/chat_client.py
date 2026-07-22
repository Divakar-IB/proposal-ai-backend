from typing import Any, Iterator, Optional

from openai import OpenAI

from config import config


class GroqChatClient:
    """Shared GPT-OSS (via Groq) chat-completions wrapper — used by both
    requirements_parsing (structured extraction) and generation (drafting/quality_check)."""

    _client: OpenAI | None = None

    @classmethod
    def get_client(cls) -> OpenAI:
        if cls._client is None:
            cls._client = OpenAI(
                api_key=config.groq.api_key,
                base_url=config.groq.base_url,
            )
        return cls._client

    @classmethod
    def complete(
        cls,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[dict[str, Any]] = None,
        temperature: float = 0.2,
    ):
        client = cls.get_client()
        kwargs: dict[str, Any] = {
            "model": config.groq.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "required"

        return client.chat.completions.create(**kwargs)

    @classmethod
    def stream_complete(
        cls,
        messages: list[dict[str, str]],
        temperature: float = 0.4,
    ) -> Iterator[str]:
        """Yields text deltas as they arrive — plain completion only, no
        tool-calling (streaming + forced tool calls don't mix cleanly)."""

        client = cls.get_client()
        stream = client.chat.completions.create(
            model=config.groq.llm_model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
