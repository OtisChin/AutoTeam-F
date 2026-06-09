import base64
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from autotoken import accounts, cpa_sync, sub2api_converter
from autotoken.api_routes.account_cpa_auths import (
    AccountCpaAuthImportParams,
    AccountCpaAuthImportSource,
    AccountEmailBatchParams,
    AccountSessionCpaConvertParams,
    create_account_cpa_auths_router,
)
from autotoken.session_cpa_converter import SessionConversionError


@pytest.fixture(autouse=True)
def _auth_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("autotoken.storage.auth_storage.AUTH_DIR", tmp_path)
    return tmp_path


def _app(**router_kwargs):
    app = FastAPI()
    app.include_router(create_account_cpa_auths_router(**router_kwargs))
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_account_cpa_auth_import_rejects_empty_payload():
    app = _app()

    with _raises_http(400, "请粘贴 CPA JSON，或选择 JSON/ZIP 文件"):
        _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(AccountCpaAuthImportParams())


def test_account_cpa_auth_import_reports_parse_errors_when_nothing_valid(monkeypatch):
    app = _app()

    monkeypatch.setattr(cpa_sync, "import_local_cpa_auth_sources", lambda _sources: {"files": [], "invalid": []})

    with _raises_http(400, {"message": "未导入任何有效 CPA 认证文件", "invalid": [{"filename": "pasted.json", "error": "JSON 解析失败: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"}]}):
        _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(AccountCpaAuthImportParams(pasted_text="{"))


def test_account_cpa_auth_import_accepts_data_url_base64(monkeypatch):
    app = _app()
    captured = {}
    payload = {"codex_auth": {"email": "user@example.com", "access_token": "token"}}
    raw = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

    def fake_import(sources):
        captured["sources"] = sources
        return {"files": [{"email": "user@example.com"}], "invalid": []}

    monkeypatch.setattr(cpa_sync, "import_local_cpa_auth_sources", fake_import)

    result = _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(
        AccountCpaAuthImportParams(
            files=[
                AccountCpaAuthImportSource(
                    filename="auth.json",
                    content_base64=f"data:application/json;base64,{raw}",
                )
            ]
        )
    )

    assert result["files"] == [{"email": "user@example.com"}]
    assert captured["sources"] == [{"name": "auth.json", "auth_data": payload["codex_auth"]}]


def test_account_cpa_auth_import_rejects_oversized_base64_before_decode(monkeypatch):
    app = _app()
    monkeypatch.setattr("autotoken.api_routes.account_cpa_auths.MAX_CPA_IMPORT_BASE64_CHARS", 8)
    monkeypatch.setattr(cpa_sync, "import_local_cpa_auth_sources", lambda _sources: {"files": [], "invalid": []})

    with _raises_http(
        400,
        {
            "message": "未导入任何有效 CPA 认证文件",
            "invalid": [{"filename": "auth.json", "error": "内容解码失败: base64 内容过大"}],
        },
    ):
        _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(
            AccountCpaAuthImportParams(
                files=[
                    AccountCpaAuthImportSource(
                        filename="auth.json",
                        content_base64=base64.b64encode(b'{"auth_data":{"email":"user@example.com"}}').decode("ascii"),
                    )
                ]
            )
        )


def test_account_cpa_auth_import_rejects_invalid_base64(monkeypatch):
    app = _app()
    monkeypatch.setattr(cpa_sync, "import_local_cpa_auth_sources", lambda _sources: {"files": [], "invalid": []})

    with _raises_http(
        400,
        {
            "message": "未导入任何有效 CPA 认证文件",
            "invalid": [{"filename": "auth.json", "error": "内容解码失败: base64 内容无效"}],
        },
    ):
        _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(
            AccountCpaAuthImportParams(
                files=[AccountCpaAuthImportSource(filename="auth.json", content_base64="not valid base64")]
            )
        )


