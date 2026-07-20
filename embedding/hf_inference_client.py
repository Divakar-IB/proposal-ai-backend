import requests

from config import config


class HFInferenceEmbeddingClient:
    """Thin wrapper around HF Inference's feature-extraction endpoint."""

    @classmethod
    def embed(cls, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        response = requests.post(
            config.hf_inference.embedding_api_url,
            headers={"Authorization": f"Bearer {config.hf_inference.api_token}"},
            json={"inputs": texts},
        )
        response.raise_for_status()
        return response.json()
