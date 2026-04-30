from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Incident Management System"
    environment: str = "production"
    postgres_dsn: str = "postgresql+asyncpg://ims:ims_password@postgres:5432/ims"
    mongo_dsn: str = "mongodb://mongo:27017"
    mongo_db: str = "ims"
    redis_url: str = "redis://redis:6379/0"
    queue_max_size: int = 10000
    rate_limit: str = "500/second"
    jwt_secret: str = "change-me-in-production"
    cors_origins: str = "http://localhost:3000,http://frontend:3000"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
