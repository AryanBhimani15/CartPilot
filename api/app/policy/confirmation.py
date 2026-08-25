from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.fingerprint import FingerprintItem, cart_fingerprint
from app.db.models import Cart, CartItem, ConfirmationToken

TOKEN_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class MintedConfirmation:
    token: str
    expires_at: datetime
    cart_fingerprint: str


@dataclass(frozen=True, slots=True)
class ConfirmationValidation:
    supplied: bool
    valid: bool
    cart_matches: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _encode_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_payload(encoded: str) -> dict[str, Any] | None:
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _signature(encoded_payload: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256
    ).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _cart_fingerprint(session: AsyncSession, cart: Cart) -> str:
    items = (await session.scalars(select(CartItem).where(CartItem.cart_id == cart.id))).all()
    return cart_fingerprint(
        [
            FingerprintItem(
                variant_id=item.variant_id,
                quantity=item.quantity,
                unit_price_paise=item.unit_price_paise,
            )
            for item in items
        ],
        cart.total_paise,
    )


async def mint_confirmation_token(
    session: AsyncSession,
    *,
    cart: Cart,
    action: str,
    secret: str,
    now: datetime | None = None,
) -> MintedConfirmation:
    """Mint a server-signed, cart-bound, single-use confirmation token."""
    issued_at = now or _now()
    expires_at = issued_at + TOKEN_TTL
    fingerprint = await _cart_fingerprint(session, cart)
    payload = {
        "action": action,
        "cart_fingerprint": fingerprint,
        "exp": int(expires_at.timestamp()),
        "nonce": secrets.token_urlsafe(16),
        "session_id": str(cart.session_id),
    }
    encoded = _encode_payload(payload)
    token = f"{encoded}.{_signature(encoded, secret)}"
    session.add(
        ConfirmationToken(
            session_id=cart.session_id,
            action=action,
            cart_fingerprint=fingerprint,
            token_hash=_token_hash(token),
            expires_at=expires_at,
            is_demo=cart.is_demo,
        )
    )
    await session.flush()
    return MintedConfirmation(token, expires_at, fingerprint)


async def validate_confirmation_token(
    session: AsyncSession,
    *,
    cart: Cart,
    action: str,
    token: str | None,
    secret: str,
    now: datetime | None = None,
) -> ConfirmationValidation:
    """Validate without consuming.

    Consumption happens in `policy.engine.execute_if_allowed`, atomically with the action,
    so validation and use cannot drift apart (D-008).
    """
    if not token:
        return ConfirmationValidation(False, False, True)
    issued_at = now or _now()
    encoded, separator, supplied_signature = token.partition(".")
    if not separator or not hmac.compare_digest(_signature(encoded, secret), supplied_signature):
        return ConfirmationValidation(True, False, True)
    payload = _decode_payload(encoded)
    if payload is None:
        return ConfirmationValidation(True, False, True)
    current_fingerprint = await _cart_fingerprint(session, cart)
    payload_fingerprint = payload.get("cart_fingerprint")
    cart_matches = payload_fingerprint == current_fingerprint
    if (
        payload.get("session_id") != str(cart.session_id)
        or payload.get("action") != action
        or not isinstance(payload.get("exp"), int)
        or payload["exp"] <= int(issued_at.timestamp())
        or not cart_matches
    ):
        return ConfirmationValidation(True, False, cart_matches)
    stored = await session.scalar(
        select(ConfirmationToken).where(
            ConfirmationToken.token_hash == _token_hash(token),
            ConfirmationToken.session_id == cart.session_id,
            ConfirmationToken.action == action,
            ConfirmationToken.used_at.is_(None),
        )
    )
    if (
        stored is None
        or stored.expires_at <= issued_at
        or stored.cart_fingerprint != current_fingerprint
    ):
        return ConfirmationValidation(True, False, cart_matches)
    return ConfirmationValidation(True, True, True)


async def consume_confirmation_token(
    session: AsyncSession,
    *,
    token: str,
    now: datetime | None = None,
) -> bool:
    """Mark a previously validated token used exactly once under a row lock."""
    token_row = await session.scalar(
        select(ConfirmationToken)
        .where(ConfirmationToken.token_hash == _token_hash(token))
        .with_for_update()
        # Defensive, by analogy with the oversell fixed in commerce/inventory.py: validate()
        # has already loaded this row, and we must not decide single-use from a pre-lock copy.
        # Unlike the inventory case this was NOT reproducible here -- an ablation with a
        # barrier forcing both requests to validate before either consumes passed either way.
        # Kept because reading locked rows fresh is the property we want to depend on.
        .execution_options(populate_existing=True)
    )
    issued_at = now or _now()
    if token_row is None or token_row.used_at is not None or token_row.expires_at <= issued_at:
        return False
    token_row.used_at = issued_at
    await session.flush()
    return True
