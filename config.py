import os
import json
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings
from typing import List, Any

from dotenv import load_dotenv

load_dotenv()

class DatabaseConfig(BaseModel):
    username: str
    password: str
    host: str
    port: int
    db_name: str
    pool_size: int
    max_overflow: int
    pool_recycle: int
    pool_timeout: int


class JWTConfig(BaseModel):
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    issuer: str = "proposal-ai"

<<<<<<< Updated upstream
class AppConfig(BaseSettings):
    database: DatabaseConfig
    jwt: JWTConfig
=======
class AWSConfig(BaseModel):
    access_key_id: str
    secret_access_key: str
    region: str
    bucket_name: str

class PineconeConfig(BaseModel):
    api_key: str
    index_name: str
    dimension: int = 1024  # BGE-M3 embedding size
    metric: str = "cosine"
    cloud: str = "aws"
    region: str = "us-east-1"

class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0

class OCRConfig(BaseModel):
    # Rasterization DPI used when rendering a scanned PDF page to an image for OCR.
    dpi: int = 200
    # A PDF page with fewer native characters than this is treated as scanned.
    min_native_text_chars: int = 40
    # A PDF page whose embedded images cover more than this fraction of the
    # page area is treated as scanned even if a thin text layer is present.
    image_coverage_threshold: float = 0.6
    # Upper bound on a single PPStructureV3 predict() call (covers a whole batch).
    page_timeout_seconds: int = 120
    # Max number of page images sent to PPStructureV3 in one predict() call.
    batch_size: int = 8
    # PPStructureV3's own document-preprocessing sub-pipeline.
    use_doc_orientation_classify: bool = True
    use_doc_unwarping: bool = True

class AppConfig(BaseSettings):
    database: DatabaseConfig
    jwt: JWTConfig
    aws: AWSConfig
    pinecone: PineconeConfig
    redis: RedisConfig = RedisConfig()
    ocr: OCRConfig = OCRConfig()
>>>>>>> Stashed changes
    debug: bool = False
    allowed_origins: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def load_from_config_env(cls, data: Any) -> Any:
        if not data or (isinstance(data, dict) and not data):
            raw_config = os.environ.get("CONFIG")
            if not raw_config:
                raise RuntimeError(
                    '''CONFIG environment variable is required 
                    and must be a valid JSON string.''')
            try:
                data = json.loads(raw_config)
            except Exception as e:
                raise RuntimeError(f"Failed to parse CONFIG env variable as JSON: {e}")
        return data

    class Config:
        env_file = None
        arbitrary_types_allowed = True 

config = AppConfig()