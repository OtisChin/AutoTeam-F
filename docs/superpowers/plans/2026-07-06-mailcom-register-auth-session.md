# mail.com 注册供应商与 auth_session 入池 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在注册账户页新增 `mail.com` 供应商，导入 mail.com 账号后自动同步账号池并启动 ChatGPT 登录获取 `auth_session`。

**Architecture:** 复用现有 `mail_accounts` SQLite 表作为 mail.com 邮箱池唯一数据源，新增 `MailComMailProvider` 接入现有 `TemporaryEmailClient` 抽象。前端导入后调用后端同步账号池 API，再调用现有 `/api/accounts/login-batch` 后台协议登录；注册成功后后端同步 mail邮箱管理和账号池状态。

**Tech Stack:** Python/FastAPI/SQLite/Pytest，Vue 3 Composition API，现有 mail.com Lightmailer 官方网页协议取件服务。

## Global Constraints

- 只管理 `@mail.com` 邮箱。
- 导入格式固定为 `邮箱----GPT密码----邮箱密码----refreshToken`。
- 取件必须使用 mail.com 官方网页协议，不依赖第三方 `ms.lqqq.cc` 接口。
- 不实现 OTP 接入按钮。
- 不使用 Playwright 作为 mail.com 取件方案。
- 不影响 Outlook、LuckMail、Cloudflare、Cloud-Mail 既有流程。
- 导入后自动同步账号池，并自动启动 ChatGPT 登录获取 `auth_session`。

---

## File Structure

- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/storage/mail_accounts.py`
  - 增加 mail.com 邮箱池选择、状态统计、账号池同步、注册成功标记函数。
- Create: `D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/mailcom.py`
  - 实现 `MailComMailProvider`。
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/__init__.py`
  - 注册 `mail.com` / `mailcom` provider 别名。
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/settings/setup_wizard.py`
  - 注册配置页 provider 选项和 provider 归一化。
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/api_routes/account_register_task.py`
  - `mail.com` 供应商不要求注册域名。
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/api_routes/mail_accounts.py`
  - 导入后同步账号池，新增邮箱池状态和同步 API。
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/interfaces/manager.py`
  - 注册成功保存 `auth_session` 时同步 mail.com 邮箱管理状态。
- Modify: `D:/code/OpenSource/AutoTeam-F/web/src/api.js`
  - 增加 mail.com 邮箱池状态和同步 API 客户端方法。
- Modify: `D:/code/OpenSource/AutoTeam-F/web/src/components/RegisterAccountPage.vue`
  - 增加 `mail.com` 邮箱池 UI、导入、自动登录入池、重试。
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mail_accounts.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mail_accounts_routes.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mailcom_mail.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_account_register_task_routes.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_manager_mailcom_sync.py`

---

### Task 1: mail.com 存储层和 provider

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/storage/mail_accounts.py`
- Create: `D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/mailcom.py`
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/__init__.py`
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/settings/setup_wizard.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mail_accounts.py`
- Create Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mailcom_mail.py`

**Interfaces:**
- Produces: `mail_accounts.mailcom_pool_status() -> dict[str, Any]`
- Produces: `mail_accounts.sync_mail_accounts_to_account_pool(emails: Iterable[str] | None = None) -> dict[str, Any]`
- Produces: `mail_accounts.list_available_registration_accounts() -> list[dict[str, Any]]`
- Produces: `mail_accounts.mark_mailcom_registered(email: str, *, gpt_password: str = "", refresh_token: str = "", source: str = "") -> dict[str, Any] | None`
- Produces: `MailComMailProvider` with `provider_name = "mail.com"`
- Consumes: `autotoken.services.mailcom_webmail.fetch_mailcom_messages(account, size=...)`
- Consumes: `autotoken.storage.accounts.add_account/update_account/load_accounts`
- Consumes: `autotoken.storage.auth_session_store.get_auth_session_file`

- [ ] **Step 1: Write failing storage tests**

Append to `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mail_accounts.py`:

```python
def test_mailcom_pool_status_derives_account_pool_and_auth_session(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts(
        "ready@mail.com----gpt1----mail1----rt1\n"
        "fresh@mail.com----gpt2----mail2----rt2\n"
        "disabled@mail.com----gpt3----mail3----rt3\n"
    )
    mail_accounts.set_account_statuses(["disabled@mail.com"], "disabled")

    monkeypatch.setattr(
        "autotoken.storage.accounts.load_accounts",
        lambda: [
            {"email": "ready@mail.com", "status": "active", "mail_provider": "mail.com"},
            {"email": "failed@mail.com", "status": "fail", "mail_provider": "mail.com"},
        ],
    )
    monkeypatch.setattr(
        "autotoken.storage.auth_session_store.get_auth_session_file",
        lambda email: f"session/{email}.json" if email == "ready@mail.com" else "",
    )

    status = mail_accounts.mailcom_pool_status()

    assert status["total"] == 3
    assert status["available"] == 1
    assert status["auth_session_ready"] == 1
    assert status["not_logged_in"] == 1
    assert status["disabled"] == 1
    assert status["next_available_email"] == "fresh@mail.com"
    by_email = {item["email"]: item for item in status["items"]}
    assert by_email["ready@mail.com"]["auth_session_status"] == "ready"
    assert by_email["fresh@mail.com"]["account_pool_status"] == "missing"


def test_sync_mail_accounts_to_account_pool_creates_and_updates_managed_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts("one@mail.com----gpt-pass----mail-pass----rt-one")
    created = []
    updated = []

    monkeypatch.setattr("autotoken.storage.accounts.add_account", lambda *args, **kwargs: created.append((args, kwargs)))
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: updated.append((email, kwargs)) or {"email": email, **kwargs})
    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [])

    result = mail_accounts.sync_mail_accounts_to_account_pool()

    assert result["synced"] == 1
    assert result["emails"] == ["one@mail.com"]
    assert created[0][0] == ("one@mail.com", "gpt-pass")
    assert created[0][1]["cloudmail_account_id"] == "one@mail.com"
    assert created[0][1]["mail_provider"] == "mail.com"
    assert updated[0] == (
        "one@mail.com",
        {
            "password": "gpt-pass",
            "cloudmail_account_id": "one@mail.com",
            "mail_provider": "mail.com",
        },
    )


