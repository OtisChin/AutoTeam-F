"""CPA (CLIProxyAPI) 认证文件同步 - 保持本地 codex 认证文件与 CPA 一致"""

import base64
import json
import logging
import time
from datetime import datetime
from hashlib import md5
from pathlib import Path

import requests

from autoteam.auth_index import delete_codex_auth_file, upsert_codex_auth_file
from autoteam.auth_storage import AUTH_DIR, ensure_auth_dir, ensure_auth_file_permissions
from autoteam.config import CPA_KEY, CPA_URL
from autoteam.textio import read_text, write_text

logger = logging.getLogger(__name__)


def _headers():
    return {"Authorization": f"Bearer {CPA_KEY}"}


def list_cpa_files():
    """获取 CPA 中所有认证文件"""
    resp = requests.get(f"{CPA_URL}/v0/management/auth-files", headers=_headers(), timeout=10)
    if resp.status_code != 200:
        logger.error("[CPA] 获取文件列表失败: %d", resp.status_code)
        return []
    data = resp.json()
    return data.get("files", [])


def upload_to_cpa(filepath):
    """上传认证文件到 CPA"""
    filepath = Path(filepath)
    if not filepath.exists():
        logger.warning("[CPA] 文件不存在: %s", filepath)
        return False

    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{CPA_URL}/v0/management/auth-files",
            headers=_headers(),
            files={"file": (filepath.name, f, "application/json")},
            timeout=10,
        )

    if resp.status_code == 200:
        logger.info("[CPA] 已上传: %s", filepath.name)
        return True
    else:
        logger.error("[CPA] 上传失败: %d %s", resp.status_code, resp.text[:200])
        return False


def delete_from_cpa(name):
    """从 CPA 删除认证文件"""
    resp = requests.delete(
        f"{CPA_URL}/v0/management/auth-files",
        headers=_headers(),
        params={"name": name},
        timeout=10,
    )
    if resp.status_code == 200:
        logger.info("[CPA] 已删除: %s", name)
        return True
    else:
        logger.error("[CPA] 删除失败: %d %s", resp.status_code, resp.text[:200])
        return False


def download_from_cpa(name):
    """从 CPA 下载认证文件内容。"""
    resp = requests.get(
        f"{CPA_URL}/v0/management/auth-files/download",
        headers=_headers(),
        params={"name": name},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.text
    logger.error("[CPA] 下载失败: %s -> %d %s", name, resp.status_code, resp.text[:200])
    return None


def _parse_expired_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return time.time() + 3600
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return time.time() + 3600


def _parse_optional_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _parse_jwt_payload(token):
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _bundle_from_auth_data(auth_data, fallback_name=""):
    id_token = auth_data.get("id_token") or auth_data.get("idToken") or ""
    access_token = auth_data.get("access_token") or auth_data.get("accessToken") or ""
    refresh_token = auth_data.get("refresh_token") or auth_data.get("refreshToken") or ""
    claims = _parse_jwt_payload(id_token) if id_token else {}
    access_claims = _parse_jwt_payload(access_token) if access_token else {}
    auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
    access_auth_claims = access_claims.get("https://api.openai.com/auth", {}) if isinstance(access_claims, dict) else {}
    profile_claims = claims.get("https://api.openai.com/profile", {}) if isinstance(claims, dict) else {}
    access_profile_claims = access_claims.get("https://api.openai.com/profile", {}) if isinstance(access_claims, dict) else {}

    plan_type = auth_claims.get("chatgpt_plan_type", "") or access_auth_claims.get("chatgpt_plan_type", "")
    if not plan_type and "-team" in fallback_name:
        plan_type = "team"
    if not plan_type and "-plus" in fallback_name:
        plan_type = "plus"
    if not plan_type and "-free" in fallback_name:
        plan_type = "free"
    if not plan_type:
        plan_type = "unknown"

    return {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": (
            auth_data.get("account_id")
            or auth_data.get("accountId")
            or (auth_data.get("account") or {}).get("id")
            or auth_claims.get("chatgpt_account_id")
            or access_auth_claims.get("chatgpt_account_id")
            or next((o.get("id") for o in (auth_claims.get("organizations") or access_auth_claims.get("organizations") or []) if isinstance(o, dict) and o.get("is_default")), None)
            or next((o.get("id") for o in (auth_claims.get("organizations") or access_auth_claims.get("organizations") or []) if isinstance(o, dict)), None)
            or ""
        ),
        "email": (
            auth_data.get("email")
            or profile_claims.get("email")
            or access_profile_claims.get("email")
            or claims.get("email")
            or access_claims.get("email")
            or ""
        ),
        "plan_type": plan_type,
        "expired": _parse_expired_timestamp(auth_data.get("expired") or auth_data.get("expires") or access_claims.get("exp")),
        "last_refresh_ts": _parse_optional_timestamp(auth_data.get("last_refresh")),
    }


