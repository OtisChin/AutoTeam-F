"""Shared payment error classification helpers."""

from __future__ import annotations

import re
from typing import Any


def is_non_zero_amount_error(error: Any) -> bool:
    text = str(error or "")
    lower = text.lower()
    if (
        "金额必须为 0" in text
        or "金额必须是 0" in text
        or "金额应为 0" in text
        or "金额不是 0" in text
        or "金额非 0" in text
        or "金额不为 0" in text
        or "amount must be 0" in lower
        or "amount must equal 0" in lower
        or "amount is not 0" in lower
        or "amount not 0" in lower
        or "non-zero amount" in lower
    ):
        return True
    return bool(
        re.search(r"\bamount\s*[=:]\s*(?!0(?:\D|$))\d+", lower)
        and ("amount policy failed" in lower or "金额校验" in text)
    )
