import pytest

from autotoken.api_routes import config_io
from autotoken.api_routes.config_io import ConfigImportParams, create_config_io_router


class FakeEvent:
    def __init__(self) -> None:
        self.set_calls = 0

    def set(self) -> None:
        self.set_calls += 1


def _routes(
    *,
    auto_check_config=None,
    auto_refresh_quota_config=None,
    auto_check_restart=None,
    auto_refresh_quota_restart=None,
    save_auto_refresh_quota_config=None,
    state=None,
):
    state = state if state is not None else {"api_key": ""}
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_config_io_router(
            auto_check_config=auto_check_config if auto_check_config is not None else {},
            auto_check_restart=auto_check_restart or FakeEvent(),
            auto_refresh_quota_config=(
                auto_refresh_quota_config if auto_refresh_quota_config is not None else {}
            ),
            auto_refresh_quota_restart=auto_refresh_quota_restart or FakeEvent(),
            save_auto_refresh_quota_config=save_auto_refresh_quota_config or (lambda: None),
            get_api_key=lambda: state.get("api_key", ""),
            set_api_key=lambda value: state.update({"api_key": value}),
            current_time=lambda: 123.0,
        ).routes
    }


def test_export_config_includes_runtime_sections(monkeypatch):
    auto_check = {"enabled": True, "interval": 300, "threshold": 10, "min_low": 1}
    auto_refresh = {"enabled": False, "interval": 0}

    monkeypatch.setattr(config_io, "_env_config_keys", lambda: ["API_KEY", "CPA_URL"])
    monkeypatch.setattr("autotoken.setup_wizard._read_env", lambda: {"API_KEY": "token", "CPA_URL": "http://cpa"})
    monkeypatch.setattr("autotoken.runtime_config.get_register_domain", lambda: "mail.example.com")
    monkeypatch.setattr("autotoken.runtime_config.get_register_domains", lambda: ["mail.example.com"])
    monkeypatch.setattr("autotoken.account_hub.get_config", lambda: {"enabled": True})

    result = _routes(auto_check_config=auto_check, auto_refresh_quota_config=auto_refresh)["export_config_api"]()

    assert result["exported_at"] == 123.0
    assert result["env"] == {"API_KEY": "token", "CPA_URL": "http://cpa"}
    assert result["runtime"]["register_domains"] == ["mail.example.com"]
    assert result["account_hub"] == {"enabled": True}
    assert result["auto_check"] == auto_check
    assert result["auto_refresh_quota"] == auto_refresh


def test_import_config_updates_env_runtime_sections_and_runtime_api_key(monkeypatch):
    state = {"api_key": "old-token"}
    written_env = {}
    runtime_updates = {}
    saved = {"count": 0}
    auto_check_restart = FakeEvent()
    auto_refresh_restart = FakeEvent()
    auto_check = {"enabled": True, "interval": 300, "threshold": 10, "min_low": 1}
    auto_refresh = {"enabled": False, "interval": 0}

    monkeypatch.setattr(config_io, "_env_config_keys", lambda: ["API_KEY", "CPA_URL", "EMPTY"])
    monkeypatch.setattr(config_io, "_reload_env_backed_modules", lambda: None)
    monkeypatch.setattr("autotoken.setup_wizard._write_env", lambda key, value: written_env.update({key: value}))
    monkeypatch.setattr(
        "autotoken.runtime_config.set_register_domain",
        lambda value: runtime_updates.update({"register_domain": value}),
    )
    monkeypatch.setattr(
        "autotoken.runtime_config.set_register_domains",
        lambda values: runtime_updates.update({"register_domains": values}),
    )
    monkeypatch.setattr(
        "autotoken.account_hub.set_config",
        lambda value: runtime_updates.update({"account_hub": value}),
    )
    monkeypatch.delenv("API_KEY", raising=False)

    def fake_save_auto_refresh() -> None:
        saved["count"] += 1

    result = _routes(
        auto_check_config=auto_check,
        auto_refresh_quota_config=auto_refresh,
        auto_check_restart=auto_check_restart,
        auto_refresh_quota_restart=auto_refresh_restart,
        save_auto_refresh_quota_config=fake_save_auto_refresh,
        state=state,
    )["import_config_api"](
        ConfigImportParams(
            config={
                "env": {"API_KEY": "new-token", "CPA_URL": "http://cpa", "UNKNOWN": "skip", "EMPTY": ""},
                "runtime": {"register_domain": "mail-a.com", "register_domains": ["mail-a.com", "mail-b.com"]},
                "account_hub": {"enabled": True},
                "auto_check": {"enabled": False, "interval": 10, "threshold": 200, "min_low": 0},
                "auto_refresh_quota": {"enabled": True, "interval": 30},
            },
            overwrite_empty=False,
        )
    )

    assert written_env == {"API_KEY": "new-token", "CPA_URL": "http://cpa"}
    assert result["updated_env"] == ["API_KEY", "CPA_URL"]
    assert result["skipped_env"] == ["UNKNOWN", "EMPTY"]
    assert result["updated_runtime"] == ["register_domains", "register_domain"]
    assert set(result["updated_sections"]) == {"account_hub", "auto_check", "auto_refresh_quota"}
    assert runtime_updates["register_domain"] == "mail-a.com"
    assert runtime_updates["register_domains"] == ["mail-a.com", "mail-b.com"]
    assert runtime_updates["account_hub"] == {"enabled": True}
    assert auto_check == {"enabled": False, "interval": 60, "threshold": 100, "min_low": 1}
    assert auto_refresh == {"enabled": True, "interval": 60}
    assert auto_check_restart.set_calls == 1
    assert auto_refresh_restart.set_calls == 1
    assert saved["count"] == 1
    assert state["api_key"] == "new-token"


def test_import_config_rejects_oversized_pasted_json():
    oversized = " " * (config_io.CONFIG_IMPORT_MAX_BYTES + 1)

    with pytest.raises(Exception) as exc:
        _routes()["import_config_api"](ConfigImportParams(content=oversized))

    assert "配置导入内容过大" in str(exc.value)
