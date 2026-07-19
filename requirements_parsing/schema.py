from typing import Optional

from pydantic import BaseModel, Field


class RequirementsSchema(BaseModel):
    """Structured requirements extracted from an RFP/requirement document.
    Becomes the query input for retrieval in the proposal generation flow."""

    project_title: str = Field(description="The name/title of the project being requested")
    scope: str = Field(description="Summary of what work is in and out of scope")
    deliverables: list[str] = Field(default_factory=list, description="Concrete deliverables expected")
    budget_range: Optional[str] = Field(default=None, description="Stated or implied budget range, if any")
    timeline: Optional[str] = Field(default=None, description="Expected duration or key milestone dates")
    technical_requirements: list[str] = Field(
        default_factory=list, description="Technology, platform, or technical constraints called for"
    )
    evaluation_criteria: list[str] = Field(
        default_factory=list, description="How proposals will be scored/evaluated"
    )
    constraints: list[str] = Field(
        default_factory=list, description="Compliance, legal, security, or other hard constraints"
    )
