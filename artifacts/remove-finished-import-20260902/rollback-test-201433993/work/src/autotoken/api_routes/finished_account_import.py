from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.services.finished_account_import import FINISHED_IMPORT_MAX_BYTES


class FinishedAccountImportParams(BaseModel):
    accounts_path: str = Field("", validation_alias=AliasChoices("accounts_path", "accountsPath"))
    mailboxes_path: str = Field("", validation_alias=AliasChoices("mailboxes_path", "mailboxesPath"))
    accounts_content: str = Field("", validation_alias=AliasChoices("accounts_content", "accountsContent"))
    mailboxes_content: str = Field("", validation_alias=AliasChoices("mailboxes_content", "mailboxesContent"))
    accounts_filename: str = Field("", validation_alias=AliasChoices("accounts_filename", "accountsFilename"))
    mailboxes_filename: str = Field("", validation_alias=AliasChoices("mailboxes_filename", "mailboxesFilename"))


def _read_optional_text_file(path_value: str, *, label: str, required: bool) -> tuple[str, str]:
    path_text = str(path_value or "").strip()
    if not path_text:
        if required:
            raise HTTPException(status_code=400, detail=f"{label}路径不能为空")
        return "", ""
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail=f"{label}文件不存在: {path_text}")
    if path.stat().st_size > FINISHED_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"{label}文件过大，最多支持 2MB")
    try:
        return path.read_text(encoding="utf-8-sig"), str(path)
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace"), str(path)


def create_finished_account_import_router(
    *,
    import_finished_accounts_from_text: Callable[..., dict[str, Any]] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/accounts/import-finished")
    def import_finished_accounts(params: FinishedAccountImportParams):
        """Import finished account exports by synthesizing CPA-compatible auth files."""
        if import_finished_accounts_from_text is None:
            from autotoken.services.finished_account_import import import_finished_accounts_from_text as import_func
        else:
            import_func = import_finished_accounts_from_text

        accounts_content = str(params.accounts_content or "")
        accounts_source_name = str(params.accounts_filename or "").strip() or "uploaded-accounts"
        if not accounts_content.strip():
            accounts_content, accounts_source_name = _read_optional_text_file(
                params.accounts_path,
                label="账号",
                required=True,
            )
        elif len(accounts_content.encode("utf-8", errors="ignore")) > FINISHED_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="账号内容过大，最多支持 2MB")

        mailboxes_content = str(params.mailboxes_content or "")
        mailboxes_source_name = str(params.mailboxes_filename or "").strip() or "uploaded-mailboxes"
        if not mailboxes_content.strip() and str(params.mailboxes_path or "").strip():
            mailboxes_content, mailboxes_source_name = _read_optional_text_file(
                params.mailboxes_path,
                label="邮箱池",
                required=False,
            )
        elif len(mailboxes_content.encode("utf-8", errors="ignore")) > FINISHED_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=400, detail="邮箱池内容过大，最多支持 2MB")

        return import_func(
            accounts_content,
            mailboxes_content,
            accounts_source_name=accounts_source_name,
            mailboxes_source_name=mailboxes_source_name,
        )

    return router
