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