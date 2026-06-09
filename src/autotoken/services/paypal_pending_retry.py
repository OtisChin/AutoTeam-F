"""PayPal pending-retry queue helpers."""

from collections.abc import Callable
from typing import Any

from autotoken.core.normalization import normalized_email

DEFAULT_PENDING_RETRY_BACKOFFS = (60.0, 120.0)


def append_unique_email(target: list[str], value: Any, *, normalizer: Callable[[Any], str] = normalized_email) -> str:
    item = normalizer(value)
    if item and item not in target:
        target.append(item)
    return item


def remove_email(target: list[str], value: Any, *, normalizer: Callable[[Any], str] = normalized_email) -> str:
    item = normalizer(value)
    if not item:
        return ""
    target[:] = [current for current in target if normalizer(current) != item]
    return item


def remove_pending_retry(
    *,
    candidate_email: Any,
    pending_retry_emails: list[str],
    pending_retry_queue: list[dict[str, Any]],
    normalizer: Callable[[Any], str] = normalized_email,
) -> str:
    email = remove_email(pending_retry_emails, candidate_email, normalizer=normalizer)
    if email:
        pending_retry_queue[:] = [item for item in pending_retry_queue if normalizer(item.get("email")) != email]
    return email


def pending_retry_queued_progress(
    *,
    candidate_email: str,
    current_index: int,
    total_count: int,
    pending_retry_count: int | None,
    retry_round: int,
    max_retry_rounds: int,
    reason: str,
    result_payload: dict[str, Any] | None,
    source_stage: Callable[[dict[str, Any] | None, str], str],
    message: str = "",
    level: str | None = None,
    include_source_stage: bool = True,
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "stage": "paypal_pending_retry_queued",
        "email": candidate_email,
        "current": current_index,
        "total": total_count,
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "reason": reason,
        "message": message or f"PayPal 账号进入待重试池: {candidate_email}",
    }
    if include_source_stage:
        progress["source_stage"] = source_stage(result_payload, reason)
    if pending_retry_count is not None:
        progress["pending_retry"] = pending_retry_count
    if level:
        progress["level"] = level
    return progress


def queue_pending_retry(
    *,
    pending_retry_emails: list[str],
    pending_retry_queue: list[dict[str, Any]],
    candidate_queue: list[dict[str, Any]],
    candidate_email: Any,
    reason: str,
    result_payload: dict[str, Any],
    retry_round: int,
    current_index: int,
    total_count: int,
    max_retry_rounds: int,
    source_stage: Callable[[dict[str, Any] | None, str], str],
    normalizer: Callable[[Any], str] = normalized_email,
    message: str | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    email = append_unique_email(pending_retry_emails, candidate_email, normalizer=normalizer)
    pending_retry_queue.append(
        {
            "email": email,
            "reason": reason,
            "retry_round": retry_round,
            "current": current_index,
            "total": total_count,
            "result": dict(result_payload or {}),
        }
    )
    candidate_queue.append(
        {
            "email": email,
            "current": current_index,
            "retry_round": retry_round,
        }
    )
    return pending_retry_queued_progress(
        candidate_email=email,
        current_index=current_index,
        total_count=total_count,
        pending_retry_count=len(pending_retry_emails),
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        reason=reason,
        result_payload=result_payload,
        source_stage=source_stage,
        message=message or "",
        level=level,
    )


def parallel_first_round_queued_progress(
    *,
    candidate_email: str,
    current_index: int,
    total_count: int,
    retry_round: int,
    max_retry_rounds: int,
    reason: str,
    result_payload: dict[str, Any] | None,
    source_stage: Callable[[dict[str, Any] | None, str], str],
) -> dict[str, Any]:
    return pending_retry_queued_progress(
        candidate_email=candidate_email,
        current_index=current_index,
        total_count=total_count,
        pending_retry_count=None,
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        reason=reason,
        result_payload=result_payload,
        source_stage=source_stage,
        message=f"PayPal 并发首轮失败，已加入待重试池: {candidate_email}",
        level="warn",
        include_source_stage=False,
    )


def parallel_next_round_queued_progress(
    *,
    candidate_email: str,
    current_index: int,
    total_count: int,
    pending_retry_count: int,
    source_retry_round: int,
    retry_round: int,
    max_retry_rounds: int,
    reason: str,
    result_payload: dict[str, Any] | None,
    source_stage: Callable[[dict[str, Any] | None, str], str],
) -> dict[str, Any]:
    return pending_retry_queued_progress(
        candidate_email=candidate_email,
        current_index=current_index,
        total_count=total_count,
        pending_retry_count=pending_retry_count,
        retry_round=retry_round,
        max_retry_rounds=max_retry_rounds,
        reason=reason,
        result_payload=result_payload,
        source_stage=source_stage,
        message=(
            f"PayPal 待重试第 {source_retry_round}/{max_retry_rounds} 轮失败，"
            f"已加入下一轮待重试池: {candidate_email}"
        ),
        level="warn",
    )


def pending_retry_wait_seconds(
    retry_round: int,
    waited_rounds: set[int],
    backoffs: list[float] | tuple[float, ...] = DEFAULT_PENDING_RETRY_BACKOFFS,
) -> float | None:
    try:
        normalized_retry_round = int(retry_round)
    except Exception:
        normalized_retry_round = 1
    if normalized_retry_round <= 0 or normalized_retry_round in waited_rounds:
        return None
    wait_seconds = backoffs[min(normalized_retry_round - 1, len(backoffs) - 1)] if backoffs else 0.0
    waited_rounds.add(normalized_retry_round)
    return float(wait_seconds)


def pending_retry_wait_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    pending_count: int,
    wait_seconds: float,
) -> dict[str, Any]:
    return {
        "stage": "paypal_pending_retry_wait",
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "pending_retry": pending_count,
        "wait_seconds": wait_seconds,
        "message": f"PayPal 待重试第 {retry_round}/{max_retry_rounds} 轮将在 {wait_seconds:.0f}s 后开始",
    }


def pending_retry_started_progress(
    *,
    retry_round: int,
    max_retry_rounds: int,
    pending_count: int,
    concurrency: int | None = None,
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "stage": "paypal_pending_retry_started",
        "retry_round": retry_round,
        "max_retry_rounds": max_retry_rounds,
        "pending_retry": pending_count,
    }
    if concurrency is None:
        progress["message"] = f"开始 PayPal 待重试第 {retry_round}/{max_retry_rounds} 轮，共 {pending_count} 个账号"
    else:
        progress["concurrency"] = concurrency
        progress["message"] = (
            f"开始并发 PayPal 待重试第 {retry_round}/{max_retry_rounds} 轮，共 {pending_count} 个账号，并发 {concurrency}"
        )
    return progress


def candidate_retry_reason(
    result_payload: dict[str, Any] | None,
    *,
    retry_reason: Callable[[dict[str, Any] | None], str],
    phone_accounts: list[dict],
    invalid_phone_keys: set[str],
    phone_available: Callable[[dict | None, set[str]], bool],
) -> str:
    reason = retry_reason(result_payload)
    if reason not in {"paypal_phone_rejected", "paypal_phone_pool_exhausted"}:
        return reason
    if not phone_accounts:
        return ""
    has_available_phone = any(phone_available(phone_account, invalid_phone_keys) for phone_account in phone_accounts)
    return reason if has_available_phone else ""