def test_account_cpa_auth_import_collects_nested_zip_auth_items(monkeypatch):
    app = _app()
    captured = {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "bundle.json",
            json.dumps(
                {
                    "auths": [
                        {"filename": "first.json", "data": {"email": "first@example.com"}},
                        {"filename": "second.json", "data": json.dumps({"auth_data": {"email": "second@example.com"}})},
                    ]
                }
            ),
        )
        archive.writestr("broken.json", "{")

    def fake_import(sources):
        captured["sources"] = sources
        return {"files": [{"email": item["auth_data"]["email"]} for item in sources], "invalid": []}

    monkeypatch.setattr(cpa_sync, "import_local_cpa_auth_sources", fake_import)

    result = _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(
        AccountCpaAuthImportParams(
            files=[
                AccountCpaAuthImportSource(
                    filename="auths.zip",
                    content_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                )
            ]
        )
    )

    assert captured["sources"] == [
        {"name": "first.json", "auth_data": {"email": "first@example.com"}},
        {"name": "second.json", "auth_data": {"email": "second@example.com"}},
    ]
    assert result["files"] == [{"email": "first@example.com"}, {"email": "second@example.com"}]
    assert result["invalid"][0]["filename"] == "broken.json"


def test_account_cpa_auth_import_rejects_oversized_json_file(monkeypatch):
    app = _app()
    monkeypatch.setattr(
        "autotoken.api_routes.account_cpa_auths.MAX_CPA_IMPORT_JSON_BYTES",
        8,
    )
    monkeypatch.setattr(cpa_sync, "import_local_cpa_auth_sources", lambda _sources: {"files": [], "invalid": []})

    with _raises_http(
        400,
        {
            "message": "未导入任何有效 CPA 认证文件",
            "invalid": [{"filename": "auth.json", "error": "文件超过 5MB，已跳过"}],
        },
    ):
        _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(
            AccountCpaAuthImportParams(files=[AccountCpaAuthImportSource(filename="auth.json", content='{"ok": true}')])
        )


def test_account_cpa_auth_import_stops_after_zip_json_entry_limit(monkeypatch):
    app = _app()
    captured = {}
    monkeypatch.setattr(
        "autotoken.api_routes.account_cpa_auths.MAX_CPA_IMPORT_ZIP_JSON_FILES",
        1,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("first.json", json.dumps({"auth_data": {"email": "first@example.com"}}))
        archive.writestr("second.json", json.dumps({"auth_data": {"email": "second@example.com"}}))

    def fake_import(sources):
        captured["sources"] = sources
        return {"files": [{"email": item["auth_data"]["email"]} for item in sources], "invalid": []}

    monkeypatch.setattr(cpa_sync, "import_local_cpa_auth_sources", fake_import)

    result = _endpoint(app, "/api/accounts/import-cpa-auths", "POST")(
        AccountCpaAuthImportParams(
            files=[
                AccountCpaAuthImportSource(
                    filename="auths.zip",
                    content_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                )
            ]
        )
    )

    assert captured["sources"] == [{"name": "first.json", "auth_data": {"email": "first@example.com"}}]
    assert result["files"] == [{"email": "first@example.com"}]
    assert result["invalid"] == [{"filename": "auths.zip", "error": "ZIP 中 JSON 文件过多，已停止处理"}]


def test_account_cpa_auth_export_sub_reports_empty_and_missing(monkeypatch):
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        resolve_codex_auth_file=lambda _account: "",
        update_account_cpa_auth_plan_type=lambda *_args, **_kwargs: {},
    )

    with _raises_http(400, "emails 不能为空"):
        _endpoint(app, "/api/accounts/export-sub-auths", "POST")(AccountEmailBatchParams(emails=[]))

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    with _raises_http(404, "选中的账号没有可转换的 data/auths 认证文件"):
        _endpoint(app, "/api/accounts/export-sub-auths", "POST")(AccountEmailBatchParams(emails=["USER@example.com"]))