def test_list_available_registration_accounts_skips_registered_disabled_and_missing_password(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts(
        "used@mail.com----gpt----mail----rt\n"
        "fresh@mail.com----gpt----mail----rt\n"
        "nomailpass@mail.com----gpt--------rt\n"
        "disabled@mail.com----gpt----mail----rt\n"
    )
    mail_accounts.set_account_statuses(["disabled@mail.com"], "disabled")
    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [{"email": "used@mail.com"}])

    rows = mail_accounts.list_available_registration_accounts()

    assert [row["email"] for row in rows] == ["fresh@mail.com"]


def test_mark_mailcom_registered_updates_gpt_password_and_note(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "mail.sqlite3"))
    mail_accounts.import_mail_accounts("one@mail.com----old-gpt----mail----rt-old")

    updated = mail_accounts.mark_mailcom_registered(
        "one@mail.com",
        gpt_password="new-gpt",
        refresh_token="rt-new",
        source="auth_session_saved",
    )

    assert updated["email"] == "one@mail.com"
    assert updated["gpt_password"] == "new-gpt"
    assert updated["refresh_token"] == "rt-new"
    assert updated["check_status"] == "valid"
    assert "已注册" in updated["note"]
```

- [ ] **Step 2: Run storage tests and verify failure**

Run:

```powershell
pytest tests/unit/test_mail_accounts.py -q
```

Expected: FAIL because `mailcom_pool_status`, `sync_mail_accounts_to_account_pool`, `list_available_registration_accounts`, and `mark_mailcom_registered` do not exist.

- [ ] **Step 3: Implement storage helpers**

Add imports near the top of `D:/code/OpenSource/AutoTeam-F/src/autotoken/storage/mail_accounts.py`:

```python
from autotoken.storage import auth_session_store
```

Append these functions before `export_mail_accounts()`:

```python
def _account_pool_by_email() -> dict[str, dict[str, Any]]:
    try:
        from autotoken.storage.accounts import load_accounts

        return {
            normalized_email(account.get("email")): dict(account)
            for account in load_accounts()
            if normalized_email(account.get("email"))
        }
    except Exception:
        return {}


def _mailcom_registered_emails() -> set[str]:
    emails = set(_account_pool_by_email().keys())
    try:
        from autotoken.storage.register_failures import list_failures

        for failure in list_failures(500):
            email = normalized_email(failure.get("email"))
            if not email:
                continue
            category = str(failure.get("category") or "").strip().lower()
            reason = str(failure.get("reason") or "").strip().lower()
            if category == "email_already_in_use" or "email_already_in_use" in reason:
                emails.add(email)
    except Exception:
        pass
    return emails


def list_available_registration_accounts() -> list[dict[str, Any]]:
    registered = _mailcom_registered_emails()
    rows = []
    for row in list_mail_accounts():
        email = normalized_email(row.get("email"))
        if not email:
            continue
        if row.get("status") != "enabled":
            continue
        if email in registered:
            continue
        if not str(row.get("mail_password") or "").strip():
            continue
        rows.append(row)
    return rows


def sync_mail_accounts_to_account_pool(emails: Iterable[str] | None = None) -> dict[str, Any]:
    selected = {email for email in (normalized_email(item) for item in emails or []) if email}
    rows = [
        row
        for row in list_mail_accounts()
        if not selected or normalized_email(row.get("email")) in selected
    ]
    from autotoken.storage.accounts import SEAT_CODEX, add_account, update_account

    synced = []
    skipped = []
    for row in rows:
        email = normalized_email(row.get("email"))
        gpt_password = str(row.get("gpt_password") or "").strip()
        if not email:
            skipped.append({"email": str(row.get("email") or ""), "reason": "邮箱为空"})
            continue
        if not gpt_password:
            skipped.append({"email": email, "reason": "GPT密码为空"})
            continue
        add_account(
            email,
            gpt_password,
            cloudmail_account_id=email,
            seat_type=SEAT_CODEX,
            mail_provider="mail.com",
        )
        update_account(
            email,
            password=gpt_password,
            cloudmail_account_id=email,
            mail_provider="mail.com",
        )
        synced.append(email)
    return {"synced": len(synced), "skipped": skipped, "emails": synced}


def mailcom_pool_status() -> dict[str, Any]:
    accounts_by_email = _account_pool_by_email()
    items = []
    for row in list_mail_accounts():
        email = normalized_email(row.get("email"))
        account = accounts_by_email.get(email or "")
        auth_session_file = auth_session_store.get_auth_session_file(email) if email else ""
        auth_ready = bool(auth_session_file)
        account_status = "missing" if not account else str(account.get("status") or "pending")
        item = {
            **row,
            "account_pool_status": account_status,
            "auth_session_status": "ready" if auth_ready else "missing",
            "auth_session_file": auth_session_file,
            "pool_status": "disabled" if row.get("status") == "disabled" else ("ready" if auth_ready else "available"),
        }
        items.append(item)

    available_items = [
        item
        for item in items
        if item.get("status") == "enabled"
        and item.get("auth_session_status") != "ready"
        and str(item.get("mail_password") or "").strip()
    ]
    return {
        "items": items,
        "total": len(items),
        "available": len(available_items),
        "auth_session_ready": sum(1 for item in items if item.get("auth_session_status") == "ready"),
        "not_logged_in": sum(1 for item in items if item.get("status") == "enabled" and item.get("auth_session_status") != "ready"),
        "disabled": sum(1 for item in items if item.get("status") == "disabled"),
        "login_failed": sum(1 for item in items if str(item.get("account_pool_status") or "") == "fail"),
        "next_available_email": available_items[0]["email"] if available_items else "",
    }


