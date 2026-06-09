from autotoken.services import gopay_task_payloads


def test_gopay_proxy_and_task_entry_payloads_are_stable():
    proxy_api = gopay_task_payloads.gopay_proxy_api_selected_progress(
        current=2,
        total=5,
        proxy_label="pool-a",
        proxy_api_provider="cliproxy",
        selected_proxy_summary="socks5://proxy.example:1080",
    )
    proxy_pool = gopay_task_payloads.gopay_proxy_selected_progress(
        current=2,
        total=5,
        proxy_label="pool-a",
        proxy_pool_count=3,
        selected_proxy_summary="socks5://pool.example:1080",
    )
    binding = gopay_task_payloads.gopay_binding_progress(
        email="primary@example.com",
        auto_register=True,
        auto_register_count=4,
        auto_register_protocol=False,
        gopay_auto_signup=True,
        phone_number="+15550000001",
        country_code="ID",
        phone_account_count=2,
        checkout_ui_mode="hosted",
        proxy_label="pool-a",
        account_count=4,
        pending_retry_attempts=2,
        concurrency=1,
    )

    assert proxy_api == {
        "stage": "gopay_proxy_api_selected",
        "current": 2,
        "total": 5,
        "proxy_label": "pool-a",
        "proxy_api_provider": "cliproxy",
        "proxy_api_url_present": True,
        "message": "已通过 cliproxy API 获取 GoPay 注册代理: socks5://proxy.example:1080",
    }
    assert proxy_pool == {
        "stage": "gopay_proxy_selected",
        "current": 2,
        "total": 5,
        "proxy_label": "pool-a",
        "proxy_pool_count": 3,
        "message": "已从 GoPay 动态代理池选择代理: socks5://pool.example:1080",
    }
    assert binding == {
        "stage": "gopay_binding",
        "email": "primary@example.com",
        "auto_register": True,
        "auto_register_count": 4,
        "auto_register_protocol": False,
        "gopay_auto_signup": True,
        "phone_number": "+15550000001",
        "country_code": "ID",
        "phone_account_count": 2,
        "checkout_ui_mode": "hosted",
        "proxy_label": "pool-a",
        "account_count": 4,
        "pending_retry_attempts": 2,
        "concurrency": 1,
    }


def test_gopay_task_warning_and_failure_payloads_are_stable():
    limited = gopay_task_payloads.gopay_concurrency_limited_progress(
        requested_concurrency=3,
        concurrency=1,
    )
    bypassed = gopay_task_payloads.gopay_bind_proxy_bypassed_progress()
    failed = gopay_task_payloads.gopay_task_exception_result(
        failure_stage="gopay_wallet_funding",
        error=RuntimeError("Rekberinaja failed"),
    )
    bind_failed = gopay_task_payloads.gopay_bind_failure_result(
        failure_stage="gopay_wallet_no_numbers",
        message=RuntimeError("no numbers"),
    )
    invalid_email = gopay_task_payloads.gopay_invalid_email_result()
    cancelled = gopay_task_payloads.gopay_cancelled_result()
    refresh_failed = gopay_task_payloads.gopay_auth_session_refresh_failed_progress(
        email="user@example.com",
        failure_stage="",
        removed_pool_emails=["user@example.com"],
        message="auth_session access token 已失效",
    )
    retained = gopay_task_payloads.gopay_wallet_otp_session_retained_progress(
        phone_number="+1555******0001"
    )

    assert limited == {
        "stage": "gopay_concurrency_limited",
        "requested_concurrency": 3,
        "concurrency": 1,
        "message": "GoPay 并发已限制为 1，避免 checkout/自动注册/手机号资源冲突",
        "level": "warn",
    }
    assert bypassed == {
        "stage": "gopay_bind_proxy_bypassed",
        "message": "GoPay 绑定阶段不使用 SOCKS 代理，checkout/Stripe/Midtrans 将直连",
    }
    assert failed == {
        "status": "failed",
        "failure_stage": "gopay_wallet_funding",
        "message": "GoPay 任务执行异常: Rekberinaja failed",
        "screenshot_paths": [],
    }
    assert bind_failed == {
        "status": "failed",
        "failure_stage": "gopay_wallet_no_numbers",
        "message": "no numbers",
        "screenshot_paths": [],
    }
    assert invalid_email == {"status": "failed", "failure_stage": "invalid_email", "message": "邮箱为空"}
    assert cancelled == {"status": "cancelled", "failure_stage": "cancelled", "message": "任务已取消"}
    assert refresh_failed == {
        "stage": "gopay_auth_session_refresh_failed",
        "email": "user@example.com",
        "failure_stage": "token_invalidated",
        "removed_pool_emails": ["user@example.com"],
        "message": "auth_session access token 已失效",
        "level": "warn",
    }
    assert retained == {
        "stage": "gopay_wallet_otp_session_retained",
        "phone_number": "+1555******0001",
        "message": "GoPay 绑定未完整成功，已保留短信接码会话，未标记完成或取消",
        "level": "warn",
    }


def test_gopay_reusable_wallet_progress_payloads_are_stable():
    preserved = gopay_task_payloads.gopay_wallet_preserved_progress(
        phone_number="+1555******0001",
        expires_in_seconds=900,
    )
    discarded = gopay_task_payloads.gopay_wallet_reuse_discarded_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        reason="bridge_missing",
    )
    reused = gopay_task_payloads.gopay_wallet_reused_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        expires_in_seconds=800,
    )

    assert preserved == {
        "stage": "gopay_wallet_preserved",
        "phone_number": "+1555******0001",
        "expires_in_seconds": 900,
        "message": "当前失败未完成 GoPay 绑定，钱包已放入可复用池，后续账号/新任务会优先复用",
        "level": "warn",
    }
    assert discarded == {
        "stage": "gopay_wallet_reuse_discarded",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "reason": "bridge_missing",
        "message": "复用 GoPay 钱包的短信会话已不可用，丢弃该钱包并重新注册",
        "level": "warn",
    }
    assert reused == {
        "stage": "gopay_wallet_reused",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "expires_in_seconds": 800,
        "message": "优先复用 20 分钟有效期内未完成绑定的 GoPay 钱包 (2/5)",
    }


