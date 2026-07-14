import pytest

from autotoken.services import paypal_proxy, proxy_runtime


def test_is_paypal_tunnel_connection_error_matches_known_browser_errors():
    assert paypal_proxy.is_paypal_tunnel_connection_error("ERR_TUNNEL_CONNECTION_FAILED") is True
    assert paypal_proxy.is_paypal_tunnel_connection_error("Chrome tunnel connection failed while opening checkout")
    assert paypal_proxy.is_paypal_tunnel_connection_error("HTTP 500") is False
    assert paypal_proxy.is_paypal_tunnel_connection_error("") is False


def test_paypal_protocol_socks_invalid_response_matches_curl_and_socks_messages():
    assert paypal_proxy.paypal_protocol_socks_invalid_response("curl: (97) Invalid proxy response") is True
    assert (
        paypal_proxy.paypal_protocol_socks_invalid_response("Received invalid version in initial SOCKS5 response")
        is True
    )
    assert paypal_proxy.paypal_protocol_socks_invalid_response("HTTP 403") is False


def test_paypal_protocol_http_proxy_fallback_url_converts_authenticated_socks_proxy():
    assert (
        paypal_proxy.paypal_protocol_http_proxy_fallback_url("socks5h://user:pass@proxy.example:1080")
        == "http://user:pass@proxy.example:1080"
    )
    assert paypal_proxy.paypal_protocol_http_proxy_fallback_url("socks5h://proxy.example:1080") == ""
    assert paypal_proxy.paypal_protocol_http_proxy_fallback_url("http://user:pass@proxy.example:8080") == ""
    assert paypal_proxy.paypal_protocol_http_proxy_fallback_url("bad proxy") == ""


def test_paypal_requests_proxy_map_normalizes_socks5_for_requests():
    assert paypal_proxy.paypal_requests_proxy_map("") == {}
    assert paypal_proxy.paypal_requests_proxy_map("socks5://user:pass@proxy.example:1080") == {
        "http": "socks5h://user:pass@proxy.example:1080",
        "https": "socks5h://user:pass@proxy.example:1080",
    }
    assert paypal_proxy.paypal_requests_proxy_map("http://proxy.example:8080") == {
        "http": "http://proxy.example:8080",
        "https": "http://proxy.example:8080",
    }


def test_paypal_requests_proxy_map_preserves_raw_value_when_normalization_fails(monkeypatch):
    monkeypatch.setattr(paypal_proxy, "normalize_proxy_url", lambda value: (_ for _ in ()).throw(ValueError("bad")))

    assert paypal_proxy.paypal_requests_proxy_map("bad proxy") == {
        "http": "bad proxy",
        "https": "bad proxy",
    }


def test_paypal_proxy_exit_location_parses_success_response():
    class Response:
        status_code = 200

        def json(self):
            return {
                "status": "success",
                "countryCode": "jp",
                "regionName": " Tokyo ",
                "city": " Chiyoda ",
                "query": "203.0.113.10",
            }

    class Session:
        def __init__(self):
            self.trust_env = True
            self.proxies = {}
            self.calls = []

        def get(self, url, timeout=None):
            self.calls.append((url, timeout, self.trust_env, self.proxies))
            return Response()

    session = Session()

    assert paypal_proxy.paypal_proxy_exit_location(
        "socks5://proxy.example:1080",
        session_factory=lambda: session,
    ) == {
        "country_code": "JP",
        "region": "Tokyo",
        "city": "Chiyoda",
        "ip": "203.0.113.10",
    }
    assert session.calls == [
        (
            "http://ip-api.com/json/?fields=status,countryCode,regionName,city,query",
            12,
            False,
            {"http": "socks5h://proxy.example:1080", "https": "socks5h://proxy.example:1080"},
        )
    ]


def test_paypal_proxy_exit_location_returns_empty_for_http_or_api_failures():
    class HttpFailureResponse:
        status_code = 500

        def json(self):
            return {"status": "success"}

    class ApiFailureResponse:
        status_code = 200

        def json(self):
            return {"status": "fail"}

    class Session:
        def __init__(self, response):
            self.response = response

        def get(self, *_args, **_kwargs):
            return self.response

    assert (
        paypal_proxy.paypal_proxy_exit_location(
            "http://proxy.example:8080",
            session_factory=lambda: Session(HttpFailureResponse()),
        )
        == {}
    )
    assert (
        paypal_proxy.paypal_proxy_exit_location(
            "http://proxy.example:8080",
            session_factory=lambda: Session(ApiFailureResponse()),
        )
        == {}
    )


