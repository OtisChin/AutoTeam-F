"""PayPal task public payload, autofill payload, and outcome payload helpers."""

from typing import Any


def paypal_auto_login_enabled(*, manual_confirm: Any, paypal_password: Any) -> bool:
    return (not bool(manual_confirm)) and bool(str(paypal_password or "").strip())


PAYPAL_AUTO_STAGE_MESSAGES = {
    "paypal_session_ready": "已注入 ChatGPT 登录态，准备打开 checkout",
    "checkout_opened": "已打开 PayPal 相关支付页面",
    "paypal_autofill": "已自动填写账单/联系字段",
    "paypal_billing_fill_started": "正在自动填写 checkout 账单地址",
    "paypal_billing_fill_done": "checkout 账单地址已填写",
    "paypal_option_selected": "已切换到 PayPal 支付方式",
    "paypal_checkout_terms_ready": "checkout 条款已确认，准备提交",
    "paypal_submit_checkout": "正在提交 checkout 并跳转 PayPal",
    "paypal_wait_redirect": "已提交 checkout，等待跳转到 PayPal",
    "paypal_ssl_protocol_error_refresh": "PayPal SSL 连接错误，等待刷新重试",
    "paypal_ssl_protocol_error_retry_queued": "PayPal SSL 连接错误刷新后仍未恢复，加入待重试池",
    "paypal_authorize": "已进入 PayPal 页面，开始自动登录/授权",
    "paypal_login_email": "正在填写 PayPal 邮箱",
    "paypal_login_password": "正在填写 PayPal 密码",
    "paypal_create_account": "正在切换到 PayPal 注册流程",
    "paypal_signup_email": "正在填写 PayPal 注册邮箱",
    "paypal_wait_signup_form": "正在等待 PayPal 注册表单加载",
    "paypal_fill_signup": "正在填写 PayPal 注册表单",
    "paypal_submit_signup": "正在提交 PayPal 注册信息",
    "paypal_wait_signup_otp": "正在等待 PayPal 短信验证码",
    "paypal_otp_phone_lock_wait": "正在等待当前手机号验证码流程释放",
    "paypal_otp_phone_lock_acquired": "已锁定当前手机号验证码流程",
    "paypal_otp_phone_lock_released": "已释放当前手机号验证码流程",
    "paypal_otp_phone_lock_timeout": "等待当前手机号验证码流程释放超时",
    "paypal_wait_sms_otp_window": "等待短信平台下发 PayPal 验证码",
    "paypal_fetch_otp": "正在从接码接口拉取 PayPal 验证码",
    "paypal_sms_otp_resend_due": "长时间未收到 PayPal 验证码，尝试重新拉取/重发",
    "paypal_sms_provider_resend_triggered": "已通知接码平台继续接收 PayPal 验证码",
    "paypal_otp_resend_clicked": "60 秒未收到 PayPal 验证码，已点击 Resend",
    "paypal_otp_received": "已收到 PayPal 验证码",
    "paypal_submit_otp": "正在提交 PayPal 短信验证码",
    "paypal_phone_rejected_waiting_dismiss": "PayPal 拒绝当前手机号，正在关闭提示弹窗",
    "paypal_phone_rejected_rotate": "PayPal 拒绝当前手机号，切换下一个手机号重试",
    "paypal_phone_rejected_final": "PayPal 拒绝当前手机号，已标记为不可用",
    "paypal_replace_signup_phone": "PayPal 拒绝当前手机号，正在替换手机号字段",
    "paypal_card_rejected_retry": "PayPal 拒绝当前卡片，正在只替换卡片信息重试",
    "paypal_prompt_dismissed": "已关闭 PayPal 通行密钥/提示弹窗",
    "paypal_approve_clicked": "已点击 PayPal 同意并继续",
    "paypal_wait_result": "PayPal 已授权，等待商户页面确认结果",
    "paypal_wait_manual": "等待人工完成 PayPal 支付流程",
    "paypal_protocol_start": "协议模式：开始处理 PayPal checkout",
    "paypal_protocol_proxy_http_fallback": "SOCKS 代理握手失败，协议模式改用 HTTP 代理重试",
    "paypal_protocol_init": "协议模式：已初始化 Stripe checkout",
    "paypal_protocol_payment_method": "协议模式：已创建 PayPal payment_method",
    "paypal_protocol_confirm": "协议模式：已确认 Stripe checkout",
    "paypal_protocol_approve_url": "协议模式：已解析 PayPal 授权链接",
    "paypal_protocol_wait_result": "协议模式：等待 Stripe checkout 结果",
    "paypal_protocol_browser_fallback": "协议模式被 PayPal 风控拦截，正在降级到浏览器模式",
    "paypal_browser_fallback_navigate": "浏览器已打开 PayPal 授权页面",
    "paypal_browser_fallback_ddc_wait": "正在等待 DataDome 安全检查通过",
    "paypal_ddc_slider_detected": "检测到 DataDome 滑块验证，正在自动解题",
    "paypal_ddc_invisible_wait": "检测到 DataDome 隐形验证，等待自动通过",
    "paypal_ddc_blocked_retry": "检测到 DataDome 封锁页面，正在刷新重试",
    "paypal_ddc_blocked_final": "DataDome 封锁页面重试后仍未通过",
    "paypal_signup_email_reload": "邮箱提交后页面卡住，正在恢复重试",
    "paypal_agree_create_clicked": "已点击 PayPal 同意并创建账户",
    "paypal_return_wait": "等待订阅回跳确认",
    "paypal_return_confirmed": "订阅已回跳 ChatGPT/OpenAI 页面，绑定成功",
}


