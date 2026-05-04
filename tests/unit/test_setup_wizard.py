import logging

from autoteam import setup_wizard


def test_write_env_uses_example_template_when_env_file_is_missing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "CLOUDFLARE_TEMP_EMAIL_BASE_URL=\nCLOUDMAIL_EMAIL=\nAPI_KEY=\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(setup_wizard, "ENV_FILE", env_file)
    monkeypatch.setattr(setup_wizard, "ENV_EXAMPLE", env_example)

    setup_wizard._write_env("CLOUDMAIL_EMAIL", "admin@example.com")

    content = env_file.read_text(encoding="utf-8")
    assert "CLOUDMAIL_EMAIL=admin@example.com" in content
    assert "API_KEY=" in content


def test_check_and_setup_non_interactive_returns_true_when_required_values_exist(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MAIL_PROVIDER=cloudflare_temp_email",
                "CLOUDFLARE_TEMP_EMAIL_BASE_URL=http://mail.example.com",
                "CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD=secret",
                "CLOUDFLARE_TEMP_EMAIL_DOMAIN=@example.com",
                "CPA_URL=http://127.0.0.1:8317",
                "CPA_KEY=key-1",
                "API_KEY=generated-token",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(setup_wizard, "ENV_FILE", env_file)
    monkeypatch.setattr(setup_wizard, "ENV_EXAMPLE", tmp_path / ".env.example")
    monkeypatch.setattr(setup_wizard, "_is_interactive", lambda: False)
    monkeypatch.setattr(setup_wizard, "_verify_temporary_email", lambda: True)
    monkeypatch.setattr(setup_wizard, "_verify_cpa", lambda: True)
    for key in (
        "MAIL_PROVIDER",
        "CLOUDFLARE_TEMP_EMAIL_BASE_URL",
        "CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD",
        "CLOUDFLARE_TEMP_EMAIL_DOMAIN",
        "CPA_URL",
        "CPA_KEY",
        "API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    assert setup_wizard.check_and_setup(interactive=False) is True


def test_check_and_setup_non_interactive_reports_missing_required_fields(tmp_path, monkeypatch, caplog):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(setup_wizard, "ENV_FILE", env_file)
    monkeypatch.setattr(setup_wizard, "ENV_EXAMPLE", tmp_path / ".env.example")
    monkeypatch.setattr(setup_wizard, "_is_interactive", lambda: False)
    for key in (
        "MAIL_PROVIDER",
        "CLOUDFLARE_TEMP_EMAIL_BASE_URL",
        "CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD",
        "CLOUDFLARE_TEMP_EMAIL_DOMAIN",
        "CLOUD_MAIL_API_URL",
        "CLOUD_MAIL_ADMIN_EMAIL",
        "CLOUD_MAIL_ADMIN_PASSWORD",
        "CLOUD_MAIL_DOMAIN",
        "CPA_URL",
        "CPA_KEY",
        "API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    with caplog.at_level(logging.WARNING):
        ok = setup_wizard.check_and_setup(interactive=False)

    assert ok is False
    assert "[配置] 缺少必填项: CLOUDFLARE_TEMP_EMAIL_BASE_URL" in caplog.text
    assert "[配置] 缺少必填项: CPA_KEY" not in caplog.text
    assert "[配置] 缺少必填项: CPA_URL" not in caplog.text
    assert "[配置] 缺少必填项: PLAYWRIGHT_PROXY_URL" not in caplog.text
    assert "[配置] 缺少必填项: PLAYWRIGHT_PROXY_BYPASS" not in caplog.text
    assert "[配置] 缺少必填项: API_KEY" in caplog.text
    assert "[配置] 请通过 Web 面板或编辑 .env 文件填入配置" in caplog.text


def test_get_setup_schema_returns_provider_specific_groups(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MAIL_PROVIDER=cloud-mail\n", encoding="utf-8")

    monkeypatch.setattr(setup_wizard, "ENV_FILE", env_file)

    schema = setup_wizard.get_setup_schema()

    assert schema["provider"] == "cloud-mail"
    assert any(field["key"] == "CLOUD_MAIL_API_URL" for field in schema["provider_fields"]["cloud-mail"])
    assert any(
        field["key"] == "CLOUDFLARE_TEMP_EMAIL_BASE_URL"
        for field in schema["provider_fields"]["cloudflare_temp_email"]
    )