def mark_mailcom_registered(
    email: str,
    *,
    gpt_password: str = "",
    refresh_token: str = "",
    source: str = "",
) -> dict[str, Any] | None:
    current = get_mail_account(email)
    if not current:
        return None
    note_parts = [part for part in [str(current.get("note") or "").strip(), f"已注册:{source or 'registered'}"] if part]
    payload = {
        **current,
        "gpt_password": str(gpt_password or current.get("gpt_password") or "").strip(),
        "refresh_token": str(refresh_token or current.get("refresh_token") or "").strip(),
        "check_status": "valid",
        "note": "；".join(dict.fromkeys(note_parts)),
    }
    updated = upsert_mail_account(payload)
    update_check_result(
        updated["email"],
        check_status="valid",
        access_token=str(updated.get("access_token") or ""),
        refresh_token=str(updated.get("refresh_token") or ""),
        error="",
    )
    return get_mail_account(updated["email"])
```

- [ ] **Step 4: Run storage tests and verify pass**

Run:

```powershell
pytest tests/unit/test_mail_accounts.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing provider tests**

Create `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mailcom_mail.py`:

```python
import pytest

from autotoken.mail.mailcom import MailComMailProvider


def test_mailcom_provider_selects_available_sqlite_account(monkeypatch):
    provider = MailComMailProvider()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.list_available_registration_accounts",
        lambda: [
            {
                "email": "fresh@mail.com",
                "gpt_password": "gpt-pass",
                "mail_password": "mail-pass",
                "refresh_token": "rt",
            }
        ],
    )

    account_id, email = provider.create_temp_email()

    assert account_id == "fresh@mail.com"
    assert email == "fresh@mail.com"
    assert provider._resolve_account_id("fresh@mail.com") == "fresh@mail.com"


def test_mailcom_provider_exhaustion_message(monkeypatch):
    provider = MailComMailProvider()
    monkeypatch.setattr("autotoken.storage.mail_accounts.list_available_registration_accounts", lambda: [])

    with pytest.raises(RuntimeError, match="没有可用的 mail.com 账号"):
        provider.create_temp_email()


def test_mailcom_provider_fetches_messages_via_official_webmail(monkeypatch):
    provider = MailComMailProvider()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.get_mail_account",
        lambda email: {"email": email, "mail_password": "mail-pass", "refresh_token": "rt"},
    )
    monkeypatch.setattr(
        "autotoken.services.mailcom_webmail.fetch_mailcom_messages",
        lambda account, size=10: [
            {
                "id": "m1",
                "subject": "OpenAI code",
                "sendEmail": "noreply@openai.com",
                "toEmail": account["email"],
                "text": "Your code is 123456",
                "html": "",
                "content": "Your code is 123456",
                "createTime": 1710000000,
                "createdAt": 1710000000,
            }
        ],
    )

    messages = provider.search_emails_by_recipient("fresh@mail.com", size=5)

    assert messages[0]["accountId"] == "fresh@mail.com"
    assert messages[0]["toEmail"] == "fresh@mail.com"
    assert provider.extract_verification_code(messages[0]) == "123456"


def test_factory_returns_mailcom_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "mail.com")
    from autotoken.mail import get_mail_client

    assert isinstance(get_mail_client(), MailComMailProvider)
```

- [ ] **Step 6: Run provider tests and verify failure**

Run:

```powershell
pytest tests/unit/test_mailcom_mail.py -q
```

Expected: FAIL because `autotoken.mail.mailcom` does not exist.

- [ ] **Step 7: Implement `MailComMailProvider`**

Create `D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/mailcom.py`:

```python
"""mail.com account-pool mail provider backed by the local SQLite mail_accounts table."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from autotoken.mail.base import MailProvider, normalize_email_addr

logger = logging.getLogger(__name__)


class MailComMailProvider(MailProvider):
    provider_name = "mail.com"

    def __init__(self):
        self._reserved_emails: set[str] = set()
        self._lock = threading.Lock()

    def login(self) -> str:
        from autotoken.storage import mail_accounts

        total = len(mail_accounts.list_mail_accounts())
        if total <= 0:
            raise RuntimeError("mail.com provider 未导入账号。请先在注册账户页导入 mail.com 邮箱池")
        logger.info("[mail.com] 已加载 %d 个 mail.com 账号", total)
        return f"mail.com:{total}"

    def create_temp_email(self, prefix: str | None = None, domain: str | None = None) -> tuple[int | str, str]:
        requested_domain = str(domain or "").strip().lstrip("@").lower()
        if requested_domain and requested_domain != "mail.com":
            raise RuntimeError(f"mail.com provider 不支持 @{requested_domain} 域名")
        from autotoken.storage import mail_accounts

        with self._lock:
            for account in mail_accounts.list_available_registration_accounts():
                email = normalize_email_addr(account.get("email"))
                if not email or email in self._reserved_emails:
                    continue
                self._reserved_emails.add(email)
                logger.info("[mail.com] 选择注册邮箱: %s", email)
                return email, email
        raise RuntimeError("没有可用的 mail.com 账号可用于注册（可能都已注册、已禁用或缺少邮箱密码）")

    def list_accounts(self, size: int = 200) -> list[dict]:
        from autotoken.storage import mail_accounts

        limit = max(1, int(size or 200))
        return [
            {
                "id": row["email"],
                "email": row["email"],
                "accountEmail": row["email"],
                "provider": self.provider_name,
                "status": row.get("status"),
                "check_status": row.get("check_status"),
            }
            for row in mail_accounts.list_mail_accounts()[:limit]
        ]

    def delete_account(self, account_id: int | str) -> dict:
        email = normalize_email_addr(account_id)
        with self._lock:
            self._reserved_emails.discard(email)
        return {"code": 0, "message": "mail.com account retained"}

    def _resolve_account_id(self, value: int | str | None) -> str:
        return normalize_email_addr(value)

    def search_emails_by_recipient(
        self, to_email: str, size: int = 10, account_id: int | str | None = None
    ) -> list[dict]:
        email = normalize_email_addr(account_id or to_email)
        if not email:
            return []
        from autotoken.services.mailcom_webmail import fetch_mailcom_messages
        from autotoken.storage import mail_accounts

        account = mail_accounts.get_mail_account(email)
        if not account:
            logger.warning("[mail.com] 未找到收件人对应 mail.com 账号: %s", email)
            return []
        messages = fetch_mailcom_messages(account, size=max(1, int(size or 10)))
        return [self._to_legacy_dict(account, message) for message in messages[:size]]

    def list_emails(self, account_id: int | str, size: int = 10) -> list[dict]:
        return self.search_emails_by_recipient(str(account_id), size=size, account_id=account_id)

    def delete_emails_for(self, to_email: str) -> int:
        logger.info("[mail.com] 暂不删除邮件: %s", to_email)
        return 0

    @staticmethod
    def _to_legacy_dict(account: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
        email = normalize_email_addr(account.get("email"))
        created = message.get("createTime") or message.get("createdAt") or int(time.time())
        try:
            created_at = int(float(created))
        except Exception:
            created_at = int(time.time())
        html = str(message.get("html") or message.get("content") or "")
        text = str(message.get("text") or "")
        return {
            "id": str(message.get("id") or f"{email}:{created_at}"),
            "accountId": email,
            "email": email,
            "toEmail": str(message.get("toEmail") or email),
            "sendEmail": str(message.get("sendEmail") or message.get("from") or ""),
            "subject": str(message.get("subject") or ""),
            "text": text,
            "html": html,
            "content": html or text,
            "createTime": created_at,
            "createdAt": created_at,
            "raw": message,
        }
```

