from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import secrets
import string
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from autotoken.core.archive import safe_archive_member_name, safe_archive_path_segment
from autotoken.core.normalization import normalized_email
from autotoken.core.textio import read_text
from autotoken.integrations.sub2api_converter import (
    ConversionError,
    ExportSettings,
    export_records,
    generate_default_filename,
    inspect_sources,
)
from autotoken.storage import sqlite_store
from autotoken.storage.accounts import (
    ACCOUNT_TYPE_PLUS,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    STATUS_FAIL,
    STATUS_ORPHAN,
    STATUS_PLUS,
)
from autotoken.storage.auth_files import iter_auth_files_for_email, trusted_auth_file_path
from autotoken.storage.auth_storage import AUTH_DIR

CDK_TTL_SECONDS = 24 * 60 * 60
CDK_PREFIX = "PLUS-"
CDK_BODY_LEN = 12
CDK_RE = re.compile(r"^[1-9][0-9]*-[0-9]{8}-PLUS-[A-Z0-9]{12}$")
LEGACY_CDK_RE = re.compile(r"^PLUS-[A-Z0-9]{12}$")
PASSWORD_ITERATIONS = 210_000
PASSWORD_MIN_LEN = 6
EXPORT_FORMATS = {"cpa", "sub", "credentials"}
EXCLUDED_ACCOUNT_STATUSES = {STATUS_FAIL, STATUS_AUTH_INVALID, STATUS_ORPHAN}
DOMAIN_CREDENTIAL_DELIVERY_URL = "https://gptcode.external.cc.cd/"
OUTLOOK_TOKEN_DELIVERY_URL = "https://mail.cpacc.us.ci/"
EXPORT_PAYLOAD_MAX_BYTES = 20 * 1024 * 1024


class TradeError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def normalize_code(value: str) -> str:
    return str(value or "").strip().upper()


def validate_code(value: str) -> str:
    code = normalize_code(value)
    if not CDK_RE.match(code) and not LEGACY_CDK_RE.match(code):
        raise TradeError("CDK 格式无效")
    return code


def _now() -> float:
    return time.time()


def _normalized_email(value) -> str:
    return normalized_email(value)


def _code_date(timestamp: float) -> str:
    return time.strftime("%Y%m%d", time.localtime(timestamp))


def _random_code(quota_total: int, created_at: float) -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(CDK_BODY_LEN))
    return f"{int(quota_total)}-{_code_date(created_at)}-{CDK_PREFIX}{body}"


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt_value.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()
    return salt_value, digest


def _password_matches(password: str, salt: str, expected_hash: str) -> bool:
    if not salt or not expected_hash:
        return False
    _, digest = _hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


def _row_to_cdk(row: Any, *, used_count: int = 0, latest_redeemed_at: float | None = None) -> dict:
    now = _now()
    quota_total = int(row["quota_total"] or 0)
    status = str(row["status"] or "active")
    expired = now >= float(row["expires_at"] or 0)
    exhausted = used_count >= quota_total
    effective_status = status
    if status == "active" and expired:
        effective_status = "expired"
    elif status == "active" and exhausted:
        effective_status = "exhausted"
    return {
        "code": row["code"],
        "quota_total": quota_total,
        "used_count": used_count,
        "remaining": max(0, quota_total - used_count),
        "password_set": bool(row["password_hash"]),
        "password": row["password_plain"] or "",
        "status": effective_status,
        "raw_status": status,
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
        "latest_redeemed_at": latest_redeemed_at,
        "active": effective_status == "active",
    }


