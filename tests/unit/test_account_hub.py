import json

from autoteam import account_hub
from autoteam import accounts as accounts_mod
from autoteam import auth_session_store


def test_receive_payload_upserts_accounts_preserves_exported_state_and_auth(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    auth_session_dir = tmp_path / "data" / "auth_session"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", auth_session_dir)

    accounts_mod.save_accounts(
        [
            {
                "email": "user@example.com",
                "password": "old",
                "status": "active",
                "credentials_exported": True,
                "credentials_exported_at": 123,
            }
        ]
    )

    result = account_hub.receive_payload(
        {
            "source": {"name": "pc-01", "uploaded_at": 456},
            "accounts": [
                {
                    "email": "USER@example.com",
                    "password": "new",
                    "status": "plus",
                    "credentials_exported": False,
                },
                {
                    "email": "new@example.com",
                    "password": "pw",
                    "status": "active",
                    "credentials_exported": True,
                    "credentials_exported_at": 456,
                },
            ],
            "auths": [
                {
                    "email": "user@example.com",
                    "filename": "codex-user@example.com-plus-abcd1234.json",
                    "data": {"email": "user@example.com", "type": "codex"},
                }
            ],
            "auth_sessions": [
                {
                    "email": "new@example.com",
                    "data": {
                        "accessToken": "access-session",
                        "sessionToken": "session-token",
                        "account": {"id": "account-id"},
                    },
                }
            ],
        }
    )

    saved = {acc["email"]: acc for acc in accounts_mod.load_accounts()}
    assert result["received_accounts"] == 2
    assert result["received_auths"] == 1
    assert saved["user@example.com"]["password"] == "new"
    assert saved["user@example.com"]["status"] == "plus"
    assert saved["user@example.com"]["hub_source_name"] == "pc-01"
    assert saved["user@example.com"]["account_hub_synced"] is True
    assert saved["user@example.com"]["account_hub_synced_at"] == 456
    assert saved["user@example.com"]["auth_file"] == str(auth_dir / "codex-user@example.com-plus-abcd1234.json")
    assert saved["user@example.com"]["credentials_exported"] is True
    assert saved["user@example.com"]["credentials_exported_at"] == 123
    assert saved["new@example.com"]["hub_source_name"] == "pc-01"
    assert saved["new@example.com"]["credentials_exported"] is False
    assert saved["new@example.com"]["credentials_exported_at"] is None

    auth_file = auth_dir / "codex-user@example.com-plus-abcd1234.json"
    assert json.loads(auth_file.read_text())["email"] == "user@example.com"
    assert auth_session_store.load_auth_session("new@example.com")["accessToken"] == "access-session"
    assert result["received_auth_sessions"] == 1


def test_auto_upload_only_syncs_plus_team_pro_and_marks_uploaded(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)

    accounts_mod.save_accounts(
        [
            {"email": "plus@example.com", "status": "active", "account_type": "plus"},
            {"email": "team@example.com", "status": "active", "account_type": "team"},
            {"email": "pro@example.com", "status": "active", "account_type": "pro"},
            {"email": "free@example.com", "status": "active", "account_type": "free"},
            {"email": "bad@example.com", "status": "fail", "account_type": "plus"},
            {"email": "done@example.com", "status": "active", "account_type": "plus", "account_hub_synced": True},
        ]
    )

    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"received_accounts": len(captured["json"]["accounts"])}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(account_hub.requests, "post", fake_post)

    result = account_hub.upload_to_hub(
        {"url": "http://hub.local", "token": "secret", "name": "pc-01", "auto_upload": True},
        syncable_only=True,
    )

    uploaded = {acc["email"] for acc in captured["json"]["accounts"]}
    assert uploaded == {"plus@example.com", "team@example.com", "pro@example.com"}
    assert result["uploaded_accounts"] == 3
    assert result["marked_synced_accounts"] == 3

    saved = {acc["email"]: acc for acc in accounts_mod.load_accounts()}
    assert saved["plus@example.com"]["account_hub_synced"] is True
    assert saved["team@example.com"]["account_hub_synced"] is True
    assert saved["pro@example.com"]["account_hub_synced"] is True
    assert not saved["free@example.com"].get("account_hub_synced")
    assert not saved["bad@example.com"].get("account_hub_synced")


