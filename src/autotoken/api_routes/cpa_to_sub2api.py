"""CPA auth to Sub2API conversion HTTP routes."""

import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from autotoken.core.paths import is_inside_directory

MAX_CPA_TO_SUB2API_FILES = 200
MAX_CPA_TO_SUB2API_TOTAL_BYTES = 10 * 1024 * 1024


class CpaToSub2ApiSource(BaseModel):
    filename: str
    content: str


class CpaToSub2ApiProxyParams(BaseModel):
    enabled: bool = False
    name: str = "批量导入代理"
    protocol: str = "http"
    host: str = ""
    port: int = 7890
    username: str = ""
    password: str = ""
    status: str = "active"


class CpaToSub2ApiSettingsParams(BaseModel):
    output_dir: str = ""
    output_filename: str = ""
    concurrency: int = 10
    priority: int = 1
    rate_multiplier: float = 1.0
    auto_pause_on_expired: bool = True
    proxy: CpaToSub2ApiProxyParams = Field(default_factory=CpaToSub2ApiProxyParams)


class CpaToSub2ApiInspectParams(BaseModel):
    files: list[CpaToSub2ApiSource]


class CpaToSub2ApiConvertParams(BaseModel):
    files: list[CpaToSub2ApiSource]
    selected_filenames: list[str] | None = None
    settings: CpaToSub2ApiSettingsParams = Field(default_factory=CpaToSub2ApiSettingsParams)


class CpaToSub2ApiOpenDirParams(BaseModel):
    output_dir: str


class CpaToSub2ApiSelectDirParams(BaseModel):
    current_dir: str = ""


def default_cpa_to_sub2api_output_dir() -> Path:
    desktop = Path.home() / "Desktop"
    return desktop if desktop.exists() and desktop.is_dir() else Path.home()


def sub2api_record_to_dict(record):
    return {
        "file_name": record.file_name,
        "selected": record.selected,
        "is_valid": record.is_valid,
        "variant": record.variant,
        "email": record.email,
        "target_name": record.target_name,
        "plan_type": record.plan_type,
        "status_text": record.status_text,
        "error_message": record.error_message,
    }


def sub2api_settings_from_params(params: CpaToSub2ApiSettingsParams):
    from autotoken.integrations.sub2api_converter import ExportSettings, ProxyConfig, generate_default_filename

    proxy = ProxyConfig(**params.proxy.model_dump())
    return ExportSettings(
        output_filename=params.output_filename.strip() or generate_default_filename(),
        concurrency=params.concurrency,
        priority=params.priority,
        rate_multiplier=params.rate_multiplier,
        auto_pause_on_expired=params.auto_pause_on_expired,
        proxy=proxy,
    )


def _validate_cpa_to_sub2api_sources(files: list[CpaToSub2ApiSource]) -> None:
    if len(files or []) > MAX_CPA_TO_SUB2API_FILES:
        raise HTTPException(status_code=400, detail=f"最多一次转换 {MAX_CPA_TO_SUB2API_FILES} 个 JSON 文件")
    total_bytes = 0
    for item in files or []:
        total_bytes += len(str(item.content or "").encode("utf-8", errors="ignore"))
        if total_bytes > MAX_CPA_TO_SUB2API_TOTAL_BYTES:
            raise HTTPException(status_code=400, detail="CPA JSON 总内容过大，最多支持 10MB")


def write_cpa_to_sub2api_output(output_dir: str, filename: str, content: str) -> str:
    directory_text = output_dir.strip()
    directory = Path(directory_text).expanduser() if directory_text else default_cpa_to_sub2api_output_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise OSError("输出路径不是目录")
        output_path = directory / filename
        if not is_inside_directory(output_path, directory):
            raise OSError("输出文件名不能指向输出目录外")
        output_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"无法写入输出文件：{exc}") from exc
    return str(output_path.resolve())


def create_cpa_to_sub2api_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/cpa-to-sub2api/inspect")
    def inspect_cpa_to_sub2api(params: CpaToSub2ApiInspectParams):
        """检查 CPA JSON 文件是否可转换为 Sub2API 导入格式。"""
        from autotoken.integrations.sub2api_converter import inspect_sources

        _validate_cpa_to_sub2api_sources(params.files)
        records = inspect_sources([(item.filename, item.content) for item in params.files])
        return {
            "records": [sub2api_record_to_dict(record) for record in records],
            "total": len(records),
            "valid": sum(1 for record in records if record.is_valid),
            "invalid": sum(1 for record in records if not record.is_valid),
        }

    @router.post("/api/cpa-to-sub2api/convert")
    def convert_cpa_to_sub2api(params: CpaToSub2ApiConvertParams):
        """将 CPA JSON 批量转换为 Sub2API 账号导入 JSON。"""
        from autotoken.integrations.sub2api_converter import (
            ConversionError,
            export_records,
            inspect_sources,
            validate_output_filename,
        )

        try:
            _validate_cpa_to_sub2api_sources(params.files)
            records = inspect_sources([(item.filename, item.content) for item in params.files])
            settings = sub2api_settings_from_params(params.settings)
            selected = set(params.selected_filenames or []) if params.selected_filenames is not None else None
            payload = export_records(records, settings, selected_file_names=selected)
            filename = validate_output_filename(settings.output_filename)
        except ConversionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        content = json.dumps(payload, ensure_ascii=False, indent=2)
        output_path = write_cpa_to_sub2api_output(params.settings.output_dir, filename, content)
        return {
            "filename": filename,
            "content": content,
            "output_path": output_path,
            "payload": payload,
            "records": [sub2api_record_to_dict(record) for record in records],
            "total": len(records),
            "converted": len(payload.get("accounts") or []),
            "invalid": sum(1 for record in records if not record.is_valid),
        }

    @router.post("/api/cpa-to-sub2api/open-output-dir")
    def open_cpa_to_sub2api_output_dir(params: CpaToSub2ApiOpenDirParams):
        """打开 Sub2API 转换输出目录。"""
        directory_text = params.output_dir.strip()
        if not directory_text:
            raise HTTPException(status_code=400, detail="输出目录不能为空")
        directory = Path(directory_text).expanduser()
        if not directory.exists() or not directory.is_dir():
            raise HTTPException(status_code=404, detail="输出目录不存在")
        try:
            if os.name == "nt":
                os.startfile(str(directory.resolve()))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(directory.resolve())])
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"打开输出目录失败：{exc}") from exc
        return {"message": "已打开输出目录"}

    @router.get("/api/cpa-to-sub2api/default-output-dir")
    def get_cpa_to_sub2api_default_output_dir():
        """获取默认 Sub2API 转换输出目录。"""
        return {"output_dir": str(default_cpa_to_sub2api_output_dir())}

    @router.post("/api/cpa-to-sub2api/select-output-dir")
    def select_cpa_to_sub2api_output_dir(params: CpaToSub2ApiSelectDirParams):
        """弹出本机目录选择框并返回完整输出目录。"""
        try:
            import tkinter as tk
            from tkinter import filedialog

            initial_dir = Path(params.current_dir.strip()).expanduser()
            if not initial_dir.exists() or not initial_dir.is_dir():
                initial_dir = Path.cwd()

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                title="选择输出目录",
                initialdir=str(initial_dir),
                mustexist=False,
                parent=root,
            )
            root.destroy()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"选择输出目录失败：{exc}") from exc
        return {"output_dir": selected or ""}

    return router
