"""Backfill LuckMail tokens into an AutoTeam accounts.json file.

This is for accounts imported from another node/Hub where the account record
lost its LuckMail token. It reads LuckMail purchase history through the
OpenAPI, matches by email, and writes cloudmail_account_id/mail_provider back.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from curl_cffi import requests as curl_requests


DEFAULT_ROOT = Path.cwd()
PURCHASES_PATH = "/api/v1/openapi/email/purchases"


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_envs(root: Path, extra_env: Path | None = None) -> None:
    for path in [
        extra_env,
        root / ".env",
        root / "data" / ".env",
        DEFAULT_ROOT / ".env",
        DEFAULT_ROOT / "data" / ".env",
    ]:
        if path:
            _load_env_file(path)


def _parse_account_line(line: str) -> tuple[str, str] | None:
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
    if "@" not in email or not token.startswith("tok_"):
        return None
    return email, token


def _load_local_luckmail_tokens(root: Path) -> dict[str, str]:
    raw = str(os.environ.get("LUCKMAIL_ACCOUNTS") or "")
    file_value = str(os.environ.get("LUCKMAIL_ACCOUNTS_FILE") or "").strip()
    candidates: list[Path] = []
    if file_value:
        path = Path(file_value)
        candidates.append(path if path.is_absolute() else root / path)
    candidates.append(root / "data" / "luckmail_accounts.txt")
    candidates.append(DEFAULT_ROOT / "data" / "luckmail_accounts.txt")

    for path in candidates:
        try:
            if path.is_file():
                raw += ("\n" if raw else "") + path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            print(f"[WARN] 读取 LuckMail 本地 token 文件失败: {path}: {exc}", file=sys.stderr)

    tokens: dict[str, str] = {}
    for line in raw.replace(";", "\n").splitlines():
        parsed = _parse_account_line(line)
        if parsed:
            email, token = parsed
            tokens.setdefault(email, token)
    return tokens


def _purchase_item_to_token(item: dict[str, Any]) -> tuple[str, str] | None:
    email = str(item.get("email_address") or item.get("address") or item.get("email") or "").strip().lower()
    token = str(item.get("token") or "").strip()
    if "@" not in email or not token.startswith("tok_"):
        return None
    return email, token


def _fetch_luckmail_purchase_tokens(*, max_pages: int, page_size: int) -> dict[str, str]:
    base_url = str(os.environ.get("LUCKMAIL_BASE_URL") or "https://mail.luckyous.com").strip().rstrip("/")
    api_key = str(os.environ.get("LUCKMAIL_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("缺少 LUCKMAIL_API_KEY，无法从 LuckMail 购买记录恢复 token")

    tokens: dict[str, str] = {}
    total = None
    for page in range(1, max_pages + 1):
        resp = None
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = curl_requests.get(
                    f"{base_url}{PURCHASES_PATH}",
                    headers={"X-API-Key": api_key, "Accept": "application/json"},
                    params={"page": page, "page_size": page_size},
                    timeout=45,
                    impersonate="chrome110",
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= 3:
                    raise
                wait = attempt * 1.5
                print(f"[WARN] LuckMail 购买记录 page={page} 读取失败，{wait:.1f}s 后重试: {exc}")
                time.sleep(wait)
        if resp is None:
            raise RuntimeError(f"LuckMail 购买记录 page={page} 读取失败: {last_exc}")
        if resp.status_code != 200:
            raise RuntimeError(f"LuckMail 购买记录接口失败: HTTP {resp.status_code} {(resp.text or '')[:300]}")
        body = resp.json() or {}
        data = body.get("data") or {}
        items = data.get("list") or []
        if total is None:
            try:
                total = int(data.get("total") or 0)
            except Exception:
                total = 0
        for item in items:
            if isinstance(item, dict):
                parsed = _purchase_item_to_token(item)
                if parsed:
                    email, token = parsed
                    tokens.setdefault(email, token)
        print(f"[INFO] 已读取 LuckMail 购买记录 page={page}, 本页={len(items)}, 已索引={len(tokens)}")
        if not items:
            break
        if total and page * page_size >= total:
            break
        time.sleep(0.2)
    return tokens


def _load_accounts_file(path: Path) -> tuple[Any, list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, raw
    if isinstance(raw, dict) and isinstance(raw.get("accounts"), list):
        return raw, raw["accounts"]
    raise RuntimeError(f"不支持的账号文件结构: {path}")


def _write_accounts_file(path: Path, raw: Any) -> Path:
    backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup


def _is_target_account(acc: dict[str, Any], *, include_all: bool) -> bool:
    email = str(acc.get("email") or "").strip().lower()
    if "@" not in email:
        return False
    if include_all:
        return True
    domain = email.rsplit("@", 1)[-1]
    return domain.startswith("outlook.") or domain in {"outlook.com", "hotmail.com", "live.com"}


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐 accounts.json 中缺失的 LuckMail token")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="目标 AutoTeam 根目录，默认当前目录")
    parser.add_argument("--accounts", default="", help="账号文件路径，默认 <root>/accounts.json")
    parser.add_argument("--env", default="", help="额外 .env 路径")
    parser.add_argument("--apply", action="store_true", help="写入 accounts.json；默认只预览")
    parser.add_argument("--include-all", action="store_true", help="不限制 Outlook 域名，尝试匹配所有邮箱")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    accounts_path = Path(args.accounts).resolve() if args.accounts else root / "accounts.json"
    env_path = Path(args.env).resolve() if args.env else None
    _load_envs(root, env_path)

    raw, accounts = _load_accounts_file(accounts_path)
    local_tokens = _load_local_luckmail_tokens(root)
    remote_tokens = _fetch_luckmail_purchase_tokens(max_pages=max(1, args.max_pages), page_size=max(1, args.page_size))
    tokens = {**remote_tokens, **local_tokens}

    changed: list[tuple[str, str]] = []
    missing: list[str] = []
    provider_fixed: list[str] = []
    for acc in accounts:
        if not isinstance(acc, dict) or not _is_target_account(acc, include_all=args.include_all):
            continue
        email = str(acc.get("email") or "").strip().lower()
        current_token = str(acc.get("cloudmail_account_id") or "").strip()
        token = current_token if current_token.startswith("tok_") else tokens.get(email, "")
        if token:
            if current_token != token:
                acc["cloudmail_account_id"] = token
                changed.append((email, "token"))
            if str(acc.get("mail_provider") or "").strip().lower() != "luckmail":
                acc["mail_provider"] = "luckmail"
                provider_fixed.append(email)
        elif not current_token.startswith("tok_"):
            missing.append(email)

    print(f"[RESULT] 账号总数: {len(accounts)}")
    print(f"[RESULT] token 补齐: {len(changed)}")
    print(f"[RESULT] provider 修复: {len(provider_fixed)}")
    print(f"[RESULT] 仍缺 token: {len(missing)}")
    for email, kind in changed[:80]:
        print(f"  + {kind}: {email}")
    if missing:
        print("[WARN] 未在 LuckMail 购买记录中找到 token:")
        for email in missing[:120]:
            print(f"  - {email}")

    if not args.apply:
        print("[DRY-RUN] 未写入文件；确认后加 --apply")
        return 0
    if changed or provider_fixed:
        backup = _write_accounts_file(accounts_path, raw)
        print(f"[OK] 已写入: {accounts_path}")
        print(f"[OK] 备份文件: {backup}")
    else:
        print("[OK] 无需写入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
