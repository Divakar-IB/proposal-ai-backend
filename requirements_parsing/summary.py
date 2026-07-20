from typing import Optional

from llm.chat_client import GroqChatClient

_SYSTEM_PROMPT = (
    "You are a proposal analyst. Read the requirement/RFP document below and write a short, "
    "plain-language summary (2-4 sentences) for a proposal writer's sidebar view — what the "
    "client wants, the core scope, and any hard constraints. "
    "Respond in Markdown."
)


def summarize_requirements(markdown: str, additional_context: Optional[str] = None) -> str:
    user_content = markdown
    if additional_context:
        user_content = f"{markdown}\n\nAdditional context from the submitter:\n{additional_context}"

    response = GroqChatClient.complete(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()