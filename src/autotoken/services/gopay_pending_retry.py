"""GoPay pending-retry queue item and progress payload helpers."""

from typing import Any

DEFAULT_PENDING_RETRY_BACKOFFS = (60.0, 180.0, 300.0)
DEFAULT_TASK_PENDING_RETRY_BACKOFFS = (60.0, 120.0)


def normalize_pending_retry_attempts(value: Any, *, default: int = 1, maximum: int = 3) -> int:
    try:
        attempts = int(default if value is None else value)
    except Exception:
        attempts = default
    return max(0, min(maximum, attempts))


def pending_retry_wait_seconds(
    retry_round: int,
    backoffs: list[float] | tuple[float, ...] = DEFAULT_PENDING_RETRY_BACKOFFS,
) -> float:
    if not backoffs:
        return 0.0
    try:
        index = max(1, int(retry_round or 1)) - 1
    except Exception:
        index = 0
    return float(backoffs[min(index, len(backoffs) - 1)])


def pending_retry_item(
    *,
    email: str,
    index: int,
    reason: str,
    phone_accounts: list[dict[str, Any]] | None = None,
    retry_round: int | None = None,
    source_stage: str = "",
    failure_stage: str = "",
    message: str = "",
    wallet: Any = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "email": email,
        "index": index,
        "reason": reason,
    }
    if phone_accounts is not None:
        item["phone_accounts"] = phone_accounts
    if retry_round is not None:
        item["retry_round"] = retry_round
    if source_stage:
        item["source_stage"] = source_stage
    if failure_stage:
        item["failure_stage"] = failure_stage
    if message:
        item["message"] = message
    if wallet is not None:
        item["wallet"] = wallet
    return item


def pending_retry_queued_progress(
    *,
    email: str,
    retry_round: int,
    source_retry_round: int,
    max_retry_rounds: int,
    pending_retry: int,
    reason: str,
    message: str,
    current: int | None = None,
    total: int | None = None,
    source_stage: str = "",
    failure_stage: str = "",
    reuse_wallet: bool | None = None,
    detail: str = "",
    level: str = "warn",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "gopay_pending_retry_queued",
        "email": email,
        "retry_round": retry_round,
        "source_retry_round": source_retry_round,
        "max_retry_rounds": max_retry_rounds,
        "reason": reason,
        "pending_retry": pending_retry,
        "message": message,
        "level": level,
    }
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if source_stage:
        payload["source_stage"] = source_stage
    if failure_stage:
        payload["failure_stage"] = failure_stage
    if reuse_wallet is not None:
        payload["reuse_wallet"] = reuse_wallet
    if detail:
        payload["detail"] = detail
    return payload


def auto_register_pending_retry_queued_progress(
    *,
    email: str,
    current: int,
    total: int,
    retry_round: int,
    source_retry_round: int,
    max_retry_rounds: int,
    reason: str,
    pending_retry: int,
    source_stage: str = "",
) -> dict[str, Any]:
    next_round = source_retry_round > 0
    return pending_retry_queued_progress(
        email=email,
        current=current,
        total=total,
        retry_round=retry_round,
        source_retry_round=source_retry_round,
        max_retry_rounds=max_retry_rounds,
        reason=reason,
        pending_retry=pending_retry,
        source_stage=source_stage,
        message=(
            f"自动注册账号继续加入下一轮待重试: {email}"
            if next_round
            else f"自动注册账号加入待重试: {email}"
        ),
    )


def pending_retry_wait_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    delay_seconds: float,
    pending_retry: int,
    message: str = "",
    email: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "gopay_pending_retry_wait",
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "pending_retry": pending_retry,
        "delay_seconds": delay_seconds,
        "message": message
        or f"待重试第 {retry_round}/{max_retry_rounds} 轮将在 {delay_seconds:.0f}s 后开始",
    }
    if email:
        payload["email"] = email
    return payload


def pending_retry_started_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    pending_retry: int,
    message: str = "",
    concurrency: int | None = None,
    email: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "gopay_pending_retry_started",
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "pending_retry": pending_retry,
        "message": message or f"开始第 {retry_round}/{max_retry_rounds} 轮待重试，共 {pending_retry} 个账号",
    }
    if email:
        payload["email"] = email
    if concurrency is not None:
        payload["concurrency"] = concurrency
    return payload


def pending_retry_account_progress(
    *,
    email: str,
    retry_round: int,
    max_retry_rounds: int,
    message: str = "",
    attempt: int | None = None,
    total: int | None = None,
    current: int | None = None,
    auto_register_total: int | None = None,
    pending_retry: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "gopay_pending_retry_account",
        "email": email,
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "message": message or f"正在执行第 {retry_round}/{max_retry_rounds} 轮待重试: {email}",
    }
    if attempt is not None:
        payload["attempt"] = attempt
    if total is not None:
        payload["total"] = total
    if current is not None:
        payload["current"] = current
    if auto_register_total is not None:
        payload["auto_register_total"] = auto_register_total
    if pending_retry is not None:
        payload["pending_retry"] = pending_retry
    return payload


