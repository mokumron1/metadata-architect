from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_PLACEHOLDERS = {"change-me", "changeme", "secret", "password", ""}

# Algorithms that must never be accepted for JWT verification.
# "none" allows unsigned tokens; RS*/ES* are asymmetric and incompatible
# with an HS256 secret — both can be exploited in algorithm-confusion attacks.
ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


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

    # CI/CD Gate auth — MUST be overridden via GATE_API_KEY env var in production
    gate_api_key: str = "change-me"

    # JWT — MUST be overridden via JWT_SECRET_KEY env var in production
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # CORS — set to a comma-separated list of allowed origins in production.
    # Example: ALLOWED_ORIGINS="https://portal.example.com,https://ci.example.com"
    # Leave empty to keep the default restrictive behaviour (no cross-origin requests).
    allowed_origins: str = ""

    # Portal
    portal_base_url: str = "http://localhost:8000"

    def validate_production_secrets(self) -> None:
        """
        Raise ValueError if critical secrets still hold placeholder values.
        Call this once at application startup (not in tests).
        """
        import os
        env = os.getenv("ENV", "production").lower()
        if env in {"development", "dev", "local", "test"}:
            return  # relaxed in non-production environments

        errors: list[str] = []
        if self.gate_api_key.lower() in _INSECURE_PLACEHOLDERS:
            errors.append("GATE_API_KEY must be set to a strong secret in production.")
        if self.jwt_secret_key.lower() in _INSECURE_PLACEHOLDERS:
            errors.append("JWT_SECRET_KEY must be set to a strong secret in production.")
        if len(self.jwt_secret_key) < 32:
            errors.append("JWT_SECRET_KEY must be at least 32 characters long.")
        if self.jwt_algorithm not in ALLOWED_JWT_ALGORITHMS:
            errors.append(
                f"JWT_ALGORITHM '{self.jwt_algorithm}' is not in the allowed set "
                f"{ALLOWED_JWT_ALGORITHMS}."
            )
        if errors:
            raise ValueError(
                "Insecure configuration detected:\n" + "\n".join(f"  - {e}" for e in errors)
            )

    def get_allowed_origins(self) -> list[str]:
        """Return the parsed CORS allowed-origins list."""
        if not self.allowed_origins:
            return []
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
