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
    DRAFT      = "draft"        
    GENERATING = "generating"   
    REVIEW     = "review"       
    APPROVED   = "approved"  