def paypal_progress_event(stage: str, message: str = "", **kwargs) -> dict[str, Any]:
    payload = {
        "stage": stage,
        "message": message or PAYPAL_AUTO_STAGE_MESSAGES.get(stage) or stage,
    }
    payload.update(kwargs)
    return payload


def build_paypal_task_payload(
    *,
    params: Any,
    email: str,
    account_emails: list[str],
    checkout_url: str,
    bind_link_payload: dict[str, Any] | None,
    proxy_pool_count: int,
    proxy_api_url: str,
    proxy_api_provider: str,
    roxybrowser_workspace_id: str,
    roxybrowser_profile_id: str,
    roxybrowser_auto_create_profile: bool,
    paypal_browser: str,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_region: str,
    paypal_fallback_browser: str,
    sms_url: str,
    otp_channel: str,
    phone_account_count: int,
    pending_retry_attempts: int,
    paypal_concurrency: int,
    direct_ba_pre_extracted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runner_mode": "manual_checkout",
        "email": email,
        "account_emails": account_emails,
        "checkout_url": checkout_url,
        "bind_link_payload": bind_link_payload,
        "proxy_url": params.proxy_url,
        "proxy_pool_count": proxy_pool_count,
        "proxy_api_url_present": bool(proxy_api_url),
        "proxy_label": params.proxy_label,
        "proxy_bypass": params.proxy_bypass,
        "roxybrowser_workspace_id": roxybrowser_workspace_id,
        "roxybrowser_profile_id": roxybrowser_profile_id,
        "roxybrowser_auto_create_profile": roxybrowser_auto_create_profile,
        "manual_confirm": bool(params.manual_confirm),
        "paypal_browser": paypal_browser,
        "paypal_mode": paypal_mode,
        "paypal_country": paypal_country,
        "paypal_lang": paypal_lang,
        "paypal_email": params.paypal_email,
        "sms_url_present": bool(sms_url),
        "otp_channel": otp_channel,
        "phone_account_count": phone_account_count,
        "paypal_direct_ba_link_present": bool(direct_ba_pre_extracted),
        "paypal_direct_ba_checkout_reference_present": bool(
            direct_ba_pre_extracted
            and (
                direct_ba_pre_extracted.get("checkout_session_id")
                or direct_ba_pre_extracted.get("checkout_url")
                or direct_ba_pre_extracted.get("hosted_checkout_url")
            )
        ),
        "paypal_card_number_present": bool(str(params.paypal_card_number or "").strip()),
        "paypal_card_expiry_present": bool(str(params.paypal_card_expiry or "").strip()),
        "paypal_card_cvv_present": bool(str(params.paypal_card_cvv or "").strip()),
        "paypal_auto_login": paypal_auto_login_enabled(
            manual_confirm=params.manual_confirm,
            paypal_password=params.paypal_password,
        ),
        "autofill_enabled": bool(params.autofill_enabled),
        "billing_name": params.billing_name,
        "billing_email": params.billing_email,
        "billing_phone": params.billing_phone,
        "billing_country": params.billing_country,
        "billing_state": params.billing_state,
        "billing_city": params.billing_city,
        "billing_zip": params.billing_zip,
        "billing_address1": params.billing_address1,
        "billing_address2": params.billing_address2,
        "timeout_seconds": int(params.timeout_seconds or 60),
        "auto_oauth_after_success": bool(params.auto_oauth_after_success),
        "pending_retry_attempts": pending_retry_attempts,
        "paypal_concurrency": paypal_concurrency,
    }
    if paypal_region:
        payload["paypal_region"] = paypal_region
    if paypal_fallback_browser:
        payload["paypal_fallback_browser"] = paypal_fallback_browser
    if proxy_api_provider:
        payload["proxy_api_provider"] = proxy_api_provider
    return payload


