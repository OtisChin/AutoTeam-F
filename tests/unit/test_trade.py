import base64
import io
import json
import re
import threading
import zipfile

import pytest

from autotoken import accounts, trade
from autotoken.core.normalization import normalized_email


def _fake_jwt(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return f"header.{encoded}.signature"


@pytest.fixture
def trade_env(tmp_path, monkeypatch):
    db_file = tmp_path / "autotoken.sqlite3"
    auth_dir = tmp_path / "data" / "auths"
    auth_dir.mkdir(parents=True)
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_file))
    monkeypatch.setattr(trade, "AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.admin_state.get_admin_email", lambda: "owner@example.com")
    return {"db_file": db_file, "auth_dir": auth_dir}


def _add_plus_account(
    auth_dir,
    email,
    *,
    valid_sub=True,
    password="pw",
    cloudmail_account_id=None,
    mail_provider=None,
    status="active",
    account_type="plus",
    credentials_exported=False,
    with_auth=True,
):
    auth_file = auth_dir / f"codex-{email}-plus-deadbeef.json"
    if with_auth:
        payload = {
            "email": email,
            "access_token": _fake_jwt(
                {
                    "client_id": "app_client",
                    "https://api.openai.com/profile": {"email": email},
                    "https://api.openai.com/auth": {"chatgpt_account_id": f"account-{email}"},
                }
            )
            if valid_sub
            else "plain-token",
            "refresh_token": f"refresh-{email}",
            "expired": "2026-04-18T12:20:50+08:00",
        }
        auth_file.write_text(json.dumps(payload), encoding="utf-8")
    rows = accounts.load_accounts()
    rows.append(
        {
            "email": email,
            "password": password,
            "status": status,
            "account_type": account_type,
            "auth_file": str(auth_file) if with_auth else "",
            "cloudmail_account_id": cloudmail_account_id,
            "mail_provider": mail_provider,
            "credentials_exported": credentials_exported,
        }
    )
    accounts.save_accounts(rows)
    return auth_file


def test_create_cdk_uses_plus_format_and_24h_expiry(trade_env, monkeypatch):
    monkeypatch.setattr(trade.time, "time", lambda: 1000.0)

    cdk = trade.create_cdk(3, note="order-1")

    assert cdk["code"].startswith("3-19700101-PLUS-")
    assert len(cdk["code"]) == len("3-19700101-PLUS-HJOIXOIGKMEV")
    assert re.match(r"^3-19700101-PLUS-[A-Z0-9]{12}$", cdk["code"])
    assert cdk["quota_total"] == 3
    assert cdk["remaining"] == 3
    assert cdk["expires_at"] == 1000.0 + trade.CDK_TTL_SECONDS
    assert cdk["note"] == "order-1"
    assert trade.validate_code("100-20260526-PLUS-ABCDEF123456") == "100-20260526-PLUS-ABCDEF123456"
    assert trade.validate_code("PLUS-ABCDEF123456") == "PLUS-ABCDEF123456"


def test_trade_private_email_normalizer_matches_core_helper():
    assert trade._normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")


def test_redeem_cdk_binds_password_and_allows_batches(trade_env):
    auth_dir = trade_env["auth_dir"]
    first = _add_plus_account(auth_dir, "first@example.com")
    second = _add_plus_account(auth_dir, "second@example.com")
    cdk = trade.create_cdk(2)

    one = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")
    two = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    assert one["count"] == 1
    assert two["count"] == 1
    assert {one["emails"][0], two["emails"][0]} == {"first@example.com", "second@example.com"}
    assert one["content_type"] == "application/json"
    assert json.loads(base64.b64decode(one["content_base64"]).decode("utf-8")) in [
        json.loads(first.read_text()),
        json.loads(second.read_text()),
    ]
    final = trade.get_cdk(cdk["code"])
    assert final["status"] == "exhausted"
    assert final["remaining"] == 0
    assert final["password"] == "secret"
    assert final["latest_redeemed_at"] == max(one["redeemed_at"], two["redeemed_at"])
    assert trade.list_cdks()[0]["latest_redeemed_at"] == final["latest_redeemed_at"]
    saved = {item["email"]: item for item in accounts.load_accounts()}
    assert saved["first@example.com"]["credentials_exported"] is True
    assert saved["second@example.com"]["credentials_exported"] is True