def create_cdk(quota_total: int, note: str = "") -> dict:
    quota = int(quota_total or 0)
    if quota <= 0:
        raise TradeError("CDK 可提取账号数必须大于 0")
    if quota > 10_000:
        raise TradeError("CDK 可提取账号数过大")
    note_value = str(note or "").strip()[:500]
    created_at = _now()
    expires_at = created_at + CDK_TTL_SECONDS
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        for _ in range(20):
            code = _random_code(quota, created_at)
            try:
                conn.execute(
                    """
                    INSERT INTO plus_cdks(code, quota_total, note, created_at, expires_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (code, quota, note_value, created_at, expires_at, created_at),
                )
                conn.commit()
                return get_cdk(code)
            except Exception:
                continue
    raise TradeError("生成 CDK 失败，请重试")


def _allocation_counts(conn) -> dict[str, int]:
    rows = conn.execute("SELECT code, COUNT(*) AS used_count FROM plus_cdk_redemptions GROUP BY code").fetchall()
    return {row["code"]: int(row["used_count"] or 0) for row in rows}


def _latest_redemption_times(conn) -> dict[str, float]:
    rows = conn.execute("SELECT code, MAX(redeemed_at) AS latest_redeemed_at FROM plus_cdk_redemptions GROUP BY code").fetchall()
    return {row["code"]: float(row["latest_redeemed_at"] or 0) for row in rows}


def _cdk_used_count(conn, code: str) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM plus_cdk_redemptions WHERE code = ?", (code,)).fetchone()
    return int(row["count"] or 0)


def _cdk_latest_redeemed_at(conn, code: str) -> float | None:
    row = conn.execute("SELECT MAX(redeemed_at) AS latest_redeemed_at FROM plus_cdk_redemptions WHERE code = ?", (code,)).fetchone()
    value = float(row["latest_redeemed_at"] or 0)
    return value or None


def _formats_from_stored(value: str) -> list[str]:
    formats = []
    for item in str(value or "").split(","):
        format_value = item.strip().lower()
        if format_value and format_value not in formats:
            formats.append(format_value)
    if not formats:
        formats = ["cpa"]
    return _normalize_export_formats(formats)


def _assert_history_access(row) -> None:
    if str(row["status"] or "") == "revoked":
        raise TradeError("CDK 已注销或不可用", status_code=410)
    if _now() >= float(row["expires_at"] or 0):
        raise TradeError("CDK 已过期", status_code=410)


def _authenticated_cdk_row(conn, code: str, password: str):
    code = validate_code(code)
    password_value = str(password or "")
    if not password_value:
        raise TradeError("提取密码不能为空")
    row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
    if not row:
        raise TradeError("CDK 不存在", status_code=404)
    _assert_history_access(row)
    if not row["password_hash"]:
        raise TradeError("CDK 尚未设置提取密码，请先完成首次提取", status_code=403)
    if not _password_matches(password_value, row["password_salt"], row["password_hash"]):
        raise TradeError("提取密码错误", status_code=403)
    return row


def list_cdks(limit: int = 200) -> list[dict]:
    sqlite_store.initialize()
    max_rows = max(1, min(int(limit or 200), 1000))
    with sqlite_store.connect() as conn:
        counts = _allocation_counts(conn)
        latest = _latest_redemption_times(conn)
        rows = conn.execute(
            "SELECT * FROM plus_cdks ORDER BY created_at DESC LIMIT ?",
            (max_rows,),
        ).fetchall()
        return [
            _row_to_cdk(
                row,
                used_count=counts.get(row["code"], 0),
                latest_redeemed_at=latest.get(row["code"]),
            )
            for row in rows
        ]


def get_cdk(code: str) -> dict:
    code = validate_code(code)
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise TradeError("CDK 不存在", status_code=404)
        cdk = _row_to_cdk(
            row,
            used_count=_cdk_used_count(conn, code),
            latest_redeemed_at=_cdk_latest_redeemed_at(conn, code),
        )
        cdk["redemptions"] = [
            {
                "batch_id": item["batch_id"],
                "email": item["email"],
                "format": item["format"],
                "redeemed_at": item["redeemed_at"],
            }
            for item in conn.execute(
                """
                SELECT batch_id, email, format, redeemed_at
                FROM plus_cdk_redemptions
                WHERE code = ?
                ORDER BY redeemed_at DESC, id DESC
                LIMIT 500
                """,
                (code,),
            ).fetchall()
        ]
        return cdk


def _history_batches(conn, code: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT batch_id, email, format, redeemed_at
        FROM plus_cdk_redemptions
        WHERE code = ?
        ORDER BY redeemed_at DESC, id ASC
        """,
        (code,),
    ).fetchall()
    batches: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        batch_id = str(row["batch_id"] or "")
        if not batch_id:
            continue
        if batch_id not in batches:
            order.append(batch_id)
            batches[batch_id] = {
                "batch_id": batch_id,
                "redeemed_at": float(row["redeemed_at"] or 0),
                "formats": _formats_from_stored(row["format"]),
                "emails": [],
            }
        email = _normalized_email(row["email"])
        if email:
            batches[batch_id]["emails"].append(email)
    history = []
    for batch_id in order:
        item = batches[batch_id]
        item["count"] = len(item["emails"])
        history.append(item)
    return history


def list_cdk_redemption_history(code: str, password: str) -> dict:
    code = validate_code(code)
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        row = _authenticated_cdk_row(conn, code, password)
        used_count = _cdk_used_count(conn, code)
        cdk = _row_to_cdk(row, used_count=used_count, latest_redeemed_at=_cdk_latest_redeemed_at(conn, code))
        history = _history_batches(conn, code)
    return {
        "code": cdk["code"],
        "quota_total": cdk["quota_total"],
        "used_count": cdk["used_count"],
        "remaining": cdk["remaining"],
        "status": cdk["status"],
        "active": cdk["active"],
        "expires_at": cdk["expires_at"],
        "history": history,
    }