- [ ] **Step 8: Register provider factory and setup wizard**

Modify `D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/__init__.py`:

```python
    if raw in ("mail.com", "mailcom", "mail_com"):
        from autotoken.mail.mailcom import MailComMailProvider

        return MailComMailProvider()
```

Place it after the Outlook branch and update the ValueError options to:

```python
raise ValueError(f"未知 MAIL_PROVIDER={raw!r}(可选: cloudflare_temp_email | cloud-mail | outlook | mail.com | luckmail)")
```

Modify `D:/code/OpenSource/AutoTeam-F/src/autotoken/settings/setup_wizard.py`:

```python
MAIL_PROVIDER_OPTIONS = [
    ...
    {
        "value": "mail.com",
        "label": "mail.com",
        "description": "mail.com SQLite 邮箱池注册",
    },
    ...
]
```

Add:

```python
    "mail.com": [],
```

to `PROVIDER_SETUP_FIELDS`.

Add to `get_mail_provider()`:

```python
    if provider in ("mail.com", "mailcom", "mail_com"):
        return "mail.com"
```

Add a `validate_config()` branch before LuckMail:

```python
    elif provider == "mail.com":
        check_keys = "mail_accounts SQLite"
        domain_key = "mail_accounts"
        label = "mail.com"
```

Update the unknown-provider error and final provider shortcut:

```python
logger.error("[验证] 未知 MAIL_PROVIDER=%s,可选: cloudflare_temp_email | cloud-mail | outlook | mail.com | luckmail", provider)
...
if provider in ("outlook", "mail.com", "luckmail"):
    logger.info("[验证] %s 配置验证通过", label)
    return True
```

- [ ] **Step 9: Run provider tests and relevant config tests**

Run:

```powershell
pytest tests/unit/test_mailcom_mail.py tests/unit/test_mail_provider_config_routes.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 1**

```powershell
git add src/autotoken/storage/mail_accounts.py src/autotoken/mail/mailcom.py src/autotoken/mail/__init__.py src/autotoken/settings/setup_wizard.py tests/unit/test_mail_accounts.py tests/unit/test_mailcom_mail.py
git commit -m "feat: add mailcom mail provider"
```

---

### Task 2: mail.com API 与注册任务接入

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/api_routes/mail_accounts.py`
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/api_routes/account_register_task.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mail_accounts_routes.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_account_register_task_routes.py`

**Interfaces:**
- Produces: `GET /api/mail-accounts/pool-status`
- Produces: `POST /api/mail-accounts/sync-account-pool`
- Modifies: `POST /api/mail-accounts/import` response includes `pool_status` and `synced_account_pool`.
- Consumes: `mail_accounts.sync_mail_accounts_to_account_pool()`
- Consumes: `mail_accounts.mailcom_pool_status()`

- [ ] **Step 1: Write failing API route tests**

Append to `D:/code/OpenSource/AutoTeam-F/tests/unit/test_mail_accounts_routes.py`:

```python
def test_mail_accounts_import_syncs_account_pool_and_returns_pool_status(monkeypatch):
    app = _app()
    monkeypatch.setattr("autotoken.storage.mail_accounts.import_mail_accounts", lambda text: {"imported": 1, "skipped": 0, "total": 1})
    monkeypatch.setattr("autotoken.storage.mail_accounts.list_mail_accounts", lambda: [{"email": "one@mail.com"}])
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.sync_mail_accounts_to_account_pool",
        lambda emails=None: {"synced": 1, "emails": ["one@mail.com"], "skipped": []},
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mailcom_pool_status",
        lambda: {"total": 1, "auth_session_ready": 0, "items": [{"email": "one@mail.com"}]},
    )

    result = _endpoint(app, "/api/mail-accounts/import", "POST")(MailAccountImportParams(text="one@mail.com----g----m----rt"))

    assert result["imported"] == 1
    assert result["synced_account_pool"]["synced"] == 1
    assert result["pool_status"]["total"] == 1


