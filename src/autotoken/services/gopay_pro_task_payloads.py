from typing import Any


def gopay_pro_register_waf_blocked_progress(*, cooldown_remaining_seconds: int) -> dict[str, Any]:
    minutes = max(1, int(int(cooldown_remaining_seconds or 0) / 60))
    return {
        "stage": "gopay_pro_register_waf_blocked",
        "level": "error",
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "message": f"检测到 GoPay signup WAF Block，已进入注册冷却 {minutes} 分钟；请更换出口 IP 或降低并发后再试",
    }


def gopay_pro_register_waf_cooling_progress(*, cooldown_remaining_seconds: int) -> dict[str, Any]:
    minutes = max(1, int(int(cooldown_remaining_seconds or 0) / 60))
    return {
        "stage": "gopay_pro_register_waf_cooling",
        "level": "warn",
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "message": f"GoPay 注册仍在 WAF 冷却中，剩余约 {minutes} 分钟；本次不再触发 reg",
    }


def gopay_pro_register_ratelimit_cooldown_restored_progress(*, count: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_register_ratelimit_cooldown_restored",
        "count": count,
        "message": f"{count} 个 GoPay 注册限流号码冷却结束，已恢复到稳定号池",
    }


def gopay_pro_register_ratelimit_cooldown_progress(
    *,
    slot_ids: list[str],
    cooldown_minutes: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_register_ratelimit_cooldown",
        "level": "warn",
        "slot_ids": slot_ids,
        "count": len(slot_ids),
        "cooldown_minutes": cooldown_minutes,
        "message": f"检测到 {len(slot_ids)} 个 GoPay 注册限流 slot，已移入号码冷却池 {cooldown_minutes} 分钟，下一轮不再触发注册",
    }


def gopay_pro_no_trial_wallets_released_progress(*, count: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_no_trial_wallets_released",
        "count": count,
        "message": f"已将 {count} 个 NO_TRIAL 钱包重置为 WALLET_READY，继续给下一批 GPT 账号使用",
        "level": "warn",
    }


def gopay_pro_midtrans_charge_202_marked_progress(*, slot_ids: list[str]) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_midtrans_charge_202_marked",
        "level": "warn",
        "slot_ids": slot_ids,
        "count": len(slot_ids),
        "message": f"检测到 {len(slot_ids)} 个 slot 最终支付被 Midtrans 202 拒绝，已仅做标记: {', '.join(slot_ids)}",
    }


def gopay_pro_recovery_started_progress(*, stage: str, reason: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "message": reason,
        "level": "warn",
    }


def gopay_pro_recovery_failed_progress(*, stage: str, exit_code: int) -> dict[str, Any]:
    return {
        "stage": f"{stage}_failed",
        "exit_code": exit_code,
        "message": f"fix-failed 退出码 {exit_code}，继续按当前 slot 状态处理",
        "level": "warn",
    }


def gopay_pro_refresh_started_progress() -> dict[str, Any]:
    return {
        "stage": "gopay_pro_refresh_started",
        "message": "开始执行 CNGopay refresh，先无短信刷新 GoPay slot token",
    }


def gopay_pro_refresh_failed_progress(*, exit_code: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_refresh_failed",
        "exit_code": exit_code,
        "message": f"refresh 退出码 {exit_code}，继续执行后续恢复和收割",
        "level": "warn",
    }


def gopay_pro_validate_failed_recovered_progress(*, slots: list[str]) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_validate_failed_recovered",
        "slots": slots,
        "message": "payment/validate 失败 slot 已由 fix-failed 恢复，不再重绑重注册",
        "level": "success",
    }


def gopay_pro_validate_failed_repair_started_progress(*, slots: list[str]) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_validate_failed_repair_started",
        "slots": slots,
        "message": f"仍有 {len(slots)} 个 payment/validate 失败 slot 未恢复，开始单独换绑后重新注册: {', '.join(slots)}",
        "level": "warn",
    }


def gopay_pro_validate_failed_rebind_failed_progress(*, slot: str, exit_code: Any) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_validate_failed_rebind_failed",
        "slot": slot,
        "exit_code": exit_code,
        "message": f"{slot} payment/validate 失败后单独换绑退出码 {exit_code}，仍会继续处理其他 slot",
        "level": "error",
    }


def gopay_pro_validate_failed_register_started_progress(*, slots: list[str], repaired: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_validate_failed_register_started",
        "slots": slots,
        "repaired": repaired,
        "message": f"{repaired} 个 payment/validate 失败 slot 已完成换绑，开始 reg 重建 GoPay 钱包",
        "level": "warn",
    }


def gopay_pro_unusable_wallets_reset_progress(*, count: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_unusable_wallets_reset",
        "count": count,
        "message": f"检测到 {count} 个 WALLET_READY slot 缺少 refresh_token，已改为 FAILED 并交给 reg 重建",
        "level": "warn",
    }


def gopay_pro_stuck_paying_slots_released_progress(*, count: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_stuck_paying_slots_released",
        "count": count,
        "message": f"检测到 {count} 个 PLUS_PAYING slot 已带错误停止，已回退为 WALLET_READY 继续复用稳定号",
        "level": "warn",
    }


def gopay_pro_batch_started_progress(*, total: int, concurrency: int, max_attempts: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_batch_started",
        "total": total,
        "concurrency": concurrency,
        "max_attempts": max_attempts,
        "message": f"开始 GoPay Pro 全自动批量：{total} 个 GPT 账号，稳定号并发 {concurrency}",
    }


