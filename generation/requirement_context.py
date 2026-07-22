import json

from database.models import RequirementDocument


def build_combined_summary(requirement_documents: list[RequirementDocument]) -> str:
    """Concatenates each document's own summary, labeled by filename, so a
    multi-file proposal reads as one requirement brief instead of losing all
    but the first document."""

    parts = [
        f"### {document.file_name}\n{document.summary.strip()}"
        for document in requirement_documents
        if document.summary
    ]
    return "\n\n".join(parts)


def build_combined_requirements_json(requirement_documents: list[RequirementDocument]) -> str:
    """Combines each document's structured `parsed_data` into one JSON blob,
    keyed by filename, for prompts that need the raw structured requirements
    (e.g. per-section drafting) rather than the summary."""

    combined = {
        document.file_name: document.parsed_data
        for document in requirement_documents
        if document.parsed_data
    }
    return json.dumps(combined, indent=2)
