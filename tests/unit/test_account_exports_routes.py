from fastapi import FastAPI, HTTPException

from autotoken.api_routes.account_exports import (
    ACCOUNT_EXPORT_MAX_EMAILS,
    AccountCredentialExportParams,
    AccountExportStatusUpdateParams,
    create_account_exports_router,
)


def _app(*, sanitize_accounts_batch=None, get_main_account_email=None, is_main_account_email=None):
    sanitize_accounts_batch = sanitize_accounts_batch or (
        lambda account_rows: [{**account, "sanitized": True} for account in account_rows]
    )
    app = FastAPI()
    router_kwargs = {
        "normalize_email": lambda value: str(value or "").strip().lower(),
        "is_main_account_email": is_main_account_email
        or (lambda email: str(email or "").strip().lower() == "owner@example.com"),
        "sanitize_account": lambda account: {**account, "sanitized": True},
        "sanitize_accounts_batch": sanitize_accounts_batch,
    }
    if get_main_account_email is not None:
        router_kwargs["get_main_account_email"] = get_main_account_email
    app.include_router(
        create_account_exports_router(
            **router_kwargs,
        )
    )
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_export_account_credentials_rejects_too_many_raw_emails():
    app = _app()

    try:
        _endpoint(app, "/api/accounts/export-credentials", "POST")(
            AccountCredentialExportParams(
                emails=[f"user{index}@example.com" for index in range(ACCOUNT_EXPORT_MAX_EMAILS + 1)]
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "账号导出条目过多" in exc.detail
    else:
        raise AssertionError("oversized credential export selection must fail")


def test_export_account_credentials_prepares_original_outlook_oauth_line_without_committing_status(monkeypatch):
    app = _app()
    updates = []
    account = {
        "email": "User@Outlook.com",
        "password": "chatgpt-password",
        "mail_provider": "outlook",
        "account_source": "managed",
    }
    outlook_source = {
        "user@outlook.com": {
            "email": "User@Outlook.com",
            "password": "mail-password",
            "client_id": "client-id",
            "refresh_token": "refresh-token",
            "mailapi_url": "",
        }
    }

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account",
        lambda email, **kwargs: updates.append((email, kwargs)) or {**account, **kwargs},
    )
    monkeypatch.setattr("autotoken.commerce.trade.outlook_accounts_by_email", lambda: outlook_source)

    result = _endpoint(app, "/api/accounts/export-credentials", "POST")(
        AccountCredentialExportParams(emails=["user@outlook.com"])
    )

    assert result["content"] == "User@Outlook.com----mail-password----client-id----refresh-token"
    assert result["count"] == 1
    assert result["exported_emails"] == ["user@outlook.com"]
    assert result["exported_at"] is None
    assert updates == []


def test_export_account_credentials_keeps_mailapi_outlook_legacy_line(monkeypatch):
    app = _app()
    account = {
        "email": "Mailapi@Outlook.com",
        "password": "chatgpt-password",
        "mail_provider": "outlook",
        "account_source": "managed",
    }
    outlook_source = {
        "mailapi@outlook.com": {
            "email": "Mailapi@Outlook.com",
            "password": "",
            "client_id": "",
            "refresh_token": "",
            "mailapi_url": "https://mailapi.icu/key?type=html&orderNo=secret",
        }
    }

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {**account, **kwargs})
    monkeypatch.setattr("autotoken.commerce.trade.outlook_accounts_by_email", lambda: outlook_source)

    result = _endpoint(app, "/api/accounts/export-credentials", "POST")(
        AccountCredentialExportParams(emails=["mailapi@outlook.com"])
    )

    assert result["content"] == "Mailapi@Outlook.com-----chatgpt-password-----https://mailapi.icu/key?type=html&orderNo=secret"


