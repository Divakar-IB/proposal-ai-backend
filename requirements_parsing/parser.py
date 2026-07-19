import json

from pydantic import ValidationError

from llm.chat_client import NovitaChatClient
from requirements_parsing.schema import RequirementsSchema
from utilities.logger import get_logger

logger = get_logger(__name__)

MAX_REPAIR_ATTEMPTS = 3

_TOOL_NAME = "extract_requirements"

_SYSTEM_PROMPT = (
    "You are a requirements analyst. Read the requirement/RFP document below and extract "
    "a structured summary by calling the extract_requirements tool. Only use information "
    "present in the document — leave a field empty/null rather than inventing values."
)

_EXTRACT_TOOL = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": "Extract structured requirements from an RFP/requirement document.",
        "parameters": RequirementsSchema.model_json_schema(),
    },
}


def parse_requirements(markdown: str) -> RequirementsSchema:
    """GPT-OSS (via Novita) structured extraction, validated against RequirementsSchema.
    Retries with the validation error fed back as a repair instruction on failure."""

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": markdown},
    ]

    last_error: Exception | None = None
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        response = NovitaChatClient.complete(
            messages=messages,
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
        )

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
            messages.append({
                "role": "user",
                "content": (
                    f"That output failed schema validation with error: {error}. "
                    "Call extract_requirements again with corrected arguments matching the schema exactly."
                ),
            })

    raise ValueError(f"Failed to parse requirements after {MAX_REPAIR_ATTEMPTS} attempts: {last_error}")
