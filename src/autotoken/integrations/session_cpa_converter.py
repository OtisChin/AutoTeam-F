from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autotoken.core.jwt import decode_jwt_payload
from autotoken.core.textio import write_text
from autotoken.core.timestamps import epoch_seconds, normalized_utc_timestamp
from autotoken.storage.auth_files import codex_auth_path, delete_auth_file, iter_auth_files_for_email
from autotoken.storage.auth_index import upsert_codex_auth_file
from autotoken.storage.auth_storage import AUTH_DIR, ensure_auth_dir, ensure_auth_file_permissions


class SessionConversionError(ValueError):
    pass


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _nested(source: Any, *keys: str) -> Any:
    current = source
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    return decode_jwt_payload(token)


def _b64url_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _normalize_timestamp(value: Any) -> str:
    return normalized_utc_timestamp(value)


def _epoch_seconds(value: Any) -> int:
    return epoch_seconds(value)


def _synthetic_id_token(
    *,
    email: str,
    account_id: str,
    plan_type: str,
    user_id: str,
    expires_at: str,
) -> str:
    if not account_id:
        return ""
    now = int(time.time())
    exp = _epoch_seconds(expires_at) or now + 90 * 24 * 60 * 60
    auth = {"chatgpt_account_id": account_id}
    if plan_type:
        auth["chatgpt_plan_type"] = plan_type
    if user_id:
        auth["chatgpt_user_id"] = user_id
        auth["user_id"] = user_id
    payload: dict[str, Any] = {
        "iat": now,
        "exp": exp,
        "https://api.openai.com/auth": auth,
    }
    if email:
        payload["email"] = email
    return f"{_b64url_json({'alg': 'none', 'typ': 'JWT', 'cpa_synthetic': True})}.{_b64url_json(payload)}.synthetic"


