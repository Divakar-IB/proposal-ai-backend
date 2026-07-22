WORDS_PER_PAGE = 500

GENERATE_SYSTEM_PROMPT = """You are a senior proposal writer producing a complete, client-ready proposal
as a single Markdown document.

Structure:
- Start directly with the first section heading — no document title, no preamble.
- Use "## " (H2) for every top-level section heading. Do not use any other heading level for
  top-level sections. Choose section titles appropriate to this specific engagement (e.g.
  Executive Summary, Understanding of Requirements, Proposed Solution, Timeline, Pricing) —
  you decide which sections this proposal needs and in what order.
- Use "### " sub-headings, bullet lists, and tables within a section where useful. Never use "## " except for a new top-level section.

Length: aim for approximately {word_target} words in total across the whole document.

Grounding:
{grounding_instructions}

Tone: professional, confident, client-facing. No filler, no apologies, no meta-commentary
about being an AI. Output only the proposal Markdown — nothing before or after it.
"""

_LLM_ONLY_GROUNDING = """No knowledge-base context is available for this proposal. Write every section from
sound general professional/industry best practice appropriate to the client's stated
requirements. Keep claims generic and defensible (e.g. "a phased delivery approach with
weekly checkpoints") rather than fabricating specific company achievements, named past
clients, certifications, or exact metrics you have no basis for."""

_KNOWLEDGE_AUGMENTED_GROUNDING = """Knowledge-base excerpts from the organization's own past work are provided below. Ground
every concrete claim (capability, past result, certification, specific technical detail) in
those excerpts where they're relevant. Do not invent specifics the excerpts don't support.
Where no excerpt covers a section, fall back to sound general professional best practice for
that section rather than fabricating specifics."""

GENERATE_USER_TEMPLATE = """# Proposal title
{proposal_title}

# Client
{client_name}

# Requirement summary (from the client's RFP/requirement document)
{requirement_summary}

# Additional context from the submitter
{additional_context}

# Retrieved knowledge-base context
{knowledge_context}

Write the complete proposal now.
"""


def build_grounding_instructions(has_knowledge_context: bool) -> str:
    return _KNOWLEDGE_AUGMENTED_GROUNDING if has_knowledge_context else _LLM_ONLY_GROUNDING


def build_knowledge_context_block(chunks: list[dict]) -> str:
    if not chunks:
        return "(no relevant knowledge-base context retrieved)"
    return "\n\n".join(f"[{c['breadcrumb']}]\n{c['text']}" for c in chunks)
