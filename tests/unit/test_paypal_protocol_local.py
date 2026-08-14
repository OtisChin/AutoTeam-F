from __future__ import annotations

from autotoken.services import paypal_protocol_local as service


def test_protocol_internal_base_defaults_to_autoteam_api_port(monkeypatch):
    monkeypatch.delenv("PAYPAL_PROTOCOL_INTERNAL_BASE_URL", raising=False)
    monkeypatch.delenv("AUTOTEAM_API_BASE_URL", raising=False)
    monkeypatch.delenv("AUTOTOKEN_API_BASE_URL", raising=False)
    monkeypatch.delenv("AUTOTEAM_API_PORT", raising=False)
    monkeypatch.delenv("AUTOTOKEN_API_PORT", raising=False)
    monkeypatch.delenv("API_PORT", raising=False)

    assert service._protocol_internal_base_url() == "http://127.0.0.1:8799"


def test_protocol_internal_base_respects_explicit_env(monkeypatch):
    monkeypatch.setenv("PAYPAL_PROTOCOL_INTERNAL_BASE_URL", "http://127.0.0.1:18096/")

    assert service._protocol_internal_base_url() == "http://127.0.0.1:18096"


def test_protocol_runner_drives_vendored_web_job_and_submits_sms_record_otp(monkeypatch, tmp_path):
    submitted: list[str] = []
    created: list[dict[str, object]] = []

    class FakeJob:
        id = "local-web-job"
        status = "awaiting_otp"
        stage = "Waiting for SMS code / new phone"
        error = ""
        result = None

        def to_dict(self, *, include_logs=True, log_offset=0):
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "awaiting_otp": self.status == "awaiting_otp",
                "awaiting_captcha": False,
                "logs": [] if log_offset else [{"message": "SMS verification code sent"}],
                "result": self.result,
                "error": self.error,
            }

        def submit_input(self, value: str) -> None:
            submitted.append(value)
            self.status = "completed"
            self.stage = "已完成"
            self.result = {"status": "success", "return_url": "https://paypal.example/success"}

        def cancel(self) -> None:
            self.status = "cancelled"
            self.stage = "Cancelled"

    class FakeWeb:
        def create_job(self, **kwargs):
            created.append(kwargs)
            return FakeJob()

    (tmp_path / "main.py").write_text("raise SystemExit(42)\n", encoding="utf-8")
    monkeypatch.setattr(service, "_engine_root", lambda: tmp_path)
    monkeypatch.setattr(service, "_load_engine_web_module", lambda root: FakeWeb(), raising=False)
    monkeypatch.setattr(service, "_read_sms_record_code", lambda url, timeout_seconds, poll_seconds: "123456", raising=False)

    logs: list[str] = []
    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-91G197898H813770D",
        phone="+447700900001",
        sms_record_url="https://sms.example/record?token=secret",
        sms_provider="sms_record",
        proxy_url="proxy-one",
        country="GB",
        timeout_seconds=60,
    )

    result = service.run_paypal_protocol_payment(cfg, log=logs.append)

    assert result["status"] == "success"
    assert submitted == ["123456"]
    assert created[0]["ba_token"] == "BA-91G197898H813770D"
    assert created[0]["phone"] == "+447700900001"
    assert created[0]["country"] == "GB"
    assert created[0]["proxy_pool"] == ["socks5h://proxy-one"]
    assert any("PayPal协议任务已创建" in line for line in logs)


def test_protocol_runner_can_stop_before_otp_without_submitting_code(monkeypatch, tmp_path):
    submitted: list[str] = []
    cancelled: list[bool] = []

    class FakeJob:
        id = "stop-before-otp-job"
        status = "awaiting_otp"
        stage = "Waiting for SMS code"
        result = None

        def to_dict(self, *, include_logs=True, log_offset=0):
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "awaiting_otp": True,
                "awaiting_prompt": "请输入6位短信验证码",
                "awaiting_captcha": False,
                "logs": [],
                "result": self.result,
                "error": "",
            }

        def submit_input(self, value: str) -> None:
            submitted.append(value)
            self.status = "completed"
            self.result = {"status": "success"}

        def cancel(self) -> None:
            cancelled.append(True)
            self.status = "cancelled"

    class FakeWeb:
        def create_job(self, **kwargs):
            return FakeJob()

    (tmp_path / "main.py").write_text("raise SystemExit(42)\n", encoding="utf-8")
    monkeypatch.setenv("PAYPAL_PROTOCOL_STOP_BEFORE_OTP", "1")
    monkeypatch.setattr(service, "_engine_root", lambda: tmp_path)
    monkeypatch.setattr(service, "_load_engine_web_module", lambda root: FakeWeb(), raising=False)
    monkeypatch.setattr(service, "_read_sms_record_code", lambda *args, **kwargs: "123456", raising=False)

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-91G197898H813770D",
        phone="+447700900001",
        sms_record_url="https://sms.example/record?token=secret",
        sms_provider="sms_record",
        country="GB",
        timeout_seconds=60,
    )

    result = service.run_paypal_protocol_payment(cfg, log=lambda _line: None)

    assert result["status"] == "awaiting_otp"
    assert result["returncode"] is None
    assert result["message"] == "已按测试开关在 OTP 输入前停止"
    assert submitted == []
    assert cancelled == [True]