def test_gopay_wallet_balance_progress_payloads_are_stable():
    wait = gopay_task_payloads.gopay_wallet_balance_wait_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        delay_seconds=3.25,
        attempt=1,
        max_attempts=3,
    )
    failed = gopay_task_payloads.gopay_wallet_balance_check_failed_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        attempt=1,
        max_attempts=3,
        error_summary="network timeout",
    )
    checked = gopay_task_payloads.gopay_wallet_balance_checked_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        balance=1001.0,
        currency="IDR",
        display_value="Rp1.001",
        attempt=2,
        max_attempts=3,
    )
    ready = gopay_task_payloads.gopay_wallet_balance_ready_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        balance=1001.0,
        currency="IDR",
        display_value="Rp1.001",
        message="GoPay 钱包余额已到账，开始绑定",
    )
    not_ready = gopay_task_payloads.gopay_wallet_balance_not_ready_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        message="GoPay 余额三次查询仍未到账，舍弃该钱包并重新注册",
    )

    assert wait == {
        "stage": "gopay_wallet_balance_wait",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "delay_seconds": 3.2,
        "attempt": 1,
        "max_attempts": 3,
        "message": "等待 3.2s 后第 1/3 次查询 GoPay 余额",
        "level": "warn",
    }
    assert failed == {
        "stage": "gopay_wallet_balance_check_failed",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "attempt": 1,
        "max_attempts": 3,
        "message": "GoPay 余额查询失败 (1/3): network timeout",
        "level": "warn",
    }
    assert checked == {
        "stage": "gopay_wallet_balance_checked",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "balance": 1001.0,
        "currency": "IDR",
        "display_value": "Rp1.001",
        "attempt": 2,
        "max_attempts": 3,
        "message": "GoPay 钱包余额查询: Rp1.001 (2/3)",
    }
    assert ready == {
        "stage": "gopay_wallet_balance_ready",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "balance": 1001.0,
        "currency": "IDR",
        "display_value": "Rp1.001",
        "message": "GoPay 钱包余额已到账，开始绑定",
        "level": "success",
    }
    assert not_ready == {
        "stage": "gopay_wallet_balance_not_ready",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "GoPay 余额三次查询仍未到账，舍弃该钱包并重新注册",
        "level": "warn",
    }


def test_gopay_wallet_balance_threshold_progress_payloads_are_stable():
    insufficient_limit = gopay_task_payloads.gopay_wallet_balance_insufficient_limit_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        balance_insufficient_count=3,
        message="连续 3 个已充值 GoPay 钱包余额不足，停止本任务继续消耗钱包",
    )
    transfer_enabled = gopay_task_payloads.gopay_wallet_balance_auto_transfer_enabled_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        balance_miss_count=3,
    )
    transfer_disabled = gopay_task_payloads.gopay_wallet_transfer_auto_disabled_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        balance=1001.0,
        currency="IDR",
        display_value="Rp1.001",
        balance_1001_count=3,
    )

    assert insufficient_limit == {
        "stage": "gopay_wallet_balance_insufficient_limit",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "balance_insufficient_count": 3,
        "message": "连续 3 个已充值 GoPay 钱包余额不足，停止本任务继续消耗钱包",
        "level": "error",
    }
    assert transfer_enabled == {
        "stage": "gopay_wallet_balance_auto_transfer_enabled",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "balance_miss_count": 3,
        "message": "连续 3 个 GoPay 钱包官方赠送 Rp1 未到账，已切换到 Rekberinaja 转账模式",
        "level": "warn",
    }
    assert transfer_disabled == {
        "stage": "gopay_wallet_transfer_auto_disabled",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "balance": 1001.0,
        "currency": "IDR",
        "display_value": "Rp1.001",
        "balance_1001_count": 3,
        "message": "连续 3 次 Rekberinaja 转账后 GoPay 余额为 Rp1001，判断官方 Rp1 已恢复赠送，本任务后续关闭转账并等待官方 Rp1 到账",
        "level": "warn",
    }


def test_gopay_wallet_funding_progress_payloads_are_stable():
    skipped = gopay_task_payloads.gopay_wallet_funding_skipped_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        message="GoPay 钱包已有 ≥1Rp 余额，本次跳过 Rekberinaja 转账",
    )
    started = gopay_task_payloads.gopay_wallet_funding_started_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
    )
    failed = gopay_task_payloads.gopay_wallet_funding_failed_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        transaction_id="trx-1",
        rekberinaja_stage="payment",
        debited_possible=False,
        error_summary="network timeout",
    )
    debited_failed = gopay_task_payloads.gopay_wallet_funding_failed_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        transaction_id="trx-2",
        rekberinaja_stage="payment",
        debited_possible=True,
        error_summary="ignored",
    )
    submitted = gopay_task_payloads.gopay_wallet_funding_submitted_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        transaction_id="trx-1",
    )
    done = gopay_task_payloads.gopay_wallet_funding_done_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        transaction_id="trx-1",
    )
    fallback = gopay_task_payloads.gopay_wallet_balance_fallback_transfer_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        wait_seconds_total=12.4,
    )
    no_transfer_wait = gopay_task_payloads.gopay_wallet_no_transfer_bind_wait_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
        delay_seconds=4.25,
    )

    assert skipped == {
        "stage": "gopay_wallet_funding_skipped",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "GoPay 钱包已有 ≥1Rp 余额，本次跳过 Rekberinaja 转账",
    }
    assert started == {
        "stage": "gopay_wallet_funding_started",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "正在通过 Rekberinaja 站内余额给 GoPay 钱包充值 (2/5)",
    }
    assert failed == {
        "stage": "gopay_wallet_funding_failed",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "transaction_id": "trx-1",
        "rekberinaja_stage": "payment",
        "debited_possible": False,
        "message": "Rekberinaja 充值失败: network timeout",
        "level": "warn",
    }
    assert debited_failed["message"] == "Rekberinaja 充值失败；订单已进入站内支付阶段，后续复用该钱包时不会重复充值"
    assert submitted == {
        "stage": "gopay_wallet_funding_submitted",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "transaction_id": "trx-1",
        "message": "Rekberinaja GoPay 转账已提交，开始轮询 GoPay 余额 (2/5)",
    }
    assert done == {
        "stage": "gopay_wallet_funding_done",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "transaction_id": "trx-1",
        "message": "Rekberinaja GoPay 转账余额已到账 (2/5)",
    }
    assert fallback == {
        "stage": "gopay_wallet_balance_fallback_transfer",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "GoPay 余额 12s 内未到账，开始回退到 Rekberinaja 转账",
        "level": "warn",
    }
    assert no_transfer_wait == {
        "stage": "gopay_wallet_no_transfer_bind_wait",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "delay_seconds": 4.2,
        "message": "未启用 GoPay 充值/转账，等待 4.2s 后开始绑定 (2/5)",
    }


