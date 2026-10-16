from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BONUS_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = Field(default=8050, ge=1, le=65535)
    database_url: SecretStr
