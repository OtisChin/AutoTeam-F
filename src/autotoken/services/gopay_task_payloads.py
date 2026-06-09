from typing import Any


def gopay_proxy_api_selected_progress(
    *,
    current: int,
    total: int,
    proxy_label: str,
    proxy_api_provider: str,
    selected_proxy_summary: str,
) -> dict[str, Any]:
    provider = proxy_api_provider or "cliproxy"
    return {
        "stage": "gopay_proxy_api_selected",
        "current": current,
        "total": total,
        "proxy_label": proxy_label,
        "proxy_api_provider": provider,
        "proxy_api_url_present": True,
        "message": f"已通过 {provider} API 获取 GoPay 注册代理: {selected_proxy_summary}",
    }


def gopay_proxy_selected_progress(
    *,
    current: int,
    total: int,
    proxy_label: str,
    proxy_pool_count: int,
    selected_proxy_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_proxy_selected",
        "current": current,
        "total": total,
        "proxy_label": proxy_label,
        "proxy_pool_count": proxy_pool_count,
        "message": f"已从 GoPay 动态代理池选择代理: {selected_proxy_summary}",
    }


def gopay_binding_progress(
    *,
    email: str,
    auto_register: bool,
    auto_register_count: int,
    auto_register_protocol: bool,
    gopay_auto_signup: bool,
    phone_number: str,
    country_code: str,
    phone_account_count: int,
    checkout_ui_mode: str,
    proxy_label: str,
    account_count: int,
    pending_retry_attempts: int,
    concurrency: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_binding",
        "email": email,
        "auto_register": auto_register,
        "auto_register_count": auto_register_count,
        "auto_register_protocol": auto_register_protocol,
        "gopay_auto_signup": gopay_auto_signup,
        "phone_number": phone_number,
        "country_code": country_code,
        "phone_account_count": phone_account_count,
        "checkout_ui_mode": checkout_ui_mode,
        "proxy_label": proxy_label,
        "account_count": account_count,
        "pending_retry_attempts": pending_retry_attempts,
        "concurrency": concurrency,
    }


def gopay_concurrency_limited_progress(*, requested_concurrency: int, concurrency: int) -> dict[str, Any]:
    return {
        "stage": "gopay_concurrency_limited",
        "requested_concurrency": requested_concurrency,
        "concurrency": concurrency,
        "message": f"GoPay 并发已限制为 {concurrency}，避免 checkout/自动注册/手机号资源冲突",
        "level": "warn",
    }


def gopay_bind_proxy_bypassed_progress() -> dict[str, Any]:
    return {
        "stage": "gopay_bind_proxy_bypassed",
        "message": "GoPay 绑定阶段不使用 SOCKS 代理，checkout/Stripe/Midtrans 将直连",
    }


def gopay_task_exception_result(*, failure_stage: str, error: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": failure_stage,
        "message": f"GoPay 任务执行异常: {error}",
        "screenshot_paths": [],
    }


def gopay_auth_session_refresh_failed_progress(
    *,
    email: str,
    failure_stage: str,
    removed_pool_emails: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_auth_session_refresh_failed",
        "email": email,
        "failure_stage": failure_stage or "token_invalidated",
        "removed_pool_emails": removed_pool_emails,
        "message": message,
        "level": "warn",
    }


def gopay_bind_failure_result(*, failure_stage: str, message: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": failure_stage,
        "message": str(message),
        "screenshot_paths": [],
    }


def gopay_invalid_email_result() -> dict[str, Any]:
    return {"status": "failed", "failure_stage": "invalid_email", "message": "邮箱为空"}


def gopay_cancelled_result() -> dict[str, Any]:
    return {"status": "cancelled", "failure_stage": "cancelled", "message": "任务已取消"}


def gopay_wallet_otp_session_retained_progress(*, phone_number: str) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_otp_session_retained",
        "phone_number": phone_number,
        "message": "GoPay 绑定未完整成功，已保留短信接码会话，未标记完成或取消",
        "level": "warn",
    }


