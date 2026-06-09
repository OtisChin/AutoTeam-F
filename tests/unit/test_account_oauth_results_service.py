from autotoken import api
from autotoken.services import account_oauth_results


def test_oauth_phone_required_result_keeps_account_in_pool():
    result = account_oauth_results.oauth_phone_required_result(
        "user@example.com",
        RuntimeError("add-phone"),
    )

    assert result == {
        "email": "user@example.com",
        "status": "failed",
        "failure_stage": "oauth_phone_required",
        "message": "OAuth 需要手机验证，但手机号绑定流程未完成，账号已保留: user@example.com",
        "error": "add-phone",
        "removed_pool_emails": [],
    }


def test_oauth_phone_rate_limited_result_keeps_account_in_pool():
    result = account_oauth_results.oauth_phone_rate_limited_result("user@example.com", RuntimeError("too many"))

    assert result["failure_stage"] == "oauth_phone_rate_limited"
    assert result["message"] == "OAuth 手机号验证请求次数过多，已跳过当前账号: user@example.com"
    assert result["error"] == "too many"
    assert result["removed_pool_emails"] == []


def test_oauth_login_required_result_keeps_account_in_pool():
    result = account_oauth_results.oauth_login_required_result("user@example.com", RuntimeError("login page"))

    assert result["failure_stage"] == "oauth_login_required"
    assert result["message"] == "OAuth 停在登录页，未获取 authorization code，账号已保留: user@example.com"
    assert result["error"] == "login page"
    assert result["removed_pool_emails"] == []


def test_oauth_account_deactivated_result_removes_account_with_callback():
    calls = []

    result = account_oauth_results.oauth_account_deactivated_result(
        "dead@example.com",
        RuntimeError("account_deactivated"),
        remove_account_from_pool=lambda emails: calls.append(emails) or emails,
    )

    assert calls == [["dead@example.com"]]
    assert result == {
        "email": "dead@example.com",
        "status": "failed",
        "failure_stage": "oauth_account_deactivated",
        "message": "OAuth 检测到 account_deactivated，已从号池删除账号: dead@example.com",
        "error": "account_deactivated",
        "removed_pool_emails": ["dead@example.com"],
    }


def test_api_keeps_oauth_result_compatibility_wrappers(monkeypatch):
    monkeypatch.setattr(api, "_remove_oauth_account_deactivated_accounts_from_pool", lambda emails: [emails[0]])

    assert api._oauth_phone_required_result("user@example.com", RuntimeError("phone"))["failure_stage"] == (
        "oauth_phone_required"
    )
    assert api._oauth_account_deactivated_result("dead@example.com", RuntimeError("dead"))[
        "removed_pool_emails"
    ] == ["dead@example.com"]