def test_paypal_proxy_exit_location_reports_exceptions_to_callback():
    errors = []

    class Session:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("network down")

    assert (
        paypal_proxy.paypal_proxy_exit_location(
            "http://proxy.example:8080",
            session_factory=Session,
            on_error=errors.append,
        )
        == {}
    )
    assert [str(error) for error in errors] == ["network down"]


def test_prepare_paypal_proxy_runtime_infers_api_and_rewrites_protocol_regions():
    runtime = paypal_proxy.prepare_paypal_proxy_runtime(
        proxy_url="socks5://region-JP.example:1080",
        proxy_pool=["socks5://region-ID.example:1080", "socks5://region-ID.example:1080"],
        proxy_pool_text="",
        proxy_api_provider="",
        proxy_api_url="https://api.cliproxy.io/white/api?region=JP&num=1",
        paypal_country="JP",
        protocol_no_card=True,
        paypal_ba_proxy_region="US",
        default_proxy_entry=lambda _provider: "",
    )

    assert runtime.proxy_api_provider == "cliproxy"
    assert runtime.proxy_api_url == "https://api.cliproxy.io/white/api?region=JP&num=1"
    assert runtime.normalized_proxy_url == "socks5://region-JP.example:1080"
    assert runtime.normalized_proxy_pool == ["socks5://region-JP.example:1080"]
    assert runtime.bind_proxy_url == "socks5://region-JP.example:1080"
    assert runtime.provider_proxy_region == "US"


def test_prepare_paypal_proxy_runtime_uses_provider_default_and_default_entry():
    runtime = paypal_proxy.prepare_paypal_proxy_runtime(
        proxy_url="",
        proxy_pool=[],
        proxy_pool_text="",
        proxy_api_provider="1024",
        proxy_api_url="",
        paypal_country="US",
        protocol_no_card=False,
        paypal_ba_proxy_region="US",
        default_proxy_entry=lambda provider: f"socks5://{provider}.example:1080",
    )

    assert runtime.proxy_api_provider == "1024proxy"
    assert runtime.proxy_api_url == "https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=json"
    assert runtime.normalized_proxy_url == "socks5://1024proxy.example:1080"


def test_prepare_paypal_proxy_runtime_prefers_explicit_sticky_proxies():
    runtime = paypal_proxy.prepare_paypal_proxy_runtime(
        proxy_url="socks5://region-ID.example:1080",
        proxy_pool=[],
        proxy_pool_text="",
        proxy_api_provider="",
        proxy_api_url="",
        paypal_jp_proxy_url="socks5://region-JP.example:1080",
        paypal_us_proxy_url="socks5://region-US.example:1080",
        paypal_country="JP",
        protocol_no_card=True,
        paypal_ba_proxy_region="JP",
        default_proxy_entry=lambda _provider: "",
    )

    assert runtime.normalized_proxy_url == "socks5://region-JP.example:1080"
    assert runtime.bind_proxy_url == "socks5://region-JP.example:1080"
    assert runtime.provider_proxy_url == ""
    assert (
        paypal_proxy.select_paypal_provider_proxy(
            runtime,
            selected_proxy_url=runtime.normalized_proxy_url,
            protocol_no_card=True,
            fetch_proxy_from_api_url=lambda *_args, **_kwargs: "socks5://ignored.example:1080",
            default_auth_scheme="socks5",
        )
        == "socks5://region-JP.example:1080"
    )


def test_prepare_paypal_proxy_runtime_uses_us_sticky_for_us_ba_mode():
    runtime = paypal_proxy.prepare_paypal_proxy_runtime(
        proxy_url="socks5://region-JP.example:1080",
        proxy_pool=[],
        proxy_pool_text="",
        proxy_api_provider="",
        proxy_api_url="",
        paypal_jp_proxy_url="socks5://sticky-jp.example:1080",
        paypal_us_proxy_url="socks5://sticky-us.example:1080",
        paypal_country="JP",
        protocol_no_card=True,
        paypal_ba_proxy_region="US",
        default_proxy_entry=lambda _provider: "",
    )

    assert runtime.normalized_proxy_url == "socks5://sticky-jp.example:1080"
    assert runtime.bind_proxy_url == "socks5://sticky-jp.example:1080"
    assert runtime.provider_proxy_url == "socks5://sticky-us.example:1080"


