"""Aggregation helpers behind `GET /proposal/{proposal_id}/state`.

A proposal can carry several requirement documents, each parsed independently
with its own summary / knowledge matches / capability tags. These functions
collapse that per-file data into the single combined view the generation wizard
renders, while the router keeps the per-file breakdown alongside it.

Note: `combined_summary` is deliberately *not*
`generation.requirement_context.build_combined_summary` — that one always adds a
`### {file_name} (#{id})` heading because it feeds the LLM, whereas this one
leaves a single file's summary verbatim for display.
"""

from database.db_enum import ProposalStatus
from database.models import RequirementDocument


def wizard_generation_status(proposal_status: ProposalStatus) -> str:
    """Collapses the full proposal lifecycle down to what the generation
    wizard step cares about: still running, errored, or finished (review/
    done both read as "done" here — status tracking/export are separate
    steps outside this flow)."""

    if proposal_status == ProposalStatus.GENERATING:
        return "generating"
    if proposal_status == ProposalStatus.FAILED:
        return "failed"
    return "done"


def combined_summary(documents: list[RequirementDocument]) -> str:
    """One summary covering every parsed file. A single file keeps its
    summary verbatim (no heading added, so the single-upload flow renders
    exactly as before); several are concatenated under per-file headings."""

    if len(documents) == 1:
        return documents[0].summary
    return "\n\n".join(f"### {document.file_name}\n\n{document.summary}" for document in documents)


def merge_knowledge_matches(documents: list[RequirementDocument]) -> list[dict]:
    """Union of every file's knowledge matches, keeping the highest
    match_percent per knowledge document so the same source isn't listed
    once per uploaded file, and ordered strongest-first."""

    best: dict[int, dict] = {}
    for document in documents:
        for match in document.knowledge_matches or []:
            document_id = match.get("document_id")
            current = best.get(document_id)
            if current is None or match.get("match_percent", 0) > current.get("match_percent", 0):
                best[document_id] = match
    return sorted(best.values(), key=lambda match: match.get("match_percent", 0), reverse=True)


def merge_capability_tags(documents: list[RequirementDocument]) -> list[dict]:
    """Union of every file's capability tags, keeping the highest confidence
    per tag name, ordered most-confident-first."""

    best: dict[str, dict] = {}
    for document in documents:
        for tag in document.capability_tags or []:
            name = tag.get("name")
            current = best.get(name)
            if current is None or tag.get("confidence", 0) > current.get("confidence", 0):
                best[name] = tag
    return sorted(best.values(), key=lambda tag: tag.get("confidence", 0), reverse=True)
