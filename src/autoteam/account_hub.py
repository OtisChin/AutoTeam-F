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

from autoteam.auth_storage import AUTH_DIR, ensure_auth_dir, ensure_auth_file_permissions
from autoteam.paths import PROJECT_ROOT
from autoteam.runtime_config import get, set_value
from autoteam.textio import read_text, write_text

logger = logging.getLogger(__name__)

CONFIG_KEY = "account_hub"
AUTO_UPLOAD_INTERVAL_SECONDS = 300
SYNC_ACCOUNT_TYPES = {"plus", "team", "pro"}
SYNC_EXCLUDED_STATUSES = {"fail", "auth_invalid", "orphan"}
LUCKMAIL_PURCHASES_PATH = "/api/v1/openapi/email/purchases"
LUCKMAIL_TOKEN_LOOKUP_MAX_PAGES = 30
LUCKMAIL_TOKEN_LOOKUP_PAGE_SIZE = 100

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


def default_node_name() -> str:
    try:
        return socket.gethostname() or "autoteam-node"
    except Exception:
        return "autoteam-node"


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


def _auth_candidates_for_account(acc: dict) -> list[Path]:
    email = str(acc.get("email") or "").strip()
    candidates: list[Path] = []
    auth_file = str(acc.get("auth_file") or "").strip()
    if auth_file:
        path = Path(auth_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        candidates.append(path)
    if email:
        candidates.extend(AUTH_DIR.glob(f"codex-{email}-*.json"))
    out: list[Path] = []
    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(AUTH_DIR.resolve())
        except Exception:
            continue
        if not resolved.is_file() or resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _is_syncable_account(acc: dict) -> bool:
    if bool(acc.get("account_hub_synced")):
        return False
    account_type = str(acc.get("account_type") or "").strip().lower()
    status = str(acc.get("status") or "").strip().lower()
    if status in SYNC_EXCLUDED_STATUSES:
        return False
    if account_type in SYNC_ACCOUNT_TYPES:
        return True
    # 兼容旧数据：早期 GoPay 成功只写 status=plus。
    return status == "plus"


def _syncable_accounts(accounts: list[dict]) -> list[dict]:
    return [acc for acc in accounts if isinstance(acc, dict) and _is_syncable_account(acc)]


def _filter_accounts_by_emails(accounts: list[dict], selected_emails: list[str] | None) -> list[dict]:
    if selected_emails is None:
        return accounts
    wanted = []
    seen = set()
    for value in selected_emails:
        email = str(value or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        wanted.append(email)
    if not wanted:
        return []
    by_email = {
        str(acc.get("email") or "").strip().lower(): acc
        for acc in accounts
        if isinstance(acc, dict) and str(acc.get("email") or "").strip()
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
    email = str(parts[0] if parts else "").strip().lower()
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
                raw += ("\n" if raw else "") + read_text(path)
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
    email = str(acc.get("email") or "").strip().lower()
    if "@" not in email:
        return False
    token = str(acc.get("cloudmail_account_id") or "").strip()
    if token.startswith("tok_"):
        return False
    provider = str(acc.get("mail_provider") or "").strip().lower()
    if provider == "luckmail":
        return True
    domain = email.rsplit("@", 1)[-1]
    return domain.startswith("outlook.") or domain in {"outlook.com", "hotmail.com", "live.com"}


def _purchase_item_to_luckmail_token(item: dict) -> tuple[str, str] | None:
    email = str(item.get("email_address") or item.get("address") or item.get("email") or "").strip().lower()
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
        str(acc.get("email") or "").strip().lower()
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
            logger.warning("[account_hub] 从 LuckMail 购买记录恢复 token 失败: missing=%s error=%s", len(missing_after_local), exc)

    restored = 0
    for acc in accounts:
        if not isinstance(acc, dict) or not _is_luckmail_token_missing(acc):
            continue
        email = str(acc.get("email") or "").strip().lower()
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
    email = str(payload.get("email") or "").strip().lower()
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


def build_upload_payload(
    *,
    node_name: str | None = None,
    syncable_only: bool = False,
    selected_emails: list[str] | None = None,
) -> dict:
    from autoteam.accounts import load_accounts

    name = str(node_name or get_config().get("name") or default_node_name()).strip() or default_node_name()
    accounts = load_accounts()
    restored = _restore_luckmail_tokens_for_accounts(accounts)
    if restored:
        from autoteam.accounts import save_accounts

        save_accounts(accounts)
    accounts = _filter_accounts_by_emails(accounts, selected_emails)
    if syncable_only:
        accounts = _syncable_accounts(accounts)
    luckmail_tokens = _luckmail_tokens_by_email()
    accounts_payload = [_account_payload_for_hub(acc, luckmail_tokens) for acc in accounts]
    auths = []
    for acc in accounts_payload:
        email = str(acc.get("email") or "").strip().lower()
        for path in _auth_candidates_for_account(acc):
            try:
                data = json.loads(read_text(path))
            except Exception as exc:
                logger.warning("[account_hub] 跳过无法读取的 auth 文件 %s: %s", path, exc)
                continue
            auths.append({"email": email, "filename": path.name, "data": data})
    auth_sessions = []
    try:
        from autoteam.auth_session_store import load_auth_session
    except Exception:
        load_auth_session = None
    if load_auth_session:
        for acc in accounts_payload:
            email = str(acc.get("email") or "").strip().lower()
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


def _mark_accounts_synced(accounts_payload: list[dict], *, synced_at: float | None = None):
    from autoteam.accounts import find_account, load_accounts, save_accounts

    emails = []
    seen = set()
    for acc in accounts_payload:
        email = str(acc.get("email") or "").strip().lower() if isinstance(acc, dict) else ""
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
    resp = requests.post(
        _hub_endpoint(cfg["url"], "/api/account-hub/ingest"),
        headers=_auth_headers(cfg["token"]),
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"上传到账号 Hub 失败: HTTP {resp.status_code} {resp.text[:500]}")
    result = resp.json()
    marked = _mark_accounts_synced(
        payload.get("accounts") or [],
        synced_at=float(payload.get("source", {}).get("uploaded_at") or time.time()),
    )
    result.setdefault("uploaded_accounts", len(payload.get("accounts") or []))
    result.setdefault("uploaded_auths", len(payload.get("auths") or []))
    result.setdefault("uploaded_auth_sessions", len(payload.get("auth_sessions") or []))
    result.setdefault("marked_synced_accounts", marked)
    result.setdefault("syncable_only", syncable_only)
    return result


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
    from autoteam.accounts import find_account, load_accounts, save_accounts

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
        email = str(raw.get("email") or "").strip().lower()
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
        email = str(item.get("email") or data.get("email") or "").strip().lower()
        if email:
            saved_auth_by_email[email] = str(path)
        saved_auths += 1
    if saved_auth_by_email:
        updated_auth_file = 0
        for acc in accounts:
            email = str(acc.get("email") or "").strip().lower()
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
            from autoteam.auth_session_store import save_auth_session
        except Exception:
            save_auth_session = None
        if save_auth_session:
            for item in incoming_auth_sessions:
                if not isinstance(item, dict):
                    continue
                email = str(item.get("email") or "").strip().lower()
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
