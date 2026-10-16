from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    flight_url: str = "http://localhost:8060"
    ticket_url: str = "http://localhost:8070"
    bonus_url: str = "http://localhost:8050"
    connect_timeout: float = Field(default=2, gt=0)
    read_timeout: float = Field(default=5, gt=0)
    write_timeout: float = Field(default=5, gt=0)
    pool_timeout: float = Field(default=2, gt=0)
    retries: int = Field(default=2, ge=0, le=5)
