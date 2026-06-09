import pytest

from autotoken.services import payment_http
from autotoken.storage import auth_storage
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


class FakeResponse:
    status_code = 502
    text = "not-json-body"

    def json(self):
        raise ValueError("invalid json")


def test_new_http_session_normalizes_socks_proxy(monkeypatch):
    monkeypatch.setattr(payment_http, "_CurlCffiSession", None)

    session = payment_http.new_http_session("socks5://user:pass@proxy.example:1080")

    assert session.proxies == {
        "http": "socks5h://user:pass@proxy.example:1080",
        "https": "socks5h://user:pass@proxy.example:1080",
    }
    assert payment_http.http_transport_name(session) == "requests"


def test_new_http_session_requires_curl_cffi_when_requested(monkeypatch):
    monkeypatch.setattr(payment_http, "_CurlCffiSession", None)

    with pytest.raises(payment_http.PaymentHttpError) as exc:
        payment_http.new_http_session(require_curl_cffi=True)

    assert exc.value.stage == "chatgpt_http_session"
    assert "curl-cffi" in str(exc.value)


def test_response_json_wraps_non_json_with_stage():
    with pytest.raises(payment_http.PaymentHttpError) as exc:
        payment_http.response_json(FakeResponse(), "stripe_init")

    assert exc.value.stage == "stripe_init"
    assert "stripe_init 返回非 JSON: HTTP 502 not-json-body" in str(exc.value)


def test_load_chatgpt_auth_file_context_accepts_nested_account_ids():
    captured = {}

    def account_lookup(email):
        captured["email"] = email
        return {"email": email, "auth_file": "auth.json"}

    context = payment_http.load_chatgpt_auth_file_context(
        " User@Example.com ",
        account_lookup=account_lookup,
        file_reader=lambda _path: {
            "accessToken": "access-token",
            "idToken": "id-token",
            "account": {"id": "account-id"},
        },
    )

    assert context == {
        "access_token": "access-token",
        "account_id": "account-id",
        "id_token": "id-token",
        "auth_file": "auth.json",
    }
    assert captured["email"] == "user@example.com"


def test_load_chatgpt_auth_file_context_ignores_auth_file_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    outside = tmp_path / "outside-auth.json"
    outside.write_text('{"access_token":"outside-token"}', encoding="utf-8")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)

    context = payment_http.load_chatgpt_auth_file_context(
        "user@example.com",
        account_lookup=lambda email: {"email": email, "auth_file": str(outside)},
    )

    assert context == {}


def test_load_chatgpt_auth_file_context_accepts_auth_file_inside_auth_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text(
        '{"access_token":"inside-token","account":{"id":"account-id"},"id_token":"id-token"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)

    context = payment_http.load_chatgpt_auth_file_context(
        "user@example.com",
        account_lookup=lambda email: {"email": email, "auth_file": str(auth_file)},
    )

    assert context == {
        "access_token": "inside-token",
        "account_id": "account-id",
        "id_token": "id-token",
        "auth_file": str(auth_file),
    }


def test_load_chatgpt_auth_file_context_ignores_oversized_auth_file(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    auth_file = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)

    context = payment_http.load_chatgpt_auth_file_context(
        "user@example.com",
        account_lookup=lambda email: {"email": email, "auth_file": str(auth_file)},
    )

    assert context == {}