def _is_cpa_compatible_auth_data(auth_data: dict) -> bool:
    return (
        isinstance(auth_data, dict)
        and auth_data.get("type") == "codex"
        and bool(str(auth_data.get("access_token") or "").strip())
        and bool(str(auth_data.get("id_token") or "").strip())
        and bool(str(auth_data.get("refresh_token") or "").strip())
    )


def ensure_cpa_compatible_auth_file(filepath, *, fallback_email: str = "", fallback_plan_type: str = "") -> str:
    """Return a CPA-compatible codex auth file path, normalizing if possible."""
    path = Path(filepath or "")
    if not path.exists():
        return ""
    try:
        auth_data = json.loads(read_text(path))
    except Exception:
        logger.warning("[CPA] 认证文件不是有效 JSON，跳过: %s", path)
        return ""

    if _is_cpa_compatible_auth_data(auth_data):
        return str(path.resolve())

    bundle = _bundle_from_auth_data(auth_data, fallback_name=path.name)
    if fallback_email and not bundle.get("email"):
        bundle["email"] = fallback_email
    if fallback_plan_type and (not bundle.get("plan_type") or bundle.get("plan_type") == "unknown"):
        bundle["plan_type"] = fallback_plan_type

    missing = [
        key
        for key in ("access_token", "id_token", "refresh_token", "email", "account_id")
        if not str(bundle.get(key) or "").strip()
    ]
    if missing:
        logger.info(
            "[CPA] 跳过非 CPA codex 格式认证文件: %s missing=%s",
            path,
            ",".join(missing),
        )
        return ""

    normalized = Path(_save_normalized_auth_file(bundle))
    logger.info("[CPA] 已规范化认证文件为 CPA codex 格式: %s -> %s", path.name, normalized.name)
    return str(normalized.resolve())


def find_cpa_compatible_auth_file(email: str, preferred_path: str = "", *, fallback_plan_type: str = "") -> str:
    """Find a CPA-compatible codex auth file for an email.

    auth_session files are never uploaded directly. They are only accepted if
    they can be normalized into a complete codex auth file under AUTH_DIR.
    """
    target_email = str(email or "").strip().lower()
    candidates: list[Path] = []
    if preferred_path:
        candidates.append(Path(preferred_path))
    if AUTH_DIR.exists():
        candidates.extend(path for path in AUTH_DIR.glob("codex-*.json") if path.is_file())

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        prepared = ensure_cpa_compatible_auth_file(
            candidate,
            fallback_email=target_email,
            fallback_plan_type=fallback_plan_type,
        )
        if not prepared:
            continue
        try:
            auth_data = json.loads(read_text(Path(prepared)))
        except Exception:
            continue
        bundle = _bundle_from_auth_data(auth_data, fallback_name=Path(prepared).name)
        if target_email and str(bundle.get("email") or "").strip().lower() != target_email:
            continue
        return prepared
    return ""


def upload_account_auth_to_cpa(email: str, preferred_path: str = "", *, fallback_plan_type: str = "plus") -> dict:
    """Upload one account's CPA-compatible codex auth file."""
    auth_file = find_cpa_compatible_auth_file(email, preferred_path, fallback_plan_type=fallback_plan_type)
    if not auth_file:
        return {
            "status": "skipped",
            "reason": "缺少 CPA 兼容 Codex auth 文件，请先补登录生成 auths/codex-*.json",
        }
    path = Path(auth_file)
    if upload_to_cpa(path):
        return {"status": "success", "uploaded": path.name, "auth_file": str(path.resolve())}
    return {"status": "failed", "message": f"上传 CPA 失败: {path.name}", "auth_file": str(path.resolve())}


