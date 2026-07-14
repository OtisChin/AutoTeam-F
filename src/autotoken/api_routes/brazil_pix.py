"""Brazil PIX link extraction routes."""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from autotoken.core.paths import PROJECT_ROOT
from autotoken.payments.brazil_pix import PixJobConfig, generate_pix_trial

AUTH_SESSION_DIR = PROJECT_ROOT / "data" / "auth_session"
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


class BrazilPixStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field("", alias="accessToken")
    account_email: str = Field("", alias="accountEmail")
    proxies: str | list[str] = ""
    local_proxy: str = Field("", alias="localProxy")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    region: str = "BR"


def _decode_jwt_exp(token: str) -> int:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return 0
        payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or 0)
    except Exception:
        return 0


def _auth_email_from_path(path: Path, data: dict[str, Any]) -> str:
    email = str(data.get("email") or "").strip()
    if email:
        return email
    stem = path.stem
    return stem.replace("_", ".") if "@" in stem else stem


def _extract_token(value: Any) -> str:
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("{") or raw.startswith("["):
            try:
                return _extract_token(json.loads(raw)) or raw
            except Exception:
                return raw
        return raw
    if isinstance(value, list):
        for item in value:
            token = _extract_token(item)
            if token:
                return token
    if isinstance(value, dict):
        for key in ("accessToken", "access_token", "chatgpt_access_token", "token"):
            if str(value.get(key) or "").strip():
                return str(value.get(key)).strip()
        for item in value.values():
            token = _extract_token(item)
            if token:
                return token
    return ""


def _iter_auth_accounts() -> list[dict[str, Any]]:
    now = time.time()
    accounts: list[dict[str, Any]] = []
    if not AUTH_SESSION_DIR.exists():
        return accounts
    for path in sorted(AUTH_SESSION_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        token = _extract_token(data)
        if not token or len(token) < 50:
            continue
        exp = _decode_jwt_exp(token)
        if exp and exp <= now + 300:
            continue
        accounts.append(
            {
                "email": _auth_email_from_path(path, data),
                "auth_file": str(path),
                "expires_at": exp,
                "ttl_seconds": max(0, int(exp - now)) if exp else 0,
            }
        )
    accounts.sort(key=lambda item: ("example.com" in item["email"].lower(), item["email"].lower()))
    return accounts


def _load_token_for_email(email: str) -> str:
    target = email.strip().lower()
    for item in _iter_auth_accounts():
        if item["email"].lower() != target:
            continue
        data = json.loads(Path(item["auth_file"]).read_text(encoding="utf-8"))
        token = _extract_token(data)
        if token:
            return token
    return ""


def _parse_proxies(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    lines: list[str] = []
    for raw in text.replace(",", "\n").splitlines():
        item = raw.strip()
        if item:
            lines.append(item)
    return lines


def _append_log(job_id: str, message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["logs"].append(line)
        job["logs"] = job["logs"][-500:]


def _run_job(job_id: str, req: BrazilPixStartRequest) -> None:
    def log(message: str) -> None:
        _append_log(job_id, message)

    try:
        token = _extract_token(req.access_token)
        account_email = str(req.account_email or "").strip()
        if not token and account_email:
            token = _load_token_for_email(account_email)
        if not token:
            raise RuntimeError("缺少 Access Token 或账号池账号")
        proxies = _parse_proxies(req.proxies)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["account_email"] = account_email
        cfg = PixJobConfig(
            access_token=token,
            local_proxy=str(req.local_proxy or "").strip(),
            kookeey_user=str(req.kookeey_user or "").strip(),
            kookeey_pass=str(req.kookeey_pass or ""),
            kookeey_endpoint=str(req.kookeey_endpoint or "gate.kookeey.info:1000").strip(),
            region=(req.region or "BR").strip().upper() or "BR",
            direct_proxies=proxies,
        )
        result = generate_pix_trial(cfg, log=log)
        result["account_email"] = account_email
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "success"
            JOBS[job_id]["result"] = result
            JOBS[job_id]["finished_at"] = time.time()
        log("任务完成")
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        _append_log(job_id, f"失败: {exc}")


def create_brazil_pix_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/brazil-pix/accounts")
    def get_brazil_pix_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts()}

    @router.post("/api/brazil-pix/start")
    def start_brazil_pix(req: BrazilPixStartRequest) -> dict[str, str]:
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "logs": [],
                "result": None,
                "error": None,
                "created_at": time.time(),
                "finished_at": None,
                "account_email": str(req.account_email or "").strip(),
            }
        thread = threading.Thread(target=_run_job, args=(job_id, req), daemon=True)
        thread.start()
        return {"job_id": job_id}

    @router.get("/api/brazil-pix/jobs/{job_id}")
    def get_brazil_pix_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            return {
                "id": job["id"],
                "status": job["status"],
                "logs": list(job["logs"]),
                "result": job["result"],
                "error": job["error"],
                "created_at": job["created_at"],
                "finished_at": job["finished_at"],
                "account_email": job.get("account_email") or "",
            }

    return router
