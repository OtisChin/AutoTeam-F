"""Small normalization helpers shared across account and API code."""

import json
import re
from typing import Any


def normalized_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_access_token(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("{") and "accessToken" in raw:
        try:
            parsed = json.loads(raw)
            token = parsed.get("accessToken") if isinstance(parsed, dict) else ""
            if token:
                raw = str(token).strip()
        except Exception:
            pass
    raw = re.sub(r"^Bearer\s+", "", raw, flags=re.IGNORECASE).strip()
    return re.sub(r"^[\"']+|[\"',;\s]+$", "", raw).strip()
