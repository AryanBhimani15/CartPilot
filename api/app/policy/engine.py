from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentStep, Session
from app.domain.enums import PolicyDecision
from app.policy.decisions import Allow, Deny, PolicyResult, RequireConfirmation, decision_payload
from app.policy.rules import RULES, PolicyContext

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
    context: PolicyContext, action: Callable[[], Awaitable[T]]
) -> tuple[PolicyResult, T | None]:
    """Prevent a denied tool from reaching its payment or commerce side effect.

    T-009 will pass its Razorpay action through this gate. Keeping it here makes the safety
    boundary executable and directly testable before a payment client exists.
    """
    decision = pre_tool(context)
    if not isinstance(decision, Allow):
        return decision, None
    return decision, await action()


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