def gopay_wallet_preserved_progress(*, phone_number: str, expires_in_seconds: int) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_preserved",
        "phone_number": phone_number,
        "expires_in_seconds": expires_in_seconds,
        "message": "当前失败未完成 GoPay 绑定，钱包已放入可复用池，后续账号/新任务会优先复用",
        "level": "warn",
    }


def gopay_wallet_reuse_discarded_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_reuse_discarded",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "reason": reason,
        "message": "复用 GoPay 钱包的短信会话已不可用，丢弃该钱包并重新注册",
        "level": "warn",
    }


def gopay_wallet_reused_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    expires_in_seconds: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_reused",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "expires_in_seconds": expires_in_seconds,
        "message": f"优先复用 20 分钟有效期内未完成绑定的 GoPay 钱包 ({current}/{total})",
    }


def gopay_wallet_balance_wait_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    delay_seconds: float,
    attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    rounded_delay = round(float(delay_seconds or 0.0), 1)
    return {
        "stage": "gopay_wallet_balance_wait",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "delay_seconds": rounded_delay,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"等待 {float(delay_seconds or 0.0):.1f}s 后第 {attempt}/{max_attempts} 次查询 GoPay 余额",
        "level": "warn",
    }


def gopay_wallet_balance_check_failed_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    attempt: int,
    max_attempts: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_balance_check_failed",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"GoPay 余额查询失败 ({attempt}/{max_attempts}): {error_summary}",
        "level": "warn",
    }


def gopay_wallet_balance_checked_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    balance: float,
    currency: str,
    display_value: Any,
    attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    display_text = display_value or balance
    return {
        "stage": "gopay_wallet_balance_checked",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "balance": balance,
        "currency": currency or "IDR",
        "display_value": display_value or "",
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"GoPay 钱包余额查询: {display_text} ({attempt}/{max_attempts})",
    }


def gopay_wallet_balance_ready_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    balance: float,
    currency: str,
    display_value: Any,
    message: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_balance_ready",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "balance": balance,
        "currency": currency or "IDR",
        "display_value": display_value or "",
        "message": message,
        "level": "success",
    }


def gopay_wallet_balance_not_ready_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    message: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_balance_not_ready",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": message,
        "level": "warn",
    }


def gopay_wallet_balance_insufficient_limit_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    balance_insufficient_count: int,
    message: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_balance_insufficient_limit",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "balance_insufficient_count": balance_insufficient_count,
        "message": message,
        "level": "error",
    }


def gopay_wallet_balance_auto_transfer_enabled_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    balance_miss_count: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_balance_auto_transfer_enabled",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "balance_miss_count": balance_miss_count,
        "message": "连续 3 个 GoPay 钱包官方赠送 Rp1 未到账，已切换到 Rekberinaja 转账模式",
        "level": "warn",
    }


def gopay_wallet_transfer_auto_disabled_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    balance: float,
    currency: str,
    display_value: Any,
    balance_1001_count: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_transfer_auto_disabled",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "balance": balance,
        "currency": currency or "IDR",
        "display_value": display_value or "",
        "balance_1001_count": balance_1001_count,
        "message": "连续 3 次 Rekberinaja 转账后 GoPay 余额为 Rp1001，判断官方 Rp1 已恢复赠送，本任务后续关闭转账并等待官方 Rp1 到账",
        "level": "warn",
    }


def gopay_wallet_funding_skipped_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    message: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_funding_skipped",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": message,
    }


def gopay_wallet_funding_started_progress(*, current: int, total: int, phone_number: str) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_funding_started",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": f"正在通过 Rekberinaja 站内余额给 GoPay 钱包充值 ({current}/{total})",
    }


def gopay_wallet_funding_failed_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    transaction_id: str,
    rekberinaja_stage: str,
    debited_possible: bool,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_funding_failed",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "transaction_id": transaction_id,
        "rekberinaja_stage": rekberinaja_stage,
        "debited_possible": debited_possible,
        "message": (
            "Rekberinaja 充值失败；订单已进入站内支付阶段，后续复用该钱包时不会重复充值"
            if debited_possible
            else f"Rekberinaja 充值失败: {error_summary}"
        ),
        "level": "warn",
    }


