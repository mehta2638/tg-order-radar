from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TG Order Radar"
    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    postgres_db: str = "tg_order_radar"
    postgres_user: str = "tg_order_radar"
    postgres_password: str = Field(default="change-me", repr=False)
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_max_retries: int = 3
    collector_batch_limit: int = 500
    collector_backfill_days: int = 7
    collector_backfill_buffer_days: int = 1
    collector_lease_ttl_seconds: int = 600
    collector_poll_interval_seconds: int = 60

    tg_api_id: int | None = Field(default=None, repr=False)
    tg_api_hash: str | None = Field(default=None, repr=False)
    tg_phone: str | None = Field(default=None, repr=False)
    tg_session_dir: str = ".telegram-sessions"
    tg_session_name: str = "collector"

    @property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def alembic_database_url(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
