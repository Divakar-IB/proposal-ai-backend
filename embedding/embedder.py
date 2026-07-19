from embedding.novita_client import NovitaEmbeddingClient

# Kept well under Novita's per-request payload limits and gives reasonable
# progress granularity for logging on large documents.
BATCH_SIZE = 32


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batches requests to the embedding endpoint. Used by both the knowledge
    chunking pipeline (embed chunks) and retrieval (embed a query string)."""

    embeddings: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        embeddings.extend(NovitaEmbeddingClient.embed(batch))
    return embeddings


def embed_query(text: str) -> list[float]:
    results = embed_texts([text])
    return results[0] if results else []
