from autotoken.api_routes.finished_account_import import (
    FinishedAccountImportParams,
    create_finished_account_import_router,
)


def _routes(**kwargs):
    return {
        route.endpoint.__name__: route.endpoint
        for route in create_finished_account_import_router(**kwargs).routes
    }


def test_finished_account_import_route_reads_local_paths(tmp_path):
    accounts_file = tmp_path / "accounts.json"
    mailboxes_file = tmp_path / "mailboxes.txt"
    accounts_file.write_text('{"email":"user@example.com","access_token":"token"}', encoding="utf-8")
    mailboxes_file.write_text("user@example.com----mail-password\n", encoding="utf-8")
    captured = {}

    def fake_import(accounts_content, mailboxes_content, *, accounts_source_name, mailboxes_source_name):
        captured.update(
            {
                "accounts_content": accounts_content,
                "mailboxes_content": mailboxes_content,
                "accounts_source_name": accounts_source_name,
                "mailboxes_source_name": mailboxes_source_name,
            }
        )
        return {"imported": 1, "synthetic": True}

    result = _routes(import_finished_accounts_from_text=fake_import)["import_finished_accounts"](
        FinishedAccountImportParams(
            accounts_path=str(accounts_file),
            mailboxes_path=str(mailboxes_file),
        )
    )

    assert result == {"imported": 1, "synthetic": True}
    assert captured["accounts_content"] == '{"email":"user@example.com","access_token":"token"}'
    assert captured["mailboxes_content"] == "user@example.com----mail-password\n"
    assert captured["accounts_source_name"] == str(accounts_file)
    assert captured["mailboxes_source_name"] == str(mailboxes_file)


def test_finished_account_import_route_accepts_uploaded_content_with_filenames():
    captured = {}

    def fake_import(accounts_content, mailboxes_content, *, accounts_source_name, mailboxes_source_name):
        captured.update(
            {
                "accounts_content": accounts_content,
                "mailboxes_content": mailboxes_content,
                "accounts_source_name": accounts_source_name,
                "mailboxes_source_name": mailboxes_source_name,
            }
        )
        return {"imported": 1, "synthetic": True}

    result = _routes(import_finished_accounts_from_text=fake_import)["import_finished_accounts"](
        FinishedAccountImportParams(
            accounts_content='{"email":"user@example.com","access_token":"token"}',
            accounts_filename="accounts-upload.json",
            mailboxes_content="user@example.com----mail-password\n",
            mailboxes_filename="mailboxes-upload.txt",
        )
    )

    assert result == {"imported": 1, "synthetic": True}
    assert captured["accounts_content"] == '{"email":"user@example.com","access_token":"token"}'
    assert captured["mailboxes_content"] == "user@example.com----mail-password\n"
    assert captured["accounts_source_name"] == "accounts-upload.json"
    assert captured["mailboxes_source_name"] == "mailboxes-upload.txt"


def test_finished_account_import_route_rejects_missing_accounts_file(tmp_path):
    routes = _routes(import_finished_accounts_from_text=lambda *_args, **_kwargs: {})

    try:
        routes["import_finished_accounts"](FinishedAccountImportParams(accounts_path=str(tmp_path / "missing.json")))
    except Exception as exc:
        assert "账号文件不存在" in str(exc)
    else:
        raise AssertionError("expected missing file error")
