import base64
import json

from autotoken.services import chatgpt_session


def _jwt(payload: dict) -> str:
    def b64url(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return ".".join([b64url({"alg": "none"}), b64url(payload), "sig"])


def test_access_token_claim_helpers_extract_account_and_email():
    access_token = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "account-from-jwt",
            },
            "https://api.openai.com/profile": {
                "email": "user@example.com",
            },
        }
    )

    assert chatgpt_session.account_id_from_access_token(access_token) == "account-from-jwt"
    assert chatgpt_session.email_from_access_token(access_token) == "user@example.com"
    assert chatgpt_session.access_token_claims("not-a-jwt") == {}
    assert chatgpt_session.email_from_access_token("not-a-jwt") == ""


def test_extract_auth_session_context_uses_session_then_auth_file_then_jwt():
    access_token = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "account-from-jwt",
            },
        }
    )

    context = chatgpt_session.extract_auth_session_context(
        "user@example.com",
        load_session=lambda _email: {
            "accessToken": access_token,
            "sessionToken": "session-token",
            "cookie_header": "cookie=ok",
            "account": {"id": ""},
            "device_id": "device-id",
            "userAgent": "UA",
            "openaiSentinelToken": "sentinel",
            "oaiClientVersion": "1.0",
            "oaiClientBuildNumber": "2",
        },
        auth_file_context={"access_token": "auth-file-token", "account_id": "account-from-file"},
    )

    assert context == {
        "access_token": access_token,
        "session_token": "session-token",
        "cookie_header": "cookie=ok",
        "account_id": "account-from-file",
        "device_id": "device-id",
        "user_agent": "UA",
        "openai_sentinel_token": "sentinel",
        "oai_client_version": "1.0",
        "oai_client_build_number": "2",
    }

    jwt_fallback_context = chatgpt_session.extract_auth_session_context(
        "user@example.com",
        load_session=lambda _email: {"accessToken": access_token},
        auth_file_context={},
    )
    assert jwt_fallback_context["account_id"] == "account-from-jwt"

    auth_file_fallback_context = chatgpt_session.extract_auth_session_context(
        "user@example.com",
        load_session=lambda _email: {},
        auth_file_context={"access_token": "auth-file-token", "account_id": "account-from-file"},
    )
    assert auth_file_fallback_context["access_token"] == "auth-file-token"
    assert auth_file_fallback_context["account_id"] == "account-from-file"

    auth_file_jwt_fallback_context = chatgpt_session.extract_auth_session_context(
        "user@example.com",
        load_session=lambda _email: {},
        auth_file_context={"access_token": access_token},
    )
    assert auth_file_jwt_fallback_context["access_token"] == access_token
    assert auth_file_jwt_fallback_context["account_id"] == "account-from-jwt"


def test_configure_chatgpt_http_session_sets_reference_headers():
    class FakeHttp:
        def __init__(self):
            self.headers = {}

    http = FakeHttp()

    result = chatgpt_session.configure_chatgpt_http_session(
        http,
        access_token="access",
        session_token="session",
        cookie_header="small=ok",
        account_id="account",
        device_id="device",
        user_agent="UA",
        openai_sentinel_token="sentinel",
        oai_client_version="1.0",
        oai_client_build_number="2",
    )

    assert result == {
        "device_id": "device",
        "cookie_header": "small=ok; __Secure-next-auth.session-token=session; _account=account; oai-did=device",
    }
    assert http.headers["Authorization"] == "Bearer access"
    assert http.headers["Cookie"] == result["cookie_header"]
    assert http.headers["User-Agent"] == "UA"
    assert http.headers["openai-sentinel-token"] == "sentinel"
    assert http.headers["oai-client-version"] == "1.0"
    assert http.headers["oai-client-build-number"] == "2"
    assert http._oai_device_id == "device"
    assert http._chatgpt_cookie_header == result["cookie_header"]


