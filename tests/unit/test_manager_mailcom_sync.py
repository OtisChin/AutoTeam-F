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