def test_gopay_wallet_auto_signup_basic_progress_payloads_are_stable():
    detail = gopay_task_payloads.gopay_wallet_auto_signup_detail_progress(
        current=2,
        total=5,
        attempt=1,
        max_attempts=10,
        message="注册日志",
        worker_fields={"worker": "gopay-1", "worker_index": 1},
    )
    started = gopay_task_payloads.gopay_wallet_auto_signup_started_progress(
        current=2,
        total=5,
        wallet_attempt=1,
        max_wallet_attempts=10,
        sms_provider="smsbower",
    )
    retry = gopay_task_payloads.gopay_wallet_auto_signup_retry_progress(
        current=2,
        total=5,
        next_attempt=2,
        max_attempts=10,
        error_summary="temporary failure",
    )
    retry_with_message = gopay_task_payloads.gopay_wallet_auto_signup_retry_progress(
        current=2,
        total=5,
        next_attempt=3,
        max_attempts=10,
        message="GoPay 余额未到账，准备重新注册 GoPay 钱包",
    )
    done = gopay_task_payloads.gopay_wallet_auto_signup_done_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
    )

    assert detail == {
        "stage": "gopay_wallet_auto_signup_detail",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "message": "注册日志",
        "worker": "gopay-1",
        "worker_index": 1,
    }
    assert started == {
        "stage": "gopay_wallet_auto_signup_started",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "sms_provider": "smsbower",
        "message": "正在自动注册 GoPay 钱包 (2/5)，取号尝试 1/10",
    }
    assert retry == {
        "stage": "gopay_wallet_auto_signup_retry",
        "current": 2,
        "total": 5,
        "attempt": 2,
        "max_attempts": 10,
        "message": "GoPay 钱包自动注册失败，准备换号重试: temporary failure",
        "level": "warn",
    }
    assert retry_with_message == {
        "stage": "gopay_wallet_auto_signup_retry",
        "current": 2,
        "total": 5,
        "attempt": 3,
        "max_attempts": 10,
        "message": "GoPay 余额未到账，准备重新注册 GoPay 钱包",
        "level": "warn",
    }
    assert done == {
        "stage": "gopay_wallet_auto_signup_done",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "GoPay 钱包自动注册完成 (2/5)",
    }


def test_gopay_wallet_auto_signup_exception_progress_payloads_are_stable():
    probe = gopay_task_payloads.gopay_wallet_auto_signup_probe_failed_progress(
        current=2,
        total=5,
        attempt=1,
        max_attempts=10,
        error_summary="probe failed",
    )
    rate_limited = gopay_task_payloads.gopay_wallet_auto_signup_rate_limited_progress(
        current=2,
        total=5,
        attempt=1,
        max_attempts=10,
        no_numbers_attempt=0,
        no_numbers_max_attempts=3,
        error_summary="rate limited",
    )
    no_numbers_retry = gopay_task_payloads.gopay_wallet_auto_signup_no_numbers_retry_progress(
        current=2,
        total=5,
        attempt=1,
        max_attempts=10,
        no_numbers_attempt=1,
        no_numbers_max_attempts=3,
        error_summary="no numbers",
    )
    no_numbers = gopay_task_payloads.gopay_wallet_auto_signup_no_numbers_progress(
        current=2,
        total=5,
        attempt=1,
        max_attempts=10,
        no_numbers_attempt=3,
        no_numbers_max_attempts=3,
        error_summary="no numbers",
    )
    provider = gopay_task_payloads.gopay_wallet_auto_signup_provider_error_progress(
        current=2,
        total=5,
        attempt=1,
        max_attempts=10,
        error_summary="provider down",
    )
    network = gopay_task_payloads.gopay_wallet_auto_signup_network_error_progress(
        current=2,
        total=5,
        attempt=1,
        max_attempts=10,
        error_summary="network down",
    )

    assert probe == {
        "stage": "gopay_wallet_auto_signup_probe_failed",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "message": "GoPay 注册前探测异常，已停止继续取号: probe failed",
        "level": "error",
    }
    assert rate_limited == {
        "stage": "gopay_wallet_auto_signup_rate_limited",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "no_numbers_attempt": 0,
        "no_numbers_max_attempts": 3,
        "message": "GoPay 钱包自动注册触发 rate_limited，已停止任务: rate limited",
        "level": "error",
    }
    assert no_numbers_retry == {
        "stage": "gopay_wallet_auto_signup_no_numbers_retry",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "no_numbers_attempt": 1,
        "no_numbers_max_attempts": 3,
        "message": "GoPay 钱包自动注册暂时无可用号码，准备第 2/3 次重新取号: no numbers",
        "level": "warn",
    }
    assert no_numbers == {
        "stage": "gopay_wallet_auto_signup_no_numbers",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "no_numbers_attempt": 3,
        "no_numbers_max_attempts": 3,
        "message": "GoPay 钱包自动注册暂时无可用号码，将进入待重试: no numbers",
        "level": "warn",
    }
    assert provider == {
        "stage": "gopay_wallet_auto_signup_provider_error",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "message": "GoPay 钱包自动注册供应商不可用，已停止当前账号: provider down",
        "level": "error",
    }
    assert network == {
        "stage": "gopay_wallet_auto_signup_network_error",
        "current": 2,
        "total": 5,
        "attempt": 1,
        "max_attempts": 10,
        "message": "GoPay 钱包自动注册遇到网络中断，已停止继续换号: network down",
        "level": "warn",
    }


