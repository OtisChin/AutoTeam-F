import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from standalone.oauth_relogin.__main__ import main


def test_cli_config_prints_safe_provider_report(monkeypatch, capsys):
    monkeypatch.setenv("OAUTH_RELOGIN_PHONE_SMS_PROVIDER", "hero_sms")
    monkeypatch.setenv("OAUTH_RELOGIN_HERO_SMS_API_KEY", "hero-secret-key")

    assert main(["config"]) == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["provider"] == "hero_sms"
    assert data["configured"] is True
    assert "hero-secret-key" not in out


def test_cli_import_phones_writes_json_pool(tmp_path, capsys):
    pool_file = tmp_path / "pool.json"

    assert main(["import-phones", "--phone-pool", str(pool_file), "--text", "+12025550117----https://sms.example/17"]) == 0

    out = capsys.readouterr().out
    assert json.loads(out)["added_count"] == 1
    assert json.loads(pool_file.read_text(encoding="utf-8"))["items"][0]["phone_number"] == "+12025550117"
