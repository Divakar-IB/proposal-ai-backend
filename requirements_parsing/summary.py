from llm.chat_client import GroqChatClient

_SYSTEM_PROMPT = (
    "You are a proposal analyst. Read the requirement/RFP document below and write a short, "
    "plain-language summary (2-4 sentences) for a proposal writer's sidebar view — what the "
    "client wants, the core scope, and any hard constraints. No headings, no bullet points."
)


def summarize_requirements(markdown: str) -> str:
    response = GroqChatClient.complete(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": markdown},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()
