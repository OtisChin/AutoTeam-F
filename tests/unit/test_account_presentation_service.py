import json

from autotoken.services import account_presentation
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


def _normalize_email(value):
    return str(value or "").strip().lower()


def test_quota_snapshot_status_uses_classified_window_percentages():
    assert account_presentation.quota_snapshot_status(None) == ""
    assert account_presentation.quota_snapshot_status({"primary_pct": "100"}) == ""
    assert account_presentation.quota_snapshot_status({"primary_pct": 99, "weekly_pct": 20}) == "active"
    assert account_presentation.quota_snapshot_status({"primary_pct": 40, "weekly_pct": 100}) == "exhausted"
    assert account_presentation.quota_snapshot_status({"monthly_pct": 100}) == "exhausted"

def test_display_account_type_preserves_explicit_type_and_falls_back_from_status():
    assert account_presentation.display_account_type({"account_type": "Pro", "status": "active"}) == "pro"
    assert account_presentation.display_account_type({"status": "plus"}) == "plus"
    assert account_presentation.display_account_type({"status": "personal"}) == "free"
    assert account_presentation.display_account_type({"status": "active"}) == "team"
    assert account_presentation.display_account_type({"status": "unknown"}) == "free"


def test_sanitize_account_displays_token_expired_quota_failure_as_auth_invalid():
    sanitized = account_presentation.sanitize_account_with_indexes(
        {
            "email": "user@example.com",
            "status": "fail",
            "discarded_reason": "quota_refresh_401",
            "last_bind_message": "刷新额度返回 401: token_expired: Provided authentication token is expired.，账号已标记为 Fail/废弃",
        },
        None,
        {},
        {},
        "",
        normalize_email=lambda value: str(value or "").strip().lower(),
        resolve_status_auth_file_func=lambda _account: "",
        resolve_codex_auth_file_func=lambda _account: "",
    )

    assert sanitized["raw_status"] == "fail"
    assert sanitized["status"] == "auth_invalid"


def test_sanitize_account_displays_token_invalidated_quota_failure_as_auth_revoked():
    sanitized = account_presentation.sanitize_account_with_indexes(
        {
            "email": "user@example.com",
            "status": "fail",
            "discarded_reason": "quota_refresh_401",
            "last_bind_message": (
                "刷新额度返回 401: token_invalidated: Your authentication token has been invalidated. "
                "Please try signing in again.，账号已标记为 Fail/废弃"
            ),
        },
        None,
        {},
        {},
        "",
        normalize_email=lambda value: str(value or "").strip().lower(),
        resolve_status_auth_file_func=lambda _account: "",
        resolve_codex_auth_file_func=lambda _account: "",
    )

    assert sanitized["raw_status"] == "fail"
    assert sanitized["status"] == "auth_revoked"


def test_sanitize_account_exposes_display_email_from_original_email():
    sanitized = account_presentation.sanitize_account_with_indexes(
        {"email": "amandamiller143152@hotmail.com", "original_email": "AmandaMiller143152@hotmail.com", "status": "active"},
        None,
        {},
        {},
        "",
        normalize_email=lambda value: str(value or "").strip().lower(),
        resolve_status_auth_file_func=lambda _account: "",
        resolve_codex_auth_file_func=lambda _account: "",
    )

    assert sanitized["email"] == "amandamiller143152@hotmail.com"
    assert sanitized["display_email"] == "AmandaMiller143152@hotmail.com"

def test_sanitize_account_uses_outlook_source_email_for_existing_lowercase_account():
    sanitized = account_presentation.sanitize_account_with_indexes(
        {"email": "amandamiller143152@hotmail.com", "mail_provider": "outlook", "status": "active"},
        None,
        {},
        {},
        "",
        normalize_email=lambda value: str(value or "").strip().lower(),
        resolve_status_auth_file_func=lambda _account: "",
        resolve_codex_auth_file_func=lambda _account: "",
        outlook_accounts={
            "amandamiller143152@hotmail.com": {
                "email": "AmandaMiller143152@hotmail.com",
            }
        },
    )

    assert sanitized["email"] == "amandamiller143152@hotmail.com"
    assert sanitized["display_email"] == "AmandaMiller143152@hotmail.com"

def test_codex_auth_file_is_synthetic_checks_flag_and_token(tmp_path):
    flagged = tmp_path / "flagged.json"
    flagged.write_text(json.dumps({"id_token_synthetic": True}), encoding="utf-8")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"idToken": "header.synthetic.signature"}), encoding="utf-8")
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"id_token": "header.real.signature"}), encoding="utf-8")

    assert account_presentation.codex_auth_file_is_synthetic(str(flagged)) is True
    assert account_presentation.codex_auth_file_is_synthetic(str(token)) is True
    assert account_presentation.codex_auth_file_is_synthetic(str(real)) is False
    assert account_presentation.codex_auth_file_is_synthetic(str(tmp_path / "missing.json")) is False

