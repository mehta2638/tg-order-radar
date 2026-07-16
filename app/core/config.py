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
    collector_account_lease_ttl_seconds: int = 120
    collector_max_requests_per_minute: int = 20
    collector_poll_interval_seconds: int = 60
    messages_retention_days: int = 90
    messages_partition_months_ahead: int = 2
    messages_partition_months_behind: int = 1
    dictionary_cache_ttl_seconds: int = 300
    processing_fuzzy_enabled: bool = True
    classification_manual_review_min_confidence: float = 0.4
    classification_manual_review_max_confidence: float = 0.6
    classification_order_min_confidence: float = 0.6
    ml_classification_enabled: bool = False
    ml_model_artifact_path: str = "artifacts/ml/classifier.joblib"
    ml_min_confidence: float = 0.7
    ml_model_version: str | None = None
    semantic_dedup_enabled: bool = False
    semantic_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    semantic_model_version: str = "paraphrase-multilingual-MiniLM-L12-v2"
    semantic_embedding_dimension: int = 384
    semantic_similarity_threshold: float = 0.9
    semantic_review_threshold: float = 0.82
    semantic_dedup_window_days: int = 7
    semantic_batch_size: int = 32
    semantic_device: str | None = None
    order_min_relevance_score: int = 60
    relevance_freshness_days: int = 7
    relevance_weight_need: float = 0.18
    relevance_weight_task: float = 0.16
    relevance_weight_budget: float = 0.14
    relevance_weight_deadline: float = 0.08
    relevance_weight_contact: float = 0.10
    relevance_weight_niche: float = 0.14
    relevance_weight_freshness: float = 0.08
    relevance_weight_p_client: float = 0.12
    relevance_weight_ad_penalty: float = 0.10
    relevance_weight_spam_penalty: float = 0.10
    api_key_admin: str = Field(default="dev-admin-key", repr=False)
    api_key_operator: str = Field(default="dev-operator-key", repr=False)
    api_key_viewer: str = Field(default="dev-viewer-key", repr=False)
    bot_token: str | None = Field(default=None, repr=False)
    bot_allowed_user_ids: str = ""
    bot_rate_limit_seconds: float = 0.2
    bot_send_max_retries: int = 3

    app_version: str = "0.1.0"
    prometheus_enabled: bool = True
    sentry_dsn: str | None = Field(default=None, repr=False)
    sentry_traces_sample_rate: float = 0.0

    tg_api_id: int | None = Field(default=None, repr=False)
    tg_api_hash: str | None = Field(default=None, repr=False)
    tg_phone: str | None = Field(default=None, repr=False)
    tg_session_dir: str = ".telegram-sessions"
    tg_session_name: str = "collector"
    # Comma-separated session file names for multi-account load distribution.
    # Empty => single account from tg_session_name. Never used to bypass FloodWait.
    tg_session_names: str = ""

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

    @property
    def parsed_bot_allowed_user_ids(self) -> set[int]:
        return {
            int(user_id.strip())
            for user_id in self.bot_allowed_user_ids.split(",")
            if user_id.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
