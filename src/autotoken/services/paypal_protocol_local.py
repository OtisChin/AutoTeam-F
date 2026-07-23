"""Local PayPal Billing Agreement protocol approval runner.

This module deliberately runs the vendored protocol engine in this repository.
It must not call third-party wrapper services.
"""

import hashlib
import json
import os
import re
import selectors
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from autotoken.core.paths import PROJECT_ROOT

LogFn = Callable[[str], None]

BA_TOKEN_RE = re.compile(r"(?i)\bBA-[0-9][A-Za-z0-9_-]{4,}\b")
BA_APPROVE_RE = re.compile(
    r"(?i)(?:(?:https?:)?//)?(?:www\.)?paypal\.com/agreements/approve\?[^\s\"'<>]*?ba_token=(?P<token>BA-[A-Za-z0-9_-]+)"
)
SMS_TOKEN_RE = re.compile(r"(?i)(token=)[^&\s]+")
USERINFO_RE = re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@", re.I)

DEFAULT_ENGINE_ROOT = PROJECT_ROOT / "src" / "autotoken" / "_paypal_protocol_engine"
DEFAULT_TIMEOUT_SECONDS = 900
TERMINAL_BA_FILE = PROJECT_ROOT / "data" / "paypal_protocol_terminal_ba.json"


@dataclass(slots=True)
class PaypalProtocolRunConfig:
    ba_token: str = ""
    paypal_link: str = ""
    phone: str = ""
    sms_record_url: str = ""
    proxy_url: str = ""
    country: str = "US"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    sms_record_wait_seconds: int = 300
    sms_record_poll_seconds: float = 3.0
    debug: bool = False


