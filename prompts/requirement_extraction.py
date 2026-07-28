"""Prompt template for Requirement Extraction — structured extraction of an
RFP/requirement document into RequirementsSchema. Consumed by
requirements_parsing/parser.py."""

from requirements_parsing.schema import RequirementsSchema

SYSTEM_PROMPT = (
    "You are a requirements analyst. Read the requirement/RFP document below and extract "
    "a structured summary by calling the extract_requirements tool. Only use information "
    "present in the document — never invent values.\n"
    "For fields with nothing found: string fields (project_title, scope, project_type, "
    "budget_range, timeline) may be left null, but array fields (deliverables, "
    "technical_requirements, evaluation_criteria, constraints) MUST be an empty array [] — "
    "never null for an array field."
)

TOOL_NAME = "extract_requirements"

EXTRACT_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Extract structured requirements from an RFP/requirement document.",
        "parameters": RequirementsSchema.model_json_schema(),
    },
}
