import json
import threading
import time
from pathlib import Path

from autotoken import account_hub, auth_session_store
from autotoken import accounts as accounts_mod
from autotoken.core.files import READ_LINES_FILE_MAX_BYTES
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


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
    auth_dir.mkdir(parents=True, exist_ok=True)
    for email in ["plus@example.com", "team@example.com", "pro@example.com", "done@example.com"]:
        (auth_dir / f"codex-{email}-auth.json").write_text("{}", encoding="utf-8")

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


def test_upload_to_hub_splits_large_payload_into_batches(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(account_hub, "UPLOAD_BATCH_MAX_ACCOUNTS", 2)
    monkeypatch.setattr(account_hub, "UPLOAD_BATCH_MAX_BYTES", 1024 * 1024)

    rows = [
        {"email": f"user{index}@example.com", "status": "active", "account_type": "plus"}
        for index in range(5)
    ]
    accounts_mod.save_accounts(rows)
    auth_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        (auth_dir / f"codex-{row['email']}-plus.json").write_text(
            json.dumps({"email": row["email"], "plan_type": "plus"}),
            encoding="utf-8",
        )

    posted = []

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"ok": True}

    def fake_post(url, headers, json, timeout):
        posted.append(json)
        return FakeResponse()

    monkeypatch.setattr(account_hub.requests, "post", fake_post)

    result = account_hub.upload_to_hub(
        {"url": "http://hub.local", "token": "secret", "name": "pc-01"},
        syncable_only=True,
    )

    assert [len(payload["accounts"]) for payload in posted] == [2, 2, 1]
    assert [payload["source"]["batch_index"] for payload in posted] == [1, 2, 3]
    assert all(payload["source"]["batch_count"] == 3 for payload in posted)
    assert result["batch_count"] == 3
    assert result["uploaded_accounts"] == 5
    assert result["uploaded_auths"] == 5
    assert result["marked_synced_accounts"] == 5

    saved = {acc["email"]: acc for acc in accounts_mod.load_accounts()}
    assert all(saved[row["email"]]["account_hub_synced"] is True for row in rows)


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


def test_build_upload_payload_reuses_bounded_auth_file_indexes(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)

    rows = [
        {"email": f"user{index}@example.com", "status": "active", "account_type": "free"}
        for index in range(5)
    ]
    accounts_mod.save_accounts(rows)
    auth_dir.mkdir(parents=True, exist_ok=True)
    for row in rows[:2]:
        (auth_dir / f"codex-{row['email']}-free.json").write_text(
            json.dumps({"email": row["email"], "plan_type": "free"}),
            encoding="utf-8",
        )

    real_iter = account_hub.iter_codex_auth_files
    scan_count = 0

    def counted_iter_codex_auth_files(*, auth_dir=None):
        nonlocal scan_count
        scan_count += 1
        yield from real_iter(auth_dir=auth_dir)

    monkeypatch.setattr(account_hub, "iter_codex_auth_files", counted_iter_codex_auth_files)

    payload = account_hub.build_upload_payload(selected_emails=[row["email"] for row in rows])

    assert [item["email"] for item in payload["auths"]] == ["user0@example.com", "user1@example.com"]
    assert scan_count == 1


def test_build_upload_payload_loads_auth_sessions_in_one_bulk_query(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)

    rows = [
        {"email": f"user{index}@example.com", "status": "active", "account_type": "free"}
        for index in range(200)
    ]
    accounts_mod.save_accounts(rows)
    bulk_calls = []
    per_account_calls = []
    session_records = [
        {
            "email": row["email"],
            "data": {"accessToken": f"access-{index}"},
        }
        for index, row in enumerate(rows)
        if index % 50 == 0
    ]

    def list_records():
        bulk_calls.append(True)
        return session_records

    def load_one(email):
        per_account_calls.append(email)
        return {}

    monkeypatch.setattr(auth_session_store, "list_auth_session_records", list_records)
    monkeypatch.setattr(auth_session_store, "load_auth_session", load_one)

    payload = account_hub.build_upload_payload()

    assert [item["email"] for item in payload["auth_sessions"]] == [
        "user0@example.com",
        "user50@example.com",
        "user100@example.com",
        "user150@example.com",
    ]
    assert bulk_calls == [True]
    assert per_account_calls == []


