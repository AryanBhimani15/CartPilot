from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_missing_razorpay_secret_fails_with_named_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(ValidationError, match="razorpay_key_secret"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg:///cartpilot",
            confirmation_token_secret="test-confirmation-secret",
            embedding_model="deterministic-v1",
            razorpay_key_id="rzp_test_fake",
            razorpay_webhook_secret="fake-webhook-secret",
        )