def _normalized_auth_path(bundle, main=False):
    email = bundle.get("email", "")
    account_id = bundle.get("account_id", "")
    if main:
        suffix = account_id or md5(email.encode()).hexdigest()[:8]
        return AUTH_DIR / f"codex-main-{suffix}.json"
    plan_type = bundle.get("plan_type", "unknown")
    hash_id = md5(account_id.encode()).hexdigest()[:8] if account_id else "unknown"
    return AUTH_DIR / f"codex-{email}-{plan_type}-{hash_id}.json"


def _auth_identity(bundle, main=False):
    if main:
        return ("main", bundle.get("account_id") or bundle.get("email") or "")
    return ("codex", (bundle.get("email") or "").lower(), bundle.get("account_id") or "")


def _candidate_score(auth_data, bundle, name, main=False):
    canonical_name = _normalized_auth_path(bundle, main=main).name
    return (
        1 if name == canonical_name else 0,
        bundle.get("last_refresh_ts", _parse_optional_timestamp(auth_data.get("last_refresh"))),
        _parse_expired_timestamp(auth_data.get("expired")),
        len(auth_data.get("refresh_token") or ""),
    )


def _write_auth_file(filepath, bundle):
    ensure_auth_dir()
    auth_data = {
        "type": "codex",
        "disabled": False,
        "id_token": bundle.get("id_token", ""),
        "access_token": bundle.get("access_token", ""),
        "refresh_token": bundle.get("refresh_token", ""),
        "account_id": bundle.get("account_id", ""),
        "email": bundle.get("email", ""),
        "plan_type": bundle.get("plan_type", "unknown"),
        "chatgpt_plan_type": bundle.get("plan_type", "unknown"),
        "expired": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(bundle.get("expired", 0))),
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(bundle.get("last_refresh_ts", time.time()))),
    }
    write_text(filepath, json.dumps(auth_data, indent=2))
    ensure_auth_file_permissions(filepath)
    try:
        upsert_codex_auth_file(filepath, auth_data, main=Path(filepath).name.startswith("codex-main-"))
    except Exception as exc:
        logger.warning("[CPA] SQLite auth 索引写入失败: %s", exc)
    return filepath


def _save_normalized_auth_file(bundle, main=False):
    filepath = _normalized_auth_path(bundle, main=main)

    if main:
        for old in AUTH_DIR.glob("codex-main-*.json"):
            if old != filepath and old.exists():
                delete_codex_auth_file(old)
                old.unlink()
    else:
        email = bundle.get("email", "")
        for old in AUTH_DIR.glob(f"codex-{email}-*.json"):
            if old != filepath and old.exists():
                delete_codex_auth_file(old)
                old.unlink()

    return _write_auth_file(filepath, bundle)


def _load_local_best_candidate(identity_key):
    """读取本地同 identity 的最佳候选认证文件。"""
    best = None
    for path in AUTH_DIR.glob("codex-*.json"):
        if not path.is_file():
            continue
        try:
            auth_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if auth_data.get("type") != "codex":
            continue
        main = path.name.startswith("codex-main-")
        bundle = _bundle_from_auth_data(auth_data, fallback_name=path.name)
        if _auth_identity(bundle, main=main) != identity_key:
            continue
        candidate = {
            "path": path,
            "auth_data": auth_data,
            "bundle": bundle,
            "main": main,
        }
        if best is None or _candidate_score(
            candidate["auth_data"], candidate["bundle"], candidate["path"].name, candidate["main"]
        ) > _candidate_score(best["auth_data"], best["bundle"], best["path"].name, best["main"]):
            best = candidate
    return best