def test_build_upload_payload_skips_auth_session_query_without_accounts(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    accounts_mod.save_accounts([])
    bulk_calls = []

    def list_records():
        bulk_calls.append(True)
        return []

    monkeypatch.setattr(auth_session_store, "list_auth_session_records", list_records)

    payload = account_hub.build_upload_payload()

    assert payload["accounts"] == []
    assert payload["auth_sessions"] == []
    assert bulk_calls == []


def test_account_hub_private_email_normalizer_matches_core_helper():
    from autotoken.core.normalization import normalized_email

    assert account_hub._normalized_email(" USER@example.com ") == normalized_email(" USER@example.com ")
    assert account_hub._filter_accounts_by_emails(
        [{"email": " USER@example.com "}, {"email": "two@example.com"}],
        ["user@example.com", "TWO@example.com", "user@example.com"],
    ) == [{"email": " USER@example.com "}, {"email": "two@example.com"}]


def test_auth_candidates_ignore_account_auth_file_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "data" / "auths"
    auth_dir.mkdir(parents=True)
    outside = tmp_path / "outside-auth.json"
    outside.write_text("{}", encoding="utf-8")
    inside = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    inside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)

    candidates = account_hub._auth_candidates_for_account(
        {
            "email": "user@example.com",
            "auth_file": str(outside),
        }
    )

    assert candidates == [inside.resolve()]


def test_build_upload_payload_skips_oversized_auth_file(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    auth_dir.mkdir(parents=True)
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)

    accounts_mod.save_accounts(
        [
            {
                "email": "user@example.com",
                "status": "active",
                "account_type": "plus",
                "auth_file": str(auth_file),
            }
        ]
    )

    payload = account_hub.build_upload_payload(selected_emails=["user@example.com"])

    assert payload["accounts"][0]["email"] == "user@example.com"
    assert payload["auths"] == []


def test_auto_upload_skips_accounts_without_credentials(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    auth_session_dir = tmp_path / "data" / "auth_session"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", auth_session_dir)

    accounts_mod.save_accounts(
        [
            {"email": "plus@example.com", "status": "active", "account_type": "plus"},
            {"email": "team@example.com", "status": "active", "account_type": "team"},
            {"email": "pro@example.com", "status": "active", "account_type": "pro"},
            {"email": "free@example.com", "status": "active", "account_type": "free"},
        ]
    )
    (auth_dir / "codex-plus@example.com-plus.json").parent.mkdir(parents=True, exist_ok=True)
    (auth_dir / "codex-plus@example.com-plus.json").write_text("{}", encoding="utf-8")

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
        syncable_only=True,
    )

    uploaded = {acc["email"] for acc in captured["json"]["accounts"]}
    assert uploaded == {"plus@example.com"}
    assert result["uploaded_accounts"] == 1


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


def test_build_upload_payload_skips_oversized_luckmail_token_file(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    luckmail_file = tmp_path / "luckmail_accounts.txt"
    luckmail_file.write_text("x" * (READ_LINES_FILE_MAX_BYTES + 1), encoding="utf-8")
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setenv("LUCKMAIL_ACCOUNTS_FILE", str(luckmail_file))
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)
    monkeypatch.delenv("LUCKMAIL_API_KEY", raising=False)

    accounts_mod.save_accounts(
        [
            {
                "email": "USER@example.com",
                "status": "active",
                "account_type": "plus",
                "cloudmail_account_id": None,
                "mail_provider": None,
            }
        ]
    )

    payload = account_hub.build_upload_payload(selected_emails=["user@example.com"])

    assert payload["accounts"][0]["cloudmail_account_id"] is None
    assert payload["accounts"][0]["mail_provider"] is None