def build_paypal_autofill_payload(*, params: Any, email: str) -> dict[str, Any]:
    return {
        "name": params.billing_name,
        "email": params.billing_email or email,
        "phone": params.billing_phone,
        "country": params.billing_country,
        "state": params.billing_state,
        "city": params.billing_city,
        "zip": params.billing_zip,
        "address1": params.billing_address1,
        "address2": params.billing_address2,
        "card_number": params.paypal_card_number,
        "card_expiry": params.paypal_card_expiry,
        "card_cvv": params.paypal_card_cvv,
    }


def paypal_candidate_autofill_payload(
    base_payload: dict[str, Any],
    *,
    candidate_email: str,
    billing_email: str,
) -> dict[str, Any]:
    payload = dict(base_payload)
    payload["email"] = billing_email or candidate_email
    return payload


def paypal_proxy_api_failed_candidate_result(
    *,
    email: str,
    current: int,
    retry_round: int,
    error: Any,
) -> dict[str, Any]:
    return {
        "email": email,
        "index": current,
        "retry_round": retry_round,
        "selected_proxy_url": "",
        "current_candidate_phone": "",
        "result": paypal_proxy_api_failed_result(email=email, error=error),
    }


def paypal_proxy_api_failed_result(*, email: str, error: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "proxy_api",
        "message": f"动态代理 API 获取失败: {error}",
        "screenshot_paths": [],
        "email": email,
    }


