import pytest

from autotoken.rekberinaja import (
    RekberinajaClient,
    RekberinajaConfig,
    RekberinajaError,
    format_gopay_phone_for_rekberinaja,
)


def test_format_gopay_phone_for_rekberinaja_normalizes_indonesia_numbers():
    assert format_gopay_phone_for_rekberinaja("+62 877 1234 5678") == "087712345678"
    assert format_gopay_phone_for_rekberinaja("6287712345678") == "087712345678"
    assert format_gopay_phone_for_rekberinaja("87712345678") == "087712345678"
    assert format_gopay_phone_for_rekberinaja("087712345678") == "087712345678"


def test_rekberinaja_client_saldo_topup_flow(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if url.endswith("/auth/login"):
                return FakeResponse({"status": True, "data": {"access_token": "token-1", "user": {"email": "u@example.com"}}})
            if url.endswith("/user/balance"):
                return FakeResponse({"status": True, "data": {"balance": 10000}})
            if url.endswith("/transaction/product/checkout"):
                assert kwargs["json"]["data"] == "087712345678"
                assert kwargs["json"]["payment_method"] == "saldo"
                return FakeResponse({"status": True, "data": {"transaction_id": "trx-1"}})
            if url.endswith("/transaction/trx-1/pay"):
                return FakeResponse({"status": True, "data": {"invoice_url": "https://rekberinaja.com/transaction/trx-1"}})
            raise AssertionError(f"unexpected request: {method} {url}")

    config = RekberinajaConfig(
        enabled=True,
        email="u@example.com",
        password="secret",
        min_balance=5000,
        poll_interval=1,
        poll_timeout=10,
    )
    client = RekberinajaClient(config, session=FakeSession())

    result = client.top_up_gopay("+62 877 1234 5678")

    assert result["transaction_id"] == "trx-1"
    assert result["status"] == "submitted"
    assert client.session.headers["Authorization"] == "Bearer token-1"


def test_rekberinaja_client_rejects_low_balance(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def request(self, method, url, **kwargs):
            if url.endswith("/auth/login"):
                return FakeResponse({"status": True, "data": {"access_token": "token-1"}})
            if url.endswith("/user/balance"):
                return FakeResponse({"status": True, "data": {"balance": 999}})
            raise AssertionError("should stop before creating order")

    client = RekberinajaClient(
        RekberinajaConfig(enabled=True, email="u@example.com", password="secret", min_balance=5000),
        session=FakeSession(),
    )

    with pytest.raises(RekberinajaError, match="余额不足"):
        client.top_up_gopay("87712345678")


def test_rekberinaja_failed_order_poll_includes_transaction_context(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    progress = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def request(self, method, url, **kwargs):
            if url.endswith("/auth/login"):
                return FakeResponse({"status": True, "data": {"access_token": "token-1"}})
            if url.endswith("/user/balance"):
                return FakeResponse({"status": True, "data": {"balance": 10000}})
            if url.endswith("/transaction/product/checkout"):
                return FakeResponse({"status": True, "data": {"transaction_id": "trx-1"}})
            if url.endswith("/transaction/trx-1/pay"):
                return FakeResponse({"status": True, "data": {}})
            if url.endswith("/transaction/trx-1/order-product"):
                return FakeResponse(
                    {
                        "status": True,
                        "data": {
                            "status": "fail",
                            "message": "订单失败",
                            "trx_id": "order-1",
                        },
                    }
                )
            raise AssertionError(f"unexpected request: {method} {url}")

    client = RekberinajaClient(
        RekberinajaConfig(enabled=True, email="u@example.com", password="secret", min_balance=5000),
        session=FakeSession(),
        progress=lambda stage, payload: progress.append({"stage": stage, **payload}),
    )

    client.login()
    client.create_gopay_order("87712345678")
    client.pay_with_saldo("trx-1")
    with pytest.raises(RekberinajaError) as exc:
        client.wait_order_completed("trx-1")

    assert exc.value.transaction_id == "trx-1"
    assert exc.value.status == "fail"
    assert exc.value.debited_possible is True
    assert "transaction_id=trx-1" in str(exc.value)
    assert any(item["stage"] == "rekberinaja_order_failed" for item in progress)
