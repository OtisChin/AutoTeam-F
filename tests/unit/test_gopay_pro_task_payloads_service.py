from autotoken.services import gopay_pro_task_payloads


def test_gopay_pro_cooldown_progress_payloads_are_stable():
    waf_blocked = gopay_pro_task_payloads.gopay_pro_register_waf_blocked_progress(
        cooldown_remaining_seconds=125
    )
    waf_cooling = gopay_pro_task_payloads.gopay_pro_register_waf_cooling_progress(
        cooldown_remaining_seconds=125
    )
    restored = gopay_pro_task_payloads.gopay_pro_register_ratelimit_cooldown_restored_progress(
        count=2
    )
    ratelimited = gopay_pro_task_payloads.gopay_pro_register_ratelimit_cooldown_progress(
        slot_ids=["slot-01", "slot-02"],
        cooldown_minutes=60,
    )

    assert waf_blocked == {
        "stage": "gopay_pro_register_waf_blocked",
        "level": "error",
        "cooldown_remaining_seconds": 125,
        "message": "检测到 GoPay signup WAF Block，已进入注册冷却 2 分钟；请更换出口 IP 或降低并发后再试",
    }
    assert waf_cooling == {
        "stage": "gopay_pro_register_waf_cooling",
        "level": "warn",
        "cooldown_remaining_seconds": 125,
        "message": "GoPay 注册仍在 WAF 冷却中，剩余约 2 分钟；本次不再触发 reg",
    }
    assert restored == {
        "stage": "gopay_pro_register_ratelimit_cooldown_restored",
        "count": 2,
        "message": "2 个 GoPay 注册限流号码冷却结束，已恢复到稳定号池",
    }
    assert ratelimited == {
        "stage": "gopay_pro_register_ratelimit_cooldown",
        "level": "warn",
        "slot_ids": ["slot-01", "slot-02"],
        "count": 2,
        "cooldown_minutes": 60,
        "message": "检测到 2 个 GoPay 注册限流 slot，已移入号码冷却池 60 分钟，下一轮不再触发注册",
    }


def test_gopay_pro_maintenance_progress_payloads_are_stable():
    no_trial = gopay_pro_task_payloads.gopay_pro_no_trial_wallets_released_progress(count=3)
    midtrans = gopay_pro_task_payloads.gopay_pro_midtrans_charge_202_marked_progress(
        slot_ids=["slot-01", "slot-02"]
    )
    unusable = gopay_pro_task_payloads.gopay_pro_unusable_wallets_reset_progress(count=4)
    stuck = gopay_pro_task_payloads.gopay_pro_stuck_paying_slots_released_progress(count=5)
    recovery = gopay_pro_task_payloads.gopay_pro_recovery_started_progress(
        stage="gopay_pro_fix_failed_before_batch",
        reason="先恢复失败 slot",
    )
    recovery_failed = gopay_pro_task_payloads.gopay_pro_recovery_failed_progress(
        stage="gopay_pro_fix_failed_before_batch",
        exit_code=7,
    )

    assert no_trial == {
        "stage": "gopay_pro_no_trial_wallets_released",
        "count": 3,
        "message": "已将 3 个 NO_TRIAL 钱包重置为 WALLET_READY，继续给下一批 GPT 账号使用",
        "level": "warn",
    }
    assert midtrans == {
        "stage": "gopay_pro_midtrans_charge_202_marked",
        "level": "warn",
        "slot_ids": ["slot-01", "slot-02"],
        "count": 2,
        "message": "检测到 2 个 slot 最终支付被 Midtrans 202 拒绝，已仅做标记: slot-01, slot-02",
    }
    assert unusable == {
        "stage": "gopay_pro_unusable_wallets_reset",
        "count": 4,
        "message": "检测到 4 个 WALLET_READY slot 缺少 refresh_token，已改为 FAILED 并交给 reg 重建",
        "level": "warn",
    }
    assert stuck == {
        "stage": "gopay_pro_stuck_paying_slots_released",
        "count": 5,
        "message": "检测到 5 个 PLUS_PAYING slot 已带错误停止，已回退为 WALLET_READY 继续复用稳定号",
        "level": "warn",
    }
    assert recovery == {
        "stage": "gopay_pro_fix_failed_before_batch",
        "message": "先恢复失败 slot",
        "level": "warn",
    }
    assert recovery_failed == {
        "stage": "gopay_pro_fix_failed_before_batch_failed",
        "exit_code": 7,
        "message": "fix-failed 退出码 7，继续按当前 slot 状态处理",
        "level": "warn",
    }