def gopay_wallet_funding_submitted_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    transaction_id: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_funding_submitted",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "transaction_id": transaction_id,
        "message": f"Rekberinaja GoPay 转账已提交，开始轮询 GoPay 余额 ({current}/{total})",
    }


def gopay_wallet_funding_done_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    transaction_id: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_funding_done",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "transaction_id": transaction_id,
        "message": f"Rekberinaja GoPay 转账余额已到账 ({current}/{total})",
    }


def gopay_wallet_balance_fallback_transfer_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    wait_seconds_total: float,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_balance_fallback_transfer",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": f"GoPay 余额 {wait_seconds_total:.0f}s 内未到账，开始回退到 Rekberinaja 转账",
        "level": "warn",
    }


def gopay_wallet_no_transfer_bind_wait_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
    delay_seconds: float,
) -> dict[str, Any]:
    rounded_delay = round(float(delay_seconds or 0.0), 1)
    return {
        "stage": "gopay_wallet_no_transfer_bind_wait",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "delay_seconds": rounded_delay,
        "message": f"未启用 GoPay 充值/转账，等待 {float(delay_seconds or 0.0):.1f}s 后开始绑定 ({current}/{total})",
    }


def gopay_wallet_auto_signup_detail_progress(
    *,
    current: int,
    total: int,
    attempt: int,
    max_attempts: int,
    message: str,
    worker_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_detail",
        "current": current,
        "total": total,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": message,
        **(worker_fields or {}),
    }


def gopay_wallet_auto_signup_started_progress(
    *,
    current: int,
    total: int,
    wallet_attempt: int,
    max_wallet_attempts: int,
    sms_provider: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_started",
        "current": current,
        "total": total,
        "attempt": wallet_attempt,
        "max_attempts": max_wallet_attempts,
        "sms_provider": sms_provider,
        "message": f"正在自动注册 GoPay 钱包 ({current}/{total})，取号尝试 {wallet_attempt}/{max_wallet_attempts}",
    }


def gopay_wallet_auto_signup_retry_progress(
    *,
    current: int,
    total: int,
    next_attempt: int,
    max_attempts: int,
    error_summary: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_retry",
        "current": current,
        "total": total,
        "attempt": next_attempt,
        "max_attempts": max_attempts,
        "message": message or f"GoPay 钱包自动注册失败，准备换号重试: {error_summary}",
        "level": "warn",
    }


def gopay_wallet_auto_signup_done_progress(*, current: int, total: int, phone_number: str) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_done",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": f"GoPay 钱包自动注册完成 ({current}/{total})",
    }


def gopay_wallet_auto_signup_probe_failed_progress(
    *,
    current: int,
    total: int,
    attempt: int,
    max_attempts: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_probe_failed",
        "current": current,
        "total": total,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"GoPay 注册前探测异常，已停止继续取号: {error_summary}",
        "level": "error",
    }


def gopay_wallet_auto_signup_rate_limited_progress(
    *,
    current: int,
    total: int,
    attempt: int,
    max_attempts: int,
    no_numbers_attempt: int,
    no_numbers_max_attempts: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_rate_limited",
        "current": current,
        "total": total,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "no_numbers_attempt": no_numbers_attempt,
        "no_numbers_max_attempts": no_numbers_max_attempts,
        "message": f"GoPay 钱包自动注册触发 rate_limited，已停止任务: {error_summary}",
        "level": "error",
    }


def gopay_wallet_auto_signup_no_numbers_retry_progress(
    *,
    current: int,
    total: int,
    attempt: int,
    max_attempts: int,
    no_numbers_attempt: int,
    no_numbers_max_attempts: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_no_numbers_retry",
        "current": current,
        "total": total,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "no_numbers_attempt": no_numbers_attempt,
        "no_numbers_max_attempts": no_numbers_max_attempts,
        "message": (
            f"GoPay 钱包自动注册暂时无可用号码，准备第 {no_numbers_attempt + 1}/{no_numbers_max_attempts} 次重新取号: "
            f"{error_summary}"
        ),
        "level": "warn",
    }


