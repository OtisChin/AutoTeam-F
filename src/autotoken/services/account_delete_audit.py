"""Account deletion audit persistence helpers."""

import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path


def build_delete_audit_payload(
    *,
    email: str,
    log_context: str,
    reason: str,
    account: dict | None,
    record_deleted: bool,
    auth_session_deleted: bool,
    normalize_email: Callable[[str], str],
    mail_service_deleted: bool = False,
    message: str = "",
    now: float | None = None,
) -> dict:
    return {
        "ts": time.time() if now is None else float(now),
        "email": normalize_email(email),
        "source": log_context,
        "reason": reason,
        "message": message,
        "record_deleted": bool(record_deleted),
        "auth_session_deleted": bool(auth_session_deleted),
        "mail_service_deleted": bool(mail_service_deleted),
        "account_existed": bool(account),
        "status": (account or {}).get("status"),
        "account_type": (account or {}).get("account_type"),
        "seat_type": (account or {}).get("seat_type"),
        "mail_provider": (account or {}).get("mail_provider"),
        "cloudmail_account_id_present": bool((account or {}).get("cloudmail_account_id")),
        "auth_file": (account or {}).get("auth_file"),
        "last_bind_status": (account or {}).get("last_bind_status"),
        "last_bind_failure_stage": (account or {}).get("last_bind_failure_stage"),
        "last_bind_message": (account or {}).get("last_bind_message"),
        "last_bind_task_id": (account or {}).get("last_bind_task_id"),
        "last_bind_at": (account or {}).get("last_bind_at"),
    }


def audit_db_path(path: Path, *, project_root: Path, default_db_path: Callable[[], Path]) -> Path:
    default_path = project_root / "data" / "account_delete_audit.jsonl"
    try:
        if Path(path).resolve() != default_path.resolve():
            return Path(path).with_suffix(".sqlite3")
    except Exception:
        pass
    return default_db_path()


def append_delete_audit(
    *,
    path: Path,
    db_path: Path,
    audit_lock: threading.Lock,
    email: str,
    log_context: str,
    reason: str,
    account: dict | None,
    record_deleted: bool,
    auth_session_deleted: bool,
    normalize_email: Callable[[str], str],
    sqlite_store,
    logger: logging.Logger,
    mail_service_deleted: bool = False,
    message: str = "",
    now: float | None = None,
) -> None:
    payload = build_delete_audit_payload(
        email=email,
        log_context=log_context,
        reason=reason,
        account=account,
        record_deleted=record_deleted,
        auth_session_deleted=auth_session_deleted,
        normalize_email=normalize_email,
        mail_service_deleted=mail_service_deleted,
        message=message,
        now=now,
    )
    try:
        sqlite_store.initialize(db_path)
        with sqlite_store.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO event_records(kind, timestamp, email, category, task_id, status, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "account_delete_audit",
                    float(payload.get("ts") or time.time()),
                    str(payload.get("email") or ""),
                    str(payload.get("reason") or ""),
                    str(payload.get("last_bind_task_id") or ""),
                    str(payload.get("status") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with audit_lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        logger.warning("[account-delete-audit] failed to persist delete audit: email=%s error=%s", email, exc)
    logger.warning(
        "[account-delete-audit] account removed: email=%s source=%s reason=%s record_deleted=%s auth_session_deleted=%s account_type=%s status=%s task_id=%s",
        email,
        log_context,
        reason,
        record_deleted,
        auth_session_deleted,
        payload.get("account_type"),
        payload.get("status"),
        payload.get("last_bind_task_id") or "",
    )


def migrate_delete_audit_jsonl(
    *,
    path: Path,
    sqlite_store,
    logger: logging.Logger,
    now: float | None = None,
) -> int:
    if not path.exists():
        return 0
    try:
        marker = sqlite_store.get_json("migrations", "account_delete_audit_jsonl", default=None)
        if isinstance(marker, dict) and marker.get("done"):
            return 0

        count = 0
        sqlite_store.initialize()
        with sqlite_store.connect() as conn:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except Exception:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    conn.execute(
                        """
                        INSERT INTO event_records(kind, timestamp, email, category, task_id, status, data)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "account_delete_audit",
                            float(
                                payload.get("ts") or payload.get("timestamp") or (time.time() if now is None else now)
                            ),
                            str(payload.get("email") or ""),
                            str(payload.get("reason") or ""),
                            str(payload.get("last_bind_task_id") or ""),
                            str(payload.get("status") or ""),
                            json.dumps(payload, ensure_ascii=False),
                        ),
                    )
                    count += 1
        sqlite_store.set_json("migrations", "account_delete_audit_jsonl", {"done": True, "count": count})
        return count
    except Exception as exc:
        logger.warning("[启动] 迁移账号删除审计 JSONL 失败: %s", exc)
        return 0
