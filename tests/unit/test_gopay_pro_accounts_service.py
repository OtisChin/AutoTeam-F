from autotoken.services import gopay_pro_accounts


def test_success_account_update_fields_shape_and_defaults():
    fields = gopay_pro_accounts.success_account_update_fields(
        task_id="task-1",
        message="",
        marked_at=123.5,
        auth_file="auth.json",
        status_plus="plus",
        account_type_plus="plus",
        seat_codex="codex",
        account_source_managed="managed",
    )

    assert fields == {
        "status": "plus",
        "account_type": "plus",
        "seat_type": "codex",
        "account_source": "managed",
        "last_bind_status": "success",
        "last_bind_provider": "gopay_pro",
        "last_bind_at": 123.5,
        "last_bind_task_id": "task-1",
        "last_bind_message": "GoPay Pro 绑定成功",
        "last_bind_failure_stage": "",
        "plus_bound_at": 123.5,
        "auth_file": "auth.json",
    }


def test_success_account_update_fields_omits_empty_auth_file_and_keeps_message():
    fields = gopay_pro_accounts.success_account_update_fields(
        task_id="task-1",
        message="confirmed",
        marked_at=123.5,
        auth_file="",
        status_plus="plus",
        account_type_plus="plus",
        seat_codex="codex",
        account_source_managed="managed",
    )

    assert fields["last_bind_message"] == "confirmed"
    assert "auth_file" not in fields


def test_failed_account_update_fields_shape():
    assert gopay_pro_accounts.failed_account_update_fields(
        task_id="task-1",
        status="failed",
        message="payment failed",
        failure_stage="gopay_pro_harvest",
        marked_at=456.0,
    ) == {
        "last_bind_status": "failed",
        "last_bind_provider": "gopay_pro",
        "last_bind_at": 456.0,
        "last_bind_task_id": "task-1",
        "last_bind_message": "payment failed",
        "last_bind_failure_stage": "gopay_pro_harvest",
    }


def test_account_already_plus_checks_status_and_account_type_case_insensitively():
    assert gopay_pro_accounts.account_already_plus(
        {"status": " PLUS ", "account_type": "free"},
        status_plus="plus",
        account_type_plus="plus",
    )
    assert gopay_pro_accounts.account_already_plus(
        {"status": "active", "account_type": " Plus "},
        status_plus="plus",
        account_type_plus="plus",
    )
    assert not gopay_pro_accounts.account_already_plus(
        {"status": "active", "account_type": "free"},
        status_plus="plus",
        account_type_plus="plus",
    )


def test_normalized_account_emails_filters_blanks_and_preserves_first_seen_order():
    assert gopay_pro_accounts.normalized_account_emails(
        [" FIRST@example.com ", "", "second@example.com", "first@example.com", None]
    ) == ["first@example.com", "second@example.com"]
    assert gopay_pro_accounts.normalized_account_emails(None) == []


def test_account_token_item_normalizes_compatibility_auth_fields():
    direct = gopay_pro_accounts.account_token_item(
        email=" user@example.com ",
        auth_data={
            "access_token": "Bearer access-token,",
            "refresh_token": " refresh-token ",
            "account_id": " account-id ",
        },
        auth_file=" auth.json ",
    )
    camel = gopay_pro_accounts.account_token_item(
        email="user@example.com",
        auth_data={
            "accessToken": "camel-access",
            "refreshToken": " camel-refresh ",
            "accountId": " camel-account ",
        },
        auth_file="auth.json",
    )
    nested = gopay_pro_accounts.account_token_item(
        email="user@example.com",
        auth_data={"tokens": {"access_token": "nested-access"}},
        auth_file="auth.json",
    )

    assert direct == {
        "email": "user@example.com",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "account_id": "account-id",
        "auth_file": "auth.json",
    }
    assert camel["access_token"] == "camel-access"
    assert camel["refresh_token"] == "camel-refresh"
    assert camel["account_id"] == "camel-account"
    assert nested["access_token"] == "nested-access"
    assert nested["refresh_token"] == ""
    assert nested["account_id"] == ""


def test_account_token_item_access_error_reports_missing_and_duplicate_tokens():
    assert (
        gopay_pro_accounts.account_token_item_access_error(
            {"email": "user@example.com", "access_token": ""},
            set(),
        )
        == "账号认证文件缺少 access_token: user@example.com"
    )
    assert (
        gopay_pro_accounts.account_token_item_access_error(
            {"email": "user@example.com", "access_token": "token-1"},
            {"token-1"},
        )
        == "账号 access_token 重复: user@example.com"
    )
    assert (
        gopay_pro_accounts.account_token_item_access_error(
            {"email": "user@example.com", "access_token": "token-1"},
            set(),
        )
        == ""
    )


