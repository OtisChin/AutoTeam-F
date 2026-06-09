"""Small JWT claim helpers for unsigned local inspection."""

from __future__ import annotations

import base64
import json
from typing import Any

JWT_PAYLOAD_MAX_CHARS = 16 * 1024


def decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload_part = str(token or "").split(".")[1]
        if len(payload_part) > JWT_PAYLOAD_MAX_CHARS:
            return {}
        payload_part += "=" * (-len(payload_part) % 4)
        claims = json.loads(base64.b64decode(payload_part.encode("ascii"), altchars=b"-_", validate=True).decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}