def test_gopay_pro_refresh_and_validate_repair_progress_payloads_are_stable():
    refresh = gopay_pro_task_payloads.gopay_pro_refresh_started_progress()
    refresh_failed = gopay_pro_task_payloads.gopay_pro_refresh_failed_progress(exit_code=9)
    recovered = gopay_pro_task_payloads.gopay_pro_validate_failed_recovered_progress(
        slots=["slot-01", "slot-02"]
    )
    repair_started = gopay_pro_task_payloads.gopay_pro_validate_failed_repair_started_progress(
        slots=["slot-01", "slot-02"]
    )
    rebind_failed = gopay_pro_task_payloads.gopay_pro_validate_failed_rebind_failed_progress(
        slot="slot-01",
        exit_code=5,
    )
    register_started = gopay_pro_task_payloads.gopay_pro_validate_failed_register_started_progress(
        slots=["slot-01", "slot-02"],
        repaired=2,
    )

    assert refresh == {
        "stage": "gopay_pro_refresh_started",
        "message": "开始执行 CNGopay refresh，先无短信刷新 GoPay slot token",
    }
    assert refresh_failed == {
        "stage": "gopay_pro_refresh_failed",
        "exit_code": 9,
        "message": "refresh 退出码 9，继续执行后续恢复和收割",
        "level": "warn",
    }
    assert recovered == {
        "stage": "gopay_pro_validate_failed_recovered",
        "slots": ["slot-01", "slot-02"],
        "message": "payment/validate 失败 slot 已由 fix-failed 恢复，不再重绑重注册",
        "level": "success",
    }
    assert repair_started == {
        "stage": "gopay_pro_validate_failed_repair_started",
        "slots": ["slot-01", "slot-02"],
        "message": "仍有 2 个 payment/validate 失败 slot 未恢复，开始单独换绑后重新注册: slot-01, slot-02",
        "level": "warn",
    }
    assert rebind_failed == {
        "stage": "gopay_pro_validate_failed_rebind_failed",
        "slot": "slot-01",
        "exit_code": 5,
        "message": "slot-01 payment/validate 失败后单独换绑退出码 5，仍会继续处理其他 slot",
        "level": "error",
    }
    assert register_started == {
        "stage": "gopay_pro_validate_failed_register_started",
        "slots": ["slot-01", "slot-02"],
        "repaired": 2,
        "message": "2 个 payment/validate 失败 slot 已完成换绑，开始 reg 重建 GoPay 钱包",
        "level": "warn",
    }


