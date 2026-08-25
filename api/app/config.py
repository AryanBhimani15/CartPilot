from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    database_url: str
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

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings resolves required fields from the environment at runtime.
    return Settings()  # type: ignore[call-arg]
