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