def test_account_cpa_auth_export_sub_converts_valid_auth_file(monkeypatch, tmp_path):
    auth_file = tmp_path / "codex-user@example.com-plus-deadbeef.json"
    auth_file.write_text(json.dumps({"email": "user@example.com", "access_token": "token"}), encoding="utf-8")
    captured = {"updates": []}
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        resolve_codex_auth_file=lambda _account: str(auth_file),
        update_account_cpa_auth_plan_type=lambda *_args, **_kwargs: {"auth_file": str(auth_file)},
        current_time=lambda: 1778888888.0,
    )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "account_type": "plus"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(accounts, "update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))
    monkeypatch.setattr(
        sub2api_converter,
        "inspect_sources",
        lambda sources: [
            SimpleNamespace(
                file_name=sources[0][0],
                is_valid=True,
                selected=True,
                error_message="",
                status_text="",
            )
        ],
    )
    monkeypatch.setattr(sub2api_converter, "generate_default_filename", lambda: "sub2api-import.json")
    monkeypatch.setattr(
        sub2api_converter,
        "export_records",
        lambda _records, _settings: {"accounts": [{"email": "user@example.com"}]},
    )

    result = _endpoint(app, "/api/accounts/export-sub-auths", "POST")(
        AccountEmailBatchParams(emails=["USER@example.com"])
    )

    assert result["filename"] == "sub2api-import.json"
    assert result["count"] == 1
    assert result["exported_emails"] == ["user@example.com"]
    assert result["exported_at"] == 1778888888.0
    assert captured["updates"] == [
        ("user@example.com", {"credentials_exported": True, "credentials_exported_at": 1778888888.0})
    ]
    decoded = json.loads(base64.b64decode(result["content_base64"]).decode("utf-8"))
    assert decoded == {"accounts": [{"email": "user@example.com"}]}


def test_account_cpa_auth_export_sub_ignores_auth_file_outside_auth_dir(monkeypatch, tmp_path):
    outside = tmp_path.parent / f"outside-sub-{tmp_path.name}.json"
    outside.write_text(json.dumps({"email": "user@example.com", "access_token": "token"}), encoding="utf-8")
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        resolve_codex_auth_file=lambda _account: str(outside),
        update_account_cpa_auth_plan_type=lambda *_args, **_kwargs: {"auth_file": str(outside)},
    )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com", "account_type": "free"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    with _raises_http(404, "选中的账号没有可转换的 data/auths 认证文件"):
        _endpoint(app, "/api/accounts/export-sub-auths", "POST")(AccountEmailBatchParams(emails=["user@example.com"]))


def test_account_cpa_auth_export_cpa_returns_single_auth_file(monkeypatch, tmp_path):
    auth_file = tmp_path / "codex-user@example.com-free-deadbeef.json"
    payload = {"email": "user@example.com", "access_token": "token"}
    auth_file.write_text(json.dumps(payload), encoding="utf-8")
    captured = {"updates": []}
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        resolve_codex_auth_file=lambda _account: str(auth_file),
        update_account_cpa_auth_plan_type=lambda *_args, **_kwargs: {"auth_file": str(auth_file)},
        verify_plus_plan=lambda _item: {"ok": True},
        normalize_observed_auth_plan=lambda *_args: None,
        mark_failed_account=lambda *_args, **_kwargs: None,
        current_time=lambda: 1778888888.0,
    )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)
    monkeypatch.setattr(accounts, "update_account", lambda email, **kwargs: captured["updates"].append((email, kwargs)))

    result = _endpoint(app, "/api/accounts/export-cpa-auths", "POST")(
        AccountEmailBatchParams(emails=["USER@example.com"])
    )

    assert result["filename"] == auth_file.name
    assert result["content_type"] == "application/json"
    assert result["count"] == 1
    assert result["exported_emails"] == ["user@example.com"]
    assert result["exported_at"] == 1778888888.0
    assert json.loads(base64.b64decode(result["content_base64"]).decode("utf-8")) == payload
    assert captured["updates"] == [
        ("user@example.com", {"credentials_exported": True, "credentials_exported_at": 1778888888.0})
    ]


