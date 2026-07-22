# import json

# from fastapi import HTTPException, status
# from sqlalchemy.ext.asyncio import AsyncSession

# from database.crud import (
#     get_proposal_by_id,
#     get_proposal_section_by_id,
#     get_requirement_document_by_id,
#     has_any_knowledge_chunks,
#     update_proposal_section,
# )
# from database.db_enum import ProposalSectionStatus
# from database.models import ProposalSection
# from generation.nodes import decide_section_status, draft_one_section, retrieve_chunks_for_section, run_quality_check
# from generation.sections import SECTION_DEFINITIONS
# from schemas.proposal import SectionEditRequest
# from utilities.logger import get_logger

# logger = get_logger(__name__)

# _SECTION_DEFINITIONS_BY_KEY = {definition["key"]: definition for definition in SECTION_DEFINITIONS}


# async def _get_section_or_404(db: AsyncSession, section_id: int) -> ProposalSection:
#     section = await get_proposal_section_by_id(db, section_id)
#     if section is None:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal section not found")
#     return section


# async def edit_section(db: AsyncSession, section_id: int, request: SectionEditRequest) -> ProposalSection:
#     """User-edited content replaces the drafted content directly — status and
#     review_flag are left untouched; approving is a separate explicit action."""

#     section = await _get_section_or_404(db, section_id)
#     return await update_proposal_section(db, section, content=request.content)


# async def approve_section(db: AsyncSession, section_id: int) -> ProposalSection:
#     section = await _get_section_or_404(db, section_id)
#     return await update_proposal_section(
#         db, section,
#         status=ProposalSectionStatus.APPROVED,
#         review_flag=False,
#     )


# async def regenerate_section(db: AsyncSession, section_id: int) -> ProposalSection:
#     """One fresh draft + quality-check pass for a single section, reusing the
#     exact same per-section helpers the LangGraph pipeline uses (generation/nodes.py)
#     so drafting/review logic is never duplicated between the automated pipeline
#     and this user-triggered path. Unlike the automated pipeline, this never
#     force-approves — it's a single explicit action with a predictable, bounded
#     (one draft call + one review call) token cost per click."""

#     section = await _get_section_or_404(db, section_id)

#     proposal = await get_proposal_by_id(db, section.proposal_id)
#     if proposal is None:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found for this section")

#     requirement_document = await get_requirement_document_by_id(db, proposal.requirement_document_id)
#     if requirement_document is None or not requirement_document.parsed_data:
#         raise HTTPException(
#             status_code=status.HTTP_409_CONFLICT,
#             detail="Requirement document has no extracted requirements to regenerate this section from",
#         )

#     definition = _SECTION_DEFINITIONS_BY_KEY.get(section.section_key)
#     if definition is None:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Unknown section key '{section.section_key}' — no section definition to regenerate from",
#         )

#     requirements = requirement_document.parsed_data
#     requirements_json = json.dumps(requirements, indent=2)
#     has_knowledge = await has_any_knowledge_chunks(db)

#     section_state = {
#         "key": definition["key"],
#         "title": definition["title"],
#         "query_fields": definition["query_fields"],
#         "drafting_note": definition.get("drafting_note"),
#         "retrieved_chunks": [],
#         "content": None,
#         "citations": [],
#         "status": "pending",
#         "retry_count": section.retry_count,
#         "feedback": None,
#         "confidence_score": None,
#         "review_flag": False,
#     }

#     section_state["retrieved_chunks"] = await retrieve_chunks_for_section(
#         section_state, requirements, proposal.category_ids, has_knowledge,
#     )

#     content, citations = draft_one_section(section_state, requirements_json)
#     section_state["content"] = content
#     section_state["citations"] = citations

#     result = run_quality_check(section_state, requirements_json)
#     # feedback is discarded here — it only exists to seed the *next* automated
#     # draft attempt's prompt, and a single regenerate pass has no next attempt.
#     new_status, _feedback, review_flag = decide_section_status(result, force_approve=False)
#     logger.info(
#         "section regenerated | section_id=%s status=%s review_flag=%s",
#         section_id, new_status, review_flag,
#     )

#     return await update_proposal_section(
#         db, section,
#         content=content,
#         citations=citations,
#         status=ProposalSectionStatus(new_status),
#         retry_count=section.retry_count + 1,
#         confidence_score=result.confidence_score,
#         review_flag=review_flag,
#     )
