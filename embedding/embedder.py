BATCH_SIZE = 32


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batches requests to the embedding endpoint. Used by both the knowledge
    chunking pipeline (embed chunks) and retrieval (embed a query string)."""

    raise NotImplementedError("No embedding provider is configured (Novita was removed).")


def embed_query(text: str) -> list[float]:
    results = embed_texts([text])
    return results[0] if results else []
