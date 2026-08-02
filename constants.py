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


# Proposal DOCX/PDF export styles — the dummy preview HTML files live in S3
# under "proposal_templates/" (uploaded once, shown as-is so the user can
# browse sample designs) while the *real* Jinja templates used to render an
# actual export live locally under html/ (see rendering/html_templates.py).
# preview_key is the S3 object key; the presigned preview_url is generated
# fresh per request (see router/proposals.py) instead of being baked in here
# — a hardcoded presigned URL expires (that's what broke previously).
# Drives GET /proposals/templates (name/description + S3 preview thumbnail).
# The ids MUST match rendering.html_templates.HTML_TEMPLATES, which is what
# actually gets rendered on export — nothing enforces it, and they previously
# disagreed (id 1 was named "Modern" here but rendered template_1.html).
EXPORT_TEMPLATES = [
    {
        "id": 1,
        "name": "Professional",
        "description": "Formal business proposal — default",
        "preview_key": "proposal_templates/professional_preview",
    },
    {
        "id": 2,
        "name": "Minimal",
        "description": "Typography-first",
        "preview_key": "proposal_templates/Minimal",
    },
    {
        "id": 3,
        "name": "Corporate",
        "description": "Formal structure",
        "preview_key": "proposal_templates/corporate_preview",
    },
    {
        "id": 4,
        "name": "Executive",
        "description": "C-suite summary layout",
        "preview_key": "proposal_templates/executive_preview",
    },
    # {
    #     "id": 5,
    #     "name": "Modern",
    #     "description": "Clean bold headings",
    #     "preview_key": "proposal_templates/modern_preview",
    # },
]