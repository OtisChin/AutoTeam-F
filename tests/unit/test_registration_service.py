import pytest

from autotoken.accounts import (
    ACCOUNT_SOURCE_MANAGED,
    ACCOUNT_TYPE_FREE,
    SEAT_CHATGPT,
    SEAT_CODEX,
    STATUS_ACTIVE,
    STATUS_PERSONAL,
)
from autotoken.auth import go_protocol_register, protocol_register
from autotoken.interfaces import manager
from autotoken.services import registration


class FakeMailClient:
    def login(self):
        pass


def test_register_by_mode_dispatches_go_only(monkeypatch):
    calls = []
    monkeypatch.setattr(
        go_protocol_register,
        "register_once",
        lambda *args, **kwargs: calls.append(("go", args, kwargs)) or (True, {}),
    )
    monkeypatch.setattr(
        protocol_register,
        "register_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Python called")),
    )

    ok, _ = manager._register_by_mode(
        "go_protocol",
        FakeMailClient(),
        email="user@example.com",
        password="pw",
    )

    assert ok is True
    assert [call[0] for call in calls] == ["go"]


def test_register_by_mode_dispatches_python_protocol_only(monkeypatch):
    calls = []
    monkeypatch.setattr(
        protocol_register,
        "register_once",
        lambda *args, **kwargs: calls.append(("python", args, kwargs)) or (True, {}),
    )
    monkeypatch.setattr(
        go_protocol_register,
        "register_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Go called")),
    )

    ok, _ = manager._register_by_mode(
        "protocol",
        FakeMailClient(),
        email="user@example.com",
        password="pw",
    )

    assert ok is True
    assert [call[0] for call in calls] == ["python"]


@pytest.mark.parametrize(
    ("register_mode", "want_roxy", "want_cloak"),
    [
        ("browser", False, False),
        ("protocol", False, False),
        ("go_protocol", False, False),
        ("roxy", True, False),
        ("cloak", False, True),
    ],
)
def test_cmd_register_accounts_propagates_normalized_mode(
    monkeypatch,
    register_mode,
    want_roxy,
    want_cloak,
):
    captured = {}

    def fake_create_account_direct(_mail_client, **kwargs):
        captured.update(kwargs)
        kwargs["out_outcome"].update(status="success", email="new@example.com")
        return "new@example.com"

    monkeypatch.setattr(manager, "TemporaryEmailClient", FakeMailClient)
    monkeypatch.setattr(manager, "create_account_direct", fake_create_account_direct)

    result = manager.cmd_register_accounts(
        count=1,
        concurrency=1,
        interval_seconds=0,
        jitter_min_seconds=0,
        jitter_max_seconds=0,
        register_mode=register_mode,
        use_roxybrowser=want_roxy,
        use_cloakbrowser=want_cloak,
    )

    assert result["ok"] == 1
    assert captured["register_mode"] == register_mode
    assert captured["use_roxybrowser"] is want_roxy
    assert captured["use_cloakbrowser"] is want_cloak


def test_replace_outcome_mutates_existing_dict_and_ignores_none():
    outcome = {"status": "old", "stale": True}

    registration.replace_outcome(outcome, email="user@example.com", status="success", plan="team")
    registration.replace_outcome(None, email="ignored@example.com", status="success")

    assert outcome == {"status": "success", "email": "user@example.com", "plan": "team"}


def test_replace_direct_registration_outcome_preserves_attempt_counters():
    outcome = {"status": "old", "stale": True}

    registration.replace_direct_registration_outcome(
        outcome,
        last_email="last@example.com",
        status="register_failed",
        register_attempts=3,
        duplicate_swaps=2,
        reason="blocked",
    )
    registration.replace_direct_registration_outcome(
        None,
        last_email="ignored@example.com",
        status="success",
        register_attempts=0,
        duplicate_swaps=0,
    )

    assert outcome == {
        "status": "register_failed",
        "last_email": "last@example.com",
        "register_attempts": 3,
        "duplicate_swaps": 2,
        "reason": "blocked",
    }


def test_direct_registration_outcome_allows_extra_fields_to_match_existing_update_semantics():
    assert registration.direct_registration_outcome(
        last_email="last@example.com",
        status="success",
        register_attempts=1,
        duplicate_swaps=0,
        email="result@example.com",
        skipped_post_register=True,
    ) == {
        "status": "success",
        "last_email": "last@example.com",
        "register_attempts": 1,
        "duplicate_swaps": 0,
        "email": "result@example.com",
        "skipped_post_register": True,
    }


