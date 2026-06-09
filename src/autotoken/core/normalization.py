"""Small normalization helpers shared across account and API code."""

from typing import Any


def normalized_email(value: Any) -> str:
    return str(value or "").strip().lower()