def _cleanup_local_duplicates(accounts=None):
    """清理本地同账号重复认证文件，只保留一个规范文件。"""
    grouped = {}
    for path in AUTH_DIR.glob("codex-*.json"):
        if not path.is_file():
            continue
        try:
            auth_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if auth_data.get("type") != "codex":
            continue
        main = path.name.startswith("codex-main-")
        bundle = _bundle_from_auth_data(auth_data, fallback_name=path.name)
        key = _auth_identity(bundle, main=main)
        grouped.setdefault(key, []).append(
            {
                "path": path,
                "auth_data": auth_data,
                "bundle": bundle,
                "main": main,
            }
        )

    canonical_map = {}
    removed = 0
    for items in grouped.values():
        if not items:
            continue
        winner = max(
            items, key=lambda item: _candidate_score(item["auth_data"], item["bundle"], item["path"].name, item["main"])
        )
        canonical_path = Path(_save_normalized_auth_file(winner["bundle"], main=winner["main"]))
        canonical_map[_auth_identity(winner["bundle"], main=winner["main"])] = canonical_path
        for item in items:
            if item["path"] != canonical_path and item["path"].exists():
                item["path"].unlink()
                removed += 1

    if accounts is not None:
        changed = False
        for acc in accounts:
            auth_path = acc.get("auth_file")
            if not auth_path:
                continue
            try:
                path = Path(auth_path)
                if not path.exists():
                    continue
                auth_data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            bundle = _bundle_from_auth_data(auth_data, fallback_name=path.name)
            canonical_path = canonical_map.get(_auth_identity(bundle, main=False))
            if canonical_path and acc.get("auth_file") != str(canonical_path.resolve()):
                acc["auth_file"] = str(canonical_path.resolve())
                changed = True
        return removed, changed

    return removed, False


