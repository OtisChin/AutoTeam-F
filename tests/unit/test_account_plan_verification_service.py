from autotoken.services import account_plan_verification


def test_verification_failure_fields_are_provider_neutral():
    fields = account_plan_verification.verification_failure_update_fields(
        task_id="export-cpa-auths",
        status="pending_manual",
        message="plan not confirmed",
        failure_stage="export_plan_verify",
        marked_at=123.0,
    )

    assert fields == {
        "last_bind_status": "pending_manual",
        "last_bind_at": 123.0,
        "last_bind_task_id": "export-cpa-auths",
        "last_bind_message": "plan not confirmed",
        "last_bind_failure_stage": "export_plan_verify",
    }


def test_refreshed_auth_data_updates_compatible_token_fields():
    result = account_plan_verification.refreshed_auth_data(
        {"email": "user@example.com", "access_token": "old"},
        {
            "access_token": "Bearer new-token,",
            "refresh_token": "refresh-new",
            "id_token": "id-new",
            "expires_in": 60,
        },
        now=1000.0,
    )

    assert result["access_token"] == "new-token"
    assert result["accessToken"] == "new-token"
    assert result["refresh_token"] == "refresh-new"
    assert result["refreshToken"] == "refresh-new"
    assert result["id_token"] == "id-new"
    assert result["idToken"] == "id-new"
    assert result["expired"] == "1970-01-01T00:17:40Z"
    assert result["last_refresh"] == "1970-01-01T00:16:40Z"


def test_refreshed_auth_data_skips_missing_tokens_and_invalid_expiry():
    result = account_plan_verification.refreshed_auth_data(
        {"access_token": "old", "refresh_token": "old-refresh"},
        {"expires_in": "invalid"},
        now=0,
    )

    assert result["access_token"] == "old"
    assert result["refresh_token"] == "old-refresh"
    assert "expired" not in result
    assert result["last_refresh"] == "1970-01-01T00:00:00Z"


def test_usage_probe_result_helpers_keep_existing_response_contracts():
    assert account_plan_verification.usage_probe_missing_token_result() == {
        "status": "missing_token",
        "plan_type": "",
        "message": "缺少 access_token",
    }
    assert account_plan_verification.plus_plan_auth_file_read_error_result(ValueError("invalid json")) == {
        "ok": False,
        "plan_type": "",
        "message": "CPA auth 文件读取失败: invalid json",
    }
    assert account_plan_verification.usage_probe_exception_result(
        kind="网络异常",
        error=RuntimeError("timeout"),
    ) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage 网络异常: timeout",
    }
    assert account_plan_verification.usage_probe_http_result(status_code=401) == {
        "status": "auth_error",
        "plan_type": "",
        "message": "wham/usage token 无效 HTTP 401",
    }
    assert account_plan_verification.usage_probe_http_result(status_code=429) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage 临时错误 HTTP 429",
    }
    assert account_plan_verification.usage_probe_http_result(status_code=418, text="x" * 200) == {
        "status": "network_error",
        "plan_type": "",
        "message": f"wham/usage 非预期 HTTP 418: {'x' * 160}",
    }
    assert account_plan_verification.usage_probe_json_error_result(ValueError("bad json")) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage JSON 解析失败: bad json",
    }
    assert account_plan_verification.usage_probe_ok_result(" PLUS ") == {
        "status": "ok",
        "plan_type": "plus",
        "message": "wham/usage plan_type=plus",
    }
    assert account_plan_verification.usage_probe_ok_result("")["message"] == "wham/usage plan_type=unknown"


def test_plus_plan_result_helpers_keep_existing_response_contracts():
    assert account_plan_verification.plus_plan_verified_result(" PLUS ") == {
        "ok": True,
        "plan_type": "plus",
        "message": "OpenAI 已确认 plan_type=plus",
    }
    assert account_plan_verification.plus_plan_refresh_exception_probe(
        {"status": "", "message": "wham/usage plan_type=free"},
        plan_type=" FREE ",
        error=RuntimeError("refresh failed"),
    ) == {
        "status": "refresh_error",
        "plan_type": "free",
        "message": "wham/usage plan_type=free; refresh 异常: refresh failed",
    }
    assert account_plan_verification.plus_plan_unverified_result(
        email="user@example.com",
        last_probe={"status": "ok", "plan_type": "free", "message": "ignored"},
    ) == {
        "ok": False,
        "plan_type": "free",
        "message": "OpenAI wham/usage 仍返回 plan_type=free，未确认 Plus 生效",
        "email": "user@example.com",
    }
    assert account_plan_verification.plus_plan_unverified_result(
        email="user@example.com",
        last_probe={"plan_type": "", "message": ""},
    ) == {
        "ok": False,
        "plan_type": "",
        "message": "OpenAI Plus 状态未确认",
        "email": "user@example.com",
    }
