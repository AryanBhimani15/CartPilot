from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Cart
from app.db.session import get_db_session
from app.policy.confirmation import mint_confirmation_token

router = APIRouter(prefix="/api/v1/cart", tags=["cart"])


class ConfirmCartRequest(BaseModel):
    session_id: uuid.UUID
    action: Literal["create_razorpay_order", "place_order"]


class ConfirmCartResponse(BaseModel):
    token: str
    expires_at: str


@router.post("/confirm", response_model=ConfirmCartResponse, status_code=status.HTTP_201_CREATED)
async def confirm_cart(
    request: ConfirmCartRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ConfirmCartResponse:
    """Mint a cart-bound token only in response to an explicit user UI action."""
    cart = await session.scalar(select(Cart).where(Cart.session_id == request.session_id))
    if cart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")
    minted = await mint_confirmation_token(
        session,
        cart=cart,
        action=request.action,
        secret=get_settings().confirmation_token_secret,
    )
    await session.commit()
    return ConfirmCartResponse(token=minted.token, expires_at=minted.expires_at.isoformat())
