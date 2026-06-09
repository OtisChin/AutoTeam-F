import base64
import json

from autotoken import chatgpt_api, codex_auth, cpa_sync, session_cpa_converter, sub2api_converter
from autotoken.core.jwt import JWT_PAYLOAD_MAX_CHARS, decode_jwt_payload
from autotoken.mail import base as mail_base
from autotoken.services import chatgpt_session


def _jwt(payload) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def test_decode_jwt_payload_returns_payload_claims():
    assert decode_jwt_payload(_jwt({"email": "user@example.com"})) == {"email": "user@example.com"}


def test_decode_jwt_payload_returns_empty_dict_for_invalid_or_non_object_payloads():
    assert decode_jwt_payload("not-a-jwt") == {}
    assert decode_jwt_payload("header.not valid.base64") == {}
    assert decode_jwt_payload(_jwt(["not", "an", "object"])) == {}


def test_decode_jwt_payload_rejects_oversized_payload_segment():
    assert decode_jwt_payload(f"header.{'a' * (JWT_PAYLOAD_MAX_CHARS + 1)}.signature") == {}


def test_existing_jwt_claim_helpers_delegate_to_core_helper():
    token = _jwt({"https://api.openai.com/profile": {"email": "user@example.com"}})

    assert chatgpt_session.access_token_claims(token) == decode_jwt_payload(token)
    assert codex_auth._parse_jwt_payload(token) == decode_jwt_payload(token)
    assert cpa_sync._parse_jwt_payload(token) == decode_jwt_payload(token)
    assert sub2api_converter.decode_jwt_payload(token) == decode_jwt_payload(token)
    assert session_cpa_converter._decode_jwt_payload(token) == decode_jwt_payload(token)
    assert mail_base.decode_jwt_payload(token) == decode_jwt_payload(token)


def test_chatgpt_api_account_id_extraction_uses_decoded_uuid_claim():
    api = object.__new__(chatgpt_api.ChatGPTTeamAPI)
    api.access_token = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "123e4567-e89b-12d3-a456-426614174000",
            }
        }
    )

    assert api._extract_account_id_from_access_token() == "123e4567-e89b-12d3-a456-426614174000"

    api.access_token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "not-a-uuid"}})

    assert api._extract_account_id_from_access_token() == ""


def test_chatgpt_api_session_token_extraction_uses_shared_cookie_item_helper():
    class FakeContext:
        def cookies(self):
            return [
                {"name": "__Secure-next-auth.session-token.1", "value": "bbb"},
                {"name": "__Secure-next-auth.session-token.0", "value": "aaa"},
            ]

    api = object.__new__(chatgpt_api.ChatGPTTeamAPI)
    api.context = FakeContext()
    api.session_token = ""

    assert api._extract_session_token() == "aaabbb"
    assert api.session_token == "aaabbb"
