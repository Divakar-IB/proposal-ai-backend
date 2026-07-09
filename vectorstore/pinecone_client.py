from pinecone import Pinecone, ServerlessSpec
from config import config

class PineconeService():
    client = None


    @classmethod
    def get_client(cls):
        cls.client = Pinecone(
            api_key = config.pinecone.api_key
        )
        return cls.client
    
# print(PineconeService.get_client())