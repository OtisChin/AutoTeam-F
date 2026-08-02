import pytest

from autotoken.services import payment_http, proxy_runtime


def test_parse_proxy_pool_values_dedupes_comments_and_text_lines():
    values = ["1.1.1.1:8080:user:pass", " # ignored"]
    text = "1.1.1.1:8080:user:pass\n2.2.2.2:8080:u:p # comment"

    assert proxy_runtime.parse_proxy_pool_values(values, text) == [
        "1.1.1.1:8080:user:pass",
        "2.2.2.2:8080:u:p",
    ]

def test_parse_proxy_pool_values_rejects_oversized_text_before_splitting():
    with pytest.raises(ValueError, match="代理池文本过大"):
        proxy_runtime.parse_proxy_pool_values(text=" " * (proxy_runtime.PROXY_POOL_TEXT_MAX_BYTES + 1))

def test_parse_proxy_pool_values_rejects_too_many_candidates():
    values = [f"socks5://proxy-{index}.example:1080" for index in range(proxy_runtime.PROXY_POOL_MAX_ENTRIES + 1)]

    with pytest.raises(ValueError, match="代理池条目过多"):
        proxy_runtime.parse_proxy_pool_values(values=values)

def test_proxy_api_url_with_region_replaces_existing_region():
    assert proxy_runtime.proxy_api_url_with_region("https://api.example.test/white/api?region=JP&num=1", "us") == (
        "https://api.example.test/white/api?region=US&num=1"
    )

def test_normalize_proxy_api_provider_accepts_711proxy_aliases():
    assert proxy_runtime.normalize_proxy_api_provider("711Proxy") == "711proxy"
    assert proxy_runtime.normalize_proxy_api_provider("711") == "711proxy"

def test_default_proxy_api_url_builds_711proxy_residential_url():
    assert proxy_runtime.default_proxy_api_url("711proxy", country="US") == (
        "http://global.rotgbapi.711proxy.com:8089/gen?"
        "zone=custom&ptype=1&region=US&count=1&proto=http&stype=text&split=%5Cr%5Cn&"
        "sessType=sticky&sessTime=30&sessAuto=1"
    )

def test_infer_proxy_api_provider_detects_711proxy_url():
    assert (
        proxy_runtime.infer_proxy_api_provider_from_url(
            "http://global.rotgbapi.711proxy.com:8089/gen?zone=custom&region=US"
        )
        == "711proxy"
    )

