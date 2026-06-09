"""Account overview and Codex auth export HTTP routes."""

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException


def create_account_overview_router(
    *,
    load_accounts_with_session_stubs: Callable[..., list[dict]],
    sanitize_accounts_batch: Callable[[list[dict], dict | None], list[dict]],
    sanitize_account: Callable[[dict], dict],
    is_main_account_email: Callable[[str], bool],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/accounts")
    def get_accounts(include_session_stubs: bool = True):
        """获取所有账号列表"""
        accounts = load_accounts_with_session_stubs(include_session_stubs=include_session_stubs)
        return sanitize_accounts_batch(accounts, None)

    @router.get("/api/accounts/{email}/codex-auth")
    def get_codex_auth(email: str):
        """导出账号的 Codex CLI 格式认证文件（~/.codex/auth.json）"""
        from autotoken.auth.codex_auth import get_saved_main_auth_file
        from autotoken.storage.accounts import find_account, load_accounts
        from autotoken.storage.auth_files import (
            read_auth_json_file,
            trusted_auth_file_path,
            trusted_auth_or_session_path,
        )
        from autotoken.storage.auth_session_store import get_auth_session_file
        from autotoken.storage.auth_storage import AUTH_DIR

        email = email.strip().lower()
        auth_file = ""

        if is_main_account_email(email):
            auth_file = get_saved_main_auth_file()
            if not auth_file or not Path(auth_file).exists():
                raise HTTPException(status_code=404, detail="主号没有可导出的认证文件")
        else:
            account = find_account(load_accounts(), email)
            if account:
                candidate = str(account.get("auth_file") or "").strip()
                if candidate:
                    path = trusted_auth_file_path(candidate, auth_dir=AUTH_DIR)
                    if path:
                        auth_file = str(path)
            if not auth_file:
                auth_file = get_auth_session_file(email) or ""
            auth_path = trusted_auth_or_session_path(auth_file, auth_dir=AUTH_DIR)
            if not auth_path:
                raise HTTPException(status_code=404, detail="该账号没有认证文件")
            auth_file = str(auth_path)

        try:
            auth_data = read_auth_json_file(auth_file)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"认证文件无法读取: {exc}") from exc

        access_token = auth_data.get("access_token", "") or auth_data.get("accessToken", "")
        account_id = auth_data.get("account_id", "") or ((auth_data.get("account") or {}).get("id") or "")

        codex_auth = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": auth_data.get("id_token", ""),
                "access_token": access_token,
                "refresh_token": auth_data.get("refresh_token", ""),
                "account_id": account_id,
            },
            "last_refresh": auth_data.get("last_refresh", ""),
        }

        return {
            "email": email,
            "codex_auth": codex_auth,
            "auth_file": auth_file,
            "hint": "将内容保存到 ~/.codex/auth.json（Linux/macOS）或 %APPDATA%\\codex\\auth.json（Windows）",
        }

    @router.get("/api/accounts/active")
    def get_active():
        """获取活跃账号"""
        from autotoken.storage.accounts import get_active_accounts

        return [sanitize_account(account) for account in get_active_accounts()]

    @router.get("/api/accounts/standby")
    def get_standby():
        """获取待命账号"""
        from autotoken.storage.accounts import get_standby_accounts

        return [sanitize_account(account) for account in get_standby_accounts()]

    return router
