from autotoken.services import gopay_pending_retry


def test_pending_retry_attempts_and_wait_seconds_are_bounded():
    assert gopay_pending_retry.normalize_pending_retry_attempts(None) == 1
    assert gopay_pending_retry.normalize_pending_retry_attempts("bad") == 1
    assert gopay_pending_retry.normalize_pending_retry_attempts(-1) == 0
    assert gopay_pending_retry.normalize_pending_retry_attempts(9) == 3
    assert gopay_pending_retry.normalize_pending_retry_attempts(2) == 2

    assert gopay_pending_retry.pending_retry_wait_seconds(1) == 60.0
    assert gopay_pending_retry.pending_retry_wait_seconds(2) == 180.0
    assert gopay_pending_retry.pending_retry_wait_seconds(3) == 300.0
    assert gopay_pending_retry.pending_retry_wait_seconds(99) == 300.0
    assert gopay_pending_retry.pending_retry_wait_seconds(2, gopay_pending_retry.DEFAULT_TASK_PENDING_RETRY_BACKOFFS) == 120.0
    assert gopay_pending_retry.pending_retry_wait_seconds(99, gopay_pending_retry.DEFAULT_TASK_PENDING_RETRY_BACKOFFS) == 120.0
    assert gopay_pending_retry.pending_retry_wait_seconds("bad", (5.0, 10.0)) == 5.0
    assert gopay_pending_retry.pending_retry_wait_seconds(1, ()) == 0.0


def test_pending_retry_item_keeps_required_fields_and_optional_context():
    wallet = object()

    basic = gopay_pending_retry.pending_retry_item(
        email="user@example.com",
        index=2,
        reason="fetch_otp",
    )
    detailed = gopay_pending_retry.pending_retry_item(
        email="user@example.com",
        index=3,
        reason="fetch_otp",
        phone_accounts=[{"phone_number": "87761973970"}],
        retry_round=1,
        source_stage="fetch_otp",
        failure_stage="fetch_otp",
        message="OTP timeout",
        wallet=wallet,
    )

    assert basic == {
        "email": "user@example.com",
        "index": 2,
        "reason": "fetch_otp",
    }
    assert detailed["phone_accounts"] == [{"phone_number": "87761973970"}]
    assert detailed["retry_round"] == 1
    assert detailed["source_stage"] == "fetch_otp"
    assert detailed["failure_stage"] == "fetch_otp"
    assert detailed["message"] == "OTP timeout"
    assert detailed["wallet"] is wallet


def test_pending_retry_queued_progress_preserves_auto_register_and_parallel_shapes():
    auto_register = gopay_pending_retry.pending_retry_queued_progress(
        email="user@example.com",
        current=1,
        total=2,
        reason="fetch_otp",
        source_stage="fetch_otp",
        retry_round=1,
        source_retry_round=0,
        max_retry_rounds=2,
        pending_retry=1,
        message="自动注册账号加入待重试: user@example.com",
    )
    parallel = gopay_pending_retry.pending_retry_queued_progress(
        email="user@example.com",
        retry_round=2,
        source_retry_round=1,
        max_retry_rounds=2,
        reason="fetch_otp",
        source_stage="fetch_otp",
        failure_stage="fetch_otp",
        reuse_wallet=True,
        pending_retry=3,
        detail="OTP timeout",
        message="GoPay 并发账号失败，已加入待重试池: user@example.com",
    )

    assert auto_register["stage"] == "gopay_pending_retry_queued"
    assert auto_register["current"] == 1
    assert auto_register["total"] == 2
    assert auto_register["level"] == "warn"
    assert parallel["reuse_wallet"] is True
    assert parallel["failure_stage"] == "fetch_otp"
    assert parallel["detail"] == "OTP timeout"


def test_auto_register_pending_retry_queued_progress_builds_round_messages():
    first_round = gopay_pending_retry.auto_register_pending_retry_queued_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=1,
        source_retry_round=0,
        max_retry_rounds=2,
        reason="fetch_otp",
        pending_retry=1,
        source_stage="fetch_otp",
    )
    next_round = gopay_pending_retry.auto_register_pending_retry_queued_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=2,
        source_retry_round=1,
        max_retry_rounds=2,
        reason="fetch_otp",
        pending_retry=1,
    )

    assert first_round["message"] == "自动注册账号加入待重试: user@example.com"
    assert first_round["source_stage"] == "fetch_otp"
    assert next_round["message"] == "自动注册账号继续加入下一轮待重试: user@example.com"
    assert "source_stage" not in next_round