def test_mail_accounts_pool_status_and_sync_routes(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mailcom_pool_status",
        lambda: {"total": 2, "auth_session_ready": 1, "items": []},
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.sync_mail_accounts_to_account_pool",
        lambda emails=None: {"synced": len(emails or []), "emails": list(emails or []), "skipped": []},
    )

    assert _endpoint(app, "/api/mail-accounts/pool-status", "GET")()["total"] == 2
    synced = _endpoint(app, "/api/mail-accounts/sync-account-pool", "POST")(
        MailAccountBatchParams(emails=["one@mail.com", "two@mail.com"])
    )
    assert synced["synced"] == 2
```

Append to `D:/code/OpenSource/AutoTeam-F/tests/unit/test_account_register_task_routes.py`:

```python
def test_post_add_mailcom_does_not_require_register_domain(monkeypatch):
    started = []
    calls = []
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: [])
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "")
    monkeypatch.setattr("autotoken.identity.random_password", lambda: "generated-pass")
    monkeypatch.setattr("autotoken.setup_wizard.get_mail_provider", lambda value=None: value or "mail.com")
    monkeypatch.setattr("autotoken.manager.cmd_register_accounts", lambda **kwargs: calls.append(kwargs) or {"created": 1})

    routes = _routes(started)
    result = routes["post_add"](ManualRegisterParams(mail_provider="mail.com", domain="", domains=[]))

    assert result["command"] == "register"
    assert started[0]["params"]["domain"] == ""
    assert started[0]["params"]["domains"] == []
    assert started[0]["kwargs"]["mail_provider"] == "mail.com"
    assert started[0]["func"]("task-register") == {"created": 1}
    assert calls[0]["mail_provider"] == "mail.com"
```

- [ ] **Step 2: Run API tests and verify failure**

Run:

```powershell
pytest tests/unit/test_mail_accounts_routes.py tests/unit/test_account_register_task_routes.py -q
```

Expected: FAIL because the new routes do not exist and mail.com still requires a domain.

- [ ] **Step 3: Implement mail account API routes**

In `D:/code/OpenSource/AutoTeam-F/src/autotoken/api_routes/mail_accounts.py`, modify `post_mail_accounts_import()` body after `result = mail_accounts.import_mail_accounts(params.text)`:

```python
            sync_result = mail_accounts.sync_mail_accounts_to_account_pool()
            pool_status = mail_accounts.mailcom_pool_status()
            return {
                **result,
                **_response(mail_accounts.list_mail_accounts()),
                "synced_account_pool": sync_result,
                "pool_status": pool_status,
            }
```

Add routes after `post_mail_accounts_import()`:

```python
    @router.get("/api/mail-accounts/pool-status")
    def get_mail_accounts_pool_status():
        from autotoken.storage import mail_accounts

        return mail_accounts.mailcom_pool_status()

    @router.post("/api/mail-accounts/sync-account-pool")
    def post_mail_accounts_sync_account_pool(params: MailAccountBatchParams):
        from autotoken.storage import mail_accounts

        _validate_batch(params.emails)
        emails = params.emails or None
        return mail_accounts.sync_mail_accounts_to_account_pool(emails)
```

- [ ] **Step 4: Allow mail.com register task without domain**

In `D:/code/OpenSource/AutoTeam-F/src/autotoken/api_routes/account_register_task.py`, find:

```python
domain_required = mail_provider not in {"luckmail", "outlook"} and not phone_only
```

Replace with:

```python
domain_required = mail_provider not in {"luckmail", "outlook", "mail.com"} and not phone_only
```

- [ ] **Step 5: Run API tests and verify pass**

Run:

```powershell
pytest tests/unit/test_mail_accounts_routes.py tests/unit/test_account_register_task_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/autotoken/api_routes/mail_accounts.py src/autotoken/api_routes/account_register_task.py tests/unit/test_mail_accounts_routes.py tests/unit/test_account_register_task_routes.py
git commit -m "feat: expose mailcom pool APIs"
```

---

### Task 3: 注册成功和 auth_session 保存后同步 mail.com

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/interfaces/manager.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_manager_mailcom_sync.py`

**Interfaces:**
- Produces: `manager._sync_provider_registered_email(email, mail_client=None, *, mail_provider=None, password="", refresh_token="", source="") -> None`
- Replaces internal use of `_mark_outlook_email_registered()` with the generic helper.
- Consumes: `mail_accounts.mark_mailcom_registered()`

- [ ] **Step 1: Write failing manager sync test**

Create `D:/code/OpenSource/AutoTeam-F/tests/unit/test_manager_mailcom_sync.py`:

```python
from autotoken.interfaces import manager


def test_sync_provider_registered_email_marks_mailcom(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mark_mailcom_registered",
        lambda email, **kwargs: calls.append((email, kwargs)) or {"email": email},
    )

    manager._sync_provider_registered_email(
        "one@mail.com",
        mail_provider="mail.com",
        password="gpt-pass",
        refresh_token="rt-new",
        source="auth_session_saved",
    )

    assert calls == [
        (
            "one@mail.com",
            {
                "gpt_password": "gpt-pass",
                "refresh_token": "rt-new",
                "source": "auth_session_saved",
            },
        )
    ]


def test_sync_provider_registered_email_keeps_outlook_behavior(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "autotoken.storage.outlook_pool.mark_registered_email",
        lambda email, source="": calls.append((email, source)),
    )

    manager._sync_provider_registered_email("one@outlook.com", mail_provider="outlook", source="register_success")

    assert calls == [("one@outlook.com", "register_success")]
```

- [ ] **Step 2: Run manager test and verify failure**

Run:

```powershell
pytest tests/unit/test_manager_mailcom_sync.py -q
```

Expected: FAIL because `_sync_provider_registered_email` does not exist.

- [ ] **Step 3: Implement generic provider sync**

In `D:/code/OpenSource/AutoTeam-F/src/autotoken/interfaces/manager.py`, replace `_mark_outlook_email_registered` with:

```python
def _sync_provider_registered_email(
    email: str,
    mail_client=None,
    *,
    mail_provider: str | None = None,
    password: str = "",
    refresh_token: str = "",
    source: str = "",
) -> None:
    provider = (mail_provider or _mail_client_provider_name(mail_client)).strip().lower() if (mail_provider or mail_client) else ""
    if provider == "outlook":
        try:
            from autotoken.storage.outlook_pool import mark_registered_email

            mark_registered_email(email, source=source)
        except Exception as exc:
            logger.debug("[outlook] 标记已注册邮箱失败: %s", exc, exc_info=True)
        return
    if provider in {"mail.com", "mailcom", "mail_com"}:
        try:
            from autotoken.storage.mail_accounts import mark_mailcom_registered

            mark_mailcom_registered(
                email,
                gpt_password=password,
                refresh_token=refresh_token,
                source=source,
            )
        except Exception as exc:
            logger.debug("[mail.com] 标记已注册邮箱失败: %s", exc, exc_info=True)
        return


def _mark_outlook_email_registered(email: str, mail_client=None, *, mail_provider: str | None = None, source: str = "") -> None:
    _sync_provider_registered_email(email, mail_client, mail_provider=mail_provider, source=source)
```

Then update call sites:

```python
_sync_provider_registered_email(
    email,
    mail_provider=mail_provider,
    password=password,
    source="auth_session_saved",
)
```

inside `_save_auth_from_session_page()`.

Replace:

```python
_mark_outlook_email_registered(email, mail_client, source="register_success")
```

with:

```python
_sync_provider_registered_email(
    email,
    mail_client,
    password=password,
    source="register_success",
)
```

Update batch logging provider check:

```python
if provider_label in {"luckmail", "outlook", "mail.com"}
```

- [ ] **Step 4: Run manager test and targeted registration tests**

Run:

```powershell
pytest tests/unit/test_manager_mailcom_sync.py tests/unit/test_manager_mail_timeout.py tests/unit/test_account_register_task_routes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/autotoken/interfaces/manager.py tests/unit/test_manager_mailcom_sync.py
git commit -m "feat: sync mailcom registration status"
```

---

### Task 4: 注册账户页 mail.com 邮箱池 UI

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/web/src/api.js`
- Modify: `D:/code/OpenSource/AutoTeam-F/web/src/components/RegisterAccountPage.vue`

**Interfaces:**
- Consumes: `api.importMailAccounts(text)`
- Consumes: `api.getMailAccountsPoolStatus()`
- Consumes: `api.syncMailAccountsToAccountPool(emails)`
- Consumes: `api.loginAccountsBatch(emails, { mail_provider: "mail.com", protocol_only: true, bind_email: false })`
- Produces UI functions:
  - `isMailComProvider`
  - `loadMailComPoolStatus`
  - `importMailComAccounts`
  - `loginSelectedMailComAccounts`
  - `deleteSelectedMailComPoolEmails`

- [ ] **Step 1: Add API methods**

In `D:/code/OpenSource/AutoTeam-F/web/src/api.js`, after existing mail account methods:

```js
  getMailAccountsPoolStatus: () => request('GET', '/mail-accounts/pool-status'),
  syncMailAccountsToAccountPool: (emails = []) => request('POST', '/mail-accounts/sync-account-pool', { emails }),
```

- [ ] **Step 2: Add provider computeds**

In `D:/code/OpenSource/AutoTeam-F/web/src/components/RegisterAccountPage.vue`, add:

```js
const isMailComProvider = computed(() => String(registerForm.value.mailProvider || '').trim().toLowerCase() === 'mail.com')
```

Update:

```js
const registerProviderUsesPool = computed(() => isOutlookProvider.value || isMailComProvider.value)
const registerProviderPoolMessage = computed(() => {
  if (isOutlookProvider.value) return 'Outlook 邮箱池中选择'
  if (isMailComProvider.value) return 'mail.com 邮箱池中选择'
  return ''
})
const registerProviderUsesDomains = computed(() => !registerProviderUsesPool.value && !isPhoneCpaFlow.value)
```

Update `registerPreviewEmail`:

```js
if (isMailComProvider.value) return 'mail.com邮箱池中选择'
```

- [ ] **Step 3: Add mail.com UI state**

Near Outlook state variables, add:

```js
const mailComPoolStatus = ref(null)
const mailComPoolLoading = ref(false)
const mailComPoolError = ref('')
const mailComImportDialogOpen = ref(false)
const mailComImportContent = ref('')
const mailComImportResult = ref('')
const mailComImportResultOk = ref(true)
const mailComPoolDialogOpen = ref(false)
const mailComPoolSelectedEmails = ref([])
const mailComPoolDeleting = ref(false)
const mailComPoolLoginBusy = ref(false)

const mailComPoolItems = computed(() => Array.isArray(mailComPoolStatus.value?.items) ? mailComPoolStatus.value.items : [])
const mailComPoolVisibleEmails = computed(() => mailComPoolItems.value.map(item => item.email).filter(Boolean))
const mailComPoolSelectedCount = computed(() => mailComPoolSelectedEmails.value.length)
const mailComPoolAllVisibleSelected = computed(() => {
  const visible = mailComPoolVisibleEmails.value
  return visible.length > 0 && visible.every(email => mailComPoolSelectedEmails.value.includes(email))
})
const mailComLoginCandidateEmails = computed(() => {
  const selected = mailComPoolSelectedEmails.value.length ? mailComPoolSelectedEmails.value : mailComPoolVisibleEmails.value
  const ready = new Set(mailComPoolItems.value.filter(item => item.auth_session_status === 'ready').map(item => item.email))
  return selected.filter(email => email && !ready.has(email))
})
```

- [ ] **Step 4: Add mail.com UI methods**

Near Outlook methods, add:

```js
function openMailComImportDialog() {
  mailComImportDialogOpen.value = true
  mailComImportResult.value = ''
}