def test_gopay_wallet_discard_progress_payloads_are_stable():
    abandoned = gopay_task_payloads.gopay_wallet_balance_abandoned_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
    )
    already_linked = gopay_task_payloads.gopay_wallet_already_linked_discarded_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
    )
    charge_denied = gopay_task_payloads.gopay_wallet_charge_denied_discarded_progress(
        current=2,
        total=5,
        phone_number="+1555******0001",
    )

    assert abandoned == {
        "stage": "gopay_wallet_balance_abandoned",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "GoPay 余额未到账，已取消该短信会话并准备重新注册钱包",
        "level": "warn",
    }
    assert already_linked == {
        "stage": "gopay_wallet_already_linked_discarded",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "该 GoPay 手机号已绑定其他账号，已舍弃该钱包并重新注册",
        "level": "warn",
    }
    assert charge_denied == {
        "stage": "gopay_wallet_charge_denied_discarded",
        "current": 2,
        "total": 5,
        "phone_number": "+1555******0001",
        "message": "Midtrans 拒绝该 GoPay 钱包扣款，已舍弃该钱包并准备重新注册",
        "level": "warn",
    }


def test_gopay_wallet_serial_retry_progress_payloads_are_stable():
    signup_retry = gopay_task_payloads.gopay_wallet_signup_retry_same_account_progress(
        email="user@example.com",
        current=2,
        total=5,
        next_attempt=3,
        max_attempts=10,
        failure_stage="gopay_wallet_no_numbers",
        error_summary="no numbers",
    )
    charge_denied = gopay_task_payloads.gopay_wallet_charge_denied_retry_progress(
        email="user@example.com",
        current=2,
        total=5,
        next_attempt=3,
        max_attempts=10,
    )
    already_linked = gopay_task_payloads.gopay_wallet_already_linked_retry_progress(
        email="user@example.com",
        current=2,
        total=5,
        next_attempt=3,
        max_attempts=10,
    )

    assert signup_retry == {
        "stage": "gopay_wallet_signup_retry_same_account",
        "email": "user@example.com",
        "current": 2,
        "total": 5,
        "attempt": 3,
        "max_attempts": 10,
        "failure_stage": "gopay_wallet_no_numbers",
        "message": "GoPay 钱包注册未拿到可用手机号，继续为当前账号重新注册钱包后绑定: no numbers",
        "level": "warn",
    }
    assert charge_denied == {
        "stage": "gopay_wallet_charge_denied_retry",
        "email": "user@example.com",
        "current": 2,
        "total": 5,
        "attempt": 3,
        "max_attempts": 10,
        "message": "Midtrans 拒绝该 GoPay 钱包扣款，正在重新注册 GoPay 钱包后重试当前账号",
        "level": "warn",
    }
    assert already_linked == {
        "stage": "gopay_wallet_already_linked_retry",
        "email": "user@example.com",
        "current": 2,
        "total": 5,
        "attempt": 3,
        "max_attempts": 10,
        "message": "GoPay 手机号已绑定其他账号，正在重新注册 GoPay 钱包后重试当前账号",
        "level": "warn",
    }


def test_gopay_bind_attempt_finished_progress_payloads_are_stable():
    failed = gopay_task_payloads.gopay_bind_attempt_finished_progress(
        email="user@example.com",
        current=2,
        total=5,
        wallet_attempt=1,
        status="failed",
        failure_stage="gopay_wallet_no_numbers",
        detail="no numbers",
    )
    success = gopay_task_payloads.gopay_bind_attempt_finished_progress(
        email="user@example.com",
        current=2,
        total=5,
        wallet_attempt=2,
        status="success",
        failure_stage="",
        detail="",
    )

    assert failed == {
        "stage": "gopay_bind_attempt_finished",
        "email": "user@example.com",
        "current": 2,
        "total": 5,
        "wallet_attempt": 1,
        "status": "failed",
        "failure_stage": "gopay_wallet_no_numbers",
        "message": "GoPay 绑定尝试返回: status=failed; failure_stage=gopay_wallet_no_numbers; detail=no numbers",
        "level": "warn",
    }
    assert success == {
        "stage": "gopay_bind_attempt_finished",
        "email": "user@example.com",
        "current": 2,
        "total": 5,
        "wallet_attempt": 2,
        "status": "success",
        "failure_stage": "",
        "message": "GoPay 绑定尝试返回: status=success; failure_stage=-; detail=-",
        "level": "info",
    }


def test_gopay_wallet_prefetch_progress_payloads_are_stable():
    started = gopay_task_payloads.gopay_wallet_prefetch_started_progress(current=2, total=5)
    wait = gopay_task_payloads.gopay_wallet_prefetch_wait_progress(current=3, total=5)
    failed = gopay_task_payloads.gopay_wallet_prefetch_failed_progress(
        current=3,
        total=5,
        prefetch_index=2,
        error_summary="worker failed",
    )
    used = gopay_task_payloads.gopay_wallet_prefetch_used_progress(
        current=3,
        total=5,
        prefetch_index=2,
        phone_number="+1555******0001",
    )

    assert started == {
        "stage": "gopay_wallet_prefetch_started",
        "current": 2,
        "total": 5,
        "message": "后台预注册 GoPay 钱包 (2/5)",
    }
    assert wait == {
        "stage": "gopay_wallet_prefetch_wait",
        "current": 3,
        "total": 5,
        "message": "等待后台预注册 GoPay 钱包完成 (3/5)",
    }
    assert failed == {
        "stage": "gopay_wallet_prefetch_failed",
        "current": 3,
        "total": 5,
        "prefetch_index": 2,
        "message": "后台预注册 GoPay 钱包失败，回退同步注册: worker failed",
        "level": "warn",
    }
    assert used == {
        "stage": "gopay_wallet_prefetch_used",
        "current": 3,
        "total": 5,
        "prefetch_index": 2,
        "phone_number": "+1555******0001",
        "message": "使用后台预注册 GoPay 钱包 (3/5)",
    }