def test_redeem_cdk_rejects_wrong_password(trade_env):
    _add_plus_account(trade_env["auth_dir"], "user@example.com")
    cdk = trade.create_cdk(1)

    trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    with pytest.raises(trade.TradeError) as exc:
        trade.redeem_cdk(cdk["code"], "wrong1", 1, "cpa")
    assert exc.value.status_code in {403, 410}


def test_redeem_cdk_rejects_revoked_cdk(trade_env):
    _add_plus_account(trade_env["auth_dir"], "user@example.com")
    cdk = trade.create_cdk(1)

    trade.revoke_cdk(cdk["code"])

    with pytest.raises(trade.TradeError) as exc:
        trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")
    assert exc.value.status_code == 410


def test_redeem_cdk_exports_sub_format(trade_env):
    _add_plus_account(trade_env["auth_dir"], "user@example.com")
    cdk = trade.create_cdk(1)

    result = trade.redeem_cdk(cdk["code"], "secret", 1, "sub")

    assert result["content_type"] == "application/json"
    payload = json.loads(base64.b64decode(result["content_base64"]).decode("utf-8"))
    assert payload["accounts"][0]["platform"] == "openai"
    assert payload["accounts"][0]["credentials"]["email"] == "user@example.com"


def test_redeem_cdk_exports_credentials_with_luckmail_token(trade_env):
    _add_plus_account(
        trade_env["auth_dir"],
        "user@example.com",
        password="login-password",
        cloudmail_account_id="tok_luckmail_secret",
        mail_provider="luckmail",
    )
    cdk = trade.create_cdk(1)

    result = trade.redeem_cdk(cdk["code"], "secret", 1, "credentials")

    assert result["content_type"].startswith("text/plain")
    content = base64.b64decode(result["content_base64"]).decode("utf-8")
    assert content == "user@example.com-----tok_luckmail_secret-----https://mail.cpacc.us.ci/"