def test_account_cpa_auth_export_cpa_ignores_auth_file_outside_auth_dir(monkeypatch, tmp_path):
    outside = tmp_path.parent / f"outside-cpa-{tmp_path.name}.json"
    outside.write_text(json.dumps({"email": "user@example.com", "access_token": "token"}), encoding="utf-8")
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        resolve_codex_auth_file=lambda _account: str(outside),
        update_account_cpa_auth_plan_type=lambda *_args, **_kwargs: {"auth_file": str(outside)},
        verify_plus_plan=lambda _item: {"ok": True},
        normalize_observed_auth_plan=lambda *_args: None,
        mark_failed_account=lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "user@example.com"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    with _raises_http(
        404,
        {
            "message": "选中的账号没有可导出的 data/auths 认证文件，或 Plus 状态未通过 OpenAI 实测",
            "missing": ["user@example.com"],
            "unconfirmed_plus": [],
        },
    ):
        _endpoint(app, "/api/accounts/export-cpa-auths", "POST")(AccountEmailBatchParams(emails=["user@example.com"]))


def test_account_cpa_auth_export_cpa_sanitizes_duplicate_zip_member_names(monkeypatch, tmp_path):
    auth_file = tmp_path / "codex-shared@example.com-free-deadbeef.json"
    auth_file.write_text(json.dumps({"email": "shared@example.com", "access_token": "token"}), encoding="utf-8")
    accounts_list = [
        {"email": "first@example.com"},
        {"email": "../../evil@example.com"},
    ]
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        resolve_codex_auth_file=lambda _account: str(auth_file),
        update_account_cpa_auth_plan_type=lambda *_args, **_kwargs: {"auth_file": str(auth_file)},
        verify_plus_plan=lambda _item: {"ok": True},
        normalize_observed_auth_plan=lambda *_args: None,
        mark_failed_account=lambda *_args, **_kwargs: None,
        current_time=lambda: 1778888888.0,
    )

    monkeypatch.setattr(accounts, "load_accounts", lambda: accounts_list)
    monkeypatch.setattr(
        accounts,
        "find_account",
        lambda loaded, email: next((account for account in loaded if account["email"] == email), None),
    )
    monkeypatch.setattr(accounts, "update_account", lambda *_args, **_kwargs: None)

    result = _endpoint(app, "/api/accounts/export-cpa-auths", "POST")(
        AccountEmailBatchParams(emails=["first@example.com", "../../evil@example.com"])
    )

    assert result["content_type"] == "application/zip"
    raw = base64.b64decode(result["content_base64"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
    assert names == [
        "codex-shared@example.com-free-deadbeef.json",
        "codex-shared@example.com-free-deadbeef-evil@example.com.json",
    ]
    assert all("/" not in name and "\\" not in name and ".." not in name for name in names)


def test_account_cpa_auth_export_cpa_rejects_unconfirmed_plus(monkeypatch, tmp_path):
    auth_file = tmp_path / "codex-plus@example.com-plus-deadbeef.json"
    auth_file.write_text(json.dumps({"email": "plus@example.com"}), encoding="utf-8")
    captured = {}
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        resolve_codex_auth_file=lambda _account: str(auth_file),
        update_account_cpa_auth_plan_type=lambda *_args, **_kwargs: {"auth_file": str(auth_file)},
        verify_plus_plan=lambda _item: {"ok": False, "message": "Plus 状态未确认", "plan_type": "free"},
        normalize_observed_auth_plan=lambda email, auth_file, plan_type: captured.setdefault(
            "normalized", (email, auth_file, plan_type)
        ),
        mark_failed_account=lambda email, **kwargs: captured.setdefault("failed", (email, kwargs)),
        safe_email_summary=lambda email: f"safe:{email}",
    )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [{"email": "plus@example.com", "account_type": "plus"}])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "plus@example.com" else None)

    with _raises_http(
        404,
        {
            "message": "选中的账号没有可导出的 data/auths 认证文件，或 Plus 状态未通过 OpenAI 实测",
            "missing": ["plus@example.com"],
            "unconfirmed_plus": [{"email": "plus@example.com", "message": "Plus 状态未确认"}],
        },
    ):
        _endpoint(app, "/api/accounts/export-cpa-auths", "POST")(
            AccountEmailBatchParams(emails=["plus@example.com"])
        )

    assert captured["normalized"] == ("plus@example.com", str(auth_file), "free")
    assert captured["failed"] == (
        "plus@example.com",
        {
            "task_id": "export-cpa-auths",
            "status": "pending_manual",
            "message": "导出前检测到 Plus 状态未确认",
            "failure_stage": "export_plan_verify",
        },
    )