def test_gopay_auto_signup_account_result_progress_payloads_are_stable():
    started = gopay_task_payloads.gopay_auto_signup_account_progress(
        email="user@example.com",
        current=2,
        total=5,
    )
    success = gopay_task_payloads.gopay_auto_signup_account_success_progress(
        email="user@example.com",
        current=2,
        total=5,
        retry_round=1,
        max_retry_rounds=3,
        successful_count=1,
        message="GoPay 自动注册绑定账号成功: user@example.com (2/5)",
        success_progress_fields={"successful": 2, "successful_emails": ["a@example.com", "user@example.com"]},
    )
    paid_success = gopay_task_payloads.gopay_auto_signup_account_success_progress(
        email="user@example.com",
        current=2,
        total=5,
        successful_count=1,
        message="GoPay account is already Plus, counted as success: user@example.com (2/5)",
        success_progress_fields={"successful": 1, "successful_emails": ["user@example.com"]},
        position_field="current",
    )
    failed = gopay_task_payloads.gopay_auto_signup_account_failed_progress(
        email="user@example.com",
        current=2,
        total=5,
        retry_round=1,
        max_retry_rounds=3,
        failure_stage="gopay_wallet_no_numbers",
        message="failed",
    )

    assert started == {
        "stage": "gopay_auto_signup_account",
        "email": "user@example.com",
        "attempt": 2,
        "total": 5,
        "message": "正在为账号注册/复用 GoPay 钱包: user@example.com (2/5)",
    }
    assert success == {
        "stage": "gopay_auto_signup_account_success",
        "email": "user@example.com",
        "attempt": 2,
        "total": 5,
        "retry_round": 1,
        "max_retry_rounds": 3,
        "successful": 2,
        "message": "GoPay 自动注册绑定账号成功: user@example.com (2/5)",
        "successful_emails": ["a@example.com", "user@example.com"],
    }
    assert paid_success == {
        "stage": "gopay_auto_signup_account_success",
        "email": "user@example.com",
        "current": 2,
        "total": 5,
        "successful": 1,
        "message": "GoPay account is already Plus, counted as success: user@example.com (2/5)",
        "successful_emails": ["user@example.com"],
    }
    assert failed == {
        "stage": "gopay_auto_signup_account_failed",
        "email": "user@example.com",
        "attempt": 2,
        "total": 5,
        "failure_stage": "gopay_wallet_no_numbers",
        "message": "failed",
        "level": "warn",
        "retry_round": 1,
        "max_retry_rounds": 3,
    }


def test_gopay_auto_signup_rate_limited_result_is_stable():
    aggregate_results = [{"status": "success", "email_used": "done@example.com"}]
    failed_emails = [{"email": "old@example.com", "failure_stage": "old", "message": "old"}]

    result = gopay_task_payloads.gopay_auto_signup_rate_limited_result(
        email="user@example.com",
        current=2,
        total=5,
        message=RuntimeError("rate limited"),
        auto_signup_account_results=aggregate_results,
        attempted_emails=["user@example.com"],
        successful_emails=["done@example.com"],
        rejected_emails=["reject@example.com"],
        payment_failed_emails=["pay@example.com"],
        nonzero_blocked_emails=["blocked@example.com"],
        blocked_emails=["guard@example.com"],
        failed_emails=failed_emails,
    )

    assert result == {
        "status": "failed",
        "failure_stage": "gopay_wallet_rate_limited",
        "message": "rate limited",
        "screenshot_paths": [],
        "auto_signup_account_results": [
            {"status": "success", "email_used": "done@example.com"},
            {
                "status": "failed",
                "failure_stage": "gopay_wallet_rate_limited",
                "message": "rate limited",
                "screenshot_paths": [],
                "email_used": "user@example.com",
                "auto_signup_account_index": 2,
                "auto_signup_account_total": 5,
            },
        ],
        "attempted_emails": ["user@example.com"],
        "successful_emails": ["done@example.com"],
        "rejected_emails": ["reject@example.com"],
        "payment_failed_emails": ["pay@example.com"],
        "nonzero_blocked_emails": ["blocked@example.com"],
        "blocked_emails": ["guard@example.com"],
        "failed_emails": [
            {"email": "old@example.com", "failure_stage": "old", "message": "old"},
            {
                "email": "user@example.com",
                "failure_stage": "gopay_wallet_rate_limited",
                "message": "rate limited",
            },
        ],
    }
    assert aggregate_results == [{"status": "success", "email_used": "done@example.com"}]
    assert failed_emails == [{"email": "old@example.com", "failure_stage": "old", "message": "old"}]


