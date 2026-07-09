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