function closeMailComImportDialog() {
  if (mailComPoolLoading.value) return
  mailComImportDialogOpen.value = false
}

async function loadMailComPoolStatus() {
  if (!isMailComProvider.value || mailComPoolLoading.value) return
  mailComPoolLoading.value = true
  mailComPoolError.value = ''
  try {
    mailComPoolStatus.value = await api.getMailAccountsPoolStatus()
    const visible = new Set(mailComPoolVisibleEmails.value)
    mailComPoolSelectedEmails.value = mailComPoolSelectedEmails.value.filter(email => visible.has(email))
  } catch (e) {
    mailComPoolStatus.value = null
    mailComPoolError.value = `读取 mail.com 邮箱池失败: ${e.message}`
  } finally {
    mailComPoolLoading.value = false
  }
}

async function importMailComAccounts() {
  if (mailComPoolLoading.value) return
  const content = mailComImportContent.value.trim()
  if (!content) {
    mailComImportResult.value = '请先粘贴 mail.com 账号'
    mailComImportResultOk.value = false
    return
  }
  mailComPoolLoading.value = true
  try {
    const result = await api.importMailAccounts(content)
    mailComPoolStatus.value = result.pool_status || await api.getMailAccountsPoolStatus()
    const emails = Array.isArray(result.synced_account_pool?.emails) ? result.synced_account_pool.emails : []
    mailComImportResult.value = `导入完成：成功 ${result.imported || 0}，跳过 ${result.skipped || 0}，同步账号池 ${emails.length} 个，正在启动登录入池`
    mailComImportResultOk.value = true
    if (emails.length) {
      await api.loginAccountsBatch(emails, {
        mail_provider: 'mail.com',
        protocol_only: true,
        bind_email: false,
      })
      emit('task-started')
    }
    await loadMailComPoolStatus()
  } catch (e) {
    mailComImportResult.value = `导入失败: ${e.message}`
    mailComImportResultOk.value = false
  } finally {
    mailComPoolLoading.value = false
  }
}

function openMailComPoolDialog() {
  mailComPoolDialogOpen.value = true
  loadMailComPoolStatus()
}

function closeMailComPoolDialog() {
  if (mailComPoolDeleting.value || mailComPoolLoginBusy.value) return
  mailComPoolDialogOpen.value = false
}

function toggleMailComPoolEmail(email, checked) {
  const value = String(email || '').trim()
  if (!value) return
  const selected = new Set(mailComPoolSelectedEmails.value)
  checked ? selected.add(value) : selected.delete(value)
  mailComPoolSelectedEmails.value = Array.from(selected)
}

function toggleMailComPoolVisible(checked) {
  const selected = new Set(mailComPoolSelectedEmails.value)
  for (const email of mailComPoolVisibleEmails.value) {
    checked ? selected.add(email) : selected.delete(email)
  }
  mailComPoolSelectedEmails.value = Array.from(selected)
}

async function loginSelectedMailComAccounts() {
  if (mailComPoolLoginBusy.value) return
  const emails = mailComLoginCandidateEmails.value
  if (!emails.length) {
    setMessage('没有需要登录入池的 mail.com 账号', false)
    return
  }
  mailComPoolLoginBusy.value = true
  try {
    await api.syncMailAccountsToAccountPool(emails)
    await api.loginAccountsBatch(emails, {
      mail_provider: 'mail.com',
      protocol_only: true,
      bind_email: false,
    })
    emit('task-started')
    setMessage(`已启动 ${emails.length} 个 mail.com 账号登录入池`, true)
  } catch (e) {
    setMessage(`启动 mail.com 登录入池失败: ${e.message}`, false)
  } finally {
    mailComPoolLoginBusy.value = false
  }
}

async function deleteSelectedMailComPoolEmails() {
  if (mailComPoolDeleting.value || mailComPoolSelectedCount.value === 0) return
  const emails = [...mailComPoolSelectedEmails.value]
  const ok = window.confirm(`确认从 mail.com 邮箱池删除 ${emails.length} 个邮箱?\\n\\n只会删除 mail邮箱管理中的记录，不会删除本地账号池记录。`)
  if (!ok) return
  mailComPoolDeleting.value = true
  try {
    const result = await api.deleteMailAccounts(emails)
    mailComPoolSelectedEmails.value = []
    await loadMailComPoolStatus()
    setMessage(`已从 mail.com 邮箱池删除 ${result.deleted || 0} 个邮箱`, true)
  } catch (e) {
    setMessage(`删除 mail.com 邮箱失败: ${e.message}`, false)
  } finally {
    mailComPoolDeleting.value = false
  }
}
```

- [ ] **Step 5: Add mail.com card and dialogs**

Copy the Outlook 邮箱池 card in `RegisterAccountPage.vue` and change text/state/function names:

```vue
<div v-if="isMailComProvider" class="rounded-xl border border-gray-800 bg-gray-950/60 p-3 space-y-3">
  <div class="flex items-start justify-between gap-3">
    <div>
      <div class="text-sm font-medium text-white">mail.com 邮箱池</div>
      <div class="mt-1 text-xs text-gray-500">导入后会同步账号池，并自动启动 ChatGPT 登录获取 auth_session。</div>
    </div>
    <div class="flex flex-wrap justify-end gap-2">
      <button type="button" @click="loadMailComPoolStatus" :disabled="mailComPoolLoading" class="px-3 py-1.5 rounded-lg text-xs border bg-gray-900 hover:bg-gray-800 text-gray-300 border-gray-700 transition disabled:opacity-50">
        {{ mailComPoolLoading ? '刷新中...' : '刷新状态' }}
      </button>
      <button type="button" @click="openMailComImportDialog" class="px-3 py-1.5 rounded-lg text-xs border bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border-emerald-500/30 transition">
        导入邮箱
      </button>
      <button type="button" @click="openMailComPoolDialog" class="px-3 py-1.5 rounded-lg text-xs border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition">
        管理邮箱池
      </button>
    </div>
  </div>
  <div v-if="mailComPoolStatus" class="border-y border-gray-800 py-3">
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <div><div class="text-[11px] text-gray-500">邮箱池</div><div class="mt-0.5 text-sm font-medium text-white">{{ mailComPoolStatus.total }}</div></div>
      <div><div class="text-[11px] text-gray-500">可用</div><div class="mt-0.5 text-sm font-medium text-emerald-300">{{ mailComPoolStatus.available }}</div></div>
      <div><div class="text-[11px] text-gray-500">auth_session</div><div class="mt-0.5 text-sm font-medium text-blue-300">{{ mailComPoolStatus.auth_session_ready }}</div></div>
      <div><div class="text-[11px] text-gray-500">未登录</div><div class="mt-0.5 text-sm font-medium text-amber-300">{{ mailComPoolStatus.not_logged_in }}</div></div>
      <div><div class="text-[11px] text-gray-500">失败</div><div class="mt-0.5 text-sm font-medium text-red-300">{{ mailComPoolStatus.login_failed }}</div></div>
    </div>
    <div class="mt-2 text-xs text-gray-500">
      下一个可用邮箱：
      <span class="font-mono text-gray-300">{{ mailComPoolStatus.next_available_email || '无' }}</span>
    </div>
  </div>
  <div v-else-if="mailComPoolError" class="text-xs text-red-300">{{ mailComPoolError }}</div>
