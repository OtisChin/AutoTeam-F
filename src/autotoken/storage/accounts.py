"""账号池管理 - 通过 SQLite 持久化存储所有账号状态。

运行时只读写 ``data/autotoken.sqlite3``。旧版 ``accounts.json`` 需要通过
``scripts/migrate_to_sqlite.py`` 手动迁移，避免启动时隐式合并旧数据造成误删或卡顿。
"""

import json
import threading
import time
from pathlib import Path

from autotoken.core.normalization import normalized_email as _core_normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.settings.admin_state import get_admin_email
from autotoken.storage import sqlite_store

ACCOUNTS_FILE = PROJECT_ROOT / "accounts.json"

# 账号状态
STATUS_ACTIVE = "active"  # 在 team 中，额度可用
STATUS_EXHAUSTED = "exhausted"  # 在 team 中，额度用完
STATUS_STANDBY = "standby"  # 已移出 team，等待额度恢复
STATUS_PENDING = "pending"  # 已邀请，等待注册完成
STATUS_PERSONAL = "personal"  # 已主动退出 team，走个人号 Codex OAuth，不再参与 Team 轮转
STATUS_PLUS = "plus"  # 已通过 GoPay/支付流程升级为 Plus，不再参与号池选择
STATUS_PAYPAL_ICE = "paypal_ice"  # 旧状态兼容：PayPal ICE 应记录为 last_bind_provider，账号状态仍为 active
STATUS_AUTH_INVALID = "auth_invalid"  # auth_file token 已不可用(401/403),待 reconcile 清理或重登
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
_accounts_write_lock = threading.RLock()

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
    if str(acc.get("status") or "").strip().lower() == STATUS_PAYPAL_ICE:
        acc["status"] = STATUS_ACTIVE
        acc["account_type"] = ACCOUNT_TYPE_PLUS
        if not acc.get("last_bind_provider"):
            acc["last_bind_provider"] = "paypal_ice"
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
    acc.setdefault("credentials_exported", False)
    acc.setdefault("credentials_exported_at", None)
    acc.setdefault("account_source", ACCOUNT_SOURCE_MANAGED)
    return acc


def _row_to_account(row) -> dict:
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
        }
    )
    return _normalize_account_record(data)


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


def _get_account_by_email(conn, email: str) -> dict | None:
    target = _normalized_email(email)
    if not target:
        return None
    row = conn.execute("SELECT * FROM accounts WHERE email = ?", (target,)).fetchone()
    return _row_to_account(row) if row else None


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
            existing = _get_account_by_email(conn, normalized)
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
            return


def ensure_session_only_account(email):
    """把仅有 auth_session 的账号显式写入账号池，便于前端和清理逻辑统一处理。"""
    normalized = _normalized_email(email)
    if not normalized:
        return None
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            existing = _get_account_by_email(conn, normalized)
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
                        existing = _get_account_by_email(conn, normalized) or existing
                return existing

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
            return _get_account_by_email(conn, normalized)


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
            acc = _get_account_by_email(conn, email)
            if acc:
                acc.update(kwargs)
                _upsert_account(conn, acc)
                return _get_account_by_email(conn, email) or acc
            return None


def replace_account_email(old_email, new_email, **kwargs):
    """Move an account row to a new email key while preserving existing metadata."""
    old_target = _normalized_email(old_email)
    new_target = _normalized_email(new_email)
    if not old_target or not new_target:
        return None
    with _accounts_write_lock:
        sqlite_store.initialize(_db_path())
        with sqlite_store.connect(_db_path()) as conn:
            old_acc = _get_account_by_email(conn, old_target)
            if not old_acc:
                return None
            existing_new = _get_account_by_email(conn, new_target)
            merged = dict(existing_new or {})
            merged.update(old_acc)
            merged.update(kwargs)
            merged["email"] = new_target
            _upsert_account(conn, merged)
            if old_target != new_target:
                conn.execute("DELETE FROM accounts WHERE email = ?", (old_target,))
            return _get_account_by_email(conn, new_target) or merged


def delete_account(email):
    """从账号池彻底移除（不动认证文件、不动临时邮箱账户）。返回是否真的删除了记录。"""
    target = _normalized_email(email)
    if not target:
        return False
    sqlite_store.initialize(_db_path())
    with sqlite_store.connect(_db_path()) as conn:
        cursor = conn.execute("DELETE FROM accounts WHERE email = ?", (target,))
        return cursor.rowcount > 0


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
