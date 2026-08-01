import json
from typing import AsyncIterator

from database.crud import (
    create_proposal_sections,
    delete_proposal_sections_for_proposal,
    get_proposal_by_id,
    get_requirement_documents_by_proposal_id,
    has_any_knowledge_chunks,
    update_proposal,
)
from database.database import db_session
from database.db_enum import GenerationMode, ProposalSectionStatus, ProposalStatus
from database.models import ProposalSection
from generation.markdown_sections import assemble_markdown
from generation.nodes import draft_one_section_stream, retrieve_chunks_for_section, section_citations
from generation.prompts import WORDS_PER_PAGE
from generation.requirement_context import build_combined_requirements_json
from generation.sections import SECTION_DEFINITIONS, build_outline_instruction
from utilities.logger import get_logger
from utilities.s3_service import S3Service

logger = get_logger(__name__)
s3_service = S3Service()

MIN_SECTION_WORD_TARGET = 100


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_common_note(
    proposal_title: str, client_name: str, additional_context: str | None, word_target: int
) -> str:
    lines = [
        f"Proposal: {proposal_title} — Client: {client_name}",
        f"Additional context: {additional_context}" if additional_context else None,
        f"Target length: approximately {word_target} words.",
    ]
    return "\n".join(line for line in lines if line)


def _build_drafting_note(
    proposal_title: str,
    client_name: str,
    additional_context: str | None,
    word_target: int,
    outline: list[str] | None,
) -> str:
    common_note = _build_common_note(proposal_title, client_name, additional_context, word_target)
    outline_instruction = build_outline_instruction(outline)
    return "\n\n".join(part for part in [common_note, outline_instruction] if part)


async def generate_proposal_stream(
    proposal_id: int,
    page_count: int,
    generation_mode: GenerationMode,
) -> AsyncIterator[str]:
    """Drafts the proposal one section at a time and streams each section's
    lifecycle as Server-Sent Events:

        event: section_start  data: {"name": "..."}
        event: section_chunk  data: {"content": "..."}   (repeated)
        event: section_done   data: {"name": "..."}
        ... (repeated per section) ...
        event: done            data: {}

    Each section is persisted to the ProposalSection table as soon as its
    draft completes, so a client disconnecting mid-stream still leaves
    earlier sections saved. On failure, an "error" event is emitted and the
    proposal is marked FAILED instead of raising into a stream that already
    sent a 200 response."""

    async with db_session() as db:
        proposal = await get_proposal_by_id(db, proposal_id)
        if proposal is None:
            raise ValueError(f"proposal {proposal_id} not found")

        requirement_documents = await get_requirement_documents_by_proposal_id(db, proposal.id)
        requirements_json = build_combined_requirements_json(requirement_documents)
        requirements = json.loads(requirements_json) if requirements_json else {}

        has_knowledge = generation_mode == GenerationMode.KNOWLEDGE_AUGMENTED and await has_any_knowledge_chunks(db)

        proposal_title = proposal.title
        client_name = proposal.client_name
        additional_context = proposal.additional_context
        user_id = proposal.user_id
        category_ids = proposal.category_ids

        await delete_proposal_sections_for_proposal(db, proposal.id)
        await update_proposal(
            db, proposal,
            status=ProposalStatus.GENERATING,
            generation_mode=generation_mode,
            page_count=page_count,
        )

    word_target = max((page_count * WORDS_PER_PAGE) // len(SECTION_DEFINITIONS), MIN_SECTION_WORD_TARGET)

    persisted_sections: list[dict] = []
    try:
        for order_index, definition in enumerate(SECTION_DEFINITIONS):
            yield _sse("section_start", {"name": definition["title"]})

            section_state = {
                "key": definition["key"],
                "title": definition["title"],
                "query_fields": definition["query_fields"],
                "drafting_note": _build_drafting_note(
                    proposal_title, client_name, additional_context, word_target, definition.get("outline"),
                ),
                "retrieved_chunks": [],
            }
            async with db_session() as db:
                section_state["retrieved_chunks"] = await retrieve_chunks_for_section(
                    db, section_state, requirements, category_ids, has_knowledge,
                )

            content_parts: list[str] = []
            for delta in draft_one_section_stream(section_state, requirements_json):
                content_parts.append(delta)
                yield _sse("section_chunk", {"content": delta})

            content = "".join(content_parts).strip()
            citations = section_citations(section_state)

            persisted_sections.append({
                "title": definition["title"],
                "content": content,
                "order_index": order_index,
            })

            async with db_session() as db:
                await create_proposal_sections(db, [
                    ProposalSection(
                        proposal_id=proposal_id,
                        section_key=definition["key"],
                        title=definition["title"],
                        order_index=order_index,
                        content=content,
                        citations=citations,
                        status=ProposalSectionStatus.APPROVED,
                    )
                ])

            yield _sse("section_done", {"name": definition["title"]})

    except Exception as error:
        logger.exception("proposal generation failed | proposal_id=%s", proposal_id)
        async with db_session() as db:
            proposal = await get_proposal_by_id(db, proposal_id)
            if proposal:
                await update_proposal(db, proposal, status=ProposalStatus.FAILED, error_message=str(error))
        yield _sse("error", {"message": str(error)})
        return

    markdown = assemble_markdown(proposal_title, persisted_sections)
    s3_key = f"output/proposals/{user_id}/{proposal_id}/proposal.md"
    s3_service.upload_bytes(markdown.encode("utf-8"), s3_key, content_type="text/markdown")

    async with db_session() as db:
        proposal = await get_proposal_by_id(db, proposal_id)
        await update_proposal(db, proposal, markdown_path=s3_key, status=ProposalStatus.REVIEW)

    logger.info(
        "proposal generation completed | proposal_id=%s sections=%s", proposal_id, len(persisted_sections)
    )
    yield _sse("done", {})
