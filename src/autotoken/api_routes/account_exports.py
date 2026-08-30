"""Local account export HTTP routes."""

import time
from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.api_routes.input_limits import validate_list_payload_limit

ACCOUNT_EXPORT_MAX_EMAILS = 1_000


class AccountCredentialExportParams(BaseModel):
    emails: list[str] = Field(default_factory=list)
    line_format: str = "{email}-----{password}"
    include_totp_secret: bool = Field(
        False,
        validation_alias=AliasChoices("include_totp_secret", "includeTotpSecret", "include2fa", "include2FA"),
    )


class AccountExportStatusUpdateParams(BaseModel):
    emails: list[str]
    exported: bool


def create_account_exports_router(
    *,
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str], bool],
    sanitize_account: Callable[[dict], dict],
    sanitize_accounts_batch: Callable[[list[dict]], list[dict]] | None = None,
    get_main_account_email: Callable[[], str] | None = None,
    current_time: Callable[[], float] = time.time,
) -> APIRouter:
    router = APIRouter()
    batch_sanitizer = sanitize_accounts_batch or (lambda accounts: [sanitize_account(account) for account in accounts])

    @router.post("/api/accounts/export-credentials")
    def export_account_credentials(params: AccountCredentialExportParams):
        """导出本地账号池账密，固定格式: 邮箱-----密码/Token-----接码地址。"""
        from autotoken.commerce.trade import (
            credential_export_line_for_account,
            generic_api_accounts_by_email,
            icloud_accounts_by_email,
            outlook_accounts_by_email,
            outlook_mailapi_urls_by_email,
        )
        from autotoken.storage.accounts import (
            ACCOUNT_SOURCE_AUTH_SESSION_STUB,
            get_totp_credentials,
            load_accounts,
        )

        validate_list_payload_limit(params.emails, max_items=ACCOUNT_EXPORT_MAX_EMAILS, label="账号导出")
        requested = []
        seen = set()
        for email in params.emails or []:
            normalized = normalize_email(email)
            if normalized and normalized not in seen:
                seen.add(normalized)
                requested.append(normalized)

        accounts = load_accounts()
        rows = []
        missing = []
        by_email = {normalize_email(acc.get("email")): acc for acc in accounts if normalize_email(acc.get("email"))}
        if requested:
            for email in requested:
                account = by_email.get(email)
                if account:
                    rows.append(account)
                else:
                    missing.append(email)
        else:
            rows = accounts

        skipped_session_only = []
        export_rows = []
        for account in rows:
            if str(account.get("account_source") or "").strip().lower() == ACCOUNT_SOURCE_AUTH_SESSION_STUB:
                skipped_session_only.append(normalize_email(account.get("email")))
                continue
            export_rows.append(account)

        outlook_accounts = outlook_accounts_by_email()
        outlook_mailapi_urls = outlook_mailapi_urls_by_email()
        icloud_accounts = icloud_accounts_by_email()
        generic_api_accounts = generic_api_accounts_by_email()
        include_totp_secret = bool(params.include_totp_secret)
        lines = []
        for account in export_rows:
            line = credential_export_line_for_account(
                account,
                outlook_mailapi_urls=outlook_mailapi_urls,
                outlook_accounts=outlook_accounts,
                icloud_accounts=icloud_accounts,
                generic_api_accounts=generic_api_accounts,
            )
            if include_totp_secret:
                credentials = get_totp_credentials(normalize_email(account.get("email"))) or {}
                line = f"{line}-----{credentials.get('secret') or ''}"
            lines.append(line)
        content = "\n".join(lines)
        # Preparing a response is not proof that the browser received or saved it.
        # The frontend confirms these emails through /export-status only after it
        # successfully dispatches the download, keeping a lost response retryable.
        exported_emails = [
            exported_email
            for account in export_rows
            if (exported_email := normalize_email(account.get("email")))
        ]
        return {
            "content": content,
            "count": len(export_rows),
            "missing": missing,
            "skipped_session_only": [email for email in skipped_session_only if email],
            "exported_emails": exported_emails,
            "exported_at": None,
            "filename": "accounts-credentials.txt",
            "format": "{email}-----{password_or_token}-----{mail_url}"
            + ("-----{totp_secret}" if include_totp_secret else ""),
            "totp_included": include_totp_secret,
        }

    @router.post("/api/accounts/export-status")
    def update_accounts_export_status(params: AccountExportStatusUpdateParams):
        """批量修改本地账号账密导出状态。"""
        from autotoken.storage.accounts import update_accounts_export_status_batch

        validate_list_payload_limit(params.emails, max_items=ACCOUNT_EXPORT_MAX_EMAILS, label="账号导出状态更新")
        requested = []
        seen = set()
        for email in params.emails or []:
            normalized = normalize_email(email)
            if normalized and normalized not in seen:
                seen.add(normalized)
                requested.append(normalized)
        if not requested:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        exported_at = current_time() if params.exported else None
        main_email = normalize_email(get_main_account_email()) if get_main_account_email else ""
        if get_main_account_email:
            main_emails = {main_email} & set(requested) if main_email else set()
        else:
            main_emails = {email for email in requested if is_main_account_email(email)}
        eligible = [email for email in requested if email not in main_emails]
        batch_result = update_accounts_export_status_batch(
            eligible,
            exported=bool(params.exported),
            exported_at=exported_at,
        )
        updated = batch_sanitizer(batch_result["accounts"])
        missing_set = main_emails | set(batch_result["missing"])
        missing = [email for email in requested if email in missing_set]

        return {
            "message": f"已更新 {len(updated)} 个账号导出状态",
            "updated": len(updated),
            "exported": bool(params.exported),
            "exported_at": exported_at,
            "missing": missing,
            "trade_allocations": batch_result["trade_allocations"],
            "accounts": updated,
        }

    return router
