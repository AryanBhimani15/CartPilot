from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class Allow:
    decision: Literal["allow"] = "allow"


@dataclass(frozen=True, slots=True)
class Deny:
    rule_id: str
    code: str
    message: str
    remediation: str
    decision: Literal["deny"] = "deny"


@dataclass(frozen=True, slots=True)
class RequireConfirmation:
    rule_id: str
    prompt: str
    decision: Literal["require_confirmation"] = "require_confirmation"


PolicyResult: TypeAlias = Allow | Deny | RequireConfirmation


def decision_payload(result: PolicyResult) -> dict[str, str]:
    if isinstance(result, Allow):
        return {"decision": result.decision}
    if isinstance(result, Deny):
        return {
            "decision": result.decision,
            "rule_id": result.rule_id,
            "code": result.code,
            "message": result.message,
            "remediation": result.remediation,
        }
    return {"decision": result.decision, "rule_id": result.rule_id, "prompt": result.prompt}