</div>
```

Add import and pool dialogs near the Outlook dialogs with fields:

```vue
<div v-if="mailComImportDialogOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
  <div class="w-full max-w-3xl rounded-2xl border border-gray-800 bg-gray-950 p-5 shadow-2xl">
    <div class="flex items-center justify-between">
      <h3 class="text-lg font-semibold text-white">导入 mail.com 邮箱</h3>
      <button type="button" class="text-gray-400 hover:text-white" @click="closeMailComImportDialog">×</button>
    </div>
    <p class="mt-2 text-xs text-gray-500">格式：邮箱----GPT密码----邮箱密码----refreshToken，每行一个。</p>
    <textarea v-model="mailComImportContent" rows="10" spellcheck="false" class="mt-3 w-full rounded-lg border border-gray-700 bg-gray-900 p-3 font-mono text-xs text-gray-100 focus:border-blue-500 focus:outline-none"></textarea>
    <div v-if="mailComImportResult" class="mt-3 rounded-lg px-3 py-2 text-xs" :class="mailComImportResultOk ? 'border border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border border-red-500/20 bg-red-500/10 text-red-300'">
      {{ mailComImportResult }}
    </div>
    <div class="mt-4 flex justify-end gap-2">
      <button type="button" @click="closeMailComImportDialog" class="rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800">取消</button>
      <button type="button" @click="importMailComAccounts" :disabled="mailComPoolLoading" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50">
        {{ mailComPoolLoading ? '导入中...' : '导入并登录入池' }}
      </button>
    </div>
  </div>
</div>
```

The management dialog should list `mailComPoolItems` with columns: checkbox, email, status, auth_session, account_pool_status, actions. Use `loginSelectedMailComAccounts()` for the “登录并入池/重试” button and `deleteSelectedMailComPoolEmails()` for deletion.

- [ ] **Step 6: Add watchers and lifecycle**

Update Escape handler:

```js
  } else if (mailComImportDialogOpen.value) {
    closeMailComImportDialog()
  } else if (mailComPoolDialogOpen.value) {
    closeMailComPoolDialog()
  }
```

Add watcher:

```js
watch(
  isMailComProvider,
  enabled => {
    if (enabled) loadMailComPoolStatus()
  }
)
```

Update mounted hooks and task-finished refresh paths:

```js
if (isMailComProvider.value) loadMailComPoolStatus()
```

- [ ] **Step 7: Run frontend build**

Run:

```powershell
npm --prefix web run build
```

Expected: build exits with code 0.

- [ ] **Step 8: Commit Task 4**

```powershell
git add web/src/api.js web/src/components/RegisterAccountPage.vue
git commit -m "feat: add mailcom pool UI"
```

---

### Task 5: End-to-end verification and service restart

**Files:**
- No new code expected.
- Verify: backend tests, frontend build, app behavior.

**Interfaces:**
- Consumes all previous tasks.
- Produces a restarted local service with updated code.

- [ ] **Step 1: Run full targeted backend test suite**

Run:

```powershell
pytest tests/unit/test_mail_accounts.py tests/unit/test_mail_accounts_routes.py tests/unit/test_mailcom_mail.py tests/unit/test_account_register_task_routes.py tests/unit/test_manager_mailcom_sync.py tests/unit/test_mailcom_webmail_service.py tests/unit/test_mailcom_password_service.py tests/unit/test_outlook_mail.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 3: Restart the service**

Use the project’s existing service start command discovered from current process or project scripts. If the previous service is still running, stop only that project process, then start the same command again.

Concrete PowerShell pattern:

```powershell
Get-Process -Name python,node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*AutoTeam-F*' } | Select-Object Id,ProcessName,Path
```

Then use the exact existing run command from the project script or previous terminal output. Do not kill unrelated Python or Node processes.

- [ ] **Step 4: Manual smoke test in UI**

1. Open 注册账户 page.
2. Select `mail.com` as 邮件供应商.
3. Confirm the `mail.com 邮箱池` card appears.
4. Import one test line:

```text
test@mail.com----gpt-password----mail-password----rt-token
```

5. Confirm import response shows synced account pool and login-batch task starts.
6. Confirm account appears in the 账号池 page.
7. Confirm mail.com 邮箱池 status changes after the login task completes.

- [ ] **Step 5: Final status**

Run:

```powershell
git status --short
```

Expected: clean working tree after commits, or only intentional uncommitted runtime files ignored by git.