def revoke_cdk(code: str) -> dict:
    code = validate_code(code)
    revoked_at = _now()
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        row = conn.execute("SELECT code FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise TradeError("CDK 不存在", status_code=404)
        conn.execute(
            """
            UPDATE plus_cdks
            SET status = 'revoked', revoked_at = ?, updated_at = ?
            WHERE code = ?
            """,
            (revoked_at, revoked_at, code),
        )
    return get_cdk(code)


def _allocated_emails(conn, accounts: list[dict] | None = None) -> set[str]:
    if accounts is None:
        from autotoken.storage.accounts import load_accounts

        accounts = load_accounts()
    exported_emails = {
        _normalized_email(account.get("email"))
        for account in accounts
        if bool(account.get("credentials_exported"))
    }
    return {
        email
        for email in (
            _normalized_email(row["email"])
            for row in conn.execute("SELECT email FROM plus_cdk_allocations")
        )
        if email and email in exported_emails
    }


def _clear_unexported_trade_allocations(conn, accounts: list[dict] | None = None) -> int:
    if accounts is None:
        from autotoken.storage.accounts import load_accounts

        accounts = load_accounts()
    reusable_emails = [
        _normalized_email(account.get("email"))
        for account in accounts
        if _normalized_email(account.get("email")) and not bool(account.get("credentials_exported"))
    ]
    if not reusable_emails:
        return 0
    placeholders = ",".join("?" for _ in reusable_emails)
    cursor = conn.execute(
        f"DELETE FROM plus_cdk_allocations WHERE lower(email) IN ({placeholders})",
        reusable_emails,
    )
    return int(cursor.rowcount or 0)


def _resolve_codex_auth_file(account: dict) -> str:
    auth_file = str(account.get("auth_file") or "").strip()
    if auth_file:
        path = trusted_auth_file_path(auth_file, auth_dir=AUTH_DIR)
        if path:
            return str(path)
    email = _normalized_email(account.get("email"))
    if not email:
        return ""
    try:
        matches = sorted(iter_auth_files_for_email(email, auth_dir=AUTH_DIR), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return ""
    return str(matches[0]) if matches else ""


def credential_password_for_account(account: dict) -> str:
    cloudmail_token = str(account.get("cloudmail_account_id") or "").strip()
    mail_provider = str(account.get("mail_provider") or "").strip().lower()
    if mail_provider == "luckmail" and cloudmail_token:
        return cloudmail_token
    if cloudmail_token.startswith("tok_"):
        return cloudmail_token
    return str(account.get("password") or "")


def outlook_accounts_by_email() -> dict[str, dict[str, str]]:
    """Return imported Outlook/Hotmail source credentials keyed by mailbox email."""
    try:
        from autotoken.mail.outlook import OutlookMailProvider
    except Exception:
        return {}
    try:
        provider = OutlookMailProvider()
    except Exception:
        return {}
    rows: dict[str, dict[str, str]] = {}
    for account in getattr(provider, "accounts", []) or []:
        email = _normalized_email(getattr(account, "email", ""))
        if not email:
            continue
        rows[email] = {
            "email": str(getattr(account, "email", "") or "").strip() or email,
            "password": str(getattr(account, "password", "") or "").strip(),
            "client_id": str(getattr(account, "client_id", "") or "").strip(),
            "refresh_token": str(getattr(account, "refresh_token", "") or "").strip(),
            "mailapi_url": str(getattr(account, "mailapi_url", "") or "").strip(),
        }
    return rows


def outlook_mailapi_urls_by_email() -> dict[str, str]:
    """Return imported Outlook/Hotmail mailapi URLs keyed by mailbox email."""
    return {
        email: item["mailapi_url"]
        for email, item in outlook_accounts_by_email().items()
        if str(item.get("mailapi_url") or "").strip()
    }


def icloud_accounts_by_email() -> dict[str, dict[str, str]]:
    """Return imported iCloud receive-code links keyed by mailbox email."""
    try:
        from autotoken.mail.icloud import ICloudMailProvider
    except Exception:
        return {}
    try:
        provider = ICloudMailProvider()
    except Exception:
        return {}
    rows: dict[str, dict[str, str]] = {}
    for account in getattr(provider, "accounts", []) or []:
        email = _normalized_email(getattr(account, "email", ""))
        if not email:
            continue
        rows[email] = {
            "email": str(getattr(account, "email", "") or "").strip() or email,
            "receive_code_url": str(getattr(account, "receive_code_url", "") or "").strip(),
        }
    return rows


def credential_export_line_for_account(
    account: dict,
    *,
    outlook_mailapi_urls: dict[str, str] | None = None,
    outlook_accounts: dict[str, dict[str, str]] | None = None,
    icloud_accounts: dict[str, dict[str, str]] | None = None,
) -> str:
    """Render account credentials as: email-----secret-----mail access URL."""
    email = _normalized_email(account.get("email"))
    password = str(account.get("password") or "")
    credential_secret = credential_password_for_account(account)
    mail_provider = str(account.get("mail_provider") or "").strip().lower()
    cloudmail_token = str(account.get("cloudmail_account_id") or "").strip()
    outlook_rows = outlook_accounts if outlook_accounts is not None else outlook_accounts_by_email()
    outlook_source = outlook_rows.get(email, {}) if isinstance(outlook_rows, dict) else {}
    is_outlook_account = mail_provider == "outlook" or bool(outlook_source)
    mailapi_urls = outlook_mailapi_urls if outlook_mailapi_urls is not None else {
        key: item["mailapi_url"]
        for key, item in outlook_rows.items()
        if isinstance(item, dict) and str(item.get("mailapi_url") or "").strip()
    }
    mailapi_url = str(account.get("mailapi_url") or mailapi_urls.get(email, "") or "").strip()
    export_email = str(outlook_source.get("email") or account.get("original_email") or email).strip()
    outlook_password = str(outlook_source.get("password") or "").strip()
    outlook_client_id = str(outlook_source.get("client_id") or "").strip()
    outlook_refresh_token = str(outlook_source.get("refresh_token") or "").strip()
    icloud_rows = icloud_accounts if icloud_accounts is not None else icloud_accounts_by_email()
    icloud_source = icloud_rows.get(email, {}) if isinstance(icloud_rows, dict) else {}
    is_icloud_account = mail_provider == "icloud" or bool(icloud_source)
    icloud_export_email = str(icloud_source.get("email") or account.get("original_email") or email).strip()
    icloud_receive_code_url = str(
        account.get("receive_code_url")
        or account.get("mail_url")
        or icloud_source.get("receive_code_url")
        or ""
    ).strip()

    if is_icloud_account:
        return f"{icloud_export_email}----{icloud_receive_code_url}"
    if mailapi_url:
        return f"{export_email}-----{password}-----{mailapi_url}"
    if is_outlook_account:
        return f"{export_email}----{outlook_password or password}----{outlook_client_id}----{outlook_refresh_token}"
    if mail_provider == "luckmail" or cloudmail_token.startswith("tok_"):
        return f"{email}-----{credential_secret}-----{OUTLOOK_TOKEN_DELIVERY_URL}"
    return f"{email}-----{password}-----{DOMAIN_CREDENTIAL_DELIVERY_URL}"


def _source_for_account(account: dict, export_format: str) -> dict | None:
    email = _normalized_email(account.get("email"))
    auth_file = _resolve_codex_auth_file(account)
    if not email or not auth_file:
        return None
    path = Path(auth_file)
    try:
        content = read_text(path)
        json.loads(content)
        if export_format == "credentials":
            content = credential_export_line_for_account(account)
            if not content:
                return None
            return {
                "email": email,
                "filename": f"{email}.txt",
                "content": content,
                "password": credential_password_for_account(account),
            }
        if export_format == "sub":
            records = inspect_sources([(path.name, content)])
            if not any(record.is_valid for record in records):
                return None
    except Exception:
        return None
    return {"email": email, "filename": path.name, "content": content}


def _eligible_plus_sources(export_format: str, allocated: set[str]) -> list[dict]:
    from autotoken.settings.admin_state import get_admin_email
    from autotoken.storage.accounts import load_accounts

    main_email = _normalized_email(get_admin_email())
    sources = []
    for account in load_accounts():
        email = _normalized_email(account.get("email"))
        if not email or email == main_email or email in allocated:
            continue
        if not _is_trade_plus_account(account, main_email):
            continue
        if not _is_trade_stock_status(account):
            continue
        if bool(account.get("credentials_exported")):
            continue
        source = _source_for_account(account, export_format)
        if source:
            sources.append(source)
    return sources


def _normalize_export_formats(value: str | list[str] | tuple[str, ...]) -> list[str]:
    raw_values = value if isinstance(value, (list, tuple)) else [value]
    formats = []
    for item in raw_values:
        format_value = str(item or "").strip().lower()
        if format_value and format_value not in formats:
            formats.append(format_value)
    if not formats or any(format_value not in EXPORT_FORMATS for format_value in formats):
        raise TradeError("提取格式只支持 cpa、sub 或 credentials")
    return formats


def _eligible_plus_bundle_sources(export_formats: list[str], allocated: set[str]) -> list[dict]:
    from autotoken.settings.admin_state import get_admin_email
    from autotoken.storage.accounts import load_accounts

    main_email = _normalized_email(get_admin_email())
    sources = []
    for account in load_accounts():
        email = _normalized_email(account.get("email"))
        if not email or email == main_email or email in allocated:
            continue
        if not _is_trade_plus_account(account, main_email):
            continue
        if not _is_trade_stock_status(account):
            continue
        if bool(account.get("credentials_exported")):
            continue
        exports = {}
        for format_value in export_formats:
            source = _source_for_account(account, format_value)
            if not source:
                exports = {}
                break
            exports[format_value] = source
        if exports:
            sources.append({"email": email, "exports": exports})
    return sources


def _bundle_sources_for_emails(emails: list[str], export_formats: list[str]) -> list[dict]:
    from autotoken.storage.accounts import load_accounts

    by_email = {
        _normalized_email(account.get("email")): account
        for account in load_accounts()
        if _normalized_email(account.get("email"))
    }
    sources = []
    missing = []
    for email in emails:
        normalized = _normalized_email(email)
        account = by_email.get(normalized)
        if not account:
            missing.append(normalized)
            continue
        exports = {}
        for format_value in export_formats:
            source = _source_for_account(account, format_value)
            if not source:
                exports = {}
                break
            exports[format_value] = source
        if not exports:
            missing.append(normalized)
            continue
        sources.append({"email": normalized, "exports": exports})
    if missing:
        raise TradeError(f"提取历史中有 {len(missing)} 个账号文件已失效，请联系管理员")
    return sources


def _is_trade_stock_status(account: dict) -> bool:
    status = str(account.get("status") or "").strip().lower()
    return status in {STATUS_ACTIVE, STATUS_PLUS}


def _is_trade_plus_account(account: dict, main_email: str) -> bool:
    email = _normalized_email(account.get("email"))
    account_type = str(account.get("account_type") or "").strip().lower()
    status = str(account.get("status") or "").strip().lower()
    return bool(
        email
        and email != main_email
        and (account_type == ACCOUNT_TYPE_PLUS or status == STATUS_PLUS)
    )


def _is_plus_account(account: dict, main_email: str) -> bool:
    return _is_trade_plus_account(account, main_email)


def _has_valid_codex_auth(account: dict) -> bool:
    return _source_for_account(account, "cpa") is not None


def _inventory_format_counts(accounts: list[dict], main_email: str, allocated: set[str]) -> tuple[dict[str, int], int]:
    counts = {
        "cpa": 0,
        "sub": 0,
        "credentials": 0,
        "cpa_sub": 0,
        "cpa_credentials": 0,
        "all_formats": 0,
    }
    missing_credentials_count = 0
    outlook_accounts = outlook_accounts_by_email()
    outlook_urls = {
        email: item["mailapi_url"]
        for email, item in outlook_accounts.items()
        if str(item.get("mailapi_url") or "").strip()
    }

    for account in accounts:
        email = _normalized_email(account.get("email"))
        if not email or email == main_email or email in allocated:
            continue
        if not _is_trade_plus_account(account, main_email):
            continue
        if not _is_trade_stock_status(account):
            continue
        if bool(account.get("credentials_exported")):
            continue

        auth_file = _resolve_codex_auth_file(account)
        if not auth_file:
            missing_credentials_count += 1
            continue

        path = Path(auth_file)
        try:
            content = read_text(path)
            json.loads(content)
        except Exception:
            missing_credentials_count += 1
            continue

        has_cpa = True
        has_sub = False
        try:
            records = inspect_sources([(path.name, content)])
            has_sub = any(record.is_valid for record in records)
        except Exception:
            has_sub = False
        has_credentials = bool(
            credential_export_line_for_account(
                account,
                outlook_mailapi_urls=outlook_urls,
                outlook_accounts=outlook_accounts,
            )
        )

        if has_cpa:
            counts["cpa"] += 1
        if has_sub:
            counts["sub"] += 1
        if has_credentials:
            counts["credentials"] += 1
        if has_cpa and has_sub:
            counts["cpa_sub"] += 1
        if has_cpa and has_credentials:
            counts["cpa_credentials"] += 1
        if has_cpa and has_sub and has_credentials:
            counts["all_formats"] += 1

    return counts, missing_credentials_count


def inventory_summary() -> dict:
    from autotoken.settings.admin_state import get_admin_email
    from autotoken.storage.accounts import load_accounts

    accounts = load_accounts()
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        _clear_unexported_trade_allocations(conn, accounts)
        allocated = _allocated_emails(conn, accounts)
    cdks = list_cdks()
    main_email = _normalized_email(get_admin_email())
    plus_accounts = [account for account in accounts if _is_plus_account(account, main_email)]
    exported_count = sum(1 for account in plus_accounts if bool(account.get("credentials_exported")))
    discarded_count = sum(
        1
        for account in plus_accounts
        if str(account.get("status") or "").strip().lower() in EXCLUDED_ACCOUNT_STATUSES
    )
    stock_counts, missing_credentials_count = _inventory_format_counts(accounts, main_email, allocated)
    return {
        "stock_available": stock_counts["cpa"],
        "stock_available_cpa": stock_counts["cpa"],
        "stock_available_sub": stock_counts["sub"],
        "stock_available_credentials": stock_counts["credentials"],
        "stock_available_cpa_sub": stock_counts["cpa_sub"],
        "stock_available_cpa_credentials": stock_counts["cpa_credentials"],
        "stock_available_all_formats": stock_counts["all_formats"],
        "stock_exported": exported_count,
        "stock_discarded": discarded_count,
        "stock_missing_credentials": missing_credentials_count,
        "allocated": len(allocated),
        "cdk_total": len(cdks),
        "cdk_active": sum(1 for item in cdks if item["status"] == "active"),
        "cdk_expired": sum(1 for item in cdks if item["status"] == "expired"),
        "cdk_exhausted": sum(1 for item in cdks if item["status"] == "exhausted"),
        "cdk_revoked": sum(1 for item in cdks if item["status"] == "revoked"),
    }


def clear_trade_allocations_for_emails(emails: list[str]) -> dict:
    targets = []
    seen = set()
    for email in emails or []:
        normalized = _normalized_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            targets.append(normalized)
    if not targets:
        return {"cleared": 0, "codes": []}

    sqlite_store.initialize()
    placeholders = ",".join("?" for _ in targets)
    with sqlite_store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            f"SELECT email, code FROM plus_cdk_allocations WHERE lower(email) IN ({placeholders})",
            targets,
        ).fetchall()
        affected_codes = sorted({str(row["code"] or "") for row in rows if row["code"]})
        conn.execute(
            f"DELETE FROM plus_cdk_allocations WHERE lower(email) IN ({placeholders})",
            targets,
        )
    return {"cleared": len(rows), "codes": affected_codes}


def _assert_cdk_redeemable(row, used_count: int, requested_count: int) -> int:
    if str(row["status"] or "") != "active":
        raise TradeError("CDK 已注销或不可用", status_code=410)
    if _now() >= float(row["expires_at"] or 0):
        raise TradeError("CDK 已过期", status_code=410)
    quota_total = int(row["quota_total"] or 0)
    remaining = quota_total - used_count
    if remaining <= 0:
        raise TradeError("CDK 可提取账号已用完", status_code=410)
    if requested_count > remaining:
        raise TradeError(f"CDK 剩余额度不足，仅剩 {remaining} 个账号")
    return remaining


def query_cdk_remaining(code: str, password: str) -> dict:
    code = validate_code(code)
    password_value = str(password or "")
    if not password_value:
        raise TradeError("提取密码不能为空")
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise TradeError("CDK 不存在", status_code=404)
        used_count = _cdk_used_count(conn, code)
        if not row["password_hash"]:
            raise TradeError("CDK 尚未设置提取密码，请先完成首次提取", status_code=403)
        if not _password_matches(password_value, row["password_salt"], row["password_hash"]):
            raise TradeError("提取密码错误", status_code=403)
        return _row_to_cdk(row, used_count=used_count, latest_redeemed_at=_cdk_latest_redeemed_at(conn, code))


def public_cdk_status(code: str) -> dict:
    code = validate_code(code)
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise TradeError("CDK 不存在", status_code=404)
        cdk = _row_to_cdk(
            row,
            used_count=_cdk_used_count(conn, code),
            latest_redeemed_at=_cdk_latest_redeemed_at(conn, code),
        )
    return {
        "code": cdk["code"],
        "quota_total": cdk["quota_total"],
        "used_count": cdk["used_count"],
        "remaining": cdk["remaining"],
        "password_set": cdk["password_set"],
        "status": cdk["status"],
        "active": cdk["active"],
        "expires_at": cdk["expires_at"],
    }


def set_cdk_password(code: str, password: str) -> dict:
    code = validate_code(code)
    password_value = str(password or "")
    if not password_value:
        raise TradeError("提取密码不能为空")
    if len(password_value) < PASSWORD_MIN_LEN:
        raise TradeError("提取密码不能少于 6 位")
    if len(password_value) > 200:
        raise TradeError("提取密码过长")
    updated_at = _now()
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise TradeError("CDK 不存在", status_code=404)
        used_count = _cdk_used_count(conn, code)
        _assert_cdk_redeemable(row, used_count, 1)
        if row["password_hash"]:
            raise TradeError("CDK 已设置提取密码", status_code=409)
        salt, password_hash = _hash_password(password_value)
        conn.execute(
            """
            UPDATE plus_cdks
            SET password_salt = ?, password_hash = ?, password_plain = ?, updated_at = ?
            WHERE code = ?
            """,
            (salt, password_hash, password_value, updated_at, code),
        )
        row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        cdk = _row_to_cdk(row, used_count=used_count, latest_redeemed_at=_cdk_latest_redeemed_at(conn, code))
    return {
        "code": cdk["code"],
        "quota_total": cdk["quota_total"],
        "used_count": cdk["used_count"],
        "remaining": cdk["remaining"],
        "password_set": cdk["password_set"],
        "status": cdk["status"],
        "active": cdk["active"],
        "expires_at": cdk["expires_at"],
    }


def _build_cpa_export(sources: list[dict]) -> dict:
    if len(sources) == 1:
        raw = sources[0]["content"].encode("utf-8")
        filename = safe_archive_member_name(
            sources[0]["filename"],
            fallback="auth.json",
            default_suffix=".json",
            allowed_suffixes={".json"},
        )
        content_type = "application/json"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            used_names = set()
            for source in sources:
                name = safe_archive_member_name(
                    source["filename"],
                    fallback="auth.json",
                    default_suffix=".json",
                    allowed_suffixes={".json"},
                )
                if name in used_names:
                    stem = Path(name).stem
                    suffix = Path(name).suffix or ".json"
                    name = safe_archive_member_name(
                        f"{stem}-{source['email']}{suffix}",
                        fallback="auth.json",
                        default_suffix=".json",
                        allowed_suffixes={".json"},
                        strip_paths=False,
                    )
                used_names.add(name)
                archive.writestr(name, source["content"])
        raw = buffer.getvalue()
        filename = f"cpa-auths-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        content_type = "application/zip"
    return {
        "filename": filename,
        "content_type": content_type,
        "content_base64": base64.b64encode(raw).decode("ascii"),
    }


def _build_sub_export(sources: list[dict]) -> dict:
    records = inspect_sources([(item["filename"], item["content"]) for item in sources])
    filename = generate_default_filename()
    try:
        payload = export_records(records, ExportSettings(output_filename=filename))
    except ConversionError as exc:
        raise TradeError(str(exc)) from exc
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "filename": filename,
        "content_type": "application/json",
        "content_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }


def _build_credentials_export(sources: list[dict]) -> dict:
    content = "\n".join(str(source.get("content") or "") for source in sources)
    raw = content.encode("utf-8")
    return {
        "filename": f"plus-credentials-{time.strftime('%Y%m%d-%H%M%S')}.txt",
        "content_type": "text/plain;charset=utf-8",
        "content_base64": base64.b64encode(raw).decode("ascii"),
    }


def _export_payload_for_format(format_value: str, sources: list[dict]) -> dict:
    if format_value == "cpa":
        return _build_cpa_export(sources)
    if format_value == "sub":
        return _build_sub_export(sources)
    return _build_credentials_export(sources)


def _decode_export_payload_base64(payload: dict, *, max_bytes: int | None = None) -> bytes:
    encoded = str((payload or {}).get("content_base64") or "")
    if not encoded:
        return b""
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise TradeError("导出内容编码无效") from exc
    max_allowed = EXPORT_PAYLOAD_MAX_BYTES if max_bytes is None else max_bytes
    if max_allowed > 0 and len(raw) > max_allowed:
        raise TradeError("导出内容过大")
    return raw


def _build_multi_export(exports: dict[str, dict]) -> dict:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for format_value, payload in exports.items():
            filename = safe_archive_member_name(payload["filename"], fallback=f"{format_value}.txt")
            raw = _decode_export_payload_base64(payload)
            archive.writestr(f"{format_value}/{filename}", raw)
    return {
        "filename": f"plus-accounts-{time.strftime('%Y%m%d-%H%M%S')}.zip",
        "content_type": "application/zip",
        "content_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


def _export_payload_from_bundle_sources(sources: list[dict], export_formats: list[str]) -> dict:
    exports = {
        format_value: _export_payload_for_format(
            format_value,
            [source["exports"][format_value] for source in sources],
        )
        for format_value in export_formats
    }
    return next(iter(exports.values())) if len(exports) == 1 else _build_multi_export(exports)


def download_cdk_redemption_batch(code: str, password: str, batch_id: str) -> dict:
    code = validate_code(code)
    batch_value = str(batch_id or "").strip()
    if not batch_value:
        raise TradeError("提取批次不能为空")
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        row = _authenticated_cdk_row(conn, code, password)
        records = conn.execute(
            """
            SELECT email, format, redeemed_at
            FROM plus_cdk_redemptions
            WHERE code = ? AND batch_id = ?
            ORDER BY id ASC
            """,
            (code, batch_value),
        ).fetchall()
        if not records:
            raise TradeError("提取历史不存在", status_code=404)
        export_formats = _formats_from_stored(records[0]["format"])
        emails = [_normalized_email(item["email"]) for item in records if _normalized_email(item["email"])]
        cdk = _row_to_cdk(row, used_count=_cdk_used_count(conn, code), latest_redeemed_at=_cdk_latest_redeemed_at(conn, code))

    sources = _bundle_sources_for_emails(emails, export_formats)
    payload = _export_payload_from_bundle_sources(sources, export_formats)
    return {
        "batch_id": batch_value,
        "code": code,
        "formats": export_formats,
        "format": export_formats[0],
        "count": len(sources),
        "emails": [source["email"] for source in sources],
        "redeemed_at": float(records[0]["redeemed_at"] or 0),
        "remaining": cdk["remaining"],
        "expires_at": cdk["expires_at"],
        **payload,
    }


def download_cdk_redemptions(code: str) -> dict:
    code = validate_code(code)
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise TradeError("CDK 不存在", status_code=404)
        records = conn.execute(
            """
            SELECT batch_id, email, format, redeemed_at
            FROM plus_cdk_redemptions
            WHERE code = ?
            ORDER BY redeemed_at ASC, id ASC
            """,
            (code,),
        ).fetchall()
        if not records:
            raise TradeError("该 CDK 暂无提取记录", status_code=404)
        cdk = _row_to_cdk(row, used_count=_cdk_used_count(conn, code), latest_redeemed_at=_cdk_latest_redeemed_at(conn, code))

    batches: dict[str, dict] = {}
    batch_order: list[str] = []
    for record in records:
        batch_id = str(record["batch_id"] or "").strip()
        if not batch_id:
            batch_id = "legacy"
        if batch_id not in batches:
            batch_order.append(batch_id)
            batches[batch_id] = {
                "batch_id": batch_id,
                "redeemed_at": float(record["redeemed_at"] or 0),
                "formats": _formats_from_stored(record["format"]),
                "emails": [],
            }
        email = _normalized_email(record["email"])
        if email:
            batches[batch_id]["emails"].append(email)

    manifest_batches = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, batch_id in enumerate(batch_order, start=1):
            batch = batches[batch_id]
            emails = list(dict.fromkeys(batch["emails"]))
            formats = ["cpa", "sub", "credentials"]
            sources = _bundle_sources_for_emails(emails, formats)
            payload = _export_payload_from_bundle_sources(sources, formats)
            raw = _decode_export_payload_base64(payload)
            folder = safe_archive_path_segment(
                f"{index:03d}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(batch['redeemed_at'] or 0))}-{batch_id[:8]}",
                fallback=f"{index:03d}-batch",
            )
            payload_filename = safe_archive_member_name(payload["filename"], fallback="redemption.zip")
            archive.writestr(f"{folder}/{payload_filename}", raw)
            archive.writestr(f"{folder}/emails.txt", "\n".join(source["email"] for source in sources))
            manifest_batches.append(
                {
                    "batch_id": batch_id,
                    "redeemed_at": batch["redeemed_at"],
                    "formats": formats,
                    "count": len(sources),
                    "emails": [source["email"] for source in sources],
                    "filename": f"{folder}/{payload_filename}",
                }
            )

        manifest = {
            "code": code,
            "quota_total": cdk["quota_total"],
            "used_count": cdk["used_count"],
            "remaining": cdk["remaining"],
            "latest_redeemed_at": cdk["latest_redeemed_at"],
            "batch_count": len(manifest_batches),
            "count": sum(batch["count"] for batch in manifest_batches),
            "batches": manifest_batches,
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return {
        "code": code,
        "batch_count": len(manifest_batches),
        "count": manifest["count"],
        "emails": [email for batch in manifest_batches for email in batch["emails"]],
        "filename": f"{code}-redemptions-{time.strftime('%Y%m%d-%H%M%S')}.zip",
        "content_type": "application/zip",
        "content_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


def redeem_cdk(code: str, password: str, count: int, export_format: str | list[str]) -> dict:
    code = validate_code(code)
    password_value = str(password or "")
    if not password_value:
        raise TradeError("提取密码不能为空")
    if len(password_value) < PASSWORD_MIN_LEN:
        raise TradeError("提取密码不能少于 6 位")
    if len(password_value) > 200:
        raise TradeError("提取密码过长")
    requested_count = int(count or 0)
    if requested_count <= 0:
        raise TradeError("提取数量必须大于 0")
    if requested_count > 500:
        raise TradeError("单次提取数量过大")
    export_formats = _normalize_export_formats(export_format)

    batch_id = uuid.uuid4().hex
    redeemed_at = _now()
    selected: list[dict] = []
    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM plus_cdks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise TradeError("CDK 不存在", status_code=404)
        used_count = _cdk_used_count(conn, code)
        remaining = _assert_cdk_redeemable(row, used_count, requested_count)
        if row["password_hash"]:
            if not _password_matches(password_value, row["password_salt"], row["password_hash"]):
                raise TradeError("提取密码错误", status_code=403)
        else:
            salt, password_hash = _hash_password(password_value)
            conn.execute(
            """
            UPDATE plus_cdks
                SET password_salt = ?, password_hash = ?, password_plain = ?, updated_at = ?
                WHERE code = ?
                """,
                (salt, password_hash, password_value, redeemed_at, code),
            )

        _clear_unexported_trade_allocations(conn)
        allocated = _allocated_emails(conn)
        candidates = _eligible_plus_bundle_sources(export_formats, allocated)
        if len(candidates) < requested_count:
            raise TradeError("Plus 库存不足")

        for source in candidates:
            if len(selected) >= requested_count:
                break
            cursor = conn.execute(
                "INSERT OR IGNORE INTO plus_cdk_allocations(email, code, allocated_at) VALUES (?, ?, ?)",
                (source["email"], code, redeemed_at),
            )
            if cursor.rowcount != 1:
                continue
            conn.execute(
                """
                INSERT INTO plus_cdk_redemptions(batch_id, code, email, format, redeemed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (batch_id, code, source["email"], ",".join(export_formats), redeemed_at),
            )
            selected.append(source)

        if len(selected) < requested_count:
            raise TradeError("Plus 库存竞争冲突，请重试")
        for source in selected:
            conn.execute(
                "UPDATE accounts SET credentials_exported = 1, updated_at = ? WHERE lower(email) = ?",
                (redeemed_at, source["email"]),
            )
        if requested_count >= remaining:
            conn.execute(
                "UPDATE plus_cdks SET status = 'exhausted', updated_at = ? WHERE code = ?",
                (redeemed_at, code),
            )

    from autotoken.storage.accounts import update_account

    for source in selected:
        update_account(source["email"], credentials_exported=True, credentials_exported_at=redeemed_at)

    export_payload = _export_payload_from_bundle_sources(selected, export_formats)
    cdk = get_cdk(code)
    return {
        "batch_id": batch_id,
        "code": code,
        "format": export_formats[0],
        "formats": export_formats,
        "count": len(selected),
        "emails": [source["email"] for source in selected],
        "redeemed_at": redeemed_at,
        "remaining": cdk["remaining"],
        "expires_at": cdk["expires_at"],
        **export_payload,
    }
