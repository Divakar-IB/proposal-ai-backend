import json

from llm.chat_client import GroqChatClient

_SYSTEM_PROMPT = (
    "You are a proposal analyst. Read the structured requirements JSON below (already "
    "extracted from a requirement/RFP document) and write a short, plain-language summary "
    "(2-4 sentences) for a proposal writer's sidebar view — what the client wants, the core "
    "scope, and any hard constraints. "
    "Respond in Markdown."
)


def summarize_requirements(requirements: dict, additional_context: str | None = None) -> str:
    """Generates the sidebar summary from the already-extracted structured requirements
    (not the raw document) — avoids re-sending the full RFP text through the LLM a second
    time on top of the structured-extraction call."""

    user_content = json.dumps(requirements, indent=2)
    if additional_context:
        user_content = f"{user_content}\n\nAdditional context from the submitter:\n{additional_context}"

    response = GroqChatClient.complete(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()
