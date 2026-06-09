"""Safe log summaries for sensitive runtime values."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from autotoken.settings.config import normalize_proxy_url


def mask_log_value(value: Any, *, left: int = 6, right: int = 4) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= left + right:
        return f"{raw[:2]}***len={len(raw)}"
    return f"{raw[:left]}...{raw[-right:]}(len={len(raw)})"


def compact_log_text(text: Any, *, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def safe_url_summary(url: Any) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except Exception:
        return mask_log_value(raw)

    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        host = f"{host}:{port}"
    safe_path_segments = []
    for segment in (parsed.path or "/").split("/"):
        if re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            segment,
            re.IGNORECASE,
        ):
            safe_path_segments.append(mask_log_value(segment))
        elif re.match(r"^(cs|pm|pi|seti|tok|src|snap)_[A-Za-z0-9_=-]{12,}$", segment):
            safe_path_segments.append(mask_log_value(segment))
        elif len(segment) >= 40 and re.fullmatch(r"[A-Za-z0-9_.=-]+", segment):
            safe_path_segments.append(mask_log_value(segment))
        else:
            safe_path_segments.append(segment)
    safe_path = "/".join(safe_path_segments) or "/"
    parts = [f"host={host}", f"path={safe_path}"]
    query_parts = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in {"reference", "checkout_session_id", "session_id", "snap_token", "token", "client_secret"}:
            query_parts.append(f"{key}={mask_log_value(value)}")
        elif key_lower in {"target", "locale", "payment_type"}:
            query_parts.append(f"{key}={value}")
        else:
            query_parts.append(f"{key}=<redacted>")
    if query_parts:
        parts.append(f"query={','.join(query_parts)}")
    return " ".join(parts)


def safe_proxy_summary(proxy_url: str | None) -> str:
    raw = str(proxy_url or "").strip()
    if not raw:
        return "disabled"
    try:
        normalized = normalize_proxy_url(raw)
        parsed = urlsplit(normalized)
        username = unquote(parsed.username or "")
        fields = [
            "enabled",
            f"scheme={parsed.scheme}",
            f"host={parsed.hostname or ''}",
            f"port={parsed.port or ''}",
            f"username={mask_log_value(username, left=8, right=4) if username else '<none>'}",
            f"password_present={bool(parsed.password)}",
        ]
        return " ".join(fields)
    except Exception as exc:
        return f"invalid error={exc}"


def safe_email_summary(email: Any) -> str:
    raw = str(email or "").strip()
    if "@" not in raw:
        return mask_log_value(raw, left=3, right=2)
    local, domain = raw.split("@", 1)
    return f"{mask_log_value(local, left=3, right=2)}@{domain}"


def safe_phone_summary(phone_number: Any, country_code: str = "") -> str:
    digits = re.sub(r"\D+", "", str(phone_number or ""))
    prefix = re.sub(r"\D+", "", str(country_code or ""))
    if not digits:
        return f"country_code={prefix or '<auto>'} phone=<empty>"
    return f"country_code={prefix or '<auto>'} phone=***{digits[-4:]}(len={len(digits)})"


def safe_otp_summary(otp: Any) -> str:
    digits = re.sub(r"\D+", "", str(otp or ""))
    if not digits:
        return "<empty>"
    if len(digits) <= 4:
        return f"{digits[:1]}***len={len(digits)}"
    return f"{digits[:2]}***{digits[-2:]}(len={len(digits)})"


def safe_error_summary(error: Any, *, limit: int = 240) -> str:
    text = compact_log_text(error, limit=limit)
    text = re.sub(r"://[^@\s]+@", "://<auth>@", text)
    text = re.sub(r"([?&](?:token|access_token|session_token|client_secret|otp|pin)=)[^&\s]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._=-]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    return text