def test_gopay_pro_batch_lifecycle_progress_payloads_are_stable():
    batch = gopay_pro_task_payloads.gopay_pro_batch_started_progress(
        total=5,
        concurrency=2,
        max_attempts=3,
    )
    round_started = gopay_pro_task_payloads.gopay_pro_round_started_progress(
        round_index=2,
        current=1,
        total=5,
        round_total=2,
        ready_slots=1,
        runtime_slots=3,
        account_emails=["a@example.com", "b@example.com"],
    )
    skipped = gopay_pro_task_payloads.gopay_pro_register_skipped_progress(
        round_index=2,
        ready_slots=3,
        round_total=2,
    )
    waf_abort = gopay_pro_task_payloads.gopay_pro_register_waf_abort_progress(
        round_index=2,
        cooldown_remaining_seconds=125,
    )
    register_failed = gopay_pro_task_payloads.gopay_pro_register_failed_progress(
        round_index=2,
        exit_code=7,
    )
    harvest_failed = gopay_pro_task_payloads.gopay_pro_harvest_failed_progress(
        round_index=2,
        exit_code=8,
    )
    round_completed = gopay_pro_task_payloads.gopay_pro_round_completed_progress(
        round_index=2,
        exit_code=0,
        successful=3,
        failed=1,
        pending=1,
        total=5,
    )

    assert batch == {
        "stage": "gopay_pro_batch_started",
        "total": 5,
        "concurrency": 2,
        "max_attempts": 3,
        "message": "开始 GoPay Pro 全自动批量：5 个 GPT 账号，稳定号并发 2",
    }
    assert round_started == {
        "stage": "gopay_pro_round_started",
        "round": 2,
        "current": 1,
        "total": 5,
        "round_total": 2,
        "ready_slots": 1,
        "runtime_slots": 3,
        "account_emails": ["a@example.com", "b@example.com"],
        "message": "第 2 轮开始：2 个 GPT 账号，启用 slot 3 个，已就绪 1 个",
    }
    assert skipped == {
        "stage": "gopay_pro_register_skipped",
        "round": 2,
        "ready_slots": 3,
        "round_total": 2,
        "message": "已有 3 个 WALLET_READY slot，跳过本轮 GoPay 注册准备",
    }
    assert waf_abort == {
        "stage": "gopay_pro_register_waf_abort",
        "round": 2,
        "level": "error",
        "cooldown_remaining_seconds": 125,
        "message": "本轮 GoPay 注册触发 WAF，已停止后续 harvest；剩余冷却约 2 分钟",
    }
    assert register_failed == {
        "stage": "gopay_pro_register_failed",
        "round": 2,
        "exit_code": 7,
        "message": "reg 脚本退出码 7，仍尝试检查/继续",
        "level": "warn",
    }
    assert harvest_failed == {
        "stage": "gopay_pro_harvest_failed",
        "round": 2,
        "exit_code": 8,
        "message": "harvest 脚本退出码 8，将按 slot 日志和最终状态逐个归因",
        "level": "warn",
    }
    assert round_completed == {
        "stage": "gopay_pro_round_completed",
        "round": 2,
        "exit_code": 0,
        "successful": 3,
        "failed": 1,
        "pending": 1,
        "total": 5,
        "message": "第 2 轮完成：成功 3，失败 1，待处理 1",
    }


def test_gopay_pro_batch_result_is_stable():
    successful = ["a@example.com"]
    failed = ["b@example.com"]
    retried = ["c@example.com"]

    result = gopay_pro_task_payloads.gopay_pro_batch_result(
        cancelled=False,
        successful_emails=successful,
        failed_emails=failed,
        pending_count=2,
        total=5,
        retried_emails=retried,
        concurrency=2,
        max_attempts=3,
    )
    cancelled = gopay_pro_task_payloads.gopay_pro_batch_result(
        cancelled=True,
        successful_emails=[],
        failed_emails=[],
        pending_count=5,
        total=5,
        retried_emails=[],
        concurrency=2,
        max_attempts=3,
    )

    assert result == {
        "status": "success",
        "total": 5,
        "successful": 1,
        "failed": 1,
        "pending": 2,
        "successful_emails": ["a@example.com"],
        "failed_emails": ["b@example.com"],
        "retried_emails": ["c@example.com"],
        "concurrency": 2,
        "max_attempts": 3,
        "message": "GoPay Pro 全自动批量完成：成功 1/5",
    }
    assert cancelled["status"] == "cancelled"
    assert cancelled["message"] == "GoPay Pro 全自动批量完成：成功 0/5"
    assert result["successful_emails"] is successful
    assert result["failed_emails"] is failed
    assert result["retried_emails"] is retried


def test_gopay_pro_script_cancelled_result_is_stable():
    result = gopay_pro_task_payloads.gopay_pro_script_cancelled_result(
        kind="harvest",
        script="harvest.cmd",
        exit_code=130,
        log_tail="cancelled",
    )

    assert result == {
        "status": "cancelled",
        "kind": "harvest",
        "script": "harvest.cmd",
        "exit_code": 130,
        "log_tail": "cancelled",
    }