def gopay_pro_round_started_progress(
    *,
    round_index: int,
    current: int,
    total: int,
    round_total: int,
    ready_slots: int,
    runtime_slots: int,
    account_emails: list[str],
) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_round_started",
        "round": round_index,
        "current": current,
        "total": total,
        "round_total": round_total,
        "ready_slots": ready_slots,
        "runtime_slots": runtime_slots,
        "account_emails": account_emails,
        "message": f"第 {round_index} 轮开始：{round_total} 个 GPT 账号，启用 slot {runtime_slots} 个，已就绪 {ready_slots} 个",
    }


def gopay_pro_register_skipped_progress(*, round_index: int, ready_slots: int, round_total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_register_skipped",
        "round": round_index,
        "ready_slots": ready_slots,
        "round_total": round_total,
        "message": f"已有 {ready_slots} 个 WALLET_READY slot，跳过本轮 GoPay 注册准备",
    }


def gopay_pro_register_waf_abort_progress(
    *,
    round_index: int,
    cooldown_remaining_seconds: int,
) -> dict[str, Any]:
    minutes = max(1, int(int(cooldown_remaining_seconds or 0) / 60))
    return {
        "stage": "gopay_pro_register_waf_abort",
        "round": round_index,
        "level": "error",
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "message": f"本轮 GoPay 注册触发 WAF，已停止后续 harvest；剩余冷却约 {minutes} 分钟",
    }


def gopay_pro_register_failed_progress(*, round_index: int, exit_code: Any) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_register_failed",
        "round": round_index,
        "exit_code": exit_code,
        "message": f"reg 脚本退出码 {exit_code}，仍尝试检查/继续",
        "level": "warn",
    }


def gopay_pro_harvest_failed_progress(*, round_index: int, exit_code: Any) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_harvest_failed",
        "round": round_index,
        "exit_code": exit_code,
        "message": f"harvest 脚本退出码 {exit_code}，将按 slot 日志和最终状态逐个归因",
        "level": "warn",
    }


def gopay_pro_round_completed_progress(
    *,
    round_index: int,
    exit_code: Any,
    successful: int,
    failed: int,
    pending: int,
    total: int,
) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_round_completed",
        "round": round_index,
        "exit_code": exit_code,
        "successful": successful,
        "failed": failed,
        "pending": pending,
        "total": total,
        "message": f"第 {round_index} 轮完成：成功 {successful}，失败 {failed}，待处理 {pending}",
    }


def gopay_pro_batch_result(
    *,
    cancelled: bool,
    successful_emails: list[str],
    failed_emails: list[str],
    pending_count: int,
    total: int,
    retried_emails: list[str],
    concurrency: int,
    max_attempts: int,
) -> dict[str, Any]:
    status = "cancelled" if cancelled else ("success" if successful_emails else "failed")
    return {
        "status": status,
        "total": total,
        "successful": len(successful_emails),
        "failed": len(failed_emails),
        "pending": pending_count,
        "successful_emails": successful_emails,
        "failed_emails": failed_emails,
        "retried_emails": retried_emails,
        "concurrency": concurrency,
        "max_attempts": max_attempts,
        "message": f"GoPay Pro 全自动批量完成：成功 {len(successful_emails)}/{total}",
    }


def gopay_pro_script_cancelled_result(*, kind: str, script: str, exit_code: int, log_tail: str) -> dict[str, Any]:
    return {
        "status": "cancelled",
        "kind": kind,
        "script": script,
        "exit_code": exit_code,
        "log_tail": log_tail,
    }


def gopay_pro_account_plan_unconfirmed_progress(
    *,
    email: str,
    failed: int,
    total: int,
    plan_message: str,
) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_plan_unconfirmed",
        "email": email,
        "failed": failed,
        "total": total,
        "message": f"支付链路完成但未确认 Plus，已停止标记并等待人工核对: {email} ({plan_message})",
        "level": "warn",
    }


def gopay_pro_account_success_progress(*, email: str, successful: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_success",
        "email": email,
        "successful": successful,
        "total": total,
        "message": f"GoPay Pro 绑定成功并已由 OpenAI 确认 Plus: {email}",
        "level": "success",
    }


def gopay_pro_account_no_trial_progress(*, email: str, failed: int, total: int, removed: bool) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_no_trial",
        "email": email,
        "failed": failed,
        "total": total,
        "removed": removed,
        "message": f"账号无试用资格，已从号池删除: {email}",
        "level": "warn",
    }


def gopay_pro_account_token_invalidated_progress(
    *,
    email: str,
    failed: int,
    total: int,
    removed: bool,
) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_token_invalidated",
        "email": email,
        "failed": failed,
        "total": total,
        "removed": removed,
        "message": f"账号 token 已失效，已从号池删除: {email}",
        "level": "error",
    }


def gopay_pro_account_checkout_unauthorized_progress(
    *,
    email: str,
    failed: int,
    total: int,
    removed: bool,
) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_checkout_unauthorized",
        "email": email,
        "failed": failed,
        "total": total,
        "removed": removed,
        "message": f"账号 checkout 401/token 无效，已从号池删除: {email}",
        "level": "error",
    }


def gopay_pro_account_ambiguous_progress(*, email: str, failed: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_ambiguous",
        "email": email,
        "failed": failed,
        "total": total,
        "message": f"token 已消费但未匹配到明确成功 slot，已停止自动重试并等待人工核对: {email}",
        "level": "error",
    }


def gopay_pro_account_requeued_progress(*, email: str, attempt: int, max_attempts: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_requeued",
        "email": email,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "message": f"账号本轮未完成，加入下一轮重试: {email}",
        "level": "warn",
    }


def gopay_pro_account_failed_progress(*, email: str, failed: int, total: int) -> dict[str, Any]:
    return {
        "stage": "gopay_pro_account_failed",
        "email": email,
        "failed": failed,
        "total": total,
        "message": f"达到最大重试次数，已标记失败: {email}",
        "level": "error",
    }
