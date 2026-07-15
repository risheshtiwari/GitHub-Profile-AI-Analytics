from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60

    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/analyzer"

    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 3600

    github_token: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    max_repos_analyzed: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