def convert_chatgpt_session_to_cpa_auth(session: dict[str, Any], *, source_name: str = "") -> dict[str, Any]:
    if not isinstance(session, dict):
        raise SessionConversionError("auth_session 不是 JSON 对象")

    access_token = _first(
        session.get("accessToken"),
        session.get("access_token"),
        _nested(session, "token", "accessToken"),
        _nested(session, "token", "access_token"),
        _nested(session, "credentials", "accessToken"),
        _nested(session, "credentials", "access_token"),
    )
    if not access_token:
        raise SessionConversionError("缺少 accessToken")

    session_token = _first(
        session.get("sessionToken"),
        session.get("session_token"),
        _nested(session, "token", "sessionToken"),
        _nested(session, "token", "session_token"),
        _nested(session, "credentials", "session_token"),
    )
    refresh_token = _first(
        session.get("refreshToken"),
        session.get("refresh_token"),
        _nested(session, "token", "refreshToken"),
        _nested(session, "token", "refresh_token"),
        _nested(session, "credentials", "refresh_token"),
    )
    input_id_token = _first(
        session.get("idToken"),
        session.get("id_token"),
        _nested(session, "token", "idToken"),
        _nested(session, "token", "id_token"),
        _nested(session, "credentials", "id_token"),
    )

    access_payload = _decode_jwt_payload(access_token)
    id_payload = _decode_jwt_payload(input_id_token)
    access_auth = access_payload.get("https://api.openai.com/auth") if isinstance(access_payload, dict) else {}
    id_auth = id_payload.get("https://api.openai.com/auth") if isinstance(id_payload, dict) else {}
    access_auth = access_auth if isinstance(access_auth, dict) else {}
    id_auth = id_auth if isinstance(id_auth, dict) else {}
    profile = access_payload.get("https://api.openai.com/profile") if isinstance(access_payload, dict) else {}
    profile = profile if isinstance(profile, dict) else {}

    expires_at = _first(
        _normalize_timestamp(access_payload.get("exp")),
        _normalize_timestamp(session.get("expires")),
        _normalize_timestamp(session.get("expiresAt")),
        _normalize_timestamp(session.get("expired")),
        _normalize_timestamp(session.get("expires_at")),
    )
    email = _first(
        _nested(session, "user", "email"),
        session.get("email"),
        _nested(session, "credentials", "email"),
        _nested(session, "providerSpecificData", "email"),
        profile.get("email"),
        id_payload.get("email"),
        access_payload.get("email"),
    ).lower()
    account_id = _first(
        _nested(session, "account", "id"),
        session.get("account_id"),
        session.get("chatgptAccountId"),
        _nested(session, "providerSpecificData", "chatgptAccountId"),
        _nested(session, "providerSpecificData", "chatgpt_account_id"),
        _nested(session, "credentials", "chatgpt_account_id"),
        access_auth.get("chatgpt_account_id"),
        id_auth.get("chatgpt_account_id"),
        session.get("id") if session.get("provider") == "codex" else "",
    )
    user_id = _first(
        _nested(session, "user", "id"),
        session.get("user_id"),
        session.get("chatgptUserId"),
        _nested(session, "providerSpecificData", "chatgptUserId"),
        _nested(session, "providerSpecificData", "chatgpt_user_id"),
        access_auth.get("chatgpt_user_id"),
        access_auth.get("user_id"),
        id_auth.get("chatgpt_user_id"),
        id_auth.get("user_id"),
    )
    plan_type = _first(
        _nested(session, "account", "planType"),
        _nested(session, "account", "plan_type"),
        session.get("planType"),
        session.get("plan_type"),
        _nested(session, "providerSpecificData", "chatgptPlanType"),
        _nested(session, "providerSpecificData", "chatgpt_plan_type"),
        _nested(session, "credentials", "plan_type"),
        access_auth.get("chatgpt_plan_type"),
        id_auth.get("chatgpt_plan_type"),
    )
    if not email:
        raise SessionConversionError("缺少可用邮箱")
    if not account_id:
        raise SessionConversionError("缺少 ChatGPT account_id")
    if not expires_at:
        expires_at = datetime.fromtimestamp(int(time.time()) + 90 * 24 * 60 * 60, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    synthetic_id_token = "" if input_id_token else _synthetic_id_token(
        email=email,
        account_id=account_id,
        plan_type=plan_type,
        user_id=user_id,
        expires_at=expires_at,
    )
    id_token = input_id_token or synthetic_id_token
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {
        "type": "codex",
        "disabled": False,
        "account_id": account_id,
        "chatgpt_account_id": account_id,
        "email": email,
        "name": _first(_nested(session, "user", "name"), email, source_name, "ChatGPT Account"),
        "plan_type": plan_type or "unknown",
        "chatgpt_plan_type": plan_type or "unknown",
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "session_token": session_token,
        "last_refresh": now,
        "expired": expires_at,
        "source": "chatgpt_web_session",
    }
    if synthetic_id_token:
        data["id_token_synthetic"] = True
    return data


def _safe_auth_path(auth_data: dict[str, Any]) -> Path:
    email = _clean(auth_data.get("email")).lower()
    plan_type = _clean(auth_data.get("plan_type")) or "unknown"
    account_id = _clean(auth_data.get("account_id"))
    return codex_auth_path(email=email, plan_type=plan_type, account_id=account_id, auth_dir=AUTH_DIR)


def save_cpa_auth_from_session(
    session: dict[str, Any],
    *,
    source_name: str = "",
    force_plan_type: str = "",
) -> dict[str, Any]:
    auth_data = convert_chatgpt_session_to_cpa_auth(session, source_name=source_name)
    forced_plan = _clean(force_plan_type).lower()
    if forced_plan:
        auth_data["plan_type"] = forced_plan
        auth_data["chatgpt_plan_type"] = forced_plan
    ensure_auth_dir()
    path = _safe_auth_path(auth_data)
    email = _clean(auth_data.get("email")).lower()
    for old in iter_auth_files_for_email(email, auth_dir=AUTH_DIR):
        if old != path and old.exists():
            try:
                delete_auth_file(old, auth_dir=AUTH_DIR)
            except Exception:
                pass
    write_text(path, json.dumps(auth_data, ensure_ascii=False, indent=2))
    ensure_auth_file_permissions(path)
    try:
        upsert_codex_auth_file(path, auth_data, main=False)
    except Exception:
        pass
    return {
        "email": email,
        "auth_file": str(path.resolve()),
        "filename": path.name,
        "plan_type": _clean(auth_data.get("plan_type")) or "unknown",
        "id_token_synthetic": bool(auth_data.get("id_token_synthetic")),
        "refresh_token_present": bool(_clean(auth_data.get("refresh_token"))),
    }