def test_upload_to_hub_can_limit_to_selected_emails(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    auth_session_dir = tmp_path / "data" / "auth_session"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", auth_session_dir)

    accounts_mod.save_accounts(
        [
            {"email": "one@example.com", "status": "active", "account_type": "plus"},
            {"email": "two@example.com", "status": "active", "account_type": "free"},
            {"email": "three@example.com", "status": "active", "account_type": "team"},
        ]
    )
    auth_session_store.save_auth_session(
        "two@example.com",
        {"accessToken": "access-free", "sessionToken": "session-free"},
    )

    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"received_accounts": len(captured["json"]["accounts"])}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(account_hub.requests, "post", fake_post)

    result = account_hub.upload_to_hub(
        {"url": "http://hub.local", "token": "secret", "name": "pc-01"},
        selected_emails=["TWO@example.com", "missing@example.com", "two@example.com", "three@example.com"],
    )

    uploaded = [acc["email"] for acc in captured["json"]["accounts"]]
    assert uploaded == ["two@example.com", "three@example.com"]
    assert captured["json"]["auth_sessions"] == [
        {"email": "two@example.com", "data": {"accessToken": "access-free", "sessionToken": "session-free"}}
    ]
    assert result["uploaded_auth_sessions"] == 1
    assert result["marked_synced_accounts"] == 2

    saved = {acc["email"]: acc for acc in accounts_mod.load_accounts()}
    assert not saved["one@example.com"].get("account_hub_synced")
    assert saved["two@example.com"]["account_hub_synced"] is True
    assert saved["three@example.com"]["account_hub_synced"] is True


def test_build_upload_payload_enriches_luckmail_token_from_config(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    luckmail_file = tmp_path / "luckmail_accounts.txt"
    luckmail_file.write_text("user@example.com----tok_user_123\nother@example.com----tok_other\n", encoding="utf-8")
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setenv("LUCKMAIL_ACCOUNTS_FILE", str(luckmail_file))
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)

    accounts_mod.save_accounts(
        [
            {
                "email": "USER@example.com",
                "status": "active",
                "account_type": "plus",
                "cloudmail_account_id": None,
                "mail_provider": None,
                "credentials_exported": True,
                "credentials_exported_at": 123,
            }
        ]
    )

    payload = account_hub.build_upload_payload(selected_emails=["user@example.com"])

    assert payload["accounts"][0]["email"] == "user@example.com"
    assert payload["accounts"][0]["cloudmail_account_id"] == "tok_user_123"
    assert payload["accounts"][0]["mail_provider"] == "luckmail"
    assert "credentials_exported" not in payload["accounts"][0]
    assert "credentials_exported_at" not in payload["accounts"][0]


def test_build_upload_payload_restores_missing_luckmail_token_from_purchases(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setenv("LUCKMAIL_API_KEY", "luck_test")
    monkeypatch.setenv("LUCKMAIL_BASE_URL", "https://mail.example.test")
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS_FILE", raising=False)
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)
    monkeypatch.setattr(account_hub, "_luckmail_purchase_cache", None)

    accounts_mod.save_accounts(
        [
            {
                "email": "USER@outlook.com",
                "status": "active",
                "account_type": "plus",
                "cloudmail_account_id": None,
                "mail_provider": "luckmail",
            }
        ]
    )

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "data": {
                    "total": 1,
                    "list": [
                        {
                            "email_address": "user@outlook.com",
                            "token": "tok_restored",
                        }
                    ],
                }
            }

    def fake_get(url, headers, params, timeout):
        assert url == "https://mail.example.test/api/v1/openapi/email/purchases"
        assert headers["X-API-Key"] == "luck_test"
        assert params["page"] == 1
        return FakeResponse()

    monkeypatch.setattr(account_hub.requests, "get", fake_get)

    payload = account_hub.build_upload_payload(selected_emails=["user@outlook.com"])

    assert payload["accounts"][0]["cloudmail_account_id"] == "tok_restored"
    assert payload["accounts"][0]["mail_provider"] == "luckmail"
    saved = {acc["email"].lower(): acc for acc in accounts_mod.load_accounts()}
    assert saved["user@outlook.com"]["cloudmail_account_id"] == "tok_restored"
    assert saved["user@outlook.com"]["mail_provider"] == "luckmail"


def test_receive_payload_preserves_existing_luckmail_token_when_incoming_is_empty(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)

    accounts_mod.save_accounts(
        [
            {
                "email": "user@example.com",
                "status": "active",
                "account_type": "plus",
                "cloudmail_account_id": "tok_existing",
                "mail_provider": "luckmail",
            }
        ]
    )

    account_hub.receive_payload(
        {
            "source": {"name": "pc-01", "uploaded_at": 456},
            "accounts": [
                {
                    "email": "user@example.com",
                    "status": "active",
                    "account_type": "plus",
                    "cloudmail_account_id": None,
                    "mail_provider": None,
                }
            ],
        }
    )

    saved = {acc["email"]: acc for acc in accounts_mod.load_accounts()}
    assert saved["user@example.com"]["cloudmail_account_id"] == "tok_existing"
    assert saved["user@example.com"]["mail_provider"] == "luckmail"
