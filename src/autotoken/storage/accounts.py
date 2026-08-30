"""账号池管理 - 通过 SQLite 持久化存储所有账号状态。

运行时只读写 ``data/autotoken.sqlite3``。旧版 ``accounts.json`` 需要通过
``scripts/migrate_to_sqlite.py`` 手动迁移，避免启动时隐式合并旧数据造成误删或卡顿。
"""

import json
import sys
import threading
import time
from pathlib import Path

from autotoken.core.normalization import normalized_email as _core_normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.services.totp import TOTPSecretError, mask_totp_secret, normalize_totp_secret
from autotoken.settings.admin_state import get_admin_email
from autotoken.storage import sqlite_store

ACCOUNTS_FILE = PROJECT_ROOT / "accounts.json"

# 账号状态
STATUS_ACTIVE = "active"  # 在 team 中，额度可用
STATUS_EXHAUSTED = "exhausted"  # 在 team 中，额度用完
STATUS_STANDBY = "standby"  # 已移出 team，等待额度恢复
STATUS_STASHED = "stashed"  # 暂存，不参与自动处理
STATUS_PENDING = "pending"  # 已邀请，等待注册完成
STATUS_PERSONAL = "personal"  # 已主动退出 team，走个人号 Codex OAuth，不再参与 Team 轮转
STATUS_PLUS = "plus"  # 已通过 GoPay/支付流程升级为 Plus，不再参与号池选择
STATUS_AUTH_INVALID = "auth_invalid"  # auth_file token 已不可用(401/403),待 reconcile 清理或重登
STATUS_AUTH_REVOKED = "auth_revoked"  # access token 掉授权(token_revoked)，需补登录，不等于废弃
STATUS_ORPHAN = "orphan"  # 在 workspace 里占着席位,但本地没 auth_file(残废,待人工介入或兜底 kick)
STATUS_FAIL = "fail"  # 已废弃账号,不再参与号池/轮转
STATUS_SESSION_ONLY = "session_only"  # 旧状态兼容：新逻辑不再写入，auth_session-only 账号也显示 active

# 账号类型:和运行状态分离。新注册账号默认 Free；Team/Plus/Pro 用于前端选择和业务过滤。
ACCOUNT_TYPE_FREE = "free"
ACCOUNT_TYPE_TEAM = "team"
ACCOUNT_TYPE_PLUS = "plus"
ACCOUNT_TYPE_PRO = "pro"

# 席位类型:标记该账号在 ChatGPT Team 里被授予的席位种类,用于下游 fill / check 区分对待
SEAT_CHATGPT = "chatgpt"  # 完整 ChatGPT 席位(PATCH invite seat_type=default 成功)
SEAT_CODEX = "codex"  # 仅 Codex 席位(usage_based,PATCH 改 default 失败时保留的兜底)
SEAT_UNKNOWN = "unknown"  # 未知/未记录,老账号或手动导入默认值

ACCOUNT_SOURCE_MANAGED = "managed"
ACCOUNT_SOURCE_AUTH_SESSION_STUB = "auth_session_stub"

TOTP_STATUS_DISABLED = "disabled"
TOTP_STATUS_ENABLED = "enabled"
TOTP_STATUS_RECOVERY_REQUIRED = "recovery_required"
_accounts_write_lock = threading.RLock()


def _invalidate_payment_account_caches() -> None:
    try:
        module = sys.modules.get("autotoken.api_routes.brazil_pix")
        if module is not None:
            module.clear_auth_accounts_cache()
    except Exception:
        pass


def _normalized_email(value):
    return _core_normalized_email(value)


def _is_main_account_email(email):
    return bool(_normalized_email(email)) and _normalized_email(email) == _normalized_email(get_admin_email())


def _db_path() -> Path:
    configured = sqlite_store.default_db_path()
    # Tests commonly monkeypatch ACCOUNTS_FILE to tmp_path/accounts.json. Keep
    # those fixtures isolated without requiring every test to patch DB_FILE too.
    try:
        if Path(ACCOUNTS_FILE).resolve() != (PROJECT_ROOT / "accounts.json").resolve():
            return Path(ACCOUNTS_FILE).with_suffix(".sqlite3")
    except Exception:
        pass
    return configured


