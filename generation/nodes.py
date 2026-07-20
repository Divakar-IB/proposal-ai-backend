import json

from database.crud import (
    create_proposal_sections,
    get_proposal_by_id,
    get_requirement_document_by_id,
    has_any_knowledge_chunks,
    update_proposal,
    update_requirement_document,
)
from database.database import db_session
from database.db_enum import DocumentStatus, ProposalSectionStatus, ProposalStatus
from database.models import ProposalSection
from embedding.embedder import embed_query
from generation.prompts import (
    DRAFT_SYSTEM_PROMPT,
    DRAFT_USER_TEMPLATE,
    QUALITY_CHECK_SYSTEM_PROMPT,
    QUALITY_CHECK_USER_TEMPLATE,
    build_context_block,
)
from generation.schema import QualityCheckResult
from generation.sections import SECTION_DEFINITIONS
from generation.state import ProposalGenerationState
from llm.chat_client import GroqChatClient
from tasks.requirement_processing import process_requirement_document_pipeline
from utilities.logger import get_logger
from utilities.s3_service import S3Service
from vectorstore.knowledge_store import query_chunks

logger = get_logger(__name__)
s3_service = S3Service()

TOP_K_CHUNKS_PER_SECTION = 5

_QUALITY_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "report_quality_check",
        "description": "Report the quality check verdict for a drafted proposal section.",
        "parameters": QualityCheckResult.model_json_schema(),
    },
}


# ------------------------------------------------------------------
# Node 1: parse_requirements
# ------------------------------------------------------------------

async def parse_requirements(state: ProposalGenerationState) -> ProposalGenerationState:
    document_id = state["requirement_document_id"]

    async with db_session() as db:
        document = await get_requirement_document_by_id(db, document_id)
        if document is None:
            return {**state, "error": f"requirement document {document_id} not found"}

        if not document.parsed_data:
            logger.info("requirement document not yet parsed, running Path B inline | document_id=%s", document_id)
            document = await process_requirement_document_pipeline(db, document)
            if document.status != DocumentStatus.PARSED:
                return {**state, "error": f"requirement document {document_id} failed to parse"}
        requirements = document.parsed_data

    sections = [
        {
            "key": definition["key"],
            "title": definition["title"],
            "query_fields": definition["query_fields"],
            "retrieved_chunks": [],
            "content": None,
            "citations": [],
            "status": "pending",
            "retry_count": 0,
            "feedback": None,
        }
        for definition in SECTION_DEFINITIONS
    ]

    return {**state, "requirements": requirements, "sections": sections}


# ------------------------------------------------------------------
# Node 2: retrieve_context
# ------------------------------------------------------------------

async def retrieve_context(state: ProposalGenerationState) -> ProposalGenerationState:
    requirements = state["requirements"]
    category_ids = state.get("category_ids")

    # No knowledge documents indexed yet — skip embedding/Pinecone entirely and
    # let draft_section fall back to general-best-practice drafting (its
    # prompt already handles an empty retrieved_chunks list as the expected
    # no-knowledge-base case, not an error).
    async with db_session() as db:
        has_knowledge = await has_any_knowledge_chunks(db)

    updated_sections = []
    for section in state["sections"]:
        if not has_knowledge:
            updated_sections.append({**section, "retrieved_chunks": []})
            continue

        query_text = _build_query_text(section, requirements)
        query_embedding = embed_query(query_text)
        chunks = query_chunks(query_embedding, top_k=TOP_K_CHUNKS_PER_SECTION, category_ids=category_ids)
        updated_sections.append({**section, "retrieved_chunks": chunks})

    return {**state, "sections": updated_sections}


def _build_query_text(section: dict, requirements: dict) -> str:
    field_names = [f.strip() for f in section["query_fields"].split(",")]
    values = []
    for name in field_names:
        value = requirements.get(name)
        if isinstance(value, list):
            values.append(", ".join(str(v) for v in value))
        elif value:
            values.append(str(value))
    return f"{section['title']}: " + " | ".join(values)


# ------------------------------------------------------------------
# Node 3: draft_section
# ------------------------------------------------------------------