def auto_register_pending_retry_wait_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    delay_seconds: float,
    pending_retry: int,
) -> dict[str, Any]:
    return pending_retry_wait_progress(
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        delay_seconds=delay_seconds,
        pending_retry=pending_retry,
        message=f"自动注册待重试第 {retry_round}/{max_retry_rounds} 轮将在 {delay_seconds:.0f}s 后开始",
    )


def auto_register_pending_retry_started_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    pending_retry: int,
) -> dict[str, Any]:
    return pending_retry_started_progress(
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        pending_retry=pending_retry,
        message=f"开始自动注册待重试第 {retry_round}/{max_retry_rounds} 轮，共 {pending_retry} 个账号",
    )


def auto_register_pending_retry_account_progress(
    *,
    email: str,
    attempt: int,
    total: int,
    current: int,
    auto_register_total: int,
    retry_round: int,
    max_retry_rounds: int,
    pending_retry: int,
) -> dict[str, Any]:
    return pending_retry_account_progress(
        email=email,
        attempt=attempt,
        total=total,
        current=current,
        auto_register_total=auto_register_total,
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        pending_retry=pending_retry,
        message=f"正在执行自动注册待重试第 {retry_round}/{max_retry_rounds} 轮: {email} ({attempt}/{total})",
    )


def auto_register_pending_retry_exception_result(error: Any) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_stage": "post_submit",
        "register_status": "success",
        "bind_status": "failed",
        "message": f"注册已成功，GoPay 待重试异常: {error}",
        "screenshot_paths": [],
    }


def auto_register_pending_retry_failed_progress(
    *,
    email: str,
    current: int,
    total: int,
    retry_round: int,
    max_retry_rounds: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    return pending_retry_failed_progress(
        email=email,
        current=current,
        total=total,
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        result=result,
        default_message="自动注册 GoPay 待重试失败",
    )


def parallel_pending_retry_wait_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    delay_seconds: float,
    pending_retry: int,
    email: str = "",
) -> dict[str, Any]:
    suffix = f": {email}" if email else ""
    return pending_retry_wait_progress(
        email=email,
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        delay_seconds=delay_seconds,
        pending_retry=pending_retry,
        message=f"GoPay 并发待重试第 {retry_round}/{max_retry_rounds} 轮将在 {delay_seconds:.0f}s 后开始{suffix}",
    )


def parallel_pending_retry_queued_progress(
    *,
    email: str,
    retry_round: int,
    source_retry_round: int,
    max_retry_rounds: int,
    reason: str,
    source_stage: str,
    failure_stage: str,
    reuse_wallet: bool,
    pending_retry: int,
    detail: str = "",
) -> dict[str, Any]:
    return pending_retry_queued_progress(
        email=email,
        retry_round=retry_round,
        source_retry_round=source_retry_round,
        max_retry_rounds=max_retry_rounds,
        reason=reason,
        source_stage=source_stage,
        failure_stage=failure_stage,
        reuse_wallet=reuse_wallet,
        pending_retry=pending_retry,
        detail=detail,
        message=f"GoPay 并发账号失败，已加入待重试池: {email}",
    )


def parallel_pending_retry_started_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    pending_retry: int,
    concurrency: int | None = None,
    email: str = "",
) -> dict[str, Any]:
    if email:
        message = f"开始并发 GoPay 待重试第 {retry_round}/{max_retry_rounds} 轮: {email}"
    elif concurrency is not None:
        message = (
            f"开始并发 GoPay 待重试第 {retry_round}/{max_retry_rounds} 轮，"
            f"共 {pending_retry} 个账号，并发 {concurrency}"
        )
    else:
        message = f"开始并发 GoPay 待重试第 {retry_round}/{max_retry_rounds} 轮，共 {pending_retry} 个账号"
    return pending_retry_started_progress(
        email=email,
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        pending_retry=pending_retry,
        concurrency=concurrency,
        message=message,
    )


def pending_retry_failed_progress(
    *,
    email: str,
    current: int | None = None,
    total: int | None = None,
    retry_round: int,
    max_retry_rounds: int,
    result: dict[str, Any],
    default_message: str,
    reason: str = "",
    include_register_bind_status: bool = True,
) -> dict[str, Any]:
    payload = {
        "stage": "gopay_pending_retry_failed",
        "email": email,
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "failure_stage": result.get("failure_stage") or "",
        "message": result.get("message") or default_message,
        "level": "error",
    }
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if reason:
        payload["reason"] = reason
    if include_register_bind_status:
        payload["register_status"] = result.get("register_status") or ""
        payload["bind_status"] = result.get("bind_status") or ""
    return payload