def test_export_account_credentials_uses_icloud_pool_line(monkeypatch):
    app = _app()
    account = {
        "email": "User@icloud.com",
        "password": "chatgpt-password",
        "mail_provider": "icloud",
        "account_source": "managed",
    }
    icloud_source = {
        "user@icloud.com": {
            "email": "User@icloud.com",
            "receive_code_url": "https://icloud-api.top/show/secret/User@icloud.com",
        }
    }

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {**account, **kwargs})
    monkeypatch.setattr("autotoken.commerce.trade.outlook_accounts_by_email", lambda: {})
    monkeypatch.setattr("autotoken.commerce.trade.icloud_accounts_by_email", lambda: icloud_source)

    result = _endpoint(app, "/api/accounts/export-credentials", "POST")(
        AccountCredentialExportParams(emails=["user@icloud.com"])
    )

    assert result["content"] == "User@icloud.com----https://icloud-api.top/show/secret/User@icloud.com"


def test_export_account_credentials_uses_generic_api_pool_line(monkeypatch):
    app = _app()
    account = {
        "email": "User@dutchmail.com",
        "password": "chatgpt-password",
        "mail_provider": "generic-api",
        "account_source": "managed",
    }

    from autotoken.mail.generic_api import GenericApiAccount, GenericApiMailProvider

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {**account, **kwargs})
    monkeypatch.setattr("autotoken.commerce.trade.outlook_accounts_by_email", lambda: {})
    monkeypatch.setattr("autotoken.commerce.trade.icloud_accounts_by_email", lambda: {})
    monkeypatch.setattr(
        GenericApiMailProvider,
        "_load_accounts",
        lambda self: [GenericApiAccount("User@dutchmail.com", "https://example.com/code/token")],
    )

    result = _endpoint(app, "/api/accounts/export-credentials", "POST")(
        AccountCredentialExportParams(emails=["user@dutchmail.com"])
    )

    assert result["content"] == "User@dutchmail.com----https://example.com/code/token"


def test_export_account_credentials_uses_external_imported_mailapi_url(monkeypatch):
    app = _app()
    account = {
        "email": "nicklesjh-split-6b9c8a@rocketship.com",
        "password": "",
        "mail_provider": "generic-api",
        "mailapi_url": "https://mail.example/api/latest?token=secret",
        "last_bind_provider": "external_import",
        "account_source": "managed",
    }

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {**account, **kwargs})
    monkeypatch.setattr("autotoken.commerce.trade.outlook_accounts_by_email", lambda: {})
    monkeypatch.setattr("autotoken.commerce.trade.icloud_accounts_by_email", lambda: {})
    monkeypatch.setattr("autotoken.commerce.trade.generic_api_accounts_by_email", lambda: {})

    result = _endpoint(app, "/api/accounts/export-credentials", "POST")(
        AccountCredentialExportParams(emails=["nicklesjh-split-6b9c8a@rocketship.com"])
    )

    assert result["content"] == (
        "nicklesjh-split-6b9c8a@rocketship.com----https://mail.example/api/latest?token=secret"
    )


def test_update_accounts_export_status_rejects_too_many_raw_emails():
    app = _app()

    try:
        _endpoint(app, "/api/accounts/export-status", "POST")(
            AccountExportStatusUpdateParams(
                emails=[f"user{index}@example.com" for index in range(ACCOUNT_EXPORT_MAX_EMAILS + 1)],
                exported=True,
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "账号导出状态更新条目过多" in exc.detail
    else:
        raise AssertionError("oversized export status update selection must fail")


def test_update_accounts_export_status_uses_one_batch_write_and_one_batch_sanitizer(monkeypatch):
    sanitizer_calls = []
    storage_calls = []

    def sanitize_batch(account_rows):
        sanitizer_calls.append(account_rows)
        return [{**account, "sanitized": True} for account in account_rows]

    def update_batch(emails, *, exported, exported_at):
        storage_calls.append((emails, exported, exported_at))
        return {
            "accounts": [
                {
                    "email": "user@example.com",
                    "credentials_exported": exported,
                    "credentials_exported_at": exported_at,
                }
            ],
            "missing": ["missing@example.com"],
            "trade_allocations": {"cleared": 0, "codes": []},
        }

    app = _app(sanitize_accounts_batch=sanitize_batch)
    monkeypatch.setattr("autotoken.storage.accounts.update_accounts_export_status_batch", update_batch)
    monkeypatch.setattr(
        "autotoken.storage.accounts.load_accounts",
        lambda: (_ for _ in ()).throw(AssertionError("full account load used")),
    )
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("per-account update used")),
    )

    result = _endpoint(app, "/api/accounts/export-status", "POST")(
        AccountExportStatusUpdateParams(
            emails=["USER@example.com", "owner@example.com", "missing@example.com"],
            exported=True,
        )
    )

    assert storage_calls == [(["user@example.com", "missing@example.com"], True, result["exported_at"])]
    assert len(sanitizer_calls) == 1
    assert sanitizer_calls[0] == [
        {
            "email": "user@example.com",
            "credentials_exported": True,
            "credentials_exported_at": result["exported_at"],
        }
    ]
    assert result["updated"] == 1
    assert result["missing"] == ["owner@example.com", "missing@example.com"]
    assert result["accounts"] == [
        {
            "email": "user@example.com",
            "credentials_exported": True,
            "credentials_exported_at": result["exported_at"],
            "sanitized": True,
        }
    ]


