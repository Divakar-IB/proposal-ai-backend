import re

from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.crud import get_knowledge_document_by_id, get_or_create_category, get_proposal_by_id
from database.database import db_session
from database.db_enum import IngestionStatus
from database.models import KnowledgeDocument, Proposal
from generation.markdown_sections import assemble_markdown
from tasks.document_processing import process_knowledge_document
from utilities.logger import get_logger
from utilities.s3_service import S3Service

logger = get_logger(__name__)
s3_service = S3Service()

GENERATED_PROPOSALS_CATEGORY = "Generated Proposals"

# assemble_markdown always starts with "# {proposal_title}\n\n" — stripped
# before ingestion (see _strip_leading_h1 below).
_LEADING_H1_PATTERN = re.compile(r"^#\s+.*\n\n?", re.MULTILINE)


def _strip_leading_h1(markdown: str) -> str:
    """The knowledge-ingestion chunker (chunking/pipeline.py) already
    receives a `root_prefix` of "{category.name} > {document.title}" (set in
    tasks/document_processing.py, unmodified/reused as-is here). If the
    proposal's own "# {title}" heading were also left in the Markdown, the
    chunker's header-splitter would fold that same title into the
    breadcrumb a second time, producing a visibly doubled
    "Generated Proposals > {title} > {title} > {section}" breadcrumb.
    Stripping it here — only for the copy used for ingestion, not for
    Proposal.markdown_path — avoids that without touching the shared
    chunker/root_prefix logic at all."""

    return _LEADING_H1_PATTERN.sub("", markdown, count=1)


async def get_or_create_proposal_knowledge_document(db, proposal: Proposal) -> KnowledgeDocument:
    """Reassembles the proposal's *current* sections into Markdown (fixing a
    staleness gap: Proposal.markdown_path's S3 blob is only ever written
    once, at the end of generation, and never refreshed after sections are
    hand-edited via PATCH /proposal/{id}/sections) and upserts a single
    KnowledgeDocument row for it.

    Reused, not recreated, across repeated re-approvals — one proposal maps
    to at most one KnowledgeDocument row, via the unique constraint on
    source_proposal_id. The upsert is atomic (INSERT ... ON CONFLICT DO
    UPDATE) so two near-simultaneous callers (e.g. a double-click on
    "mark done") can't both insert a row for the same proposal."""

    sections = [
        {"title": section.title, "content": section.content, "order_index": section.order_index}
        for section in proposal.sections
    ]
    markdown = _strip_leading_h1(assemble_markdown(proposal.title, sections))

    s3_key = f"output/proposals/{proposal.user_id}/{proposal.id}/knowledge.md"
    s3_service.upload_bytes(markdown.encode("utf-8"), s3_key, content_type="text/markdown")

    category = await get_or_create_category(db, GENERATED_PROPOSALS_CATEGORY)
    file_name = f"{proposal.title}.md"

    upsert = (
        pg_insert(KnowledgeDocument)
        .values(
            title=proposal.title,
            file_name=file_name,
            file_path=s3_key,
            extension="md",
            category_id=category.id,
            user_id=proposal.user_id,
            status=IngestionStatus.PENDING,
            source_proposal_id=proposal.id,
        )
        .on_conflict_do_update(
            index_elements=[KnowledgeDocument.source_proposal_id],
            set_={
                "title": proposal.title,
                "file_name": file_name,
                "file_path": s3_key,
                "category_id": category.id,
                "version": KnowledgeDocument.version + 1,
                "status": IngestionStatus.PENDING,
                "is_active": True,
            },
        )
        .returning(KnowledgeDocument.id)
    )
    result = await db.execute(upsert)
    document_id = result.scalar_one()
    await db.commit()

    document = await get_knowledge_document_by_id(db, document_id)
    logger.info(
        "proposal knowledge document upserted | proposal_id=%s document_id=%s version=%s",
        proposal.id,
        document.id,
        document.version,
    )
    return document


async def ingest_proposal_as_knowledge(proposal_id: int) -> None:
    """Background-task entry point, triggered every time a proposal's status
    is explicitly set to DONE via PATCH /proposal/{id}/status (see
    router/proposals.py) — re-runs on every call, not just the first, so
    re-approving a proposal after further edits re-indexes the latest
    content. Reuses the existing, unmodified knowledge-ingestion pipeline
    (process_knowledge_document: extraction -> chunking -> embedding ->
    Pinecone upsert) — only the content source differs from a manually
    uploaded knowledge document. Its existing delete-then-recreate
    idempotency is what makes "re-upload every time" correct here too, with
    no vector-ID collisions (fresh UUIDs each run)."""

    logger.info("proposal knowledge ingestion started | proposal_id=%s", proposal_id)
    async with db_session() as db:
        proposal = await get_proposal_by_id(db, proposal_id)
        if proposal is None:
            logger.error("proposal not found, aborting ingestion | proposal_id=%s", proposal_id)
            return

        document = await get_or_create_proposal_knowledge_document(db, proposal)

    await process_knowledge_document(document.id)
