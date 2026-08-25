from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def settings_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "app_env": "development",
        "database_url": "postgresql+asyncpg:///cartpilot",
        "confirmation_token_secret": "test-confirmation-secret",
        "embedding_model": "deterministic-v1",
        "razorpay_key_id": "rzp_test_fake",
        "razorpay_key_secret": "fake-key-secret",
        "razorpay_webhook_secret": "fake-webhook-secret",
    }
    values.update(overrides)
    return values


def test_missing_razorpay_secret_fails_with_named_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(ValidationError, match="razorpay_key_secret"):
        Settings(_env_file=None, **settings_kwargs(razorpay_key_secret=None))


def test_test_environment_requires_a_distinct_test_database() -> None:
    with pytest.raises(ValidationError, match="TEST_DATABASE_URL must differ"):
        Settings(
            _env_file=None,
            **settings_kwargs(
                app_env="test",
                test_database_url="postgresql+asyncpg:///cartpilot",
            ),
        )
