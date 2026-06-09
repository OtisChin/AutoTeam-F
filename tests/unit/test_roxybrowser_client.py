from autotoken.roxybrowser_client import RoxyBrowserClient, _normalize_proxy_info, pick_roxybrowser_endpoint


def test_roxybrowser_proxy_info_from_authenticated_socks_proxy():
    proxy_info = _normalize_proxy_info("socks5://user:pass@proxy.example:3010")

    assert proxy_info == {
        "moduleId": 0,
        "proxyMethod": "custom",
        "proxyCategory": "SOCKS5",
        "protocol": "SOCKS5",
        "ipType": "IPV4",
        "host": "proxy.example",
        "port": 3010,
        "proxyUserName": "user",
        "proxyPassword": "pass",
    }


def test_roxybrowser_connection_endpoint_prefers_http():
    connection = {
        "ws": "ws://127.0.0.1:52314/devtools/browser/abc",
        "http": "127.0.0.1:52314",
    }

    assert pick_roxybrowser_endpoint(connection) == "http://127.0.0.1:52314"


def test_roxybrowser_launch_clears_existing_profile_before_open(monkeypatch):
    calls = []

    def fake_request(self, method, path, *, params=None, json_body=None, timeout=None):
        calls.append((method, path, json_body))
        if path == "/browser/workspace":
            return {"data": [{"workspaceId": 1, "workspaceName": "default"}], "total": 1}
        if path == "/browser/list_v3":
            return {"data": [{"dirId": "dir-1", "windowName": "PayPal"}], "total": 1}
        if path == "/browser/open":
            return {"data": {"http": "127.0.0.1:5566", "ws": "ws://127.0.0.1:5566/devtools/browser/1"}}
        return {"code": 0, "msg": "ok"}

    monkeypatch.setattr(RoxyBrowserClient, "_request", fake_request)

    client = RoxyBrowserClient("http://127.0.0.1:50000", "token")
    result = client.launch(dir_id="dir-1", clear_profile_data=True)

    assert result.dir_id == "dir-1"
    assert ("POST", "/browser/close", {"dirId": "dir-1"}) in calls
    assert ("POST", "/browser/clear_local_cache", {"dirIds": ["dir-1"]}) in calls
    assert ("POST", "/browser/clear_server_cache", {"workspaceId": 1, "dirIds": ["dir-1"]}) in calls
    assert calls[-1] == ("POST", "/browser/open", {"dirId": "dir-1", "args": [], "workspaceId": 1})


def test_roxybrowser_launch_prefers_reusing_idle_profile_before_create(monkeypatch):
    calls = []

    def fake_request(self, method, path, *, params=None, json_body=None, timeout=None):
        calls.append((method, path, json_body, params))
        if path == "/browser/workspace":
            return {"data": [{"workspaceId": 1, "workspaceName": "default"}], "total": 1}
        if path == "/browser/create":
            raise RuntimeError("窗口额度不足")
        if path == "/browser/list_v3":
            return {
                "data": [
                    {"dirId": "busy-dir", "windowName": "Busy", "openStatus": True},
                    {"dirId": "idle-dir", "windowName": "Idle", "openStatus": False},
                ],
                "total": 2,
            }
        if path == "/browser/open":
            return {"data": {"http": "127.0.0.1:5566", "ws": "ws://127.0.0.1:5566/devtools/browser/1"}}
        return {"code": 0, "msg": "ok"}

    monkeypatch.setattr(RoxyBrowserClient, "_request", fake_request)

    client = RoxyBrowserClient("http://127.0.0.1:50000", "token")
    result = client.launch(clear_profile_data=True)

    assert result.dir_id == "idle-dir"
    assert result.created_profile is False
    assert result.reused_existing_profile is True
    assert not any(path == "/browser/create" for _method, path, _json_body, _params in calls)
    assert ("POST", "/browser/clear_local_cache", {"dirIds": ["idle-dir"]}, None) in calls
    assert calls[-1] == ("POST", "/browser/open", {"dirId": "idle-dir", "args": [], "workspaceId": 1}, None)
    client.browser_close("idle-dir")


def test_roxybrowser_launch_create_quota_has_clear_error_when_no_idle_profile(monkeypatch):
    def fake_request(self, method, path, *, params=None, json_body=None, timeout=None):
        if path == "/browser/workspace":
            return {"data": [{"workspaceId": 1, "workspaceName": "default"}], "total": 1}
        if path == "/browser/create":
            raise RuntimeError("窗口额度不足")
        if path == "/browser/list_v3":
            return {"data": [{"dirId": "busy-dir", "windowName": "Busy", "openStatus": True}], "total": 1}
        return {"code": 0, "msg": "ok"}

    monkeypatch.setattr(RoxyBrowserClient, "_request", fake_request)

    client = RoxyBrowserClient("http://127.0.0.1:50000", "token")
    try:
        client.launch(clear_profile_data=True)
    except RuntimeError as exc:
        assert "没有可复用的空闲窗口，且新建窗口额度不足" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
