from pinecone import Pinecone

from config import config


class PineconeService:
    client = None
    _index = None

    @classmethod
    def get_client(cls):
        if cls.client is None:
            cls.client = Pinecone(api_key=config.pinecone.api_key)
        return cls.client

    @classmethod
    def get_index(cls):
        # Cached alongside the client because every `Index(...)` call builds a
        # new data-plane object with its own urllib3 connection pool — so an
        # uncached call means a fresh TCP + TLS handshake for each query
        # instead of reusing a kept-alive connection. (The index *host*
        # lookup is already cached on the client, so that part costs nothing
        # extra; the connection pool is what was being thrown away.)
        if cls._index is None:
            cls._index = cls.get_client().Index(config.pinecone.index_name)
        return cls._index