def test_prepare_paypal_proxy_runtime_rewrites_payment_sticky_for_au_provider():
    runtime = paypal_proxy.prepare_paypal_proxy_runtime(
        proxy_url="socks5://region-JP.example:1080",
        proxy_pool=[],
        proxy_pool_text="",
        proxy_api_provider="",
        proxy_api_url="",
        paypal_jp_proxy_url="socks5://sticky-jp.example:1080",
        paypal_us_proxy_url="socks5://region-US.example:1080",
        paypal_country="JP",
        protocol_no_card=True,
        paypal_ba_proxy_region="AU",
        default_proxy_entry=lambda _provider: "",
    )

    assert runtime.normalized_proxy_url == "socks5://sticky-jp.example:1080"
    assert runtime.bind_proxy_url == "socks5://sticky-jp.example:1080"
    assert runtime.provider_proxy_region == "AU"
    assert runtime.provider_proxy_url == "socks5://region-AU.example:1080"
    assert (
        paypal_proxy.select_paypal_provider_proxy(
            runtime,
            selected_proxy_url=runtime.normalized_proxy_url,
            protocol_no_card=True,
            fetch_proxy_from_api_url=lambda *_args, **_kwargs: "socks5://ignored.example:1080",
            default_auth_scheme="socks5",
        )
        == "socks5://region-AU.example:1080"
    )


def test_prepare_paypal_proxy_runtime_uses_gb_checkout_and_jp_provider_for_gb_mode():
    runtime = paypal_proxy.prepare_paypal_proxy_runtime(
        proxy_url="",
        proxy_pool=[],
        proxy_pool_text="",
        proxy_api_provider="",
        proxy_api_url="",
        paypal_jp_proxy_url=(
            "socks5://user-region-JP-sid-base-t-120:pass@proxy.example:3010"
        ),
        paypal_us_proxy_url="",
        paypal_country="JP",
        protocol_no_card=True,
        paypal_ba_proxy_region="US",
        paypal_ba_mode="gb",
        default_proxy_entry=lambda _provider: "",
    )

    assert "region-GB" in runtime.bind_proxy_url
    assert runtime.provider_proxy_region == "JP"


def test_proxy_url_for_region_and_sid_replaces_routed_username_fields():
    result = proxy_runtime.proxy_url_for_region_and_sid(
        "socks5://user-region-JP-sid-old-t-120:pass@proxy.example:3010",
        "GB",
        "fresh123",
    )

    assert result == (
        "socks5://user-region-GB-sid-fresh123-t-120:pass@proxy.example:3010"
    )


def test_proxy_url_for_region_and_sid_leaves_plain_proxy_unchanged():
    assert (
        proxy_runtime.proxy_url_for_region_and_sid(
            "socks5://user:pass@proxy.example:3010",
            "GB",
            "fresh123",
        )
        == "socks5://user:pass@proxy.example:3010"
    )


def test_prepare_paypal_proxy_runtime_promotes_proxy_pool_api_url():
    runtime = paypal_proxy.prepare_paypal_proxy_runtime(
        proxy_url="",
        proxy_pool=["https://white.1024proxy.com/white/api?region=US&num=1", "socks5://pool.example:1080"],
        proxy_pool_text="",
        proxy_api_provider="",
        proxy_api_url="",
        paypal_country="US",
        protocol_no_card=False,
        paypal_ba_proxy_region="US",
        default_proxy_entry=lambda _provider: "",
    )

    assert runtime.proxy_api_provider == "1024proxy"
    assert runtime.proxy_api_url == "https://white.1024proxy.com/white/api?region=US&num=1"
    assert runtime.normalized_proxy_pool == ["socks5://pool.example:1080"]


