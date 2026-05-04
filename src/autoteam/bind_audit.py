"""绑卡任务审计日志（持久化到 bind_audit.json）。"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from autoteam.paths import PROJECT_ROOT
from autoteam.textio import read_text, write_text

logger = logging.getLogger(__name__)

BIND_AUDIT_FILE = PROJECT_ROOT / "bind_audit.json"
BIND_AUDIT_FILE_MODE = 0o666
RECORD_LIMIT = 500

_LOCK = threading.Lock()


def _load():
    if not BIND_AUDIT_FILE.exists():
        return []
    try:
        raw = read_text(BIND_AUDIT_FILE).strip()
        if not raw:
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception as exc:
        corrupt_path = BIND_AUDIT_FILE.with_suffix(f".corrupt-{int(time.time())}.json")
        try:
            BIND_AUDIT_FILE.rename(corrupt_path)
            logger.error("[bind_audit] 解析失败, 已保留原文件为 %s: %s", corrupt_path.name, exc)
        except Exception as rename_exc:
            logger.error("[bind_audit] 解析失败且无法重命名 (%s): %s", exc, rename_exc)
        return []


def _save(records):
    records = records[-RECORD_LIMIT:]
    target = BIND_AUDIT_FILE.resolve()
    write_text(target, json.dumps(records, indent=2, ensure_ascii=False))
    try:
        os.chmod(target, BIND_AUDIT_FILE_MODE)
    except Exception:
        pass


def record_bind_audit(entry: dict):
    payload = dict(entry or {})
    payload.setdefault("timestamp", time.time())
    with _LOCK:
        records = _load()
        records.append(payload)
        _save(records)
    return payload


def list_bind_audits(limit: int = 50):
    with _LOCK:
        records = _load()
    return records[-limit:][::-1]
