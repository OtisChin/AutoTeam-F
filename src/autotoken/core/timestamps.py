"""Timestamp normalization helpers shared by auth conversion code."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def normalized_utc_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return normalized_utc_timestamp(float(text))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        except Exception:
            return ""
    return ""


def epoch_seconds(value: Any) -> int:
    normalized = normalized_utc_timestamp(value)
    if not normalized:
        return 0
    try:
        return int(datetime.fromisoformat(normalized.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0
