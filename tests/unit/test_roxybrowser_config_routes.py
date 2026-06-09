import anyio

from autotoken.api_routes.roxybrowser_config import create_roxybrowser_config_router


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_roxybrowser_config_router(mask_secret=lambda value: f"masked:{value}").routes
    }


def test_roxybrowser_config_response_uses_runtime_env(monkeypatch):
    monkeypatch.setenv("ROXYBROWSER_API_HOST", "127.0.0.1:50000")
    monkeypatch.setenv("ROXYBROWSER_API_TOKEN", "secret-token")
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    cfg = _routes()["get_roxybrowser_config_api"]()

    assert cfg["api_host"] == "http://127.0.0.1:50000"
    assert cfg["api_token_present"] is True
    assert cfg["api_token_masked"] == "masked:secret-token"
    assert "workspace_id" not in cfg
    assert "dir_id" not in cfg
    assert cfg["configured"] is True


def test_roxybrowser_config_response_marks_missing_token(monkeypatch):
    monkeypatch.setenv("ROXYBROWSER_API_HOST", "http://127.0.0.1:50000")
    monkeypatch.delenv("ROXYBROWSER_API_TOKEN", raising=False)
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})

    cfg = _routes()["get_roxybrowser_config_api"]()

    assert cfg["api_host"] == "http://127.0.0.1:50000"
    assert cfg["api_token_present"] is False
    assert cfg["configured"] is False
    assert "ROXYBROWSER_API_TOKEN" in cfg["missing_keys"]


def test_save_roxybrowser_config_normalizes_host_and_writes_env(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_roxybrowser_config_api"],
        FakeRequest({"api_host": "127.0.0.1:50000/", "api_token": "secret-token"}),
    )

    assert written == {
        "ROXYBROWSER_API_HOST": "http://127.0.0.1:50000",
        "ROXYBROWSER_API_TOKEN": "secret-token",
    }
    assert result["message"] == "RoxyBrowser 配置已保存"
    assert result["api_host"] == "http://127.0.0.1:50000"
    assert result["configured"] is True


def test_roxybrowser_workspaces_and_profiles_use_configured_client(monkeypatch):
    monkeypatch.setenv("ROXYBROWSER_API_HOST", "http://roxy.local:50000")
    monkeypatch.setenv("ROXYBROWSER_API_TOKEN", "secret-token")
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})
    calls = []

    class FakeClient:
        def __init__(self, api_host, api_token):
            calls.append((api_host, api_token))

        def list_workspaces(self):
            return [{"id": "workspace-1"}]

        def list_all_profiles(self):
            return [{"id": "profile-1"}]

    monkeypatch.setattr("autotoken.roxybrowser_client.RoxyBrowserClient", FakeClient)

    routes = _routes()
    workspaces = routes["get_roxybrowser_workspaces_api"]()
    profiles = routes["get_roxybrowser_profiles_api"]()

    assert workspaces == {"workspaces": [{"id": "workspace-1"}], "count": 1}
    assert profiles == {"profiles": [{"id": "profile-1"}], "count": 1}
    assert calls == [
        ("http://roxy.local:50000", "secret-token"),
        ("http://roxy.local:50000", "secret-token"),
    ]