def test_gopay_not_executed_results_are_stable():
    attempted_emails = ["attempted@example.com"]
    failed_emails = [{"email": "failed@example.com", "failure_stage": "old", "message": "old"}]

    register_cancelled = gopay_task_payloads.gopay_auto_register_not_executed_result(cancelled=True)
    register_failed = gopay_task_payloads.gopay_auto_register_not_executed_result(cancelled=False)
    signup_cancelled = gopay_task_payloads.gopay_auto_signup_not_executed_result(
        cancelled=True,
        attempted_emails=attempted_emails,
        failed_emails=failed_emails,
    )
    signup_failed = gopay_task_payloads.gopay_auto_signup_not_executed_result(
        cancelled=False,
        attempted_emails=attempted_emails,
        failed_emails=failed_emails,
    )

    assert register_cancelled == {
        "status": "cancelled",
        "failure_stage": "cancelled",
        "message": "自动注册 GoPay 任务已取消",
        "screenshot_paths": [],
        "auto_register_results": [],
        "successful_emails": [],
        "failed_emails": [],
    }
    assert register_failed == {
        "status": "failed",
        "failure_stage": "gopay_auto_register",
        "message": "自动注册 GoPay 未执行",
        "screenshot_paths": [],
        "auto_register_results": [],
        "successful_emails": [],
        "failed_emails": [],
    }
    assert signup_cancelled == {
        "status": "cancelled",
        "failure_stage": "cancelled",
        "message": "GoPay 自动注册绑定任务已取消",
        "screenshot_paths": [],
        "auto_signup_account_results": [],
        "attempted_emails": ["attempted@example.com"],
        "successful_emails": [],
        "failed_emails": [{"email": "failed@example.com", "failure_stage": "old", "message": "old"}],
    }
    assert signup_failed == {
        "status": "failed",
        "failure_stage": "gopay_auto_signup",
        "message": "GoPay 自动注册绑定未执行",
        "screenshot_paths": [],
        "auto_signup_account_results": [],
        "attempted_emails": ["attempted@example.com"],
        "successful_emails": [],
        "failed_emails": [{"email": "failed@example.com", "failure_stage": "old", "message": "old"}],
    }
    assert signup_cancelled["attempted_emails"] is attempted_emails
    assert signup_cancelled["failed_emails"] is failed_emails
    assert signup_failed["attempted_emails"] is attempted_emails
    assert signup_failed["failed_emails"] is failed_emails


def test_gopay_auto_signup_wallet_failure_progress_payloads_are_stable():
    no_account_retry = gopay_task_payloads.gopay_wallet_signup_failed_no_account_retry_progress(
        email="user@example.com",
        retry_round=1,
        max_retry_rounds=3,
        reason="gopay_wallet_no_numbers",
        failure_stage="gopay_wallet_no_numbers",
    )
    preserved = gopay_task_payloads.gopay_account_failed_wallet_preserved_progress(
        email="user@example.com",
        retry_round=1,
        max_retry_rounds=3,
        reason="account_failed",
        failure_stage="email_login",
    )

    assert no_account_retry == {
        "stage": "gopay_wallet_signup_failed_no_account_retry",
        "email": "user@example.com",
        "retry_round": 1,
        "max_retry_rounds": 3,
        "reason": "gopay_wallet_no_numbers",
        "failure_stage": "gopay_wallet_no_numbers",
        "message": "GoPay 钱包注册阶段失败，账号尚未进入绑定，不加入账号待重试池: user@example.com",
        "level": "warn",
    }
    assert preserved == {
        "stage": "gopay_account_failed_wallet_preserved",
        "email": "user@example.com",
        "retry_round": 1,
        "max_retry_rounds": 3,
        "reason": "account_failed",
        "failure_stage": "email_login",
        "message": "GoPay 邮箱账号侧失败，已保留注册好的钱包给其他账号复用: user@example.com",
        "level": "warn",
    }


def test_gopay_auto_register_progress_payloads_are_stable():
    luckmail_started = gopay_task_payloads.gopay_auto_register_started_progress(
        current=2,
        total=5,
        mail_provider="luckmail",
        luckmail_email_type="hot",
        luckmail_register_domain="mail.example",
        register_domain="fallback.example",
    )
    outlook_started = gopay_task_payloads.gopay_auto_register_started_progress(
        current=2,
        total=5,
        mail_provider="outlook",
        luckmail_email_type="",
        luckmail_register_domain=None,
        register_domain="fallback.example",
    )
    domain_started = gopay_task_payloads.gopay_auto_register_started_progress(
        current=2,
        total=5,
        mail_provider="temporary",
        luckmail_email_type="",
        luckmail_register_domain=None,
        register_domain="register.example",
    )
    done = gopay_task_payloads.gopay_auto_register_done_progress(
        email="new@example.com",
        current=2,
        total=5,
    )
    next_progress = gopay_task_payloads.gopay_auto_register_next_progress(
        current=2,
        total=5,
    )
    child_progress = gopay_task_payloads.gopay_auto_register_child_progress(
        {"stage": "mail_wait", "message": "等待验证码", "email": "new@example.com", "current": 99},
        current=2,
        total=5,
    )
    fallback_child_progress = gopay_task_payloads.gopay_auto_register_child_progress(
        {"message": ""},
        current=2,
        total=5,
    )
    bind_wait = gopay_task_payloads.gopay_auto_register_bind_wait_progress(
        email="new@example.com",
        current=2,
        total=5,
        delay_seconds=1.25,
    )
    failed = gopay_task_payloads.gopay_auto_register_failed_result(
        error=RuntimeError("mail provider failed")
    )

    assert luckmail_started == {
        "stage": "gopay_auto_register_started",
        "current": 2,
        "total": 5,
        "message": "自动注册已开始 (2/5): LuckMail/hot/@mail.example",
    }
    assert outlook_started == {
        "stage": "gopay_auto_register_started",
        "current": 2,
        "total": 5,
        "message": "自动注册已开始 (2/5): Outlook账号池",
    }
    assert domain_started == {
        "stage": "gopay_auto_register_started",
        "current": 2,
        "total": 5,
        "message": "自动注册已开始 (2/5): domain=@register.example",
    }
    assert done == {
        "stage": "gopay_auto_register_done",
        "email": "new@example.com",
        "current": 2,
        "total": 5,
        "message": "自动注册完成 (2/5)，开始 GoPay 绑定: new@example.com",
    }
    assert next_progress == {
        "stage": "gopay_auto_register_next",
        "current": 2,
        "total": 5,
        "message": "自动注册 GoPay 进度: 2/5",
    }
    assert child_progress == {
        "stage": "mail_wait",
        "message": "自动注册 (2/5)：等待验证码",
        "email": "new@example.com",
        "current": 2,
        "total": 5,
    }
    assert fallback_child_progress == {
        "message": "自动注册 (2/5)：gopay_auto_register_progress",
        "stage": "gopay_auto_register_progress",
        "current": 2,
        "total": 5,
    }
    assert bind_wait == {
        "stage": "gopay_auto_register_bind_wait",
        "email": "new@example.com",
        "current": 2,
        "total": 5,
        "delay_seconds": 1.2,
        "message": "注册已成功，等待 1.2s 后开始 GoPay 绑定: new@example.com",
    }
    assert failed == {
        "status": "failed",
        "failure_stage": "gopay_auto_register",
        "register_status": "failed",
        "bind_status": "not_started",
        "message": "自动注册失败: mail provider failed",
        "screenshot_paths": [],
    }


