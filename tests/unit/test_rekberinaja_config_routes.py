import anyio

from autotoken.api_routes.rekberinaja_config import create_rekberinaja_config_router


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _routes():
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_rekberinaja_config_router(mask_secret=lambda value: f"masked:{value}").routes
    }


def test_get_rekberinaja_config_uses_env_and_masks_password(monkeypatch):
    monkeypatch.setattr(
        "autotoken.setup_wizard._read_env",
        lambda: {
            "REKBERINAJA_TRANSFER_ENABLED": "1",
            "REKBERINAJA_EMAIL": "user@example.com",
            "REKBERINAJA_PASSWORD": "secret",
            "REKBERINAJA_MIN_BALANCE": "7000",
            "REKBERINAJA_POLL_TIMEOUT": "120",
            "REKBERINAJA_INVOICE_EMAIL": "invoice@example.com",
        },
    )

    result = _routes()["get_rekberinaja_config"]()

    assert result["enabled"] is True
    assert result["transfer_enabled"] is True
    assert result["email"] == "user@example.com"
    assert result["password_present"] is True
    assert result["password_masked"] == "masked:secret"
    assert result["credentials_configured"] is True
    assert result["configured"] is True
    assert result["min_balance"] == "7000"
    assert result["poll_timeout"] == "120"
    assert result["invoice_email"] == "invoice@example.com"


def test_save_rekberinaja_config_writes_enabled_transfer_settings(monkeypatch):
    written = {}
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {})
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_rekberinaja_config"],
        FakeRequest(
            {
                "transfer_enabled": True,
                "email": "user@example.com",
                "password": "secret",
                "min_balance": "8000",
                "poll_timeout": "90",
                "invoice_email": "invoice@example.com",
                "base_url": "https://rek.example/api",
                "store": "store-1",
                "gopay_product_id": "product-1",
                "gopay_service_id": "service-1",
            }
        ),
    )

    assert written == {
        "REKBERINAJA_ENABLED": "1",
        "REKBERINAJA_TRANSFER_ENABLED": "1",
        "REKBERINAJA_MIN_BALANCE": "8000",
        "REKBERINAJA_POLL_TIMEOUT": "90",
        "REKBERINAJA_BASE_URL": "https://rek.example/api",
        "REKBERINAJA_STORE": "store-1",
        "REKBERINAJA_GOPAY_PRODUCT_ID": "product-1",
        "REKBERINAJA_GOPAY_SERVICE_ID": "service-1",
        "REKBERINAJA_INVOICE_EMAIL": "invoice@example.com",
        "REKBERINAJA_EMAIL": "user@example.com",
        "REKBERINAJA_PASSWORD": "secret",
    }
    assert result["message"] == "Rekberinaja 配置已保存"
    assert result["enabled"] is True
    assert result["configured"] is True


def test_save_rekberinaja_config_preserves_existing_secret_when_blank(monkeypatch):
    written = {}
    monkeypatch.setenv("REKBERINAJA_PASSWORD", "existing-secret")
    monkeypatch.setattr(
        "autotoken.setup_wizard._read_env",
        lambda: {
            "REKBERINAJA_TRANSFER_ENABLED": "0",
            "REKBERINAJA_EMAIL": "existing@example.com",
            "REKBERINAJA_PASSWORD": "existing-secret",
        },
    )
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written.update({key: value}))

    result = anyio.run(
        _routes()["save_rekberinaja_config"],
        FakeRequest({"transfer_enabled": False, "email": "", "password": ""}),
    )

    assert "REKBERINAJA_EMAIL" not in written
    assert "REKBERINAJA_PASSWORD" not in written
    assert result["enabled"] is False
    assert result["password_present"] is True