def test_gopay_pro_account_outcome_progress_payloads_are_stable():
    plan_unconfirmed = gopay_pro_task_payloads.gopay_pro_account_plan_unconfirmed_progress(
        email="user@example.com",
        failed=1,
        total=5,
        plan_message="OpenAI Plus 状态未确认",
    )
    success = gopay_pro_task_payloads.gopay_pro_account_success_progress(
        email="user@example.com",
        successful=2,
        total=5,
    )
    no_trial = gopay_pro_task_payloads.gopay_pro_account_no_trial_progress(
        email="user@example.com",
        failed=2,
        total=5,
        removed=True,
    )
    token_invalidated = gopay_pro_task_payloads.gopay_pro_account_token_invalidated_progress(
        email="user@example.com",
        failed=3,
        total=5,
        removed=True,
    )
    checkout_unauthorized = gopay_pro_task_payloads.gopay_pro_account_checkout_unauthorized_progress(
        email="user@example.com",
        failed=4,
        total=5,
        removed=False,
    )
    ambiguous = gopay_pro_task_payloads.gopay_pro_account_ambiguous_progress(
        email="user@example.com",
        failed=5,
        total=5,
    )
    requeued = gopay_pro_task_payloads.gopay_pro_account_requeued_progress(
        email="user@example.com",
        attempt=1,
        max_attempts=3,
    )
    failed = gopay_pro_task_payloads.gopay_pro_account_failed_progress(
        email="user@example.com",
        failed=5,
        total=5,
    )

    assert plan_unconfirmed == {
        "stage": "gopay_pro_account_plan_unconfirmed",
        "email": "user@example.com",
        "failed": 1,
        "total": 5,
        "message": "支付链路完成但未确认 Plus，已停止标记并等待人工核对: user@example.com (OpenAI Plus 状态未确认)",
        "level": "warn",
    }
    assert success == {
        "stage": "gopay_pro_account_success",
        "email": "user@example.com",
        "successful": 2,
        "total": 5,
        "message": "GoPay Pro 绑定成功并已由 OpenAI 确认 Plus: user@example.com",
        "level": "success",
    }
    assert no_trial == {
        "stage": "gopay_pro_account_no_trial",
        "email": "user@example.com",
        "failed": 2,
        "total": 5,
        "removed": True,
        "message": "账号无试用资格，已从号池删除: user@example.com",
        "level": "warn",
    }
    assert token_invalidated == {
        "stage": "gopay_pro_account_token_invalidated",
        "email": "user@example.com",
        "failed": 3,
        "total": 5,
        "removed": True,
        "message": "账号 token 已失效，已从号池删除: user@example.com",
        "level": "error",
    }
    assert checkout_unauthorized == {
        "stage": "gopay_pro_account_checkout_unauthorized",
        "email": "user@example.com",
        "failed": 4,
        "total": 5,
        "removed": False,
        "message": "账号 checkout 401/token 无效，已从号池删除: user@example.com",
        "level": "error",
    }
    assert ambiguous == {
        "stage": "gopay_pro_account_ambiguous",
        "email": "user@example.com",
        "failed": 5,
        "total": 5,
        "message": "token 已消费但未匹配到明确成功 slot，已停止自动重试并等待人工核对: user@example.com",
        "level": "error",
    }
    assert requeued == {
        "stage": "gopay_pro_account_requeued",
        "email": "user@example.com",
        "attempt": 1,
        "max_attempts": 3,
        "message": "账号本轮未完成，加入下一轮重试: user@example.com",
        "level": "warn",
    }
    assert failed == {
        "stage": "gopay_pro_account_failed",
        "email": "user@example.com",
        "failed": 5,
        "total": 5,
        "message": "达到最大重试次数，已标记失败: user@example.com",
        "level": "error",
    }
