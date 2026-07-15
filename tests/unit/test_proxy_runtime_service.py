import pytest

from autotoken.services import proxy_runtime


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


def test_proxy_api_url_detection_and_provider_defaults():
    api_url = "https://dashboard.1024proxy.com/getporxy/traffic?demo=1"

    assert proxy_runtime.is_proxy_api_url(api_url) is True
    assert proxy_runtime.infer_proxy_api_provider_from_url(api_url) == "1024proxy"
    assert proxy_runtime.default_proxy_api_url("1024") == (
        "https://white.1024proxy.com/white/api?region=JP&num=1&time=10&format=1&type=json"
    )
    assert proxy_runtime.default_proxy_api_url("cliproxy") == (
        "https://api.cliproxy.io/white/api?region=JP&num=1&time=30&format=n&type=json"
    )
    assert proxy_runtime.default_proxy_api_url("cliproxy", country="us") == (
        "https://api.cliproxy.io/white/api?region=US&num=1&time=30&format=n&type=json"
    )
    assert proxy_runtime.default_paypal_proxy_api_url("1024") == (
        "https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=json"
    )
    assert proxy_runtime.default_gopay_proxy_api_url("cliproxy") == (
        "https://api.cliproxy.io/white/api?region=ID&num=1&time=30&format=n&type=txt"
    )


def test_default_paypal_proxy_api_url_uses_country_except_protocol_no_card_default():
    assert proxy_runtime.default_paypal_proxy_api_url("1024proxy", country="JP") == (
        "https://white.1024proxy.com/white/api?region=JP&num=1&time=10&format=1&type=json"
    )
    assert proxy_runtime.default_paypal_proxy_api_url("cliproxy", country="jp") == (
        "https://api.cliproxy.io/white/api?region=JP&num=1&time=30&format=n&type=json"
    )
    assert proxy_runtime.default_paypal_proxy_api_url("1024proxy", country="JP", protocol_no_card=True) == (
        "https://white.1024proxy.com/white/api?region=JP&num=1&time=10&format=1&type=json"
    )


def test_proxy_api_url_with_region_replaces_existing_region():
    assert proxy_runtime.proxy_api_url_with_region("https://api.example.test/white/api?region=JP&num=1", "us") == (
        "https://api.example.test/white/api?region=US&num=1"
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
