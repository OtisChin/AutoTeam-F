"""管理员登录态持久化。

统一使用 `data/autotoken.sqlite3` 保存：
- session_token
- email
- password
- account_id
- workspace_name
- updated_at

旧的项目根目录 `state.json` / `session` 需要通过
`scripts/migrate_to_sqlite.py` 手动导入。
"""

import json
import os
import time
from pathlib import Path

from autotoken.core.paths import PROJECT_ROOT
from autotoken.core.textio import write_text
from autotoken.storage import sqlite_store

STATE_FILE = PROJECT_ROOT / "state.json"
LEGACY_SESSION_FILE = PROJECT_ROOT / "session"
STATE_FILE_MODE = 0o666
ADMIN_STATE_FILE_MAX_BYTES = 256 * 1024
_KV_NAMESPACE = "admin_state"
_KV_KEY = "state"


def _normalize_state(data):
    if not isinstance(data, dict):
        return {}
    return {
        "email": data.get("email", "") or "",
        "session_token": data.get("session_token", "") or "",
        "password": data.get("password", "") or "",
        "account_id": data.get("account_id", "") or "",
        "workspace_name": data.get("workspace_name", "") or "",
        "updated_at": data.get("updated_at"),
    }


def _db_path() -> Path:
    try:
        if Path(STATE_FILE).resolve() != (PROJECT_ROOT / "state.json").resolve():
            return Path(STATE_FILE).with_suffix(".sqlite3")
    except Exception:
        pass
    return sqlite_store.default_db_path()


def _load_state_from_db():
    return sqlite_store.get_json(_KV_NAMESPACE, _KV_KEY, default=None, path=_db_path())


def _should_write_state_file() -> bool:
    try:
        if Path(STATE_FILE).resolve() != (PROJECT_ROOT / "state.json").resolve():
            return True
    except Exception:
        return True
    return STATE_FILE.exists() or STATE_FILE.is_symlink()


def _write_state_file_mirror(state):
    if not _should_write_state_file():
        return
    target = STATE_FILE.resolve()
    write_text(target, json.dumps(_normalize_state(state), indent=2, ensure_ascii=False))
    try:
        os.chmod(target, STATE_FILE_MODE)
    except Exception:
        pass


def _read_state_text(path: Path) -> str:
    if path.exists() and path.stat().st_size > ADMIN_STATE_FILE_MAX_BYTES:
        raise ValueError(f"管理员状态文件过大，无法一次性读取: {path}")
    return path.read_text(encoding="utf-8")


def _save_state(state):
    normalized = _normalize_state(state)
    sqlite_store.set_json(_KV_NAMESPACE, _KV_KEY, normalized, path=_db_path())
    _write_state_file_mirror(normalized)


def load_admin_state():
    state = _normalize_state(_load_state_from_db() or {})
    if any(state.values()):
        return state
    try:
        if STATE_FILE.exists():
            raw = json.loads(_read_state_text(STATE_FILE) or "{}")
            state = _normalize_state(raw)
            if any(state.values()):
                _save_state(state)
                return state
    except Exception:
        pass
    try:
        if LEGACY_SESSION_FILE.exists():
            state = _normalize_state({"session_token": _read_state_text(LEGACY_SESSION_FILE).strip()})
            _save_state(state)
            LEGACY_SESSION_FILE.unlink()
            return state
    except Exception:
        pass
    return state


def save_admin_state(state):
    _save_state(state)


def update_admin_state(**kwargs):
    state = load_admin_state()
    state.update(kwargs)
    state["updated_at"] = time.time()
    save_admin_state(state)
    return state


def clear_admin_state():
    sqlite_store.set_json(_KV_NAMESPACE, _KV_KEY, {}, path=_db_path())
    if _should_write_state_file():
        target = STATE_FILE.resolve()
        write_text(target, "{}")
        try:
            os.chmod(target, STATE_FILE_MODE)
        except Exception:
            pass
    try:
        if LEGACY_SESSION_FILE.exists():
            LEGACY_SESSION_FILE.unlink()
    except Exception:
        pass


def get_admin_email():
    return load_admin_state().get("email", "")


def get_admin_session_token():
    return load_admin_state().get("session_token", "")


def _is_valid_uuid(value: str) -> bool:
    """检查是否为有效的 UUID 格式"""
    import re

    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", value, re.I))


def get_chatgpt_account_id():
    state = load_admin_state()
    state_id = state.get("account_id", "")
    # state.json 里的值必须是 UUID 格式才有效（user-xxx 是 user ID 不是 account ID）
    if state_id and _is_valid_uuid(state_id):
        return state_id
    return os.environ.get("CHATGPT_ACCOUNT_ID", "")


def get_admin_password():
    return load_admin_state().get("password", "")


def get_chatgpt_workspace_name():
    state = load_admin_state()
    return state.get("workspace_name", "")


def get_admin_state_summary():
    state = load_admin_state()
    return {
        "configured": bool(state.get("session_token") and state.get("account_id")),
        "email": state.get("email", ""),
        "account_id": state.get("account_id", ""),
        "workspace_name": state.get("workspace_name", ""),
        "session_present": bool(state.get("session_token")),
        "password_saved": bool(state.get("password")),
        "updated_at": state.get("updated_at"),
    }
