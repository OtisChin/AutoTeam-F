from autotoken.interfaces import api as interface_api


def test_bind_link_open_default_proxy_selector_uses_us_cliproxy(monkeypatch):
    calls = {}

    def fake_default_proxy_api_url(provider, _proxy_url="", *, country="JP"):
        calls["default"] = {"provider": provider, "proxy_url": _proxy_url, "country": country}
        return "https://api.cliproxy.io/white/api?region=US&num=1"

    def fake_fetch_proxy_from_api_url(api_url, *, default_auth_scheme, provider=""):
        calls["fetch"] = {
            "api_url": api_url,
            "default_auth_scheme": default_auth_scheme,
            "provider": provider,
        }
        return "socks5h://us-proxy.example:3010"

    monkeypatch.setattr(interface_api.proxy_runtime_service, "default_proxy_api_url", fake_default_proxy_api_url)
    monkeypatch.setattr(interface_api.proxy_runtime_service, "fetch_proxy_from_api_url", fake_fetch_proxy_from_api_url)

    assert interface_api._select_bind_link_open_proxy_url() == "socks5h://us-proxy.example:3010"
    assert calls["default"] == {"provider": "cliproxy", "proxy_url": "", "country": "US"}
    assert calls["fetch"] == {
        "api_url": "https://api.cliproxy.io/white/api?region=US&num=1",
        "default_auth_scheme": "socks5h",
        "provider": "cliproxy",
    }


def test_bind_link_open_default_proxy_selector_rejects_empty_us_proxy(monkeypatch):
    monkeypatch.setattr(
        interface_api.proxy_runtime_service,
        "default_proxy_api_url",
        lambda *_args, **_kwargs: "https://api.cliproxy.io/white/api?region=US&num=1",
    )
    monkeypatch.setattr(
        interface_api.proxy_runtime_service,
        "fetch_proxy_from_api_url",
        lambda *_args, **_kwargs: "",
    )

    try:
        interface_api._select_bind_link_open_proxy_url()
    except RuntimeError as exc:
        assert str(exc) == "Cliproxy US 代理 API 未返回可用代理"
    else:
        raise AssertionError("empty Cliproxy US proxy must fail instead of opening directly")


def test_open_bind_checkout_with_auth_session_passes_proxy_to_roxybrowser(monkeypatch):
    launched = {}

    class FakePage:
        url = ""

        def goto(self, url, **_kwargs):
            self.url = url

    class FakeChatGPTTeamAPI:
        def __init__(self):
            self.oai_device_id = ""
            self.page = FakePage()

        def _launch_browser(self, **kwargs):
            launched.update(kwargs)

        def _wait_for_cloudflare(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr("autotoken.integrations.chatgpt_api.ChatGPTTeamAPI", FakeChatGPTTeamAPI)
    monkeypatch.setattr(
        "autotoken.storage.auth_session_store.load_auth_session",
        lambda _email: {"sessionToken": "session-token"},
    )
    monkeypatch.setattr(
        interface_api.chatgpt_session_service,
        "inject_chatgpt_browser_cookies",
        lambda *_args, **_kwargs: None,
    )
    interface_api._bind_checkout_browser_sessions.clear()

    result = interface_api._open_bind_checkout_with_auth_session(
        "User@Example.com",
        "https://chatgpt.com/checkout/openai_llc/oaics_demo",
        open_mode="roxybrowser",
        proxy_url="socks5h://us-proxy.example:3010",
    )

    assert launched["proxy_url"] == "socks5h://us-proxy.example:3010"
    assert launched["use_roxybrowser"] is True
    assert result["open_mode"] == "roxybrowser"
    assert result["open_proxy_url_present"] is True
