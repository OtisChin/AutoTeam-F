import pytest

from autotoken.interfaces.manager import _detect_registration_trial_eligibility


class FakePage:
    def __init__(self, payload):
        self._payload = payload

    def evaluate(self, script):
        return self._payload


def test_trial_detection_persists_eligible_from_available_plans(monkeypatch):
    updated = {}
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account", lambda email, **payload: updated.update(payload) or {}
    )

    def fake_normalize(raw, account_id=""):
        return {"available_plans": ["chatgptplusplan"]}

    monkeypatch.setattr("autotoken.api_routes.account_overview.normalize_chatgpt_subscription", fake_normalize)
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda token, account_id="", proxy_url="": {"raw": {"subscription": {"plan_type": "free"}}},
    )

    result = _detect_registration_trial_eligibility("user@example.com", "tok", "acct_1")

    assert result["trial_eligible"] is True
    assert result["trial_available_plans"] == ["chatgptplusplan"]
    assert updated["trial_eligible"] is True
    assert updated["trial_available_plans"] == ["chatgptplusplan"]
    assert updated["trial_checked_at"] > 0


def test_trial_detection_persists_not_eligible_when_no_plans(monkeypatch):
    updated = {}
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account", lambda email, **payload: updated.update(payload) or {}
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.normalize_chatgpt_subscription",
        lambda raw, account_id="": {"available_plans": []},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda token, account_id="", proxy_url="": {"raw": {"subscription": {"plan_type": "free"}}},
    )

    result = _detect_registration_trial_eligibility("user@example.com", "tok", "acct_1")

    assert result["trial_eligible"] is False
    assert updated["trial_eligible"] is False


def test_trial_detection_skips_when_missing_token_or_account(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *args, **kwargs: calls.append(1) or {},
    )

    result = _detect_registration_trial_eligibility("user@example.com", "", "")

    assert result["trial_eligible"] is False
    assert calls == []


def test_trial_detection_uses_browser_page_when_available(monkeypatch):
    updated = {}
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account", lambda email, **payload: updated.update(payload) or {}
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.normalize_chatgpt_subscription",
        lambda raw, account_id="": {"available_plans": ["chatgptplusplan"]},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *args, **kwargs: pytest.fail("should not fall back to HTTP when page works"),
    )
    page = FakePage({"status": 200, "data": {"plan_type": "free"}})

    result = _detect_registration_trial_eligibility("user@example.com", "tok", "acct_1", page=page)

    assert result["trial_eligible"] is True
    assert updated["trial_eligible"] is True


def test_trial_detection_falls_back_to_http_when_page_fails(monkeypatch):
    updated = {}
    monkeypatch.setattr(
        "autotoken.storage.accounts.update_account", lambda email, **payload: updated.update(payload) or {}
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.normalize_chatgpt_subscription",
        lambda raw, account_id="": {"available_plans": ["chatgptteamplan"]},
    )
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda token, account_id="", proxy_url="": {"raw": {"subscription": {"plan_type": "free"}}},
    )

    class BrokenPage:
        def evaluate(self, script):
            raise RuntimeError("page closed")

    result = _detect_registration_trial_eligibility("user@example.com", "tok", "acct_1", page=BrokenPage())

    assert result["trial_eligible"] is True
    assert updated["trial_eligible"] is True
    assert "chatgptteamplan" in updated["trial_available_plans"]


def test_trial_detection_handles_query_exception(monkeypatch):
    monkeypatch.setattr("autotoken.storage.accounts.update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "autotoken.api_routes.account_overview.query_chatgpt_subscription",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    result = _detect_registration_trial_eligibility("user@example.com", "tok", "acct_1")

    assert result["trial_eligible"] is False