def test_prepare_paypal_proxy_runtime_preserves_error_messages():
    with pytest.raises(ValueError, match="代理格式错误: bad proxy"):
        paypal_proxy.prepare_paypal_proxy_runtime(
            proxy_url="bad proxy",
            proxy_pool=[],
            proxy_pool_text="",
            proxy_api_provider="",
            proxy_api_url="",
            paypal_country="US",
            protocol_no_card=False,
            paypal_ba_proxy_region="US",
            default_proxy_entry=lambda _provider: "",
        )


def test_prepare_paypal_proxy_runtime_preserves_pool_error_messages():
    with pytest.raises(ValueError, match="动态代理池格式错误: bad pool"):
        paypal_proxy.prepare_paypal_proxy_runtime(
            proxy_url="",
            proxy_pool=["bad pool"],
            proxy_pool_text="",
            proxy_api_provider="",
            proxy_api_url="",
            paypal_country="US",
            protocol_no_card=False,
            paypal_ba_proxy_region="US",
            default_proxy_entry=lambda _provider: "",
        )


def test_select_paypal_proxy_uses_static_pool(monkeypatch):
    runtime = paypal_proxy.PayPalProxyRuntime(
        proxy_api_url="",
        proxy_api_provider="",
        normalized_proxy_url="",
        normalized_proxy_pool=["socks5://one.example:1080", "socks5://two.example:1080"],
        bind_proxy_url="",
    )

    monkeypatch.setattr(paypal_proxy.random, "choice", lambda values: values[1])

    assert (
        paypal_proxy.select_paypal_proxy(
            runtime,
            fetch_proxy_from_api_url=lambda *_args, **_kwargs: "",
            default_auth_scheme="socks5",
        )
        == "socks5://two.example:1080"
    )


def test_select_paypal_proxy_raises_when_api_returns_empty_without_fallback():
    runtime = paypal_proxy.PayPalProxyRuntime(
        proxy_api_url="https://api.cliproxy.io/white/api?region=JP&num=1",
        proxy_api_provider="cliproxy",
        normalized_proxy_url="",
        normalized_proxy_pool=[],
        bind_proxy_url="",
    )

    with pytest.raises(RuntimeError, match="Cliproxy API 已触发换 IP"):
        paypal_proxy.select_paypal_proxy(
            runtime,
            fetch_proxy_from_api_url=lambda *_args, **_kwargs: "",
            default_auth_scheme="socks5",
        )


def test_select_paypal_proxy_and_provider_proxy():
    runtime = paypal_proxy.PayPalProxyRuntime(
        proxy_api_url="https://api.cliproxy.io/white/api?region=JP&num=1",
        proxy_api_provider="cliproxy",
        normalized_proxy_url="socks5://region-US.example:1080",
        normalized_proxy_pool=[],
        bind_proxy_url="socks5://region-US.example:1080",
    )
    calls = []

    def fetch(api_url, *, default_auth_scheme, provider):
        calls.append((api_url, default_auth_scheme, provider))
        return "" if len(calls) == 1 else "socks5://fetched.example:1080"

    assert (
        paypal_proxy.select_paypal_proxy(
            runtime,
            fetch_proxy_from_api_url=fetch,
            default_auth_scheme="socks5",
        )
        == "socks5://region-US.example:1080"
    )
    assert (
        paypal_proxy.select_paypal_provider_proxy(
            runtime,
            selected_proxy_url="socks5://region-JP.example:1080",
            protocol_no_card=True,
            fetch_proxy_from_api_url=fetch,
            default_auth_scheme="socks5",
        )
        == "socks5://fetched.example:1080"
    )
    assert calls[1][0] == "https://api.cliproxy.io/white/api?region=US&num=1"