def paypal_starting_progress(
    *,
    email: str,
    current: int,
    total: int,
    proxy_label: str,
    retry_round: int | None = None,
    concurrency: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "paypal_starting",
        "email": email,
        "current": current,
        "total": total,
        "proxy_label": proxy_label,
        "message": total > 1 and f"PayPal 批量任务启动中 ({current}/{total}): {email}" or "PayPal 任务启动中",
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    if concurrency is not None:
        payload["concurrency"] = concurrency
    return payload


def paypal_missing_checkout_access_token_result(*, email: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "generate_checkout",
        "message": f"账号缺少可用 access_token，无法自动生成 checkout 链接: {email}",
        "screenshot_paths": [],
        "email": email,
    }


def paypal_checkout_failed_result(*, email: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "generate_checkout",
        "message": message,
        "screenshot_paths": [],
        "email": email,
    }


def paypal_candidate_exception_result(*, email: str, error: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": f"PayPal 账号执行异常: {error}",
        "screenshot_paths": [],
        "email": email,
    }


def paypal_checkout_token_refreshed_progress(*, email: str, current: int, total: int) -> dict[str, Any]:
    return {
        "stage": "paypal_checkout_token_refreshed",
        "email": email,
        "current": current,
        "total": total,
        "message": f"生成 checkout 返回 401，已刷新 access_token 并重试: {email}",
    }


def paypal_checkout_browser_fallback_progress(
    *,
    email: str,
    current: int,
    total: int,
    retry_round: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "paypal_checkout_browser_fallback",
        "email": email,
        "current": current,
        "total": total,
        "message": f"HTTP 生成 checkout 失败，改用浏览器登录态回退: {email}",
        "level": "warn",
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    return payload


def paypal_checkout_generated_progress(
    *,
    email: str,
    current: int,
    total: int,
    checkout_url: str,
    retry_round: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "paypal_checkout_generated",
        "email": email,
        "current": current,
        "total": total,
        "checkout_url": checkout_url,
        "message": f"已生成 checkout 链接 ({current}/{total}): {email}",
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    return payload


def paypal_checkout_browser_generated_progress(*, email: str, current: int, total: int) -> dict[str, Any]:
    return {
        "stage": "paypal_checkout_browser_generated",
        "email": email,
        "current": current,
        "total": total,
        "message": f"浏览器登录态已生成 checkout 链接 ({current}/{total}): {email}",
    }


def paypal_phone_pool_exhausted_progress(
    *,
    email: str,
    current: int,
    total: int,
    message: str,
    level: str,
    retry_round: int | None = None,
    reserved_phone_count: int | None = None,
    invalid_phone_count: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "paypal_phone_pool_exhausted",
        "email": email,
        "current": current,
        "total": total,
        "message": message,
        "level": level,
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    if reserved_phone_count is not None:
        payload["reserved_phone_count"] = reserved_phone_count
    if invalid_phone_count is not None:
        payload["invalid_phone_count"] = invalid_phone_count
    return payload


def paypal_phone_pool_exhausted_result(*, email: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "paypal_phone_pool_exhausted",
        "message": message,
        "screenshot_paths": [],
        "email": email,
    }


def paypal_parallel_started_progress(*, total: int, concurrency: int) -> dict[str, Any]:
    return {
        "stage": "paypal_parallel_started",
        "total": total,
        "concurrency": concurrency,
        "message": f"开始并发 PayPal 绑定：{total} 个账号，并发 {concurrency}",
    }


def paypal_pending_retry_account_progress(
    *,
    email: str,
    current: int,
    total: int,
    retry_round: int,
    max_retry_rounds: int,
    pending_retry: int,
    concurrency: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "paypal_pending_retry_account",
        "email": email,
        "current": current,
        "total": total,
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "pending_retry": pending_retry,
        "message": f"正在执行 PayPal 待重试第 {retry_round}/{max_retry_rounds} 轮: {email}",
    }
    if concurrency is not None:
        payload["concurrency"] = concurrency
        payload["message"] = f"正在并发执行 PayPal 待重试第 {retry_round}/{max_retry_rounds} 轮: {email}"
    return payload


def paypal_task_exception_result(*, error: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": f"PayPal 任务执行异常: {error}",
        "screenshot_paths": [],
    }


def paypal_success_account_update_fields() -> dict[str, Any]:
    return {
        "status": "active",
        "account_type": "plus",
        "seat_type": "codex",
        "account_source": "managed",
        "last_bind_provider": "paypal",
    }


def normalize_paypal_candidate_result(
    *,
    single_result: dict[str, Any] | None,
    candidate_email: str,
    effective_checkout_url: str,
) -> dict[str, Any]:
    payload = dict(single_result or {})
    payload["email"] = candidate_email
    payload["checkout_url"] = effective_checkout_url or payload.get("checkout_url") or ""
    return payload


def paypal_candidate_phone_rejection_update(
    *,
    single_result: dict[str, Any],
    current_candidate_phone: Any,
    invalid_phone_pool: list[str],
) -> tuple[Any, dict[str, Any]]:
    if single_result.get("failure_stage") != "paypal_phone_rejected":
        return None, single_result
    payload = dict(single_result)
    payload["invalid_phone_numbers"] = invalid_phone_pool[:]
    return payload.get("rejected_phone") or current_candidate_phone, payload


def paypal_candidate_outcome_flags(
    *,
    single_result: dict[str, Any],
    candidate_email: str,
    nonzero_blocked_pool_emails: list[str],
) -> dict[str, bool]:
    is_success = single_result.get("status") == "success"
    return {
        "success": is_success,
        "failed": not is_success,
        "nonzero_blocked": (not is_success) and candidate_email in nonzero_blocked_pool_emails,
    }


def paypal_success_persistence_warning_needed(*, single_result: dict[str, Any], updated_account: Any) -> bool:
    return single_result.get("status") == "success" and not updated_account


def paypal_success_plan_update_request(
    *,
    candidate_email: str,
    updated_account: Any,
    plan_type: str = "plus",
) -> dict[str, Any]:
    return {
        "email": candidate_email,
        "account": updated_account if isinstance(updated_account, dict) else None,
        "plan_type": plan_type,
    }


def apply_paypal_success_plan_update(*, updated_account: Any, plan_update: dict[str, Any]) -> Any:
    if isinstance(updated_account, dict) and plan_update.get("auth_file"):
        updated_account["auth_file"] = plan_update["auth_file"]
    return updated_account


def paypal_success_progress_fields(successful_emails: list[str]) -> dict[str, Any]:
    return {
        "successful": len(successful_emails),
        "successful_emails": successful_emails[:],
    }


def paypal_oauth_login_skipped_progress(*, success_email: str, successful_emails: list[str]) -> dict[str, Any]:
    return {
        "stage": "paypal_oauth_login_skipped",
        "email": success_email,
        **paypal_success_progress_fields(successful_emails),
        "message": f"PayPal 绑定成功；未启用 OAuth 补登录，已跳过 CPA 直接转换: {success_email}",
        "level": "success",
    }


def paypal_oauth_login_started_progress(*, success_email: str, successful_emails: list[str]) -> dict[str, Any]:
    return {
        "stage": "paypal_oauth_login_started",
        "email": success_email,
        **paypal_success_progress_fields(successful_emails),
        "message": f"PayPal 绑定成功，已在后台开始 OAuth 补登录: {success_email}",
    }


def paypal_oauth_proxy_selected_progress(
    *,
    success_email: str,
    proxy_label: str,
    proxy_api_provider: str,
) -> dict[str, Any]:
    return {
        "stage": "paypal_oauth_proxy_selected",
        "email": success_email,
        "proxy_label": proxy_label,
        "proxy_api_provider": proxy_api_provider,
        "message": "PayPal 绑定成功后的 OAuth 补登录将复用当前代理",
    }


def paypal_oauth_login_done_progress(
    *,
    success_email: str,
    auth_file: str,
    attempt: int,
    max_attempts: int,
    successful_emails: list[str],
) -> dict[str, Any]:
    return {
        "stage": "paypal_oauth_login_done",
        "email": success_email,
        "auth_file": auth_file,
        "attempt": attempt,
        "max_attempts": max_attempts,
        **paypal_success_progress_fields(successful_emails),
        "message": f"OAuth 补登录成功: {success_email}",
        "level": "success",
    }


def paypal_oauth_phone_required_progress(
    *,
    success_email: str,
    removed_pool_emails: list[str],
    attempt: int,
    max_attempts: int,
    successful_emails: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "stage": "paypal_oauth_phone_required",
        "email": success_email,
        "removed_pool_emails": removed_pool_emails,
        "attempt": attempt,
        "max_attempts": max_attempts,
        **paypal_success_progress_fields(successful_emails),
        "message": message,
        "level": "warn",
    }


def paypal_oauth_phone_required_failure_record(
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


def paypal_oauth_login_retrying_progress(
    *,
    success_email: str,
    attempt: int,
    max_attempts: int,
    successful_emails: list[str],
    error: Any,
) -> dict[str, Any]:
    return {
        "stage": "paypal_oauth_login_retrying",
        "email": success_email,
        "attempt": attempt,
        "next_attempt": attempt + 1,
        "max_attempts": max_attempts,
        **paypal_success_progress_fields(successful_emails),
        "message": f"OAuth 补登录失败，准备重试 {attempt + 1}/{max_attempts}: {success_email}: {error}",
        "level": "warn",
    }


def paypal_oauth_login_failed_progress(
    *,
    success_email: str,
    attempt: int,
    max_attempts: int,
    successful_emails: list[str],
    error: Any,
) -> dict[str, Any]:
    return {
        "stage": "paypal_oauth_login_failed",
        "email": success_email,
        "attempt": attempt,
        "max_attempts": max_attempts,
        **paypal_success_progress_fields(successful_emails),
        "message": f"OAuth 补登录失败: {success_email}: {error}",
        "level": "error",
    }


def paypal_oauth_failed_record(
    *,
    success_email: str,
    error: Any,
    attempts: int,
) -> dict[str, Any]:
    return {"email": success_email, "error": str(error), "attempts": attempts}


def paypal_oauth_thread_name(success_email: str) -> str:
    return f"paypal-oauth-{success_email[:24]}"


def paypal_bind_update_fields(
    *,
    single_result: dict[str, Any],
    is_cancelled: bool,
    proxy_label: str,
    task_id: str,
    bind_at: float,
    success_account_fields: dict[str, Any],
) -> dict[str, Any]:
    status = single_result.get("status")
    fields: dict[str, Any] = {
        "last_bind_status": "cancelled" if is_cancelled and status != "success" else status or "failed",
        "last_bind_at": bind_at,
        "last_checkout_url": single_result.get("checkout_url") or "",
        "last_proxy_label": proxy_label,
        "last_bind_task_id": task_id,
        "last_bind_message": single_result.get("message") or "",
        "last_bind_failure_stage": single_result.get("failure_stage") or "",
    }
    if status == "success":
        fields.update(success_account_fields)
        fields["plus_bound_at"] = fields["last_bind_at"]
    return fields


def paypal_bind_audit_record(
    *,
    task_id: str,
    candidate_email: str,
    single_result: dict[str, Any],
    proxy_label: str,
    selected_proxy_url: str,
    manual_confirm: Any,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_password: Any,
    autofill_enabled: Any,
    started_at: float,
    finished_at: float,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "email": candidate_email,
        "checkout_url": single_result.get("checkout_url") or "",
        "proxy_label": proxy_label,
        "proxy_url": selected_proxy_url or "",
        "manual_confirm": bool(manual_confirm),
        "paypal_mode": paypal_mode,
        "paypal_country": paypal_country,
        "paypal_lang": paypal_lang,
        "paypal_auto_login": paypal_auto_login_enabled(
            manual_confirm=manual_confirm,
            paypal_password=paypal_password,
        ),
        "autofill_enabled": bool(autofill_enabled),
        "status": single_result.get("status") or "failed",
        "task_status": "completed" if single_result.get("status") == "success" else "failed",
        "failure_stage": single_result.get("failure_stage") or "",
        "message": single_result.get("message") or "",
        "started_at": started_at,
        "finished_at": finished_at,
        "screenshot_paths": single_result.get("screenshot_paths") or [],
        "flow": f"paypal_{paypal_mode}",
        "category": "paypal",
        "provider": "paypal",
    }


def paypal_nonzero_amount_blocked_progress(
    *,
    candidate_email: str,
    current: int,
    total: int,
) -> dict[str, Any]:
    return {
        "stage": "paypal_nonzero_amount_blocked_rotate",
        "email": candidate_email,
        "current": current,
        "total": total,
        "message": f"今日应付非 0，已删除并跳过账号: {candidate_email}",
        "level": "warn",
    }


def paypal_nonzero_amount_blocked_cleanup_request(
    *,
    candidate_email: str,
    current: int,
    total: int,
) -> dict[str, Any]:
    return {
        "emails": [candidate_email],
        "log_context": "paypal-nonzero",
        "reason": "paypal_nonzero_amount_blocked",
        "message": "PayPal checkout 今日应付金额非 0，账号已从本地号池删除",
        "progress": paypal_nonzero_amount_blocked_progress(
            candidate_email=candidate_email,
            current=current,
            total=total,
        ),
    }


def finalize_paypal_task_result(
    *,
    result: dict[str, Any] | None,
    email: str,
    checkout_url: str,
    last_checkout_url: str,
    proxy_label: str,
    manual_confirm: Any,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_password: Any,
    autofill_enabled: Any,
    effective_concurrency: int,
    candidates: list[str],
    successful_emails: list[str],
    failed_emails: list[str],
    pending_retry_emails: list[str],
    retried_emails: list[str],
    nonzero_blocked_emails: list[str],
    removed_pool_emails: list[str],
    invalid_phone_pool: list[str],
    oauth_scheduled_emails: set[str],
    oauth_successful_emails: list[str],
    oauth_failed_emails: list[dict[str, Any]],
    session_cpa_converted_emails: list[str],
    session_cpa_failed_auths: list[dict[str, Any]],
    is_cancelled: bool,
) -> tuple[dict[str, Any], str]:
    payload = dict(result or {})
    payload.setdefault("status", "failed")
    payload.setdefault("failure_stage", "")
    payload.setdefault("message", "")
    payload.setdefault("screenshot_paths", [])
    payload["email"] = payload.get("email") or email
    payload["checkout_url"] = payload.get("checkout_url") or last_checkout_url or checkout_url
    payload["proxy_label"] = proxy_label
    payload["manual_confirm"] = bool(manual_confirm)
    payload["paypal_mode"] = paypal_mode
    payload["paypal_country"] = paypal_country
    payload["paypal_lang"] = paypal_lang
    payload["paypal_auto_login"] = paypal_auto_login_enabled(
        manual_confirm=manual_confirm,
        paypal_password=paypal_password,
    )
    payload["autofill_enabled"] = bool(autofill_enabled)
    payload["provider"] = "paypal"
    payload["concurrency"] = effective_concurrency
    payload["account_emails"] = candidates
    payload["successful_emails"] = successful_emails
    payload["failed_emails"] = failed_emails
    if pending_retry_emails:
        payload["pending_retry_emails"] = pending_retry_emails[:]
    if retried_emails:
        payload["retried_emails"] = retried_emails[:]
    payload["nonzero_blocked_emails"] = nonzero_blocked_emails
    payload["removed_pool_emails"] = removed_pool_emails
    if invalid_phone_pool:
        payload["invalid_phone_numbers"] = invalid_phone_pool[:]
    if oauth_scheduled_emails:
        payload["oauth_scheduled_emails"] = sorted(oauth_scheduled_emails)
    if oauth_successful_emails:
        payload["oauth_successful_emails"] = oauth_successful_emails[:]
    if oauth_failed_emails:
        payload["oauth_failed_emails"] = oauth_failed_emails[:]
    if session_cpa_converted_emails:
        payload["session_cpa_converted_emails"] = session_cpa_converted_emails[:]
    if session_cpa_failed_auths:
        payload["session_cpa_failed_auths"] = session_cpa_failed_auths[:]
    if len(candidates) > 1:
        if successful_emails:
            payload["status"] = "success"
            payload["failure_stage"] = ""
            payload["message"] = f"PayPal 批量绑定完成: 成功 {len(successful_emails)}/{len(candidates)} 个账号"
        elif nonzero_blocked_emails and len(nonzero_blocked_emails) == len(candidates):
            payload["status"] = "failed"
            payload["failure_stage"] = "browser_charge_guard"
            payload["message"] = f"PayPal 批量绑定失败: {len(candidates)} 个账号今日应付均非 0"
        else:
            payload["status"] = "failed"
            payload["message"] = payload.get("message") or f"PayPal 批量绑定失败: 尝试 {len(candidates)} 个账号均未成功"

    if is_cancelled and payload.get("status") != "success":
        task_status = "cancelled"
    elif payload.get("status") == "success":
        task_status = "completed"
    else:
        task_status = "failed"
    payload["task_status"] = task_status
    return payload, task_status


def paypal_completion_progress(
    *,
    result: dict[str, Any],
    task_status: str,
    successful_count: int,
    failed_count: int,
    total_count: int,
) -> dict[str, Any]:
    return {
        "stage": "paypal_completed" if result.get("status") == "success" else "paypal_finished",
        "bind_status": result.get("status") or "failed",
        "task_status": task_status,
        "successful": successful_count,
        "failed": failed_count,
        "total": total_count,
        "message": result.get("message") or "",
    }
