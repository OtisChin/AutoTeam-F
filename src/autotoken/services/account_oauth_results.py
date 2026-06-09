"""Stable result payloads for account OAuth failures."""

from collections.abc import Callable


def oauth_phone_required_result(email: str, exc: Exception) -> dict:
    return {
        "email": email,
        "status": "failed",
        "failure_stage": "oauth_phone_required",
        "message": f"OAuth 需要手机验证，但手机号绑定流程未完成，账号已保留: {email}",
        "error": str(exc),
        "removed_pool_emails": [],
    }


def oauth_phone_rate_limited_result(email: str, exc: Exception) -> dict:
    return {
        "email": email,
        "status": "failed",
        "failure_stage": "oauth_phone_rate_limited",
        "message": f"OAuth 手机号验证请求次数过多，已跳过当前账号: {email}",
        "error": str(exc),
        "removed_pool_emails": [],
    }


def oauth_login_required_result(email: str, exc: Exception) -> dict:
    return {
        "email": email,
        "status": "failed",
        "failure_stage": "oauth_login_required",
        "message": f"OAuth 停在登录页，未获取 authorization code，账号已保留: {email}",
        "error": str(exc),
        "removed_pool_emails": [],
    }


def oauth_account_deactivated_result(
    email: str,
    exc: Exception,
    *,
    remove_account_from_pool: Callable[[list[str]], list[str]],
) -> dict:
    removed = remove_account_from_pool([email])
    return {
        "email": email,
        "status": "failed",
        "failure_stage": "oauth_account_deactivated",
        "message": f"OAuth 检测到 account_deactivated，已从号池删除账号: {email}",
        "error": str(exc),
        "removed_pool_emails": removed,
    }