async def draft_section(state: ProposalGenerationState) -> ProposalGenerationState:
    requirements_json = json.dumps(state["requirements"], indent=2)
    updated_sections = []

    for section in state["sections"]:
        if section["status"] not in ("pending", "needs_revision"):
            updated_sections.append(section)
            continue

        context_block = build_context_block(section["retrieved_chunks"])
        user_prompt = DRAFT_USER_TEMPLATE.format(
            section_title=section["title"],
            requirements_json=requirements_json,
            context_block=context_block,
            feedback=section["feedback"] or "(none — first draft)",
        )

        response = GroqChatClient.complete(
            messages=[
                {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
        content = response.choices[0].message.content

        citations = [
            {
                "chunk_document_id": chunk.get("document_id"),
                "breadcrumb": chunk.get("breadcrumb"),
                "page_number": chunk.get("page_number"),
            }
            for chunk in section["retrieved_chunks"]
        ]

        updated_sections.append({
            **section,
            "content": content,
            "citations": citations,
            "status": "drafted",
            "retry_count": section["retry_count"] + 1,
        })

    return {**state, "sections": updated_sections}


# ------------------------------------------------------------------
# Node 4: quality_check
# ------------------------------------------------------------------

async def quality_check(state: ProposalGenerationState) -> ProposalGenerationState:
    requirements_json = json.dumps(state["requirements"], indent=2)
    max_retries = state["max_retries"]
    updated_sections = []

    for section in state["sections"]:
        if section["status"] != "drafted":
            updated_sections.append(section)
            continue

        context_block = build_context_block(section["retrieved_chunks"])
        user_prompt = QUALITY_CHECK_USER_TEMPLATE.format(
            section_title=section["title"],
            requirements_json=requirements_json,
            context_block=context_block,
            content=section["content"],
        )

        response = GroqChatClient.complete(
            messages=[
                {"role": "system", "content": QUALITY_CHECK_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[_QUALITY_CHECK_TOOL],
            tool_choice={"type": "function", "function": {"name": "report_quality_check"}},
        )
        tool_calls = response.choices[0].message.tool_calls
        result = QualityCheckResult.model_validate(json.loads(tool_calls[0].function.arguments))

        if result.approved or section["retry_count"] >= max_retries:
            status = "approved"
            feedback = None if result.approved else f"Force-approved after {max_retries} revisions: {result.feedback}"
        else:
            status = "needs_revision"
            feedback = result.feedback

        updated_sections.append({**section, "status": status, "feedback": feedback})

    return {**state, "sections": updated_sections}


def needs_another_draft_pass(state: ProposalGenerationState) -> str:
    if any(section["status"] == "needs_revision" for section in state["sections"]):
        return "draft_section"
    return "compile_proposal"


# ------------------------------------------------------------------
# Node 5: compile_proposal
# ------------------------------------------------------------------

async def compile_proposal(state: ProposalGenerationState) -> ProposalGenerationState:
    proposal_id = state["proposal_id"]
    markdown = _assemble_markdown(state)

    async with db_session() as db:
        proposal = await get_proposal_by_id(db, proposal_id)
        if proposal is None:
            return {**state, "error": f"proposal {proposal_id} not found"}

        s3_key = f"output/proposals/{state['user_id']}/{proposal_id}/proposal.md"
        s3_service.upload_bytes(markdown.encode("utf-8"), s3_key, content_type="text/markdown")

        section_rows = [
            ProposalSection(
                proposal_id=proposal_id,
                section_key=section["key"],
                order_index=index,
                content=section["content"],
                citations=section["citations"],
                status=ProposalSectionStatus(section["status"]),
                retry_count=section["retry_count"],
            )
            for index, section in enumerate(state["sections"])
        ]
        await create_proposal_sections(db, section_rows)

        all_approved = all(section["status"] == "approved" for section in state["sections"])
        await update_proposal(
            db, proposal,
            markdown_path=s3_key,
            status=ProposalStatus.REVIEW if all_approved else ProposalStatus.INPROGRESS,
        )

    return state


def _assemble_markdown(state: ProposalGenerationState) -> str:
    parts = []
    for section in state["sections"]:
        parts.append(f"## {section['title']}\n\n{section['content'] or ''}")
    return "\n\n".join(parts)