def test_register_failed_and_kick_failed_payloads_are_stable():
    assert registration.register_failed_outcome("new@example.com") == {
        "status": "register_failed",
        "reason": registration.INVITE_REGISTER_FAILED_REASON,
        "last_email": "new@example.com",
    }
    assert registration.kick_failed_reason("failed") == "主号踢出失败 status=failed"


def test_success_update_fields_preserve_status_and_seat_contracts():
    assert registration.personal_success_update_fields(auth_file="auth.json", last_active_at=123.0) == {
        "status": STATUS_PERSONAL,
        "seat_type": SEAT_CODEX,
        "auth_file": "auth.json",
        "last_active_at": 123.0,
    }
    assert registration.team_success_update_fields(
        plan_type="team",
        auth_file="team.json",
        last_active_at=456.0,
    ) == {
        "status": STATUS_ACTIVE,
        "seat_type": SEAT_CHATGPT,
        "auth_file": "team.json",
        "last_active_at": 456.0,
    }
    assert registration.team_success_update_fields(
        plan_type="free",
        auth_file="free.json",
        last_active_at=789.0,
    )["seat_type"] == SEAT_CODEX


def test_team_auth_missing_update_fields_keep_account_active():
    assert registration.team_auth_missing_update_fields() == {"status": STATUS_ACTIVE}


def test_auth_session_update_fields_preserve_managed_session_contract():
    assert registration.auth_session_update_fields(last_active_at=111.0) == {
        "status": STATUS_ACTIVE,
        "seat_type": SEAT_CODEX,
        "auth_file": None,
        "account_source": ACCOUNT_SOURCE_MANAGED,
        "last_active_at": 111.0,
    }


def test_free_codex_oauth_update_fields_preserve_free_codex_contract():
    assert registration.free_codex_oauth_update_fields(auth_file="auth.json", last_active_at=222.0) == {
        "status": STATUS_ACTIVE,
        "account_type": ACCOUNT_TYPE_FREE,
        "seat_type": SEAT_CODEX,
        "auth_file": "auth.json",
        "last_active_at": 222.0,
    }


def test_free_codex_oauth_bundle_preserves_tokens_and_forces_free_metadata():
    original = {
        "email": "",
        "access_token": "access",
        "refresh_token": "refresh",
        "plan_type": "plus",
        "chatgpt_plan_type": "team",
    }

    bundle = registration.free_codex_oauth_bundle(original, email="user@example.com")

    assert bundle == {
        "email": "user@example.com",
        "access_token": "access",
        "refresh_token": "refresh",
        "plan_type": "free",
        "chatgpt_plan_type": "free",
    }
    assert original["plan_type"] == "plus"
    assert original["chatgpt_plan_type"] == "team"


def test_free_codex_oauth_bundle_can_force_registration_email():
    bundle = registration.free_codex_oauth_bundle(
        {"email": "stale@example.com", "plan_type": "team"},
        email="new@example.com",
        force_email=True,
    )

    assert bundle["email"] == "new@example.com"
    assert bundle["plan_type"] == "free"
    assert bundle["chatgpt_plan_type"] == "free"


def test_account_codex_oauth_bundle_fills_plus_metadata_and_account_id():
    original = {
        "email": "plus@example.com",
        "access_token": "access",
        "refresh_token": "refresh",
        "plan_type": "unknown",
        "account_id": "",
    }

    bundle = registration.account_codex_oauth_bundle(
        original,
        account_type="plus",
        account_id="acct-plus",
    )

    assert bundle["plan_type"] == "plus"
    assert bundle["chatgpt_plan_type"] == "plus"
    assert bundle["account_id"] == "acct-plus"
    assert original["plan_type"] == "unknown"
    assert original["account_id"] == ""


def test_account_codex_oauth_bundle_does_not_downgrade_known_plus_to_stale_free():
    bundle = registration.account_codex_oauth_bundle(
        {
            "email": "plus@example.com",
            "plan_type": "free",
            "chatgpt_plan_type": "free",
        },
        account_type="plus",
    )

    assert bundle["plan_type"] == "plus"
    assert bundle["chatgpt_plan_type"] == "plus"


def test_free_codex_oauth_result_omits_none_optional_fields():
    assert registration.free_codex_oauth_result(
        email="user@example.com",
        auth_file="auth.json",
        password="pw",
        cloudmail_account_id=None,
        mail_provider="outlook",
        source="protocol_oauth",
    ) == {
        "email": "user@example.com",
        "status": "success",
        "plan_type": "free",
        "auth_file": "auth.json",
        "password": "pw",
        "mail_provider": "outlook",
        "source": "protocol_oauth",
    }