def sync_from_cpa():
    """
    从 CPA 反向同步认证文件到本地。

    规则：
    - 下载 CPA 中所有 codex 认证文件到本地 auths/
    - 非主号文件会导入/修复到 accounts.json，默认状态为 standby（保守导入）
    - 不删除本地账号记录，仅补充/更新 auth_file
    """
    from autoteam.accounts import STATUS_STANDBY, find_account, load_accounts, save_accounts

    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    accounts = load_accounts()
    changed_accounts = False
    imported_files = 0
    updated_files = 0
    added_accounts = 0
    updated_accounts = 0
    skipped = 0
    cpa_duplicates_deleted = 0
    local_kept_newer = 0

    local_duplicates_deleted, accounts_path_repaired = _cleanup_local_duplicates(accounts)
    if accounts_path_repaired:
        save_accounts(accounts)

    cpa_files = list_cpa_files()
    if not cpa_files:
        logger.info("[CPA] 未发现可反向同步的认证文件")
        return {
            "downloaded": 0,
            "updated": 0,
            "accounts_added": 0,
            "accounts_updated": 0,
            "skipped": 0,
            "cpa_duplicates_deleted": 0,
            "local_duplicates_deleted": local_duplicates_deleted,
            "local_kept_newer": 0,
            "total": 0,
        }

    candidates = []
    for item in cpa_files:
        name = (item.get("name") or "").strip()
        if not name or not name.endswith(".json") or not name.startswith("codex-"):
            skipped += 1
            continue

        content = download_from_cpa(name)
        if not content:
            skipped += 1
            continue

        try:
            auth_data = json.loads(content)
        except Exception:
            logger.warning("[CPA] 跳过无效 JSON: %s", name)
            skipped += 1
            continue

        if auth_data.get("type") != "codex":
            logger.info("[CPA] 跳过非 codex 文件: %s", name)
            skipped += 1
            continue

        bundle = _bundle_from_auth_data(auth_data, fallback_name=name)
        email = (bundle.get("email") or item.get("email") or "").lower().strip()
        bundle["email"] = email

        if not email and not name.startswith("codex-main-"):
            logger.info("[CPA] 跳过缺少邮箱的文件: %s", name)
            continue

        candidates.append(
            {
                "name": name,
                "auth_data": auth_data,
                "bundle": bundle,
                "main": name.startswith("codex-main-"),
            }
        )

    grouped = {}
    for item in candidates:
        grouped.setdefault(_auth_identity(item["bundle"], main=item["main"]), []).append(item)

    for items in grouped.values():
        winner = max(
            items,
            key=lambda item: _candidate_score(item["auth_data"], item["bundle"], item["name"], main=item["main"]),
        )
        for item in items:
            if item is winner:
                continue
            if delete_from_cpa(item["name"]):
                cpa_duplicates_deleted += 1

        name = winner["name"]
        bundle = winner["bundle"]
        email = bundle.get("email", "")
        identity_key = _auth_identity(bundle, main=winner["main"])
        local_best = _load_local_best_candidate(identity_key)
        cpa_score = _candidate_score(winner["auth_data"], bundle, name, main=winner["main"])
        local_score = None
        if local_best:
            local_score = _candidate_score(
                local_best["auth_data"], local_best["bundle"], local_best["path"].name, main=local_best["main"]
            )

        if winner["main"]:
            if local_best and local_score >= cpa_score:
                local_kept_newer += 1
                normalized_path = local_best["path"]
            else:
                normalized_path = _normalized_auth_path(bundle, main=True)
                existed = normalized_path.exists()
                previous = None
                if existed:
                    try:
                        previous = normalized_path.read_text(encoding="utf-8")
                    except Exception:
                        previous = None

                normalized_path = Path(_save_normalized_auth_file(bundle, main=True))
                current = normalized_path.read_text(encoding="utf-8")
                if not existed:
                    imported_files += 1
                elif previous != current:
                    updated_files += 1
            if normalized_path.name != name:
                old_path = AUTH_DIR / name
                if old_path.exists() and old_path != normalized_path:
                    old_path.unlink()
            continue

        if local_best and local_score >= cpa_score:
            local_kept_newer += 1
            normalized_path = local_best["path"]
        else:
            normalized_path = _normalized_auth_path(bundle)
            existed = normalized_path.exists()
            previous = None
            if existed:
                try:
                    previous = normalized_path.read_text(encoding="utf-8")
                except Exception:
                    previous = None

            normalized_path = Path(_save_normalized_auth_file(bundle))
            current = normalized_path.read_text(encoding="utf-8")

            if not existed:
                imported_files += 1
            elif previous != current:
                updated_files += 1

        acc = find_account(accounts, email)
        resolved_path = str(normalized_path.resolve())
        if acc:
            if acc.get("auth_file") != resolved_path:
                acc["auth_file"] = resolved_path
                changed_accounts = True
                updated_accounts += 1
        else:
            accounts.append(
                {
                    "email": email,
                    "password": "",
                    "cloudmail_account_id": None,
                    "status": STATUS_STANDBY,
                    "auth_file": resolved_path,
                    "quota_exhausted_at": None,
                    "quota_resets_at": None,
                    "created_at": time.time(),
                    "last_active_at": None,
                }
            )
            changed_accounts = True
            added_accounts += 1

    if changed_accounts:
        save_accounts(accounts)

    local_duplicates_deleted_after, accounts_path_repaired = _cleanup_local_duplicates(accounts)
    local_duplicates_deleted += local_duplicates_deleted_after
    if accounts_path_repaired:
        save_accounts(accounts)

    logger.info(
        "[CPA] 反向同步完成: 新增文件 %d, 更新文件 %d, 新增账号 %d, 更新账号 %d, 保留本地较新 %d, CPA去重 %d, 本地去重 %d, 跳过 %d",
        imported_files,
        updated_files,
        added_accounts,
        updated_accounts,
        local_kept_newer,
        cpa_duplicates_deleted,
        local_duplicates_deleted,
        skipped,
    )
    return {
        "downloaded": imported_files,
        "updated": updated_files,
        "accounts_added": added_accounts,
        "accounts_updated": updated_accounts,
        "skipped": skipped,
        "local_kept_newer": local_kept_newer,
        "cpa_duplicates_deleted": cpa_duplicates_deleted,
        "local_duplicates_deleted": local_duplicates_deleted,
        "total": len(cpa_files),
    }


