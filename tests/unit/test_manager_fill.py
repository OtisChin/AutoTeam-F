import pytest

from autotoken import manager


class _FakeChatGPT:
    def __init__(self):
        self.browser = True
        self.started = 0
        self.stopped = 0

    def start(self):
        self.browser = True
        self.started += 1

    def stop(self):
        self.browser = False
        self.stopped += 1


class _FakeMailClient:
    def login(self):
        return None


def test_cmd_fill_tries_other_reusable_accounts_before_creating_new(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([4, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "TemporaryEmailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(
        manager,
        "get_standby_accounts",
        lambda: [
            {"email": "old-1@example.com", "_quota_recovered": True},
            {"email": "old-2@example.com", "_quota_recovered": True},
        ],
    )

    def fake_reinvite(_chatgpt, _mail, acc):
        events.append(("reinvite", acc["email"]))
        return acc["email"] == "old-2@example.com"

    monkeypatch.setattr(manager, "reinvite_account", fake_reinvite)
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("reinvite", "old-1@example.com"),
        ("reinvite", "old-2@example.com"),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_skips_google_accounts_during_auto_reuse(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([4, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "TemporaryEmailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(
        manager,
        "get_standby_accounts",
        lambda: [
            {"email": "bubblehuntr@gmail.com", "_quota_recovered": True},
            {"email": "old-2@example.com", "_quota_recovered": True},
        ],
    )

    def fake_reinvite(_chatgpt, _mail, acc):
        events.append(("reinvite", acc["email"]))
        return True

    monkeypatch.setattr(manager, "reinvite_account", fake_reinvite)
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("reinvite", "old-2@example.com"),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_rejects_leave_workspace_without_starting_personal_chain(monkeypatch):
    monkeypatch.setattr(
        manager,
        "_cmd_fill_personal",
        lambda _target: (_ for _ in ()).throw(AssertionError("leave_workspace 链路不应再被调用")),
    )

    with pytest.raises(RuntimeError) as exc_info:
        manager.cmd_fill(target=3, leave_workspace=True)

    assert "Team invite / leave_workspace 注册链路已禁用" in str(exc_info.value)


def test_create_new_account_ignores_pending_team_invites(monkeypatch):
    chatgpt = _FakeChatGPT()
    events = []

    monkeypatch.setattr(
        manager,
        "_check_pending_invites",
        lambda *_args, **_kwargs: events.append("pending") or ["pending@example.com"],
    )
    monkeypatch.setattr(
        manager,
        "create_account_direct",
        lambda *_args, **_kwargs: events.append("direct") or "direct@example.com",
    )

    result = manager.create_new_account(chatgpt, _FakeMailClient())

    assert result == "direct@example.com"
    assert events == ["direct"]


def test_create_account_direct_rejects_leave_workspace_before_mailbox_creation():
    class MailClient:
        def create_temp_email(self, **_kwargs):
            raise AssertionError("不应创建邮箱")

    with pytest.raises(RuntimeError) as exc_info:
        manager.create_account_direct(MailClient(), leave_workspace=True)

    assert "Team invite / leave_workspace 注册链路已禁用" in str(exc_info.value)


def test_run_post_register_oauth_rejects_leave_workspace_before_team_api(monkeypatch):
    monkeypatch.setattr(
        manager,
        "ChatGPTTeamAPI",
        lambda: (_ for _ in ()).throw(AssertionError("不应启动 Team API")),
    )

    with pytest.raises(RuntimeError) as exc_info:
        manager._run_post_register_oauth("user@example.com", "secret", None, leave_workspace=True)

    assert "Team invite / leave_workspace 注册链路已禁用" in str(exc_info.value)


def test_cmd_fill_personal_rejects_before_team_api(monkeypatch):
    monkeypatch.setattr(
        manager,
        "ChatGPTTeamAPI",
        lambda: (_ for _ in ()).throw(AssertionError("不应启动 Team API")),
    )

    with pytest.raises(RuntimeError) as exc_info:
        manager._cmd_fill_personal(2)

    assert "Team invite / leave_workspace 注册链路已禁用" in str(exc_info.value)


def test_auto_reuse_skip_reason_detects_google_provider_and_gmail():
    assert manager._auto_reuse_skip_reason({"email": "bubblehuntr@gmail.com"}) == "Google 登录账号暂不支持自动复用"
    assert (
        manager._auto_reuse_skip_reason({"email": "user@example.com", "login_provider": "google"})
        == "Google 登录账号暂不支持自动复用"
    )
    assert manager._auto_reuse_skip_reason({"email": "user@example.com"}) is None
