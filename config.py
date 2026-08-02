import os
import json
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings
from typing import Any, List, Literal, Optional

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

class GroqConfig(BaseModel):
    api_key: str
    base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"

class HFInferenceConfig(BaseModel):
    api_token: str
    embedding_model: str
    hf_base_api_url: str

    @property
    def embedding_api_url(self) -> str:

        return (
            f"{self.hf_base_api_url.rstrip('/')}/"
            f"{self.embedding_model}/pipeline/feature-extraction"
        )

class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0

class SMTPConfig(BaseModel):
    host: str = "smtp.gmail.com"
    port: int = 587
    username: str
    password: str
    from_email: str
    use_tls: bool = True

    # How mail actually leaves the process.
    #
    #   "smtp"  – classic smtplib over port 587. Works locally, but many hosts
    #             (Render among them) block outbound SMTP entirely; there the
    #             connect fails immediately with
    #             "OSError: [Errno 101] Network is unreachable".
    #   others  – the provider's HTTPS REST API, which goes out over 443 and is
    #             therefore not blocked. Set `api_key` when using one of these.
    #
    # `from_email` is reused as the sender for every provider. For a real
    # provider the sending domain usually has to be verified with them first.
    provider: Literal["smtp", "resend", "brevo", "sendgrid"] = "smtp"
    api_key: Optional[str] = None
    from_name: Optional[str] = None

    @model_validator(mode="after")
    def check_api_key_present(self) -> "SMTPConfig":
        if self.provider != "smtp" and not self.api_key:
            raise ValueError(f"smtp.api_key is required when smtp.provider is '{self.provider}'")
        return self

class AppConfig(BaseSettings):
    database: DatabaseConfig
    jwt: JWTConfig
    aws: AWSConfig
    pinecone: PineconeConfig
    groq: GroqConfig
    hf_inference: HFInferenceConfig
    redis: RedisConfig = RedisConfig()
    smtp: SMTPConfig
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