def test_pending_retry_wait_started_and_account_progress_payloads():
    wait = gopay_pending_retry.pending_retry_wait_progress(
        email="user@example.com",
        retry_round=1,
        max_retry_rounds=2,
        delay_seconds=60.0,
        pending_retry=2,
        message="wait",
    )
    started = gopay_pending_retry.pending_retry_started_progress(
        email="user@example.com",
        retry_round=1,
        max_retry_rounds=2,
        pending_retry=2,
        concurrency=3,
        message="started",
    )
    account = gopay_pending_retry.pending_retry_account_progress(
        email="user@example.com",
        attempt=1,
        total=2,
        current=3,
        auto_register_total=4,
        retry_round=1,
        max_retry_rounds=2,
        pending_retry=1,
        message="account",
    )

    assert wait == {
        "stage": "gopay_pending_retry_wait",
        "retry_round": 1,
        "max_retry_rounds": 2,
        "pending_retry": 2,
        "delay_seconds": 60.0,
        "message": "wait",
        "email": "user@example.com",
    }
    assert started["stage"] == "gopay_pending_retry_started"
    assert started["email"] == "user@example.com"
    assert started["concurrency"] == 3
    assert account["stage"] == "gopay_pending_retry_account"
    assert account["auto_register_total"] == 4
    assert account["pending_retry"] == 1


def test_pending_retry_progress_builds_default_messages():
    wait = gopay_pending_retry.pending_retry_wait_progress(
        retry_round=2,
        max_retry_rounds=3,
        delay_seconds=180.0,
        pending_retry=4,
    )
    started = gopay_pending_retry.pending_retry_started_progress(
        retry_round=2,
        max_retry_rounds=3,
        pending_retry=4,
    )
    account = gopay_pending_retry.pending_retry_account_progress(
        email="user@example.com",
        retry_round=2,
        max_retry_rounds=3,
    )

    assert wait["message"] == "待重试第 2/3 轮将在 180s 后开始"
    assert started["message"] == "开始第 2/3 轮待重试，共 4 个账号"
    assert account["message"] == "正在执行第 2/3 轮待重试: user@example.com"


def test_auto_register_pending_retry_progress_builds_stable_messages():
    wait = gopay_pending_retry.auto_register_pending_retry_wait_progress(
        retry_round=2,
        max_retry_rounds=3,
        delay_seconds=120.0,
        pending_retry=4,
    )
    started = gopay_pending_retry.auto_register_pending_retry_started_progress(
        retry_round=2,
        max_retry_rounds=3,
        pending_retry=4,
    )
    account = gopay_pending_retry.auto_register_pending_retry_account_progress(
        email="user@example.com",
        attempt=2,
        total=4,
        current=7,
        auto_register_total=10,
        retry_round=2,
        max_retry_rounds=3,
        pending_retry=1,
    )

    assert wait["stage"] == "gopay_pending_retry_wait"
    assert wait["message"] == "自动注册待重试第 2/3 轮将在 120s 后开始"
    assert started["message"] == "开始自动注册待重试第 2/3 轮，共 4 个账号"
    assert account["message"] == "正在执行自动注册待重试第 2/3 轮: user@example.com (2/4)"
    assert account["current"] == 7
    assert account["auto_register_total"] == 10
    assert account["pending_retry"] == 1


def test_auto_register_pending_retry_exception_result_preserves_successful_register_shape():
    payload = gopay_pending_retry.auto_register_pending_retry_exception_result(RuntimeError("network down"))

    assert payload == {
        "status": "failed",
        "failure_stage": "post_submit",
        "register_status": "success",
        "bind_status": "failed",
        "message": "注册已成功，GoPay 待重试异常: network down",
        "screenshot_paths": [],
    }


def test_auto_register_pending_retry_failed_progress_uses_default_message():
    failed = gopay_pending_retry.auto_register_pending_retry_failed_progress(
        email="user@example.com",
        current=2,
        total=4,
        retry_round=1,
        max_retry_rounds=3,
        result={"failure_stage": "post_submit", "register_status": "success", "bind_status": "failed"},
    )
    explicit = gopay_pending_retry.auto_register_pending_retry_failed_progress(
        email="user@example.com",
        current=2,
        total=4,
        retry_round=1,
        max_retry_rounds=3,
        result={"failure_stage": "fetch_otp", "message": "OTP timeout"},
    )

    assert failed == {
        "stage": "gopay_pending_retry_failed",
        "email": "user@example.com",
        "current": 2,
        "total": 4,
        "retry_round": 1,
        "max_retry_rounds": 3,
        "failure_stage": "post_submit",
        "register_status": "success",
        "bind_status": "failed",
        "message": "自动注册 GoPay 待重试失败",
        "level": "error",
    }
    assert explicit["message"] == "OTP timeout"


