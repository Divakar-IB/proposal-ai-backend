from pydantic import BaseModel, Field


class CapabilityTag(BaseModel):
    name: str = Field(description="Capability/category name, chosen from the provided list")
    confidence: float = Field(ge=0, le=1, description="Confidence that this capability applies, 0-1")


class CapabilityClassification(BaseModel):
    """LLM-determined capability tags for an RFP, used to scope knowledge-base
    retrieval during proposal generation without requiring manual category selection."""

    tags: list[CapabilityTag] = Field(default_factory=list)