def test_fetch_proxy_from_api_url_normalizes_1024proxy_to_default_scheme(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        text = "1.1.1.1:8080:user-a:pass-a"

    monkeypatch.setattr(proxy_runtime.requests, "get", lambda url, timeout: FakeResponse())

    assert (
        proxy_runtime.fetch_proxy_from_api_url(
            "https://dashboard.1024proxy.com/getporxy/traffic?demo=1",
            default_auth_scheme="socks5h",
            provider="1024proxy",
        )
        == "socks5h://user-a:pass-a@1.1.1.1:8080"
    )

def test_fetch_proxy_from_api_url_normalizes_711proxy_to_http(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        text = "5.5.5.5:8080"

    monkeypatch.setattr(proxy_runtime.requests, "get", lambda url, timeout: FakeResponse())

    assert (
        proxy_runtime.fetch_proxy_from_api_url(
            "http://global.rotgbapi.711proxy.com:8089/gen?zone=custom&region=US",
            default_auth_scheme=proxy_runtime.default_proxy_auth_scheme("711proxy"),
            provider="711proxy",
        )
        == "http://5.5.5.5:8080"
    )

def test_fetch_proxy_from_api_url_rejects_html_response(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<!doctype html><html><body>login</body></html>"

    monkeypatch.setattr(proxy_runtime.requests, "get", lambda url, timeout: FakeResponse())

    with pytest.raises(RuntimeError, match="返回 HTML 页面"):
        proxy_runtime.fetch_proxy_from_api_url(
            "https://dashboard.1024proxy.com/getporxy/traffic?demo=1",
            default_auth_scheme="socks5h",
            provider="1024proxy",
        )

def test_build_oauth_proxy_selector_treats_proxy_pool_api_url_as_api(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"data":["3.3.3.3:8080:user-c:pass-c"]}'

        def json(self):
            return {"data": ["3.3.3.3:8080:user-c:pass-c"]}

    monkeypatch.setattr(proxy_runtime.requests, "get", lambda url, timeout: FakeResponse())

    selector, meta = proxy_runtime.build_oauth_proxy_selector(
        proxy_pool_text="https://dashboard.1024proxy.com/getporxy/traffic?demo=1",
        default_auth_scheme="socks5h",
    )

    assert meta == {
        "proxy_url_present": False,
        "proxy_pool_count": 0,
        "proxy_api_provider": "1024proxy",
        "proxy_api_url_present": True,
    }
    assert selector() == "socks5h://user-c:pass-c@3.3.3.3:8080"

def test_build_oauth_proxy_selector_uses_proxy_api_country(monkeypatch):
    requested_urls = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        text = "4.4.4.4:8080:user-d:pass-d"

    def fake_get(url, timeout):
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(proxy_runtime.requests, "get", fake_get)

    selector, meta = proxy_runtime.build_oauth_proxy_selector(
        proxy_api_provider="cliproxy",
        proxy_api_country="us",
        default_auth_scheme="socks5h",
    )

    assert meta["proxy_api_provider"] == "cliproxy"
    assert selector() == "socks5h://user-d:pass-d@4.4.4.4:8080"
    assert requested_urls == [
        "https://api.cliproxy.io/white/api?region=US&num=1&time=30&format=n&type=json"
    ]


def test_build_oauth_proxy_selector_infers_711proxy_api_url(monkeypatch):
    requested = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        text = "6.6.6.6:8080"

    def fake_get(url, timeout):
        requested.append(url)
        return FakeResponse()

    monkeypatch.setattr(proxy_runtime.requests, "get", fake_get)

    selector, meta = proxy_runtime.build_oauth_proxy_selector(
        proxy_api_url="http://global.rotgbapi.711proxy.com:8089/gen?zone=custom&region=US",
    )

    assert meta["proxy_api_provider"] == "711proxy"
    assert selector() == "http://6.6.6.6:8080"
    assert requested == ["http://global.rotgbapi.711proxy.com:8089/gen?zone=custom&region=US"]


def test_preflight_payment_proxy_rejects_chatgpt_homepage_403(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, text="", headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

    class FakeSession:
        def get(self, url, timeout):
            calls.append(url)
            if url.endswith("/cdn-cgi/trace"):
                return FakeResponse(200, "loc=IN\n")
            return FakeResponse(
                403,
                "<html><head><title>Access denied</title></head><body>cloudflare challenge</body></html>",
                {"content-type": "text/html", "cf-ray": "ray-test"},
            )

        def close(self):
            pass

    monkeypatch.setattr(payment_http, "new_http_session", lambda *args, **kwargs: FakeSession())

    ok, message = proxy_runtime.preflight_payment_proxy_url("socks5h://user:pass@proxy.example:1000")

    assert ok is False
    assert "chatgpt_home HTTP 403" in message
    assert "html_challenge" in message
    assert calls == ["https://chatgpt.com/cdn-cgi/trace", "https://chatgpt.com/"]


def test_preflight_payment_proxy_accepts_trace_and_homepage_200(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, text="", headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

    class FakeSession:
        def get(self, url, timeout):
            calls.append(url)
            return FakeResponse(200, "ok", {"content-type": "text/plain" if url.endswith("/trace") else "text/html"})

        def close(self):
            pass

    monkeypatch.setattr(payment_http, "new_http_session", lambda *args, **kwargs: FakeSession())

    ok, message = proxy_runtime.preflight_payment_proxy_url("socks5h://user:pass@proxy.example:1000")

    assert ok is True
    assert message == "trace HTTP 200; chatgpt_home HTTP 200"
    assert calls == ["https://chatgpt.com/cdn-cgi/trace", "https://chatgpt.com/"]


def test_preflight_authenticated_proxy_rejects_backend_403_html(monkeypatch):
    class FakeResponse:
        status_code = 403
        text = "<html><body>cloudflare access denied</body></html>"
        headers = {"content-type": "text/html", "cf-ray": "ray-test"}

    class FakeSession:
        headers = {}
        proxies = {}

        def get(self, url, timeout):
            assert url == "https://chatgpt.com/backend-api/me"
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(payment_http, "new_http_session", lambda *args, **kwargs: FakeSession())

    ok, message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url("socks5h://user:pass@proxy.example:1000", "token")

    assert ok is False
    assert "auth_api HTTP 403" in message
    assert "html_challenge" in message


def test_preflight_authenticated_proxy_reports_token_revoked(monkeypatch):
    class FakeResponse:
        status_code = 401
        text = '{"error":{"code":"token_revoked"},"status":401}'
        headers = {"content-type": "application/json"}

    class FakeSession:
        headers = {}
        proxies = {}

        def get(self, url, timeout):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(payment_http, "new_http_session", lambda *args, **kwargs: FakeSession())

    ok, message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url("socks5h://user:pass@proxy.example:1000", "token")

    assert ok is False
    assert "auth_api HTTP 401" in message
    assert "token_revoked" in message


def test_preflight_authenticated_proxy_accepts_backend_200(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = '{"object":"user"}'
        headers = {"content-type": "application/json"}

    class FakeSession:
        headers = {}
        proxies = {}

        def get(self, url, timeout):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(payment_http, "new_http_session", lambda *args, **kwargs: FakeSession())

    ok, message = proxy_runtime.preflight_chatgpt_authenticated_proxy_url("socks5h://user:pass@proxy.example:1000", "token")

    assert ok is True
    assert message == "auth_api HTTP 200"
