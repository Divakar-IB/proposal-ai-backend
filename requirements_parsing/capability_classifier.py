import json

from llm.chat_client import GroqChatClient
from prompts.capability_classification import CLASSIFY_TOOL, TOOL_NAME, build_system_prompt
from requirements_parsing.capability_schema import CapabilityClassification
from utilities.logger import get_logger

logger = get_logger(__name__)


def classify_capabilities(requirements: dict) -> CapabilityClassification:
    """Single-shot LLM classification against the fixed KNOWLEDGE_CATEGORIES vocabulary,
    using the already-extracted structured requirements JSON — no raw document text is
    re-sent. Callers should treat failures as recoverable (this is enrichment metadata,
    not a blocking step)."""

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": json.dumps(requirements, indent=2)},
    ]

    response = GroqChatClient.complete(
        messages=messages,
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
    )

    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("model returned no tool call for capability classification")

    parsed = json.loads(tool_calls[0].function.arguments)
    return CapabilityClassification.model_validate(parsed)
