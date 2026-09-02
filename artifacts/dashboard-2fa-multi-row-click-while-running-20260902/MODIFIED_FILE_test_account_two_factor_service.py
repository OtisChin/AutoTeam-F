from autotoken.api_routes.account_overview import _dashboard_accounts_payload
from autotoken.api_routes.task_actions import AccountTwoFactorSetupParams, create_task_actions_router
from autotoken.services import account_two_factor
from autotoken.services.chatgpt_2fa_setup import ChatGPT2FASetupResult, ChatGPT2FASetupStatus


class _MailClient:
    def login(self):
        return "ok"


class _Executor:
    def __init__(self, *, email_code_provider, save_metadata):
        self.email_code_provider = email_code_provider
        self.save_metadata = save_metadata

    def enable(self, email, session_data, *, progress=None):
        assert session_data == {"sessionToken": f"session:{email}"}
        return ChatGPT2FASetupResult(ChatGPT2FASetupStatus.ENABLED, email, masked_secret="ABCD…WXYZ")


def test_protocol_setup_batches_unconfigured_accounts_and_reports_skips():
    accounts = [
        {"email": "new@example.com", "two_factor_enabled": False, "cloudmail_account_id": "mail-1"},
        {"email": "done@example.com", "two_factor_enabled": True, "totp_status": "enabled"},
    ]

    progress_events = []

    result = account_two_factor.setup_accounts_two_factor_protocol(
        ["new@example.com", "done@example.com", "missing@example.com"],
        accounts_loader=lambda: accounts,
        session_loader=lambda email: {"sessionToken": f"session:{email}"} if email == "new@example.com" else {},
        mail_client_factory=lambda _account: _MailClient(),
        executor_factory=lambda **kwargs: _Executor(**kwargs),
        save_metadata=lambda **_kwargs: None,
        otp_waiter=lambda *_args, **_kwargs: "123456",
        progress=lambda event: progress_events.append(event),
    )

    assert result["total"] == 3
    assert [item["email"] for item in result["enabled"]] == ["new@example.com"]
    assert result["skipped"] == [{"email": "done@example.com", "reason": "already_enabled"}]
    assert result["failed"] == [{"email": "missing@example.com", "reason": "account_not_found"}]
    assert progress_events[0]["stage"] == "account_2fa_account_started"
    assert progress_events[0]["email"] == "new@example.com"


def test_task_route_submits_protocol_2fa_background_job(monkeypatch):
    captured = {}
    progress_events = []
    log_messages = []

    class FakeLogger:
        def info(self, message, *args):
            log_messages.append(message % args if args else message)

    def start_task(command, func, params, *args, **kwargs):
        captured.update(command=command, func=func, params=params, args=args, kwargs=kwargs)
        return {"task_id": "task-2fa", "command": command, "status": "pending"}

    def fake_setup(emails, *, progress=None, **_kwargs):
        progress({"stage": "unit_progress", "message": "单测进度"})
        return {"total": len(emails), "enabled": [], "skipped": [], "failed": []}

    monkeypatch.setattr(account_two_factor, "setup_accounts_two_factor_protocol", fake_setup)

    router = create_task_actions_router(
        start_task=start_task,
        append_task_progress=lambda task_id, event: progress_events.append((task_id, event)),
        logger=FakeLogger(),
    )
    endpoint = next(route.endpoint for route in router.routes if route.path == "/api/accounts/2fa/setup")
    response = endpoint(AccountTwoFactorSetupParams(emails=["one@example.com", "one@example.com"]))

    assert response["task_id"] == "task-2fa"
    assert captured["command"] == "setup-2fa"
    assert captured["params"] == {"emails": ["one@example.com"]}
    assert captured["kwargs"]["pass_task_id"] is True
    assert captured["kwargs"]["exclusive"] is False

    assert captured["func"]("task-2fa") == {"total": 1, "enabled": [], "skipped": [], "failed": []}
    assert progress_events[0][0] == "task-2fa"
    assert progress_events[0][1]["stage"] == "account_2fa_started"
    assert progress_events[1][1]["stage"] == "unit_progress"
    assert "[2FA] 单测进度" in log_messages


def test_dashboard_projection_keeps_two_factor_status_fields():
    payload = _dashboard_accounts_payload(
        [
            {
                "email": "enabled@example.com",
                "two_factor_enabled": True,
                "totp_status": "enabled",
            }
        ]
    )

    fields = payload["fields"]
    row = payload["rows"][0]
    assert row[fields.index("two_factor_enabled")] is True
    assert row[fields.index("totp_status")] == "enabled"
