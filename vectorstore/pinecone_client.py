from pinecone import Pinecone, ServerlessSpec
from config import config

class PineconeService():
    client = None


    @classmethod
    def get_client(cls):
        if cls.client is None:
            cls.client = Pinecone(
                api_key = config.pinecone.api_key
            )
        return cls.client

    @classmethod
    def get_index(cls):
        return cls.get_client().Index(config.pinecone.index_name)