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
    current_time: Callable[[], float] = time.time,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/accounts/export-credentials")
    def export_account_credentials(params: AccountCredentialExportParams):
        """导出本地账号池账密，固定格式: 邮箱-----密码/Token-----接码地址。"""
        from autotoken.commerce.trade import (
            credential_export_line_for_account,
            generic_api_accounts_by_email,
            icloud_accounts_by_email,
            outlook_accounts_by_email,
        )
        from autotoken.storage.accounts import (
            ACCOUNT_SOURCE_AUTH_SESSION_STUB,
            get_totp_credentials,
            load_accounts,
            update_account,
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
        outlook_mailapi_urls = {
            email: item["mailapi_url"]
            for email, item in outlook_accounts.items()
            if str(item.get("mailapi_url") or "").strip()
        }
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
        exported_at = current_time()
        exported_emails = []
        for account in export_rows:
            exported_email = normalize_email(account.get("email"))
            if not exported_email:
                continue
            update_account(
                exported_email,
                credentials_exported=True,
                credentials_exported_at=exported_at,
            )
            exported_emails.append(exported_email)
        return {
            "content": content,
            "count": len(export_rows),
            "missing": missing,
            "skipped_session_only": [email for email in skipped_session_only if email],
            "exported_emails": exported_emails,
            "exported_at": exported_at,
            "filename": "accounts-credentials.txt",
            "format": "{email}-----{password_or_token}-----{mail_url}"
            + ("-----{totp_secret}" if include_totp_secret else ""),
            "totp_included": include_totp_secret,
        }

    @router.post("/api/accounts/export-status")
    def update_accounts_export_status(params: AccountExportStatusUpdateParams):
        """批量修改本地账号账密导出状态。"""
        from autotoken.storage.accounts import find_account, load_accounts, update_account

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

        accounts = load_accounts()
        exported_at = current_time() if params.exported else None
        updated = []
        updated_emails = []
        missing = []
        for email in requested:
            if is_main_account_email(email):
                missing.append(email)
                continue
            account = find_account(accounts, email)
            if not account:
                missing.append(email)
                continue
            saved = update_account(
                email,
                credentials_exported=bool(params.exported),
                credentials_exported_at=exported_at,
            )
            if saved:
                updated_emails.append(email)
                updated.append(sanitize_account(saved))
        trade_allocations = {"cleared": 0, "codes": []}
        if not params.exported and updated_emails:
            from autotoken.commerce.trade import clear_trade_allocations_for_emails

            trade_allocations = clear_trade_allocations_for_emails(updated_emails)

        return {
            "message": f"已更新 {len(updated)} 个账号导出状态",
            "updated": len(updated),
            "exported": bool(params.exported),
            "exported_at": exported_at,
            "missing": missing,
            "trade_allocations": trade_allocations,
            "accounts": updated,
        }

    return router
