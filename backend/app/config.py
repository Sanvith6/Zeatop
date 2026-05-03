from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized configuration — all runtime settings in one place.

    WHY pydantic-settings:
    Reads from environment variables with type validation, so Docker Compose
    environment blocks and .env files both work without manual parsing.
    Every threshold is configurable without code changes — operators can tune
    circuit breaker sensitivity, queue limits, and rate limits at deploy time.
    """
    app_name: str = "Incident Management System"
    environment: str = "production"
    postgres_dsn: str = "postgresql+asyncpg://ims:ims_password@postgres:5432/ims"
    mongo_dsn: str = "mongodb://mongo:27017"
    mongo_db: str = "ims"
    redis_url: str = "redis://redis:6379/0"
    queue_max_size: int = 10000
    redis_signal_queue: str = "signals:queue"
    redis_processing_queue: str = "signals:processing"
    worker_concurrency: int = 4
    rate_limit: str = "10000/second"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    demo_username: str = "sre-intern"
    demo_password: str = "zeotap-local"
    cors_origins: str = "http://localhost:3000,http://frontend:3000"

    # Circuit breaker settings — tune based on dependency SLAs
    cb_failure_threshold: int = 5
    cb_recovery_timeout: float = 30.0
    cb_half_open_max_calls: int = 2

    # Database call timeout in seconds — prevents hanging connections
    db_call_timeout: float = 5.0

    # Backpressure warning thresholds (as fraction of queue_max_size)
    queue_warn_threshold: float = 0.5   # log warning at 50%
    queue_critical_threshold: float = 0.8  # log critical at 80%

    # Adaptive throttling threshold (fraction of queue_max_size)
    adaptive_throttle_threshold: float = 0.7  # start throttling at 70%

    # Worker batch settings
    worker_batch_size: int = 500
    worker_batch_timeout: float = 1.0  # flush every 1 second regardless of size

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