def import_local_cpa_auth_sources(sources):
    """Import local CPA/Codex auth JSON payloads into data/auths and accounts."""
    from autoteam.accounts import (
        ACCOUNT_SOURCE_MANAGED,
        ACCOUNT_TYPE_FREE,
        SEAT_CODEX,
        STATUS_STANDBY,
        find_account,
        load_accounts,
        save_accounts,
    )

    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    accounts = load_accounts()
    changed_accounts = False
    imported_files = 0
    updated_files = 0
    added_accounts = 0
    updated_accounts = 0
    invalid = []
    duplicate_sources = 0
    imported = []
    seen_identities = set()

    for source in sources or []:
        name = str((source or {}).get("name") or "pasted.json").strip() or "pasted.json"
        auth_data = (source or {}).get("auth_data")
        if isinstance(auth_data, dict) and isinstance(auth_data.get("codex_auth"), dict):
            auth_data = auth_data.get("codex_auth")
        if not isinstance(auth_data, dict):
            invalid.append({"filename": name, "error": "不是有效的 JSON 对象"})
            continue
        if auth_data.get("type") and auth_data.get("type") != "codex":
            invalid.append({"filename": name, "error": "不是 Codex CPA 认证文件"})
            continue

        bundle = _bundle_from_auth_data(auth_data, fallback_name=name)
        missing = [
            key
            for key in ("access_token", "id_token", "refresh_token", "email", "account_id")
            if not str(bundle.get(key) or "").strip()
        ]
        if missing:
            invalid.append({"filename": name, "error": f"缺少字段: {', '.join(missing)}"})
            continue

        main = name.startswith("codex-main-") or bool(auth_data.get("main") or auth_data.get("is_main"))
        identity = _auth_identity(bundle, main=main)
        if identity in seen_identities:
            duplicate_sources += 1
            continue
        seen_identities.add(identity)

        normalized_path = _normalized_auth_path(bundle, main=main)
        existed = normalized_path.exists()
        previous = None
        if existed:
            try:
                previous = normalized_path.read_text(encoding="utf-8")
            except Exception:
                previous = None

        normalized_path = Path(_save_normalized_auth_file(bundle, main=main))
        current = normalized_path.read_text(encoding="utf-8")
        if not existed:
            imported_files += 1
        elif previous != current:
            updated_files += 1

        email = str(bundle.get("email") or "").strip().lower()
        resolved_path = str(normalized_path.resolve())
        imported.append(
            {
                "email": email,
                "filename": normalized_path.name,
                "auth_file": resolved_path,
                "plan_type": bundle.get("plan_type") or "unknown",
                "main": main,
            }
        )

        if main:
            continue

        acc = find_account(accounts, email)
        if acc:
            changed = False
            updates = {
                "auth_file": resolved_path,
                "account_source": ACCOUNT_SOURCE_MANAGED,
                "account_type": ACCOUNT_TYPE_FREE,
            }
            if not acc.get("seat_type"):
                updates["seat_type"] = SEAT_CODEX
            for key, value in updates.items():
                if acc.get(key) != value:
                    acc[key] = value
                    changed = True
            if changed:
                changed_accounts = True
                updated_accounts += 1
        else:
            accounts.append(
                {
                    "email": email,
                    "password": "",
                    "cloudmail_account_id": None,
                    "status": STATUS_STANDBY,
                    "account_type": ACCOUNT_TYPE_FREE,
                    "seat_type": SEAT_CODEX,
                    "auth_file": resolved_path,
                    "quota_exhausted_at": None,
                    "quota_resets_at": None,
                    "created_at": time.time(),
                    "last_active_at": None,
                    "account_source": ACCOUNT_SOURCE_MANAGED,
                }
            )
            changed_accounts = True
            added_accounts += 1

    if changed_accounts:
        save_accounts(accounts)

    return {
        "imported": imported_files,
        "updated": updated_files,
        "accounts_added": added_accounts,
        "accounts_updated": updated_accounts,
        "duplicates": duplicate_sources,
        "invalid": invalid,
        "files": imported,
        "total": len(sources or []),
    }


