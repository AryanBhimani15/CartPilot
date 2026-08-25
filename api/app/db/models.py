from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import (
    EventType,
    OfferType,
    OrderStatus,
    PaymentStatus,
    PolicyDecision,
    SessionOutcome,
    VariantAxis,
)


def native_enum(
    enum_class: type[
        EventType
        | OfferType
        | OrderStatus
        | PaymentStatus
        | PolicyDecision
        | SessionOutcome
        | VariantAxis
    ],
) -> SqlEnum:
    enum_names = {
        EventType: "event_type",
        OfferType: "offer_type",
        OrderStatus: "order_status",
        PaymentStatus: "payment_status",
        PolicyDecision: "policy_decision",
        SessionOutcome: "session_outcome",
        VariantAxis: "variant_axis",
    }
    return SqlEnum(
        enum_class,
        name=enum_names[enum_class],
        values_callable=lambda values: [member.value for member in values],
    )


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class DemoMixin:
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Merchant(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "merchants"

    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    max_cart_value_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=2_000_000)


class Product(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_merchant_category", "merchant_id", "category"),
        Index("ix_products_price_paise", "price_paise"),
        Index("ix_products_search_tsv_gin", "search_tsv", postgresql_using="gin"),
        Index("ix_products_attrs_gin", "attrs", postgresql_using="gin"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    subcategory: Mapped[str] = mapped_column(String(80), nullable=False)
    price_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    search_tsv: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)


class ProductVariant(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "product_variants"
    __table_args__ = (
        Index("ix_product_variants_product_size", "product_id", "size"),
        Index("uq_product_variants_product_size", "product_id", "size", unique=True),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    axis: Mapped[VariantAxis] = mapped_column(native_enum(VariantAxis), nullable=False)
    size: Mapped[str] = mapped_column(String(20), nullable=False)
    colour: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProductEmbedding(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "product_embeddings"
    __table_args__ = (
        Index("uq_product_embedding_content", "product_id", "model", "content_hash", unique=True),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(ARRAY(REAL), nullable=False)


class Offer(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "offers"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    offer_type: Mapped[OfferType] = mapped_column(native_enum(OfferType), nullable=False)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    min_cart_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    max_discount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    applicable_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Session(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "sessions"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    outcome: Mapped[SessionOutcome] = mapped_column(
        native_enum(SessionOutcome), nullable=False, default=SessionOutcome.ACTIVE
    )
    budget_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Message(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)


class AgentStep(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "agent_steps"
    __table_args__ = (Index("uq_agent_steps_session_step", "session_id", "step_no", unique=True),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy_rule_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_decision: Mapped[PolicyDecision] = mapped_column(
        native_enum(PolicyDecision), nullable=False
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Cart(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "carts"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), unique=True, nullable=False
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id"), nullable=True
    )
    subtotal_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    discount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class CartItem(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "cart_items"
    __table_args__ = (Index("uq_cart_items_cart_variant", "cart_id", "variant_id", unique=True),)

    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ConfirmationToken(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "confirmation_tokens"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    cart_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Order(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "orders"

    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(native_enum(OrderStatus), nullable=False)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    cart_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class Payment(Base, IdMixin, DemoMixin, TimestampMixin):
    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    razorpay_payment_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(native_enum(PaymentStatus), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class SessionEvent(Base, IdMixin, DemoMixin):
    __tablename__ = "session_events"
    __table_args__ = (Index("ix_session_events_session_created", "session_id", "created_at"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(native_enum(EventType), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvalRun(Base, IdMixin, TimestampMixin):
    __tablename__ = "eval_runs"

    simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    catalog_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    git_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class EvalSession(Base, IdMixin, TimestampMixin):
    __tablename__ = "eval_sessions"

    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False
    )
    arm: Mapped[str] = mapped_column(String(80), nullable=False)
    persona_id: Mapped[str] = mapped_column(String(80), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
