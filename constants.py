KNOWLEDGE_CATEGORIES = [

    # ── Technical Capabilities ─────────────────────────────────────
    {
        "name": "Backend Development",
        "description": "Server-side development, REST APIs, microservices, databases, FastAPI, Django, Node.js, system architecture"
    },
    {
        "name": "Frontend Development",
        "description": "Web UI development, React, Next.js, Vue, mobile-responsive design, component libraries"
    },
    {
        "name": "Mobile Development",
        "description": "iOS, Android, React Native, Flutter — native and cross-platform mobile apps"
    },
    {
        "name": "Cloud & DevOps",
        "description": "AWS, GCP, Azure, infrastructure setup, CI/CD pipelines, Docker, Kubernetes, deployments"
    },
    {
        "name": "AI & ML Solutions",
        "description": "Machine learning, LLMs, RAG pipelines, NLP, computer vision, model training and deployment"
    },
    {
        "name": "Data Engineering",
        "description": "ETL pipelines, data warehouses, analytics, PostgreSQL, MongoDB, Kafka, reporting dashboards"
    },
    {
        "name": "Security & Compliance",
        "description": "Application security, OWASP, penetration testing, ISO 27001, GDPR, SOC2, auth systems"
    },
    {
        "name": "QA & Testing",
        "description": "Manual testing, automated testing, Selenium, Playwright, performance testing, test strategies"
    },
    {
        "name": "UI/UX Design",
        "description": "User research, wireframes, prototyping, Figma, design systems, accessibility"
    },

    # ── Delivery & Process ─────────────────────────────────────────
    {
        "name": "Project Management",
        "description": "Agile, Scrum, sprint planning, milestone tracking, risk management, stakeholder communication"
    },
    {
        "name": "Delivery Methodology",
        "description": "How the org delivers projects — discovery phase, iterative delivery, handover, documentation standards"
    },
    {
        "name": "Support & Maintenance",
        "description": "Post-launch support plans, SLA definitions, bug fix policies, monitoring, on-call processes"
    },

    # ── Organisation ───────────────────────────────────────────────
    {
        "name": "Company Overview",
        "description": "About the organisation, founding story, team size, offices, mission and values"
    },
    {
        "name": "Team & Expertise",
        "description": "Team structure, key personnel bios, certifications, skill matrix, hiring practices"
    },
    {
        "name": "Case Studies",
        "description": "Past client projects — problem, solution, tech stack, outcome, measurable results"
    },
    {
        "name": "Pricing & Commercials",
        "description": "Engagement models, hourly rates, fixed price vs T&M, payment terms, cost breakdowns"
    },
    {
        "name": "Partnerships & Certifications",
        "description": "AWS Partner, Google Partner, ISO certs, technology vendor relationships, accreditations"
    },
]


# Proposal DOCX/PDF export styles — the HTML template files themselves live
# in S3 under "proposal_templates/" (see test.py for the upload script).
# preview_url should be filled in with each template's uploaded S3 URL once
# the actual template files exist.
EXPORT_TEMPLATES = [
    {
        "id": 1,
        "name": "Modern",
        "description": "Clean bold headings",
        "preview_url": "https://proposal-ai-bucket-2026.s3.amazonaws.com/proposal_templates/modern_preview?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIAVEYVEB5PHQRUPE7A%2F20260722%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20260722T171526Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=f4c5cb71746d3aae4835cf3f07a271247fa60c50962602f8e88bd70db840b50b",
    },
    {
        "id": 2,
        "name": "Minimal",
        "description": "Typography-first",
        "preview_url": "https://proposal-ai-bucket-2026.s3.amazonaws.com/proposal_templates/Minimal?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIAVEYVEB5PHQRUPE7A%2F20260722%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20260722T172117Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=87f84bcf9dfa3e092de7d6ddcce0c04ad57f0fcdfde1d2b5ec1d5e3160de192a",
    },
    {
        "id": 3,
        "name": "Corporate",
        "description": "Formal structure",
        "preview_url": "https://proposal-ai-bucket-2026.s3.amazonaws.com/proposal_templates/corporate_preview?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIAVEYVEB5PHQRUPE7A%2F20260722%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20260722T172218Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=d4ab7dff8195e32e21ab2b34e9a105c1c79ead20572bf6bde9d5b3784b97e6cc",
    },
    {
        "id": 4,
        "name": "Executive",
        "description": "C-suite summary layout",
        "preview_url": "https://proposal-ai-bucket-2026.s3.amazonaws.com/proposal_templates/executive_preview?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIAVEYVEB5PHQRUPE7A%2F20260722%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20260722T171659Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=f8b256a7c48b34468738b42bf00ba0bf6d229e903aa8036fd4802dc3807c2260",
    },
]