def test_merge_cookie_headers_preserves_first_cookie_name_and_skips_invalid_parts():
    assert (
        chatgpt_session.merge_cookie_headers(
            "a=1; b=2; invalid",
            " b=override ; c=3; =missing-name",
            "",
        )
        == "a=1; b=2; c=3"
    )


def test_cookie_header_from_cookie_items_preserves_first_cookie_name():
    assert (
        chatgpt_session.cookie_header_from_cookie_items(
            [
                {"name": "a", "value": "1"},
                {"name": "empty", "value": ""},
                {"name": "a", "value": "override"},
                object(),
                {"name": "b", "value": "2"},
            ]
        )
        == "a=1; b=2"
    )


def test_chatgpt_checkout_headers_builds_frontend_style_headers():
    headers = chatgpt_session.chatgpt_checkout_headers(
        access_token="access",
        checkout_session_id="cs_test",
        processor_entity="openai_llc",
        cookie_header="cookie=ok",
        account_id="account",
        device_id="device",
        target_path="/backend-api/payments/checkout/approve",
        openai_sentinel_token="sentinel",
    )

    assert headers["referer"] == "https://chatgpt.com/checkout/openai_llc/cs_test"
    assert headers["authorization"] == "Bearer access"
    assert headers["cookie"] == "cookie=ok"
    assert headers["oai-device-id"] == "device"
    assert headers["chatgpt-account-id"] == "account"
    assert headers["openai-sentinel-token"] == "sentinel"
    assert headers["x-openai-target-path"] == "/backend-api/payments/checkout/approve"
    assert headers["x-openai-target-route"] == "/backend-api/payments/checkout/approve"
    assert headers["sec-fetch-site"] == "same-origin"


def test_chatgpt_verify_checkout_result_normalizes_status_and_body():
    assert chatgpt_session.chatgpt_verify_checkout_result(200, "ignored") == {
        "state": "succeeded",
        "verify": {"status": 200},
    }

    result = chatgpt_session.chatgpt_verify_checkout_result(504, "x" * 600)

    assert result["state"] == "verify_timeout"
    assert result["verify"]["status"] == 504
    assert result["verify"]["body"] == "x" * 500


def test_session_token_from_cookie_header_prefers_full_cookie_and_reassembles_split_parts():
    assert (
        chatgpt_session.session_token_from_cookie_header(
            "__Secure-next-auth.session-token.1=bbb; "
            "__Secure-next-auth.session-token.0=aaa; __Secure-next-auth.session-token=full"
        )
        == "full"
    )
    assert (
        chatgpt_session.session_token_from_cookie_header(
            "a=1; __Secure-next-auth.session-token.2=ccc; "
            "__Secure-next-auth.session-token.0=aaa; __Secure-next-auth.session-token.1=bbb"
        )
        == "aaabbbccc"
    )


def test_session_token_from_cookie_items_prefers_full_cookie_and_reassembles_split_parts():
    assert (
        chatgpt_session.session_token_from_cookie_items(
            [
                {"name": "__Secure-next-auth.session-token.1", "value": "bbb"},
                {"name": "__Secure-next-auth.session-token.0", "value": "aaa"},
                {"name": "__Secure-next-auth.session-token", "value": "full"},
            ]
        )
        == "full"
    )
    assert (
        chatgpt_session.session_token_from_cookie_items(
            [
                {"name": "__Secure-next-auth.session-token.2", "value": "ccc"},
                {"name": "__Secure-next-auth.session-token.0", "value": "aaa"},
                {"name": "__Secure-next-auth.session-token.1", "value": "bbb"},
                {"name": "malformed", "value": ""},
            ]
        )
        == "aaabbbccc"
    )


