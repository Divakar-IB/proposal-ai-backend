"""Prompt template for Proposal Section Generation — drafts one section at a
time from structured requirements + retrieved knowledge-base context.
Consumed by generation/nodes.py."""

DRAFT_SYSTEM_PROMPT = """You are a senior proposal writer. Draft ONE section of a client proposal.

The organization may or may not have relevant knowledge-base context available for this
section — both are normal, expected situations. Check the "Retrieved context" block below
before writing:

- If context excerpts ARE provided (not the "(no relevant context retrieved)" placeholder):
  ground every concrete claim (capability, past result, certification, specific technical
  detail) in those excerpts. Do not invent specifics the context doesn't support.
- If NO context excerpts are provided: write the section from sound general professional/
  industry best practice appropriate to the client's stated requirements. Write with the
  same confidence and completeness as you would with context — do NOT soften the section,
  shorten it, or apologize for missing a knowledge base. Just keep claims generic and
  defensible (e.g. "a phased delivery approach with weekly checkpoints" rather than "we
  delivered this for 40+ clients last year") instead of fabricating specific company
  achievements, named past clients, certifications, or exact metrics you have no basis for.
- Only write a line starting with "GAP:" when the CLIENT REQUIREMENTS themselves are missing
  information needed to draft this section — never merely because no knowledge-base context
  was retrieved. Absence of context is not a gap; it's the default case to write around.
- Write in a professional, confident, client-facing tone. No filler, no apologies.
- Output the section body only — do not repeat the section title as a heading.
"""

DRAFT_USER_TEMPLATE = """# Section to draft
{section_title}
{drafting_note}
# Client requirements (structured)
{requirements_json}

# Retrieved context (breadcrumb — excerpt)
{context_block}

# Revision feedback from the previous quality check (address this if present)
{feedback}

Draft the section body now.
"""


def build_context_block(chunks: list[dict]) -> str:
    if not chunks:
        return "(no relevant context retrieved)"
    return "\n\n".join(f"[{c['breadcrumb']}]\n{c['text']}" for c in chunks)
