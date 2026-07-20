from typing import Optional
from uuid import uuid4

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
    upload_timestamp: Optional[str] = None,
) -> list[str]:
    """Upserts embedded chunks into Pinecone with structured metadata.
    Returns the Pinecone vector IDs in the same order as `chunks`, so the
    caller can persist them onto the corresponding KnowledgeChunk rows."""

    index = PineconeService.get_index()
    vector_ids = [build_vector_id(document_id, chunk.chunk_index) for chunk in chunks]

    vectors = [
        {
            "id": vector_id,
            "values": embedding,
            "metadata": _build_metadata(document_id, category_id, source_filename, chunk, upload_timestamp),
        }
        for vector_id, chunk, embedding in zip(vector_ids, chunks, embeddings)
    ]

    index.upsert(vectors=vectors)
    return vector_ids


def _build_metadata(
    document_id: int,
    category_id: int,
    source_filename: str,
    chunk: Chunk,
    upload_timestamp: Optional[str],
) -> dict:
    """Pinecone rejects null metadata values, so optional fields (confidence,
    source_type, upload_timestamp) are only included when actually available."""

    metadata = {
        "document_id": document_id,
        "category_id": category_id,
        "breadcrumb": chunk.breadcrumb,
        "page_number": chunk.page_number or 0,
        "chunk_index": chunk.chunk_index,
        "source_filename": source_filename,
        "text": chunk.content,
        "section_heading": chunk.breadcrumb.rsplit(" > ", 1)[-1] if chunk.breadcrumb else "",
    }
    if chunk.source_type is not None:
        metadata["source_type"] = chunk.source_type
    if chunk.confidence is not None:
        metadata["confidence"] = chunk.confidence
    if upload_timestamp is not None:
        metadata["upload_timestamp"] = upload_timestamp
    return metadata


def delete_document_vectors(document_id: int) -> None:
    """Removes all vectors for a document (e.g. before re-processing a new version)."""

    index = PineconeService.get_index()
    index.delete(filter={"document_id": document_id})


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
