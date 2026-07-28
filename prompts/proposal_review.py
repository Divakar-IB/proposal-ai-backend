"""Prompt template for Proposal Review — quality-checks a drafted section and
reports an approve/revise verdict plus a confidence score. Consumed by
generation/nodes.py."""

from generation.schema import QualityCheckResult

QUALITY_CHECK_SYSTEM_PROMPT = """You are reviewing a drafted proposal section for a client-ready proposal.

First check whether "Retrieved context available to the drafter" below has real excerpts or
is the "(no relevant context retrieved)" placeholder — that determines how to judge claim #3.

Check for:
1. Completeness — does it address the client requirements relevant to this section?
2. Tone — professional and confident, no filler or hedging. Do NOT penalize a section for
   lacking company-specific proof points if no context was available to the drafter — that
   is expected, not a defect.
3. Unsupported claims:
   - If context excerpts WERE available: flag any specific claim (numbers, named past
     results, certifications) that isn't traceable to those excerpts.
   - If NO context excerpts were available: do not require citations. Instead, only flag
     claims that look fabricated as if specific to this company (e.g. a named client, an
     exact statistic, a specific certification) with nothing in the context to back it —
     generic best-practice statements are fine and expected in this case.
4. Any "GAP:" lines the drafter left — these should only reflect missing requirement
   information. If a "GAP:" line exists merely because no context was retrieved, treat that
   as a drafting mistake to flag in feedback, not a legitimate gap.

Respond by calling the report_quality_check tool, including a confidence_score between 0 and 1
reflecting how client-ready this section is as drafted (1 = fully client-ready, 0 = not usable).
"""

QUALITY_CHECK_USER_TEMPLATE = """# Section: {section_title}

# Client requirements (structured)
{requirements_json}

# Retrieved context available to the drafter
{context_block}

# Drafted content
{content}
"""

TOOL_NAME = "report_quality_check"

QUALITY_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Report the quality check verdict for a drafted proposal section.",
        "parameters": QualityCheckResult.model_json_schema(),
    },
}