def test_update_accounts_export_status_reads_main_identity_once_per_batch(monkeypatch):
    getter_calls = 0

    def get_main_account_email():
        nonlocal getter_calls
        getter_calls += 1
        return "owner@example.com"

    app = _app(
        get_main_account_email=get_main_account_email,
        is_main_account_email=lambda _email: (_ for _ in ()).throw(
            AssertionError("per-account main identity lookup used")
        ),
    )
    captured = {}

    def update_batch(emails, *, exported, exported_at):
        captured["emails"] = emails
        return {
            "accounts": [],
            "missing": ["missing@example.com"],
            "trade_allocations": {"cleared": 0, "codes": []},
        }

    monkeypatch.setattr("autotoken.storage.accounts.update_accounts_export_status_batch", update_batch)

    result = _endpoint(app, "/api/accounts/export-status", "POST")(
        AccountExportStatusUpdateParams(
            emails=["owner@example.com", "missing@example.com", "user@example.com"],
            exported=True,
        )
    )

    assert getter_calls == 1
    assert captured["emails"] == ["missing@example.com", "user@example.com"]
    assert result["missing"] == ["owner@example.com", "missing@example.com"]


def test_export_account_credentials_excludes_totp_secret_by_default(monkeypatch):
    app = _app()
    account = {
        "email": "totp@example.com",
        "password": "chatgpt-password",
        "mail_provider": "cloudmail",
        "account_source": "managed",
        "two_factor_enabled": True,
        "totp_secret_masked": "GEZD…QOJQ",
    }

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {**account, **kwargs})
    monkeypatch.setattr("autotoken.commerce.trade.outlook_accounts_by_email", lambda: {})
    monkeypatch.setattr("autotoken.commerce.trade.icloud_accounts_by_email", lambda: {})
    monkeypatch.setattr(
        "autotoken.storage.accounts.get_totp_credentials",
        lambda email: {"secret": ("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ")},
    )

    result = _endpoint(app, "/api/accounts/export-credentials", "POST")(
        AccountCredentialExportParams(emails=["totp@example.com"])
    )

    assert "GEZDGNBVGY3TQOJQ" not in result["content"]
    assert result["totp_included"] is False


def test_export_account_credentials_includes_totp_secret_only_when_requested(monkeypatch):
    app = _app()
    account = {
        "email": "totp@example.com",
        "password": "chatgpt-password",
        "mail_provider": "cloudmail",
        "account_source": "managed",
        "two_factor_enabled": True,
        "totp_secret_masked": "GEZD…QOJQ",
    }

    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [account])
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda email, **kwargs: {**account, **kwargs})
    monkeypatch.setattr("autotoken.commerce.trade.outlook_accounts_by_email", lambda: {})
    monkeypatch.setattr("autotoken.commerce.trade.icloud_accounts_by_email", lambda: {})
    monkeypatch.setattr(
        "autotoken.storage.accounts.get_totp_credentials",
        lambda email: {"secret": ("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ")} if email == "totp@example.com" else None,
    )

    result = _endpoint(app, "/api/accounts/export-credentials", "POST")(
        AccountCredentialExportParams(emails=["totp@example.com"], include_totp_secret=True)
    )

    assert result["content"].endswith("-----GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    assert result["totp_included"] is True
    assert result["format"].endswith("-----{totp_secret}")
