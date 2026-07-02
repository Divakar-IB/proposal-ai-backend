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

class AppConfig(BaseSettings):
    database: DatabaseConfig
    jwt: JWTConfig
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