def test_account_cpa_auth_convert_session_returns_converted_files(monkeypatch):
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        is_main_account_email=lambda _email: False,
        convert_account_auth_session_to_cpa_auth=lambda email, *, account: {
            "email": email,
            "filename": f"codex-{email}.json",
            "auth_file": f"data/auths/codex-{email}.json",
            "id_token_synthetic": True,
            "refresh_token_present": False,
            "account": {**account, "converted": True},
        },
    )
    account = {"email": "user@example.com"}

    monkeypatch.setattr(accounts, "load_accounts", lambda: [account])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    result = _endpoint(app, "/api/accounts/convert-session-cpa-auths", "POST")(
        AccountSessionCpaConvertParams(emails=["USER@example.com", "USER@example.com"])
    )

    assert result == {
        "converted": 1,
        "missing": [],
        "invalid": [],
        "files": [
            {
                "email": "user@example.com",
                "filename": "codex-user@example.com.json",
                "auth_file": "data/auths/codex-user@example.com.json",
                "id_token_synthetic": True,
                "refresh_token_present": False,
            }
        ],
        "accounts": [{"email": "user@example.com", "converted": True}],
    }


def test_account_cpa_auth_convert_session_reports_empty_missing_and_invalid(monkeypatch):
    def fake_convert(email, *, account):
        raise SessionConversionError(f"未找到 auth_session: {email}")

    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        is_main_account_email=lambda email: email == "owner@example.com",
        convert_account_auth_session_to_cpa_auth=fake_convert,
    )
    account = {"email": "user@example.com"}

    with _raises_http(400, "emails 不能为空"):
        _endpoint(app, "/api/accounts/convert-session-cpa-auths", "POST")(AccountSessionCpaConvertParams(emails=[]))

    monkeypatch.setattr(accounts, "load_accounts", lambda: [account])
    monkeypatch.setattr(accounts, "find_account", lambda loaded, email: loaded[0] if email == "user@example.com" else None)

    result = _endpoint(app, "/api/accounts/convert-session-cpa-auths", "POST")(
        AccountSessionCpaConvertParams(emails=["missing@example.com", "owner@example.com", "user@example.com"])
    )

    assert result["converted"] == 0
    assert result["missing"] == ["missing@example.com", "owner@example.com"]
    assert result["invalid"] == [{"email": "user@example.com", "error": "未找到 auth_session: user@example.com"}]


def test_account_cpa_auth_convert_session_raises_when_no_convertible_accounts(monkeypatch):
    app = _app(
        normalize_email=lambda value: (value or "").strip().lower(),
        is_main_account_email=lambda _email: False,
        convert_account_auth_session_to_cpa_auth=lambda _email, *, account: account,
    )

    monkeypatch.setattr(accounts, "load_accounts", lambda: [])
    monkeypatch.setattr(accounts, "find_account", lambda _loaded, _email: None)

    with _raises_http(404, "选中的账号没有可转换的 auth_session"):
        _endpoint(app, "/api/accounts/convert-session-cpa-auths", "POST")(
            AccountSessionCpaConvertParams(emails=["missing@example.com"])
        )


class _raises_http:
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, _traceback):
        assert exc_type is HTTPException
        assert exc.status_code == self.status_code
        assert exc.detail == self.detail
        return True