def test_protocol_runner_submits_new_provider_phone_when_paypal_requests_phone_retry(monkeypatch, tmp_path):
    submitted: list[str] = []
    reserved: list[str] = []

    class FakeActivation:
        def __init__(self, phone):
            self.phone_number = phone
            self.activation_id = f"act-{phone[-4:]}"

    class FakeProvider:
        def reserve_number(self):
            phone = f"+6680000{len(reserved) + 1:04d}"
            reserved.append(phone)
            return FakeActivation(phone)

        def mark_sms_sent(self, activation):
            return None

        def wait_for_code(self, activation, timeout_seconds=None):
            assert activation.phone_number == reserved[-1]
            return "654321"

        def register_confirmation_result(self, activation, confirmed):
            return None

    class FakeJob:
        id = "phone-retry-job"
        status = "awaiting_otp"
        stage = "Waiting for SMS code / new phone"
        result = None

        def __init__(self):
            self.prompt = "发送验证码失败。请输入新的手机号重新发送（如 +66812345678）；输入 q 退出。"

        def to_dict(self, *, include_logs=True, log_offset=0):
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "awaiting_otp": self.status == "awaiting_otp",
                "awaiting_prompt": self.prompt,
                "awaiting_captcha": False,
                "logs": [],
                "result": self.result,
                "error": "",
            }

        def submit_input(self, value: str) -> None:
            submitted.append(value)
            if len(submitted) == 1:
                assert value == reserved[1]
                self.prompt = "输入6位短信验证码；如需换号，直接输入新手机号"
                return
            assert value == "654321"
            self.status = "completed"
            self.stage = "已完成"
            self.result = {"status": "success"}

        def cancel(self) -> None:
            self.status = "cancelled"

    class FakeWeb:
        def create_job(self, **kwargs):
            return FakeJob()

    monkeypatch.setattr(service, "_engine_root", lambda: tmp_path)
    monkeypatch.setattr(service, "_load_engine_web_module", lambda root: FakeWeb(), raising=False)
    monkeypatch.setattr(service, "_build_protocol_sms_provider", lambda cfg, engine_root: FakeProvider())

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-91G197898H813770D",
        sms_provider="hero_sms",
        proxy_url="proxy-one",
        country="TH",
        timeout_seconds=60,
    )

    result = service.run_paypal_protocol_payment(cfg, log=lambda _line: None)

    assert result["status"] == "success"
    assert reserved == ["+66800000001", "+66800000002"]
    assert submitted == ["+66800000002", "654321"]


def test_protocol_runner_fails_sms_record_when_paypal_requests_phone_retry(monkeypatch, tmp_path):
    submitted: list[str] = []

    class FakeJob:
        id = "sms-record-phone-retry-job"
        status = "awaiting_otp"
        stage = "Waiting for SMS code / new phone"
        result = None

        def to_dict(self, *, include_logs=True, log_offset=0):
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "awaiting_otp": True,
                "awaiting_prompt": "发送验证码失败。请输入新的手机号重新发送（如 +66812345678）；输入 q 退出。",
                "awaiting_captcha": False,
                "logs": [],
                "result": self.result,
                "error": "BRAINTREE_VAULT_FAILED",
            }

        def submit_input(self, value: str) -> None:
            submitted.append(value)
            self.status = "completed"
            self.result = {"status": "success"}

        def cancel(self) -> None:
            self.status = "cancelled"

    class FakeWeb:
        def create_job(self, **kwargs):
            return FakeJob()

    monkeypatch.setattr(service, "_engine_root", lambda: tmp_path)
    monkeypatch.setattr(service, "_load_engine_web_module", lambda root: FakeWeb(), raising=False)
    monkeypatch.setattr(service, "_read_sms_record_code", lambda *args, **kwargs: "123456", raising=False)

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-91G197898H813770D",
        phone="+66812345678",
        sms_record_url="https://sms.example/record?token=secret",
        sms_provider="sms_record",
        country="TH",
        timeout_seconds=60,
    )

    result = service.run_paypal_protocol_payment(cfg, log=lambda _line: None)

    assert result["status"] == "failed"
    assert "sms_record 固定号码无法自动换号" in result["message"]
    assert submitted == []