def _normalize_account_record(account: dict) -> dict:
    acc = dict(account or {})
    raw_email = str(acc.get("email") or "").strip()
    original_email = str(acc.get("original_email") or acc.get("display_email") or "").strip()
    acc["email"] = _normalized_email(raw_email)
    if not original_email and raw_email and raw_email != acc["email"]:
        original_email = raw_email
    acc["original_email"] = original_email or acc["email"]
    acc.setdefault("password", "")
    acc.setdefault("cloudmail_account_id", None)
    acc.setdefault("mail_provider", None)
    acc.setdefault("mailapi_url", None)
    acc.setdefault("status", STATUS_PENDING)
    acc.setdefault("account_type", ACCOUNT_TYPE_FREE)
    acc.setdefault("seat_type", SEAT_UNKNOWN)
    acc.setdefault("auth_file", None)
    acc.setdefault("quota_exhausted_at", None)
    acc.setdefault("quota_resets_at", None)
    acc.setdefault("last_quota_check_at", None)
    acc.setdefault("created_at", time.time())
    acc.setdefault("last_active_at", None)
    acc.setdefault("last_bind_status", "")
    acc.setdefault("last_bind_at", None)
    acc.setdefault("last_bind_provider", "")
    acc.setdefault("last_checkout_url", "")
    acc.setdefault("last_card_id", "")
    acc.setdefault("last_proxy_label", "")
    acc.setdefault("last_bind_task_id", "")
    acc.setdefault("last_bind_message", "")
    acc.setdefault("last_bind_failure_stage", "")
    acc.setdefault("kakao_link_extracted", False)
    acc.setdefault("kakao_link_extracted_at", None)
    acc.setdefault("kakao_link_expires_at", None)
    acc.setdefault("kakao_link_cs_id", "")
    acc.setdefault("kakao_link_job_id", "")
    acc.setdefault("credentials_exported", False)
    acc.setdefault("credentials_exported_at", None)
    acc.setdefault("account_source", ACCOUNT_SOURCE_MANAGED)
    acc.setdefault("two_factor_enabled", False)
    acc.setdefault("totp_status", TOTP_STATUS_DISABLED)
    acc.setdefault("totp_secret_masked", "")
    acc.setdefault("totp_enabled_at", None)
    acc.setdefault("totp_issuer", "")
    acc.setdefault("totp_factor_label", "")
    return acc


def _public_account(account: dict) -> dict:
    public = dict(account or {})
    public.pop("totp_secret", None)
    public.pop("totp_otpauth_uri", None)
    return public