def test_gopay_auto_register_rate_limited_result_is_stable():
    aggregate_results = [{"status": "success", "email_used": "done@example.com"}]
    failed_emails = [{"email": "old@example.com", "failure_stage": "old", "message": "old"}]
    bind_failed_emails = [{"email": "old@example.com", "failure_stage": "old", "message": "old"}]

    result = gopay_task_payloads.gopay_auto_register_rate_limited_result(
        failed_email="new@example.com",
        fallback_email="fallback@example.com",
        current=2,
        total=5,
        message=RuntimeError("rate limited"),
        auto_register_results=aggregate_results,
        registered_emails=["new@example.com"],
        successful_emails=["done@example.com"],
        failed_emails=failed_emails,
        bind_failed_emails=bind_failed_emails,
        pending_retry_emails=["retry@example.com"],
        retried_emails=["retried@example.com"],
        rejected_emails=["reject@example.com"],
        payment_failed_emails=["pay@example.com"],
        nonzero_blocked_emails=["blocked@example.com"],
        blocked_emails=["guard@example.com"],
    )

    assert result == {
        "status": "failed",
        "failure_stage": "gopay_wallet_rate_limited",
        "register_status": "success",
        "bind_status": "failed",
        "message": "rate limited",
        "screenshot_paths": [],
        "auto_register_results": [
            {"status": "success", "email_used": "done@example.com"},
            {
                "status": "failed",
                "failure_stage": "gopay_wallet_rate_limited",
                "register_status": "success",
                "bind_status": "failed",
                "message": "rate limited",
                "screenshot_paths": [],
                "email_used": "new@example.com",
                "auto_register_index": 2,
                "auto_register_total": 5,
            },
        ],
        "auto_register_count": 5,
        "auto_register_attempted": 2,
        "registered_emails": ["new@example.com"],
        "successful_emails": ["done@example.com"],
        "failed_emails": [
            {"email": "old@example.com", "failure_stage": "old", "message": "old"},
            {
                "email": "new@example.com",
                "failure_stage": "gopay_wallet_rate_limited",
                "message": "rate limited",
                "register_status": "success",
                "bind_status": "failed",
            },
        ],
        "bind_failed_emails": [
            {"email": "old@example.com", "failure_stage": "old", "message": "old"},
            {
                "email": "new@example.com",
                "failure_stage": "gopay_wallet_rate_limited",
                "message": "rate limited",
            },
        ],
        "pending_retry_emails": ["retry@example.com"],
        "retried_emails": ["retried@example.com"],
        "rejected_emails": ["reject@example.com"],
        "payment_failed_emails": ["pay@example.com"],
        "nonzero_blocked_emails": ["blocked@example.com"],
        "blocked_emails": ["guard@example.com"],
        "email_used": "new@example.com",
    }
    assert aggregate_results == [{"status": "success", "email_used": "done@example.com"}]
    assert failed_emails == [{"email": "old@example.com", "failure_stage": "old", "message": "old"}]
    assert bind_failed_emails == [{"email": "old@example.com", "failure_stage": "old", "message": "old"}]


def test_gopay_auto_register_rate_limited_result_without_email_is_stable():
    aggregate_results = [{"status": "success", "email_used": "done@example.com"}]

    result = gopay_task_payloads.gopay_auto_register_rate_limited_result(
        failed_email="",
        fallback_email="fallback@example.com",
        current=2,
        total=5,
        message="rate limited",
        auto_register_results=aggregate_results,
        registered_emails=[],
        successful_emails=[],
        failed_emails=[],
        bind_failed_emails=[],
        pending_retry_emails=[],
        retried_emails=[],
        rejected_emails=[],
        payment_failed_emails=[],
        nonzero_blocked_emails=[],
        blocked_emails=[],
    )

    assert result["register_status"] == "failed"
    assert result["bind_status"] == "not_started"
    assert result["auto_register_results"] is aggregate_results
    assert result["failed_emails"] == []
    assert result["bind_failed_emails"] == []
    assert result["email_used"] == "fallback@example.com"


def test_gopay_auto_register_bind_failure_result_is_stable():
    result = gopay_task_payloads.gopay_auto_register_bind_failure_result(
        error=RuntimeError("browser crashed")
    )

    assert result == {
        "status": "failed",
        "failure_stage": "post_submit",
        "register_status": "success",
        "bind_status": "failed",
        "message": "注册已成功，GoPay 绑定异常: browser crashed",
        "screenshot_paths": [],
    }


