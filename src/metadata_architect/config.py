from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database — defaults to a local SQLite file so the app runs with no infrastructure
    database_url: str = "sqlite+aiosqlite:///./metadata_architect.db"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Anthropic
    anthropic_api_key: str = ""
    soi_draft_model: str = "claude-sonnet-4-6"
    soi_escalation_model: str = "claude-opus-4-7"
    tdk_confidence_escalation_threshold: float = 0.65

    # MinIO / S3
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "metadata"
    minio_secret_key: str = "metadata123"
    minio_bucket_ddl: str = "ddl-inputs"
    minio_bucket_policy: str = "policy-outputs"
    minio_bucket_edits: str = "sme-edits"
    minio_secure: bool = False

    # SME Workflow
    sme_sla_hours: int = 48
    tdk_sla_breach_penalty: float = 0.40

    # Notifications
    sendgrid_api_key: str = ""
    slack_bot_token: str = ""
    slack_governance_channel: str = "#data-governance"

    # CI/CD Gate auth
    gate_api_key: str = "change-me"

    # JWT
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # Portal
    portal_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
