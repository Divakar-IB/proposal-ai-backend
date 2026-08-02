import asyncio
import json
from typing import Any, AsyncIterator, Callable, Iterator, Optional

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

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
from generation.length_budget import (
    MIN_PROPOSAL_PAGES,
    MIN_SECTION_WORDS,
    WORDS_PER_PAGE,
    allocate_section_word_targets,
    build_length_instruction,
)
from generation.markdown_sections import assemble_markdown
from generation.nodes import draft_one_section_stream, retrieve_chunks_for_section, section_citations
from generation.requirement_context import build_combined_requirements_json
from generation.sections import SECTION_DEFINITIONS, build_outline_instruction
from generation.state import ProposalGenerationState, SectionState
from utilities.logger import get_logger
from utilities.s3_service import S3Service

logger = get_logger(__name__)
s3_service = S3Service()


def _build_drafting_note(
    proposal_title: str,
    client_name: str,
    additional_context: Optional[str],
    word_target: int,
    page_count: int,
    outline: Optional[list[str]],
) -> str:
    """Per-section drafting note: what is being written, then the strict word
    range for this section, then its required subsection outline. The length
    clause is deliberately last-but-one so it sits close to the outline it
    constrains."""

    header = "\n".join(part for part in [
        f"Proposal: {proposal_title} — Client: {client_name}",
        f"Additional context: {additional_context}" if additional_context else None,
    ] if part)

    parts = [
        header,
        build_length_instruction(word_target, page_count),
        build_outline_instruction(outline),
    ]
    return "\n\n".join(part for part in parts if part)


async def load_context(state: ProposalGenerationState) -> dict[str, Any]:
    """Fetches the proposal + its requirement documents, builds the combined
    requirements JSON, resets any previously persisted sections, and moves
    the proposal into GENERATING — the same setup `generate_proposal_stream`
    used to do inline before its per-section loop."""

    proposal_id = state["proposal_id"]
    page_count = state["page_count"]
    generation_mode = state["generation_mode"]

    async with db_session() as db:
        proposal = await get_proposal_by_id(db, proposal_id)
        if proposal is None:
            raise ValueError(f"proposal {proposal_id} not found")

        requirement_documents = await get_requirement_documents_by_proposal_id(db, proposal.id)
        requirements_json = build_combined_requirements_json(requirement_documents)
        requirements = json.loads(requirements_json) if requirements_json else {}

        has_knowledge = (
            generation_mode == GenerationMode.KNOWLEDGE_AUGMENTED and await has_any_knowledge_chunks(db)
        )

        proposal_title = proposal.title
        client_name = proposal.client_name
        additional_context = proposal.additional_context
        user_id = proposal.user_id

        await delete_proposal_sections_for_proposal(db, proposal.id)
        await update_proposal(
            db, proposal,
            status=ProposalStatus.GENERATING,
            generation_mode=generation_mode,
            page_count=page_count,
        )

    # One weighted split of the page budget up front, so every section knows
    # its own allocation before any drafting starts.
    word_targets = allocate_section_word_targets(page_count, SECTION_DEFINITIONS)
    allocated = sum(word_targets.values())
    budget = page_count * WORDS_PER_PAGE
    if page_count < MIN_PROPOSAL_PAGES:
        # The API rejects this (ProposalGenerateRequest.page_count has ge=
        # MIN_PROPOSAL_PAGES), so reaching here means a non-HTTP caller — the
        # Arq job or tasks/proposal_generation.py — passed a raw value.
        logger.warning(
            "page_count below the %s-page minimum | proposal_id=%s page_count=%s: sections "
            "cannot cover their required subsections at this length",
            MIN_PROPOSAL_PAGES, proposal_id, page_count,
        )
    if allocated > budget:
        logger.warning(
            "page_count too small for the section list | proposal_id=%s page_count=%s "
            "budget_words=%s floor_words=%s sections=%s — the export will run long",
            proposal_id, page_count, budget, allocated, len(SECTION_DEFINITIONS),
        )
    logger.info(
        "section word budget allocated | proposal_id=%s page_count=%s budget_words=%s allocated=%s",
        proposal_id, page_count, budget, allocated,
    )

    return {
        "user_id": user_id,
        "requirements": requirements,
        "requirements_json": requirements_json,
        "proposal_title": proposal_title,
        "client_name": client_name,
        "additional_context": additional_context,
        "word_targets": word_targets,
        "has_knowledge": has_knowledge,
        "current_section_index": 0,
        "sections": [],
        "persisted_sections": [],
    }


async def start_section(state: ProposalGenerationState) -> dict[str, Any]:
    definition = SECTION_DEFINITIONS[state["current_section_index"]]

    drafting_note = _build_drafting_note(
        state["proposal_title"], state["client_name"], state["additional_context"],
        state["word_targets"].get(definition["key"], MIN_SECTION_WORDS),
        state["page_count"], definition.get("outline"),
    )

    section_state: SectionState = {
        "key": definition["key"],
        "title": definition["title"],
        "query_fields": definition["query_fields"],
        "drafting_note": drafting_note,
        "retrieved_chunks": [],
        "content": None,
        "citations": [],
        "status": ProposalSectionStatus.PENDING.value,
        "feedback": None,
    }

    writer = get_stream_writer()
    writer({"event": "section_start", "data": {"name": definition["title"]}})

    return {"current_section": section_state}