def test_build_upload_payload_normalizes_plus_auth_plan_type(tmp_path, monkeypatch):
    from autotoken import cpa_sync

    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    auth_dir.mkdir(parents=True)
    auth_file = auth_dir / "codex-user@example.com-unknown-deadbeef.json"
    auth_file.write_text(
        json.dumps(
            {
                "type": "codex",
                "email": "user@example.com",
                "account_id": "acc-user",
                "access_token": "access-token",
                "id_token": "id-token",
                "refresh_token": "refresh-token",
                "expired": "2030-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", auth_dir)

    accounts_mod.save_accounts(
        [
            {
                "email": "USER@example.com",
                "status": "active",
                "account_type": "plus",
                "auth_file": str(auth_file),
            }
        ]
    )

    payload = account_hub.build_upload_payload(selected_emails=["user@example.com"])

    assert payload["auths"][0]["data"]["plan_type"] == "plus"
    assert payload["auths"][0]["data"]["chatgpt_plan_type"] == "plus"
    assert payload["auths"][0]["filename"].startswith("codex-user@example.com-plus-")
    saved = {acc["email"]: acc for acc in accounts_mod.load_accounts()}
    assert Path(saved["user@example.com"]["auth_file"]).name.startswith("codex-user@example.com-plus-")


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


def test_luckmail_restore_preserves_account_added_during_persistence(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    luckmail_file = tmp_path / "luckmail_accounts.txt"
    luckmail_file.write_text("restore@example.com----tok_restored\n", encoding="utf-8")
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setenv("LUCKMAIL_ACCOUNTS_FILE", str(luckmail_file))
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)

    accounts_mod.save_accounts(
        [
            {
                "email": "restore@example.com",
                "status": "active",
                "account_type": "free",
                "cloudmail_account_id": None,
                "mail_provider": "luckmail",
            }
        ]
    )

    real_save_accounts = accounts_mod.save_accounts
    real_update_account = accounts_mod.update_account
    persistence_calls = {"save": 0, "update": 0}
    persistence_started = threading.Event()
    release_persistence = threading.Event()

    def wait_for_concurrent_write():
        persistence_started.set()
        assert release_persistence.wait(2)

    def racing_save_accounts(accounts):
        persistence_calls["save"] += 1
        wait_for_concurrent_write()
        return real_save_accounts(accounts)

    def racing_update_account(email, **changes):
        persistence_calls["update"] += 1
        wait_for_concurrent_write()
        return real_update_account(email, **changes)

    monkeypatch.setattr(accounts_mod, "save_accounts", racing_save_accounts)
    monkeypatch.setattr(accounts_mod, "update_account", racing_update_account)

    payloads = []
    errors = []

    def build_payload():
        try:
            payloads.append(account_hub.build_upload_payload(selected_emails=["restore@example.com"]))
        except Exception as exc:  # pragma: no cover - asserted below for clearer thread failures
            errors.append(exc)

    build_thread = threading.Thread(target=build_payload)
    build_thread.start()
    assert persistence_started.wait(2)

    add_thread = threading.Thread(
        target=lambda: accounts_mod.add_account("created-during-restore@example.com", "secret")
    )
    add_thread.start()
    add_thread.join(2)
    assert not add_thread.is_alive()

    release_persistence.set()
    build_thread.join(2)
    assert not build_thread.is_alive()
    assert errors == []

    saved = {item["email"]: item for item in accounts_mod.load_accounts()}
    assert payloads[0]["accounts"][0]["cloudmail_account_id"] == "tok_restored"
    assert saved["restore@example.com"]["cloudmail_account_id"] == "tok_restored"
    assert "created-during-restore@example.com" in saved
    assert persistence_calls == {"save": 0, "update": 1}


def test_build_upload_payload_does_not_restore_luckmail_for_providerless_outlook_account(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_dir = tmp_path / "data" / "auths"
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_hub, "AUTH_DIR", auth_dir)
    monkeypatch.setenv("LUCKMAIL_API_KEY", "luck_test")
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS_FILE", raising=False)
    monkeypatch.delenv("LUCKMAIL_ACCOUNTS", raising=False)
    monkeypatch.setattr(account_hub, "_luckmail_purchase_cache", None)

    accounts_mod.save_accounts(
        [
            {
                "email": "imported@outlook.com",
                "status": "active",
                "account_type": "plus",
                "cloudmail_account_id": None,
                "mail_provider": None,
            }
        ]
    )

    def fail_get(*args, **kwargs):
        raise AssertionError("providerless Outlook accounts must not query LuckMail purchases")

    monkeypatch.setattr(account_hub.requests, "get", fail_get)

    payload = account_hub.build_upload_payload(selected_emails=["imported@outlook.com"])

    assert payload["accounts"][0]["email"] == "imported@outlook.com"
    assert payload["accounts"][0]["cloudmail_account_id"] is None
    assert payload["accounts"][0]["mail_provider"] is None


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


def test_upload_to_hub_rejects_overlapping_snapshots_before_building_payload(monkeypatch):
    monkeypatch.setattr(
        account_hub,
        "build_upload_payload",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("a rejected overlap must not build a stale snapshot")),
    )

    assert account_hub._upload_lock.acquire(blocking=False)
    try:
        try:
            account_hub.upload_to_hub(
                {"url": "http://hub.local", "token": "secret", "name": "pc-01"},
                selected_emails=["user@example.com"],
            )
        except account_hub.AccountHubSyncBusyError as exc:
            assert "正在进行" in str(exc)
        else:
            raise AssertionError("overlapping Hub upload must be rejected")
    finally:
        account_hub._upload_lock.release()


def test_mark_accounts_synced_delegates_to_atomic_storage_update(monkeypatch):
    calls = []
    monkeypatch.setattr(
        accounts_mod,
        "mark_accounts_hub_synced",
        lambda emails, *, synced_at: calls.append((list(emails), synced_at)) or len(emails),
    )

    result = account_hub._mark_accounts_synced(
        [
            {"email": "UPLOADED@example.com", "updated_at": 123},
            {"email": "uploaded@example.com", "updated_at": 123},
        ],
        synced_at=456,
    )

    assert result == 1
    assert calls == [([{"email": "uploaded@example.com", "updated_at": 123}], 456.0)]


def test_mark_accounts_synced_skips_account_changed_after_upload_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    accounts_mod.save_accounts([{"email": "uploaded@example.com", "status": "active"}])
    uploaded_account = accounts_mod.load_accounts()[0]

    time.sleep(0.01)
    accounts_mod.update_account("uploaded@example.com", status="standby")

    marked = account_hub._mark_accounts_synced([uploaded_account], synced_at=789)

    current = accounts_mod.load_accounts()[0]
    assert current["updated_at"] != uploaded_account["updated_at"]
    assert marked == 0
    assert not current.get("account_hub_synced")


def test_mark_accounts_hub_synced_serializes_a_concurrent_account_add(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts_mod, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    accounts_mod.save_accounts([{"email": "uploaded@example.com", "status": "active"}])
    uploaded_account = accounts_mod.load_accounts()[0]

    entered_update = threading.Event()
    release_update = threading.Event()
    original_upsert = accounts_mod._upsert_account

    def blocking_upsert(conn, account):
        if account.get("email") == "uploaded@example.com" and account.get("account_hub_synced") is True:
            entered_update.set()
            assert release_update.wait(2)
        return original_upsert(conn, account)

    monkeypatch.setattr(accounts_mod, "_upsert_account", blocking_upsert)
    marked = []
    mark_thread = threading.Thread(
        target=lambda: marked.append(
            accounts_mod.mark_accounts_hub_synced(
                [{"email": "uploaded@example.com", "updated_at": uploaded_account["updated_at"]}],
                synced_at=789,
            )
        ),
    )
    mark_thread.start()
    assert entered_update.wait(2)

    add_thread = threading.Thread(
        target=lambda: accounts_mod.add_account("created-during-sync@example.com", "secret"),
    )
    add_thread.start()
    time.sleep(0.05)
    assert add_thread.is_alive(), "the concurrent writer should wait for the atomic Hub update transaction"

    release_update.set()
    mark_thread.join(2)
    add_thread.join(2)
    assert not mark_thread.is_alive()
    assert not add_thread.is_alive()

    saved = {item["email"]: item for item in accounts_mod.load_accounts()}
    assert marked == [1]
    assert saved["uploaded@example.com"]["account_hub_synced"] is True
    assert saved["uploaded@example.com"]["account_hub_synced_at"] == 789
    assert "created-during-sync@example.com" in saved
