from typing import Optional
from uuid import uuid4

from pinecone.errors.exceptions import NotFoundError

from chunking.models import Chunk
from vectorstore.pinecone_client import PineconeService


def build_vector_id(document_id: int, chunk_index: int) -> str:
    return f"kdoc-{document_id}-{chunk_index}-{uuid4().hex[:8]}"


def upsert_chunks(
    document_id: int,
    category_id: int,
    source_filename: str,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    source_type: Optional[str] = None,
    source_proposal_id: Optional[int] = None,
    organization_name: Optional[str] = None,
    embedding_version: Optional[str] = None,
) -> list[str]:
    """Upserts embedded chunks into Pinecone with structured metadata.
    Returns the Pinecone vector IDs in the same order as `chunks`, so the
    caller can persist them onto the corresponding KnowledgeChunk rows.

    `source_type`/`source_proposal_id`/`organization_name`/`embedding_version`
    are additive, optional metadata (omitted entirely when not passed) used
    to attribute chunks originating from an approved proposal rather than a
    manually uploaded document — see services.citation_service. They are
    not used to filter retrieval; query_chunks callers that need to exclude
    proposal-derived content do so by resolving each hit's source document
    in Postgres instead (see generation/nodes.py, tasks/requirement_processing.py)."""

    index = PineconeService.get_index()
    vector_ids = [build_vector_id(document_id, chunk.chunk_index) for chunk in chunks]

    extra_metadata = {
        key: value
        for key, value in {
            "source_type": source_type,
            "source_proposal_id": source_proposal_id,
            "organization_name": organization_name,
            "embedding_version": embedding_version,
        }.items()
        if value is not None
    }

    vectors = [
        {
            "id": vector_id,
            "values": embedding,
            "metadata": {
                "document_id": document_id,
                "category_id": category_id,
                "breadcrumb": chunk.breadcrumb,
                "page_number": chunk.page_number or 0,
                "chunk_index": chunk.chunk_index,
                "source_filename": source_filename,
                "text": chunk.content,
                **extra_metadata,
            },
        }
        for vector_id, chunk, embedding in zip(vector_ids, chunks, embeddings)
    ]

    index.upsert(vectors=vectors)
    return vector_ids


def delete_document_vectors(document_id: int) -> None:
    """Removes all vectors for a document (e.g. before re-processing a new version).
    No-ops if the namespace doesn't exist yet (first-ever upload for this index)."""

    index = PineconeService.get_index()
    try:
        index.delete(filter={"document_id": document_id})
    except NotFoundError:
        pass


def query_chunks(
    query_embedding: list[float],
    top_k: int = 5,
    category_ids: Optional[list[int]] = None,
) -> list[dict]:
    """Queries Pinecone with optional metadata filtering by category.
    Returns a list of {text, breadcrumb, document_id, page_number, score, source_filename}."""

    index = PineconeService.get_index()
    query_filter = {"category_id": {"$in": category_ids}} if category_ids else None

    response = index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
        filter=query_filter,
    )

    return [
        {
            "text": match["metadata"].get("text", ""),
            "breadcrumb": match["metadata"].get("breadcrumb", ""),
            "document_id": match["metadata"].get("document_id"),
            "page_number": match["metadata"].get("page_number"),
            "source_filename": match["metadata"].get("source_filename"),
            "score": match["score"],
        }
        for match in response.get("matches", [])
    ]
