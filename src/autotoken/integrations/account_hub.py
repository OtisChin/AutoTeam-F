"""Remote account Hub sync helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from autotoken.core.files import read_lines_file
from autotoken.core.normalization import normalized_email
from autotoken.core.paths import PROJECT_ROOT
from autotoken.core.textio import write_text
from autotoken.settings.runtime_config import get, set_value
from autotoken.storage.auth_files import (
    iter_auth_files_for_email,
    iter_codex_auth_files,
    read_auth_json_file,
    trusted_auth_file_path,
)
from autotoken.storage.auth_index import upsert_codex_auth_file
from autotoken.storage.auth_storage import AUTH_DIR, ensure_auth_file_permissions

logger = logging.getLogger(__name__)

CONFIG_KEY = "account_hub"
AUTO_UPLOAD_INTERVAL_SECONDS = 300
SYNC_ACCOUNT_TYPES = {"plus", "team", "pro"}
SYNC_EXCLUDED_STATUSES = {"fail", "auth_invalid", "orphan", "exhausted", "standby", "pending"}
LUCKMAIL_PURCHASES_PATH = "/api/v1/openapi/email/purchases"
LUCKMAIL_TOKEN_LOOKUP_MAX_PAGES = 30
LUCKMAIL_TOKEN_LOOKUP_PAGE_SIZE = 100


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or str(default))
    except (TypeError, ValueError):
        return default
    return max(1, value)


UPLOAD_BATCH_MAX_ACCOUNTS = _positive_int_env("ACCOUNT_HUB_UPLOAD_BATCH_MAX_ACCOUNTS", 25)
UPLOAD_BATCH_MAX_BYTES = _positive_int_env("ACCOUNT_HUB_UPLOAD_BATCH_MAX_BYTES", 900 * 1024)

_auto_upload_stop = threading.Event()
_auto_upload_lock = threading.Lock()
_auto_upload_thread_lock = threading.Lock()
_auto_upload_thread: threading.Thread | None = None
_luckmail_purchase_cache_lock = threading.Lock()
_luckmail_purchase_cache: tuple[float, dict[str, str]] | None = None


def _normalize_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url, re.I):
        url = f"http://{url}"
    return url


def _normalized_email(value) -> str:
    return normalized_email(value)


def default_node_name() -> str:
    try:
        return socket.gethostname() or "autotoken-node"
    except Exception:
        return "autotoken-node"


def normalize_config(raw: dict | None = None) -> dict:
    data = raw if isinstance(raw, dict) else {}
    return {
        "url": _normalize_url(data.get("url") or ""),
        "token": str(data.get("token") or "").strip(),
        "name": str(data.get("name") or "").strip() or default_node_name(),
        "auto_upload": bool(data.get("auto_upload")),
    }


def get_config() -> dict:
    return normalize_config(get(CONFIG_KEY) or {})


def set_config(config: dict) -> dict:
    saved = normalize_config(config)
    set_value(CONFIG_KEY, saved)
    return saved


def _auth_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Account-Hub-Token": token,
    }


def _hub_endpoint(base_url: str, path: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def test_connection(config: dict | None = None, *, timeout: int = 20) -> dict:
    cfg = normalize_config(config or get_config())
    if not cfg["url"]:
        raise ValueError("远程 Hub URL 不能为空")
    if not cfg["token"]:
        raise ValueError("远程 Hub Token 不能为空")
    resp = requests.post(
        _hub_endpoint(cfg["url"], "/api/account-hub/ping"),
        headers=_auth_headers(cfg["token"]),
        json={"name": cfg["name"], "time": time.time()},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Hub 连接失败: HTTP {resp.status_code} {resp.text[:300]}")
    payload = resp.json()
    return {
        "ok": True,
        "message": payload.get("message") or "Hub 连接成功",
        "hub": payload,
    }


def _safe_auth_filename(name: str) -> str:
    filename = Path(str(name or "")).name
    if not filename.endswith(".json") or not filename.startswith("codex-"):
        filename = ""
    return filename


def _auth_file_index_for_emails(emails: list[str] | set[str] | tuple[str, ...]) -> dict[str, list[Path]]:
    wanted = sorted({_normalized_email(email) for email in emails if _normalized_email(email)}, key=len, reverse=True)
    indexed = {email: [] for email in wanted}
    if not wanted:
        return indexed

    prefixes = [(email, f"codex-{email}-") for email in wanted]
    for path in iter_codex_auth_files(auth_dir=AUTH_DIR):
        name = path.name.lower()
        for email, prefix in prefixes:
            if name.startswith(prefix):
                indexed[email].append(path)
                break
    return indexed


def _auth_file_index_for_accounts(accounts: list[dict]) -> dict[str, list[Path]]:
    return _auth_file_index_for_emails(
        [
            str(acc.get("email") or "")
            for acc in accounts
            if isinstance(acc, dict) and str(acc.get("email") or "").strip()
        ]
    )


def _auth_candidates_for_account(acc: dict, auth_files_by_email: dict[str, list[Path]] | None = None) -> list[Path]:
    email = str(acc.get("email") or "").strip()
    candidates: list[Path] = []
    auth_file = str(acc.get("auth_file") or "").strip()
    if auth_file:
        path = Path(auth_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        candidates.append(path)
    if email:
        indexed = (auth_files_by_email or {}).get(_normalized_email(email))
        if indexed is not None:
            candidates.extend(indexed)
        else:
            candidates.extend(iter_auth_files_for_email(email, auth_dir=AUTH_DIR))
    out: list[Path] = []
    seen = set()
    for path in candidates:
        try:
            trusted = trusted_auth_file_path(path, auth_dir=AUTH_DIR)
            if trusted is None:
                continue
            resolved = trusted.resolve()
        except Exception:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _is_syncable_account(acc: dict, auth_files_by_email: dict[str, list[Path]] | None = None) -> bool:
    if bool(acc.get("account_hub_synced")):
        return False
    account_type = str(acc.get("account_type") or "").strip().lower()
    status = str(acc.get("status") or "").strip().lower()
    if status in SYNC_EXCLUDED_STATUSES:
        return False
    if account_type not in SYNC_ACCOUNT_TYPES and status != "plus":
        return False
    return bool(_auth_candidates_for_account(acc, auth_files_by_email))


def _syncable_accounts(accounts: list[dict], auth_files_by_email: dict[str, list[Path]] | None = None) -> list[dict]:
    return [acc for acc in accounts if isinstance(acc, dict) and _is_syncable_account(acc, auth_files_by_email)]


def _filter_accounts_by_emails(accounts: list[dict], selected_emails: list[str] | None) -> list[dict]:
    if selected_emails is None:
        return accounts
    wanted = []
    seen = set()
    for value in selected_emails:
        email = _normalized_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        wanted.append(email)
    if not wanted:
        return []
    by_email = {
        _normalized_email(acc.get("email")): acc
        for acc in accounts
        if isinstance(acc, dict) and _normalized_email(acc.get("email"))
    }
    return [by_email[email] for email in wanted if email in by_email]


def _parse_luckmail_account_line(line: str) -> tuple[str, str] | None:
    value = str(line or "").strip()
    if not value or value.startswith("#"):
        return None
    if "----" in value:
        parts = [part.strip() for part in value.split("----")]
    elif "," in value:
        parts = [part.strip() for part in value.split(",")]
    else:
        parts = [part.strip() for part in value.split()]
    email = _normalized_email(parts[0] if parts else "")
    token = str(parts[1] if len(parts) > 1 else "").strip()
    if "@" not in email or not token:
        return None
    return email, token


def _luckmail_tokens_by_email() -> dict[str, str]:
    raw = str(os.environ.get("LUCKMAIL_ACCOUNTS") or "")
    file_value = str(os.environ.get("LUCKMAIL_ACCOUNTS_FILE") or "").strip()
    candidates: list[Path] = []
    if file_value:
        path = Path(file_value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        candidates.append(path)
    else:
        candidates.append(PROJECT_ROOT / "data" / "luckmail_accounts.txt")

    for path in candidates:
        try:
            if path.exists():
                raw += ("\n" if raw else "") + "\n".join(read_lines_file(path))
        except Exception as exc:
            logger.warning("[account_hub] 读取 LuckMail token 文件失败 %s: %s", path, exc)

    tokens: dict[str, str] = {}
    for line in raw.replace(";", "\n").splitlines():
        parsed = _parse_luckmail_account_line(line)
        if not parsed:
            continue
        email, token = parsed
        tokens.setdefault(email, token)
    return tokens


def _is_luckmail_token_missing(acc: dict) -> bool:
    email = _normalized_email(acc.get("email"))
    if "@" not in email:
        return False
    token = str(acc.get("cloudmail_account_id") or "").strip()
    if token.startswith("tok_"):
        return False
    provider = str(acc.get("mail_provider") or "").strip().lower()
    return provider == "luckmail"


def _purchase_item_to_luckmail_token(item: dict) -> tuple[str, str] | None:
    email = _normalized_email(item.get("email_address") or item.get("address") or item.get("email"))
    token = str(item.get("token") or "").strip()
    if "@" not in email or not token.startswith("tok_"):
        return None
    return email, token


def _luckmail_purchase_tokens_by_email(*, force: bool = False) -> dict[str, str]:
    global _luckmail_purchase_cache
    api_key = str(os.environ.get("LUCKMAIL_API_KEY") or "").strip()
    if not api_key:
        return {}
    now = time.time()
    with _luckmail_purchase_cache_lock:
        if not force and _luckmail_purchase_cache and now - _luckmail_purchase_cache[0] < 300:
            return dict(_luckmail_purchase_cache[1])

    base_url = str(os.environ.get("LUCKMAIL_BASE_URL") or "https://mail.luckyous.com").strip().rstrip("/")
    tokens: dict[str, str] = {}
    total = 0
    for page in range(1, LUCKMAIL_TOKEN_LOOKUP_MAX_PAGES + 1):
        resp = requests.get(
            f"{base_url}{LUCKMAIL_PURCHASES_PATH}",
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            params={"page": page, "page_size": LUCKMAIL_TOKEN_LOOKUP_PAGE_SIZE},
            timeout=45,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"LuckMail 购买记录接口失败: HTTP {resp.status_code} {(resp.text or '')[:300]}")
        body = resp.json() or {}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        items = data.get("list") if isinstance(data.get("list"), list) else []
        if not items:
            break
        if not total:
            try:
                total = int(data.get("total") or 0)
            except Exception:
                total = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            parsed = _purchase_item_to_luckmail_token(item)
            if parsed:
                email, token = parsed
                tokens.setdefault(email, token)
        if total and page * LUCKMAIL_TOKEN_LOOKUP_PAGE_SIZE >= total:
            break

    with _luckmail_purchase_cache_lock:
        _luckmail_purchase_cache = (time.time(), dict(tokens))
    return tokens


def _restore_luckmail_tokens_for_accounts(accounts: list[dict]) -> int:
    missing = [
        _normalized_email(acc.get("email"))
        for acc in accounts
        if isinstance(acc, dict) and _is_luckmail_token_missing(acc)
    ]
    missing = [email for email in dict.fromkeys(missing) if email]
    if not missing:
        return 0

    tokens = _luckmail_tokens_by_email()
    missing_after_local = [email for email in missing if not tokens.get(email)]
    if missing_after_local:
        try:
            tokens.update(_luckmail_purchase_tokens_by_email())
        except Exception as exc:
            logger.warning(
                "[account_hub] 从 LuckMail 购买记录恢复 token 失败: missing=%s error=%s", len(missing_after_local), exc
            )

    restored = 0
    for acc in accounts:
        if not isinstance(acc, dict) or not _is_luckmail_token_missing(acc):
            continue
        email = _normalized_email(acc.get("email"))
        token = tokens.get(email, "")
        if not token:
            continue
        acc["cloudmail_account_id"] = token
        acc["mail_provider"] = "luckmail"
        restored += 1
    if restored:
        logger.info("[account_hub] 已自动恢复 LuckMail token: restored=%s missing_before=%s", restored, len(missing))
    return restored


def _account_payload_for_hub(acc: dict, luckmail_tokens: dict[str, str]) -> dict:
    payload = dict(acc)
    # Export state is local to the machine doing the export. Do not propagate it
    # through Hub sync, otherwise newly received accounts look already exported.
    payload.pop("credentials_exported", None)
    payload.pop("credentials_exported_at", None)
    email = _normalized_email(payload.get("email"))
    if email:
        payload["email"] = email

    cloudmail_account_id = str(payload.get("cloudmail_account_id") or "").strip()
    token = cloudmail_account_id if cloudmail_account_id.startswith("tok_") else ""
    if not token and email:
        token = luckmail_tokens.get(email, "")
    if token:
        payload["cloudmail_account_id"] = token
        if not str(payload.get("mail_provider") or "").strip():
            payload["mail_provider"] = "luckmail"
    return payload


def _normalize_plus_auth_plan_types_for_hub(
    accounts: list[dict],
    auth_files_by_email: dict[str, list[Path]] | None = None,
) -> int:
    try:
        from autotoken.integrations.cpa_sync import update_local_auth_plan_type
        from autotoken.storage.accounts import update_account
    except Exception:
        return 0

    updated = 0
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        email = _normalized_email(acc.get("email"))
        if not email:
            continue
        account_type = str(acc.get("account_type") or "").strip().lower()
        status = str(acc.get("status") or "").strip().lower()
        if account_type != "plus" and status != "plus":
            continue
        try:
            result = update_local_auth_plan_type(
                email,
                str(acc.get("auth_file") or ""),
                plan_type="plus",
                candidate_paths=_auth_candidates_for_account(acc, auth_files_by_email),
            )
        except Exception as exc:
            logger.warning("[account_hub] 修正 Plus auth plan_type 失败: email=%s error=%s", email, exc)
            continue
        auth_file = str(result.get("auth_file") or "").strip()
        if result.get("status") == "updated" and auth_file and auth_file != str(acc.get("auth_file") or ""):
            acc["auth_file"] = auth_file
            try:
                update_account(email, auth_file=auth_file)
            except Exception as exc:
                logger.warning("[account_hub] 保存 Plus auth_file 路径失败: email=%s error=%s", email, exc)
            updated += 1
    return updated


def build_upload_payload(
    *,
    node_name: str | None = None,
    syncable_only: bool = False,
    selected_emails: list[str] | None = None,
) -> dict:
    from autotoken.storage.accounts import load_accounts

    name = str(node_name or get_config().get("name") or default_node_name()).strip() or default_node_name()
    accounts = load_accounts()
    accounts = _filter_accounts_by_emails(accounts, selected_emails)
    auth_files_by_email = _auth_file_index_for_accounts(accounts)
    if syncable_only:
        accounts = _syncable_accounts(accounts, auth_files_by_email)
    _normalize_plus_auth_plan_types_for_hub(accounts, auth_files_by_email)
    restored = _restore_luckmail_tokens_for_accounts(accounts)
    if restored:
        from autotoken.storage.accounts import save_accounts

        all_accounts = load_accounts()
        restored_by_email = {
            _normalized_email(acc.get("email")): acc
            for acc in accounts
            if isinstance(acc, dict) and _normalized_email(acc.get("email"))
        }
        for acc in all_accounts:
            email = _normalized_email(acc.get("email"))
            restored_acc = restored_by_email.get(email)
            if restored_acc:
                acc["cloudmail_account_id"] = restored_acc.get("cloudmail_account_id")
                acc["mail_provider"] = restored_acc.get("mail_provider")
        save_accounts(all_accounts)
    luckmail_tokens = _luckmail_tokens_by_email()
    accounts_payload = [_account_payload_for_hub(acc, luckmail_tokens) for acc in accounts]
    auth_files_by_email = _auth_file_index_for_accounts(accounts_payload)
    auths = []
    for acc in accounts_payload:
        email = _normalized_email(acc.get("email"))
        for path in _auth_candidates_for_account(acc, auth_files_by_email):
            try:
                data = read_auth_json_file(path)
            except Exception as exc:
                logger.warning("[account_hub] 跳过无法读取的 auth 文件 %s: %s", path, exc)
                continue
            auths.append({"email": email, "filename": path.name, "data": data})
    auth_sessions = []
    try:
        from autotoken.storage.auth_session_store import load_auth_session
    except Exception:
        load_auth_session = None
    if load_auth_session:
        for acc in accounts_payload:
            email = _normalized_email(acc.get("email"))
            if not email:
                continue
            try:
                data = load_auth_session(email)
            except Exception as exc:
                logger.warning("[account_hub] 跳过无法读取的 auth_session %s: %s", email, exc)
                continue
            if isinstance(data, dict) and data:
                auth_sessions.append({"email": email, "data": data})
    return {
        "source": {
            "name": name,
            "uploaded_at": time.time(),
        },
        "accounts": accounts_payload,
        "auths": auths,
        "auth_sessions": auth_sessions,
    }


def _payload_size_bytes(payload: dict) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return UPLOAD_BATCH_MAX_BYTES + 1


def _copy_payload_with_items(payload: dict, accounts: list[dict], auths: list[dict], auth_sessions: list[dict]) -> dict:
    return {
        "source": dict(payload.get("source") or {}),
        "accounts": accounts,
        "auths": auths,
        "auth_sessions": auth_sessions,
    }


def _split_upload_payload_batches(payload: dict) -> list[dict]:
    accounts = [item for item in payload.get("accounts") or [] if isinstance(item, dict)]
    if not accounts:
        return [_copy_payload_with_items(payload, [], [], [])]

    auths_by_email: dict[str, list[dict]] = {}
    for item in payload.get("auths") or []:
        if not isinstance(item, dict):
            continue
        auths_by_email.setdefault(_normalized_email(item.get("email")), []).append(item)

    sessions_by_email: dict[str, list[dict]] = {}
    for item in payload.get("auth_sessions") or []:
        if not isinstance(item, dict):
            continue
        sessions_by_email.setdefault(_normalized_email(item.get("email")), []).append(item)

    batches: list[dict] = []
    current_accounts: list[dict] = []
    current_auths: list[dict] = []
    current_sessions: list[dict] = []

    for account in accounts:
        email = _normalized_email(account.get("email"))
        account_auths = auths_by_email.get(email, [])
        account_sessions = sessions_by_email.get(email, [])
        candidate = _copy_payload_with_items(
            payload,
            [*current_accounts, account],
            [*current_auths, *account_auths],
            [*current_sessions, *account_sessions],
        )
        account_limit_reached = len(current_accounts) >= max(1, UPLOAD_BATCH_MAX_ACCOUNTS)
        size_limit_reached = current_accounts and _payload_size_bytes(candidate) > max(1, UPLOAD_BATCH_MAX_BYTES)
        if account_limit_reached or size_limit_reached:
            batches.append(_copy_payload_with_items(payload, current_accounts, current_auths, current_sessions))
            current_accounts = [account]
            current_auths = list(account_auths)
            current_sessions = list(account_sessions)
        else:
            current_accounts.append(account)
            current_auths.extend(account_auths)
            current_sessions.extend(account_sessions)

    if current_accounts:
        batches.append(_copy_payload_with_items(payload, current_accounts, current_auths, current_sessions))

    total = len(batches)
    for index, batch in enumerate(batches, start=1):
        batch["source"]["batch_index"] = index
        batch["source"]["batch_count"] = total
    return batches


def _mark_accounts_synced(accounts_payload: list[dict], *, synced_at: float | None = None):
    from autotoken.storage.accounts import find_account, load_accounts, save_accounts

    emails = []
    seen = set()
    for acc in accounts_payload:
        email = _normalized_email(acc.get("email")) if isinstance(acc, dict) else ""
        if not email or email in seen:
            continue
        seen.add(email)
        emails.append(email)
    if not emails:
        return 0

    accounts = load_accounts()
    now = float(synced_at or time.time())
    updated = 0
    for email in emails:
        acc = find_account(accounts, email)
        if not acc:
            continue
        acc["account_hub_synced"] = True
        acc["account_hub_synced_at"] = now
        updated += 1
    if updated:
        save_accounts(accounts)
    return updated


def upload_to_hub(
    config: dict | None = None,
    *,
    syncable_only: bool = False,
    selected_emails: list[str] | None = None,
) -> dict:
    cfg = normalize_config(config or get_config())
    if not cfg["url"]:
        raise ValueError("远程 Hub URL 不能为空")
    if not cfg["token"]:
        raise ValueError("远程 Hub Token 不能为空")
    payload = build_upload_payload(
        node_name=cfg["name"],
        syncable_only=syncable_only,
        selected_emails=selected_emails,
    )
    batches = _split_upload_payload_batches(payload)
    totals = {
        "uploaded_accounts": 0,
        "uploaded_auths": 0,
        "uploaded_auth_sessions": 0,
        "marked_synced_accounts": 0,
        "batch_count": len(batches),
        "syncable_only": syncable_only,
    }
    endpoint = _hub_endpoint(cfg["url"], "/api/account-hub/ingest")
    headers = _auth_headers(cfg["token"])
    for index, batch in enumerate(batches, start=1):
        resp = requests.post(
            endpoint,
            headers=headers,
            json=batch,
            timeout=60,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"上传到账号 Hub 失败: batch={index}/{len(batches)} HTTP {resp.status_code} {resp.text[:500]}"
            )
        try:
            resp.json()
        except Exception:
            pass
        marked = _mark_accounts_synced(
            batch.get("accounts") or [],
            synced_at=float(batch.get("source", {}).get("uploaded_at") or time.time()),
        )
        totals["uploaded_accounts"] += len(batch.get("accounts") or [])
        totals["uploaded_auths"] += len(batch.get("auths") or [])
        totals["uploaded_auth_sessions"] += len(batch.get("auth_sessions") or [])
        totals["marked_synced_accounts"] += marked
    return totals


def auto_upload_if_enabled(reason: str = "") -> dict | None:
    cfg = get_config()
    if not cfg.get("auto_upload"):
        return None
    if not cfg.get("url") or not cfg.get("token"):
        logger.warning("[account_hub] 已开启自动上传，但 URL 或 token 未配置")
        return None
    if not _auto_upload_lock.acquire(blocking=False):
        logger.info("[account_hub] 上一次自动上传仍在进行，跳过本轮: reason=%s", reason)
        return None
    try:
        result = upload_to_hub(cfg, syncable_only=True)
        logger.info(
            "[account_hub] 自动上传完成: reason=%s uploaded=%s auths=%s",
            reason,
            result.get("uploaded_accounts", result.get("received_accounts")),
            result.get("uploaded_auths", result.get("received_auths")),
        )
        return result
    except Exception as exc:
        logger.warning("[account_hub] 自动上传失败: reason=%s error=%s", reason, exc)
        return None
    finally:
        _auto_upload_lock.release()


def _auto_upload_loop(interval_seconds: int = AUTO_UPLOAD_INTERVAL_SECONDS):
    logger.info("[account_hub] 自动上传线程已启动: interval=%ss", interval_seconds)
    while not _auto_upload_stop.wait(interval_seconds):
        auto_upload_if_enabled(reason="periodic")
    logger.info("[account_hub] 自动上传线程已停止")


def start_auto_upload_loop(interval_seconds: int = AUTO_UPLOAD_INTERVAL_SECONDS):
    global _auto_upload_thread
    with _auto_upload_thread_lock:
        if _auto_upload_thread and _auto_upload_thread.is_alive():
            return
        _auto_upload_stop.clear()
        _auto_upload_thread = threading.Thread(
            target=_auto_upload_loop,
            args=(max(60, int(interval_seconds or AUTO_UPLOAD_INTERVAL_SECONDS)),),
            daemon=True,
            name="account-hub-auto-upload",
        )
        _auto_upload_thread.start()


def stop_auto_upload_loop():
    _auto_upload_stop.set()


def expected_inbound_token() -> str:
    return str(get_config().get("token") or "").strip()


def receive_payload(payload: dict) -> dict:
    from autotoken.storage.accounts import find_account, load_accounts, save_accounts

    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 JSON object")
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    source_name = str(source.get("name") or "unknown").strip() or "unknown"
    uploaded_at = float(source.get("uploaded_at") or time.time())
    incoming_accounts = payload.get("accounts") if isinstance(payload.get("accounts"), list) else []
    incoming_auths = payload.get("auths") if isinstance(payload.get("auths"), list) else []
    incoming_auth_sessions = payload.get("auth_sessions") if isinstance(payload.get("auth_sessions"), list) else []

    accounts = load_accounts()
    upserted = 0
    skipped = 0
    for raw in incoming_accounts:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        email = _normalized_email(raw.get("email"))
        if not email:
            skipped += 1
            continue
        incoming = dict(raw)
        incoming["email"] = email
        incoming_token = str(incoming.get("cloudmail_account_id") or "").strip()
        if incoming_token.startswith("tok_") and not str(incoming.get("mail_provider") or "").strip():
            incoming["mail_provider"] = "luckmail"
        incoming["hub_source_name"] = source_name
        incoming["hub_uploaded_at"] = uploaded_at
        incoming["hub_received_at"] = time.time()
        incoming["account_hub_synced"] = True
        incoming["account_hub_synced_at"] = uploaded_at
        incoming.pop("credentials_exported", None)
        incoming.pop("credentials_exported_at", None)
        existing = find_account(accounts, email)
        if existing:
            exported = bool(existing.get("credentials_exported"))
            exported_at = existing.get("credentials_exported_at")
            if not incoming_token and existing.get("cloudmail_account_id"):
                incoming.pop("cloudmail_account_id", None)
            if not str(incoming.get("mail_provider") or "").strip() and existing.get("mail_provider"):
                incoming.pop("mail_provider", None)
            existing.update(incoming)
            existing["credentials_exported"] = exported
            existing["credentials_exported_at"] = exported_at if exported else None
        else:
            incoming["credentials_exported"] = False
            incoming["credentials_exported_at"] = None
            accounts.append(incoming)
        upserted += 1
    save_accounts(accounts)

    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    saved_auths = 0
    saved_auth_by_email: dict[str, str] = {}
    for item in incoming_auths:
        if not isinstance(item, dict):
            continue
        filename = _safe_auth_filename(str(item.get("filename") or ""))
        data = item.get("data")
        if not filename or not isinstance(data, dict):
            continue
        path = AUTH_DIR / filename
        write_text(path, json.dumps(data, indent=2, ensure_ascii=False))
        ensure_auth_file_permissions(path)
        try:
            upsert_codex_auth_file(path, data, main=filename.startswith("codex-main-"))
        except Exception as exc:
            logger.warning("[AccountHub] SQLite auth 索引写入失败: %s", exc)
        email = _normalized_email(item.get("email") or data.get("email"))
        if email:
            saved_auth_by_email[email] = str(path)
        saved_auths += 1
    if saved_auth_by_email:
        updated_auth_file = 0
        for acc in accounts:
            email = _normalized_email(acc.get("email"))
            auth_file = saved_auth_by_email.get(email)
            if not auth_file:
                continue
            acc["auth_file"] = auth_file
            updated_auth_file += 1
        if updated_auth_file:
            save_accounts(accounts)

    saved_auth_sessions = 0
    if incoming_auth_sessions:
        try:
            from autotoken.storage.auth_session_store import save_auth_session
        except Exception:
            save_auth_session = None
        if save_auth_session:
            for item in incoming_auth_sessions:
                if not isinstance(item, dict):
                    continue
                email = _normalized_email(item.get("email"))
                data = item.get("data")
                if not email or not isinstance(data, dict):
                    continue
                save_auth_session(email, data)
                saved_auth_sessions += 1

    return {
        "message": f"账号 Hub 已接收 {upserted} 个账号，{saved_auths} 个认证文件，{saved_auth_sessions} 个 auth_session",
        "source_name": source_name,
        "received_accounts": upserted,
        "skipped_accounts": skipped,
        "received_auths": saved_auths,
        "received_auth_sessions": saved_auth_sessions,
    }
