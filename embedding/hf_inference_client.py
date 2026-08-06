import threading

import requests

from config import config


class HFInferenceEmbeddingClient:
    """Thin wrapper around HF Inference's feature-extraction endpoint."""

    # One Session per thread, reused for that thread's lifetime.
    #
    # Module-level `requests.post` opens and discards a fresh TCP + TLS
    # connection on every call, and this endpoint is hit once per embed batch
    # — once per retrieval query during generation, and once per chunk batch
    # during knowledge ingestion. A Session keeps the connection alive through
    # urllib3's pool so those calls reuse it.
    #
    # Thread-local rather than one shared Session because embeds are dispatched
    # to worker threads (see generation/nodes.py::prefetch_section_retrievals);
    # requests.Session offers no thread-safety guarantee, and a per-thread
    # instance avoids the question without giving up connection reuse, since
    # the pool's threads are long-lived.
    _local = threading.local()

    @classmethod
    def _session(cls) -> requests.Session:
        session = getattr(cls._local, "session", None)
        if session is None:
            session = requests.Session()
            cls._local.session = session
        return session

    @classmethod
    def embed(cls, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        response = cls._session().post(
            config.hf_inference.embedding_api_url,
            headers={"Authorization": f"Bearer {config.hf_inference.api_token}"},
            json={"inputs": texts},
        )
        response.raise_for_status()
        return response.json()
