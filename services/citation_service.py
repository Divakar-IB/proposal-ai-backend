from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import get_knowledge_documents_by_ids
from database.models import KnowledgeDocument


def _is_proposal_sourced(document: Optional[KnowledgeDocument]) -> bool:
    """A KnowledgeDocument carries source_proposal_id only when it was
    auto-ingested from an approved proposal (see
    services.proposal_knowledge_service); a manual upload leaves it NULL."""

    return document is not None and document.source_proposal_id is not None

# Retrieval fetches this multiple of the caller's requested top_k from
# Pinecone, so that after excluding proposal-derived chunks by default (see
# resolve_and_filter_chunks) there's still a reasonable pool left to
# truncate back down to top_k from, instead of silently returning fewer
# results than requested.
_RETRIEVAL_HEADROOM_MULTIPLIER = 3
_MAX_RETRIEVAL_POOL = 50


def retrieval_pool_size(top_k: int) -> int:
    return min(top_k * _RETRIEVAL_HEADROOM_MULTIPLIER, _MAX_RETRIEVAL_POOL)


async def resolve_and_filter_chunks(
    db: AsyncSession,
    chunks: list[dict],
    top_k: int,
    include_proposal_sources: bool = False,
) -> list[tuple[dict, Optional[KnowledgeDocument]]]:
    """Resolves each retrieved chunk's source KnowledgeDocument with one
    batched lookup (not one query per chunk — this runs per proposal-
    generation section, so N+1 here would scale badly across thousands of
    proposals).

    By default, drops any chunk whose source document was itself
    auto-ingested from a previously approved proposal (source_proposal_id is
    set — see services.proposal_knowledge_service) rather than a manually
    uploaded document — otherwise another client's approved pricing/prose becomes
    retrievable, and pastable verbatim into a brand-new client's draft via
    generation/nodes.py's build_context_block. Pass
    include_proposal_sources=True for call sites where surfacing that (e.g.
    a purely informational "related past proposal" citation) is desired
    rather than a content-leakage risk.

    Truncates to top_k after filtering, so callers should over-fetch (see
    retrieval_pool_size) before calling this."""

    document_ids = {chunk["document_id"] for chunk in chunks if chunk.get("document_id") is not None}
    documents = await get_knowledge_documents_by_ids(db, list(document_ids))
    document_by_id = {document.id: document for document in documents}

    resolved: list[tuple[dict, Optional[KnowledgeDocument]]] = []
    for chunk in chunks:
        document = document_by_id.get(chunk.get("document_id"))
        if _is_proposal_sourced(document) and not include_proposal_sources:
            continue
        resolved.append((chunk, document))
        if len(resolved) >= top_k:
            break

    return resolved


def _section_name_from_breadcrumb(breadcrumb: str, proposal_title: str) -> Optional[str]:
    """breadcrumb for a proposal-derived chunk looks like
    "Generated Proposals > {proposal_title} > {section_title}[ > {subsection}]"
    (see services.proposal_knowledge_service and chunking/pipeline.py) — the
    section name is whichever segment immediately follows the proposal
    title."""

    parts = [part.strip() for part in breadcrumb.split(">") if part.strip()]
    if proposal_title in parts:
        index = parts.index(proposal_title)
        if index + 1 < len(parts):
            return parts[index + 1]
    return parts[-1] if parts else None


def label_knowledge_match(chunk: dict, document: Optional[KnowledgeDocument]) -> dict:
    """Shapes one requirement-document knowledge-match entry (see
    tasks.requirement_processing._compute_knowledge_matches), keeping every
    existing field populated (document_id/title/source_filename/breadcrumb/
    match_percent) so existing consumers of KnowledgeMatch are unaffected,
    and adding proposal-attribution fields alongside when the source is a
    previously approved proposal rather than an uploaded document."""

    match = {
        "document_id": chunk.get("document_id"),
        "title": document.title if document is not None else chunk.get("source_filename"),
        "source_filename": chunk.get("source_filename"),
        "breadcrumb": chunk.get("breadcrumb", ""),
        "match_percent": round(chunk["score"] * 100),
        "type": "knowledge_document",
    }

    if _is_proposal_sourced(document):
        match.update({
            "type": "proposal",
            "proposal_id": document.source_proposal_id,
            "proposal_name": document.title,
            "section_name": _section_name_from_breadcrumb(chunk.get("breadcrumb", ""), document.title),
        })

    return match


def label_section_citation(chunk: dict, document: Optional[KnowledgeDocument]) -> dict:
    """Shapes one proposal-generation section citation (see
    generation.nodes.section_citations) — same additive-fields approach as
    label_knowledge_match."""

    citation = {
        "breadcrumb": chunk.get("breadcrumb", ""),
        "source_filename": chunk.get("source_filename"),
        "type": "knowledge_document",
    }

    if _is_proposal_sourced(document):
        citation.update({
            "type": "proposal",
            "proposal_id": document.source_proposal_id,
            "proposal_name": document.title,
            "section_name": _section_name_from_breadcrumb(chunk.get("breadcrumb", ""), document.title),
        })

    return citation
