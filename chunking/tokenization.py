import tiktoken

# cl100k_base is a good universal approximation for chunk-sizing purposes;
# it doesn't need to match BGE-M3's own tokenizer exactly, only to keep
# chunks in a consistent, predictable size band.
_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))