def sync_to_cpa():
    """
    同步本地认证文件到 CPA。同步范围：STATUS_ACTIVE（Team 席位）+ STATUS_PERSONAL（免费号）+ STATUS_PLUS（GoPay Plus）。
    - active / personal / plus 有 auth_file → 上传（覆盖）
    - CPA 有但本地账号状态已不在上述两种（standby / exhausted / pending 等）→ 从 CPA 删除
    - 仅清理本地 accounts.json 管理过的邮箱，主号和 CPA 手动上传文件不会被删
    """
    from autoteam.accounts import STATUS_ACTIVE, STATUS_PERSONAL, STATUS_PLUS, load_accounts, save_accounts

    accounts = load_accounts()
    local_emails = {a["email"].lower() for a in accounts}
    local_duplicates_deleted, accounts_path_repaired = _cleanup_local_duplicates(accounts)
    if accounts_path_repaired:
        save_accounts(accounts)

    # 修复断裂的 auth_file 路径
    changed = False
    for acc in accounts:
        auth_path = acc.get("auth_file")
        if auth_path and not Path(auth_path).exists():
            matches = list(AUTH_DIR.glob(f"codex-{acc['email']}-*.json"))
            if matches:
                acc["auth_file"] = str(matches[0].resolve())
                changed = True
    if changed:
        save_accounts(accounts)

    # 需要同步到 CPA 的账号：active（Team 席位）、personal（免费号）和 plus（GoPay Plus）都要覆盖
    # 只上传 CPA 兼容的 codex auth 文件，不能直接上传 data/auth_session/*.json。
    files_to_sync = {}
    synced_active = 0
    synced_personal = 0
    synced_plus = 0
    for acc in accounts:
        status = acc.get("status")
        if status not in (STATUS_ACTIVE, STATUS_PERSONAL, STATUS_PLUS):
            continue
        auth_path = acc.get("auth_file")
        if not auth_path:
            continue
        prepared = find_cpa_compatible_auth_file(
            str(acc.get("email") or ""),
            auth_path,
            fallback_plan_type=STATUS_PLUS if status == STATUS_PLUS else str(status or ""),
        )
        if not prepared:
            continue
        path = Path(prepared)
        if str(path.resolve()) != str(acc.get("auth_file") or ""):
            acc["auth_file"] = str(path.resolve())
            changed = True
        files_to_sync[path.name] = path
        if status == STATUS_ACTIVE:
            synced_active += 1
        elif status == STATUS_PERSONAL:
            synced_personal += 1
        else:
            synced_plus += 1

    # CPA 认证文件
    cpa_files = list_cpa_files()
    cpa_names = {f["name"]: f for f in cpa_files}

    logger.info(
        "[CPA] 待同步认证文件: %d (Team=%d, Personal=%d, Plus=%d), CPA 现有: %d",
        len(files_to_sync),
        synced_active,
        synced_personal,
        synced_plus,
        len(cpa_files),
    )

    # 上传：所有 active + personal 认证文件（覆盖同名文件，确保 token 最新）
    uploaded = 0
    for name, path in files_to_sync.items():
        logger.info("[CPA] 上传: %s", name)
        if upload_to_cpa(path):
            uploaded += 1

    # 删除：CPA 中有但不在同步列表的（仅限本地管理的账号 — 避免误删主号或 CPA 手动文件）
    # 注意：personal 号已计入 files_to_sync，这里不会被删掉；只有状态变成 STANDBY/EXHAUSTED 等才会清理
    deleted = 0
    for name, cpa_file in cpa_names.items():
        email = cpa_file.get("email", "").lower()
        if email in local_emails and name not in files_to_sync:
            logger.info("[CPA] 删除非 active/personal 文件: %s (%s)", name, email)
            if delete_from_cpa(name):
                deleted += 1

    logger.info("[CPA] 同步完成: 上传 %d, 删除 %d, 本地去重 %d", uploaded, deleted, local_duplicates_deleted)

    # 最终状态
    final_cpa = list_cpa_files()
    final_local_managed = [f for f in final_cpa if f.get("email", "").lower() in local_emails]
    logger.info(
        "[CPA] CPA 中本地管理: %d, 本地待同步 (Team+Personal+Plus): %d",
        len(final_local_managed),
        len(files_to_sync),
    )
    return {
        "uploaded": uploaded,
        "deleted": deleted,
        "local_duplicates_deleted": local_duplicates_deleted,
        "synced_active": synced_active,
        "synced_personal": synced_personal,
        "synced_plus": synced_plus,
        "total": len(files_to_sync),
    }


def sync_main_codex_to_cpa(filepath):
    """同步主号 Codex 认证文件到 CPA。"""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"主号认证文件不存在: {filepath}")

    name = filepath.name
    existing = {item.get("name"): item for item in list_cpa_files()}

    for old_name in existing:
        if old_name and old_name.startswith("codex-main-"):
            logger.info("[CPA] 删除旧主号文件: %s", old_name)
            delete_from_cpa(old_name)

    if not upload_to_cpa(filepath):
        raise RuntimeError(f"上传主号认证文件失败: {name}")

    logger.info("[CPA] 主号 Codex 已同步: %s", name)
    return {"uploaded": name}
