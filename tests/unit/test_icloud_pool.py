from autotoken.mail.icloud import ICloudMailProvider
from autotoken.storage import icloud_pool


def test_mark_unavailable_email_persists_in_pool_state(tmp_path, monkeypatch):
    monkeypatch.setattr(icloud_pool, "STATE_FILE", tmp_path / "icloud_pool.json")

    assert icloud_pool.mark_unavailable_email("Dead@icloud.com", source="account_deactivated")

    assert icloud_pool.list_unavailable_emails() == {"dead@icloud.com"}


def test_icloud_provider_skips_pool_unavailable_email(tmp_path, monkeypatch):
    accounts_file = tmp_path / "icloud_accounts.txt"
    accounts_file.write_text(
        "\n".join(
            [
                "dead@icloud.com----https://icloud-api.top/show/token/dead@icloud.com",
                "fresh@icloud.com----https://icloud-api.top/show/token/fresh@icloud.com",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ICLOUD_ACCOUNTS_FILE", str(accounts_file))
    monkeypatch.setattr(icloud_pool, "STATE_FILE", tmp_path / "icloud_pool.json")
    monkeypatch.setattr("autotoken.storage.accounts.load_accounts", lambda: [])

    icloud_pool.mark_unavailable_email("dead@icloud.com", source="account_deactivated")

    provider = ICloudMailProvider()

    assert provider.create_temp_email() == ("fresh@icloud.com", "fresh@icloud.com")
