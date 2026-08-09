"""Local TOTP helpers for ChatGPT/OpenAI MFA flows."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import struct
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")


class TOTPSecretError(ValueError):
    """Raised when a TOTP secret or otpauth URI cannot be used safely."""


@dataclass(frozen=True)
class OTPAuthMetadata:
    secret: str
    issuer: str = ""
    label: str = ""
    account_name: str = ""
    algorithm: str = "SHA1"
    digits: int = 6
    period: int = 30
    uri: str = ""

    @property
    def masked_secret(self) -> str:
        return mask_totp_secret(self.secret)


def normalize_totp_secret(secret: str) -> str:
    normalized = re.sub(r"\s+", "", str(secret or "")).upper()
    if not normalized:
        raise TOTPSecretError("TOTP secret is required")
    if not _BASE32_RE.fullmatch(normalized):
        raise TOTPSecretError("TOTP secret contains invalid base32 characters")
    try:
        base64.b32decode(_pad_base32(normalized), casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise TOTPSecretError("TOTP secret is not valid base32") from exc
    return normalized.rstrip("=")


def parse_otpauth_uri(uri: str) -> OTPAuthMetadata:
    raw = str(uri or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "otpauth" or parsed.netloc != "totp":
        raise TOTPSecretError("otpauth URI must use otpauth://totp/")

    query = parse_qs(parsed.query)
    secret_values = query.get("secret") or []
    if not secret_values:
        raise TOTPSecretError("otpauth URI is missing secret")

    label = unquote((parsed.path or "").lstrip("/"))
    issuer = (query.get("issuer") or [""])[0]
    account_name = label.split(":", 1)[1] if ":" in label else label
    algorithm = (query.get("algorithm") or ["SHA1"])[0].upper()
    if algorithm != "SHA1":
        raise TOTPSecretError(f"unsupported TOTP algorithm: {algorithm}")

    digits = _parse_positive_int(query, "digits", default=6)
    period = _parse_positive_int(query, "period", default=30)
    if digits <= 0 or period <= 0:
        raise TOTPSecretError("TOTP digits and period must be positive")

    return OTPAuthMetadata(
        secret=normalize_totp_secret(secret_values[0]),
        issuer=issuer,
        label=label,
        account_name=account_name,
        algorithm=algorithm,
        digits=digits,
        period=period,
        uri=raw,
    )


def generate_totp(secret: str, *, for_time: int | float | None = None, period: int = 30, digits: int = 6) -> str:
    if period <= 0 or digits <= 0:
        raise TOTPSecretError("TOTP period and digits must be positive")
    normalized = normalize_totp_secret(secret)
    timestamp = time.time() if for_time is None else float(for_time)
    counter = int(timestamp // period)
    key = base64.b32decode(_pad_base32(normalized), casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**digits)).zfill(digits)


def generate_totp_candidates(
    secret: str,
    *,
    for_time: int | float | None = None,
    period: int = 30,
    digits: int = 6,
    window: int = 1,
) -> list[str]:
    if window < 0:
        raise TOTPSecretError("TOTP candidate window must be non-negative")
    timestamp = time.time() if for_time is None else float(for_time)
    candidates: list[str] = []
    for offset in range(-window, window + 1):
        candidates.append(generate_totp(secret, for_time=timestamp + offset * period, period=period, digits=digits))
    return candidates


def mask_totp_secret(secret: str, *, left: int = 4, right: int = 4) -> str:
    raw = normalize_totp_secret(secret)
    if len(raw) <= left + right:
        return f"{raw[:2]}…len={len(raw)}"
    return f"{raw[:left]}…{raw[-right:]}"


def _pad_base32(secret: str) -> str:
    return secret + "=" * ((8 - len(secret) % 8) % 8)


def _parse_positive_int(query: dict[str, list[str]], key: str, *, default: int) -> int:
    raw = (query.get(key) or [str(default)])[0]
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise TOTPSecretError(f"TOTP {key} must be an integer") from exc