def test_select_paypal_provider_proxy_respects_protocol_and_derives_without_api():
    runtime = paypal_proxy.PayPalProxyRuntime(
        proxy_api_url="",
        proxy_api_provider="",
        normalized_proxy_url="",
        normalized_proxy_pool=[],
        bind_proxy_url="",
    )

    assert (
        paypal_proxy.select_paypal_provider_proxy(
            runtime,
            selected_proxy_url="socks5://region-JP.example:1080",
            protocol_no_card=False,
            fetch_proxy_from_api_url=lambda *_args, **_kwargs: "socks5://ignored.example:1080",
            default_auth_scheme="socks5",
        )
        == ""
    )
    assert (
        paypal_proxy.select_paypal_provider_proxy(
            runtime,
            selected_proxy_url="socks5://region-JP.example:1080",
            protocol_no_card=True,
            fetch_proxy_from_api_url=lambda *_args, **_kwargs: "",
            default_auth_scheme="socks5",
        )
        == "socks5://region-US.example:1080"
    )

    au_runtime = paypal_proxy.PayPalProxyRuntime(
        proxy_api_url="",
        proxy_api_provider="",
        normalized_proxy_url="",
        normalized_proxy_pool=[],
        bind_proxy_url="",
        provider_proxy_region="AU",
    )
    assert (
        paypal_proxy.select_paypal_provider_proxy(
            au_runtime,
            selected_proxy_url="socks5://region-JP.example:1080",
            protocol_no_card=True,
            fetch_proxy_from_api_url=lambda *_args, **_kwargs: "",
            default_auth_scheme="socks5",
        )
        == "socks5://region-AU.example:1080"
    )


def test_paypal_proxy_selected_progress_preserves_api_and_pool_shapes():
    api_progress = paypal_proxy.paypal_proxy_selected_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=0,
        proxy_label="pool-a",
        proxy_pool_count=3,
        proxy_api_url_present=True,
        proxy_api_provider="cliproxy",
        selected_proxy_summary="socks5h://***",
        using_proxy_api=True,
    )
    pool_progress = paypal_proxy.paypal_proxy_selected_progress(
        email="user@example.com",
        current=1,
        total=2,
        proxy_label="pool-a",
        proxy_pool_count=3,
        proxy_api_url_present=False,
        proxy_api_provider="",
        selected_proxy_summary="socks5h://***",
        using_proxy_api=False,
    )

    assert api_progress == {
        "stage": "paypal_proxy_api_selected",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "proxy_label": "pool-a",
        "proxy_pool_count": 3,
        "proxy_api_url_present": True,
        "proxy_api_provider": "cliproxy",
        "message": "已通过 cliproxy API 轮换代理: socks5h://***",
        "retry_round": 0,
    }
    assert pool_progress == {
        "stage": "paypal_proxy_selected",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "proxy_label": "pool-a",
        "proxy_pool_count": 3,
        "proxy_api_url_present": False,
        "proxy_api_provider": "",
        "message": "已从动态代理池随机选择代理: socks5h://***",
    }


def test_paypal_proxy_selected_progress_supports_ba_retry_fields():
    progress = paypal_proxy.paypal_proxy_selected_progress(
        email="user@example.com",
        current=1,
        total=2,
        retry_round=1,
        ba_attempt=2,
        proxy_label="pool-a",
        proxy_pool_count=3,
        proxy_api_url_present=True,
        proxy_api_provider="cliproxy",
        selected_proxy_summary="socks5h://***",
        using_proxy_api=True,
        ba_retry=True,
    )

    assert progress["stage"] == "paypal_proxy_api_selected"
    assert progress["retry_round"] == 1
    assert progress["ba_attempt"] == 2
    assert progress["message"] == "PayPal BA 重试已通过 cliproxy API 轮换代理: socks5h://***"


def test_paypal_proxy_failed_and_probe_progress_payloads():
    failed = paypal_proxy.paypal_proxy_api_failed_progress(
        email="user@example.com",
        current=1,
        total=2,
        proxy_label="pool-a",
        proxy_api_provider="cliproxy",
        error=RuntimeError("api down"),
    )
    probe = paypal_proxy.paypal_proxy_api_probe_progress(
        email="user@example.com",
        current=1,
        total=2,
        proxy_label="pool-a",
        proxy_api_provider="cliproxy",
        exit_ip="203.0.113.10",
    )

    assert failed == {
        "stage": "paypal_proxy_api_failed",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "proxy_label": "pool-a",
        "proxy_api_provider": "cliproxy",
        "message": "动态代理 API 获取失败: api down",
        "level": "error",
    }
    assert probe == {
        "stage": "paypal_proxy_api_probe",
        "email": "user@example.com",
        "current": 1,
        "total": 2,
        "proxy_label": "pool-a",
        "proxy_api_provider": "cliproxy",
        "message": "代理出口 IP 探测成功: 203.0.113.10",
    }
