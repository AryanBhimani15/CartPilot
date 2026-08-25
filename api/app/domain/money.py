from __future__ import annotations

from typing import NewType

Paise = NewType("Paise", int)


def paise(value: int) -> Paise:
    if not isinstance(value, int):
        raise TypeError("Money must be represented as an integer paise value")
    if value < 0:
        raise ValueError("Money cannot be negative")
    return Paise(value)


def add(*values: Paise) -> Paise:
    return Paise(sum(values))
