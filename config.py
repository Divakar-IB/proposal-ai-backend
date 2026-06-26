import json

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    envi: str = "DEV"
    config: str = ""

    class Config:
        env_file = ".env"


settings = Settings()

assert settings.config, "config_environment_variable_missing"

config = json.loads(settings.config)