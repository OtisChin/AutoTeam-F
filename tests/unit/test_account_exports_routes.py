from fastapi import FastAPI, HTTPException

from autotoken.api_routes.account_exports import (
    ACCOUNT_EXPORT_MAX_EMAILS,
    AccountCredentialExportParams,
    AccountExportStatusUpdateParams,
    create_account_exports_router,
)


def _app():
    app = FastAPI()
    app.include_router(
        create_account_exports_router(
            normalize_email=lambda value: str(value or "").strip().lower(),
            is_main_account_email=lambda email: str(email or "").strip().lower() == "owner@example.com",
            sanitize_account=lambda account: {**account, "sanitized": True},
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
