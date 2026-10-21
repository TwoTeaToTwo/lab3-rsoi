from urllib.parse import quote

from pydantic import Field, SecretStr
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
    circuit_breaker_n: int = Field(default=3, ge=0)
    circuit_breaker_recovery_timeout: float = Field(default=5, gt=0, allow_inf_nan=False)
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = Field(default=5672, ge=1, le=65535)
    rabbitmq_username: str = "gateway"
    rabbitmq_password: SecretStr = SecretStr("gateway")
    rabbitmq_timeout: float = Field(default=5, gt=0, allow_inf_nan=False)
    refund_queue: str = Field(default="gateway.bonus-refunds", min_length=1)
    refund_error_queue: str = Field(default="gateway.bonus-refunds.errors", min_length=1)
    refund_retry_interval: float = Field(default=10, gt=0, allow_inf_nan=False)

    @property
    def rabbitmq_url(self) -> str:
        username = quote(self.rabbitmq_username, safe="")
        password = quote(self.rabbitmq_password.get_secret_value(), safe="")
        return f"amqp://{username}:{password}@{self.rabbitmq_host}:{self.rabbitmq_port}/"
