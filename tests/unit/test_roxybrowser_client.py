import pytest

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

def test_roxybrowser_fingerprint_can_be_overridden_by_env(monkeypatch):
    calls = []

    def fake_request(self, method, path, *, params=None, json_body=None, timeout=None):
        calls.append((method, path, json_body))
        return {"code": 0, "msg": "ok"}

    monkeypatch.setenv("ROXYBROWSER_DEFAULT_OS", "Android")
    monkeypatch.setenv("ROXYBROWSER_DEFAULT_OS_VERSION", "14")
    monkeypatch.setattr(RoxyBrowserClient, "_request", fake_request)

    client = RoxyBrowserClient("http://127.0.0.1:50000", "token")
    client.browser_mdf(workspace_id="1", dir_id="dir-1")

    assert calls == [
        (
            "POST",
            "/browser/mdf",
            {"workspaceId": 1, "dirId": "dir-1", "os": "Android", "osVersion": "14"},
        )
    ]

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
    assert (
        "POST",
        "/browser/mdf",
        {"workspaceId": 1, "dirId": "idle-dir", "os": "Windows", "osVersion": "10"},
        None,
    ) in calls
    assert calls[-1] == ("POST", "/browser/open", {"dirId": "idle-dir", "args": [], "workspaceId": 1}, None)
    client.browser_close("idle-dir")

def test_roxybrowser_launch_force_new_profile_skips_idle_profile(monkeypatch):
    calls = []

    def fake_request(self, method, path, *, params=None, json_body=None, timeout=None):
        calls.append((method, path, json_body, params))
        if path == "/browser/workspace":
            return {"data": [{"workspaceId": 1, "workspaceName": "default"}], "total": 1}
        if path == "/browser/create":
            return {"data": {"dirId": "new-dir"}}
        if path == "/browser/open":
            return {"data": {"http": "127.0.0.1:5566", "ws": "ws://127.0.0.1:5566/devtools/browser/1"}}
        if path == "/browser/list_v3":
            raise AssertionError("force_new_profile must not inspect idle profiles")
        return {"code": 0, "msg": "ok"}

    monkeypatch.setattr(RoxyBrowserClient, "_request", fake_request)

    client = RoxyBrowserClient("http://127.0.0.1:50000", "token")
    result = client.launch(clear_profile_data=True, force_new_profile=True)

    assert result.dir_id == "new-dir"
    assert result.created_profile is True
    assert result.reused_existing_profile is False
    assert any(path == "/browser/create" for _method, path, _json_body, _params in calls)
    assert not any(path == "/browser/list_v3" for _method, path, _json_body, _params in calls)

