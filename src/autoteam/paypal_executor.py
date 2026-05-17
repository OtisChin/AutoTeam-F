"""PayPal payment runner integration.

This module wraps the external Gpt-Agreement-Payment pipeline as an AutoTeam
background task.  It intentionally keeps the process boundary: the PayPal
project owns its protocol implementation, while AutoTeam owns task status and
UI integration.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable


DEFAULT_PROJECT_PATH = Path(r"D:\code\OpenSource\Gpt-Agreement-Payment")


def _default_project_path() -> Path:
    configured = os.environ.get("PAYPAL_PROJECT_PATH", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_PROJECT_PATH


def _default_config_path(project_path: Path) -> Path:
    configured = os.environ.get("PAYPAL_CONFIG_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else project_path / path
    for rel in ("CTF-pay/config.paypal.json", "CTF-pay/config.auto.json", "CTF-pay/config.paypal.example.json"):
        candidate = project_path / rel
        if candidate.exists():
            return candidate
    return project_path / "CTF-pay/config.paypal.json"


def build_paypal_command(params: dict) -> tuple[list[str], Path]:
    project_path = Path(str(params.get("project_path") or _default_project_path())).expanduser()
    if not project_path.is_absolute():
        project_path = Path.cwd() / project_path
    project_path = project_path.resolve()
    if not project_path.exists():
        raise RuntimeError(f"PayPal 项目目录不存在: {project_path}")
    pipeline_path = project_path / "pipeline.py"
    if not pipeline_path.exists():
        raise RuntimeError(f"PayPal 项目缺少 pipeline.py: {pipeline_path}")

    config_raw = str(params.get("config_path") or "").strip()
    config_path = Path(config_raw).expanduser() if config_raw else _default_config_path(project_path)
    if not config_path.is_absolute():
        config_path = project_path / config_path
    config_path = config_path.resolve()
    if not config_path.exists():
        raise RuntimeError(f"PayPal 配置文件不存在: {config_path}")

    python_executable = str(params.get("python_executable") or os.environ.get("PAYPAL_PYTHON") or sys.executable)
    use_xvfb = params.get("use_xvfb")
    if use_xvfb is None:
        use_xvfb = os.name != "nt"

    cmd: list[str] = []
    if use_xvfb:
        cmd.extend(["xvfb-run", "-a"])
    cmd.extend([python_executable, "-u", "pipeline.py", "--config", str(config_path), "--paypal"])

    mode = str(params.get("mode") or "single").strip().lower()
    if mode == "batch":
        batch = max(1, int(params.get("batch") or 1))
        workers = max(1, int(params.get("workers") or 1))
        cmd.extend(["--batch", str(batch), "--workers", str(workers)])
    elif mode == "self_dealer":
        self_dealer = max(1, int(params.get("self_dealer") or 1))
        cmd.extend(["--self-dealer", str(self_dealer)])
    elif mode == "daemon":
        cmd.append("--daemon")
    elif mode == "free_register":
        cmd = []
        if use_xvfb:
            cmd.extend(["xvfb-run", "-a"])
        cmd.extend([python_executable, "-u", "pipeline.py", "--config", str(config_path), "--free-register"])
        count = int(params.get("count") or 0)
        if count > 0:
            cmd.extend(["--count", str(count)])
    elif mode == "free_backfill_rt":
        cmd = []
        if use_xvfb:
            cmd.extend(["xvfb-run", "-a"])
        cmd.extend([python_executable, "-u", "pipeline.py", "--config", str(config_path), "--free-backfill-rt"])
    elif mode != "single":
        raise RuntimeError(f"不支持的 PayPal 运行模式: {mode}")

    if mode not in ("free_register", "free_backfill_rt"):
        if bool(params.get("register_only")):
            cmd.append("--register-only")
        elif bool(params.get("pay_only")):
            cmd.append("--pay-only")
        if bool(params.get("rt_only")):
            cmd.append("--rt-only")

    target_emails = params.get("target_emails")
    if isinstance(target_emails, list):
        joined = ",".join(str(email).strip() for email in target_emails if str(email).strip())
        if joined:
            cmd.extend(["--target-emails", joined])

    extra_args = str(params.get("extra_args") or "").strip()
    if extra_args:
        cmd.extend(shlex.split(extra_args, posix=os.name != "nt"))

    return cmd, project_path


def _stage_from_line(line: str) -> str:
    lower = line.lower()
    if "register" in lower or "注册" in line:
        return "paypal_register"
    if "checkout" in lower or "stripe" in lower or "支付链接" in line:
        return "paypal_checkout"
    if "paypal" in lower:
        return "paypal_authorize"
    if "oauth" in lower or "refresh_token" in lower or "codex" in lower:
        return "paypal_oauth"
    if "success" in lower or "完成" in line:
        return "paypal_completed"
    if "error" in lower or "failed" in lower or "失败" in line:
        return "paypal_failed"
    return "paypal_running"


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def _extract_email(line: str) -> str:
    match = _EMAIL_RE.search(line)
    return match.group(0) if match else ""


def run_paypal_pipeline(
    params: dict,
    *,
    on_progress: Callable[[dict], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    cmd, cwd = build_paypal_command(params)
    timeout_seconds = int(params.get("timeout_seconds") or 0)
    started_at = time.time()
    line_count = 0
    last_stage = "paypal_starting"
    last_email = ""

    def progress(event: dict) -> None:
        if on_progress:
            on_progress(event)

    progress({
        "stage": "paypal_starting",
        "message": "PayPal 任务启动中",
        "cmd": " ".join(cmd),
        "project_path": str(cwd),
        "total": int(params.get("batch") or params.get("count") or 1),
        "current": 0,
    })

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    register_mode = str(params.get("register_mode") or "").strip().lower()
    if register_mode:
        env["WEBUI_REG_MODE"] = "protocol" if register_mode == "protocol" else "browser"

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"PayPal 任务启动失败: {exc}") from exc

    try:
        while True:
            if is_cancelled and is_cancelled():
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                progress({"stage": "paypal_cancelled", "message": "PayPal 任务已请求取消"})
                return {
                    "status": "cancelled",
                    "message": "PayPal 任务已取消",
                    "exit_code": proc.returncode,
                    "lines": line_count,
                }

            if timeout_seconds > 0 and time.time() - started_at > timeout_seconds:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise RuntimeError(f"PayPal 任务超时: {timeout_seconds}s")

            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if line:
                text = line.rstrip()
                if not text:
                    continue
                line_count += 1
                last_stage = _stage_from_line(text)
                last_email = _extract_email(text) or last_email
                progress({
                    "stage": last_stage,
                    "message": text,
                    "line": text,
                    "line_count": line_count,
                    "current_email": last_email,
                })
                continue

            if proc.poll() is not None:
                break
            time.sleep(0.2)

        exit_code = proc.wait()
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass

    duration = round(time.time() - started_at, 2)
    result = {
        "status": "completed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "duration_seconds": duration,
        "lines": line_count,
        "last_stage": last_stage,
        "last_email": last_email,
    }
    if exit_code != 0:
        raise RuntimeError(f"PayPal 任务失败: exit_code={exit_code}")
    progress({
        "stage": "paypal_completed",
        "message": "PayPal 任务完成",
        "current": int(params.get("batch") or params.get("count") or 1),
        "total": int(params.get("batch") or params.get("count") or 1),
    })
    return result
