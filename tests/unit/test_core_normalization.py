from autotoken import accounts, api, auth_session_store, cpa_sync, manager, trade
from autotoken.core.normalization import normalize_access_token, normalized_email
from autotoken.mail.base import normalize_email_addr
from autotoken.services import paypal_pending_retry


def test_normalized_email_strips_whitespace_and_lowercases_values():
    assert normalized_email(" User@Example.COM ") == "user@example.com"
    assert normalized_email(None) == ""
    assert normalized_email(123) == "123"


def test_normalize_access_token_handles_json_bearer_and_trailing_delimiters():
    assert normalize_access_token('{"accessToken":"json-token"}') == "json-token"
    assert normalize_access_token("Bearer bearer-token,") == "bearer-token"
    assert normalize_access_token("new-access,") == "new-access"
    assert normalize_access_token("token-ending-in-s") == "token-ending-in-s"
    assert normalize_access_token(None) == ""


def test_existing_private_email_normalizers_delegate_to_core_helper():
    assert api._normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")
    assert accounts._normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")
    assert manager._normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")
    assert auth_session_store._normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")
    assert cpa_sync._normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")
    assert trade._normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")


def test_existing_public_email_normalizers_delegate_to_core_helper():
    assert normalize_email_addr(" User@Example.COM ") == normalized_email(" User@Example.COM ")
    assert paypal_pending_retry.normalized_email(" User@Example.COM ") == normalized_email(" User@Example.COM ")


def test_auth_session_paths_keep_legacy_email_shape_and_reject_path_separators(tmp_path, monkeypatch):
    auth_session_dir = tmp_path / "auth_session"
    monkeypatch.setattr(auth_session_store, "AUTH_SESSION_DIR", auth_session_dir)

    normal_path = auth_session_store._target_path("User@Example.com")
    unsafe_path = auth_session_store._target_path("User/../../Escape:Name@Example.com")

    assert normal_path == auth_session_dir / "user@example_com.json"
    assert unsafe_path.parent == auth_session_dir
    assert unsafe_path.name == "user_escape_name@example_com.json"
