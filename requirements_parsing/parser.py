import json
from typing import Optional

from openai import APIStatusError
from pydantic import ValidationError

from llm.chat_client import GroqChatClient
from prompts.requirement_extraction import EXTRACT_TOOL, SYSTEM_PROMPT, TOOL_NAME
from requirements_parsing.schema import RequirementsSchema
from utilities.logger import get_logger

logger = get_logger(__name__)

MAX_REPAIR_ATTEMPTS = 3


def parse_requirements(markdown: str, additional_context: Optional[str] = None) -> RequirementsSchema:
    """GPT-OSS (via Groq) structured extraction, validated against RequirementsSchema.
    Retries with the validation error fed back as a repair instruction on failure."""

    user_content = markdown
    if additional_context:
        user_content = f"{markdown}\n\nAdditional context from the submitter:\n{additional_context}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    last_error: Exception | None = None
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        try:
            response = GroqChatClient.complete(
                messages=messages,
                tools=[EXTRACT_TOOL],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            )
        except APIStatusError as error:
            # The provider itself validates tool-call arguments against the schema
            # before returning them — e.g. sending null for an array field — and
            # raises here rather than giving us malformed JSON to catch below.
            last_error = error
            logger.warning("requirements parse attempt %s: API rejected tool call: %s", attempt, error)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous tool call was rejected: {error}. Remember: array fields "
                        "must be an empty array [] when nothing is found, never null. "
                        "Call extract_requirements again with corrected arguments."
                    ),
                }
            )
            continue

        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            last_error = ValueError("model returned no tool call")
            logger.warning("requirements parse attempt %s: no tool call returned", attempt)
            continue

        raw_arguments = tool_calls[0].function.arguments
        try:
            parsed = json.loads(raw_arguments)
            return RequirementsSchema.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as error:
            last_error = error
            logger.warning("requirements parse attempt %s failed validation: %s", attempt, error)
            messages.append({"role": "assistant", "content": raw_arguments})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"That output failed schema validation with error: {error}. "
                        "Call extract_requirements again with corrected arguments matching the schema exactly."
                    ),
                }
            )

    raise ValueError(f"Failed to parse requirements after {MAX_REPAIR_ATTEMPTS} attempts: {last_error}")
