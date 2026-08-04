from pinecone import ServerlessSpec

from config import config
from vectorstore.pinecone_client import PineconeService


class PineconeIndexManager:

    @classmethod
    def create_index(cls):

        client = PineconeService.get_client()
        index_name = config.pinecone.index_name
        existing_indexes = [
            index["name"]
            for index in client.list_indexes()
        ]

        if index_name in existing_indexes:
            print(f"Index '{index_name}' already exists.")
            return

        client.create_index(
            name=index_name,
            dimension=config.pinecone.dimension,
            metric=config.pinecone.metric,
            spec=ServerlessSpec(
                cloud=config.pinecone.cloud,
                region=config.pinecone.region,
            ),
        )

        print(f"Index '{index_name}' created successfully.")