def extract_ba_token(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = BA_APPROVE_RE.search(text) or BA_TOKEN_RE.search(text)
    if not match:
        return ""
    return str(match.group("token") if "token" in match.groupdict() else match.group(0)).strip()


def paypal_approve_url(token: str) -> str:
    clean = extract_ba_token(token)
    return f"https://www.paypal.com/agreements/approve?ba_token={quote(clean, safe='')}" if clean else ""


def normalize_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    parts = raw.split(":", 3)
    if len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        return f"socks5h://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return f"http://{raw}"


def first_proxy(value: str | list[str]) -> str:
    if isinstance(value, list):
        candidates = value
    else:
        candidates = re.split(r"[\r\n]+", str(value or ""))
    for item in candidates:
        text = str(item or "").strip()
        if text:
            return normalize_proxy_url(text)
    return ""


def _mask_ba(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return token[:6] + "…" + token[-4:] if len(token) > 12 else "BA-***"

    return BA_TOKEN_RE.sub(repl, text)


def sanitize_log_text(value: Any) -> str:
    text = str(value or "")
    text = SMS_TOKEN_RE.sub(r"\1<redacted>", text)
    text = USERINFO_RE.sub(lambda m: f"{m.group('scheme')}<proxy-auth>@", text)
    text = re.sub(r"(?i)(--sms-record-url\s+)\S+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(--proxy-url\s+)\S+", r"\1<redacted>", text)
    text = _mask_ba(text)
    return text


def sanitize_result(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("password", "secret", "access_token", "cookie")):
                output[key] = "<redacted>"
            elif "sms" in lowered and "url" in lowered:
                output[key] = sanitize_log_text(item)
            elif "proxy" in lowered:
                output[key] = sanitize_log_text(item)
            elif "ba_token" == lowered:
                output[key] = _mask_ba(str(item))
            else:
                output[key] = sanitize_result(item)
        return output
    if isinstance(value, list):
        return [sanitize_result(item) for item in value]
    if isinstance(value, str):
        return sanitize_log_text(value)
    return value


def _ba_digest(token: str) -> str:
    clean = extract_ba_token(token)
    return hashlib.sha256(("paypal-protocol-ba-v1:" + clean).encode("utf-8")).hexdigest() if clean else ""


def _load_terminal_ba_records() -> dict[str, Any]:
    try:
        parsed = json.loads(TERMINAL_BA_FILE.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_terminal_ba_records(records: dict[str, Any]) -> None:
    TERMINAL_BA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = TERMINAL_BA_FILE.with_suffix(TERMINAL_BA_FILE.suffix + ".tmp")
    temp_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, TERMINAL_BA_FILE)


def terminal_ba_record(token: str) -> dict[str, Any]:
    digest = _ba_digest(token)
    if not digest:
        return {}
    records = _load_terminal_ba_records()
    item = records.get(digest)
    return item if isinstance(item, dict) else {}


def remember_terminal_ba(token: str, *, reason: str, stage: str = "member_approve_failed_after_create_member") -> None:
    clean = extract_ba_token(token)
    digest = _ba_digest(clean)
    if not digest:
        return
    records = _load_terminal_ba_records()
    now = time.time()
    existing = records.get(digest) if isinstance(records.get(digest), dict) else {}
    record = {
        "token_hash": digest,
        "token_masked": sanitize_log_text(clean),
        "stage": stage,
        "reason": sanitize_log_text(reason),
        "first_seen_at": existing.get("first_seen_at") or now if isinstance(existing, dict) else now,
        "last_seen_at": now,
        "attempt_count": int(existing.get("attempt_count") or 0) + 1 if isinstance(existing, dict) else 1,
    }
    records[digest] = record
    _save_terminal_ba_records(records)


def _terminal_ba_retry_allowed() -> bool:
    return str(os.getenv("PAYPAL_PROTOCOL_ALLOW_TERMINAL_BA_RETRY") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _member_approve_terminal_after_create(output: str, parsed: dict[str, Any]) -> bool:
    text = output or ""
    parsed_text = json.dumps(parsed, ensure_ascii=False) if parsed else ""
    create_member_reached = (
        "Member account created without backup FI" in text
        or "CreateMemberAccountMutation HTTP 200" in text
        or "onboardAccount" in parsed_text
    )
    member_approve_failed = (
        "ApproveMemberPaymentMutation returned errors" in text
        or "approveMemberPayment returned empty result" in text
        or "MEMBER_NO_FI_APPROVE_FAILED" in parsed_text
        or "approveMemberPayment returned empty result" in parsed_text
    )
    return bool(create_member_reached and member_approve_failed)


def _engine_root() -> Path:
    configured = str(os.getenv("AUTOTEAM_PAYPAL_ENGINE_ROOT") or "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ENGINE_ROOT


def _engine_main(root: Path) -> Path:
    main_py = root / "main.py"
    if not main_py.exists():
        raise RuntimeError(f"本地 PayPal 协议引擎不存在: {main_py}")
    return main_py


def build_protocol_command(cfg: PaypalProtocolRunConfig, *, engine_root: Path | None = None) -> tuple[list[str], dict[str, str], Path]:
    root = (engine_root or _engine_root()).resolve()
    main_py = _engine_main(root)
    ba_token = extract_ba_token(cfg.ba_token or cfg.paypal_link)
    if not ba_token:
        raise ValueError("缺少有效 PayPal BA token/link")
    if not str(cfg.phone or "").strip():
        raise ValueError("缺少 PayPal 注册手机号")
    if not str(cfg.sms_record_url or "").strip():
        raise ValueError("缺少 SMS record URL")
    country = str(cfg.country or "US").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        country = "US"
    if country != "US":
        raise ValueError("当前本地协议支付仅开放 US，其他国家后续扩展")

    cmd = [
        sys.executable,
        "-u",
        str(main_py),
        "--ba-token",
        ba_token,
        "--phone",
        str(cfg.phone).strip(),
        "--sms-record-url",
        str(cfg.sms_record_url).strip(),
        "--sms-record-wait",
        str(max(60, int(cfg.sms_record_wait_seconds or 300))),
        "--sms-record-poll",
        str(max(1.0, float(cfg.sms_record_poll_seconds or 3.0))),
        "--country",
        country,
        "--approval-path",
        "create-member-no-fi",
        "--fingerprint-source",
        "headless",
        "--datadome-mode",
        "headless",
        "--mtr-runtime",
        "headless",
        "--risk-signals-mode",
        "headless",
        "--max-flow-attempts",
        "1",
    ]
    proxy = normalize_proxy_url(cfg.proxy_url)
    if proxy:
        cmd.extend(["--proxy-url", proxy, "--proxy"])
    else:
        cmd.append("--no-proxy")
    if cfg.debug:
        cmd.append("--debug")

    env = os.environ.copy()
    env["PAYPAL_USE_CURL_CFFI"] = "0"
    env["PAYPAL_HEADLESS_USE_PINNED_FINGERPRINT"] = "1"
    env["PAYPAL_RISK_SIGNALS_MODE"] = "headless"
    env["PAYPAL_RISK_HEADLESS_WAIT_SECONDS"] = "45"
    env["PAYPAL_DATADOME_MODE"] = "headless"
    env["PAYPAL_MTR_RUNTIME"] = "headless"
    env["PAYPAL_MTR_HEADLESS_WAIT_SECONDS"] = "45"
    env["PAYPAL_APPROVAL_PATH"] = "create_member_no_fi"
    env["PAYPAL_COUNTRY"] = country
    # The verified AutoTeam-F tuple is a normal preflight run, not strict lab
    # mode.  Parent shells may export PAYPAL_STRICT_BROWSER_RISK=1 while doing
    # research; do not let that leak into the web runner and reject otherwise
    # usable runs with diagnostic-only blockers such as mtr_sealedResult_missing.
    env["PAYPAL_STRICT_BROWSER_RISK"] = "0"
    env["PAYPAL_ALLOW_SYNTHETIC_CAPTCHA"] = "0"
    fingerprint_path = root / "var" / "roxy_ios_fingerprint_current.json"
    if fingerprint_path.exists():
        env["PAYPAL_HEADLESS_PINNED_FINGERPRINT_PATH"] = str(fingerprint_path)
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(root) + (os.pathsep + existing_path if existing_path else "")
    return cmd, env, root


def _parse_result_from_output(output: str) -> dict[str, Any]:
    marker = "RESULT:"
    idx = output.rfind(marker)
    if idx < 0:
        return {}
    tail = output[idx + len(marker):]
    start = tail.find("{")
    end = tail.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        parsed = json.loads(tail[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _output_indicates_paypal_success(output: str) -> bool:
    text = output or ""
    if "=== Flow completed successfully ===" not in text:
        return False
    if re.search(r'"status"\s*:\s*"success"', text, re.I):
        return True
    if re.search(r'"state"\s*:\s*"APPROVED"', text, re.I):
        return True
    if "ApproveMemberPaymentMutation HTTP 200" in text and "APPROVED" in text:
        return True
    return False


def run_paypal_protocol_payment(
    cfg: PaypalProtocolRunConfig,
    *,
    log: LogFn | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    log = log or (lambda _line: None)
    cancel_check = cancel_check or (lambda: False)
    timeout = max(60, int(cfg.timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
    cmd, env, cwd = build_protocol_command(cfg)
    ba_token = extract_ba_token(cfg.ba_token or cfg.paypal_link)
    terminal_record = terminal_ba_record(ba_token)
    if terminal_record and not _terminal_ba_retry_allowed():
        message = (
            "该 BA 已在本机进入 CreateMemberAccount 后于 member approve 阶段失败，"
            "属于不可安全重试状态；请使用 fresh BA"
        )
        log(
            "阻止重复协议支付："
            + message
            + f" stage={terminal_record.get('stage') or '<unknown>'}"
        )
        return {
            "status": "failed",
            "returncode": 0,
            "elapsed_s": 0.0,
            "ba_token": sanitize_log_text(ba_token),
            "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
            "country": str(cfg.country or "US").strip().upper() or "US",
            "engine": "bundled-local",
            "engine_root": str(cwd),
            "protocol_result": {},
            "message": message,
            "terminal_ba_record": sanitize_result(terminal_record),
        }
    log("本地 PayPal 协议引擎启动：" + sanitize_log_text(" ".join(cmd)))
    started = time.monotonic()
    output_lines: list[str] = []
    suppress_result_log = False
    result_log_notice_sent = False
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        while True:
            if cancel_check():
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return {"status": "cancelled", "message": "任务已取消", "elapsed_s": round(time.monotonic() - started, 1)}
            if time.monotonic() - started > timeout:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise TimeoutError(f"PayPal 协议支付超时: {timeout}s")
            events = selector.select(timeout=0.2)
            for key, _mask in events:
                line = key.fileobj.readline()
                if line:
                    clean = sanitize_log_text(line.rstrip("\n"))
                    output_lines.append(clean)
                    stripped = clean.strip()
                    if stripped == "RESULT:":
                        suppress_result_log = True
                        if not result_log_notice_sent:
                            log("本地协议引擎已返回 RESULT JSON，详情见结果面板。")
                            result_log_notice_sent = True
                        continue
                    if suppress_result_log and stripped.startswith("="):
                        suppress_result_log = False
                        continue
                    if stripped and not suppress_result_log:
                        log(clean)
            if proc.poll() is not None:
                for line in proc.stdout.readlines():
                    clean = sanitize_log_text(line.rstrip("\n"))
                    output_lines.append(clean)
                    stripped = clean.strip()
                    if stripped == "RESULT:":
                        suppress_result_log = True
                        if not result_log_notice_sent:
                            log("本地协议引擎已返回 RESULT JSON，详情见结果面板。")
                            result_log_notice_sent = True
                        continue
                    if suppress_result_log and stripped.startswith("="):
                        suppress_result_log = False
                        continue
                    if stripped and not suppress_result_log:
                        log(clean)
                break
        rc = proc.wait(timeout=5)
    finally:
        try:
            selector.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        if proc.poll() is None:
            proc.kill()

    output = "\n".join(output_lines)
    parsed = sanitize_result(_parse_result_from_output(output))
    output_success = _output_indicates_paypal_success(output)
    ok = rc == 0 and (str(parsed.get("status") or "").lower() == "success" or output_success)
    if ok and not parsed:
        parsed = {
            "status": "success",
            "inferred_from_log": True,
            "evidence": "Flow completed successfully + approveMemberPayment APPROVED",
        }
    failure_message = parsed.get("message") or parsed.get("error") or ""
    if not ok:
        if str(failure_message) == "approveMemberPayment returned empty result":
            failure_message = "PayPal member approve 阶段失败；CreateMemberAccount 已成功，但当前 BA/EC checkout session 未能完成 approval"
        if not failure_message:
            if "Signup-context browser risk incomplete before CreateMemberAccount" in output:
                failure_message = "CreateMemberAccount 前 signup-context 风控信号不完整；已阻断提交以避免 PayPal OAS_ERROR"
            elif "mtr_sealedResult_missing" in output:
                failure_message = "本地 MTR browser runtime 未生成 sealedResult；请使用 fresh BA 重试，或增加 MTR/headless 等待时间"
            elif "OAS_ERROR" in output and "createMemberAccount" in output:
                failure_message = "PayPal createMemberAccount 返回 OAS_ERROR；通常是 signup-context 风控信号不完整或 BA/代理环境风险过高"
            elif "ApproveMemberPaymentMutation returned errors" in output or "approveMemberPayment returned empty result" in output:
                failure_message = "PayPal member approve 阶段失败；CreateMemberAccount 已成功，但当前 BA/EC checkout session 未能完成 approval"
            elif "PAYER_INVALID_FOR_PAYMENT" in output:
                failure_message = "PayPal 返回 PAYER_INVALID_FOR_PAYMENT；当前 payer 与该 payment/checkout session 不匹配或 BA/EC 已不可继续"
            elif "returned PayPal authchallenge HTML" in output:
                failure_message = "PayPal authchallenge/recaptcha 拦截了 OTP 发起；短信未发送，需更换新 BA/代理会话/风险环境后重试"
            elif "SMSBower OTP confirmation failed after all attempts" in output:
                failure_message = "SMS record OTP 等待超时，未收到本次请求后的新验证码"
            elif "VALIDATION_FAILED" in output:
                failure_message = "PayPal OTP 校验失败，可能拿到了旧码或错误验证码"
    if not ok and _member_approve_terminal_after_create(output, parsed):
        try:
            remember_terminal_ba(
                ba_token,
                reason=str(failure_message or "member approve failed after CreateMemberAccount"),
            )
            log("已记录该 BA 的本机终态：CreateMemberAccount 后 member approve 失败；后续将阻止重复重跑。")
        except Exception:
            pass
    result = {
        "status": "success" if ok else "failed",
        "returncode": rc,
        "elapsed_s": round(time.monotonic() - started, 1),
        "ba_token": sanitize_log_text(ba_token),
        "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
        "country": str(cfg.country or "US").strip().upper() or "US",
        "engine": "bundled-local",
        "engine_root": str(cwd),
        "protocol_result": parsed,
    }
    if not ok:
        result["message"] = failure_message or f"本地协议引擎退出码 {rc}"
    return result