def test_parallel_pending_retry_progress_builds_stable_messages():
    wait_single = gopay_pending_retry.parallel_pending_retry_wait_progress(
        email="user@example.com",
        retry_round=2,
        max_retry_rounds=3,
        delay_seconds=120.0,
        pending_retry=4,
    )
    wait_batch = gopay_pending_retry.parallel_pending_retry_wait_progress(
        retry_round=2,
        max_retry_rounds=3,
        delay_seconds=120.0,
        pending_retry=4,
    )
    started_single = gopay_pending_retry.parallel_pending_retry_started_progress(
        email="user@example.com",
        retry_round=2,
        max_retry_rounds=3,
        pending_retry=4,
        concurrency=2,
    )
    started_batch = gopay_pending_retry.parallel_pending_retry_started_progress(
        retry_round=2,
        max_retry_rounds=3,
        pending_retry=4,
        concurrency=2,
    )

    assert wait_single["message"] == "GoPay 并发待重试第 2/3 轮将在 120s 后开始: user@example.com"
    assert wait_single["email"] == "user@example.com"
    assert wait_batch["message"] == "GoPay 并发待重试第 2/3 轮将在 120s 后开始"
    assert "email" not in wait_batch
    assert started_single["message"] == "开始并发 GoPay 待重试第 2/3 轮: user@example.com"
    assert started_single["concurrency"] == 2
    assert started_batch["message"] == "开始并发 GoPay 待重试第 2/3 轮，共 4 个账号，并发 2"


def test_parallel_pending_retry_queued_progress_builds_failure_shape():
    payload = gopay_pending_retry.parallel_pending_retry_queued_progress(
        email="user@example.com",
        retry_round=2,
        source_retry_round=1,
        max_retry_rounds=3,
        reason="gopay_payment_process",
        source_stage="gopay_payment_process_failed_rotate",
        failure_stage="gopay_payment_process",
        reuse_wallet=True,
        pending_retry=4,
        detail="payment switch denied",
    )

    assert payload == {
        "stage": "gopay_pending_retry_queued",
        "email": "user@example.com",
        "retry_round": 2,
        "source_retry_round": 1,
        "max_retry_rounds": 3,
        "reason": "gopay_payment_process",
        "pending_retry": 4,
        "message": "GoPay 并发账号失败，已加入待重试池: user@example.com",
        "level": "warn",
        "source_stage": "gopay_payment_process_failed_rotate",
        "failure_stage": "gopay_payment_process",
        "reuse_wallet": True,
        "detail": "payment switch denied",
    }


def test_pending_retry_failed_progress_uses_result_fields_and_default_message():
    failed = gopay_pending_retry.pending_retry_failed_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=1,
        max_retry_rounds=2,
        result={
            "failure_stage": "fetch_otp",
            "register_status": "success",
            "bind_status": "failed",
            "message": "OTP timeout",
        },
        default_message="fallback",
    )
    fallback = gopay_pending_retry.pending_retry_failed_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=1,
        max_retry_rounds=2,
        result={},
        default_message="fallback",
    )

    assert failed == {
        "stage": "gopay_pending_retry_failed",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "retry_round": 1,
        "max_retry_rounds": 2,
        "failure_stage": "fetch_otp",
        "register_status": "success",
        "bind_status": "failed",
        "message": "OTP timeout",
        "level": "error",
    }
    assert fallback["message"] == "fallback"
    assert fallback["failure_stage"] == ""


def test_pending_retry_failed_progress_can_preserve_executor_shape():
    payload = gopay_pending_retry.pending_retry_failed_progress(
        email="user@example.com",
        retry_round=2,
        max_retry_rounds=3,
        result={"failure_stage": "post_submit", "message": "HTTP 403"},
        reason="http_403",
        default_message="fallback",
        include_register_bind_status=False,
    )

    assert payload == {
        "stage": "gopay_pending_retry_failed",
        "email": "user@example.com",
        "retry_round": 2,
        "max_retry_rounds": 3,
        "failure_stage": "post_submit",
        "message": "HTTP 403",
        "level": "error",
        "reason": "http_403",
    }
