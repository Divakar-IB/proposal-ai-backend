from typing import Optional


def build_outline_instruction(outline: Optional[list[str]]) -> str:
    """Renders a section's required subsection outline into an instruction
    the drafter must follow verbatim — entries starting with "- " are
    bullet points nested under the previous heading (e.g. the five use
    cases under "Use Case Solutions") rather than headings of their own."""

    if not outline:
        return ""

    lines = [f"  {item}" if item.startswith("- ") else f"### {item}" for item in outline]
    return (
        "This section must be broken into the following subsections, using \"### \" headings "
        "in exactly this order (items already prefixed with \"- \" are bullet points nested under "
        "the heading directly above them, not headings themselves):\n" + "\n".join(lines)
    )


# `weight` is each section's relative share of the document's word budget (see
# generation/length_budget.py). It is a ratio, not a word count — the absolute
# figures fall out of the caller's requested page_count. Weight a section by
# how much it genuinely has to say: a section with a seven-item outline needs
# several times the room of a one-paragraph declaration, and splitting the
# budget equally is what previously made long sections overshoot the page
# limit. Omitting `weight` defaults it to 1.0.
SECTION_DEFINITIONS: list[dict] = [
    {
        "key": "executive_summary",
        "title": "Executive Summary",
        "query_fields": "project_title, scope",
        "weight": 1.0,
    },
    {
        "key": "company_profile",
        "title": "Company Profile",
        "query_fields": "project_title, scope",
        "weight": 1.0,
        "outline": [
            "About InnoBoon Technologies",
            "Relevant AI Capabilities",
        ],
    },
    {
        "key": "understanding_of_requirements",
        "title": "Understanding of Requirements",
        "query_fields": "scope, technical_requirements, constraints",
        "weight": 1.2,
    },
    {
        "key": "proposed_solution",
        "title": "Proposed Solution",
        "query_fields": "deliverables, technical_requirements",
        "weight": 3.0,
        "outline": [
            "Architecture Overview",
            "Use Case Solutions",
            "- Use Case 1 – Insights & Visualization on Large Structured Trade Data",
            "- Use Case 2 – Semantic Search on Free Trade Agreement (FTA) Documents",
            "- Use Case 3 – HS Code Search Functionality",
            "- Use Case 4 – Summary Dossier & Search from Non-Public Documents",
            "- Use Case 5 – HS / Tariff Concordance Tool",
        ],
    },
    {
        "key": "technology_stack",
        "title": "Technology Stack",
        "query_fields": "technical_requirements",
        "weight": 1.0,
    },
    {
        "key": "proposed_team_structure",
        "title": "Proposed Team Structure",
        "query_fields": "deliverables, project_title",
        "weight": 0.8,
    },
    {
        "key": "project_implementation_plan",
        "title": "Project Implementation Plan",
        "query_fields": "timeline, deliverables",
        "weight": 2.0,
        "outline": [
            "Phase 1 – Foundation",
            "Phase 2 – Use Case 1 & Use Case 3",
            "Phase 3 – Use Case 2 & Use Case 4",
            "Phase 4 – Use Case 5",
            "Phase 5 – Integration & User Acceptance Testing (UAT)",
            "Phase 6 – Go-Live",
            "Operations & Maintenance (O&M) Phase",
        ],
    },
    {
        "key": "non_functional_requirements_compliance",
        "title": "Non-Functional Requirements Compliance",
        "query_fields": "constraints, technical_requirements",
        "weight": 1.0,
    },
    {
        "key": "security_and_data_privacy_framework",
        "title": "Security & Data Privacy Framework",
        "query_fields": "constraints, technical_requirements",
        "weight": 1.8,
        "outline": [
            "Zero Egress Guarantee",
            "Data Access Architecture",
            "Role-Based Access Control (RBAC)",
            "Encryption Standards",
            "Audit & Accountability",
            "Third-Party Security Audit",
            "GPU & Infrastructure Security",
        ],
    },
    {
        "key": "commercial_proposal",
        "title": "Commercial Proposal",
        "query_fields": "budget_range, deliverables",
        "weight": 1.2,
        "outline": [
            "Pricing Components",
            "Important Notes on Pricing",
        ],
    },
    {
        "key": "competitive_differentiators",
        "title": "InnoBoon's Competitive Differentiators",
        "query_fields": "project_title, scope, technical_requirements",
        "weight": 0.8,
    },
    {
        "key": "declaration_and_authorised_undertaking",
        "title": "Declaration & Authorised Undertaking",
        "query_fields": "project_title",
        "weight": 0.5,
    },
]
