"""CPA/Codex auth import HTTP routes."""

import base64
import io
import json
import logging
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.core.archive import safe_archive_member_name
from autotoken.core.textio import read_text
from autotoken.storage.auth_files import safe_auth_filename_fragment, trusted_auth_file_path

logger = logging.getLogger(__name__)

MAX_CPA_IMPORT_JSON_BYTES = 5 * 1024 * 1024
MAX_CPA_IMPORT_RAW_BYTES = 20 * 1024 * 1024
MAX_CPA_IMPORT_BASE64_CHARS = ((MAX_CPA_IMPORT_RAW_BYTES + 2) // 3) * 4 + 4096
MAX_CPA_IMPORT_ZIP_JSON_FILES = 200
MAX_CPA_IMPORT_ZIP_TOTAL_BYTES = 20 * 1024 * 1024


class AccountCpaAuthImportSource(BaseModel):
    filename: str = "pasted.json"
    content: str = ""
    content_base64: str = Field("", validation_alias=AliasChoices("content_base64", "contentBase64"))


class AccountCpaAuthImportParams(BaseModel):
    pasted_text: str = Field("", validation_alias=AliasChoices("pasted_text", "pastedText"))
    files: list[AccountCpaAuthImportSource] = Field(default_factory=list)


class AccountEmailBatchParams(BaseModel):
    emails: list[str]


class AccountSessionCpaConvertParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


def _decode_cpa_import_content(source: AccountCpaAuthImportSource) -> bytes:
    if source.content_base64:
        raw = str(source.content_base64).strip()
        if "," in raw and raw.lower().startswith("data:"):
            raw = raw.split(",", 1)[1]
        compact = "".join(raw.split())
        if len(compact) > MAX_CPA_IMPORT_BASE64_CHARS:
            raise ValueError("base64 内容过大")
        try:
            return base64.b64decode(compact, validate=True)
        except Exception as exc:
            raise ValueError("base64 内容无效") from exc
    return str(source.content or "").encode("utf-8")


def _iter_cpa_import_json_items(value, filename: str):
    if isinstance(value, list):
        for index, item in enumerate(value, start=1):
            yield from _iter_cpa_import_json_items(item, f"{filename}#{index}")
        return
    if isinstance(value, dict):
        if isinstance(value.get("auth_data"), dict):
            yield {"name": filename, "auth_data": value.get("auth_data")}
            return
        if isinstance(value.get("codex_auth"), dict):
            yield {"name": filename, "auth_data": value.get("codex_auth")}
            return
        if isinstance(value.get("auths"), list):
            for index, item in enumerate(value.get("auths") or [], start=1):
                item_name = str((item or {}).get("filename") or (item or {}).get("name") or f"{filename}#auth{index}")
                item_data = (item or {}).get("data") if isinstance(item, dict) else item
                if isinstance(item_data, str):
                    try:
                        item_data = json.loads(item_data)
                    except Exception:
                        item_data = None
                yield from _iter_cpa_import_json_items(item_data, item_name)
            return
        yield {"name": filename, "auth_data": value}


def _parse_cpa_import_text(text: str, filename: str):
    stripped = str(text or "").strip()
    if not stripped:
        return [], []
    try:
        value = json.loads(stripped)
    except Exception as exc:
        return [], [{"filename": filename, "error": f"JSON 解析失败: {exc}"}]
    return list(_iter_cpa_import_json_items(value, filename)), []


def _collect_cpa_auth_import_sources(params: AccountCpaAuthImportParams):
    sources = []
    invalid = []

    pasted_sources, pasted_invalid = _parse_cpa_import_text(params.pasted_text, "pasted.json")
    sources.extend(pasted_sources)
    invalid.extend(pasted_invalid)

    for item in params.files or []:
        filename = str(item.filename or "auth.json").strip() or "auth.json"
        try:
            raw = _decode_cpa_import_content(item)
        except Exception as exc:
            invalid.append({"filename": filename, "error": f"内容解码失败: {exc}"})
            continue
        if not raw:
            continue
        if len(raw) > MAX_CPA_IMPORT_RAW_BYTES:
            invalid.append({"filename": filename, "error": "文件过大，已跳过"})
            continue

        is_zip = filename.lower().endswith(".zip") or raw[:4] == b"PK\x03\x04"
        if is_zip:
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    json_entries = 0
                    total_json_size = 0
                    for entry in archive.infolist():
                        if entry.is_dir() or not entry.filename.lower().endswith(".json"):
                            continue
                        json_entries += 1
                        if json_entries > MAX_CPA_IMPORT_ZIP_JSON_FILES:
                            invalid.append({"filename": filename, "error": "ZIP 中 JSON 文件过多，已停止处理"})
                            break
                        total_json_size += int(entry.file_size or 0)
                        if total_json_size > MAX_CPA_IMPORT_ZIP_TOTAL_BYTES:
                            invalid.append({"filename": filename, "error": "ZIP 解压后 JSON 内容过大，已停止处理"})
                            break
                        if entry.file_size > MAX_CPA_IMPORT_JSON_BYTES:
                            invalid.append({"filename": entry.filename, "error": "文件超过 5MB，已跳过"})
                            continue
                        try:
                            entry_raw = archive.read(entry)
                            text = entry_raw.decode("utf-8-sig")
                        except UnicodeDecodeError:
                            text = entry_raw.decode("utf-8", errors="replace")
                        parsed, parse_invalid = _parse_cpa_import_text(text, entry.filename)
                        sources.extend(parsed)
                        invalid.extend(parse_invalid)
            except Exception as exc:
                invalid.append({"filename": filename, "error": f"ZIP 解析失败: {exc}"})
            continue

        if len(raw) > MAX_CPA_IMPORT_JSON_BYTES:
            invalid.append({"filename": filename, "error": "文件超过 5MB，已跳过"})
            continue

        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        parsed, parse_invalid = _parse_cpa_import_text(text, filename)
        sources.extend(parsed)
        invalid.extend(parse_invalid)

    return sources, invalid


def _auth_file_declares_plan(auth_file: str, expected_plan: str) -> bool:
    path = trusted_auth_file_path(auth_file)
    if not path:
        return False
    try:
        payload = json.loads(read_text(path))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    target = str(expected_plan or "").strip().lower()
    if not target:
        return False
    values = [
        payload.get("plan_type"),
        payload.get("chatgpt_plan_type"),
    ]
    for key in ("credentials", "providerSpecificData", "account"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            values.extend([nested.get("plan_type"), nested.get("chatgpt_plan_type")])
    return any(str(value or "").strip().lower() == target for value in values)


def create_account_cpa_auths_router(
    *,
    normalize_email: Callable[[str | None], str] | None = None,
    resolve_codex_auth_file: Callable[[dict], str] | None = None,
    update_account_cpa_auth_plan_type: Callable[..., dict] | None = None,
    convert_account_auth_session_to_cpa_auth: Callable[..., dict] | None = None,
    is_main_account_email: Callable[[str], bool] | None = None,
    verify_plus_plan: Callable[[dict[str, str]], dict] | None = None,
    normalize_observed_auth_plan: Callable[[str, str, str], None] | None = None,
    mark_failed_account: Callable[..., None] | None = None,
    safe_email_summary: Callable[[str], str] | None = None,
    current_time: Callable[[], float] = time.time,
) -> APIRouter:
    router = APIRouter()

    def _normalize_email(value: str | None) -> str:
        if normalize_email:
            return normalize_email(value)
        return (value or "").strip().lower()

    @router.post("/api/accounts/import-cpa-auths")
    def import_account_cpa_auths(params: AccountCpaAuthImportParams):
        """导入本地 CPA/Codex auth JSON，支持粘贴、多个 JSON 文件和 ZIP。"""
        from autotoken.integrations.cpa_sync import import_local_cpa_auth_sources

        sources, parse_invalid = _collect_cpa_auth_import_sources(params)
        if not sources and not parse_invalid:
            raise HTTPException(status_code=400, detail="请粘贴 CPA JSON，或选择 JSON/ZIP 文件")

        result = import_local_cpa_auth_sources(sources)
        result["invalid"] = parse_invalid + list(result.get("invalid") or [])
        if not result.get("files") and result.get("invalid"):
            raise HTTPException(
                status_code=400, detail={"message": "未导入任何有效 CPA 认证文件", "invalid": result["invalid"]}
            )
        return result

    @router.post("/api/accounts/convert-session-cpa-auths")
    def convert_account_session_cpa_auths(params: AccountSessionCpaConvertParams):
        """直接把 ChatGPT Web auth_session 转成本地 CPA codex auth 文件，不走 Codex OAuth。"""
        from autotoken.integrations.session_cpa_converter import SessionConversionError
        from autotoken.storage.accounts import find_account, load_accounts

        if convert_account_auth_session_to_cpa_auth is None:
            raise RuntimeError("convert_account_auth_session_to_cpa_auth dependency is required")
        if is_main_account_email is None:
            raise RuntimeError("is_main_account_email dependency is required")

        requested = []
        seen = set()
        for email in params.emails or []:
            normalized = _normalize_email(email)
            if normalized and normalized not in seen:
                seen.add(normalized)
                requested.append(normalized)
        if not requested:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        accounts = load_accounts()
        converted = []
        missing = []
        invalid = []
        for email in requested:
            account = find_account(accounts, email)
            if not account or is_main_account_email(email):
                missing.append(email)
                continue
            try:
                result = convert_account_auth_session_to_cpa_auth(email, account=account)
            except SessionConversionError as exc:
                invalid.append({"email": email, "error": str(exc)})
                continue
            converted.append(result)

        if not converted and not invalid:
            raise HTTPException(status_code=404, detail="选中的账号没有可转换的 auth_session")

        return {
            "converted": len(converted),
            "missing": missing,
            "invalid": invalid,
            "files": [
                {
                    "email": item["email"],
                    "filename": item["filename"],
                    "auth_file": item["auth_file"],
                    "id_token_synthetic": item["id_token_synthetic"],
                    "refresh_token_present": item["refresh_token_present"],
                }
                for item in converted
            ],
            "accounts": [item["account"] for item in converted if item.get("account")],
        }

    @router.post("/api/accounts/export-cpa-auths")
    def export_account_cpa_auths(params: AccountEmailBatchParams):
        """导出 data/auths 下的 CPA 兼容认证 JSON。单个返回 JSON，多个返回 zip。"""
        from autotoken.storage.accounts import ACCOUNT_TYPE_PLUS, find_account, load_accounts, update_account

        if resolve_codex_auth_file is None:
            raise RuntimeError("resolve_codex_auth_file dependency is required")
        if update_account_cpa_auth_plan_type is None:
            raise RuntimeError("update_account_cpa_auth_plan_type dependency is required")
        if verify_plus_plan is None:
            raise RuntimeError("verify_plus_plan dependency is required")
        if normalize_observed_auth_plan is None:
            raise RuntimeError("normalize_observed_auth_plan dependency is required")
        if mark_failed_account is None:
            raise RuntimeError("mark_failed_account dependency is required")

        requested = []
        seen = set()
        for email in params.emails or []:
            normalized = _normalize_email(email)
            if normalized and normalized not in seen:
                seen.add(normalized)
                requested.append(normalized)
        if not requested:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        accounts = load_accounts()
        files = []
        missing = []
        unconfirmed_plus = []
        for email in requested:
            account = find_account(accounts, email)
            if not account:
                missing.append(email)
                continue
            auth_file = resolve_codex_auth_file(account)
            if not auth_file and str(account.get("account_type") or "").strip().lower() == ACCOUNT_TYPE_PLUS:
                try:
                    from autotoken.storage.auth_session_store import get_auth_session_file

                    session_auth_file = str(get_auth_session_file(email) or "").strip()
                    if session_auth_file and Path(session_auth_file).exists():
                        plan_update = update_account_cpa_auth_plan_type(
                            email,
                            account={**account, "auth_file": session_auth_file},
                            plan_type=ACCOUNT_TYPE_PLUS,
                        )
                        auth_file = str(plan_update.get("auth_file") or "")
                        if auth_file:
                            account = {**account, "auth_file": auth_file}
                except Exception:
                    summary = safe_email_summary(email) if safe_email_summary else email
                    logger.warning("[API] CPA auth 导出兜底转换 auth_session 失败: email=%s", summary, exc_info=True)
            if not auth_file:
                missing.append(email)
                continue
            if str(account.get("account_type") or "").strip().lower() == ACCOUNT_TYPE_PLUS:
                external_import = str(account.get("last_bind_provider") or "").strip().lower() == "external_import"
                if external_import:
                    plan_update = update_account_cpa_auth_plan_type(email, account=account, plan_type=ACCOUNT_TYPE_PLUS)
                    auth_file = str(plan_update.get("auth_file") or auth_file)
                    account = {**account, "auth_file": auth_file}
                elif not _auth_file_declares_plan(auth_file, ACCOUNT_TYPE_PLUS):
                    verification = verify_plus_plan(
                        {
                            "email": email,
                            "auth_file": auth_file,
                        }
                    )
                    if not verification.get("ok"):
                        message = str(verification.get("message") or "OpenAI Plus 状态未确认")
                        normalize_observed_auth_plan(email, auth_file, str(verification.get("plan_type") or ""))
                        summary = safe_email_summary(email) if safe_email_summary else email
                        logger.warning("[API] CPA auth 导出跳过未确认 Plus: email=%s message=%s", summary, message)
                        mark_failed_account(
                            email,
                            task_id="export-cpa-auths",
                            status="pending_manual",
                            message=f"导出前检测到 {message}",
                            failure_stage="export_plan_verify",
                        )
                        missing.append(email)
                        unconfirmed_plus.append({"email": email, "message": message})
                        continue
                    plan_update = update_account_cpa_auth_plan_type(email, account=account, plan_type=ACCOUNT_TYPE_PLUS)
                    auth_file = str(plan_update.get("auth_file") or auth_file)
                else:
                    plan_update = update_account_cpa_auth_plan_type(email, account=account, plan_type=ACCOUNT_TYPE_PLUS)
                    auth_file = str(plan_update.get("auth_file") or auth_file)
            path = trusted_auth_file_path(auth_file)
            if not path:
                missing.append(email)
                continue
            try:
                content = read_text(path)
                json.loads(content)
            except Exception as exc:
                logger.warning("[API] CPA auth 导出跳过无效文件: email=%s path=%s error=%s", email, path, exc)
                missing.append(email)
                continue
            files.append({"email": email, "filename": path.name, "content": content})

        if not files:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "选中的账号没有可导出的 data/auths 认证文件，或 Plus 状态未通过 OpenAI 实测",
                    "missing": missing,
                    "unconfirmed_plus": unconfirmed_plus,
                },
            )

        exported_at = current_time()
        exported_emails = []
        for file in files:
            email = _normalize_email(file.get("email"))
            if not email:
                continue
            update_account(
                email,
                credentials_exported=True,
                credentials_exported_at=exported_at,
            )
            exported_emails.append(email)

        if len(files) == 1:
            file = files[0]
            raw = file["content"].encode("utf-8")
            filename = safe_archive_member_name(
                file["filename"],
                fallback="auth.json",
                default_suffix=".json",
                allowed_suffixes={".json"},
            )
            content_type = "application/json"
        else:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                used_names = set()
                for file in files:
                    name = safe_archive_member_name(
                        file["filename"],
                        fallback="auth.json",
                        default_suffix=".json",
                        allowed_suffixes={".json"},
                    )
                    if name in used_names:
                        stem = Path(name).stem
                        suffix = Path(name).suffix or ".json"
                        name = safe_archive_member_name(
                            f"{stem}-{safe_auth_filename_fragment(file['email'])}{suffix}",
                            fallback="auth.json",
                            default_suffix=".json",
                            allowed_suffixes={".json"},
                            strip_paths=False,
                        )
                    used_names.add(name)
                    archive.writestr(name, file["content"])
            raw = buffer.getvalue()
            filename = f"cpa-auths-{time.strftime('%Y%m%d-%H%M%S')}.zip"
            content_type = "application/zip"

        return {
            "filename": filename,
            "content_type": content_type,
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "count": len(files),
            "missing": missing,
            "unconfirmed_plus": unconfirmed_plus,
            "exported_emails": exported_emails,
            "exported_at": exported_at,
            "files": [{"email": file["email"], "filename": file["filename"]} for file in files],
        }

    @router.post("/api/accounts/export-sub-auths")
    def export_account_sub_auths(params: AccountEmailBatchParams):
        """导出所选账号的 Sub2API 导入 JSON。"""
        from autotoken.integrations.sub2api_converter import (
            ConversionError,
            ExportSettings,
            export_records,
            generate_default_filename,
            inspect_sources,
        )
        from autotoken.storage.accounts import ACCOUNT_TYPE_PLUS, find_account, load_accounts, update_account

        if resolve_codex_auth_file is None:
            raise RuntimeError("resolve_codex_auth_file dependency is required")
        if update_account_cpa_auth_plan_type is None:
            raise RuntimeError("update_account_cpa_auth_plan_type dependency is required")

        requested = []
        seen = set()
        for email in params.emails or []:
            normalized = _normalize_email(email)
            if normalized and normalized not in seen:
                seen.add(normalized)
                requested.append(normalized)
        if not requested:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        accounts = load_accounts()
        sources = []
        missing = []
        for email in requested:
            account = find_account(accounts, email)
            if not account:
                missing.append(email)
                continue
            auth_file = resolve_codex_auth_file(account)
            if not auth_file:
                missing.append(email)
                continue
            if str(account.get("account_type") or "").strip().lower() == ACCOUNT_TYPE_PLUS:
                plan_update = update_account_cpa_auth_plan_type(email, account=account, plan_type=ACCOUNT_TYPE_PLUS)
                auth_file = str(plan_update.get("auth_file") or auth_file)
            path = trusted_auth_file_path(auth_file)
            if not path:
                missing.append(email)
                continue
            try:
                content = read_text(path)
                json.loads(content)
            except Exception as exc:
                logger.warning("[API] Sub auth 导出跳过无效文件: email=%s path=%s error=%s", email, path, exc)
                missing.append(email)
                continue
            sources.append({"email": email, "filename": path.name, "content": content})

        if not sources:
            raise HTTPException(status_code=404, detail="选中的账号没有可转换的 data/auths 认证文件")

        try:
            records = inspect_sources([(item["filename"], item["content"]) for item in sources])
            filename = generate_default_filename()
            payload = export_records(records, ExportSettings(output_filename=filename))
        except ConversionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        valid_filenames = {record.file_name for record in records if record.is_valid and record.selected}
        exported_sources = [item for item in sources if item["filename"] in valid_filenames]
        invalid = [
            {
                "filename": record.file_name,
                "error": record.error_message or record.status_text,
            }
            for record in records
            if not record.is_valid
        ]

        exported_at = current_time()
        exported_emails = []
        for item in exported_sources:
            email = _normalize_email(item.get("email"))
            if not email:
                continue
            update_account(
                email,
                credentials_exported=True,
                credentials_exported_at=exported_at,
            )
            exported_emails.append(email)

        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return {
            "filename": filename,
            "content_type": "application/json",
            "content_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "count": len(payload.get("accounts") or []),
            "missing": missing,
            "invalid": invalid,
            "exported_emails": exported_emails,
            "exported_at": exported_at,
            "files": [{"email": item["email"], "filename": item["filename"]} for item in exported_sources],
        }

    return router
