from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolError(Exception):
    code: str
    message: str
    remediation: str

    def __str__(self) -> str:
        return self.message


class NotFoundError(ToolError):
    pass


class ValidationError(ToolError):
    pass