def test_roxybrowser_launch_force_new_profile_cleans_project_profiles_after_quota(monkeypatch):
    calls = []
    create_attempts = {"count": 0}

    def fake_request(self, method, path, *, params=None, json_body=None, timeout=None):
        calls.append((method, path, json_body, params))
        if path == "/browser/workspace":
            return {"data": [{"workspaceId": 1, "workspaceName": "default"}], "total": 1}
        if path == "/browser/create":
            create_attempts["count"] += 1
            if create_attempts["count"] == 1:
                raise RuntimeError("窗口额度不足")
            return {"data": {"dirId": "new-dir"}}
        if path == "/browser/list_v3":
            return {
                "data": [
                    {"dirId": "foreign-dir", "windowName": "User Window", "openStatus": False},
                    {"dirId": "project-open-dir", "windowName": "autotoken-chatgpt-open", "openStatus": True},
                    {"dirId": "project-idle-dir", "windowName": "autotoken-chatgpt-idle", "openStatus": False},
                ],
                "total": 3,
            }
        if path == "/browser/open":
            return {"data": {"http": "127.0.0.1:5566", "ws": "ws://127.0.0.1:5566/devtools/browser/1"}}
        return {"code": 0, "msg": "ok"}

    monkeypatch.setattr(RoxyBrowserClient, "_request", fake_request)

    client = RoxyBrowserClient("http://127.0.0.1:50000", "token")
    result = client.launch(clear_profile_data=True, force_new_profile=True)

    assert result.dir_id == "new-dir"
    assert result.created_profile is True
    assert result.reused_existing_profile is False
    assert create_attempts["count"] == 2
    assert ("POST", "/browser/close", {"dirId": "project-open-dir"}, None) in calls
    assert ("POST", "/browser/close", {"dirId": "project-idle-dir"}, None) in calls
    assert (
        "POST",
        "/browser/delete",
        {"workspaceId": 1, "dirIds": ["project-open-dir", "project-idle-dir"]},
        None,
    ) in calls
    assert not any(
        path == "/browser/delete" and "foreign-dir" in (json_body or {}).get("dirIds", [])
        for _method, path, json_body, _params in calls
    )
    assert calls[-1] == ("POST", "/browser/open", {"dirId": "new-dir", "args": [], "workspaceId": 1}, None)
    client.browser_close("new-dir")

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
        assert "没有可清理的本项目窗口，且新建窗口额度不足" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_cleanup_created_roxybrowser_launch_keeps_reservation_until_after_delete():
    from autotoken.roxybrowser_client import RoxyBrowserLaunchResult, cleanup_roxybrowser_launch

    calls = []

    class FakeClient:
        def browser_close(self, dir_id, *, release_reservation=True):
            calls.append(("close", dir_id, release_reservation))

        def browser_delete(self, workspace_id, dir_ids):
            calls.append(("delete", workspace_id, dir_ids))

        def release_profile_reservation(self, dir_id):
            calls.append(("release", dir_id))

    launch = RoxyBrowserLaunchResult(
        workspace_id="workspace-1",
        dir_id="created-dir",
        connection={"http": "127.0.0.1:5566"},
        created_profile=True,
    )

    cleanup_roxybrowser_launch(FakeClient(), launch)

    assert calls == [
        ("close", "created-dir", False),
        ("delete", "workspace-1", ["created-dir"]),
        ("release", "created-dir"),
    ]


def test_roxybrowser_launch_failure_keeps_created_profile_reserved_until_after_delete(monkeypatch):
    from autotoken.roxybrowser_client import RoxyBrowserClient, _RESERVED_PROFILE_IDS

    requests = []
    cleanup_calls = []

    def fake_request(self, method, path, *, params=None, json_body=None, timeout=None):
        requests.append((method, path, json_body, params))
        if path == "/browser/workspace":
            return {"data": [{"workspaceId": 1, "workspaceName": "default"}], "total": 1}
        if path == "/browser/create":
            return {"data": {"dirId": "new-dir"}}
        if path == "/browser/open":
            raise RuntimeError("open failed")
        return {"code": 0, "msg": "ok"}

    def fake_close(self, dir_id, *, release_reservation=True):
        cleanup_calls.append(("close", dir_id, release_reservation))

    def fake_delete(self, workspace_id, dir_ids):
        cleanup_calls.append(("delete", workspace_id, dir_ids))

    def fake_release(self, dir_id):
        cleanup_calls.append(("release", dir_id))
        _RESERVED_PROFILE_IDS.discard(dir_id)

    monkeypatch.setattr(RoxyBrowserClient, "_request", fake_request)
    monkeypatch.setattr(RoxyBrowserClient, "browser_close", fake_close)
    monkeypatch.setattr(RoxyBrowserClient, "browser_delete", fake_delete)
    monkeypatch.setattr(RoxyBrowserClient, "release_profile_reservation", fake_release)

    client = RoxyBrowserClient("http://127.0.0.1:50000", "token")
    try:
        with pytest.raises(RuntimeError, match="open failed"):
            client.launch(force_new_profile=True)

        assert cleanup_calls == [
            ("close", "new-dir", False),
            ("delete", "1", ["new-dir"]),
            ("release", "new-dir"),
        ]
    finally:
        _RESERVED_PROFILE_IDS.discard("new-dir")