async def retrieve(state: ProposalGenerationState) -> dict[str, Any]:
    section_state = state["current_section"]

    async with db_session() as db:
        section_state["retrieved_chunks"] = await retrieve_chunks_for_section(
            db, section_state, state["requirements"], state["has_knowledge"],
        )

    return {"current_section": section_state}


async def _aiter_blocking(make_iterator: Callable[[], Iterator[str]]) -> AsyncIterator[str]:
    """Bridges a blocking synchronous generator into an async iterator.

    Required for live token streaming. `draft_one_section_stream` is a sync
    generator that blocks on socket reads from the LLM; iterating it directly
    inside an async node never yields to the event loop, so LangGraph's stream
    consumer cannot drain the writer queue and every token of a section is
    flushed in one burst when the node finally returns — the client sees a
    lump per section instead of text appearing as it is generated.

    Running the producer in a worker thread and awaiting each item hands
    control back to the event loop per token, so the SSE line goes out
    immediately. It also keeps the loop free while the LLM socket blocks,
    instead of stalling every other request in the process.
    """

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    def produce() -> None:
        try:
            for item in make_iterator():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except BaseException as error:  # re-raised on the consumer side below
            loop.call_soon_threadsafe(queue.put_nowait, error)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, done)

    producer = loop.run_in_executor(None, produce)
    try:
        while True:
            item = await queue.get()
            if item is done:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        await producer


async def draft(state: ProposalGenerationState) -> dict[str, Any]:
    section_state = state["current_section"]
    writer = get_stream_writer()

    content_parts: list[str] = []
    async for delta in _aiter_blocking(
        lambda: draft_one_section_stream(section_state, state["requirements_json"])
    ):
        content_parts.append(delta)
        writer({"event": "section_chunk", "data": {"content": delta}})

    section_state["content"] = "".join(content_parts).strip()
    section_state["citations"] = section_citations(section_state)
    section_state["status"] = ProposalSectionStatus.APPROVED.value

    return {"current_section": section_state}


async def persist_section(state: ProposalGenerationState) -> dict[str, Any]:
    section_state = state["current_section"]
    order_index = state["current_section_index"]

    async with db_session() as db:
        await create_proposal_sections(db, [
            ProposalSection(
                proposal_id=state["proposal_id"],
                section_key=section_state["key"],
                title=section_state["title"],
                order_index=order_index,
                content=section_state["content"],
                citations=section_state["citations"],
                status=ProposalSectionStatus.APPROVED,
            )
        ])

    writer = get_stream_writer()
    writer({"event": "section_done", "data": {"name": section_state["title"]}})

    persisted_sections = [*state["persisted_sections"], {
        "title": section_state["title"],
        "content": section_state["content"],
        "order_index": order_index,
    }]

    return {
        "persisted_sections": persisted_sections,
        "current_section_index": state["current_section_index"] + 1,
    }


def _has_more_sections(state: ProposalGenerationState) -> str:
    return "start_section" if state["current_section_index"] < len(SECTION_DEFINITIONS) else "compile_proposal"


async def compile_proposal(state: ProposalGenerationState) -> dict[str, Any]:
    markdown = assemble_markdown(state["proposal_title"], state["persisted_sections"])
    s3_key = f"output/proposals/{state['user_id']}/{state['proposal_id']}/proposal.md"
    s3_service.upload_bytes(markdown.encode("utf-8"), s3_key, content_type="text/markdown")

    async with db_session() as db:
        proposal = await get_proposal_by_id(db, state["proposal_id"])
        await update_proposal(db, proposal, markdown_path=s3_key, status=ProposalStatus.REVIEW)

    logger.info(
        "proposal generation completed | proposal_id=%s sections=%s",
        state["proposal_id"], len(state["persisted_sections"]),
    )

    return {"markdown_path": s3_key}


def build_proposal_generation_graph():
    graph = StateGraph(ProposalGenerationState)

    graph.add_node("load_context", load_context)
    graph.add_node("start_section", start_section)
    graph.add_node("retrieve", retrieve)
    graph.add_node("draft", draft)
    graph.add_node("persist_section", persist_section)
    graph.add_node("compile_proposal", compile_proposal)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "start_section")
    graph.add_edge("start_section", "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", "persist_section")
    graph.add_conditional_edges(
        "persist_section",
        _has_more_sections,
        {"start_section": "start_section", "compile_proposal": "compile_proposal"},
    )
    graph.add_edge("compile_proposal", END)

    return graph.compile()


PROPOSAL_GENERATION_GRAPH = build_proposal_generation_graph()