def test_session_token_from_cookie_jar_prefers_full_cookie_and_filters_domain():
    class Cookie:
        def __init__(self, name, value, domain):
            self.name = name
            self.value = value
            self.domain = domain

    class CookieJar:
        def __init__(self, cookies, direct=""):
            self.cookies = cookies
            self.direct = direct

        def get(self, name, default=""):
            if name == "__Secure-next-auth.session-token":
                return self.direct
            return default

        def __iter__(self):
            return iter(self.cookies)

    assert (
        chatgpt_session.session_token_from_cookie_jar(
            CookieJar(
                [
                    Cookie("__Secure-next-auth.session-token.0", "wrong", "example.com"),
                    Cookie("__Secure-next-auth.session-token.1", "bbb", ".chatgpt.com"),
                    Cookie("__Secure-next-auth.session-token.0", "aaa", "chatgpt.com"),
                ],
            ),
            domain_contains="chatgpt.com",
        )
        == "aaabbb"
    )
    assert chatgpt_session.session_token_from_cookie_jar(CookieJar([], direct="full")) == "full"


def test_http_session_cookie_header_prefers_domain_dict_and_falls_back():
    class CookieJar:
        def __init__(self, domain_items, fallback_items):
            self.domain_items = domain_items
            self.fallback_items = fallback_items

        def get_dict(self, domain=None):
            if domain == "chatgpt.com":
                return dict(self.domain_items)
            return dict(self.fallback_items)

    class Http:
        def __init__(self, cookies):
            self.cookies = cookies

    assert (
        chatgpt_session.http_session_cookie_header(
            Http(CookieJar([("session", "chatgpt")], [("fallback", "all")]))
        )
        == "session=chatgpt"
    )
    assert chatgpt_session.http_session_cookie_header(Http(CookieJar([], [("fallback", "all")]))) == "fallback=all"


def test_http_session_cookie_header_reads_iterable_cookie_jar():
    class Cookie:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    class Http:
        cookies = [Cookie("a", "1"), Cookie("empty", ""), Cookie("b", "2")]

    assert chatgpt_session.http_session_cookie_header(Http()) == "a=1; b=2"


def test_playwright_cookie_items_from_header_splits_large_session_cookie():
    session_value = "x" * 4200

    cookies = chatgpt_session.playwright_cookie_items_from_header(
        f"__Secure-next-auth.session-token={session_value}; Path=/; SameSite=Lax; HttpOnly; malformed name=value; small=ok"
    )
    cookie_by_name = {cookie["name"]: cookie for cookie in cookies}

    assert "__Secure-next-auth.session-token" not in cookie_by_name
    assert cookie_by_name["__Secure-next-auth.session-token.0"]["value"] == "x" * 3800
    assert cookie_by_name["__Secure-next-auth.session-token.1"]["value"] == "x" * 400
    assert "Path" not in cookie_by_name
    assert "SameSite" not in cookie_by_name
    assert "malformed name" not in cookie_by_name
    assert cookie_by_name["small"]["value"] == "ok"


def test_inject_chatgpt_browser_cookies_adds_missing_context_cookies():
    class FakeContext:
        def __init__(self):
            self.cookies = []

        def add_cookies(self, cookies):
            self.cookies.extend(cookies)

    class FakeApi:
        def __init__(self):
            self.context = FakeContext()

    api = FakeApi()

    chatgpt_session.inject_chatgpt_browser_cookies(
        api,
        session_token="session",
        cookie_header="small=ok",
        account_id="account",
        device_id="device",
    )
    cookie_by_name = {cookie["name"]: cookie for cookie in api.context.cookies}

    assert cookie_by_name["small"]["value"] == "ok"
    assert cookie_by_name["__Secure-next-auth.session-token"]["value"] == "session"
    assert cookie_by_name["_account"]["value"] == "account"
    assert cookie_by_name["oai-did"]["value"] == "device"


def test_inject_chatgpt_browser_cookies_uses_missing_context_error_factory():
    class FakeApi:
        context = None

    try:
        chatgpt_session.inject_chatgpt_browser_cookies(
            FakeApi(),
            missing_context_error_factory=lambda: ValueError("missing context"),
        )
    except ValueError as exc:
        assert str(exc) == "missing context"
    else:
        raise AssertionError("expected missing context to raise custom error")
