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

from autoteam import sqlite_store
from autoteam.accounts import ACCOUNT_TYPE_PLUS, STATUS_ACTIVE, STATUS_AUTH_INVALID, STATUS_FAIL, STATUS_ORPHAN
from autoteam.auth_storage import AUTH_DIR
from autoteam.sub2api_converter import (
    ConversionError,
    ExportSettings,
    export_records,
    generate_default_filename,
    inspect_sources,
)
from autoteam.textio import read_text

CDK_TTL_SECONDS = 24 * 60 * 60
CDK_PREFIX = "PLUS-"
CDK_BODY_LEN = 12
CDK_RE = re.compile(r"^PLUS-[A-Z0-9]{12}$")
PASSWORD_ITERATIONS = 210_000
PASSWORD_MIN_LEN = 6
EXPORT_FORMATS = {"cpa", "sub", "credentials"}
EXCLUDED_ACCOUNT_STATUSES = {STATUS_FAIL, STATUS_AUTH_INVALID, STATUS_ORPHAN}


class TradeError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def normalize_code(value: str) -> str:
    return str(value or "").strip().upper()


def validate_code(value: str) -> str:
    code = normalize_code(value)
    if not CDK_RE.match(code):
        raise TradeError("CDK 格式无效")
    return code


def _now() -> float:
    return time.time()


def _random_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return CDK_PREFIX + "".join(secrets.choice(alphabet) for _ in range(CDK_BODY_LEN))


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
            code = _random_code()
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


def _allocated_emails(conn) -> set[str]:
    from autoteam.accounts import load_accounts

    exported_emails = {
        str(account.get("email") or "").strip().lower()
        for account in load_accounts()
        if bool(account.get("credentials_exported"))
    }
    return {
        email
        for email in (
            str(row["email"] or "").strip().lower()
            for row in conn.execute("SELECT email FROM plus_cdk_allocations")
        )
        if email and email in exported_emails
    }


def _clear_unexported_trade_allocations(conn) -> int:
    from autoteam.accounts import load_accounts

    reusable_emails = [
        str(account.get("email") or "").strip().lower()
        for account in load_accounts()
        if str(account.get("email") or "").strip() and not bool(account.get("credentials_exported"))
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
        path = Path(auth_file)
        if path.exists() and path.is_file():
            try:
                path.resolve().relative_to(AUTH_DIR.resolve())
                return str(path)
            except Exception:
                pass
    email = str(account.get("email") or "").strip().lower()
    if not email:
        return ""
    try:
        matches = sorted(AUTH_DIR.glob(f"codex-{email}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
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


def _source_for_account(account: dict, export_format: str) -> dict | None:
    email = str(account.get("email") or "").strip().lower()
    auth_file = _resolve_codex_auth_file(account)
    if not email or not auth_file:
        return None
    path = Path(auth_file)
    try:
        content = read_text(path)
        json.loads(content)
        if export_format == "credentials":
            password = credential_password_for_account(account)
            if not password:
                return None
            return {
                "email": email,
                "filename": f"{email}.txt",
                "content": f"{email}-----{password}",
                "password": password,
            }
        if export_format == "sub":
            records = inspect_sources([(path.name, content)])
            if not any(record.is_valid for record in records):
                return None
    except Exception:
        return None
    return {"email": email, "filename": path.name, "content": content}


def _eligible_plus_sources(export_format: str, allocated: set[str]) -> list[dict]:
    from autoteam.accounts import load_accounts
    from autoteam.admin_state import get_admin_email

    main_email = str(get_admin_email() or "").strip().lower()
    sources = []
    for account in load_accounts():
        email = str(account.get("email") or "").strip().lower()
        if not email or email == main_email or email in allocated:
            continue
        if str(account.get("account_type") or "").strip().lower() != ACCOUNT_TYPE_PLUS:
            continue
        if str(account.get("status") or "").strip().lower() != STATUS_ACTIVE:
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
    from autoteam.accounts import load_accounts
    from autoteam.admin_state import get_admin_email

    main_email = str(get_admin_email() or "").strip().lower()
    sources = []
    for account in load_accounts():
        email = str(account.get("email") or "").strip().lower()
        if not email or email == main_email or email in allocated:
            continue
        if str(account.get("account_type") or "").strip().lower() != ACCOUNT_TYPE_PLUS:
            continue
        if str(account.get("status") or "").strip().lower() != STATUS_ACTIVE:
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


def _is_plus_account(account: dict, main_email: str) -> bool:
    email = str(account.get("email") or "").strip().lower()
    return bool(
        email
        and email != main_email
        and str(account.get("account_type") or "").strip().lower() == ACCOUNT_TYPE_PLUS
    )


def _has_valid_codex_auth(account: dict) -> bool:
    return _source_for_account(account, "cpa") is not None


def inventory_summary() -> dict:
    from autoteam.accounts import load_accounts
    from autoteam.admin_state import get_admin_email

    sqlite_store.initialize()
    with sqlite_store.connect() as conn:
        _clear_unexported_trade_allocations(conn)
        allocated = _allocated_emails(conn)
    stock_sources = _eligible_plus_sources("cpa", allocated)
    cdks = list_cdks()
    main_email = str(get_admin_email() or "").strip().lower()
    plus_accounts = [account for account in load_accounts() if _is_plus_account(account, main_email)]
    exported_count = sum(1 for account in plus_accounts if bool(account.get("credentials_exported")))
    discarded_count = sum(
        1
        for account in plus_accounts
        if str(account.get("status") or "").strip().lower() in EXCLUDED_ACCOUNT_STATUSES
    )
    missing_credentials_count = sum(
        1
        for account in plus_accounts
        if str(account.get("status") or "").strip().lower() == STATUS_ACTIVE
        and not bool(account.get("credentials_exported"))
        and str(account.get("email") or "").strip().lower() not in allocated
        and not _has_valid_codex_auth(account)
    )
    return {
        "stock_available": len(stock_sources),
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
        normalized = str(email or "").strip().lower()
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
        filename = sources[0]["filename"]
        content_type = "application/json"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            used_names = set()
            for source in sources:
                name = source["filename"]
                if name in used_names:
                    stem = Path(name).stem
                    suffix = Path(name).suffix or ".json"
                    name = f"{stem}-{source['email']}{suffix}"
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


def _build_multi_export(exports: dict[str, dict]) -> dict:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for format_value, payload in exports.items():
            filename = str(payload["filename"] or f"{format_value}.txt")
            raw = base64.b64decode(payload["content_base64"])
            archive.writestr(f"{format_value}/{filename}", raw)
    return {
        "filename": f"plus-accounts-{time.strftime('%Y%m%d-%H%M%S')}.zip",
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
        if requested_count >= remaining:
            conn.execute(
                "UPDATE plus_cdks SET status = 'exhausted', updated_at = ? WHERE code = ?",
                (redeemed_at, code),
            )

    from autoteam.accounts import update_account

    for source in selected:
        update_account(source["email"], credentials_exported=True, credentials_exported_at=redeemed_at)

    exports = {
        format_value: _export_payload_for_format(
            format_value,
            [source["exports"][format_value] for source in selected],
        )
        for format_value in export_formats
    }
    export_payload = next(iter(exports.values())) if len(exports) == 1 else _build_multi_export(exports)
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
