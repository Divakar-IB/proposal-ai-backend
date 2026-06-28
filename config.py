import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    envi: str = "DEV"
    config: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()

assert settings.config, "config_environment_variable_missing"

config = json.loads(settings.config)