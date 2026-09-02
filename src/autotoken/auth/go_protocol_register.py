"""Dedicated bridge for the independent Go protocol registration mode."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from autotoken.integrations.go_protocol_register_client import (
    GoProtocolRegisterClient,
    go_response_to_protocol_result,
)


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def _mail_payload(
    mail_client,
    *,
    email: str,
    account_id: str | int | None = None,
) -> dict[str, Any]:
    target = str(email or "").strip()
    payload = {
        "provider": str(getattr(mail_client, "provider_name", "") or "").strip().lower(),
        "account_id": str(account_id or target),
        "receive_code_url": "",
        "issued_after_unix": int(time.time()),
    }
    for account in getattr(mail_client, "accounts", []) or []:
        if str(getattr(account, "email", "") or "").strip().lower() != target.lower():
            continue
        payload["receive_code_url"] = str(getattr(account, "receive_code_url", "") or "").strip()
        break
    return payload


def register_once(
    mail_client,
    *,
    email: str,
    password: str,
    account_id: str | int | None = None,
    proxy: str | None = None,
    fingerprint_profile: str | None = None,
) -> tuple[bool, dict]:
    provider_name = str(getattr(mail_client, "provider_name", "") or "").strip().lower()
    default_timeout = "120" if provider_name == "icloud" else "60"
    timeout_seconds = max(30, int(os.environ.get("OTP_TIMEOUT", default_timeout) or default_timeout))
    client = GoProtocolRegisterClient(timeout=max(90.0, float(timeout_seconds + 30)))
    client.health()
    options = {
        "timeout_seconds": timeout_seconds,
        "trace": _env_flag("GO_PROTOCOL_TRACE", "0"),
    }
    profile = str(fingerprint_profile or "").strip()
    if profile:
        options["impersonate"] = profile
    response = client.register(
        {
            "request_id": str(uuid.uuid4()),
            "email": email,
            "password": password,
            "proxy_url": proxy or "",
            "mail": _mail_payload(mail_client, email=email, account_id=account_id),
            "options": options,
        }
    )
    return go_response_to_protocol_result(response)
