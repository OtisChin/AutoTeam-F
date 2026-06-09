"""GoPay Pro status, configuration, number pool, and slot routes."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotoken.api_routes.input_limits import validate_text_payload_limits

GOPAY_PRO_NUMBERS_IMPORT_MAX_BYTES = 2 * 1024 * 1024
GOPAY_PRO_NUMBERS_IMPORT_MAX_LINES = 10_000


class GoPayProNumbersParams(BaseModel):
    text: str = ""


class GoPayProConfigParams(BaseModel):
    slots: int | None = None
    concurrency: int | None = None


class GoPayProSlotParams(BaseModel):
    id: str = ""
    action: str = ""
    state: str = ""


def create_gopay_pro_config_router(
    *,
    gopay_pro_paths: Callable[[], dict[str, Path]],
    read_json_file: Callable[[Path, Any], Any],
    write_json_atomic: Callable[[Path, Any], None],
    read_lines_file: Callable[[Path], list[str]],
    active_pool_lines: Callable[[list[str]], list[str]],
    append_unique_pool_lines: Callable[[Path, list[str]], dict],
    status_payload: Callable[[], dict],
    slot_states: set[str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/gopay-pro/status")
    def get_gopay_pro_status():
        return status_payload()

    @router.put("/api/gopay-pro/config")
    def update_gopay_pro_config(params: GoPayProConfigParams):
        paths = gopay_pro_paths()
        if not paths["root"].exists():
            raise HTTPException(status_code=404, detail=f"CNgopay 目录不存在: {paths['root']}")
        config = read_json_file(paths["config"], {})
        if not isinstance(config, dict):
            config = {}
        pool = config.setdefault("pool", {})
        if not isinstance(pool, dict):
            pool = {}
            config["pool"] = pool
        active_number_count = len(active_pool_lines(read_lines_file(paths["numbers"])))
        pool["slots"] = max(1, min(50, active_number_count or int(pool.get("slots") or 1)))
        if params.concurrency is not None:
            pool["concurrency"] = max(1, min(50, int(params.concurrency)))
        pool.pop("proxy_api", None)
        pool.pop("proxy_api_enabled", None)
        pool.pop("proxy_api_provider", None)
        pool.pop("proxy_api_url", None)
        write_json_atomic(paths["config"], config)
        return status_payload()

    @router.post("/api/gopay-pro/numbers")
    def import_gopay_pro_numbers(params: GoPayProNumbersParams):
        paths = gopay_pro_paths()
        lines = validate_text_payload_limits(
            params.text,
            max_bytes=GOPAY_PRO_NUMBERS_IMPORT_MAX_BYTES,
            max_lines=GOPAY_PRO_NUMBERS_IMPORT_MAX_LINES,
            label="GoPay Pro 稳定号导入",
        )
        invalid = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#") and "----" not in line.strip()
        ]
        if invalid:
            raise HTTPException(status_code=400, detail={"message": "稳定号格式需要包含 ---- 接码 URL", "invalid": invalid})
        result = append_unique_pool_lines(paths["numbers"], lines)
        config = read_json_file(paths["config"], {})
        if isinstance(config, dict):
            pool = config.setdefault("pool", {})
            if isinstance(pool, dict):
                pool["slots"] = max(
                    1,
                    min(50, len(active_pool_lines(read_lines_file(paths["numbers"]))) or int(pool.get("slots") or 1)),
                )
                write_json_atomic(paths["config"], config)
        return {**result, "status": status_payload()}

    @router.post("/api/gopay-pro/slot")
    def update_gopay_pro_slot(params: GoPayProSlotParams):
        slot_id = str(params.id or "").strip()
        action = str(params.action or "").strip()
        if not slot_id:
            raise HTTPException(status_code=400, detail="slot id 不能为空")
        paths = gopay_pro_paths()
        state = read_json_file(paths["state"], {"slots": {}})
        slots = state.setdefault("slots", {})
        if not isinstance(slots, dict) or slot_id not in slots:
            raise HTTPException(status_code=404, detail="slot 不存在")
        if action == "set-state":
            next_state = str(params.state or "").strip()
            if next_state not in slot_states:
                raise HTTPException(status_code=400, detail="状态不合法")
            slots[slot_id]["state"] = next_state
            slots[slot_id]["updated_at"] = int(time.time())
        elif action == "clear-error":
            slots[slot_id].pop("error", None)
            slots[slot_id]["updated_at"] = int(time.time())
        elif action == "delete":
            slots.pop(slot_id, None)
        else:
            raise HTTPException(status_code=400, detail="未知 slot 动作")
        write_json_atomic(paths["state"], state)
        return {"ok": True, "status": status_payload()}

    return router
