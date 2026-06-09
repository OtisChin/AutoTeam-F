import base64
import json
from pathlib import Path

from autotoken import auth_storage
from autotoken.session_cpa_converter import convert_chatgpt_session_to_cpa_auth, save_cpa_auth_from_session
from autotoken.sub2api_converter import ExportSettings, export_records, inspect_sources


def _b64url(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _jwt(payload):
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(payload)}.sig"


def _session():
    return {
        "user": {"id": "user-1", "email": "user@example.com", "name": "User One"},
        "expires": "2026-08-06T14:29:36.155Z",
        "account": {"id": "acc-1", "planType": "plus"},
        "accessToken": _jwt(
            {
                "exp": 1786026576,
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "acc-1",
                    "chatgpt_user_id": "user-1",
                    "chatgpt_plan_type": "plus",
                },
                "https://api.openai.com/profile": {"email": "user@example.com"},
            }
        ),
        "sessionToken": "session-token",
    }


def _session_for(email: str, account_id: str) -> dict:
    session = _session()
    session["user"] = {"id": "user-1", "email": email, "name": "User One"}
    session["account"] = {"id": account_id, "planType": "plus"}
    session["accessToken"] = _jwt(
        {
            "exp": 1786026576,
            "https://api.openai.com/auth": {
                "chatgpt_account_id": account_id,
                "chatgpt_user_id": "user-1",
                "chatgpt_plan_type": "plus",
            },
            "https://api.openai.com/profile": {"email": email},
        }
    )
    return session


def test_convert_chatgpt_session_builds_cpa_auth_with_synthetic_id_token():
    auth = convert_chatgpt_session_to_cpa_auth(_session())

    assert auth["type"] == "codex"
    assert auth["email"] == "user@example.com"
    assert auth["account_id"] == "acc-1"
    assert auth["plan_type"] == "plus"
    assert auth["session_token"] == "session-token"
    assert auth["refresh_token"] == ""
    assert auth["id_token_synthetic"] is True
    assert auth["id_token"].count(".") == 2


def test_save_cpa_auth_from_session_writes_auth_file_and_sub2api_accepts_missing_refresh(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    monkeypatch.setattr("autotoken.session_cpa_converter.AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.session_cpa_converter.upsert_codex_auth_file", lambda *args, **kwargs: None)

    result = save_cpa_auth_from_session(_session())

    path = auth_dir / result["filename"]
    assert path.exists()
    records = inspect_sources([(path.name, path.read_text(encoding="utf-8"))])
    payload = export_records(records, ExportSettings(output_filename="sub2api.json"))
    account = payload["accounts"][0]
    assert account["credentials"]["access_token"]
    assert account["credentials"]["chatgpt_account_id"] == "acc-1"
    assert "refresh_token" not in account["credentials"]


def test_save_cpa_auth_from_session_matches_glob_chars_literally(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    literal = auth_dir / "codex-user[abc]@example.com-unknown-deadbeef.json"
    wildcard_match = auth_dir / "codex-usera@example.com-unknown-deadbeef.json"
    literal.write_text("{}", encoding="utf-8")
    wildcard_match.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("autotoken.session_cpa_converter.AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr("autotoken.session_cpa_converter.upsert_codex_auth_file", lambda *args, **kwargs: None)

    result = save_cpa_auth_from_session(_session_for("user[abc]@example.com", "acc-literal"))

    saved = Path(result["auth_file"])
    assert saved.parent == auth_dir
    assert saved.name.startswith("codex-user_abc_@example.com-plus-")
    assert not literal.exists()
    assert wildcard_match.exists()