def test_redeem_cdk_exports_multiple_formats_in_one_zip(trade_env):
    _add_plus_account(
        trade_env["auth_dir"],
        "user@example.com",
        password="login-password",
        cloudmail_account_id="tok_luckmail_secret",
        mail_provider="luckmail",
    )
    cdk = trade.create_cdk(1)

    result = trade.redeem_cdk(cdk["code"], "secret", 1, ["cpa", "sub", "credentials"])

    assert result["content_type"] == "application/zip"
    assert result["filename"].endswith(".zip")
    assert result["formats"] == ["cpa", "sub", "credentials"]
    raw = base64.b64decode(result["content_base64"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        assert any(name.startswith("cpa/") and name.endswith(".json") for name in names)
        assert any(name.startswith("sub/") and name.endswith(".json") for name in names)
        credential_names = [name for name in names if name.startswith("credentials/") and name.endswith(".txt")]
        assert credential_names
        assert archive.read(credential_names[0]).decode("utf-8") == "user@example.com-----tok_luckmail_secret-----https://mail.cpacc.us.ci/"
    final = trade.get_cdk(cdk["code"])
    assert final["remaining"] == 0


def test_build_multi_export_rejects_invalid_base64_payload():
    with pytest.raises(trade.TradeError) as exc:
        trade._build_multi_export(
            {
                "cpa": {
                    "filename": "auth.json",
                    "content_base64": "not-valid-base64!!!",
                }
            }
        )

    assert str(exc.value) == "导出内容编码无效"


def test_build_multi_export_rejects_oversized_decoded_payload(monkeypatch):
    payload = base64.b64encode(b"123456").decode("ascii")
    monkeypatch.setattr(trade, "EXPORT_PAYLOAD_MAX_BYTES", 5)

    with pytest.raises(trade.TradeError) as exc:
        trade._build_multi_export({"cpa": {"filename": "auth.json", "content_base64": payload}})

    assert str(exc.value) == "导出内容过大"


def test_redemption_history_downloads_previous_batch_without_consuming_quota(trade_env):
    _add_plus_account(
        trade_env["auth_dir"],
        "first@example.com",
        password="login-password",
        cloudmail_account_id="tok_luckmail_secret",
        mail_provider="luckmail",
    )
    _add_plus_account(trade_env["auth_dir"], "second@example.com")
    cdk = trade.create_cdk(2)
    redeemed = trade.redeem_cdk(cdk["code"], "secret", 1, ["cpa", "credentials"])

    history = trade.list_cdk_redemption_history(cdk["code"], "secret")

    assert history["used_count"] == 1
    assert history["remaining"] == 1
    assert history["history"] == [
        {
            "batch_id": redeemed["batch_id"],
            "redeemed_at": redeemed["redeemed_at"],
            "formats": ["cpa", "credentials"],
            "emails": ["first@example.com"],
            "count": 1,
        }
    ]

    downloaded = trade.download_cdk_redemption_batch(cdk["code"], "secret", redeemed["batch_id"])

    assert downloaded["batch_id"] == redeemed["batch_id"]
    assert downloaded["emails"] == ["first@example.com"]
    assert downloaded["formats"] == ["cpa", "credentials"]
    assert downloaded["remaining"] == 1
    assert downloaded["content_type"] == "application/zip"
    raw = base64.b64decode(downloaded["content_base64"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        assert any(name.startswith("cpa/") and name.endswith(".json") for name in names)
        credential_names = [name for name in names if name.startswith("credentials/") and name.endswith(".txt")]
        assert credential_names
        assert archive.read(credential_names[0]).decode("utf-8") == "first@example.com-----tok_luckmail_secret-----https://mail.cpacc.us.ci/"

    final = trade.get_cdk(cdk["code"])
    assert final["used_count"] == 1
    assert final["remaining"] == 1
    assert len(final["redemptions"]) == 1


def test_admin_downloads_all_cdk_redemptions_without_password(trade_env):
    _add_plus_account(
        trade_env["auth_dir"],
        "first@example.com",
        password="login-password",
        cloudmail_account_id="tok_luckmail_secret",
        mail_provider="luckmail",
    )
    _add_plus_account(trade_env["auth_dir"], "second@example.com")
    cdk = trade.create_cdk(2)
    first = trade.redeem_cdk(cdk["code"], "secret", 1, ["cpa", "credentials"])
    second = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    downloaded = trade.download_cdk_redemptions(cdk["code"])

    assert downloaded["code"] == cdk["code"]
    assert downloaded["batch_count"] == 2
    assert downloaded["count"] == 2
    assert downloaded["emails"] == ["first@example.com", "second@example.com"]
    assert downloaded["content_type"] == "application/zip"
    raw = base64.b64decode(downloaded["content_base64"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["code"] == cdk["code"]
        assert manifest["batch_count"] == 2
        assert [batch["batch_id"] for batch in manifest["batches"]] == [first["batch_id"], second["batch_id"]]
        assert all(batch["formats"] == ["cpa", "sub", "credentials"] for batch in manifest["batches"])
        assert any(name.endswith("/emails.txt") for name in names)
        assert any(name.endswith(".zip") for name in names)


def test_admin_downloads_redemptions_sanitizes_archive_member_names(trade_env):
    _add_plus_account(trade_env["auth_dir"], "first@example.com")
    cdk = trade.create_cdk(1)
    trade.redeem_cdk(cdk["code"], "secret", 1, ["cpa", "credentials"])
    malicious_batch_id = "../evil/batch"
    with trade.sqlite_store.connect() as conn:
        conn.execute(
            "UPDATE plus_cdk_redemptions SET batch_id = ? WHERE code = ?",
            (malicious_batch_id, cdk["code"]),
        )

    downloaded = trade.download_cdk_redemptions(cdk["code"])

    raw = base64.b64decode(downloaded["content_base64"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
    assert all(not name.startswith("/") for name in names)
    assert all("\\" not in name for name in names)
    assert all("../" not in name and "/.." not in name for name in names)
    assert manifest["batches"][0]["batch_id"] == malicious_batch_id
    assert manifest["batches"][0]["filename"].startswith("001-")
    assert "../" not in manifest["batches"][0]["filename"]


def test_redemption_history_requires_password(trade_env):
    _add_plus_account(trade_env["auth_dir"], "user@example.com")
    cdk = trade.create_cdk(1)
    trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    with pytest.raises(trade.TradeError) as exc:
        trade.list_cdk_redemption_history(cdk["code"], "wrong1")

    assert exc.value.status_code == 403


def test_redeem_cdk_only_distributes_active_unexported_plus_with_auth(trade_env):
    auth_dir = trade_env["auth_dir"]
    _add_plus_account(auth_dir, "free@example.com", account_type="free")
    _add_plus_account(auth_dir, "exported@example.com", credentials_exported=True)
    _add_plus_account(auth_dir, "discarded@example.com", status="fail")
    _add_plus_account(auth_dir, "missing-auth@example.com", with_auth=False)
    _add_plus_account(auth_dir, "ok@example.com")
    cdk = trade.create_cdk(1)

    result = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    assert result["emails"] == ["ok@example.com"]


def test_redeem_cdk_accepts_gopay_plus_status_stock(trade_env):
    auth_dir = trade_env["auth_dir"]
    _add_plus_account(auth_dir, "synced-plus@example.com", status="plus", account_type="free")
    cdk = trade.create_cdk(1)

    result = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    assert result["emails"] == ["synced-plus@example.com"]


def test_redeem_cdk_accepts_paypal_ice_bound_active_plus_stock(trade_env):
    auth_dir = trade_env["auth_dir"]
    _add_plus_account(auth_dir, "paypal-ice@example.com", status="active", account_type="plus")
    accounts.update_account("paypal-ice@example.com", last_bind_provider="paypal_ice")
    cdk = trade.create_cdk(1)

    result = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    assert result["emails"] == ["paypal-ice@example.com"]


def test_redeem_cdk_credentials_requires_auth_file(trade_env):
    _add_plus_account(trade_env["auth_dir"], "missing-auth@example.com", with_auth=False)
    cdk = trade.create_cdk(1)

    with pytest.raises(trade.TradeError) as exc:
        trade.redeem_cdk(cdk["code"], "secret", 1, "credentials")

    assert str(exc.value) == "Plus 库存不足"


def test_resolve_codex_auth_file_ignores_account_auth_outside_auth_dir(trade_env, tmp_path):
    outside = tmp_path / "outside-auth.json"
    outside.write_text("{}", encoding="utf-8")
    inside = trade_env["auth_dir"] / "codex-user@example.com-plus-deadbeef.json"
    inside.write_text("{}", encoding="utf-8")

    resolved = trade._resolve_codex_auth_file(
        {
            "email": "user@example.com",
            "auth_file": str(outside),
        }
    )

    assert resolved == str(inside)


def test_inventory_summary_uses_trade_distribution_rules(trade_env):
    auth_dir = trade_env["auth_dir"]
    _add_plus_account(auth_dir, "available@example.com")
    _add_plus_account(auth_dir, "free@example.com", account_type="free")
    _add_plus_account(auth_dir, "exported@example.com", credentials_exported=True)
    _add_plus_account(auth_dir, "discarded@example.com", status="fail")
    _add_plus_account(auth_dir, "missing-auth@example.com", with_auth=False)
    cdk = trade.create_cdk(1)
    trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    summary = trade.inventory_summary()

    assert "available_cpa" not in summary
    assert "available_sub" not in summary
    assert "available_credentials" not in summary
    assert summary["stock_available"] == 0
    assert summary["stock_exported"] == 2
    assert summary["stock_discarded"] == 1
    assert summary["stock_missing_credentials"] == 1
    assert summary["allocated"] == 1
    assert summary["cdk_exhausted"] == 1


def test_clear_trade_allocations_returns_accounts_to_available_stock_without_refunding_cdk(trade_env):
    auth_dir = trade_env["auth_dir"]
    _add_plus_account(auth_dir, "user@example.com")
    cdk = trade.create_cdk(1)
    redeemed = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    accounts.update_account("user@example.com", credentials_exported=False, credentials_exported_at=None)
    result = trade.clear_trade_allocations_for_emails(["user@example.com"])
    summary = trade.inventory_summary()
    restored = trade.get_cdk(cdk["code"])

    assert result == {"cleared": 1, "codes": [cdk["code"]]}
    assert summary["stock_available"] == 1
    assert summary["stock_exported"] == 0
    assert restored["used_count"] == 1
    assert restored["remaining"] == 0
    assert restored["status"] == "exhausted"
    assert restored["latest_redeemed_at"] == redeemed["redeemed_at"]
    assert restored["redemptions"][0]["email"] == "user@example.com"


def test_unexported_accounts_are_not_blocked_by_stale_trade_allocations(trade_env):
    auth_dir = trade_env["auth_dir"]
    _add_plus_account(auth_dir, "user@example.com")
    cdk = trade.create_cdk(1)
    redeemed = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")

    accounts.update_account("user@example.com", credentials_exported=False, credentials_exported_at=None)
    next_cdk = trade.create_cdk(1)
    next_redeemed = trade.redeem_cdk(next_cdk["code"], "secret", 1, "cpa")
    summary = trade.inventory_summary()
    stale = trade.get_cdk(cdk["code"])
    next_status = trade.get_cdk(next_cdk["code"])

    assert next_redeemed["emails"] == ["user@example.com"]
    assert summary["stock_available"] == 0
    assert summary["allocated"] == 1
    assert stale["used_count"] == 1
    assert stale["remaining"] == 0
    assert stale["status"] == "exhausted"
    assert stale["latest_redeemed_at"] == redeemed["redeemed_at"]
    assert next_status["used_count"] == 1
    assert next_status["remaining"] == 0
    assert next_status["status"] == "exhausted"


def test_query_cdk_remaining_requires_bound_password(trade_env):
    _add_plus_account(trade_env["auth_dir"], "user@example.com")
    cdk = trade.create_cdk(2)

    with pytest.raises(trade.TradeError) as exc:
        trade.query_cdk_remaining(cdk["code"], "secret")
    assert exc.value.status_code == 403

    trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")
    status = trade.query_cdk_remaining(cdk["code"], "secret")

    assert status["remaining"] == 1
    assert status["used_count"] == 1


def test_set_cdk_password_binds_without_redeeming_account(trade_env):
    _add_plus_account(trade_env["auth_dir"], "user@example.com")
    cdk = trade.create_cdk(2)

    status = trade.set_cdk_password(cdk["code"], "secret")
    queried = trade.query_cdk_remaining(cdk["code"], "secret")

    assert status["password_set"] is True
    assert status["remaining"] == 2
    assert queried["remaining"] == 2
    assert "password" not in status
    assert trade.get_cdk(cdk["code"])["password"] == "secret"
    assert trade.list_cdks()[0]["password"] == "secret"

    with pytest.raises(trade.TradeError) as exc:
        trade.set_cdk_password(cdk["code"], "other1")
    assert exc.value.status_code == 409


def test_set_cdk_password_rejects_short_password(trade_env):
    cdk = trade.create_cdk(2)

    with pytest.raises(trade.TradeError) as exc:
        trade.set_cdk_password(cdk["code"], "12345")

    assert str(exc.value) == "提取密码不能少于 6 位"


def test_public_cdk_status_exposes_password_state_without_password(trade_env):
    _add_plus_account(trade_env["auth_dir"], "user@example.com")
    cdk = trade.create_cdk(2)

    before = trade.public_cdk_status(cdk["code"])
    trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")
    after = trade.public_cdk_status(cdk["code"])

    assert before["password_set"] is False
    assert before["remaining"] == 2
    assert "redemptions" not in before
    assert after["password_set"] is True
    assert after["remaining"] == 1
    assert "password" not in after


def test_parallel_redeem_does_not_duplicate_accounts(trade_env):
    for index in range(4):
        _add_plus_account(trade_env["auth_dir"], f"user{index}@example.com")
    cdk = trade.create_cdk(4)
    emails = []
    errors = []
    lock = threading.Lock()

    def worker():
        try:
            result = trade.redeem_cdk(cdk["code"], "secret", 1, "cpa")
            with lock:
                emails.extend(result["emails"])
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(emails) == 4
    assert len(set(emails)) == 4
