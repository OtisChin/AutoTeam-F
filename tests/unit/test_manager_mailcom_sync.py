from autotoken.interfaces import manager


def test_sync_provider_registered_email_marks_mailcom(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "autotoken.storage.mail_accounts.mark_mailcom_registered",
        lambda email, **kwargs: calls.append((email, kwargs)) or {"email": email},
    )

    manager._sync_provider_registered_email(
        "one@mail.com",
        mail_provider="mail.com",
        password="gpt-pass",
        refresh_token="rt-new",
        source="auth_session_saved",
    )

    assert calls == [
        (
            "one@mail.com",
            {
                "gpt_password": "gpt-pass",
                "refresh_token": "rt-new",
                "source": "auth_session_saved",
            },
        )
    ]


def test_sync_provider_registered_email_keeps_outlook_behavior(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "autotoken.storage.outlook_pool.mark_registered_email",
        lambda email, source="": calls.append((email, source)),
    )

    manager._sync_provider_registered_email("one@outlook.com", mail_provider="outlook", source="register_success")

    assert calls == [("one@outlook.com", "register_success")]


def test_save_codex_oauth_bundle_uses_generic_sync_helper(monkeypatch):
    sync_calls = []

    monkeypatch.setattr(manager, "_mark_outlook_email_registered", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy wrapper should not be used")))
    monkeypatch.setattr(
        manager,
        "_sync_provider_registered_email",
        lambda *args, **kwargs: sync_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(manager, "save_auth_file", lambda bundle: "data/auths/codex-one@mail.com-free.json")
    monkeypatch.setattr(manager, "add_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        manager.registration,
        "free_codex_oauth_update_fields",
        lambda **kwargs: kwargs,
    )

    manager._save_codex_oauth_bundle_for_account(
        "one@mail.com",
        "pw-1",
        "mail-1",
        {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "id_token": "id-1",
        },
        mail_provider="mail.com",
        source="protocol_oauth",
    )

    assert sync_calls == [
        (
            ("one@mail.com",),
            {
                "mail_provider": "mail.com",
                "password": "pw-1",
                "refresh_token": "refresh-1",
                "source": "protocol_oauth",
            },
        )
    ]


def test_duplicate_email_path_uses_generic_sync_helper(monkeypatch):
    sync_calls = []
    register_attempts = {"count": 0}

    class FakeMailClient:
        provider_name = "mail.com"

        def create_registration_email(self, prefix=None, domain=None):
            return ("mail-2", "first@mail.com") if not sync_calls else ("mail-3", "second@mail.com")

    from autotoken.auth.invite import RegisterBlocked

    monkeypatch.setattr(manager, "_mark_outlook_email_registered", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy wrapper should not be used")))
    monkeypatch.setattr(
        manager,
        "_sync_provider_registered_email",
        lambda *args, **kwargs: sync_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(manager, "_save_auth_from_session_page", lambda email, *args, **kwargs: {"email": email})
    monkeypatch.setattr(manager, "record_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.registration, "replace_direct_registration_outcome", lambda *args, **kwargs: None)

    def fake_register_once(*args, **kwargs):
        register_attempts["count"] += 1
        if register_attempts["count"] == 1:
            raise RegisterBlocked("email_submit", "duplicate email", is_duplicate=True)
        return True, {"data": {"sessionToken": "session-1"}}

    monkeypatch.setattr(manager, "_register_direct_once", fake_register_once)

    result = manager.create_account_direct(FakeMailClient(), password="pw-2", check_team_membership=False)

    assert result == {"email": "second@mail.com"}
    assert sync_calls[0][0][0] == "first@mail.com"
    assert sync_calls[0][0][1].provider_name == "mail.com"
    assert sync_calls[0][1] == {"password": "pw-2", "source": "email_already_in_use"}


def test_register_blocked_detects_account_deactivated_page():
    from autotoken.auth.invite import RegisterBlocked, assert_not_blocked

    class FakeLocator:
        def inner_text(self, timeout=1000):
            return (
                "身份验证错误\n"
                "你没有账户，因为该账户已被删除或停用。\n"
                "错误代码：account_deactivated"
            )

    class FakePage:
        url = "https://auth.openai.com/email-verification"

        def locator(self, selector):
            assert selector == "body"
            return FakeLocator()

        def inner_text(self, selector):
            assert selector == "body"
            return FakeLocator().inner_text()

    try:
        assert_not_blocked(FakePage(), "code_submit")
    except RegisterBlocked as exc:
        assert exc.is_account_deactivated is True
        assert exc.reason == "account_deactivated"
        assert exc.step == "code_submit"
    else:
        raise AssertionError("account_deactivated page should block registration")


def test_account_deactivated_stops_direct_registration_without_retry(monkeypatch):
    from autotoken.auth.invite import RegisterBlocked

    calls = {"register": 0}
    failures = []
    outcomes = []
    sync_calls = []

    class FakeMailClient:
        provider_name = "icloud"

        def create_registration_email(self, prefix=None, domain=None):
            return "mail-1", "dead@icloud.com"

    def fake_register_once(*_args, **_kwargs):
        calls["register"] += 1
        raise RegisterBlocked("code_submit", "account_deactivated", is_account_deactivated=True)

    monkeypatch.setattr(manager, "_register_direct_once", fake_register_once)
    monkeypatch.setattr(manager, "_sync_provider_registered_email", lambda *args, **kwargs: sync_calls.append((args, kwargs)))
    monkeypatch.setattr(manager, "record_failure", lambda *args, **kwargs: failures.append((args, kwargs)))
    monkeypatch.setattr(manager.registration, "replace_direct_registration_outcome", lambda *args, **kwargs: outcomes.append((args, kwargs)))

    result = manager.create_account_direct(FakeMailClient(), password="pw-2", check_team_membership=False)

    assert result is None
    assert calls["register"] == 1
    assert failures[0][0][:3] == (
        "dead@icloud.com",
        "account_deactivated",
        "OpenAI 返回 account_deactivated（step=code_submit）",
    )
    assert sync_calls[0][0][0] == "dead@icloud.com"
    assert sync_calls[0][1] == {"password": "pw-2", "source": "account_deactivated"}
    assert outcomes[-1][1]["status"] == "account_deactivated"


def test_registration_precheck_skips_already_registered_email(monkeypatch):
    sync_calls = []
    register_calls = []
    precheck_calls = []

    class FakeMailClient:
        provider_name = "mail.com"

        def create_registration_email(self, prefix=None, domain=None):
            return ("mail-1", "used@mail.com") if not precheck_calls else ("mail-2", "fresh@mail.com")

    def fake_precheck(email, **kwargs):
        precheck_calls.append((email, kwargs))
        return {"registered": email == "used@mail.com", "reason": "email already exists"}

    def fake_register_once(_mail_client, email, *_args, **_kwargs):
        register_calls.append(email)
        return True, {"data": {"sessionToken": "session-1"}}

    monkeypatch.setattr(manager, "_check_registration_email_registered", fake_precheck)
    monkeypatch.setattr(manager, "_sync_provider_registered_email", lambda *args, **kwargs: sync_calls.append((args, kwargs)))
    monkeypatch.setattr(manager, "_register_direct_once", fake_register_once)
    monkeypatch.setattr(manager, "_save_auth_from_session_page", lambda email, *args, **kwargs: {"email": email})
    monkeypatch.setattr(manager, "record_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.registration, "replace_direct_registration_outcome", lambda *args, **kwargs: None)

    result = manager.create_account_direct(FakeMailClient(), password="pw-3", check_team_membership=False)

    assert result == {"email": "fresh@mail.com"}
    assert [call[0] for call in precheck_calls] == ["used@mail.com", "fresh@mail.com"]
    assert register_calls == ["fresh@mail.com"]
    assert sync_calls[0][0][0] == "used@mail.com"
    assert sync_calls[0][1] == {"password": "pw-3", "source": "precheck_email_already_registered"}


def test_registration_precheck_does_not_submit_email_to_openai(monkeypatch):
    calls = []

    def fail_remote_precheck(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("remote OpenAI precheck must not run before browser registration")

    monkeypatch.setattr("autotoken.auth.protocol_register.check_email_registered", fail_remote_precheck)
    monkeypatch.setattr(manager, "load_accounts", lambda: [])

    result = manager._check_registration_email_registered("fresh@mail.com", register_mode="browser")

    assert result["registered"] is False
    assert result["known"] is False
    assert calls == []


def test_direct_registration_failure_retries_after_30_seconds(monkeypatch, caplog):
    progress_events = []
    sleeps = []
    register_calls = []

    class FakeMailClient:
        provider_name = "icloud"

        def create_registration_email(self, prefix=None, domain=None):
            return "mail-1", "retry@icloud.com"

    def fake_register_once(_mail_client, email, *_args, **_kwargs):
        register_calls.append(email)
        return False, {"raw": "not finished"}

    monkeypatch.setattr(manager, "_check_registration_email_registered", lambda *_args, **_kwargs: {"registered": False})
    monkeypatch.setattr(manager, "_register_direct_once", fake_register_once)
    monkeypatch.setattr(manager, "_sync_provider_registered_email", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "record_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.registration, "replace_direct_registration_outcome", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: sleeps.append(seconds))

    with caplog.at_level("WARNING"):
        result = manager.create_account_direct(
            FakeMailClient(),
            password="pw",
            check_team_membership=False,
            progress_callback=progress_events.append,
        )

    assert result is None
    assert register_calls == ["retry@icloud.com", "retry@icloud.com", "retry@icloud.com"]
    assert sleeps == [30, 30]
    retry_messages = [event["message"] for event in progress_events if event.get("stage") == "register_retry_wait"]
    assert retry_messages == [
        "注册未完成，30 秒后重试: retry@icloud.com",
        "注册未完成，30 秒后重试: retry@icloud.com",
    ]
    assert "注册失败，30 秒后重试: retry@icloud.com" in caplog.text
    assert "60 秒后重试" not in caplog.text
