from __future__ import annotations

import pytest

from autotoken.services import paypal_protocol_local as service


def test_build_protocol_command_uses_vendored_engine_and_success_env(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    (engine / "var").mkdir(parents=True)
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    fp = engine / "var" / "roxy_ios_fingerprint_current.json"
    fp.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, env, cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        paypal_link="https://www.paypal.com/agreements/approve?ba_token=BA-1CMD123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api/record?token=secret",
        proxy_url="proxy.example:10000:user:pass",
    ))

    assert cwd == engine.resolve()
    assert str(engine / "main.py") in cmd
    assert "--approval-path" in cmd and "create-member-no-fi" in cmd
    assert "--proxy" in cmd
    assert env["PAYPAL_USE_CURL_CFFI"] == "0"
    assert env["PAYPAL_HEADLESS_USE_PINNED_FINGERPRINT"] == "1"
    assert env["PAYPAL_HEADLESS_PINNED_FINGERPRINT_PATH"] == str(fp)
    assert env["PAYPAL_APPROVAL_PATH"] == "create_member_no_fi"
    assert env["PAYPAL_STRICT_BROWSER_RISK"] == "0"
    assert env["PAYPAL_MTR_HEADLESS_WAIT_SECONDS"] == "45"
    joined = " ".join(cmd)
    assert "153" + ".ink" not in joined
    assert "pay" + "153" not in joined


def test_protocol_service_sanitizes_sensitive_values():
    text = service.sanitize_log_text(
        "BA-1234567890 https://sms.example/api?token=abcdef socks5h://user:pass@proxy.example:10000"
    )

    assert "abcdef" not in text
    assert "user:pass" not in text
    assert "BA-1234567890" not in text


def test_build_protocol_command_rejects_non_us(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    with pytest.raises(ValueError, match="仅开放 US"):
        service.build_protocol_command(service.PaypalProtocolRunConfig(
            ba_token="BA-1CMD123",
            phone="+18350000000",
            sms_record_url="https://sms.example/api?token=secret",
            country="BR",
        ))


def test_build_protocol_command_passes_sms_wait_and_poll(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    cmd, _env, _cwd = service.build_protocol_command(service.PaypalProtocolRunConfig(
        ba_token="BA-1WAIT123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
        sms_record_wait_seconds=600,
        sms_record_poll_seconds=2,
    ))

    assert cmd[cmd.index("--sms-record-wait") + 1] == "600"
    assert cmd[cmd.index("--sms-record-poll") + 1] == "2.0"


def test_protocol_service_classifies_oas_error(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('GraphQL CreateMemberAccountMutation returned errors: OAS_ERROR createMemberAccount')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1OAS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "failed"
    assert "OAS_ERROR" in result["message"]
    assert "createMemberAccount" in result["message"]


def test_protocol_service_classifies_signup_context_preflight_block(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('Signup-context browser risk incomplete before CreateMemberAccount; blocked to avoid PayPal OAS_ERROR: missing=fraudnet_p1')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1MISS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "failed"
    assert "风控信号不完整" in result["message"]


def test_protocol_service_classifies_mtr_missing_before_authchallenge(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('PayPal authchallenge type=recaptcha requires manual/official verification')\n"
        "print('RESULT:')\n"
        "print('{\"status\":\"error\",\"risk_runtime\":{\"strict_blockers\":[\"mtr_sealedResult_missing\"]}}')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    logs: list[str] = []
    result = service.run_paypal_protocol_payment(
        service.PaypalProtocolRunConfig(
            ba_token="BA-1MTR123",
            phone="+18350000000",
            sms_record_url="https://sms.example/api?token=secret",
        ),
        log=logs.append,
    )

    assert result["status"] == "failed"
    assert "MTR" in result["message"]
    assert "sealedResult" in result["message"]
    assert any("RESULT JSON" in line for line in logs)
    assert not any("strict_blockers" in line for line in logs)


def test_protocol_service_classifies_member_approve_failure_from_result(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('RESULT:')\n"
        "print('{\"status\":\"error\",\"error\":\"approveMemberPayment returned empty result\"}')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1APPROVE123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "failed"
    assert "member approve" in result["message"]


def test_protocol_service_records_and_blocks_terminal_ba_retry(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    script = engine / "main.py"
    script.write_text(
        "print('Member account created without backup FI. User ID: TEST')\n"
        "print('ApproveMemberPaymentMutation returned errors')\n"
        "print('RESULT:')\n"
        "print('{\"status\":\"error\",\"error\":\"approveMemberPayment returned empty result\"}')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))
    monkeypatch.setattr(service, "TERMINAL_BA_FILE", tmp_path / "terminal_ba.json")

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-1TERM123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    )
    first_logs: list[str] = []
    first = service.run_paypal_protocol_payment(cfg, log=first_logs.append)

    assert first["status"] == "failed"
    assert service.terminal_ba_record("BA-1TERM123")
    assert any("本机终态" in line for line in first_logs)

    script.write_text("print('should not run')\nraise SystemExit(0)\n", encoding="utf-8")
    second_logs: list[str] = []
    second = service.run_paypal_protocol_payment(cfg, log=second_logs.append)

    assert second["status"] == "failed"
    assert "fresh BA" in second["message"]
    assert any("阻止重复协议支付" in line for line in second_logs)
    assert not any("should not run" in line for line in second_logs)


def test_protocol_service_treats_success_log_as_success_when_result_json_missing(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('GraphQL ApproveMemberPaymentMutation HTTP 200 bytes=1166')\n"
        "print('  \"state\": \"APPROVED\",')\n"
        "print('=== Flow completed successfully ===')\n"
        "print('RESULT:')\n"
        "print('{not-json')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1SUCCESS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "success"
    assert result["protocol_result"]["inferred_from_log"] is True


def test_protocol_service_does_not_fail_success_on_risk_runtime_diagnostic(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "main.py").write_text(
        "print('=== Flow completed successfully ===')\n"
        "print('RESULT:')\n"
        "print('{\"status\":\"success\",\"risk_runtime\":{\"strict_blockers\":[\"mtr_sealedResult_missing\"]}}')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTEAM_PAYPAL_ENGINE_ROOT", str(engine))

    result = service.run_paypal_protocol_payment(service.PaypalProtocolRunConfig(
        ba_token="BA-1RISKSUCCESS123",
        phone="+18350000000",
        sms_record_url="https://sms.example/api?token=secret",
    ))

    assert result["status"] == "success"
    assert "message" not in result