def test_refreshed_auth_data_updates_compatibility_token_keys_and_timestamps():
    result = gopay_pro_accounts.refreshed_auth_data(
        {"existing": "kept", "access_token": "old"},
        {
            "access_token": "Bearer new-access,",
            "refresh_token": " new-refresh ",
            "id_token": " id-token ",
            "expires_in": 60,
        },
        now=0,
    )

    assert result["existing"] == "kept"
    assert result["access_token"] == "new-access"
    assert result["accessToken"] == "new-access"
    assert result["refresh_token"] == "new-refresh"
    assert result["refreshToken"] == "new-refresh"
    assert result["id_token"] == "id-token"
    assert result["idToken"] == "id-token"
    assert result["expired"] == "1970-01-01T00:01:00Z"
    assert result["last_refresh"] == "1970-01-01T00:00:00Z"


def test_refreshed_auth_data_skips_missing_tokens_and_invalid_expiry():
    result = gopay_pro_accounts.refreshed_auth_data(
        {"access_token": "old", "refresh_token": "old-refresh"},
        {"expires_in": "invalid"},
        now=0,
    )

    assert result["access_token"] == "old"
    assert result["refresh_token"] == "old-refresh"
    assert "expired" not in result
    assert result["last_refresh"] == "1970-01-01T00:00:00Z"


def test_usage_probe_result_helpers_are_stable():
    assert gopay_pro_accounts.usage_probe_missing_token_result() == {
        "status": "missing_token",
        "plan_type": "",
        "message": "缺少 access_token",
    }
    assert gopay_pro_accounts.plus_plan_auth_file_read_error_result(ValueError("invalid json")) == {
        "ok": False,
        "plan_type": "",
        "message": "CPA auth 文件读取失败: invalid json",
    }
    assert gopay_pro_accounts.usage_probe_exception_result(kind="网络异常", error=RuntimeError("timeout")) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage 网络异常: timeout",
    }
    assert gopay_pro_accounts.usage_probe_http_result(status_code=401) == {
        "status": "auth_error",
        "plan_type": "",
        "message": "wham/usage token 无效 HTTP 401",
    }
    assert gopay_pro_accounts.usage_probe_http_result(status_code=429) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage 临时错误 HTTP 429",
    }
    assert gopay_pro_accounts.usage_probe_http_result(status_code=418, text="x" * 200) == {
        "status": "network_error",
        "plan_type": "",
        "message": f"wham/usage 非预期 HTTP 418: {'x' * 160}",
    }
    assert gopay_pro_accounts.usage_probe_json_error_result(ValueError("bad json")) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage JSON 解析失败: bad json",
    }
    assert gopay_pro_accounts.usage_probe_ok_result(" PLUS ") == {
        "status": "ok",
        "plan_type": "plus",
        "message": "wham/usage plan_type=plus",
    }
    assert gopay_pro_accounts.usage_probe_ok_result("") == {
        "status": "ok",
        "plan_type": "",
        "message": "wham/usage plan_type=unknown",
    }


def test_plus_plan_verification_result_helpers_are_stable():
    assert gopay_pro_accounts.plus_plan_verified_result(" PLUS ") == {
        "ok": True,
        "plan_type": "plus",
        "message": "OpenAI 已确认 plan_type=plus",
    }
    assert gopay_pro_accounts.plus_plan_refresh_exception_probe(
        {"status": "", "message": "wham/usage plan_type=free"},
        plan_type=" FREE ",
        error=RuntimeError("refresh failed"),
    ) == {
        "status": "refresh_error",
        "plan_type": "free",
        "message": "wham/usage plan_type=free; refresh 异常: refresh failed",
    }
    assert gopay_pro_accounts.plus_plan_refresh_exception_probe(
        {"status": "network_error", "message": "temporary"},
        plan_type="",
        error=RuntimeError("refresh failed"),
    )["status"] == "network_error"
    assert gopay_pro_accounts.plus_plan_unverified_result(
        email="user@example.com",
        last_probe={"plan_type": " FREE ", "message": "ignored"},
    ) == {
        "ok": False,
        "plan_type": "free",
        "message": "OpenAI wham/usage 仍返回 plan_type=free，未确认 Plus 生效",
        "email": "user@example.com",
    }
    assert gopay_pro_accounts.plus_plan_unverified_result(
        email="user@example.com",
        last_probe={"plan_type": "", "message": ""},
    ) == {
        "ok": False,
        "plan_type": "",
        "message": "OpenAI Plus 状态未确认",
        "email": "user@example.com",
    }