def gopay_wallet_auto_signup_no_numbers_progress(
    *,
    current: int,
    total: int,
    attempt: int,
    max_attempts: int,
    no_numbers_attempt: int,
    no_numbers_max_attempts: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_no_numbers",
        "current": current,
        "total": total,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "no_numbers_attempt": no_numbers_attempt,
        "no_numbers_max_attempts": no_numbers_max_attempts,
        "message": f"GoPay 钱包自动注册暂时无可用号码，将进入待重试: {error_summary}",
        "level": "warn",
    }


def gopay_wallet_auto_signup_provider_error_progress(
    *,
    current: int,
    total: int,
    attempt: int,
    max_attempts: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_provider_error",
        "current": current,
        "total": total,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"GoPay 钱包自动注册供应商不可用，已停止当前账号: {error_summary}",
        "level": "error",
    }


def gopay_wallet_auto_signup_network_error_progress(
    *,
    current: int,
    total: int,
    attempt: int,
    max_attempts: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_auto_signup_network_error",
        "current": current,
        "total": total,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"GoPay 钱包自动注册遇到网络中断，已停止继续换号: {error_summary}",
        "level": "warn",
    }


def gopay_wallet_balance_abandoned_progress(*, current: int, total: int, phone_number: str) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_balance_abandoned",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": "GoPay 余额未到账，已取消该短信会话并准备重新注册钱包",
        "level": "warn",
    }


def gopay_wallet_already_linked_discarded_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_already_linked_discarded",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": "该 GoPay 手机号已绑定其他账号，已舍弃该钱包并重新注册",
        "level": "warn",
    }


def gopay_wallet_charge_denied_discarded_progress(
    *,
    current: int,
    total: int,
    phone_number: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_charge_denied_discarded",
        "current": current,
        "total": total,
        "phone_number": phone_number,
        "message": "Midtrans 拒绝该 GoPay 钱包扣款，已舍弃该钱包并准备重新注册",
        "level": "warn",
    }


def gopay_wallet_signup_retry_same_account_progress(
    *,
    email: str,
    current: int,
    total: int,
    next_attempt: int,
    max_attempts: int,
    failure_stage: str,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_signup_retry_same_account",
        "email": email,
        "current": current,
        "total": total,
        "attempt": next_attempt,
        "max_attempts": max_attempts,
        "failure_stage": failure_stage,
        "message": f"GoPay 钱包注册未拿到可用手机号，继续为当前账号重新注册钱包后绑定: {error_summary}",
        "level": "warn",
    }


def gopay_wallet_charge_denied_retry_progress(
    *,
    email: str,
    current: int,
    total: int,
    next_attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_charge_denied_retry",
        "email": email,
        "current": current,
        "total": total,
        "attempt": next_attempt,
        "max_attempts": max_attempts,
        "message": "Midtrans 拒绝该 GoPay 钱包扣款，正在重新注册 GoPay 钱包后重试当前账号",
        "level": "warn",
    }


def gopay_wallet_already_linked_retry_progress(
    *,
    email: str,
    current: int,
    total: int,
    next_attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_already_linked_retry",
        "email": email,
        "current": current,
        "total": total,
        "attempt": next_attempt,
        "max_attempts": max_attempts,
        "message": "GoPay 手机号已绑定其他账号，正在重新注册 GoPay 钱包后重试当前账号",
        "level": "warn",
    }


def gopay_bind_attempt_finished_progress(
    *,
    email: str,
    current: int,
    total: int,
    wallet_attempt: int,
    status: str,
    failure_stage: str,
    detail: str,
) -> dict[str, Any]:
    normalized_status = status or "failed"
    normalized_failure_stage = failure_stage or ""
    return {
        "stage": "gopay_bind_attempt_finished",
        "email": email,
        "current": current,
        "total": total,
        "wallet_attempt": wallet_attempt,
        "status": normalized_status,
        "failure_stage": normalized_failure_stage,
        "message": (
            f"GoPay 绑定尝试返回: status={normalized_status}; "
            f"failure_stage={normalized_failure_stage or '-'}; detail={detail or '-'}"
        ),
        "level": "info" if normalized_status == "success" else "warn",
    }