def _row_to_account(row, *, include_private: bool = False) -> dict:
    data = {}
    try:
        data = json.loads(row["data"] or "{}")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.update(
        {
            "email": row["email"],
            "status": row["status"],
            "account_type": row["account_type"],
            "seat_type": row["seat_type"],
            "password": row["password"],
            "cloudmail_account_id": data.get("cloudmail_account_id", row["cloudmail_account_id"]),
            "mail_provider": data.get("mail_provider", row["mail_provider"]),
            "mailapi_url": data.get("mailapi_url"),
            "auth_file": data.get("auth_file", row["auth_file"]),
            "credentials_exported": bool(row["credentials_exported"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )
    normalized = _normalize_account_record(data)
    return normalized if include_private else _public_account(normalized)


def _upsert_account(conn, account: dict) -> None:
    acc = _normalize_account_record(account)
    if not acc.get("email"):
        return
    data = dict(acc)
    now = time.time()
    conn.execute(
        """
        INSERT INTO accounts (
            email, status, account_type, seat_type, password, cloudmail_account_id,
            mail_provider, auth_file, credentials_exported, created_at, updated_at, data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            status=excluded.status,
            account_type=excluded.account_type,
            seat_type=excluded.seat_type,
            password=excluded.password,
            cloudmail_account_id=excluded.cloudmail_account_id,
            mail_provider=excluded.mail_provider,
            auth_file=excluded.auth_file,
            credentials_exported=excluded.credentials_exported,
            created_at=excluded.created_at,
            updated_at=excluded.updated_at,
            data=excluded.data
        """,
        (
            acc["email"],
            str(acc.get("status") or STATUS_PENDING),
            str(acc.get("account_type") or ACCOUNT_TYPE_FREE),
            str(acc.get("seat_type") or SEAT_UNKNOWN),
            str(acc.get("password") or ""),
            None if acc.get("cloudmail_account_id") is None else str(acc.get("cloudmail_account_id")),
            acc.get("mail_provider"),
            acc.get("auth_file"),
            1 if bool(acc.get("credentials_exported")) else 0,
            acc.get("created_at") or now,
            now,
            json.dumps(data, ensure_ascii=False),
        ),
    )


def _get_account_by_email(conn, email: str, *, include_private: bool = False) -> dict | None:
    target = _normalized_email(email)
    if not target:
        return None
    row = conn.execute("SELECT * FROM accounts WHERE email = ?", (target,)).fetchone()
    return _row_to_account(row, include_private=include_private) if row else None


def load_accounts():
    """加载账号列表"""
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY rowid").fetchall()
        return [_row_to_account(row) for row in rows]


def save_accounts(accounts):
    """保存账号列表"""
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            conn.execute("DELETE FROM accounts")
            for account in accounts or []:
                _upsert_account(conn, account)
    _invalidate_payment_account_caches()


def mark_accounts_hub_synced(account_versions, *, synced_at: float | None = None) -> int:
    """Atomically mark uploaded rows only when their stored versions still match."""
    targets = []
    seen = set()
    for value in account_versions or []:
        if not isinstance(value, dict):
            continue
        email = _normalized_email(value.get("email"))
        if not email or email in seen:
            continue
        try:
            uploaded_updated_at = float(value.get("updated_at"))
        except (TypeError, ValueError):
            continue
        seen.add(email)
        targets.append((email, uploaded_updated_at))
    if not targets:
        return 0

    timestamp = float(time.time() if synced_at is None else synced_at)
    updated = 0
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for email, uploaded_updated_at in targets:
                account = _get_account_by_email(conn, email, include_private=True)
                if not account or float(account.get("updated_at")) != uploaded_updated_at:
                    continue
                account["account_hub_synced"] = True
                account["account_hub_synced_at"] = timestamp
                _upsert_account(conn, account)
                updated += 1
    if updated:
        _invalidate_payment_account_caches()
    return updated


def find_account(accounts, email):
    """按邮箱查找账号"""
    target = _normalized_email(email)
    for acc in accounts:
        if _normalized_email(acc.get("email")) == target:
            return acc
    return None


def add_account(email, password, cloudmail_account_id=None, seat_type=SEAT_UNKNOWN, mail_provider=None, mailapi_url=None):
    """添加新账号。seat_type 取值见 SEAT_CHATGPT / SEAT_CODEX / SEAT_UNKNOWN。"""
    normalized = _normalized_email(email)
    if not normalized:
        return
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            existing = _get_account_by_email(conn, normalized, include_private=True)
            if existing:
                changed = False
                # 已存在仍允许补写注册来源信息。auth_session stub 由真实注册流程接管后恢复为 managed。
                desired = {}
                if password and not existing.get("password"):
                    desired["password"] = password
                if cloudmail_account_id and not existing.get("cloudmail_account_id"):
                    desired["cloudmail_account_id"] = cloudmail_account_id
                if seat_type and seat_type != SEAT_UNKNOWN:
                    desired["seat_type"] = seat_type
                if mail_provider and not existing.get("mail_provider"):
                    desired["mail_provider"] = mail_provider
                if mailapi_url and not existing.get("mailapi_url"):
                    desired["mailapi_url"] = mailapi_url
                raw_email = str(email or "").strip()
                if raw_email and raw_email != normalized and not existing.get("original_email"):
                    desired["original_email"] = raw_email
                if existing.get("account_source") == ACCOUNT_SOURCE_AUTH_SESSION_STUB:
                    desired["account_source"] = ACCOUNT_SOURCE_MANAGED
                for key, value in desired.items():
                    if existing.get(key) != value:
                        existing[key] = value
                        changed = True
                if changed:
                    _upsert_account(conn, existing)
                    _invalidate_payment_account_caches()
                return

            _upsert_account(
                conn,
                {
                    "email": normalized,
                    "original_email": str(email or "").strip() or normalized,
                    "password": password,
                    "cloudmail_account_id": cloudmail_account_id,
                    "mail_provider": mail_provider or None,
                    "mailapi_url": mailapi_url or None,
                    "status": STATUS_PENDING,
                    "account_type": ACCOUNT_TYPE_FREE,
                    "seat_type": seat_type or SEAT_UNKNOWN,
                    "auth_file": None,  # CPA 认证文件路径
                    "quota_exhausted_at": None,  # 额度用完的时间
                    "quota_resets_at": None,  # 额度恢复时间
                    "last_quota_check_at": None,  # 最近一次 wham/usage 探测时间戳,用于 standby 探测去重
                    "created_at": time.time(),
                    "last_active_at": None,
                    "last_bind_status": "",
                    "last_bind_at": None,
                    "last_bind_provider": "",
                    "last_checkout_url": "",
                    "last_card_id": "",
                    "last_proxy_label": "",
                    "last_bind_task_id": "",
                    "last_bind_message": "",
                    "last_bind_failure_stage": "",
                    "credentials_exported": False,
                    "credentials_exported_at": None,
                    "account_source": ACCOUNT_SOURCE_MANAGED,
                },
            )
            _invalidate_payment_account_caches()
            return


def ensure_session_only_account(email):
    """把仅有 auth_session 的账号显式写入账号池，便于前端和清理逻辑统一处理。"""
    normalized = _normalized_email(email)
    if not normalized:
        return None
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            existing = _get_account_by_email(conn, normalized, include_private=True)
            if existing:
                if (
                    existing.get("account_source") == ACCOUNT_SOURCE_AUTH_SESSION_STUB
                    or existing.get("status") == STATUS_SESSION_ONLY
                ):
                    # A stale stub marker must not downgrade an account that has
                    # already been upgraded or has a real CPA/Codex auth file.
                    account_type = str(existing.get("account_type") or "").strip().lower()
                    if account_type in {ACCOUNT_TYPE_PLUS, ACCOUNT_TYPE_PRO, ACCOUNT_TYPE_TEAM} or existing.get("auth_file"):
                        desired = {
                            "status": STATUS_ACTIVE,
                            "account_source": ACCOUNT_SOURCE_MANAGED,
                        }
                    else:
                        desired = {
                            "status": STATUS_ACTIVE,
                            "account_type": ACCOUNT_TYPE_FREE,
                            "seat_type": SEAT_CODEX,
                            "account_source": ACCOUNT_SOURCE_AUTH_SESSION_STUB,
                        }
                    changed = False
                    for key, value in desired.items():
                        if existing.get(key) != value:
                            existing[key] = value
                            changed = True
                    if changed:
                        _upsert_account(conn, existing)
                        existing = _get_account_by_email(conn, normalized, include_private=True) or existing
                        _invalidate_payment_account_caches()
                return _public_account(existing)

            stub = {
                "email": normalized,
                "password": "",
                "cloudmail_account_id": None,
                "mail_provider": None,
                "status": STATUS_ACTIVE,
                "account_type": ACCOUNT_TYPE_FREE,
                "seat_type": SEAT_CODEX,
                "auth_file": None,
                "quota_exhausted_at": None,
                "quota_resets_at": None,
                "last_quota_check_at": None,
                "created_at": time.time(),
                "last_active_at": None,
                "last_bind_status": "",
                "last_bind_at": None,
                "last_bind_provider": "",
                "last_checkout_url": "",
                "last_card_id": "",
                "last_proxy_label": "",
                "last_bind_task_id": "",
                "last_bind_message": "",
                "last_bind_failure_stage": "",
                "credentials_exported": False,
                "credentials_exported_at": None,
                "account_source": ACCOUNT_SOURCE_AUTH_SESSION_STUB,
            }
            _upsert_account(conn, stub)
            created = _get_account_by_email(conn, normalized)
            _invalidate_payment_account_caches()
            return created


def reconcile_auth_session_accounts(
    session_emails,
    *,
    indexed_auth_files=None,
    gopay_success_emails=None,
):
    """Persist and upgrade auth-session accounts in one SQLite transaction."""
    targets = []
    seen = set()
    for value in session_emails or []:
        email = _normalized_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        targets.append(email)
    if not targets:
        return {}

    indexed = {
        email: str(path or "").strip()
        for raw_email, path in (indexed_auth_files or {}).items()
        if (email := _normalized_email(raw_email))
    }
    gopay = {
        email
        for value in (gopay_success_emails or set())
        if (email := _normalized_email(value))
    }
    reconciled = {}
    changed = False

    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            existing = {}
            for start in range(0, len(targets), 500):
                chunk = targets[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM accounts WHERE email IN ({placeholders})",
                    chunk,
                ).fetchall()
                existing.update(
                    {
                        str(row["email"] or "").strip().lower(): _row_to_account(row, include_private=True)
                        for row in rows
                    }
                )

            for email in targets:
                account = existing.get(email)
                indexed_auth_file = indexed.get(email, "")
                has_managed_evidence = bool(indexed_auth_file or email in gopay)
                if account is None:
                    account = {
                        "email": email,
                        "password": "",
                        "cloudmail_account_id": None,
                        "mail_provider": None,
                        "status": STATUS_ACTIVE,
                        "account_type": ACCOUNT_TYPE_PLUS if email in gopay else ACCOUNT_TYPE_FREE,
                        "seat_type": SEAT_CODEX,
                        "auth_file": indexed_auth_file or None,
                        "quota_exhausted_at": None,
                        "quota_resets_at": None,
                        "last_quota_check_at": None,
                        "created_at": time.time(),
                        "last_active_at": None,
                        "last_bind_status": "",
                        "last_bind_at": None,
                        "last_bind_provider": "",
                        "last_checkout_url": "",
                        "last_card_id": "",
                        "last_proxy_label": "",
                        "last_bind_task_id": "",
                        "last_bind_message": "",
                        "last_bind_failure_stage": "",
                        "credentials_exported": False,
                        "credentials_exported_at": None,
                        "account_source": (
                            ACCOUNT_SOURCE_MANAGED if has_managed_evidence else ACCOUNT_SOURCE_AUTH_SESSION_STUB
                        ),
                    }
                    _upsert_account(conn, account)
                    changed = True
                elif (
                    str(account.get("account_source") or "").strip().lower()
                    == ACCOUNT_SOURCE_AUTH_SESSION_STUB
                    or str(account.get("status") or "").strip().lower() == STATUS_SESSION_ONLY
                ):
                    account_type = str(account.get("account_type") or "").strip().lower()
                    already_managed = account_type in {
                        ACCOUNT_TYPE_PLUS,
                        ACCOUNT_TYPE_PRO,
                        ACCOUNT_TYPE_TEAM,
                    } or bool(account.get("auth_file"))
                    if already_managed or has_managed_evidence:
                        desired = {
                            "status": STATUS_ACTIVE,
                            "account_type": (
                                ACCOUNT_TYPE_PLUS
                                if email in gopay
                                else (account.get("account_type") or ACCOUNT_TYPE_FREE)
                            ),
                            "seat_type": account.get("seat_type") or SEAT_CODEX,
                            "auth_file": indexed_auth_file or account.get("auth_file"),
                            "account_source": ACCOUNT_SOURCE_MANAGED,
                        }
                        if has_managed_evidence:
                            desired.update(
                                {
                                    "account_hub_synced": False,
                                    "account_hub_synced_at": None,
                                }
                            )
                    else:
                        desired = {
                            "status": STATUS_ACTIVE,
                            "account_type": ACCOUNT_TYPE_FREE,
                            "seat_type": SEAT_CODEX,
                            "account_source": ACCOUNT_SOURCE_AUTH_SESSION_STUB,
                        }
                    if any(account.get(key) != value for key, value in desired.items()):
                        account.update(desired)
                        _upsert_account(conn, account)
                        changed = True

            persisted = {}
            for start in range(0, len(targets), 500):
                chunk = targets[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM accounts WHERE email IN ({placeholders})",
                    chunk,
                ).fetchall()
                persisted.update(
                    {
                        str(row["email"] or "").strip().lower(): _row_to_account(row)
                        for row in rows
                    }
                )
            reconciled = {email: persisted[email] for email in targets if email in persisted}

    if changed:
        _invalidate_payment_account_caches()
    return reconciled


def update_account(email, **kwargs):
    """更新账号字段"""
    hub_dirty_keys = {
        "status",
        "account_type",
        "seat_type",
        "password",
        "cloudmail_account_id",
        "mail_provider",
        "auth_file",
        "last_active_at",
        "last_bind_status",
        "last_bind_at",
        "last_bind_provider",
        "last_checkout_url",
        "last_card_id",
        "last_proxy_label",
        "last_bind_task_id",
        "last_bind_message",
        "last_bind_failure_stage",
        "kakao_link_extracted",
        "kakao_link_extracted_at",
        "kakao_link_expires_at",
        "kakao_link_cs_id",
        "kakao_link_job_id",
        "plus_bound_at",
        "quota_exhausted_at",
        "quota_resets_at",
        "last_quota_check_at",
        "account_source",
    }
    if any(key in kwargs for key in hub_dirty_keys) and "account_hub_synced" not in kwargs:
        kwargs["account_hub_synced"] = False
        kwargs["account_hub_synced_at"] = None
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            acc = _get_account_by_email(conn, email, include_private=True)
            if acc:
                acc.update(kwargs)
                _upsert_account(conn, acc)
                updated = _get_account_by_email(conn, email) or _public_account(acc)
                _invalidate_payment_account_caches()
                return updated
            return None


def update_accounts_export_status_batch(emails, *, exported: bool, exported_at: float | None) -> dict:
    """Update export state and release trade allocations in one transaction."""
    targets = []
    seen = set()
    for value in emails or []:
        email = _normalized_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        targets.append(email)
    if not targets:
        return {
            "accounts": [],
            "missing": [],
            "trade_allocations": {"cleared": 0, "codes": []},
        }

    updated_emails = []
    missing = []
    allocation_rows = []
    persisted = {}
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = {}
            for start in range(0, len(targets), 500):
                chunk = targets[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM accounts WHERE email IN ({placeholders})",
                    chunk,
                ).fetchall()
                existing.update(
                    {
                        _normalized_email(row["email"]): _row_to_account(row, include_private=True)
                        for row in rows
                    }
                )

            for email in targets:
                account = existing.get(email)
                if account is None:
                    missing.append(email)
                    continue
                account["credentials_exported"] = bool(exported)
                account["credentials_exported_at"] = exported_at if exported else None
                _upsert_account(conn, account)
                updated_emails.append(email)

            if not exported:
                for start in range(0, len(updated_emails), 500):
                    chunk = updated_emails[start : start + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    allocation_rows.extend(
                        conn.execute(
                            f"SELECT email, code FROM plus_cdk_allocations WHERE email IN ({placeholders})",
                            chunk,
                        ).fetchall()
                    )
                    conn.execute(
                        f"DELETE FROM plus_cdk_allocations WHERE email IN ({placeholders})",
                        chunk,
                    )

            for start in range(0, len(updated_emails), 500):
                chunk = updated_emails[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM accounts WHERE email IN ({placeholders})",
                    chunk,
                ).fetchall()
                persisted.update(
                    {
                        _normalized_email(row["email"]): _row_to_account(row)
                        for row in rows
                    }
                )

    if updated_emails:
        _invalidate_payment_account_caches()
    return {
        "accounts": [persisted[email] for email in updated_emails if email in persisted],
        "missing": missing,
        "trade_allocations": {
            "cleared": len(allocation_rows),
            "codes": sorted({str(row["code"] or "") for row in allocation_rows if row["code"]}),
        },
    }


def replace_account_email(old_email, new_email, **kwargs):
    """Move an account row to a new email key while preserving existing metadata."""
    old_target = _normalized_email(old_email)
    new_target = _normalized_email(new_email)
    if not old_target or not new_target:
        return None
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            old_acc = _get_account_by_email(conn, old_target, include_private=True)
            if not old_acc:
                return None
            existing_new = _get_account_by_email(conn, new_target, include_private=True)
            merged = dict(existing_new or {})
            merged.update(old_acc)
            merged.update(kwargs)
            merged["email"] = new_target
            _upsert_account(conn, merged)
            if old_target != new_target:
                conn.execute("DELETE FROM accounts WHERE email = ?", (old_target,))
            updated = _get_account_by_email(conn, new_target) or _public_account(merged)
            _invalidate_payment_account_caches()
            return updated


def delete_account(email):
    """从账号池彻底移除（不动认证文件、不动临时邮箱账户）。返回是否真的删除了记录。"""
    target = _normalized_email(email)
    if not target:
        return False
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        cursor = conn.execute("DELETE FROM accounts WHERE email = ?", (target,))
        deleted = cursor.rowcount > 0
    if deleted:
        _invalidate_payment_account_caches()
    return deleted


def get_active_accounts():
    """获取所有活跃账号"""
    return [a for a in load_accounts() if a["status"] == STATUS_ACTIVE and not _is_main_account_email(a.get("email"))]


def get_personal_accounts():
    """获取所有已退出 Team、走个人 Codex 授权的账号（不参与席位轮转）"""
    return [a for a in load_accounts() if a["status"] == STATUS_PERSONAL and not _is_main_account_email(a.get("email"))]


def get_standby_accounts():
    """获取所有待命账号（已移出 team，可能额度已恢复）"""
    accounts = load_accounts()
    now = time.time()
    standby = []
    for a in accounts:
        if _is_main_account_email(a.get("email")):
            continue
        if a["status"] == STATUS_STANDBY:
            resets_at = a.get("quota_resets_at")
            if resets_at is None:
                # 没有恢复时间 = 不是因为额度用完被移出的，随时可复用
                a["_quota_recovered"] = True
            else:
                # 有恢复时间，看是否已过
                a["_quota_recovered"] = now >= resets_at
            standby.append(a)
    # 已恢复的排前面
    standby.sort(key=lambda x: (not x.get("_quota_recovered", False), x.get("quota_exhausted_at") or 0))
    return standby


def get_next_reusable_account():
    """获取下一个可重用的 standby 账号（优先额度已恢复的）"""
    standby = get_standby_accounts()
    if standby:
        return standby[0]
    return None

def save_totp_metadata(
    email: str,
    *,
    secret: str,
    otpauth_uri: str = "",
    issuer: str = "",
    factor_label: str = "",
    enabled_at: float | None = None,
    status: str = TOTP_STATUS_ENABLED,
) -> dict | None:
    """Persist account-level TOTP credentials and return the public account view."""
    try:
        normalized_secret = normalize_totp_secret(secret)
    except TOTPSecretError as exc:
        raise ValueError(str(exc)) from exc

    target = _normalized_email(email)
    if not target:
        return None

    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            acc = _get_account_by_email(conn, target, include_private=True)
            if not acc:
                return None
            acc.update(
                {
                    "two_factor_enabled": status == TOTP_STATUS_ENABLED,
                    "totp_status": status,
                    "totp_secret": normalized_secret,
                    "totp_secret_masked": mask_totp_secret(normalized_secret),
                    "totp_otpauth_uri": str(otpauth_uri or ""),
                    "totp_issuer": str(issuer or ""),
                    "totp_factor_label": str(factor_label or ""),
                    "totp_enabled_at": enabled_at if enabled_at is not None else time.time(),
                }
            )
            _upsert_account(conn, acc)
            return _get_account_by_email(conn, target)


def mark_totp_recovery_required(email: str) -> dict | None:
    """Record that remote MFA is enabled but the local secret is unavailable."""
    return update_account(
        email,
        two_factor_enabled=True,
        totp_status=TOTP_STATUS_RECOVERY_REQUIRED,
        totp_secret_masked="",
        totp_enabled_at=time.time(),
    )


def get_totp_credentials(email: str) -> dict | None:
    """Return raw TOTP credentials for privileged login/setup handlers only."""
    target = _normalized_email(email)
    if not target:
        return None
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        acc = _get_account_by_email(conn, target, include_private=True)
    if not acc or not acc.get("two_factor_enabled") or not acc.get("totp_secret"):
        return None
    return {
        "email": target,
        "secret": str(acc.get("totp_secret") or ""),
        "masked_secret": str(acc.get("totp_secret_masked") or ""),
        "otpauth_uri": str(acc.get("totp_otpauth_uri") or ""),
        "issuer": str(acc.get("totp_issuer") or ""),
        "factor_label": str(acc.get("totp_factor_label") or ""),
        "enabled_at": acc.get("totp_enabled_at"),
        "status": str(acc.get("totp_status") or TOTP_STATUS_DISABLED),
    }