def test_protocol_runner_does_not_change_provider_phone_inside_attempt_after_sms_timeout(monkeypatch, tmp_path):
    submitted: list[str] = []
    reserved: list[str] = []
    abandoned: list[tuple[str, str]] = []
    waited: list[str] = []

    class FakeActivation:
        def __init__(self, phone):
            self.phone_number = phone
            self.activation_id = f"act-{phone[-4:]}"

    class FakeProvider:
        def reserve_number(self):
            phone = f"+6680000{len(reserved) + 1:04d}"
            reserved.append(phone)
            return FakeActivation(phone)

        def mark_sms_sent(self, activation):
            return None

        def wait_for_code(self, activation, timeout_seconds=None):
            waited.append(activation.phone_number)
            return None

        def abandon(self, activation, reason):
            abandoned.append((activation.phone_number, reason))

        def register_confirmation_result(self, activation, confirmed):
            return None

    class FakeJob:
        id = "sms-timeout-change-phone-job"
        status = "awaiting_otp"
        stage = "Waiting for SMS code / new phone"
        result = None

        def __init__(self):
            self.prompt = "请输入6位短信验证码；如需换号，输入新手机号（如 +66812345678 或 phone:+66812345678）；输入 q 退出。"

        def to_dict(self, *, include_logs=True, log_offset=0):
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "awaiting_otp": self.status == "awaiting_otp",
                "awaiting_prompt": self.prompt,
                "awaiting_captcha": False,
                "logs": [],
                "result": self.result,
                "error": "BRAINTREE_VAULT_FAILED",
            }

        def submit_input(self, value: str) -> None:
            submitted.append(value)
            raise AssertionError("OTP timeout must not submit a replacement phone inside the same PayPal协议 attempt")

        def cancel(self) -> None:
            self.status = "cancelled"

    class FakeWeb:
        def create_job(self, **kwargs):
            return FakeJob()

    monkeypatch.setattr(service, "_engine_root", lambda: tmp_path)
    monkeypatch.setattr(service, "_load_engine_web_module", lambda root: FakeWeb(), raising=False)
    monkeypatch.setattr(service, "_build_protocol_sms_provider", lambda cfg, engine_root: FakeProvider())

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-91G197898H813770D",
        sms_provider="hero_sms",
        proxy_url="proxy-one",
        country="TH",
        timeout_seconds=60,
    )

    result = service.run_paypal_protocol_payment(cfg, log=lambda _line: None)

    assert result["status"] == "failed"
    assert "OTP 等待超时" in result["message"]
    assert "请重试换号" in result["message"]
    assert reserved == ["+66800000001"]
    assert submitted == []
    assert abandoned == [("+66800000001", "sms_timeout")]


