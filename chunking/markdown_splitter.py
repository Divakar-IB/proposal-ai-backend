from langchain_text_splitters import MarkdownHeaderTextSplitter

_HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]


def split_by_headers(markdown: str) -> list[tuple[str, str]]:
    """Splits Markdown on heading hierarchy. Returns (content, breadcrumb) pairs,
    where breadcrumb is "h1 > h2 > h3" built from whichever levels are present."""

    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_HEADERS_TO_SPLIT_ON, strip_headers=True)
    docs = splitter.split_text(markdown)

    sections: list[tuple[str, str]] = []
    for doc in docs:
        content = doc.page_content.strip()
        if not content:
            continue

        breadcrumb_parts = [doc.metadata[key] for key in ("h1", "h2", "h3") if doc.metadata.get(key)]
        breadcrumb = " > ".join(breadcrumb_parts)
        sections.append((content, breadcrumb))

    return sections
