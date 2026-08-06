from langchain_text_splitters import RecursiveCharacterTextSplitter

from chunking.table_aware import split_section
from chunking.tokenization import count_tokens

# 500 tokens / ~10% overlap: small enough for focused retrieval matches,
# large enough to keep coherent context for both embedding and drafting.
DEFAULT_CHUNK_SIZE_TOKENS = 500
DEFAULT_CHUNK_OVERLAP_TOKENS = 50


def split_oversized_section(
    text: str, chunk_size: int = DEFAULT_CHUNK_SIZE_TOKENS, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP_TOKENS
) -> list[str]:
    """Sub-splits a single heading-hierarchy section that exceeds chunk_size tokens.
    Returns [text] unchanged if it already fits.

    Markdown tables are split on row boundaries with their header repeated on
    each piece (see chunking/table_aware.py); prose still goes through the
    recursive character splitter below, overlap included.
    """

    if count_tokens(text) <= chunk_size:
        return [text]

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    def split_prose(block: str) -> list[str]:
        return [chunk.strip() for chunk in splitter.split_text(block) if chunk.strip()]

    return [chunk.strip() for chunk in split_section(text, chunk_size, split_prose) if chunk.strip()]
