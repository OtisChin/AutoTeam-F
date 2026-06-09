import sys
from types import ModuleType

from autotoken import cli, manager


def test_build_parser_keeps_existing_command_surface():
    parser = cli.build_parser()
    help_text = parser.format_help()

    assert help_text.startswith("usage: autotoken ")
    assert "manager.py" not in help_text

    for command in (
        "status",
        "check",
        "rotate",
        "add",
        "manual-add",
        "admin-login",
        "admin-session",
        "main-codex-sync",
        "fill",
        "cleanup",
        "sync",
        "pull-cpa",
        "reconcile",
        "api",
    ):
        assert command in help_text


def test_cli_main_dispatches_check_after_startup_checks(monkeypatch):
    calls = []

    setup_wizard = ModuleType("autotoken.settings.setup_wizard")
    setup_wizard.check_and_setup = lambda interactive: calls.append(("setup", interactive))
    auth_storage = ModuleType("autotoken.storage.auth_storage")
    auth_storage.ensure_auth_file_permissions = lambda: calls.append(("permissions",))

    monkeypatch.setitem(sys.modules, "autotoken.settings.setup_wizard", setup_wizard)
    monkeypatch.setitem(sys.modules, "autotoken.storage.auth_storage", auth_storage)
    monkeypatch.setattr(
        manager,
        "cmd_check",
        lambda include_standby=False: calls.append(("check", include_standby)) or {"ok": True},
    )

    assert cli.main(["check", "--include-standby"]) == {"ok": True}
    assert calls == [("setup", True), ("permissions",), ("check", True)]


def test_cli_main_api_skips_setup_and_starts_server(monkeypatch):
    calls = []

    setup_wizard = ModuleType("autotoken.settings.setup_wizard")
    setup_wizard.check_and_setup = lambda interactive: calls.append(("setup", interactive))
    auth_storage = ModuleType("autotoken.storage.auth_storage")
    auth_storage.ensure_auth_file_permissions = lambda: calls.append(("permissions",))
    api_module = ModuleType("autotoken.interfaces.api")
    api_module.start_server = lambda host, port: calls.append(("api", host, port)) or "started"

    monkeypatch.setitem(sys.modules, "autotoken.settings.setup_wizard", setup_wizard)
    monkeypatch.setitem(sys.modules, "autotoken.storage.auth_storage", auth_storage)
    monkeypatch.setitem(sys.modules, "autotoken.interfaces.api", api_module)

    assert cli.main(["api", "--host", "127.0.0.1", "--port", "9999"]) == "started"
    assert calls == [("permissions",), ("api", "127.0.0.1", 9999)]


def test_manager_main_delegates_to_cli(monkeypatch):
    calls = []

    monkeypatch.setattr(cli, "main", lambda argv=None: calls.append(argv) or "delegated")

    assert manager.main(["status"]) == "delegated"
    assert calls == [["status"]]