def test_protocol_runner_does_not_wait_for_sms_before_new_phone_is_consumed(monkeypatch, tmp_path):
    submitted: list[str] = []
    reserved: list[str] = []
    waited: list[str] = []

    class FakeActivation:
        def __init__(self, phone):
            self.phone_number = phone
            self.activation_id = f"act-{phone[-4:]}"

    class FakeProvider:
        def reserve_number(self):
            phone = f"+6680000{len(reserved) + 1:04d}"
            reserved.append(phone)
            return FakeActivation(phone)

        def mark_sms_sent(self, activation):
            return None

        def wait_for_code(self, activation, timeout_seconds=None):
            waited.append(activation.phone_number)
            if activation.phone_number == "+66800000002":
                raise AssertionError("runner waited for SMS before PayPal consumed the submitted new phone")
            return "445566"

        def abandon(self, activation, reason):
            return None

        def register_confirmation_result(self, activation, confirmed):
            return None

    class FakeJob:
        id = "phone-submit-race-job"
        status = "awaiting_otp"
        stage = "Waiting for SMS code / new phone"
        result = None

        def __init__(self):
            self.prompt = "发送验证码失败。请输入新的手机号重新发送（如 +66812345678）；输入 q 退出。"
            self.snapshots_after_submit = 0

        def to_dict(self, *, include_logs=True, log_offset=0):
            if len(submitted) == 1:
                self.snapshots_after_submit += 1
                if self.snapshots_after_submit >= 2:
                    self.prompt = "发送验证码失败。请输入新的手机号重新发送（如 +66812345678）；输入 q 退出。"
                else:
                    self.prompt = "请输入6位短信验证码；如需换号，输入新手机号（如 +66812345678 或 phone:+66812345678）；输入 q 退出。"
            elif len(submitted) == 2:
                self.prompt = "请输入6位短信验证码；如需换号，输入新手机号（如 +66812345678 或 phone:+66812345678）；输入 q 退出。"
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "awaiting_otp": self.status == "awaiting_otp",
                "awaiting_prompt": self.prompt,
                "awaiting_captcha": False,
                "logs": [],
                "result": self.result,
                "error": "BRAINTREE_VAULT_FAILED",
            }

        def submit_input(self, value: str) -> None:
            submitted.append(value)
            if len(submitted) == 2:
                self.prompt = "请输入6位短信验证码；如需换号，输入新手机号（如 +66812345678 或 phone:+66812345678）；输入 q 退出。"
            if len(submitted) == 3:
                assert value == "445566"
                self.status = "completed"
                self.result = {"status": "success"}

        def cancel(self) -> None:
            self.status = "cancelled"

    class FakeWeb:
        def create_job(self, **kwargs):
            return FakeJob()

    monkeypatch.setattr(service, "_engine_root", lambda: tmp_path)
    monkeypatch.setattr(service, "_load_engine_web_module", lambda root: FakeWeb(), raising=False)
    monkeypatch.setattr(service, "_build_protocol_sms_provider", lambda cfg, engine_root: FakeProvider())
    monkeypatch.setattr(service, "PHONE_INPUT_SETTLE_SECONDS", 0.05)

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-91G197898H813770D",
        sms_provider="hero_sms",
        country="TH",
        timeout_seconds=60,
    )

    result = service.run_paypal_protocol_payment(cfg, log=lambda _line: None)

    assert result["status"] == "success"
    assert submitted[:2] == ["+66800000002", "+66800000003"]
    assert waited == ["+66800000003"]


def test_protocol_runner_matches_upstream_bridge_failure_as_failed_even_when_paypal_authorized(monkeypatch, tmp_path):
    class FakeJob:
        id = "paypal-authorized-bridge-failed"
        status = "failed"
        stage = "最终授权失败"
        result = {
            "status": "error",
            "error_code": "BRAINTREE_VAULT_FAILED",
            "settlement_status": "vault_failed",
            "paypal_authorized": True,
            "redirect_status": "succeeded",
            "return_url": "https://pm-redirects.example/return?status=success",
        }

        def to_dict(self, *, include_logs=True, log_offset=0):
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "awaiting_otp": False,
                "awaiting_captcha": False,
                "logs": [],
                "result": self.result,
                "error": "BRAINTREE_VAULT_FAILED",
            }

        def cancel(self) -> None:
            self.status = "cancelled"

    class FakeWeb:
        def create_job(self, **kwargs):
            return FakeJob()

    monkeypatch.setattr(service, "_engine_root", lambda: tmp_path)
    monkeypatch.setattr(service, "_load_engine_web_module", lambda root: FakeWeb(), raising=False)
    monkeypatch.setattr(service, "_read_sms_record_code", lambda *args, **kwargs: "", raising=False)

    cfg = service.PaypalProtocolRunConfig(
        ba_token="BA-91G197898H813770D",
        phone="+66812345678",
        sms_record_url="https://sms.example/record?token=secret",
        sms_provider="sms_record",
        country="TH",
        timeout_seconds=60,
    )

    result = service.run_paypal_protocol_payment(cfg, log=lambda _line: None)

    assert result["status"] == "failed"
    assert result["returncode"] == 1
    assert result["message"] == "BRAINTREE_VAULT_FAILED"
    assert result["protocol_result"]["error_code"] == "BRAINTREE_VAULT_FAILED"
    assert result["protocol_result"]["paypal_authorized"] is True
