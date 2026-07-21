"""Standard proposal section template. Each entry drives one ProposalSection row
and one retrieval query in the LangGraph flow. `query_fields` names must match
fields on requirements_parsing.schema.RequirementsSchema. `drafting_note` is
optional — when present, it's surfaced to the drafting prompt as a special
instruction for that section only (see prompts/proposal_generation.py)."""

SECTION_DEFINITIONS: list[dict[str, str]] = [
    {
        "key": "executive_summary",
        "title": "Executive Summary",
        "query_fields": "project_title, project_type, scope",
    },
    {
        "key": "understanding_of_requirements",
        "title": "Understanding the Requirements",
        "query_fields": "scope, technical_requirements, constraints, evaluation_criteria",
    },
    {
        "key": "technical_approach",
        "title": "Technical Approach",
        "query_fields": "technical_requirements, project_type",
    },
    {
        "key": "architecture",
        "title": "Architecture",
        "query_fields": "technical_requirements, constraints",
    },
    {
        "key": "implementation_plan",
        "title": "Implementation Plan",
        "query_fields": "deliverables, technical_requirements",
    },
    {
        "key": "timeline",
        "title": "Timeline",
        "query_fields": "timeline, deliverables",
    },
    {
        "key": "team_structure",
        "title": "Team Structure",
        "query_fields": "project_title, scope, project_type",
    },
    {
        "key": "security",
        "title": "Security",
        "query_fields": "constraints",
    },
    {
        "key": "compliance",
        "title": "Compliance",
        "query_fields": "constraints, evaluation_criteria",
    },
    {
        "key": "deliverables",
        "title": "Deliverables",
        "query_fields": "deliverables",
    },
    {
        "key": "assumptions",
        "title": "Assumptions",
        "query_fields": "scope, constraints",
    },
    {
        "key": "risks",
        "title": "Risks",
        "query_fields": "constraints, technical_requirements",
    },
    {
        "key": "pricing_placeholder",
        "title": "Pricing Placeholder",
        "query_fields": "budget_range, deliverables",
        "drafting_note": (
            "This is a placeholder section — do NOT invent specific prices, rates, or "
            "totals. Output a clearly-labeled placeholder noting that commercial/pricing "
            "details will be finalized separately by the pricing team; you may reference "
            "the stated budget_range/deliverables only to note scope-appropriate pricing "
            "considerations in general terms."
        ),
    },
    {
        "key": "conclusion",
        "title": "Conclusion",
        "query_fields": "project_title, scope",
    },
]
