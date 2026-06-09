from dataclasses import dataclass

from fastapi import FastAPI, HTTPException

from autotoken import sub2api_converter
from autotoken.api_routes import cpa_to_sub2api as cpa_routes
from autotoken.api_routes.cpa_to_sub2api import (
    CpaToSub2ApiConvertParams,
    CpaToSub2ApiInspectParams,
    CpaToSub2ApiOpenDirParams,
    CpaToSub2ApiSettingsParams,
    CpaToSub2ApiSource,
    create_cpa_to_sub2api_router,
)


@dataclass
class _Record:
    file_name: str
    selected: bool
    is_valid: bool
    variant: str = "CPA"
    email: str = "user@example.com"
    target_name: str = "user"
    plan_type: str = "team"
    status_text: str = "可转换"
    error_message: str = ""


def _app():
    app = FastAPI()
    app.include_router(create_cpa_to_sub2api_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


def test_cpa_to_sub2api_inspect_route_reports_counts(monkeypatch):
    app = _app()
    records = [
        _Record(file_name="valid.json", selected=True, is_valid=True),
        _Record(file_name="bad.json", selected=False, is_valid=False, status_text="JSON 解析失败"),
    ]

    monkeypatch.setattr(sub2api_converter, "inspect_sources", lambda sources: records)

    result = _endpoint(app, "/api/cpa-to-sub2api/inspect", "POST")(
        CpaToSub2ApiInspectParams(files=[CpaToSub2ApiSource(filename="valid.json", content="{}")])
    )

    assert result["total"] == 2
    assert result["valid"] == 1
    assert result["invalid"] == 1
    assert result["records"][0]["file_name"] == "valid.json"
    assert result["records"][1]["status_text"] == "JSON 解析失败"


def test_cpa_to_sub2api_convert_route_exports_and_writes_output(monkeypatch, tmp_path):
    app = _app()
    captured = {}
    records = [_Record(file_name="valid.json", selected=True, is_valid=True)]

    monkeypatch.setattr(sub2api_converter, "inspect_sources", lambda sources: records)

    def fake_export_records(records_arg, settings, selected_file_names=None):
        captured["settings"] = settings
        captured["selected"] = selected_file_names
        return {"accounts": [{"name": "user"}], "proxies": []}

    monkeypatch.setattr(sub2api_converter, "export_records", fake_export_records)
    monkeypatch.setattr(cpa_routes, "write_cpa_to_sub2api_output", lambda output_dir, filename, content: str(tmp_path / filename))

    result = _endpoint(app, "/api/cpa-to-sub2api/convert", "POST")(
        CpaToSub2ApiConvertParams(
            files=[CpaToSub2ApiSource(filename="valid.json", content="{}")],
            selected_filenames=["valid.json"],
            settings=CpaToSub2ApiSettingsParams(
                output_dir=str(tmp_path),
                output_filename="accounts",
                concurrency=3,
                priority=2,
                rate_multiplier=1.5,
            ),
        )
    )

    assert result["filename"] == "accounts.json"
    assert result["converted"] == 1
    assert result["invalid"] == 0
    assert result["payload"] == {"accounts": [{"name": "user"}], "proxies": []}
    assert captured["selected"] == {"valid.json"}
    assert captured["settings"].concurrency == 3
    assert captured["settings"].priority == 2
    assert captured["settings"].rate_multiplier == 1.5


def test_cpa_to_sub2api_convert_route_maps_conversion_errors(monkeypatch):
    app = _app()

    monkeypatch.setattr(sub2api_converter, "inspect_sources", lambda _sources: [])
    monkeypatch.setattr(
        sub2api_converter,
        "export_records",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sub2api_converter.ConversionError("没有可导出的有效文件。")),
    )

    try:
        _endpoint(app, "/api/cpa-to-sub2api/convert", "POST")(
            CpaToSub2ApiConvertParams(files=[CpaToSub2ApiSource(filename="bad.json", content="{}")])
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "没有可导出的有效文件。"
    else:
        raise AssertionError("conversion error must fail")


def test_cpa_to_sub2api_inspect_rejects_too_many_files():
    app = _app()
    files = [
        CpaToSub2ApiSource(filename=f"auth-{index}.json", content="{}")
        for index in range(cpa_routes.MAX_CPA_TO_SUB2API_FILES + 1)
    ]

    try:
        _endpoint(app, "/api/cpa-to-sub2api/inspect", "POST")(CpaToSub2ApiInspectParams(files=files))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert f"最多一次转换 {cpa_routes.MAX_CPA_TO_SUB2API_FILES} 个 JSON 文件" in exc.detail
    else:
        raise AssertionError("too many CPA sources must fail")


def test_cpa_to_sub2api_convert_rejects_oversized_content():
    app = _app()

    try:
        _endpoint(app, "/api/cpa-to-sub2api/convert", "POST")(
            CpaToSub2ApiConvertParams(
                files=[
                    CpaToSub2ApiSource(
                        filename="auth.json",
                        content=" " * (cpa_routes.MAX_CPA_TO_SUB2API_TOTAL_BYTES + 1),
                    )
                ]
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "CPA JSON 总内容过大" in exc.detail
    else:
        raise AssertionError("oversized CPA source content must fail")


def test_write_cpa_to_sub2api_output_rejects_filename_escape(tmp_path):
    try:
        cpa_routes.write_cpa_to_sub2api_output(str(tmp_path), "../outside.json", "{}")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "输出文件名不能指向输出目录外" in exc.detail
    else:
        raise AssertionError("escaping output filename must fail")

    assert not (tmp_path.parent / "outside.json").exists()


def test_write_cpa_to_sub2api_output_rejects_existing_symlink_escape(tmp_path):
    link = tmp_path / "link.json"
    outside = tmp_path.parent / "outside-sub2api.json"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        return

    try:
        cpa_routes.write_cpa_to_sub2api_output(str(tmp_path), "link.json", "{}")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "输出文件名不能指向输出目录外" in exc.detail
    else:
        raise AssertionError("symlink escaping output filename must fail")

    assert not outside.exists()


def test_cpa_to_sub2api_default_and_open_dir_validation(monkeypatch, tmp_path):
    app = _app()

    monkeypatch.setattr(cpa_routes, "default_cpa_to_sub2api_output_dir", lambda: tmp_path)
    assert _endpoint(app, "/api/cpa-to-sub2api/default-output-dir", "GET")() == {
        "output_dir": str(tmp_path)
    }

    try:
        _endpoint(app, "/api/cpa-to-sub2api/open-output-dir", "POST")(CpaToSub2ApiOpenDirParams(output_dir=""))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "输出目录不能为空"
    else:
        raise AssertionError("empty output directory must fail")

    try:
        _endpoint(app, "/api/cpa-to-sub2api/open-output-dir", "POST")(
            CpaToSub2ApiOpenDirParams(output_dir=str(tmp_path / "missing"))
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "输出目录不存在"
    else:
        raise AssertionError("missing output directory must fail")
