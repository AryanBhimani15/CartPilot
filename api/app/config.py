from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    database_url: str
    test_database_url: str | None = None
    confirmation_token_secret: str
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    anthropic_api_key: str | None = None
    embedding_provider: str = "deterministic"
    embedding_model: str
    embedding_api_key: str | None = None
    eval_use_real_embeddings: bool = False
    vector_backend: str = "numpy"
    razorpay_key_id: str
    razorpay_key_secret: str
    razorpay_webhook_secret: str
    razorpay_reconcile_poll_seconds: int = 5

    @model_validator(mode="after")
    def require_test_database_url(self) -> Settings:
        if self.app_env == "test" and not self.test_database_url:
            raise ValueError("TEST_DATABASE_URL is required when APP_ENV=test")
        if self.app_env == "test" and self.test_database_url == self.database_url:
            raise ValueError("TEST_DATABASE_URL must differ from DATABASE_URL")
        return self

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_database_url(self) -> str:
        if self.app_env == "test":
            assert self.test_database_url is not None
            return self.test_database_url
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings resolves required fields from the environment at runtime.
    return Settings()  # type: ignore[call-arg]
