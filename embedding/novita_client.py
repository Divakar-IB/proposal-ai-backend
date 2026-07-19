from openai import OpenAI

from config import config


class NovitaEmbeddingClient:
    """Thin wrapper around Novita's OpenAI-compatible embeddings endpoint (BGE-M3)."""

    _client: OpenAI | None = None

    @classmethod
    def get_client(cls) -> OpenAI:
        if cls._client is None:
            cls._client = OpenAI(
                api_key=config.novita.api_key,
                base_url=config.novita.embedding_base_url,
            )
        return cls._client

    @classmethod
    def embed(cls, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        client = cls.get_client()
        response = client.embeddings.create(
            model=config.novita.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]
