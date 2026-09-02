"""Run account 2FA setup in a separate process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from loguru import logger

from autotoken.core.normalization import normalized_email
from autotoken.services.account_two_factor import setup_accounts_two_factor_protocol


def _clean_emails(emails: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in emails or []:
        email = normalized_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        result.append(email)
    return result


def run_account_two_factor_worker(emails: Iterable[str], *, source: str = "register") -> dict[str, Any]:
    targets = _clean_emails(emails)
    logger.info("[2FA] 进入2FA设置流程（独立进程）: source={} total={}", source, len(targets))
    if not targets:
        return {"total": 0, "enabled": [], "skipped": [], "failed": []}
    return setup_accounts_two_factor_protocol(targets, max_workers=1)


def launch_account_two_factor_process(emails: Iterable[str], *, source: str = "register") -> dict[str, Any]:
    targets = _clean_emails(emails)
    if not targets:
        raise ValueError("2FA 设置账号列表为空")

    args = _worker_command(targets, source=source)
    env = os.environ.copy()
    env["AUTOTOKEN_2FA_PROCESS_SOURCE"] = source
    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    process = subprocess.Popen(
        args,
        cwd=str(Path.cwd()),
        env=env,
        creationflags=creationflags,
    )
    logger.info("[2FA] 已启动独立2FA设置进程: pid={} source={} total={}", process.pid, source, len(targets))
    return {"pid": process.pid, "source": source, "emails": targets}


def _worker_command(emails: list[str], *, source: str) -> list[str]:
    payload = json.dumps(emails, ensure_ascii=False)
    if getattr(sys, "frozen", False):
        return [sys.executable, "setup-2fa-worker", "--emails-json", payload, "--source", source]
    return [sys.executable, "-m", "autotoken", "setup-2fa-worker", "--emails-json", payload, "--source", source]


def run_account_two_factor_worker_from_cli(args: Any) -> dict[str, Any]:
    emails = json.loads(str(getattr(args, "emails_json", "[]") or "[]"))
    if not isinstance(emails, list):
        raise ValueError("--emails-json 必须是 JSON 数组")
    return run_account_two_factor_worker([str(email) for email in emails], source=str(getattr(args, "source", "cli")))
