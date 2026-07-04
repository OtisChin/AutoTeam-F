import base64
import json
from pathlib import Path

from autotoken.services.finished_account_import import (
    build_finished_cpa_auth,
    import_finished_accounts_from_text,
    parse_finished_account_text,
)


def _jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return "header." + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") + ".sig"


def test_parse_finished_account_text_accepts_concatenated_json_objects():
    content = (
        json.dumps({"email": "First@Example.com", "access_token": "a", "password": "pw1"}, indent=2)
        + "\n"
        + json.dumps({"email": "second@example.com", "access_token": "b", "password": "pw2"}, indent=2)
    )

    records, invalid = parse_finished_account_text(content, source_name="accounts.json")

    assert invalid == []
    assert [record["email"] for record in records] == ["first@example.com", "second@example.com"]


def test_build_finished_cpa_auth_fills_missing_cpa_fields():
    access_token = _jwt(
        {
            "exp": 1783843075,
            "https://api.openai.com/profile": {"email": "user@example.com"},
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-1",
                "chatgpt_user_id": "user-1",
                "chatgpt_plan_type": "plus",
            },
        }
    )

    auth = build_finished_cpa_auth(
        {
            "email": "USER@example.com",
            "password": "secret",
            "access_token": access_token,
            "expires_at": "2026-07-12T07:57:55.000Z",
            "last_refresh": "2026-07-02T07:58:03.030Z",
        }
    )

    assert auth["type"] == "codex"
    assert auth["email"] == "user@example.com"
    assert auth["account_id"] == "acct-1"
    assert auth["plan_type"] == "plus"
    assert auth["expired"] == "2026-07-12T07:57:55.000Z"
    assert auth["id_token_synthetic"] is True
    assert auth["id_token"].count(".") == 2
    assert auth["refresh_token"].startswith("synthetic-refresh-token-")


def test_import_finished_accounts_writes_cpa_auths_and_updates_accounts(tmp_path, monkeypatch):
    from autotoken import accounts as accounts_module
    from autotoken import auth_storage, cpa_sync

    auth_dir = tmp_path / "auths"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(accounts_module, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", auth_dir)

    access_token = _jwt(
        {
            "exp": 1783843075,
            "https://api.openai.com/profile": {"email": "ready@example.com"},
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-ready",
                "chatgpt_plan_type": "plus",
            },
        }
    )
    accounts_text = json.dumps(
        {
            "email": "ready@example.com",
            "password": "login-password",
            "access_token": access_token,
            "expires_at": "2026-07-12T07:57:55.000Z",
            "last_refresh": "2026-07-02T07:58:03.030Z",
        },
        indent=2,
    )
    mailboxes_text = "ready@example.com----mail-password----client-id----mail-refresh-token\n"

    result = import_finished_accounts_from_text(
        accounts_text,
        mailboxes_text,
        accounts_source_name="accounts.json",
        mailboxes_source_name="mailboxes.txt",
    )

    assert result["imported"] == 1
    assert result["accounts_updated"] == 1
    assert result["mailboxes_matched"] == 1
    assert result["invalid"] == []
    account = accounts_module.find_account(accounts_module.load_accounts(), "ready@example.com")
    assert account["password"] == "login-password"
    assert account["account_type"] == "plus"
    assert account["seat_type"] == "codex"
    assert account["mail_provider"] == "outlook"
    assert account["cloudmail_account_id"] == "ready@example.com"
    auth_path = Path(account["auth_file"])
    assert auth_path.exists()
    saved = json.loads(auth_path.read_text(encoding="utf-8"))
    assert saved["type"] == "codex"
    assert saved["id_token_synthetic"] is True
    assert saved["refresh_token"].startswith("synthetic-refresh-token-")


def test_import_finished_accounts_marks_plus_external_import_with_visible_auth(tmp_path, monkeypatch):
    from autotoken import accounts as accounts_module
    from autotoken import auth_storage, cpa_sync
    from autotoken.services.account_presentation import (
        resolve_codex_auth_file,
        resolve_status_auth_file,
        sanitize_accounts_batch,
    )

    auth_dir = tmp_path / "auths"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(tmp_path / "autotoken.sqlite3"))
    monkeypatch.setattr(accounts_module, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", auth_dir)

    access_token = _jwt(
        {
            "exp": 1783843075,
            "https://api.openai.com/profile": {"email": "external@example.com"},
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-external",
                "chatgpt_plan_type": "free",
            },
        }
    )

    import_finished_accounts_from_text(
        json.dumps(
            {
                "email": "external@example.com",
                "password": "login-password",
                "access_token": access_token,
                "expires_at": "2026-07-12T07:57:55.000Z",
            },
            indent=2,
        )
    )

    account = accounts_module.find_account(accounts_module.load_accounts(), "external@example.com")
    assert account["account_type"] == "plus"
    assert account["status"] == "plus"
    assert account["last_bind_provider"] == "external_import"
    assert account["last_bind_status"] == "success"
    assert account["auth_file"]
    saved = json.loads(Path(account["auth_file"]).read_text(encoding="utf-8"))
    assert saved["plan_type"] == "plus"
    assert saved["chatgpt_plan_type"] == "plus"

    displayed = sanitize_accounts_batch(
        [account],
        None,
        normalize_email=lambda value: str(value or "").strip().lower(),
        is_main_account_email=lambda _email: False,
        resolve_status_auth_file_func=lambda acc: resolve_status_auth_file(acc, is_main_account_email=lambda _email: False),
        resolve_codex_auth_file_func=lambda acc: resolve_codex_auth_file(
            acc,
            normalize_email=lambda value: str(value or "").strip().lower(),
        ),
    )[0]
    assert displayed["account_type"] == "plus"
    assert displayed["last_bind_provider"] == "external_import"
    assert displayed["has_codex_auth_file"] is True
    assert displayed["needs_codex_login"] is False
