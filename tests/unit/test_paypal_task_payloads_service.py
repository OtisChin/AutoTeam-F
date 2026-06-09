from types import SimpleNamespace

from autotoken.services import paypal_task_payloads


def _params(**overrides):
    values = {
        "proxy_url": "socks5://proxy.example:1080",
        "proxy_label": "pool-a",
        "proxy_bypass": "localhost",
        "manual_confirm": False,
        "paypal_email": "paypal@example.com",
        "paypal_password": "secret",
        "paypal_card_number": "4111111111111111",
        "paypal_card_expiry": "12/30",
        "paypal_card_cvv": "123",
        "autofill_enabled": True,
        "billing_name": "User Example",
        "billing_email": "",
        "billing_phone": "+15550000001",
        "billing_country": "US",
        "billing_state": "CA",
        "billing_city": "San Francisco",
        "billing_zip": "94105",
        "billing_address1": "1 Market St",
        "billing_address2": "Suite 1",
        "timeout_seconds": 0,
        "auto_oauth_after_success": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_build_paypal_task_payload_preserves_public_task_snapshot_fields():
    params = _params(timeout_seconds=45)

    payload = paypal_task_payloads.build_paypal_task_payload(
        params=params,
        email="user@example.com",
        account_emails=["user@example.com", "other@example.com"],
        checkout_url="https://pay.openai.com/demo",
        bind_link_payload={"plan_name": "chatgptplusplan"},
        proxy_pool_count=2,
        proxy_api_url="https://api.proxy.example",
        proxy_api_provider="cliproxy",
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        roxybrowser_auto_create_profile=True,
        paypal_browser="protocol",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja-JP",
        paypal_region="JP",
        paypal_fallback_browser="chromium",
        sms_url="https://sms.example",
        otp_channel="sms",
        phone_account_count=3,
        pending_retry_attempts=2,
        paypal_concurrency=4,
    )

    assert payload["runner_mode"] == "manual_checkout"
    assert payload["email"] == "user@example.com"
    assert payload["account_emails"] == ["user@example.com", "other@example.com"]
    assert payload["proxy_pool_count"] == 2
    assert payload["proxy_api_url_present"] is True
    assert payload["proxy_api_provider"] == "cliproxy"
    assert payload["roxybrowser_auto_create_profile"] is True
    assert payload["manual_confirm"] is False
    assert payload["paypal_browser"] == "protocol"
    assert payload["paypal_region"] == "JP"
    assert payload["paypal_fallback_browser"] == "chromium"
    assert payload["sms_url_present"] is True
    assert payload["phone_account_count"] == 3
    assert payload["paypal_card_number_present"] is True
    assert payload["paypal_card_expiry_present"] is True
    assert payload["paypal_card_cvv_present"] is True
    assert payload["paypal_auto_login"] is True
    assert payload["timeout_seconds"] == 45
    assert payload["auto_oauth_after_success"] is True
    assert payload["pending_retry_attempts"] == 2
    assert payload["paypal_concurrency"] == 4


def test_build_paypal_task_payload_omits_optional_empty_fields_and_defaults_timeout():
    params = _params(
        paypal_password="",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
        manual_confirm=True,
    )

    payload = paypal_task_payloads.build_paypal_task_payload(
        params=params,
        email="user@example.com",
        account_emails=["user@example.com"],
        checkout_url="",
        bind_link_payload=None,
        proxy_pool_count=0,
        proxy_api_url="",
        proxy_api_provider="",
        roxybrowser_workspace_id="",
        roxybrowser_profile_id="",
        roxybrowser_auto_create_profile=False,
        paypal_browser="chromium",
        paypal_mode="existing_account",
        paypal_country="US",
        paypal_lang="en-US",
        paypal_region="",
        paypal_fallback_browser="",
        sms_url="",
        otp_channel="sms",
        phone_account_count=0,
        pending_retry_attempts=0,
        paypal_concurrency=1,
    )

    assert payload["proxy_api_url_present"] is False
    assert "proxy_api_provider" not in payload
    assert "paypal_region" not in payload
    assert "paypal_fallback_browser" not in payload
    assert payload["paypal_card_number_present"] is False
    assert payload["paypal_card_expiry_present"] is False
    assert payload["paypal_card_cvv_present"] is False
    assert payload["paypal_auto_login"] is False
    assert payload["timeout_seconds"] == 60


def test_paypal_autofill_payload_uses_billing_email_then_candidate_fallback():
    params = _params(billing_email="")
    base = paypal_task_payloads.build_paypal_autofill_payload(params=params, email="primary@example.com")

    assert base["email"] == "primary@example.com"
    assert base["phone"] == "+15550000001"
    assert base["card_number"] == "4111111111111111"

    candidate = paypal_task_payloads.paypal_candidate_autofill_payload(
        base,
        candidate_email="candidate@example.com",
        billing_email="",
    )
    fixed = paypal_task_payloads.paypal_candidate_autofill_payload(
        base,
        candidate_email="candidate@example.com",
        billing_email="billing@example.com",
    )

    assert candidate["email"] == "candidate@example.com"
    assert fixed["email"] == "billing@example.com"
    assert base["email"] == "primary@example.com"


def test_paypal_worker_start_and_checkout_payload_helpers_are_stable():
    proxy_error = RuntimeError("proxy unavailable")
    candidate_failure = paypal_task_payloads.paypal_proxy_api_failed_candidate_result(
        email="candidate@example.com",
        current=2,
        retry_round=1,
        error=proxy_error,
    )
    serial_failure = paypal_task_payloads.paypal_proxy_api_failed_result(
        email="candidate@example.com",
        error=proxy_error,
    )
    parallel_start = paypal_task_payloads.paypal_starting_progress(
        email="candidate@example.com",
        current=2,
        total=3,
        proxy_label="pool-a",
        retry_round=1,
        concurrency=4,
    )
    serial_start = paypal_task_payloads.paypal_starting_progress(
        email="candidate@example.com",
        current=1,
        total=1,
        proxy_label="pool-a",
    )

    assert serial_failure == {
        "status": "failed",
        "failure_stage": "proxy_api",
        "message": "动态代理 API 获取失败: proxy unavailable",
        "screenshot_paths": [],
        "email": "candidate@example.com",
    }
    assert candidate_failure == {
        "email": "candidate@example.com",
        "index": 2,
        "retry_round": 1,
        "selected_proxy_url": "",
        "current_candidate_phone": "",
        "result": serial_failure,
    }
    assert parallel_start == {
        "stage": "paypal_starting",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "proxy_label": "pool-a",
        "message": "PayPal 批量任务启动中 (2/3): candidate@example.com",
        "retry_round": 1,
        "concurrency": 4,
    }
    assert serial_start == {
        "stage": "paypal_starting",
        "email": "candidate@example.com",
        "current": 1,
        "total": 1,
        "proxy_label": "pool-a",
        "message": "PayPal 任务启动中",
    }


def test_paypal_checkout_payload_helpers_are_stable():
    missing_token = paypal_task_payloads.paypal_missing_checkout_access_token_result(
        email="candidate@example.com"
    )
    checkout_failed = paypal_task_payloads.paypal_checkout_failed_result(
        email="candidate@example.com",
        message="checkout unavailable",
    )
    candidate_exception = paypal_task_payloads.paypal_candidate_exception_result(
        email="candidate@example.com",
        error=RuntimeError("browser crashed"),
    )
    token_refreshed = paypal_task_payloads.paypal_checkout_token_refreshed_progress(
        email="candidate@example.com",
        current=2,
        total=3,
    )
    fallback = paypal_task_payloads.paypal_checkout_browser_fallback_progress(
        email="candidate@example.com",
        current=2,
        total=3,
        retry_round=1,
    )
    generated = paypal_task_payloads.paypal_checkout_generated_progress(
        email="candidate@example.com",
        current=2,
        total=3,
        checkout_url="https://checkout.example",
        retry_round=1,
    )
    browser_generated = paypal_task_payloads.paypal_checkout_browser_generated_progress(
        email="candidate@example.com",
        current=2,
        total=3,
    )

    assert missing_token == {
        "status": "failed",
        "failure_stage": "generate_checkout",
        "message": "账号缺少可用 access_token，无法自动生成 checkout 链接: candidate@example.com",
        "screenshot_paths": [],
        "email": "candidate@example.com",
    }
    assert checkout_failed == {
        "status": "failed",
        "failure_stage": "generate_checkout",
        "message": "checkout unavailable",
        "screenshot_paths": [],
        "email": "candidate@example.com",
    }
    assert candidate_exception == {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": "PayPal 账号执行异常: browser crashed",
        "screenshot_paths": [],
        "email": "candidate@example.com",
    }
    assert token_refreshed == {
        "stage": "paypal_checkout_token_refreshed",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "message": "生成 checkout 返回 401，已刷新 access_token 并重试: candidate@example.com",
    }
    assert fallback == {
        "stage": "paypal_checkout_browser_fallback",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "message": "HTTP 生成 checkout 失败，改用浏览器登录态回退: candidate@example.com",
        "level": "warn",
        "retry_round": 1,
    }
    assert generated == {
        "stage": "paypal_checkout_generated",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "checkout_url": "https://checkout.example",
        "message": "已生成 checkout 链接 (2/3): candidate@example.com",
        "retry_round": 1,
    }
    assert browser_generated == {
        "stage": "paypal_checkout_browser_generated",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "message": "浏览器登录态已生成 checkout 链接 (2/3): candidate@example.com",
    }


def test_paypal_phone_pool_exhausted_payload_helpers_are_stable():
    concurrent_progress = paypal_task_payloads.paypal_phone_pool_exhausted_progress(
        email="candidate@example.com",
        current=2,
        total=3,
        retry_round=1,
        reserved_phone_count=2,
        invalid_phone_count=4,
        message="手机号池没有未占用的可用号码，当前账号不会启动浏览器（本任务已占用 2 个，已失效 4 个）",
        level="warn",
    )
    serial_progress = paypal_task_payloads.paypal_phone_pool_exhausted_progress(
        email="candidate@example.com",
        current=1,
        total=1,
        message="手机号池已无可用号码，停止后续 PayPal 绑定任务",
        level="error",
    )
    result = paypal_task_payloads.paypal_phone_pool_exhausted_result(
        email="candidate@example.com",
        message="手机号池已无可用号码",
    )

    assert concurrent_progress == {
        "stage": "paypal_phone_pool_exhausted",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "message": "手机号池没有未占用的可用号码，当前账号不会启动浏览器（本任务已占用 2 个，已失效 4 个）",
        "level": "warn",
        "retry_round": 1,
        "reserved_phone_count": 2,
        "invalid_phone_count": 4,
    }
    assert serial_progress == {
        "stage": "paypal_phone_pool_exhausted",
        "email": "candidate@example.com",
        "current": 1,
        "total": 1,
        "message": "手机号池已无可用号码，停止后续 PayPal 绑定任务",
        "level": "error",
    }
    assert result == {
        "status": "failed",
        "failure_stage": "paypal_phone_pool_exhausted",
        "message": "手机号池已无可用号码",
        "screenshot_paths": [],
        "email": "candidate@example.com",
    }


def test_paypal_task_level_progress_and_exception_payloads_are_stable():
    parallel_started = paypal_task_payloads.paypal_parallel_started_progress(total=3, concurrency=2)
    parallel_retry = paypal_task_payloads.paypal_pending_retry_account_progress(
        email="candidate@example.com",
        current=2,
        total=3,
        retry_round=1,
        max_retry_rounds=2,
        pending_retry=1,
        concurrency=2,
    )
    serial_retry = paypal_task_payloads.paypal_pending_retry_account_progress(
        email="candidate@example.com",
        current=2,
        total=3,
        retry_round=1,
        max_retry_rounds=2,
        pending_retry=1,
    )
    exception_result = paypal_task_payloads.paypal_task_exception_result(
        error=RuntimeError("task crashed")
    )

    assert parallel_started == {
        "stage": "paypal_parallel_started",
        "total": 3,
        "concurrency": 2,
        "message": "开始并发 PayPal 绑定：3 个账号，并发 2",
    }
    assert parallel_retry == {
        "stage": "paypal_pending_retry_account",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "retry_round": 1,
        "max_retry_rounds": 2,
        "pending_retry": 1,
        "message": "正在并发执行 PayPal 待重试第 1/2 轮: candidate@example.com",
        "concurrency": 2,
    }
    assert serial_retry == {
        "stage": "paypal_pending_retry_account",
        "email": "candidate@example.com",
        "current": 2,
        "total": 3,
        "retry_round": 1,
        "max_retry_rounds": 2,
        "pending_retry": 1,
        "message": "正在执行 PayPal 待重试第 1/2 轮: candidate@example.com",
    }
    assert exception_result == {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": "PayPal 任务执行异常: task crashed",
        "screenshot_paths": [],
    }


def test_paypal_success_account_and_candidate_result_helpers_are_stable():
    assert paypal_task_payloads.paypal_success_account_update_fields() == {
        "status": "active",
        "account_type": "plus",
        "seat_type": "codex",
        "account_source": "managed",
        "last_bind_provider": "paypal",
    }

    normalized = paypal_task_payloads.normalize_paypal_candidate_result(
        single_result={"status": "failed", "checkout_url": "https://returned.example"},
        candidate_email="candidate@example.com",
        effective_checkout_url="https://effective.example",
    )
    fallback = paypal_task_payloads.normalize_paypal_candidate_result(
        single_result={"status": "failed", "checkout_url": "https://returned.example"},
        candidate_email="candidate@example.com",
        effective_checkout_url="",
    )

    assert normalized["email"] == "candidate@example.com"
    assert normalized["checkout_url"] == "https://effective.example"
    assert fallback["checkout_url"] == "https://returned.example"


def test_paypal_candidate_phone_rejection_update_attaches_invalid_pool_copy():
    original = {"failure_stage": "paypal_phone_rejected", "rejected_phone": "+15550000001"}
    invalid_phone_pool = ["+15550000001"]

    rejected_phone, updated = paypal_task_payloads.paypal_candidate_phone_rejection_update(
        single_result=original,
        current_candidate_phone="+15550000002",
        invalid_phone_pool=invalid_phone_pool,
    )
    ignored_phone, ignored = paypal_task_payloads.paypal_candidate_phone_rejection_update(
        single_result={"failure_stage": "other"},
        current_candidate_phone="+15550000002",
        invalid_phone_pool=invalid_phone_pool,
    )

    invalid_phone_pool.append("+15550000003")

    assert rejected_phone == "+15550000001"
    assert updated["invalid_phone_numbers"] == ["+15550000001"]
    assert "invalid_phone_numbers" not in original
    assert ignored_phone is None
    assert ignored == {"failure_stage": "other"}


def test_paypal_candidate_outcome_flags_classify_success_failure_and_nonzero():
    success = paypal_task_payloads.paypal_candidate_outcome_flags(
        single_result={"status": "success"},
        candidate_email="user@example.com",
        nonzero_blocked_pool_emails=["user@example.com"],
    )
    failed = paypal_task_payloads.paypal_candidate_outcome_flags(
        single_result={"status": "failed"},
        candidate_email="user@example.com",
        nonzero_blocked_pool_emails=[],
    )
    nonzero = paypal_task_payloads.paypal_candidate_outcome_flags(
        single_result={"status": "failed", "failure_stage": "browser_charge_guard"},
        candidate_email="user@example.com",
        nonzero_blocked_pool_emails=["user@example.com"],
    )

    assert success == {"success": True, "failed": False, "nonzero_blocked": False}
    assert failed == {"success": False, "failed": True, "nonzero_blocked": False}
    assert nonzero == {"success": False, "failed": True, "nonzero_blocked": True}


def test_paypal_success_persistence_warning_needed_only_for_unpersisted_success():
    assert paypal_task_payloads.paypal_success_persistence_warning_needed(
        single_result={"status": "success"},
        updated_account=None,
    )
    assert not paypal_task_payloads.paypal_success_persistence_warning_needed(
        single_result={"status": "success"},
        updated_account={"email": "user@example.com"},
    )
    assert not paypal_task_payloads.paypal_success_persistence_warning_needed(
        single_result={"status": "failed"},
        updated_account=None,
    )


def test_paypal_success_plan_update_helpers_preserve_account_mutation_contract():
    account = {"email": "user@example.com"}
    request = paypal_task_payloads.paypal_success_plan_update_request(
        candidate_email="user@example.com",
        updated_account=account,
        plan_type="plus",
    )
    missing_account_request = paypal_task_payloads.paypal_success_plan_update_request(
        candidate_email="user@example.com",
        updated_account=None,
        plan_type="plus",
    )

    returned = paypal_task_payloads.apply_paypal_success_plan_update(
        updated_account=account,
        plan_update={"auth_file": "data/auth/user.json"},
    )
    ignored = paypal_task_payloads.apply_paypal_success_plan_update(
        updated_account=None,
        plan_update={"auth_file": "data/auth/user.json"},
    )

    assert request == {"email": "user@example.com", "account": account, "plan_type": "plus"}
    assert missing_account_request == {"email": "user@example.com", "account": None, "plan_type": "plus"}
    assert returned is account
    assert account["auth_file"] == "data/auth/user.json"
    assert ignored is None


def test_paypal_oauth_success_followup_progress_payloads_are_stable():
    successful_emails = ["first@example.com"]
    fields = paypal_task_payloads.paypal_success_progress_fields(successful_emails)
    skipped = paypal_task_payloads.paypal_oauth_login_skipped_progress(
        success_email="second@example.com",
        successful_emails=successful_emails,
    )
    started = paypal_task_payloads.paypal_oauth_login_started_progress(
        success_email="second@example.com",
        successful_emails=successful_emails,
    )
    proxy = paypal_task_payloads.paypal_oauth_proxy_selected_progress(
        success_email="second@example.com",
        proxy_label="proxy-a",
        proxy_api_provider="cliproxy",
    )
    done = paypal_task_payloads.paypal_oauth_login_done_progress(
        success_email="second@example.com",
        auth_file="data/auths/second.json",
        attempt=2,
        max_attempts=3,
        successful_emails=successful_emails,
    )
    phone_required = paypal_task_payloads.paypal_oauth_phone_required_progress(
        success_email="second@example.com",
        removed_pool_emails=["second@example.com"],
        attempt=1,
        max_attempts=3,
        successful_emails=successful_emails,
        message="需要手机号验证",
    )
    retrying = paypal_task_payloads.paypal_oauth_login_retrying_progress(
        success_email="second@example.com",
        attempt=1,
        max_attempts=3,
        successful_emails=successful_emails,
        error="temporary",
    )
    failed = paypal_task_payloads.paypal_oauth_login_failed_progress(
        success_email="second@example.com",
        attempt=3,
        max_attempts=3,
        successful_emails=successful_emails,
        error="final",
    )
    successful_emails.append("mutated@example.com")

    assert fields == {"successful": 1, "successful_emails": ["first@example.com"]}
    assert skipped == {
        "stage": "paypal_oauth_login_skipped",
        "email": "second@example.com",
        "successful": 1,
        "successful_emails": ["first@example.com"],
        "message": "PayPal 绑定成功；未启用 OAuth 补登录，已跳过 CPA 直接转换: second@example.com",
        "level": "success",
    }
    assert started == {
        "stage": "paypal_oauth_login_started",
        "email": "second@example.com",
        "successful": 1,
        "successful_emails": ["first@example.com"],
        "message": "PayPal 绑定成功，已在后台开始 OAuth 补登录: second@example.com",
    }
    assert proxy == {
        "stage": "paypal_oauth_proxy_selected",
        "email": "second@example.com",
        "proxy_label": "proxy-a",
        "proxy_api_provider": "cliproxy",
        "message": "PayPal 绑定成功后的 OAuth 补登录将复用当前代理",
    }
    assert done == {
        "stage": "paypal_oauth_login_done",
        "email": "second@example.com",
        "auth_file": "data/auths/second.json",
        "attempt": 2,
        "max_attempts": 3,
        "successful": 1,
        "successful_emails": ["first@example.com"],
        "message": "OAuth 补登录成功: second@example.com",
        "level": "success",
    }
    assert phone_required == {
        "stage": "paypal_oauth_phone_required",
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
        "stage": "paypal_oauth_login_retrying",
        "email": "second@example.com",
        "attempt": 1,
        "next_attempt": 2,
        "max_attempts": 3,
        "successful": 1,
        "successful_emails": ["first@example.com"],
        "message": "OAuth 补登录失败，准备重试 2/3: second@example.com: temporary",
        "level": "warn",
    }
    assert failed == {
        "stage": "paypal_oauth_login_failed",
        "email": "second@example.com",
        "attempt": 3,
        "max_attempts": 3,
        "successful": 1,
        "successful_emails": ["first@example.com"],
        "message": "OAuth 补登录失败: second@example.com: final",
        "level": "error",
    }


def test_paypal_oauth_followup_failure_records_and_thread_name_are_stable():
    removed_pool_emails = ["second@example.com"]

    phone_required = paypal_task_payloads.paypal_oauth_phone_required_failure_record(
        success_email="second@example.com",
        error=RuntimeError("需要手机号验证"),
        removed_pool_emails=removed_pool_emails,
    )
    failed = paypal_task_payloads.paypal_oauth_failed_record(
        success_email="second@example.com",
        error=RuntimeError("final oauth failure"),
        attempts=3,
    )
    thread_name = paypal_task_payloads.paypal_oauth_thread_name(
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
    assert thread_name == "paypal-oauth-abcdefghijklmnopqrstuvwx"


def test_paypal_bind_update_fields_preserves_success_and_cancel_rules():
    success = paypal_task_payloads.paypal_bind_update_fields(
        single_result={"status": "success", "checkout_url": "https://checkout", "message": "ok"},
        is_cancelled=True,
        proxy_label="proxy-a",
        task_id="task-1",
        bind_at=123.0,
        success_account_fields={
            "status": "active",
            "account_type": "plus",
            "seat_type": "codex",
            "account_source": "managed",
            "last_bind_provider": "paypal",
        },
    )
    failed = paypal_task_payloads.paypal_bind_update_fields(
        single_result={"status": "failed", "failure_stage": "paypal_login"},
        is_cancelled=True,
        proxy_label="proxy-a",
        task_id="task-1",
        bind_at=456.0,
        success_account_fields={"status": "active"},
    )

    assert success["last_bind_status"] == "success"
    assert success["status"] == "active"
    assert success["plus_bound_at"] == 123.0
    assert success["last_bind_provider"] == "paypal"
    assert failed["last_bind_status"] == "cancelled"
    assert failed["last_bind_failure_stage"] == "paypal_login"
    assert "plus_bound_at" not in failed


def test_paypal_bind_audit_and_nonzero_progress_payloads_are_stable():
    audit = paypal_task_payloads.paypal_bind_audit_record(
        task_id="task-1",
        candidate_email="user@example.com",
        single_result={"status": "success", "checkout_url": "https://checkout", "screenshot_paths": ["shot.png"]},
        proxy_label="proxy-a",
        selected_proxy_url="socks5://proxy.example:1080",
        manual_confirm=False,
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja-JP",
        paypal_password="secret",
        autofill_enabled=True,
        started_at=10.0,
        finished_at=20.0,
    )
    progress = paypal_task_payloads.paypal_nonzero_amount_blocked_progress(
        candidate_email="user@example.com",
        current=2,
        total=3,
    )
    cleanup = paypal_task_payloads.paypal_nonzero_amount_blocked_cleanup_request(
        candidate_email="user@example.com",
        current=2,
        total=3,
    )

    assert audit["task_status"] == "completed"
    assert audit["paypal_auto_login"] is True
    assert audit["flow"] == "paypal_create_account"
    assert audit["provider"] == "paypal"
    assert progress == {
        "stage": "paypal_nonzero_amount_blocked_rotate",
        "email": "user@example.com",
        "current": 2,
        "total": 3,
        "message": "今日应付非 0，已删除并跳过账号: user@example.com",
        "level": "warn",
    }
    assert cleanup == {
        "emails": ["user@example.com"],
        "log_context": "paypal-nonzero",
        "reason": "paypal_nonzero_amount_blocked",
        "message": "PayPal checkout 今日应付金额非 0，账号已从本地号池删除",
        "progress": progress,
    }


def test_paypal_progress_event_uses_stage_messages_and_preserves_extra_fields():
    assert paypal_task_payloads.paypal_progress_event("paypal_wait_result", url="https://paypal.example") == {
        "stage": "paypal_wait_result",
        "message": "PayPal 已授权，等待商户页面确认结果",
        "url": "https://paypal.example",
    }
    assert paypal_task_payloads.paypal_progress_event(
        "paypal_wait_result",
        "custom message",
        level="warn",
    ) == {
        "stage": "paypal_wait_result",
        "message": "custom message",
        "level": "warn",
    }
    assert paypal_task_payloads.paypal_progress_event("paypal_unknown_stage") == {
        "stage": "paypal_unknown_stage",
        "message": "paypal_unknown_stage",
    }


def test_finalize_paypal_task_result_preserves_batch_and_optional_fields():
    result, task_status = paypal_task_payloads.finalize_paypal_task_result(
        result={"status": "failed", "message": "", "checkout_url": ""},
        email="primary@example.com",
        checkout_url="https://initial",
        last_checkout_url="https://last",
        proxy_label="proxy-a",
        manual_confirm=False,
        paypal_mode="create_account",
        paypal_country="US",
        paypal_lang="en-US",
        paypal_password="secret",
        autofill_enabled=True,
        effective_concurrency=2,
        candidates=["a@example.com", "b@example.com"],
        successful_emails=["a@example.com"],
        failed_emails=["b@example.com"],
        pending_retry_emails=["b@example.com"],
        retried_emails=["b@example.com"],
        nonzero_blocked_emails=[],
        removed_pool_emails=[],
        invalid_phone_pool=["+15550000001"],
        oauth_scheduled_emails={"b@example.com", "a@example.com"},
        oauth_successful_emails=["a@example.com"],
        oauth_failed_emails=[{"email": "b@example.com"}],
        session_cpa_converted_emails=["a@example.com"],
        session_cpa_failed_auths=[{"email": "b@example.com"}],
        is_cancelled=False,
    )
    progress = paypal_task_payloads.paypal_completion_progress(
        result=result,
        task_status=task_status,
        successful_count=1,
        failed_count=1,
        total_count=2,
    )

    assert task_status == "completed"
    assert result["status"] == "success"
    assert result["message"] == "PayPal 批量绑定完成: 成功 1/2 个账号"
    assert result["checkout_url"] == "https://last"
    assert result["paypal_auto_login"] is True
    assert result["oauth_scheduled_emails"] == ["a@example.com", "b@example.com"]
    assert result["invalid_phone_numbers"] == ["+15550000001"]
    assert progress["stage"] == "paypal_completed"
    assert progress["successful"] == 1


def test_finalize_paypal_task_result_handles_all_nonzero_and_cancelled_failure():
    nonzero, nonzero_status = paypal_task_payloads.finalize_paypal_task_result(
        result={"status": "failed", "failure_stage": "ignored"},
        email="primary@example.com",
        checkout_url="",
        last_checkout_url="",
        proxy_label="proxy-a",
        manual_confirm=True,
        paypal_mode="existing_account",
        paypal_country="US",
        paypal_lang="en-US",
        paypal_password="secret",
        autofill_enabled=False,
        effective_concurrency=1,
        candidates=["a@example.com", "b@example.com"],
        successful_emails=[],
        failed_emails=["a@example.com", "b@example.com"],
        pending_retry_emails=[],
        retried_emails=[],
        nonzero_blocked_emails=["a@example.com", "b@example.com"],
        removed_pool_emails=[],
        invalid_phone_pool=[],
        oauth_scheduled_emails=set(),
        oauth_successful_emails=[],
        oauth_failed_emails=[],
        session_cpa_converted_emails=[],
        session_cpa_failed_auths=[],
        is_cancelled=False,
    )
    cancelled, cancelled_status = paypal_task_payloads.finalize_paypal_task_result(
        result={"status": "failed"},
        email="primary@example.com",
        checkout_url="",
        last_checkout_url="",
        proxy_label="proxy-a",
        manual_confirm=True,
        paypal_mode="existing_account",
        paypal_country="US",
        paypal_lang="en-US",
        paypal_password="secret",
        autofill_enabled=False,
        effective_concurrency=1,
        candidates=["primary@example.com"],
        successful_emails=[],
        failed_emails=["primary@example.com"],
        pending_retry_emails=[],
        retried_emails=[],
        nonzero_blocked_emails=[],
        removed_pool_emails=[],
        invalid_phone_pool=[],
        oauth_scheduled_emails=set(),
        oauth_successful_emails=[],
        oauth_failed_emails=[],
        session_cpa_converted_emails=[],
        session_cpa_failed_auths=[],
        is_cancelled=True,
    )

    assert nonzero_status == "failed"
    assert nonzero["failure_stage"] == "browser_charge_guard"
    assert nonzero["message"] == "PayPal 批量绑定失败: 2 个账号今日应付均非 0"
    assert cancelled_status == "cancelled"
    assert cancelled["task_status"] == "cancelled"
    assert cancelled["paypal_auto_login"] is False
