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
