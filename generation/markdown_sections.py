import re

_H2_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "section"


def split_into_sections(markdown: str) -> list[dict]:
    """Splits a generated proposal on its "## " headings. Each heading starts
    a new section running through (not including) the next "## " heading.
    Any content before the first heading is dropped — the generation prompt
    instructs the model to start directly with a heading, so this only
    triggers on a malformed response."""

    matches = list(_H2_PATTERN.finditer(markdown))
    sections: list[dict] = []
    seen_slugs: dict[str, int] = {}

    for index, match in enumerate(matches):
        title = match.group(1).strip()
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        content = markdown[content_start:content_end].strip()

        slug = slugify(title)
        seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
        if seen_slugs[slug] > 1:
            slug = f"{slug}-{seen_slugs[slug]}"

        sections.append({
            "section_key": slug,
            "title": title,
            "order_index": index,
            "content": content,
        })

    return sections


def assemble_markdown(proposal_title: str, sections: list[dict]) -> str:
    """Inverse of split_into_sections — rebuilds one canonical Markdown
    document from ordered section dicts (each needs at least "title" and
    "content"). Shared by the per-section generation stream and the
    DOCX/PDF export service, so both always render from the same shape."""

    ordered = sorted(sections, key=lambda section: section.get("order_index", 0))
    body = "\n\n".join(f"## {section['title']}\n\n{section['content'] or ''}".rstrip() for section in ordered)
    return f"# {proposal_title}\n\n{body}\n"
