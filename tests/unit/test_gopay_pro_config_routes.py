import pytest
from fastapi import HTTPException

from autotoken.api_routes.gopay_pro_config import (
    GOPAY_PRO_NUMBERS_IMPORT_MAX_BYTES,
    GOPAY_PRO_NUMBERS_IMPORT_MAX_LINES,
    GoPayProConfigParams,
    GoPayProNumbersParams,
    GoPayProSlotParams,
    create_gopay_pro_config_router,
)


def _routes(tmp_path, *, config=None, state=None, number_lines=None):
    root = tmp_path / "CNgopay"
    root.mkdir()
    paths = {
        "root": root,
        "config": root / "config.json",
        "state": root / "runs" / "pool" / "state.json",
        "numbers": root / "pool_numbers.txt",
    }
    store = {
        "config": config if config is not None else {"pool": {"slots": 1, "proxy_api": "legacy"}},
        "state": state if state is not None else {"slots": {}},
        "number_lines": number_lines if number_lines is not None else ["6281----https://sms.example"],
        "writes": [],
        "appends": [],
    }

    def read_json_file(path, fallback):
        if path == paths["config"]:
            return store["config"]
        if path == paths["state"]:
            return store["state"]
        return fallback

    def write_json_atomic(path, value):
        store["writes"].append((path, value))
        if path == paths["config"]:
            store["config"] = value
        if path == paths["state"]:
            store["state"] = value

    def read_lines_file(path):
        assert path == paths["numbers"]
        return store["number_lines"]

    def active_pool_lines(lines):
        return [line for line in lines if str(line or "").strip() and not str(line).strip().startswith("#")]

    def append_unique_pool_lines(path, lines):
        assert path == paths["numbers"]
        store["appends"].extend(lines)
        store["number_lines"].extend(lines)
        return {"added": len(lines), "total": len(store["number_lines"])}

    router = create_gopay_pro_config_router(
        gopay_pro_paths=lambda: paths,
        read_json_file=read_json_file,
        write_json_atomic=write_json_atomic,
        read_lines_file=read_lines_file,
        active_pool_lines=active_pool_lines,
        append_unique_pool_lines=append_unique_pool_lines,
        status_payload=lambda: {"status": "ok"},
        slot_states={"EMPTY", "WALLET_READY", "FAILED"},
    )
    return {route.endpoint.__name__: route.endpoint for route in router.routes}, store


def test_update_gopay_pro_config_uses_active_number_count_and_removes_proxy_api(tmp_path):
    routes, store = _routes(
        tmp_path,
        config={"pool": {"slots": 9, "concurrency": 1, "proxy_api": "legacy", "proxy_api_enabled": True}},
        number_lines=["6281----https://sms.example", "# comment", ""],
    )

    result = routes["update_gopay_pro_config"](GoPayProConfigParams(concurrency=8))

    assert result == {"status": "ok"}
    assert store["config"]["pool"]["slots"] == 1
    assert store["config"]["pool"]["concurrency"] == 8
    assert "proxy_api" not in store["config"]["pool"]
    assert "proxy_api_enabled" not in store["config"]["pool"]


def test_import_gopay_pro_numbers_rejects_invalid_lines(tmp_path):
    routes, _store = _routes(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        routes["import_gopay_pro_numbers"](GoPayProNumbersParams(text="not-a-number-line"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["message"] == "稳定号格式需要包含 ---- 接码 URL"
    assert exc_info.value.detail["invalid"] == ["not-a-number-line"]


def test_import_gopay_pro_numbers_rejects_oversized_text(tmp_path):
    routes, store = _routes(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        routes["import_gopay_pro_numbers"](GoPayProNumbersParams(text=" " * (GOPAY_PRO_NUMBERS_IMPORT_MAX_BYTES + 1)))

    assert exc_info.value.status_code == 400
    assert "GoPay Pro 稳定号导入内容过大" in exc_info.value.detail
    assert store["appends"] == []


def test_import_gopay_pro_numbers_rejects_too_many_lines(tmp_path):
    routes, store = _routes(tmp_path)
    text = "\n".join(["6281----https://sms.example"] * (GOPAY_PRO_NUMBERS_IMPORT_MAX_LINES + 1))

    with pytest.raises(HTTPException) as exc_info:
        routes["import_gopay_pro_numbers"](GoPayProNumbersParams(text=text))

    assert exc_info.value.status_code == 400
    assert "GoPay Pro 稳定号导入行数过多" in exc_info.value.detail
    assert store["appends"] == []


def test_import_gopay_pro_numbers_appends_valid_lines_and_updates_slots(tmp_path):
    routes, store = _routes(tmp_path, number_lines=[])

    result = routes["import_gopay_pro_numbers"](GoPayProNumbersParams(text="6281----https://sms.example"))

    assert result["added"] == 1
    assert result["status"] == {"status": "ok"}
    assert store["config"]["pool"]["slots"] == 1


def test_update_gopay_pro_slot_set_state_writes_state(tmp_path):
    routes, store = _routes(tmp_path, state={"slots": {"slot-01": {"state": "EMPTY", "error": "old"}}})

    result = routes["update_gopay_pro_slot"](GoPayProSlotParams(id="slot-01", action="set-state", state="WALLET_READY"))

    assert result == {"ok": True, "status": {"status": "ok"}}
    assert store["state"]["slots"]["slot-01"]["state"] == "WALLET_READY"
    assert store["state"]["slots"]["slot-01"]["updated_at"] > 0


def test_update_gopay_pro_slot_rejects_unknown_state(tmp_path):
    routes, _store = _routes(tmp_path, state={"slots": {"slot-01": {"state": "EMPTY"}}})

    with pytest.raises(HTTPException) as exc_info:
        routes["update_gopay_pro_slot"](GoPayProSlotParams(id="slot-01", action="set-state", state="UNKNOWN"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "状态不合法"
