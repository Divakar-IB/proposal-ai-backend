from enum import Enum

class UserRole(str, Enum):
    ADMIN = "org_admin"
    USER = "member"

class IngestionStatus(str, Enum):
    PENDING    = "pending"     
    PROCESSING = "processing"   
    INDEXED    = "indexed"    
    FAILED     = "failed"   

class DocumentStatus(str,Enum):
    UPLOADING = "uploading"
    EXTRACTING = "extracting"   
    PARSED     = "parsed" 
    FAILED = "failed"


class ProposalStatus(str, Enum):
    INPROGRESS = "inprogress"
    GENERATING = "generating"
    REVIEW     = "review"
    DONE       = "done"
    FAILED     = "failed"


class ProposalSectionStatus(str, Enum):
    PENDING        = "pending"
    DRAFTING       = "drafting"
    DRAFTED        = "drafted"
    NEEDS_REVISION = "needs_revision"
    APPROVED       = "approved"


class GenerationMode(str, Enum):
    LLM_ONLY = "llm_only"
    KNOWLEDGE_AUGMENTED = "knowledge_augmented"


class DocumentAvailability(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SectionContentFormat(str, Enum):
    """How ProposalSection.content/structured_content should be read. Most
    sections are MARKDOWN (content is the authoritative source); a few
    (pricing, milestones) are STRUCTURED (structured_content is
    authoritative, content is a rendered Markdown fallback for consumers
    that only read plain text, e.g. knowledge-ingestion chunking)."""

    MARKDOWN = "markdown"
    STRUCTURED = "structured"


class KnowledgeSourceType(str, Enum):
    """Where a KnowledgeDocument's content originated from."""

    UPLOAD = "upload"
    PROPOSAL = "proposal"