def gopay_wallet_prefetch_started_progress(*, current: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_prefetch_started",
        "current": current,
        "total": total,
        "message": f"后台预注册 GoPay 钱包 ({current}/{total})",
    }


def gopay_wallet_prefetch_wait_progress(*, current: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_prefetch_wait",
        "current": current,
        "total": total,
        "message": f"等待后台预注册 GoPay 钱包完成 ({current}/{total})",
    }


def gopay_wallet_prefetch_failed_progress(
    *,
    current: int,
    total: int,
    prefetch_index: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_prefetch_failed",
        "current": current,
        "total": total,
        "prefetch_index": prefetch_index,
        "message": f"后台预注册 GoPay 钱包失败，回退同步注册: {error_summary}",
        "level": "warn",
    }


def gopay_wallet_prefetch_used_progress(
    *,
    current: int,
    total: int,
    prefetch_index: int,
    phone_number: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_prefetch_used",
        "current": current,
        "total": total,
        "prefetch_index": prefetch_index,
        "phone_number": phone_number,
        "message": f"使用后台预注册 GoPay 钱包 ({current}/{total})",
    }


def gopay_auto_signup_account_success_progress(
    *,
    email: str,
    current: int,
    total: int,
    successful_count: int,
    message: str,
    success_progress_fields: dict[str, Any],
    retry_round: int | None = None,
    max_retry_rounds: int | None = None,
    position_field: str = "attempt",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "gopay_auto_signup_account_success",
        "email": email,
        position_field: current,
        "total": total,
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    if max_retry_rounds is not None:
        payload["max_retry_rounds"] = max_retry_rounds
    payload.update(
        {
            "successful": successful_count,
            "message": message,
        }
    )
    payload.update(success_progress_fields)
    return payload


def gopay_wallet_signup_failed_no_account_retry_progress(
    *,
    email: str,
    retry_round: int,
    max_retry_rounds: int,
    reason: str,
    failure_stage: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_wallet_signup_failed_no_account_retry",
        "email": email,
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "reason": reason,
        "failure_stage": failure_stage,
        "message": f"GoPay 钱包注册阶段失败，账号尚未进入绑定，不加入账号待重试池: {email}",
        "level": "warn",
    }


def gopay_account_failed_wallet_preserved_progress(
    *,
    email: str,
    retry_round: int,
    max_retry_rounds: int,
    reason: str,
    failure_stage: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_account_failed_wallet_preserved",
        "email": email,
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "reason": reason,
        "failure_stage": failure_stage,
        "message": f"GoPay 邮箱账号侧失败，已保留注册好的钱包给其他账号复用: {email}",
        "level": "warn",
    }


def gopay_auto_register_started_progress(
    *,
    current: int,
    total: int,
    mail_provider: str,
    luckmail_email_type: str,
    luckmail_register_domain: str | None,
    register_domain: str,
) -> dict[str, Any]:
    if mail_provider == "luckmail":
        provider_message = (
            f"LuckMail/{luckmail_email_type or '默认'}"
            + (f"/@{luckmail_register_domain}" if luckmail_register_domain else "/自动分配")
        )
    elif mail_provider == "outlook":
        provider_message = "Outlook账号池"
    else:
        provider_message = f"domain=@{register_domain}"
    return {
        "stage": "gopay_auto_register_started",
        "current": current,
        "total": total,
        "message": f"自动注册已开始 ({current}/{total}): {provider_message}",
    }


def gopay_auto_register_done_progress(*, email: str, current: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_auto_register_done",
        "email": email,
        "current": current,
        "total": total,
        "message": f"自动注册完成 ({current}/{total})，开始 GoPay 绑定: {email}",
    }


def gopay_auto_register_next_progress(*, current: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_auto_register_next",
        "current": current,
        "total": total,
        "message": f"自动注册 GoPay 进度: {current}/{total}",
    }


def gopay_auto_register_child_progress(
    progress: dict[str, Any],
    *,
    current: int,
    total: int,
) -> dict[str, Any]:
    stage = str(progress.get("stage") or "gopay_auto_register_progress")
    message = str(progress.get("message") or stage)
    return {
        **progress,
        "stage": stage,
        "current": current,
        "total": total,
        "message": f"自动注册 ({current}/{total})：{message}",
    }


def gopay_auto_register_bind_wait_progress(
    *,
    email: str,
    current: int,
    total: int,
    delay_seconds: float,
) -> dict[str, Any]:
    rounded_delay = round(float(delay_seconds or 0.0), 1)
    return {
        "stage": "gopay_auto_register_bind_wait",
        "email": email,
        "current": current,
        "total": total,
        "delay_seconds": rounded_delay,
        "message": f"注册已成功，等待 {float(delay_seconds or 0.0):.1f}s 后开始 GoPay 绑定: {email}",
    }


def gopay_auto_register_failed_result(*, error: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "gopay_auto_register",
        "register_status": "failed",
        "bind_status": "not_started",
        "message": f"自动注册失败: {error}",
        "screenshot_paths": [],
    }


def gopay_auto_register_not_executed_result(*, cancelled: bool) -> dict[str, Any]:
    return {
        "status": "cancelled" if cancelled else "failed",
        "failure_stage": "cancelled" if cancelled else "gopay_auto_register",
        "message": "自动注册 GoPay 任务已取消" if cancelled else "自动注册 GoPay 未执行",
        "screenshot_paths": [],
        "auto_register_results": [],
        "successful_emails": [],
        "failed_emails": [],
    }


def gopay_auto_register_rate_limited_result(
    *,
    failed_email: str,
    fallback_email: str,
    current: int,
    total: int,
    message: Any,
    auto_register_results: list[dict[str, Any]],
    registered_emails: list[str],
    successful_emails: list[str],
    failed_emails: list[dict[str, Any]],
    bind_failed_emails: list[dict[str, Any]],
    pending_retry_emails: list[str],
    retried_emails: list[str],
    rejected_emails: list[str],
    payment_failed_emails: list[str],
    nonzero_blocked_emails: list[str],
    blocked_emails: list[str],
) -> dict[str, Any]:
    message_text = str(message)
    result: dict[str, Any] = {
        "status": "failed",
        "failure_stage": "gopay_wallet_rate_limited",
        "register_status": "success" if failed_email else "failed",
        "bind_status": "failed" if failed_email else "not_started",
        "message": message_text,
        "screenshot_paths": [],
        "auto_register_results": auto_register_results,
        "auto_register_count": total,
        "auto_register_attempted": current,
        "registered_emails": registered_emails,
        "successful_emails": successful_emails,
        "failed_emails": failed_emails
        + (
            [
                {
                    "email": failed_email,
                    "failure_stage": "gopay_wallet_rate_limited",
                    "message": message_text,
                    "register_status": "success",
                    "bind_status": "failed",
                }
            ]
            if failed_email
            else []
        ),
        "bind_failed_emails": bind_failed_emails
        + (
            [
                {
                    "email": failed_email,
                    "failure_stage": "gopay_wallet_rate_limited",
                    "message": message_text,
                }
            ]
            if failed_email
            else []
        ),
        "pending_retry_emails": pending_retry_emails,
        "retried_emails": retried_emails,
        "rejected_emails": rejected_emails,
        "payment_failed_emails": payment_failed_emails,
        "nonzero_blocked_emails": nonzero_blocked_emails,
        "blocked_emails": blocked_emails,
        "email_used": failed_email or fallback_email,
    }
    if failed_email:
        result["auto_register_results"] = auto_register_results + [
            {
                "status": "failed",
                "failure_stage": "gopay_wallet_rate_limited",
                "register_status": "success",
                "bind_status": "failed",
                "message": message_text,
                "screenshot_paths": [],
                "email_used": failed_email,
                "auto_register_index": current,
                "auto_register_total": total,
            }
        ]
    return result


def gopay_auto_register_bind_failure_result(*, error: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "post_submit",
        "register_status": "success",
        "bind_status": "failed",
        "message": f"注册已成功，GoPay 绑定异常: {error}",
        "screenshot_paths": [],
    }


def gopay_auto_signup_account_progress(*, email: str, current: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_auto_signup_account",
        "email": email,
        "attempt": current,
        "total": total,
        "message": f"正在为账号注册/复用 GoPay 钱包: {email} ({current}/{total})",
    }


def gopay_auto_signup_account_failed_progress(
    *,
    email: str,
    current: int,
    total: int,
    failure_stage: str,
    message: str,
    retry_round: int | None = None,
    max_retry_rounds: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "gopay_auto_signup_account_failed",
        "email": email,
        "attempt": current,
        "total": total,
        "failure_stage": failure_stage,
        "message": message or "GoPay 自动注册绑定失败",
        "level": "warn",
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    if max_retry_rounds is not None:
        payload["max_retry_rounds"] = max_retry_rounds
    return payload


def gopay_auto_signup_rate_limited_result(
    *,
    email: str,
    current: int,
    total: int,
    message: Any,
    auto_signup_account_results: list[dict[str, Any]],
    attempted_emails: list[str],
    successful_emails: list[str],
    rejected_emails: list[str],
    payment_failed_emails: list[str],
    nonzero_blocked_emails: list[str],
    blocked_emails: list[str],
    failed_emails: list[dict[str, Any]],
) -> dict[str, Any]:
    message_text = str(message)
    failure_record = {
        "status": "failed",
        "failure_stage": "gopay_wallet_rate_limited",
        "message": message_text,
        "screenshot_paths": [],
        "email_used": email,
        "auto_signup_account_index": current,
        "auto_signup_account_total": total,
    }
    return {
        "status": "failed",
        "failure_stage": "gopay_wallet_rate_limited",
        "message": message_text,
        "screenshot_paths": [],
        "auto_signup_account_results": auto_signup_account_results + [failure_record],
        "attempted_emails": attempted_emails,
        "successful_emails": successful_emails,
        "rejected_emails": rejected_emails,
        "payment_failed_emails": payment_failed_emails,
        "nonzero_blocked_emails": nonzero_blocked_emails,
        "blocked_emails": blocked_emails,
        "failed_emails": failed_emails
        + [
            {
                "email": email,
                "failure_stage": "gopay_wallet_rate_limited",
                "message": message_text,
            }
        ],
    }


def gopay_auto_signup_not_executed_result(
    *,
    cancelled: bool,
    attempted_emails: list[str],
    failed_emails: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "cancelled" if cancelled else "failed",
        "failure_stage": "cancelled" if cancelled else "gopay_auto_signup",
        "message": "GoPay 自动注册绑定任务已取消" if cancelled else "GoPay 自动注册绑定未执行",
        "screenshot_paths": [],
        "auto_signup_account_results": [],
        "attempted_emails": attempted_emails,
        "successful_emails": [],
        "failed_emails": failed_emails,
    }


def gopay_parallel_started_progress(*, total: int, concurrency: int) -> dict[str, Any]:
    return {
        "stage": "gopay_parallel_started",
        "total": total,
        "concurrency": concurrency,
        "message": f"开始并发 GoPay 自动钱包绑定：{total} 个账号，并发 {concurrency}",
    }


def gopay_parallel_account_progress(
    *,
    email: str,
    current: int,
    total: int,
    retry_round: int,
    max_retry_rounds: int,
    worker_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "gopay_parallel_account",
        "email": email,
        "attempt": current,
        "total": total,
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "message": (
            f"并发处理 GoPay 待重试第 {retry_round}/{max_retry_rounds} 轮: {email} ({current}/{total})"
            if retry_round
            else f"并发处理 GoPay 账号: {email} ({current}/{total})"
        ),
        **(worker_fields or {}),
    }


def gopay_runtime_accounts_added_progress(
    *,
    added: int,
    added_emails: list[str],
    pending: int,
    total: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_runtime_accounts_added",
        "added": added,
        "added_emails": added_emails[:],
        "pending": pending,
        "total": total,
        "message": f"已追加 {added} 个 GoPay 待处理账号，后续空闲并发会继续处理",
        "level": "success",
    }


def gopay_parallel_cancelled_progress(*, active: int, pending: int) -> dict[str, Any]:
    return {
        "stage": "gopay_parallel_cancelled",
        "active": active,
        "pending": pending,
        "message": "GoPay 并发任务已停止提交新账号，正在释放未开始的后台步骤",
    }


def gopay_success_progress_fields(successful_emails: list[str]) -> dict[str, Any]:
    return {
        "successful": len(successful_emails),
        "successful_emails": successful_emails[:],
    }


def gopay_oauth_login_skipped_progress(*, success_email: str, successful_emails: list[str]) -> dict[str, Any]:
    return {
        "stage": "gopay_oauth_login_skipped",
        "email": success_email,
        **gopay_success_progress_fields(successful_emails),
        "message": f"GoPay 绑定成功；未启用 OAuth 补登录，已跳过 CPA 直接转换: {success_email}",
        "level": "success",
    }


def gopay_oauth_login_started_progress(*, success_email: str) -> dict[str, Any]:
    return {
        "stage": "gopay_oauth_login_started",
        "email": success_email,
        "message": f"GoPay 绑定成功，已在后台开始 OAuth 补登录: {success_email}",
    }


def gopay_oauth_proxy_selected_progress(*, success_email: str, proxy_label: str) -> dict[str, Any]:
    return {
        "stage": "gopay_oauth_proxy_selected",
        "email": success_email,
        "proxy_label": proxy_label,
        "message": "GoPay 绑定成功后的 OAuth 补登录将复用当前代理",
    }


def gopay_oauth_login_done_progress(
    *,
    success_email: str,
    auth_file: str,
    attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_oauth_login_done",
        "email": success_email,
        "auth_file": auth_file,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"OAuth 补登录成功: {success_email}",
    }


def gopay_oauth_phone_required_progress(
    *,
    success_email: str,
    removed_pool_emails: list[str],
    attempt: int,
    max_attempts: int,
    successful_emails: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_oauth_phone_required",
        "email": success_email,
        "removed_pool_emails": removed_pool_emails,
        "attempt": attempt,
        "max_attempts": max_attempts,
        **gopay_success_progress_fields(successful_emails),
        "message": message,
        "level": "warn",
    }


def gopay_oauth_phone_required_failure_record(
    *,
    success_email: str,
    error: Any,
    removed_pool_emails: list[str],
) -> dict[str, Any]:
    return {
        "email": success_email,
        "error": str(error),
        "failure_stage": "oauth_phone_required",
        "removed_pool_emails": removed_pool_emails[:],
    }


def gopay_oauth_login_retrying_progress(
    *,
    success_email: str,
    attempt: int,
    max_attempts: int,
    error: Any,
) -> dict[str, Any]:
    return {
        "stage": "gopay_oauth_login_retrying",
        "email": success_email,
        "attempt": attempt,
        "next_attempt": attempt + 1,
        "max_attempts": max_attempts,
        "message": f"OAuth 补登录失败，准备重试 {attempt + 1}/{max_attempts}: {success_email}: {error}",
        "level": "warn",
    }


def gopay_oauth_login_failed_progress(
    *,
    success_email: str,
    attempt: int,
    max_attempts: int,
    error: Any,
) -> dict[str, Any]:
    return {
        "stage": "gopay_oauth_login_failed",
        "email": success_email,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"OAuth 补登录失败: {success_email}: {error}",
    }


def gopay_oauth_failed_record(
    *,
    success_email: str,
    error: Any,
    attempts: int,
) -> dict[str, Any]:
    return {"email": success_email, "error": str(error), "attempts": attempts}


def gopay_oauth_thread_name(success_email: str) -> str:
    return f"gopay-oauth-{success_email[:24]}"
