from fastapi import FastAPI, HTTPException

from autotoken.api_routes.mail_accounts import (
    MailAccountBatchParams,
    MailAccountChangePasswordParams,
    MailAccountImportParams,
    MailAccountStatusParams,
    MailAccountUpsertParams,
    create_mail_accounts_router,
    fetch_mail_messages,
)


def _app():
    app = FastAPI()
    app.include_router(create_mail_accounts_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_mail_account_routes_delegate_to_storage(monkeypatch):
    app = _app()
    calls = {}

    monkeypatch.setattr("autotoken.storage.mail_accounts.list_mail_accounts", lambda: [{"email": "one@mail.com"}])
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.import_mail_accounts",
        lambda text: {"imported": 1, "skipped": 0, "total": 1, "emails": ["one@mail.com"], "text": text},
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.sync_mail_accounts_to_account_pool",
        lambda emails=None: {"synced": len(emails or []), "emails": list(emails or []), "skipped": []},
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mailcom_pool_status",
        lambda: {"total": 1, "auth_session_ready": 0, "items": [{"email": "one@mail.com"}]},
    )

    def fake_upsert(payload):
        calls["upsert"] = payload
        return {"email": payload["email"]}

    monkeypatch.setattr("autotoken.storage.mail_accounts.upsert_mail_account", fake_upsert)
    monkeypatch.setattr("autotoken.storage.mail_accounts.update_mail_account", lambda email, payload: {"email": email, **payload})
    monkeypatch.setattr("autotoken.storage.mail_accounts.delete_mail_accounts", lambda emails: {"deleted": len(emails)})
    monkeypatch.setattr("autotoken.storage.mail_accounts.clear_mail_accounts", lambda: {"deleted": 2})
    monkeypatch.setattr("autotoken.storage.mail_accounts.change_mail_passwords", lambda emails, password: {"updated": len(emails), "password": password})
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.get_mail_account",
        lambda email: {"email": email, "mail_password": "old-password"},
    )
    monkeypatch.setattr(
        "autotoken.services.mailcom_password.change_mailcom_password",
        lambda email, old_password, new_password: {"status": "success", "email": email},
    )
    monkeypatch.setattr("autotoken.storage.mail_accounts.set_account_statuses", lambda emails, status: {"updated": len(emails), "status": status})
    monkeypatch.setattr("autotoken.storage.mail_accounts.update_notes", lambda emails, note: {"updated": len(emails), "note": note})
    monkeypatch.setattr("autotoken.storage.mail_accounts.export_mail_accounts", lambda: "one----gpt----mail----rt")

    assert _endpoint(app, "/api/mail-accounts", "GET")()["items"] == [{"email": "one@mail.com"}]
    assert _endpoint(app, "/api/mail-accounts/import", "POST")(MailAccountImportParams(text="line"))["imported"] == 1
    assert _endpoint(app, "/api/mail-accounts", "POST")(
        MailAccountUpsertParams(email="two@mail.com", gptPassword="gpt", mailPassword="mail", refreshToken="rt")
    ) == {"email": "two@mail.com"}
    assert calls["upsert"]["gpt_password"] == "gpt"
    assert calls["upsert"]["mail_password"] == "mail"
    assert calls["upsert"]["refresh_token"] == "rt"
    assert _endpoint(app, "/api/mail-accounts/{email}", "PUT")(
        "two@mail.com",
        MailAccountUpsertParams(email="ignored@mail.com", refresh_token="rt2"),
    )["email"] == "two@mail.com"
    assert _endpoint(app, "/api/mail-accounts/delete", "POST")(MailAccountBatchParams(emails=["a", "b"])) == {"deleted": 2}
    assert _endpoint(app, "/api/mail-accounts/clear", "POST")() == {"deleted": 2}
    assert _endpoint(app, "/api/mail-accounts/change-password", "POST")(
        MailAccountChangePasswordParams(emails=["a@mail.com"], newPassword="new-password-123")
    )["updated"] == 1
    assert _endpoint(app, "/api/mail-accounts/status", "POST")(
        MailAccountStatusParams(emails=["a"], status="disabled")
    ) == {"updated": 1, "status": "disabled"}
    assert _endpoint(app, "/api/mail-accounts/note", "POST")(MailAccountBatchParams(emails=["a"], note="n")) == {
        "updated": 1,
        "note": "n",
    }
    assert _endpoint(app, "/api/mail-accounts/export", "GET")() == {"content": "one----gpt----mail----rt"}


