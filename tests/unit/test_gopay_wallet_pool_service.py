import pytest

from autotoken import api
from autotoken.services import gopay_wallet_pool


@pytest.fixture(autouse=True)
def _clear_wallet_pool():
    with gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL_LOCK:
        gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL.clear()
    yield
    with gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL_LOCK:
        gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL.clear()


class WalletFromAccount:
    def __init__(self, phone_number="87761973970", bridge_token="", sms_url=""):
        self.closed = []
        self._account = {
            "country_code": "+62",
            "phone_number": phone_number,
            "sms_url": sms_url or "http://127.0.0.1:8787/otp/gopay-signup/from-url",
            "gopay_pin": "558023",
            "otp_channel": "sms",
        }
        if bridge_token:
            self._account["bridgeToken"] = bridge_token

    def as_phone_account(self):
        return dict(self._account)

    def close(self, *, success=True):
        self.closed.append(success)


def test_wallet_accessors_prefer_attributes_then_phone_account_fields():
    class WalletWithAttributes:
        phone_number = "attr-phone"
        bridge_token = "attr-token"

        def as_phone_account(self):
            return {
                "phone_number": "account-phone",
                "bridge_token": "account-token",
            }

    assert gopay_wallet_pool.wallet_phone(WalletWithAttributes()) == "attr-phone"
    assert gopay_wallet_pool.wallet_bridge_token(WalletWithAttributes()) == "attr-token"

    wallet = WalletFromAccount(phone_number="account-phone", bridge_token="account-token")
    assert gopay_wallet_pool.wallet_phone(wallet) == "account-phone"
    assert gopay_wallet_pool.wallet_bridge_token(wallet) == "account-token"


def test_wallet_bridge_token_falls_back_to_signup_sms_url_token():
    wallet = WalletFromAccount(sms_url="http://127.0.0.1:8787/otp/gopay-signup/url-token?x=1")

    assert gopay_wallet_pool.wallet_bridge_token(wallet) == "url-token"
    assert gopay_wallet_pool.wallet_account(wallet)["bridge_token"] == "url-token"


def test_push_reusable_wallet_normalizes_entry_and_replaces_duplicates(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_WALLET_POOL_TTL_SECONDS", "120")
    monkeypatch.setattr(gopay_wallet_pool.time, "time", lambda: 1000.0)
    wallet = WalletFromAccount(phone_number="87761973970", bridge_token="bridge-a")

    first = gopay_wallet_pool.push_reusable_wallet(wallet, task_id="task-a", run_id="run-a", funded=True)
    second = gopay_wallet_pool.push_reusable_wallet(wallet, task_id="task-b", run_id="run-b", funded=False)

    assert first is not None
    assert second == {
        "wallet": wallet,
        "phone_number": "87761973970",
        "country_code": "62",
        "gopay_pin": "558023",
        "sms_url": "http://127.0.0.1:8787/otp/gopay-signup/from-url",
        "bridge_token": "bridge-a",
        "created_at": 1000.0,
        "expires_at": 1120.0,
        "funded": False,
        "task_id": "task-b",
        "run_id": "run-b",
    }
    assert gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL == [second]


def test_pop_reusable_wallet_filters_pin_and_country(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_WALLET_POOL_TTL_SECONDS", "120")
    monkeypatch.setattr(gopay_wallet_pool.time, "time", lambda: 1000.0)
    wallet_a = WalletFromAccount(phone_number="phone-a")
    wallet_b = WalletFromAccount(phone_number="phone-b")
    wallet_b._account["country_code"] = "+63"

    entry_a = gopay_wallet_pool.push_reusable_wallet(wallet_a)
    entry_b = gopay_wallet_pool.push_reusable_wallet(wallet_b)

    assert gopay_wallet_pool.pop_reusable_wallet(gopay_pin="bad", country_code="62") is None
    assert gopay_wallet_pool.pop_reusable_wallet(gopay_pin="558023", country_code="+63") == entry_b
    assert gopay_wallet_pool.pop_reusable_wallet(gopay_pin="", country_code="62") == entry_a
    assert gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL == []


def test_prune_reusable_wallet_pool_closes_expired_wallets():
    expired_wallet = WalletFromAccount(phone_number="expired")
    kept_wallet = WalletFromAccount(phone_number="kept")
    gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL[:] = [
        {"wallet": expired_wallet, "expires_at": 10},
        {"wallet": kept_wallet, "expires_at": 30},
    ]

    gopay_wallet_pool.prune_reusable_wallet_pool(now=20)

    assert expired_wallet.closed == [False]
    assert kept_wallet.closed == []
    assert gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL == [{"wallet": kept_wallet, "expires_at": 30}]


def test_api_wallet_pool_wrappers_share_service_state(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_WALLET_POOL_TTL_SECONDS", "120")
    monkeypatch.setattr(gopay_wallet_pool.time, "time", lambda: 1000.0)
    wallet = WalletFromAccount(phone_number="api-phone")

    entry = api._push_gopay_reusable_wallet(wallet, task_id="api-task")

    assert api._GOPAY_REUSABLE_WALLET_POOL is gopay_wallet_pool.GOPAY_REUSABLE_WALLET_POOL
    assert api._GOPAY_REUSABLE_WALLET_POOL == [entry]
    assert api._gopay_wallet_phone(wallet) == "api-phone"
    assert api._pop_gopay_reusable_wallet(gopay_pin="558023", country_code="62") == entry