def test_codex_auth_file_is_synthetic_ignores_oversized_auth_file(tmp_path):
    auth_file = tmp_path / "huge.json"
    auth_file.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")

    assert account_presentation.codex_auth_file_is_synthetic(str(auth_file)) is False

def test_resolve_status_auth_file_accepts_account_auth_inside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus.json"
    auth_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)

    assert (
        account_presentation.resolve_status_auth_file(
            {"email": "user@example.com", "auth_file": str(auth_file)},
            is_main_account_email=lambda _email: False,
        )
        == str(auth_file)
    )

def test_resolve_status_auth_file_ignores_account_auth_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.auth_session_store.get_auth_session_file", lambda _email: "")

    assert (
        account_presentation.resolve_status_auth_file(
            {"email": "user@example.com", "auth_file": str(outside)},
            is_main_account_email=lambda _email: False,
        )
        == ""
    )

def test_resolve_codex_auth_file_ignores_account_auth_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    inside = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    inside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)

    assert (
        account_presentation.resolve_codex_auth_file(
            {"email": "user@example.com", "auth_file": str(outside)},
            normalize_email=_normalize_email,
        )
        == str(inside)
    )

def test_sanitize_account_with_indexes_removes_secrets_and_marks_indexed_auth(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus.json"
    auth_file.write_text(json.dumps({"id_token_synthetic": True}), encoding="utf-8")
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)

    sanitized = account_presentation.sanitize_account_with_indexes(
        {
            "email": "User@Example.COM",
            "password": "secret",
            "cloudmail_account_id": "cloud-1",
            "status": "active",
            "credentials_exported": 1,
            "account_hub_synced": "",
        },
        None,
        {"user@example.com": {"file_path": str(auth_file), "synthetic": True}},
        {"user@example.com": "session.json"},
        "",
        normalize_email=_normalize_email,
        resolve_status_auth_file_func=lambda _account: "",
        resolve_codex_auth_file_func=lambda _account: "",
    )

    assert "password" not in sanitized
    assert "cloudmail_account_id" not in sanitized
    assert sanitized["is_main_account"] is False
    assert sanitized["account_type"] == "team"
    assert sanitized["credentials_exported"] is True
    assert sanitized["account_hub_synced"] is False
    assert sanitized["codex_auth_file"] == str(auth_file)
    assert sanitized["codex_auth_synthetic"] is True
    assert sanitized["needs_codex_login"] is True
    assert sanitized["auth_session_file"] == "session.json"

def test_sanitize_account_with_indexes_ignores_indexed_auth_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside-indexed-auth.json"
    outside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("autotoken.auth_storage.AUTH_DIR", auth_dir)

    sanitized = account_presentation.sanitize_account_with_indexes(
        {"email": "User@Example.COM", "status": "active"},
        None,
        {"user@example.com": {"file_path": str(outside), "synthetic": True}},
        {},
        "",
        normalize_email=_normalize_email,
        resolve_status_auth_file_func=lambda _account: "",
        resolve_codex_auth_file_func=lambda _account: "",
    )

    assert sanitized["codex_auth_file"] == ""
    assert sanitized["has_codex_auth_file"] is False
    assert sanitized["codex_auth_synthetic"] is False

def test_sanitize_account_with_indexes_uses_main_fallback_auth_file():
    sanitized = account_presentation.sanitize_account_with_indexes(
        {"email": "owner@example.com", "status": "exhausted"},
        None,
        {},
        {},
        "owner@example.com",
        normalize_email=_normalize_email,
        resolve_status_auth_file_func=lambda _account: "",
        resolve_codex_auth_file_func=lambda _account: "main-auth.json",
    )

    assert sanitized["is_main_account"] is True
    assert sanitized["status"] == "exhausted"
    assert sanitized["codex_auth_file"] == "main-auth.json"
    assert sanitized["needs_codex_login"] is False


def test_display_account_type_prefers_wham_plan_type_snapshot():
    assert account_presentation.display_account_type({"account_type": "free", "last_quota": {"plan_type": "plus"}}) == "plus"
    assert account_presentation.display_account_type({"account_type": "plus", "last_quota": {"plan_type": "free"}}) == "plus"
    assert account_presentation.display_account_type({"account_type": "free", "last_quota": {"plan_type": "business"}}) == "team"
