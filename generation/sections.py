SECTION_DEFINITIONS: list[dict[str, str]] = [
    {
        "key": "executive_summary",
        "title": "Executive Summary",
        "query_fields": "project_title, scope",
    },
    {
        "key": "understanding_of_requirements",
        "title": "Understanding of Requirements",
        "query_fields": "scope, technical_requirements, constraints",
    },
    {
        "key": "proposed_solution",
        "title": "Proposed Solution",
        "query_fields": "deliverables, technical_requirements",
    },
    {
        "key": "technical_approach",
        "title": "Technical Approach",
        "query_fields": "technical_requirements, constraints",
    },
    {
        "key": "team_and_expertise",
        "title": "Team & Expertise",
        "query_fields": "project_title, scope",
    },
    {
        "key": "timeline",
        "title": "Timeline & Milestones",
        "query_fields": "timeline, deliverables",
    },
    {
        "key": "pricing",
        "title": "Pricing & Commercials",
        "query_fields": "budget_range, deliverables",
    },
    {
        "key": "case_studies",
        "title": "Relevant Case Studies",
        "query_fields": "project_title, scope, technical_requirements",
    },
]
