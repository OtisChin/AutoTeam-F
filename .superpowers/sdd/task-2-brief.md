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

