r"""One-shot legacy data migration into data/autoteam.sqlite3.

Run manually before starting the web service when upgrading an old install:

    .\.venv\Scripts\python.exe scripts\migrate_to_sqlite.py --apply

The script is intentionally idempotent. It merges legacy JSON files with the
current SQLite database, keeps richer/current account fields, rebuilds derived
indexes, and prints verification counts at the end.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autoteam import sqlite_store  # noqa: E402
from autoteam.accounts import ACCOUNT_TYPE_FREE, _normalize_account_record  # noqa: E402
from autoteam.auth_session_store import _target_path as auth_session_target_path  # noqa: E402


ACCOUNT_TYPE_RANK = {"free": 0, "team": 1, "plus": 2, "pro": 3}
STATUS_RANK = {
    "pending": 0,
    "personal": 1,
    "standby": 2,
    "exhausted": 3,
    "active": 4,
    "plus": 5,
    "orphan": 6,
    "auth_invalid": 7,
    "fail": 8,
}


def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return fallback
        return json.loads(text)
    except Exception as exc:
        print(f"[WARN] 跳过无法解析的 JSON: {path} ({exc})")
        return fallback


def load_delete_audit_emails() -> set[str]:
    emails: set[str] = set()
    sources = [ROOT / "data" / "account_delete_audit.jsonl"]
    for source in sources:
        if not source.exists():
            continue
        try:
            for line in source.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                email = str(payload.get("email") or "").strip().lower()
                if email:
                    emails.add(email)
        except Exception as exc:
            print(f"[WARN] 跳过无法读取的删除审计文件: {source} ({exc})")
    return emails


def set_json(conn, namespace: str, key: str, value) -> None:
    conn.execute(
        """
        INSERT INTO kv_store(namespace, key, value, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(namespace, key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (namespace, key, json.dumps(value, ensure_ascii=False), time.time()),
    )


def get_json(conn, namespace: str, key: str, default=None):
    row = conn.execute(
        "SELECT value FROM kv_store WHERE namespace = ? AND key = ?",
        (namespace, key),
    ).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return default


def row_to_account(row) -> dict:
    try:
        data = json.loads(row["data"] or "{}")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.update(
        {
            "email": row["email"],
            "status": row["status"],
            "account_type": row["account_type"],
            "seat_type": row["seat_type"],
            "password": row["password"],
            "cloudmail_account_id": data.get("cloudmail_account_id", row["cloudmail_account_id"]),
            "mail_provider": data.get("mail_provider", row["mail_provider"]),
            "auth_file": data.get("auth_file", row["auth_file"]),
            "credentials_exported": bool(row["credentials_exported"]),
            "created_at": row["created_at"],
        }
    )
    return _normalize_account_record(data)


def truthy(value) -> bool:
    return bool(value not in (None, "", [], {}, False))


def choose_account_type(left: str, right: str) -> str:
    left = str(left or ACCOUNT_TYPE_FREE).lower()
    right = str(right or ACCOUNT_TYPE_FREE).lower()
    return right if ACCOUNT_TYPE_RANK.get(right, 0) > ACCOUNT_TYPE_RANK.get(left, 0) else left


def choose_status(left: str, right: str) -> str:
    left = str(left or "pending").lower()
    right = str(right or "pending").lower()
    return right if STATUS_RANK.get(right, 0) > STATUS_RANK.get(left, 0) else left


def merge_account(base: dict | None, incoming: dict) -> dict:
    if not base:
        return _normalize_account_record(incoming)
    merged = dict(base)
    incoming = _normalize_account_record(incoming)
    for key, value in incoming.items():
        if key == "email":
            continue
        if key == "account_type":
            merged[key] = choose_account_type(merged.get(key), value)
        elif key == "status":
            merged[key] = choose_status(merged.get(key), value)
        elif key == "credentials_exported":
            merged[key] = bool(merged.get(key)) or bool(value)
        elif key in {"created_at"}:
            if not truthy(merged.get(key)) or (truthy(value) and float(value or 0) < float(merged.get(key) or 0)):
                merged[key] = value
        elif key.endswith("_at") or key in {"updated_at", "last_active_at", "last_bind_at"}:
            if truthy(value) and float(value or 0) > float(merged.get(key) or 0):
                merged[key] = value
        elif truthy(value) and not truthy(merged.get(key)):
            merged[key] = value
        elif key in {
            "last_bind_status",
            "last_bind_message",
            "last_bind_failure_stage",
            "last_checkout_url",
            "last_bind_task_id",
        } and truthy(value):
            if not truthy(merged.get("last_bind_at")) or float(incoming.get("last_bind_at") or 0) >= float(merged.get("last_bind_at") or 0):
                merged[key] = value
    return _normalize_account_record(merged)


def upsert_account(conn, account: dict) -> None:
    acc = _normalize_account_record(account)
    if not acc.get("email"):
        return
    now = time.time()
    conn.execute(
        """
        INSERT INTO accounts (
            email, status, account_type, seat_type, password, cloudmail_account_id,
            mail_provider, auth_file, credentials_exported, created_at, updated_at, data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            status=excluded.status,
            account_type=excluded.account_type,
            seat_type=excluded.seat_type,
            password=excluded.password,
            cloudmail_account_id=excluded.cloudmail_account_id,
            mail_provider=excluded.mail_provider,
            auth_file=excluded.auth_file,
            credentials_exported=excluded.credentials_exported,
            created_at=excluded.created_at,
            updated_at=excluded.updated_at,
            data=excluded.data
        """,
        (
            acc["email"],
            str(acc.get("status") or "pending"),
            str(acc.get("account_type") or ACCOUNT_TYPE_FREE),
            str(acc.get("seat_type") or "unknown"),
            str(acc.get("password") or ""),
            None if acc.get("cloudmail_account_id") is None else str(acc.get("cloudmail_account_id")),
            acc.get("mail_provider"),
            acc.get("auth_file"),
            1 if bool(acc.get("credentials_exported")) else 0,
            acc.get("created_at") or now,
            now,
            json.dumps(dict(acc), ensure_ascii=False),
        ),
    )


def load_existing_accounts(conn) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    return {str(row["email"]).lower(): row_to_account(row) for row in rows}


def migrate_accounts(conn, *, apply: bool) -> dict:
    merged = load_existing_accounts(conn)
    deleted_emails = load_delete_audit_emails()
    sources = [ROOT / "accounts.json", ROOT / "data" / "accounts.json"]
    source_counts = {}
    for path in sources:
        data = read_json(path, [])
        rows = data if isinstance(data, list) else []
        source_counts[str(path.relative_to(ROOT))] = len(rows)
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            email = str(raw.get("email") or "").strip().lower()
            if not email:
                continue
            merged[email] = merge_account(merged.get(email), raw)
    for email in list(merged.keys()):
        if email in deleted_emails:
            merged.pop(email, None)

    if apply:
        conn.execute("DELETE FROM accounts")
        for account in merged.values():
            upsert_account(conn, account)
        conn.execute("DELETE FROM kv_store WHERE namespace = ? AND key = ?", ("accounts", "deleted_account_tombstones"))
        conn.execute("DELETE FROM kv_store WHERE namespace = ? AND key = ?", ("accounts", "legacy_accounts_mtime_ns"))
    return {"total": len(merged), "sources": source_counts, "deleted_filtered": len(deleted_emails)}


def event_payload(row) -> dict:
    try:
        data = json.loads(row["data"] or "{}")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("timestamp", row["timestamp"])
    data.setdefault("email", row["email"])
    data.setdefault("category", row["category"])
    data.setdefault("task_id", row["task_id"])
    data.setdefault("status", row["status"])
    return data


def insert_event(conn, kind: str, payload: dict) -> None:
    conn.execute(
        """
        INSERT INTO event_records(kind, timestamp, email, category, task_id, status, data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            float(payload.get("timestamp") or time.time()),
            str(payload.get("email") or payload.get("account_email") or ""),
            str(payload.get("category") or payload.get("flow") or ""),
            str(payload.get("task_id") or ""),
            str(payload.get("status") or ""),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def migrate_events(conn, *, apply: bool, kind: str, path: Path) -> dict:
    merged: dict[str, dict] = {}
    for row in conn.execute("SELECT * FROM event_records WHERE kind = ?", (kind,)).fetchall():
        payload = event_payload(row)
        merged[json.dumps(payload, ensure_ascii=False, sort_keys=True)] = payload
    data = read_json(path, [])
    for payload in data if isinstance(data, list) else []:
        if isinstance(payload, dict):
            merged[json.dumps(payload, ensure_ascii=False, sort_keys=True)] = payload
    if apply:
        conn.execute("DELETE FROM event_records WHERE kind = ?", (kind,))
        for payload in merged.values():
            insert_event(conn, kind, payload)
    return {"total": len(merged), "source": str(path.relative_to(ROOT)), "legacy_count": len(data) if isinstance(data, list) else 0}


def card_item_key(item: dict) -> str:
    return str(item.get("id") or item.get("value") or json.dumps(item, sort_keys=True, ensure_ascii=False))


def migrate_card_pool(conn, *, apply: bool) -> dict:
    from autoteam.card_pool import _ensure_item_defaults, _normalize_pool_type, _normalize_status

    merged: dict[str, dict] = {}
    for row in conn.execute("SELECT * FROM card_pool_items").fetchall():
        try:
            meta = json.loads(row["meta"] or "{}")
        except Exception:
            meta = {}
        item = {
            "id": row["id"],
            "type": row["pool_type"],
            "value": row["value"],
            "provider": row["provider"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "used_by": row["used_by"],
            "used_at": row["used_at"],
            "meta": meta,
        }
        merged[card_item_key(item)] = item
    legacy = read_json(ROOT / "data" / "card_pool.json", {})
    legacy_counts = {}
    for pool_type in ("redeem", "card"):
        rows = legacy.get(pool_type, []) if isinstance(legacy, dict) and isinstance(legacy.get(pool_type), list) else []
        legacy_counts[pool_type] = len(rows)
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item["type"] = pool_type
            merged[card_item_key(item)] = item
    if apply:
        conn.execute("DELETE FROM card_pool_items")
        for raw in merged.values():
            item = _ensure_item_defaults(dict(raw))
            conn.execute(
                """
                INSERT INTO card_pool_items(
                    id, pool_type, value, provider, status, created_at, expires_at,
                    used_by, used_at, meta, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    pool_type=excluded.pool_type,
                    value=excluded.value,
                    provider=excluded.provider,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    used_by=excluded.used_by,
                    used_at=excluded.used_at,
                    meta=excluded.meta,
                    updated_at=excluded.updated_at
                """,
                (
                    str(item.get("id") or card_item_key(item)),
                    _normalize_pool_type(item.get("type") or item.get("pool_type")),
                    str(item.get("value") or "").strip(),
                    str(item.get("provider") or "").strip(),
                    _normalize_status(item.get("status")),
                    item.get("created_at") or time.time(),
                    str(item.get("expires_at") or "").strip(),
                    str(item.get("used_by") or "").strip(),
                    item.get("used_at"),
                    json.dumps(item.get("meta") or {}, ensure_ascii=False),
                    time.time(),
                ),
            )
    return {"total": len(merged), "legacy": legacy_counts}


def migrate_runtime_config(conn, *, apply: bool) -> dict:
    existing = get_json(conn, "runtime_config", "config", default={})
    legacy = read_json(ROOT / "runtime_config.json", {})
    data = {}
    if isinstance(legacy, dict):
        data.update(legacy)
    if isinstance(existing, dict):
        data.update(existing)
    if apply:
        set_json(conn, "runtime_config", "config", data)
    return {"keys": sorted(data.keys())}


def normalize_admin_state(data: dict) -> dict:
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


def migrate_admin_state(conn, *, apply: bool) -> dict:
    existing = get_json(conn, "admin_state", "state", default={})
    legacy = read_json(ROOT / "state.json", {})
    if not isinstance(legacy, dict):
        legacy = {}
    data = normalize_admin_state(legacy)
    if isinstance(existing, dict) and any(existing.values()):
        data.update(normalize_admin_state(existing))
    if apply:
        set_json(conn, "admin_state", "state", data)
    return {"configured": bool(data.get("session_token") and data.get("account_id")), "email_present": bool(data.get("email"))}


def migrate_auth_sessions(conn, *, apply: bool) -> dict:
    merged: dict[str, dict] = {}
    for row in conn.execute("SELECT email, data FROM auth_sessions").fetchall():
        try:
            data = json.loads(row["data"] or "{}")
        except Exception:
            data = {}
        if isinstance(data, dict):
            merged[str(row["email"]).lower()] = data
    session_dir = ROOT / "data" / "auth_session"
    legacy_count = 0
    if session_dir.exists():
        for path in session_dir.glob("*.json"):
            data = read_json(path, {})
            if not isinstance(data, dict) or not data:
                continue
            email = str(data.get("email") or path.stem.replace("_", ".")).strip().lower()
            if "@" not in email:
                continue
            merged[email] = data
            legacy_count += 1
    if apply:
        conn.execute("DELETE FROM auth_sessions")
        for email, data in merged.items():
            conn.execute(
                """
                INSERT INTO auth_sessions(email, file_path, data, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    file_path=excluded.file_path,
                    data=excluded.data,
                    updated_at=excluded.updated_at
                """,
                (email, str(auth_session_target_path(email)), json.dumps(data, ensure_ascii=False), time.time()),
            )
    return {"total": len(merged), "legacy_files": legacy_count}


def migrate_codex_auth_index(conn, *, apply: bool) -> dict:
    auth_dir = ROOT / "data" / "auths"
    count = 0
    if not auth_dir.exists():
        return {"indexed": 0}
    for path in auth_dir.glob("codex-*.json"):
        data = read_json(path, {})
        if not isinstance(data, dict) or not data:
            continue
        if apply:
            payload = dict(data)
            conn.execute(
                """
                INSERT INTO codex_auth_files(
                    file_path, filename, email, account_id, plan_type, is_main, data, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    filename=excluded.filename,
                    email=excluded.email,
                    account_id=excluded.account_id,
                    plan_type=excluded.plan_type,
                    is_main=excluded.is_main,
                    data=excluded.data,
                    updated_at=excluded.updated_at
                """,
                (
                    str(path.resolve()),
                    path.name,
                    str(payload.get("email") or "").strip().lower(),
                    str(payload.get("account_id") or payload.get("accountId") or "").strip(),
                    str(payload.get("plan_type") or payload.get("planType") or "unknown").strip().lower() or "unknown",
                    1 if path.name.startswith("codex-main-") else 0,
                    json.dumps(payload, ensure_ascii=False),
                    time.time(),
                ),
            )
        count += 1
    return {"indexed": count}


def backup_db(db_path: Path) -> str:
    if not db_path.exists():
        return ""
    backup = db_path.with_suffix(f".sqlite3.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(db_path, backup)
    wal = db_path.with_suffix(db_path.suffix + "-wal")
    shm = db_path.with_suffix(db_path.suffix + "-shm")
    if wal.exists():
        shutil.copy2(wal, backup.with_suffix(backup.suffix + "-wal"))
    if shm.exists():
        shutil.copy2(shm, backup.with_suffix(backup.suffix + "-shm"))
    return str(backup)


def verify(conn) -> dict:
    account_rows = conn.execute(
        "SELECT account_type, status, COUNT(*) AS n FROM accounts GROUP BY account_type, status"
    ).fetchall()
    summary = {}
    for row in account_rows:
        summary[f"{row['account_type']}:{row['status']}"] = row["n"]
    return {
        "accounts_total": conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
        "accounts_by_type_status": summary,
        "auth_sessions": conn.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0],
        "codex_auth_files": conn.execute("SELECT COUNT(*) FROM codex_auth_files").fetchone()[0],
        "card_pool_items": conn.execute("SELECT COUNT(*) FROM card_pool_items").fetchone()[0],
        "bind_audits": conn.execute("SELECT COUNT(*) FROM event_records WHERE kind = 'bind_audit'").fetchone()[0],
        "register_failures": conn.execute("SELECT COUNT(*) FROM event_records WHERE kind = 'register_failure'").fetchone()[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate AutoTeam legacy JSON data into SQLite")
    parser.add_argument("--apply", action="store_true", help="write changes; omit for dry-run")
    parser.add_argument("--no-backup", action="store_true", help="do not create a DB backup before writing")
    args = parser.parse_args()

    db_path = sqlite_store.default_db_path()
    if args.apply and not args.no_backup:
        backup = backup_db(db_path)
        if backup:
            print(f"[OK] SQLite 备份: {backup}")

    sqlite_store.initialize(db_path)
    with sqlite_store.connect(db_path) as conn:
        report = {
            "accounts": migrate_accounts(conn, apply=args.apply),
            "auth_sessions": migrate_auth_sessions(conn, apply=args.apply),
            "codex_auth_files": migrate_codex_auth_index(conn, apply=args.apply),
            "runtime_config": migrate_runtime_config(conn, apply=args.apply),
            "admin_state": migrate_admin_state(conn, apply=args.apply),
            "card_pool": migrate_card_pool(conn, apply=args.apply),
            "bind_audit": migrate_events(conn, apply=args.apply, kind="bind_audit", path=ROOT / "bind_audit.json"),
            "register_failures": migrate_events(
                conn,
                apply=args.apply,
                kind="register_failure",
                path=ROOT / "register_failures.json",
            ),
        }
        final = verify(conn)

    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "report": report, "verify": final}, ensure_ascii=False, indent=2))
    if not args.apply:
        print("[INFO] 当前为 dry-run。确认报告无误后运行: python scripts/migrate_to_sqlite.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
