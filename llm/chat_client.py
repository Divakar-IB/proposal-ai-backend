from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Optional

from openai import OpenAI

from config import config


@dataclass
class StreamOutcome:
    """Everything about a streamed completion that isn't the text itself.

    `stream_complete` yields only content deltas, so without this the caller
    cannot tell a finished section from a truncated one, or from a response
    that spent its whole allowance on reasoning and emitted nothing. Both of
    those used to reach the database as a silently empty section.

    Passed in by the caller and filled in as the stream is consumed, so the
    fields are valid once iteration has finished (and partially valid if the
    stream raises part-way, which is what makes a dropped tail visible).
    """

    finish_reason: Optional[str] = None
    content_chunks: int = 0
    content_chars: int = 0
    # `gpt-oss` emits reasoning on a separate `reasoning` delta that is billed
    # against max_completion_tokens but never streamed to the client. Tracked
    # so "the model produced nothing" can be distinguished from "the model
    # thought until it ran out of room" in the logs.
    reasoning_chunks: int = 0
    reasoning_chars: int = 0
    # Chunks carrying no `choices` at all — Groq's usage-only trailer. Counted
    # rather than indexed into, since choices[0] on one is an IndexError.
    empty_choice_chunks: int = 0
    rate_limit_headers: dict[str, str] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        """True when the model stopped because it hit the token cap. Groq also
        reports a bare `None` finish_reason if the stream is cut off before any
        terminal chunk, which is a dropped tail rather than a clean finish."""

        return self.finish_reason not in ("stop", "tool_calls")

    @property
    def produced_no_content(self) -> bool:
        return self.content_chars == 0


_RATE_LIMIT_HEADER_PREFIXES = ("x-ratelimit-", "retry-after")


def _rate_limit_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items() if key.lower().startswith(_RATE_LIMIT_HEADER_PREFIXES)}


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
        max_completion_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        outcome: Optional[StreamOutcome] = None,
        max_retries: Optional[int] = None,
    ) -> Iterator[str]:
        """Yields text deltas as they arrive — plain completion only, no
        tool-calling (streaming + forced tool calls don't mix cleanly).

        `max_completion_tokens` and `reasoning_effort` are only sent when set,
        so a caller that passes neither gets exactly the request this made
        before they existed.

        Pass `outcome` to find out how the stream ended. Callers that persist
        the result must check it: an empty or truncated response is
        indistinguishable from a short one by looking at the yielded text
        alone.

        `max_retries` overrides the SDK's own retry count for this request.
        Generation sets it to 0 because it does its own Retry-After-aware
        retrying per section (generation/rate_limit.py), and two independent
        retry layers would multiply the wait.
        """

        client = cls.get_client()
        if max_retries is not None:
            client = client.with_options(max_retries=max_retries)

        kwargs: dict[str, Any] = {
            "model": config.groq.llm_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = max_completion_tokens
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        stream = client.chat.completions.create(**kwargs)

        if outcome is not None:
            # httpx.Response on the live SDK stream. Guarded because the test
            # suite substitutes a plain generator for this method's transport.
            response = getattr(stream, "response", None)
            if response is not None:
                outcome.rate_limit_headers = _rate_limit_headers(response.headers)

        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                if outcome is not None:
                    outcome.empty_choice_chunks += 1
                continue

            choice = choices[0]
            delta = choice.delta

            if outcome is not None:
                if choice.finish_reason:
                    outcome.finish_reason = choice.finish_reason
                # `reasoning` is an undeclared field on ChoiceDelta, so it
                # arrives via model_extra rather than as an attribute.
                reasoning = (getattr(delta, "model_extra", None) or {}).get("reasoning")
                if reasoning:
                    outcome.reasoning_chunks += 1
                    outcome.reasoning_chars += len(reasoning)

            delta_content = delta.content
            if delta_content:
                if outcome is not None:
                    outcome.content_chunks += 1
                    outcome.content_chars += len(delta_content)
                yield delta_content
