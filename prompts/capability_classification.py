"""Prompt template for Capability Classification — determines which
capability/category tags apply to an RFP from its already-extracted
structured requirements JSON (never the raw document text). The vocabulary
is injected from constants.KNOWLEDGE_CATEGORIES at call time, so the system
prompt is built by a function rather than a bare string constant."""

from constants import KNOWLEDGE_CATEGORIES
from requirements_parsing.capability_schema import CapabilityClassification

TOOL_NAME = "report_capability_tags"

_SYSTEM_PROMPT_TEMPLATE = """You are classifying an RFP/requirement document against a fixed \
list of capability categories, using its already-extracted structured requirements (not the \
raw document) as input.

Choose ONLY from this list of categories — do not invent new ones:
{category_list}

For each category that genuinely applies to this project, call the report_capability_tags tool \
with its exact name and a confidence score (0-1) reflecting how strongly the requirements point \
to that capability. Omit categories that don't apply — do not include low-relevance categories \
just to fill out the list."""


def build_system_prompt() -> str:
    category_list = "\n".join(f"- {c['name']}: {c['description']}" for c in KNOWLEDGE_CATEGORIES)
    return _SYSTEM_PROMPT_TEMPLATE.format(category_list=category_list)


CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Report the capability/category tags that apply to this RFP.",
        "parameters": CapabilityClassification.model_json_schema(),
    },
}