def test_gopay_parallel_task_progress_payloads_are_stable():
    started = gopay_task_payloads.gopay_parallel_started_progress(total=5, concurrency=2)
    account = gopay_task_payloads.gopay_parallel_account_progress(
        email="user@example.com",
        current=2,
        total=5,
        retry_round=0,
        max_retry_rounds=3,
        worker_fields={"worker": "worker-1", "worker_index": 1},
    )
    retry_account = gopay_task_payloads.gopay_parallel_account_progress(
        email="user@example.com",
        current=2,
        total=5,
        retry_round=1,
        max_retry_rounds=3,
    )
    added = gopay_task_payloads.gopay_runtime_accounts_added_progress(
        added=2,
        added_emails=["a@example.com", "b@example.com"],
        pending=4,
        total=6,
    )
    cancelled = gopay_task_payloads.gopay_parallel_cancelled_progress(active=1, pending=3)

    assert started == {
        "stage": "gopay_parallel_started",
        "total": 5,
        "concurrency": 2,
        "message": "开始并发 GoPay 自动钱包绑定：5 个账号，并发 2",
    }
    assert account == {
        "stage": "gopay_parallel_account",
        "email": "user@example.com",
        "attempt": 2,
        "total": 5,
        "retry_round": 0,
        "max_retry_rounds": 3,
        "message": "并发处理 GoPay 账号: user@example.com (2/5)",
        "worker": "worker-1",
        "worker_index": 1,
    }
    assert retry_account["message"] == "并发处理 GoPay 待重试第 1/3 轮: user@example.com (2/5)"
    assert added == {
        "stage": "gopay_runtime_accounts_added",
        "added": 2,
        "added_emails": ["a@example.com", "b@example.com"],
        "pending": 4,
        "total": 6,
        "message": "已追加 2 个 GoPay 待处理账号，后续空闲并发会继续处理",
        "level": "success",
    }
    assert cancelled == {
        "stage": "gopay_parallel_cancelled",
        "active": 1,
        "pending": 3,
        "message": "GoPay 并发任务已停止提交新账号，正在释放未开始的后台步骤",
    }


def test_gopay_oauth_success_followup_progress_payloads_are_stable():
    successful_emails = ["first@example.com"]
    fields = gopay_task_payloads.gopay_success_progress_fields(successful_emails)
    skipped = gopay_task_payloads.gopay_oauth_login_skipped_progress(
        success_email="second@example.com",
        successful_emails=successful_emails,
    )
    started = gopay_task_payloads.gopay_oauth_login_started_progress(
        success_email="second@example.com"
    )
    proxy = gopay_task_payloads.gopay_oauth_proxy_selected_progress(
        success_email="second@example.com",
        proxy_label="pool-a",
    )
    done = gopay_task_payloads.gopay_oauth_login_done_progress(
        success_email="second@example.com",
        auth_file="data/auths/second.json",
        attempt=2,
        max_attempts=3,
    )
    phone_required = gopay_task_payloads.gopay_oauth_phone_required_progress(
        success_email="second@example.com",
        removed_pool_emails=["second@example.com"],
        attempt=1,
        max_attempts=3,
        successful_emails=successful_emails,
        message="需要手机号验证",
    )
    retrying = gopay_task_payloads.gopay_oauth_login_retrying_progress(
        success_email="second@example.com",
        attempt=1,
        max_attempts=3,
        error="temporary",
    )
    failed = gopay_task_payloads.gopay_oauth_login_failed_progress(
        success_email="second@example.com",
        attempt=3,
        max_attempts=3,
        error="final",
    )
    successful_emails.append("mutated@example.com")

    assert fields == {"successful": 1, "successful_emails": ["first@example.com"]}
    assert skipped == {
        "stage": "gopay_oauth_login_skipped",
        "email": "second@example.com",
        "successful": 1,
        "successful_emails": ["first@example.com"],
        "message": "GoPay 绑定成功；未启用 OAuth 补登录，已跳过 CPA 直接转换: second@example.com",
        "level": "success",
    }
    assert started == {
        "stage": "gopay_oauth_login_started",
        "email": "second@example.com",
        "message": "GoPay 绑定成功，已在后台开始 OAuth 补登录: second@example.com",
    }
    assert proxy == {
        "stage": "gopay_oauth_proxy_selected",
        "email": "second@example.com",
        "proxy_label": "pool-a",
        "message": "GoPay 绑定成功后的 OAuth 补登录将复用当前代理",
    }
    assert done == {
        "stage": "gopay_oauth_login_done",
        "email": "second@example.com",
        "auth_file": "data/auths/second.json",
        "attempt": 2,
        "max_attempts": 3,
        "message": "OAuth 补登录成功: second@example.com",
    }
    assert phone_required == {
        "stage": "gopay_oauth_phone_required",
        "email": "second@example.com",
        "removed_pool_emails": ["second@example.com"],
        "attempt": 1,
        "max_attempts": 3,
        "successful": 1,
        "successful_emails": ["first@example.com"],
        "message": "需要手机号验证",
        "level": "warn",
    }
    assert retrying == {
        "stage": "gopay_oauth_login_retrying",
        "email": "second@example.com",
        "attempt": 1,
        "next_attempt": 2,
        "max_attempts": 3,
        "message": "OAuth 补登录失败，准备重试 2/3: second@example.com: temporary",
        "level": "warn",
    }
    assert failed == {
        "stage": "gopay_oauth_login_failed",
        "email": "second@example.com",
        "attempt": 3,
        "max_attempts": 3,
        "message": "OAuth 补登录失败: second@example.com: final",
    }


def test_gopay_oauth_failure_records_and_thread_name_are_stable():
    removed_pool_emails = ["second@example.com"]

    phone_required = gopay_task_payloads.gopay_oauth_phone_required_failure_record(
        success_email="second@example.com",
        error=RuntimeError("需要手机号验证"),
        removed_pool_emails=removed_pool_emails,
    )
    failed = gopay_task_payloads.gopay_oauth_failed_record(
        success_email="second@example.com",
        error=RuntimeError("final oauth failure"),
        attempts=3,
    )
    thread_name = gopay_task_payloads.gopay_oauth_thread_name(
        "abcdefghijklmnopqrstuvwxyz@example.com"
    )
    removed_pool_emails.append("mutated@example.com")

    assert phone_required == {
        "email": "second@example.com",
        "error": "需要手机号验证",
        "failure_stage": "oauth_phone_required",
        "removed_pool_emails": ["second@example.com"],
    }
    assert failed == {
        "email": "second@example.com",
        "error": "final oauth failure",
        "attempts": 3,
    }
    assert thread_name == "gopay-oauth-abcdefghijklmnopqrstuvwx"
