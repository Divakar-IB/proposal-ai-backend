from typing import Optional

from pydantic import BaseModel, Field


class QualityCheckResult(BaseModel):
    approved: bool = Field(description="True if the section is client-ready as-is")
    feedback: Optional[str] = Field(
        default=None, description="What to fix, if not approved — specific and actionable"
    )
    confidence_score: float = Field(
        description="How client-ready this section is as drafted (1 = fully client-ready, 0 = not usable)"
    )