def test_mail_account_change_password_updates_sqlite_only_after_official_success(monkeypatch):
    app = _app()
    calls = {"stored": []}

    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.get_mail_account",
        lambda email: {"email": email, "mail_password": "old-pass"} if email == "ok@mail.com" else {"email": email, "mail_password": "old-pass"},
    )

    def fake_change(email, old_password, new_password):
        if email == "bad@mail.com":
            raise RuntimeError("官网改密失败")
        assert old_password == "old-pass"
        assert new_password == "new-password-123"
        return {"status": "success", "email": email}

    def fake_store(emails, password):
        calls["stored"].append((emails, password))
        return {"updated": len(emails)}

    monkeypatch.setattr("autotoken.services.mailcom_password.change_mailcom_password", fake_change)
    monkeypatch.setattr("autotoken.storage.mail_accounts.change_mail_passwords", fake_store)

    result = _endpoint(app, "/api/mail-accounts/change-password", "POST")(
        MailAccountChangePasswordParams(emails=["ok@mail.com", "bad@mail.com"], newPassword="new-password-123")
    )

    assert result["updated"] == 1
    assert result["failed"] == 1
    assert calls["stored"] == [(["ok@mail.com"], "new-password-123")]
    assert result["results"][0]["status"] == "success"
    assert result["results"][1]["status"] == "failed"


def test_mail_account_check_openai_refresh_token_updates_status(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.get_mail_account",
        lambda email: {"email": email, "mail_password": "mail-pass", "refresh_token": "rt-old"},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.mail_accounts.exchange_openai_refresh_token",
        lambda refresh_token: {"access_token": "openai-at", "refresh_token": "rt-new", "expires_in": 3600},
    )

    captured = {}

    def fake_update(email, **kwargs):
        captured["email"] = email
        captured.update(kwargs)
        return {"email": email, **kwargs}

    monkeypatch.setattr("autotoken.storage.mail_accounts.update_check_result", fake_update)

    result = _endpoint(app, "/api/mail-accounts/check", "POST")(MailAccountBatchParams(emails=["one@mail.com"]))

    assert result["checked"] == 1
    assert result["results"][0]["check_status"] == "valid"
    assert captured["access_token"] == "openai-at"
    assert captured["refresh_token"] == "rt-new"


def test_mail_account_fetch_reads_recent_mailcom_messages(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.get_mail_account",
        lambda email: {"email": email, "mail_password": "mail-pass", "refresh_token": "rt-old"},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.mail_accounts.fetch_mail_messages",
        lambda account, size=10: [
            {
                "id": "m1",
                "subject": "OpenAI verification",
                "sendEmail": "noreply@tm.openai.com",
                "text": "Your code is 123456",
                "createTime": 123,
            }
        ],
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.update_check_result",
        lambda email, **kwargs: {"email": email, **kwargs},
    )

    result = _endpoint(app, "/api/mail-accounts/fetch", "POST")(MailAccountBatchParams(emails=["one@mail.com"]))

    assert result["fetched"] == 1
    assert result["results"][0]["status"] == "ok"
    assert result["results"][0]["messages"][0]["subject"] == "OpenAI verification"


def test_fetch_mail_messages_uses_official_mailcom_web_login(monkeypatch):
    calls = {}

    def fake_fetch(account, size=10):
        calls["account"] = account
        calls["size"] = size
        return [
            {
                "id": "m1",
                "subject": "Your OpenAI code",
                "sendEmail": "noreply@tm.openai.com",
                "toEmail": account["email"],
                "text": "123456",
                "html": "",
                "content": "123456",
                "createTime": 1710000000,
                "createdAt": 1710000000,
                "raw": {"source": "mail.com-lightmailer"},
            }
        ]

    monkeypatch.setattr("autotoken.services.mailcom_webmail.fetch_mailcom_messages", fake_fetch)
    messages = fetch_mail_messages({"email": "one@mail.com", "mail_password": "mail pass"}, size=5)

    assert calls["account"] == {"email": "one@mail.com", "mail_password": "mail pass"}
    assert calls["size"] == 5
    assert messages == [
        {
            "id": "m1",
            "subject": "Your OpenAI code",
            "sendEmail": "noreply@tm.openai.com",
            "toEmail": "one@mail.com",
            "text": "123456",
            "html": "",
            "content": "123456",
            "createTime": 1710000000,
            "createdAt": 1710000000,
            "raw": {"source": "mail.com-lightmailer"},
        }
    ]


