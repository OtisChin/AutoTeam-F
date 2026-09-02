from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from autotoken.core.jwt import decode_jwt_payload
from autotoken.core.normalization import normalized_email

FINISHED_IMPORT_MAX_BYTES = 2 * 1024 * 1024
FINISHED_IMPORT_PLAN_TYPE = "plus"


def _clean(value: Any) -> str:
    return str(value or "").strip() if value is not None else ""


def _first(*values: Any) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _b64url_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _utc_timestamp_from_epoch(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    return datetime.fromtimestamp(number, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _synthetic_token_id(*parts: str) -> str:
    source = "\n".join(parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def _synthetic_id_token(*, email: str, account_id: str, user_id: str, plan_type: str, expires_at: str) -> str:
    now = int(time.time())
    exp = int(time.time()) + 90 * 24 * 60 * 60
    try:
        parsed = datetime.fromisoformat(str(expires_at or "").replace("Z", "+00:00"))
        exp = int(parsed.timestamp())
    except Exception:
        pass
    auth: dict[str, Any] = {"chatgpt_account_id": account_id}
    if user_id:
        auth["chatgpt_user_id"] = user_id
        auth["user_id"] = user_id
    if plan_type:
        auth["chatgpt_plan_type"] = plan_type
    payload: dict[str, Any] = {
        "email": email,
        "iat": now,
        "exp": exp,
        "https://api.openai.com/auth": auth,
    }
    return f"{_b64url_json({'alg': 'none', 'typ': 'JWT', 'autotoken_synthetic': True})}.{_b64url_json(payload)}.synthetic"


def parse_finished_account_text(content: str, *, source_name: str = "accounts.json") -> tuple[list[dict], list[dict]]:
    """Parse exported finished-account JSON.

    The common export shape is a file containing pretty-printed JSON objects
    back-to-back, not JSONL. This parser also accepts a JSON array or
    {"accounts": [...]} for compatibility.
    """
    text = str(content or "").lstrip("\ufeff")
    if not text.strip():
        return [], [{"filename": source_name, "error": "账号文件为空"}]
    if len(text.encode("utf-8", errors="ignore")) > FINISHED_IMPORT_MAX_BYTES:
        return [], [{"filename": source_name, "error": "账号文件过大，最多支持 2MB"}]

    invalid: list[dict] = []

    def _normalize_items(items: Any) -> list[dict]:
        if isinstance(items, dict) and isinstance(items.get("accounts"), list):
            items = items.get("accounts")
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            invalid.append({"filename": source_name, "error": "账号 JSON 顶层必须是对象、数组或连续对象"})
            return []
        records: list[dict] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                invalid.append({"filename": source_name, "line": index, "error": "账号记录不是 JSON object"})
                continue
            email = normalized_email(item.get("email"))
            access_token = _clean(item.get("access_token") or item.get("accessToken"))
            if not email or not access_token:
                invalid.append({"filename": source_name, "line": index, "error": "缺少 email 或 access_token"})
                continue
            record = dict(item)
            record["email"] = email
            record["access_token"] = access_token
            records.append(record)
        return records

    try:
        return _normalize_items(json.loads(text)), invalid
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    index = 0
    items: list[dict] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            item, next_index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            invalid.append({"filename": source_name, "offset": index, "error": f"JSON 解析失败: {exc.msg}"})
            break
        items.append(item)
        index = next_index
    return _normalize_items(items), invalid


def parse_mailbox_text(content: str) -> dict[str, dict]:
    from autotoken.mail.outlook import OutlookMailProvider

    mailboxes: dict[str, dict] = {}
    for line in str(content or "").replace("\ufeff", "").replace(";", "\n").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        account = OutlookMailProvider._parse_account_line(raw)
        if not account or not account.validate():
            continue
        mailboxes[account.email.lower()] = {
            "email": account.email.lower(),
            "line": raw,
            "mailapi_url": account.mailapi_url,
        }
    return mailboxes


def build_finished_cpa_auth(record: dict[str, Any]) -> dict[str, Any]:
    access_token = _clean(record.get("access_token") or record.get("accessToken"))
    access_claims = decode_jwt_payload(access_token)
    access_auth = access_claims.get("https://api.openai.com/auth") if isinstance(access_claims, dict) else {}
    access_auth = access_auth if isinstance(access_auth, dict) else {}
    access_profile = access_claims.get("https://api.openai.com/profile") if isinstance(access_claims, dict) else {}
    access_profile = access_profile if isinstance(access_profile, dict) else {}

    email = normalized_email(_first(record.get("email"), access_profile.get("email"), access_claims.get("email")))
    account_id = _first(
        record.get("account_id"),
        record.get("accountId"),
        record.get("chatgpt_account_id"),
        access_auth.get("chatgpt_account_id"),
        f"synthetic-{hashlib.md5(email.encode('utf-8')).hexdigest()[:12]}" if email else "",
    )
    user_id = _first(record.get("chatgpt_user_id"), access_auth.get("chatgpt_user_id"), access_auth.get("user_id"))
    plan_type = FINISHED_IMPORT_PLAN_TYPE
    expired = _first(
        record.get("expired"),
        record.get("expires"),
        record.get("expires_at"),
        record.get("expiresAt"),
        _utc_timestamp_from_epoch(access_claims.get("exp") if isinstance(access_claims, dict) else None),
    )
    last_refresh = _first(record.get("last_refresh"), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    refresh_token = _clean(record.get("refresh_token") or record.get("refreshToken"))
    if not refresh_token:
        refresh_token = f"synthetic-refresh-token-{_synthetic_token_id(email, account_id, access_token)}"

    id_token = _clean(record.get("id_token") or record.get("idToken"))
    synthetic_id = False
    if not id_token:
        id_token = _synthetic_id_token(
            email=email,
            account_id=account_id,
            user_id=user_id,
            plan_type=plan_type,
            expires_at=expired,
        )
        synthetic_id = True

    auth = {
        "type": "codex",
        "disabled": False,
        "email": email,
        "account_id": account_id,
        "chatgpt_account_id": account_id,
        "chatgpt_user_id": user_id,
        "plan_type": plan_type,
        "chatgpt_plan_type": plan_type,
        "access_token": access_token,
        "id_token": id_token,
        "refresh_token": refresh_token,
        "expired": expired,
        "last_refresh": last_refresh,
        "source": "finished_import_synthetic_cpa",
    }
    if synthetic_id:
        auth["id_token_synthetic"] = True
    if _clean(record.get("source")):
        auth["source_account_export"] = _clean(record.get("source"))
    return auth


def _account_type_for_plan(plan_type: str) -> str:
    from autotoken.storage.accounts import ACCOUNT_TYPE_PLUS

    return ACCOUNT_TYPE_PLUS


def _status_for_plan(plan_type: str) -> str:
    from autotoken.storage.accounts import STATUS_PLUS

    return STATUS_PLUS


def import_finished_accounts_from_text(
    accounts_content: str,
    mailboxes_content: str = "",
    *,
    accounts_source_name: str = "accounts.json",
    mailboxes_source_name: str = "mailboxes.txt",
) -> dict[str, Any]:
    from autotoken.integrations import cpa_sync
    from autotoken.storage.accounts import SEAT_CODEX, add_account, find_account, load_accounts, update_account

    records, invalid = parse_finished_account_text(accounts_content, source_name=accounts_source_name)
    mailboxes = parse_mailbox_text(mailboxes_content)

    sources: list[dict[str, Any]] = []
    metadata_by_email: dict[str, dict[str, Any]] = {}
    for record in records:
        auth = build_finished_cpa_auth(record)
        email = normalized_email(auth.get("email"))
        if not email:
            invalid.append({"filename": accounts_source_name, "error": "缺少可用 email"})
            continue
        sources.append({"name": f"{email}.json", "auth_data": auth})
        metadata_by_email[email] = {
            "password": _clean(record.get("password")),
            "plan_type": auth.get("plan_type") or "unknown",
            "mailbox": mailboxes.get(email),
            "auth_data": auth,
        }

    result = cpa_sync.import_local_cpa_auth_sources(sources)

    accounts_updated = 0
    for item in result.get("files") or []:
        email = normalized_email(item.get("email"))
        if not email:
            continue
        metadata = metadata_by_email.get(email) or {}
        mailbox = metadata.get("mailbox") if isinstance(metadata.get("mailbox"), dict) else None
        if item.get("auth_file"):
            try:
                from pathlib import Path

                path = Path(item["auth_file"])
                saved = json.loads(path.read_text(encoding="utf-8"))
                source_auth = metadata.get("auth_data") if isinstance(metadata.get("auth_data"), dict) else {}
                if source_auth.get("id_token_synthetic"):
                    saved["id_token_synthetic"] = True
                saved["source"] = "finished_import_synthetic_cpa"
                path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        account = find_account(load_accounts(), email)
        if not account:
            add_account(email, metadata.get("password") or "", seat_type=SEAT_CODEX, mail_provider="outlook" if mailbox else None)
        updates = {
            "password": metadata.get("password") or (account or {}).get("password") or "",
            "status": _status_for_plan(metadata.get("plan_type") or ""),
            "account_type": _account_type_for_plan(metadata.get("plan_type") or ""),
            "seat_type": SEAT_CODEX,
            "auth_file": item.get("auth_file"),
            "last_active_at": time.time(),
            "last_bind_status": "success",
            "last_bind_at": time.time(),
            "last_bind_provider": "external_import",
            "last_bind_message": "成品导入",
            "plus_bound_at": time.time(),
        }
        if mailbox:
            updates["mail_provider"] = "outlook"
            updates["cloudmail_account_id"] = email
            if mailbox.get("mailapi_url"):
                updates["mailapi_url"] = mailbox.get("mailapi_url")
        update_account(email, **updates)
        accounts_updated += 1

    return {
        **result,
        "invalid": [*(result.get("invalid") or []), *invalid],
        "accounts_updated": accounts_updated,
        "mailboxes_total": len(mailboxes),
        "mailboxes_matched": sum(1 for email in metadata_by_email if email in mailboxes),
        "accounts_source": accounts_source_name,
        "mailboxes_source": mailboxes_source_name,
        "synthetic": True,
    }
