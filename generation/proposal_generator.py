from typing import AsyncIterator, Optional

from database.crud import (
    create_proposal_sections,
    delete_proposal_sections_for_proposal,
    get_proposal_by_id,
    get_requirement_document_by_id,
    has_any_knowledge_chunks,
    update_proposal,
)
from database.database import db_session
from database.db_enum import GenerationMode, ProposalSectionStatus, ProposalStatus
from database.models import Proposal, ProposalSection
from embedding.embedder import embed_query
from generation.markdown_sections import split_into_sections
from generation.prompts import (
    GENERATE_SYSTEM_PROMPT,
    GENERATE_USER_TEMPLATE,
    WORDS_PER_PAGE,
    build_grounding_instructions,
    build_knowledge_context_block,
)
from llm.chat_client import GroqChatClient
from utilities.logger import get_logger
from utilities.s3_service import S3Service
from vectorstore.knowledge_store import query_chunks

logger = get_logger(__name__)
s3_service = S3Service()

TOP_K_KNOWLEDGE_CHUNKS = 15


async def _retrieve_knowledge_context(
    db, proposal: Proposal, requirement_summary: Optional[str]
) -> list[dict]:
    if not await has_any_knowledge_chunks(db):
        return []

    query_text = "\n".join(
        part for part in [proposal.title, requirement_summary, proposal.additional_context] if part
    ).strip()
    if not query_text:
        return []

    query_embedding = embed_query(query_text)
    return query_chunks(query_embedding, top_k=TOP_K_KNOWLEDGE_CHUNKS)


def _build_messages(
    proposal: Proposal,
    requirement_summary: Optional[str],
    page_count: int,
    knowledge_chunks: list[dict],
) -> list[dict]:
    system_prompt = GENERATE_SYSTEM_PROMPT.format(
        word_target=page_count * WORDS_PER_PAGE,
        grounding_instructions=build_grounding_instructions(bool(knowledge_chunks)),
    )
    user_prompt = GENERATE_USER_TEMPLATE.format(
        proposal_title=proposal.title,
        client_name=proposal.client_name,
        requirement_summary=requirement_summary or "(no summary available)",
        additional_context=proposal.additional_context or "(none provided)",
        knowledge_context=build_knowledge_context_block(knowledge_chunks),
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def generate_proposal_stream(
    proposal_id: int,
    page_count: int,
    generation_mode: GenerationMode,
) -> AsyncIterator[str]:
    """Core generator: fetches the proposal + its requirement summary,
    optionally retrieves knowledge-base context, streams Markdown deltas
    from Groq as they arrive, then on completion splits the full text into
    sections and persists everything. Yields raw Markdown text chunks."""

    async with db_session() as db:
        proposal = await get_proposal_by_id(db, proposal_id)
        if proposal is None:
            raise ValueError(f"proposal {proposal_id} not found")

        requirement_document = await get_requirement_document_by_id(db, proposal.requirement_document_id)
        requirement_summary = requirement_document.summary if requirement_document else None

        knowledge_chunks: list[dict] = []
        if generation_mode == GenerationMode.KNOWLEDGE_AUGMENTED:
            knowledge_chunks = await _retrieve_knowledge_context(db, proposal, requirement_summary)

        await update_proposal(
            db, proposal,
            status=ProposalStatus.GENERATING,
            generation_mode=generation_mode,
            page_count=page_count,
        )
        messages = _build_messages(proposal, requirement_summary, page_count, knowledge_chunks)

    full_markdown_parts: list[str] = []
    try:
        for delta in GroqChatClient.stream_complete(messages):
            full_markdown_parts.append(delta)
            yield delta
    except Exception as error:
        logger.exception("proposal generation failed | proposal_id=%s", proposal_id)
        async with db_session() as db:
            proposal = await get_proposal_by_id(db, proposal_id)
            if proposal:
                await update_proposal(db, proposal, status=ProposalStatus.FAILED, error_message=str(error))
        raise

    await _persist_generated_proposal(proposal_id, "".join(full_markdown_parts))


async def _persist_generated_proposal(proposal_id: int, markdown: str) -> None:
    sections = split_into_sections(markdown)

    async with db_session() as db:
        proposal = await get_proposal_by_id(db, proposal_id)
        if proposal is None:
            return

        s3_key = f"output/proposals/{proposal.user_id}/{proposal_id}/proposal.md"
        s3_service.upload_bytes(markdown.encode("utf-8"), s3_key, content_type="text/markdown")

        await delete_proposal_sections_for_proposal(db, proposal_id)
        section_rows = [
            ProposalSection(
                proposal_id=proposal_id,
                section_key=section["section_key"],
                title=section["title"],
                order_index=section["order_index"],
                content=section["content"],
                status=ProposalSectionStatus.APPROVED,
            )
            for section in sections
        ]
        await create_proposal_sections(db, section_rows)

        await update_proposal(db, proposal, markdown_path=s3_key, status=ProposalStatus.REVIEW)
        logger.info(
            "proposal generation completed | proposal_id=%s sections=%s", proposal_id, len(sections)
        )