def test_mail_account_check_missing_account_returns_404(monkeypatch):
    app = _app()
    monkeypatch.setattr("autotoken.storage.mail_accounts.get_mail_account", lambda _email: None)

    try:
        _endpoint(app, "/api/mail-accounts/check", "POST")(MailAccountBatchParams(emails=["missing@mail.com"]))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("missing account check must fail")


def test_mail_accounts_import_syncs_account_pool_and_returns_pool_status(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.import_mail_accounts",
        lambda text: {"imported": 1, "skipped": 0, "total": 1, "emails": ["one@mail.com"]},
    )
    monkeypatch.setattr("autotoken.storage.mail_accounts.list_mail_accounts", lambda: [{"email": "one@mail.com"}])
    captured = {}

    def fake_sync(emails=None):
        captured["emails"] = list(emails or [])
        return {"synced": 1, "emails": ["one@mail.com"], "skipped": []}

    monkeypatch.setattr("autotoken.storage.mail_accounts.sync_mail_accounts_to_account_pool", fake_sync)
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mailcom_pool_status",
        lambda: {"total": 1, "auth_session_ready": 0, "items": [{"email": "one@mail.com"}]},
    )

    result = _endpoint(app, "/api/mail-accounts/import", "POST")(MailAccountImportParams(text="one@mail.com----g----m----rt"))

    assert result["imported"] == 1
    assert result["synced_account_pool"]["synced"] == 1
    assert result["pool_status"]["total"] == 1
    assert captured["emails"] == ["one@mail.com"]


def test_mail_accounts_import_returns_login_emails_for_synced_enabled_accounts_without_auth_session(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.import_mail_accounts",
        lambda text: {"imported": 1, "skipped": 0, "total": 1, "emails": ["oldformat@mail.com"]},
    )
    monkeypatch.setattr("autotoken.storage.mail_accounts.list_mail_accounts", lambda: [{"email": "oldformat@mail.com"}])
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.sync_mail_accounts_to_account_pool",
        lambda emails=None: {"synced": 1, "emails": list(emails or []), "skipped": []},
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mailcom_pool_status",
        lambda: {
            "total": 1,
            "auth_session_ready": 0,
            "items": [
                {
                    "email": "oldformat@mail.com",
                    "status": "enabled",
                    "auth_session_status": "missing",
                }
            ],
        },
    )

    result = _endpoint(app, "/api/mail-accounts/import", "POST")(
        MailAccountImportParams(text="oldformat@mail.com----gpt-pass----mail-pass----rt-token")
    )

    assert result["login_emails"] == ["oldformat@mail.com"]


def test_mail_accounts_import_can_skip_dashboard_account_pool_sync(monkeypatch):
    app = _app()
    sync_calls = []
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.import_mail_accounts",
        lambda text: {"imported": 1, "skipped": 0, "total": 1, "emails": ["poolonly@mail.com"]},
    )
    monkeypatch.setattr("autotoken.storage.mail_accounts.list_mail_accounts", lambda: [{"email": "poolonly@mail.com"}])
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.sync_mail_accounts_to_account_pool",
        lambda emails=None: sync_calls.append(list(emails or [])) or {"synced": 1, "emails": list(emails or []), "skipped": []},
    )
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mailcom_pool_status",
        lambda: {"total": 1, "auth_session_ready": 0, "items": [{"email": "poolonly@mail.com"}]},
    )

    result = _endpoint(app, "/api/mail-accounts/import", "POST")(
        MailAccountImportParams(
            text="poolonly@mail.com----mail-pass",
            sync_account_pool=False,
        )
    )

    assert result["imported"] == 1
    assert result["synced_account_pool"] == {"synced": 0, "emails": [], "skipped": []}
    assert result["login_emails"] == []
    assert sync_calls == []


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
