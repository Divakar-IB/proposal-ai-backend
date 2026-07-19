from typing import Any, Optional

from openai import OpenAI

from config import config


class NovitaChatClient:
    """Shared GPT-OSS (via Novita) chat-completions wrapper — used by both
    requirements_parsing (structured extraction) and generation (drafting/quality_check)."""

    _client: OpenAI | None = None

    @classmethod
    def get_client(cls) -> OpenAI:
        if cls._client is None:
            cls._client = OpenAI(
                api_key=config.novita.api_key,
                base_url=config.novita.chat_base_url,
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
            "model": config.novita.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "required"

        return client.chat.completions.create(**kwargs)
