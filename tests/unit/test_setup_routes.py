import json

from fastapi.responses import JSONResponse
from starlette.requests import Request

from autotoken.api_routes.setup import SetupConfig, create_setup_router


def _request_with_authorization(value: str = "") -> Request:
    headers = []
    if value:
        headers.append((b"authorization", value.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/auth/check",
            "headers": headers,
            "query_string": b"",
        }
    )


def _routes(state: dict[str, str]):
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_setup_router(
            get_api_key=lambda: state.get("api_key", ""),
            set_api_key=lambda value: state.update({"api_key": value}),
        ).routes
    }


def test_check_auth_allows_access_when_api_key_is_unconfigured():
    routes = _routes({"api_key": ""})

    result = routes["check_auth"](_request_with_authorization())

    assert result == {"authenticated": True, "auth_required": False}


def test_check_auth_accepts_matching_bearer_token():
    routes = _routes({"api_key": "secret"})

    result = routes["check_auth"](_request_with_authorization("Bearer secret"))

    assert result == {"authenticated": True, "auth_required": True}


def test_check_auth_rejects_invalid_bearer_token():
    routes = _routes({"api_key": "secret"})

    result = routes["check_auth"](_request_with_authorization("Bearer wrong"))

    assert isinstance(result, JSONResponse)
    assert result.status_code == 401
    assert json.loads(result.body) == {"authenticated": False, "auth_required": True}


def test_post_setup_save_failure_returns_generated_key_without_updating_runtime_key(monkeypatch):
    state = {"api_key": ""}
    written = {}

    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written.update({key: value}))
    monkeypatch.setattr("autotoken.setup_wizard._verify_temporary_email", lambda: False)
    monkeypatch.setattr("autotoken.setup_wizard._verify_cpa", lambda: True)
    monkeypatch.setattr("secrets.token_urlsafe", lambda _n: "generated-token")
    monkeypatch.setattr("importlib.reload", lambda module: module)

    result = _routes(state)["post_setup_save"](
        SetupConfig(
            MAIL_PROVIDER="cloudflare_temp_email",
            CLOUDFLARE_TEMP_EMAIL_BASE_URL="http://mail.example.com",
            CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD="secret",
            CLOUDFLARE_TEMP_EMAIL_DOMAIN="@example.com",
            CPA_URL="",
            CPA_KEY="",
            API_KEY="",
        )
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 400
    assert json.loads(result.body) == {"message": "临时邮箱服务连接失败", "api_key": "generated-token"}
    assert written["API_KEY"] == "generated-token"
    assert state["api_key"] == ""
