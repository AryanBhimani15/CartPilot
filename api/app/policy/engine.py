from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentStep, Session
from app.domain.enums import PolicyDecision
from app.policy.confirmation import consume_confirmation_token
from app.policy.decisions import Allow, Deny, PolicyResult, RequireConfirmation, decision_payload
from app.policy.rules import PAYMENT_TOOLS, RULES, PolicyContext

T = TypeVar("T")


def pre_tool(context: PolicyContext) -> PolicyResult:
    """Run deterministic preconditions in a stable, audit-friendly order."""
    for rule in RULES:
        result = rule(context)
        if not isinstance(result, Allow):
            return result
    return Allow()


def post_tool(context: PolicyContext) -> PolicyResult:
    """Re-evaluate facts after a write so a changed total cannot bypass policy."""
    return pre_tool(context)


# Explicit aliases preserve the readable names used in policy tests and in the T-007 tool adapter.
evaluate_pre_tool = pre_tool
evaluate_post_tool = post_tool


async def execute_if_allowed(
    context: PolicyContext,
    action: Callable[[], Awaitable[T]],
    *,
    session: AsyncSession | None = None,
    confirmation_token: str | None = None,
) -> tuple[PolicyResult, T | None]:
    """Prevent a denied tool from reaching its payment or commerce side effect.

    For payment tools the gate **consumes** the confirmation token itself, in the same
    transaction as the action. Validation alone is not single use: leaving consumption to
    downstream payment code means one confirmation can authorise an unbounded number of
    executions, which is the precise property D-008 exists to prevent. Doing it here also
    closes the validate-then-act window, and makes it impossible for T-007 or T-009 to
    forget. A payment tool reaching this gate without a consumable token is denied.
    """
    decision = pre_tool(context)
    if not isinstance(decision, Allow):
        return decision, None
    if context.tool_name in PAYMENT_TOOLS:
        if session is None or not confirmation_token:
            return _confirmation_denied("The payment confirmation was never presented."), None
        if not await consume_confirmation_token(session, token=confirmation_token):
            return _confirmation_denied(
                "The payment confirmation is invalid, expired, or already used."
            ), None
    return decision, await action()


def _confirmation_denied(message: str) -> Deny:
    return Deny(
        "CONFIRM_BEFORE_PAY",
        "CONFIRMATION_INVALID",
        message,
        "Review the cart and confirm it again.",
    )


def _policy_decision(result: PolicyResult) -> PolicyDecision:
    if isinstance(result, Allow):
        return PolicyDecision.ALLOW
    if isinstance(result, Deny):
        return PolicyDecision.DENY
    if isinstance(result, RequireConfirmation):
        return PolicyDecision.REQUIRE_CONFIRMATION
    raise AssertionError("Unknown policy result")


@dataclass(frozen=True, slots=True)
class PolicyAudit:
    session_id: uuid.UUID
    step_no: int
    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any]
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


async def persist_decision(
    session: AsyncSession, audit: PolicyAudit, decision: PolicyResult
) -> AgentStep:
    """Persist a decision before an agent can observe or act on it.

    T-007 can call this for both pre/post checks using the same step number; the row is updated
    rather than duplicated, preserving the schema's one-step-per-agent-iteration invariant.
    """
    commerce_session = await session.scalar(select(Session).where(Session.id == audit.session_id))
    if commerce_session is None:
        raise ValueError("Cannot audit policy for a missing session")
    existing = await session.scalar(
        select(AgentStep)
        .where(AgentStep.session_id == audit.session_id, AgentStep.step_no == audit.step_no)
        .with_for_update()
    )
    policy_rule_id = decision.rule_id if not isinstance(decision, Allow) else None
    payload = {**audit.result, "policy": decision_payload(decision)}
    if existing is None:
        existing = AgentStep(
            session_id=audit.session_id,
            step_no=audit.step_no,
            tool_name=audit.tool_name,
            args=audit.args,
            result=payload,
            policy_rule_id=policy_rule_id,
            policy_decision=_policy_decision(decision),
            latency_ms=audit.latency_ms,
            input_tokens=audit.input_tokens,
            output_tokens=audit.output_tokens,
            error_code=decision.code if isinstance(decision, Deny) else None,
            is_demo=commerce_session.is_demo,
        )
        session.add(existing)
    else:
        existing.result = payload
        existing.policy_rule_id = policy_rule_id
        existing.policy_decision = _policy_decision(decision)
        existing.error_code = decision.code if isinstance(decision, Deny) else None
    await session.flush()
    return existing
