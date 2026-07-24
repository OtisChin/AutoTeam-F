"""Local PayPal Billing Agreement protocol approval runner.

This module deliberately runs the vendored protocol engine in this repository.
It must not call third-party wrapper services.
"""

import hashlib
import json
import os
import queue
import re
import selectors
import subprocess
import sys
import threading
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
SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES = {"US", "GB", "NL", "BR"}
DEFAULT_SMS_COUNTRY_BY_PAYPAL_COUNTRY = {"US": "187", "GB": "16", "NL": "48", "BR": "73"}
DEFAULT_HEROSMS_COUNTRY_BY_PAYPAL_COUNTRY = {"US": "187", "GB": "16", "NL": "48", "BR": "73"}
DEFAULT_SMSBOWER_COUNTRY_BY_PAYPAL_COUNTRY = {"US": "187", "GB": "16", "NL": "48", "BR": "73"}
DEFAULT_PAYPAL_SMS_SERVICE = "ts"
DEFAULT_HEROSMS_BASE_URL = "https://hero-sms.com/stubs/handler_api.php"
DEFAULT_SMSBOWER_BASE_URL = "https://smsbower.page/stubs/handler_api.php"


@dataclass(slots=True)
class PaypalProtocolRunConfig:
    ba_token: str = ""
    paypal_link: str = ""
    phone: str = ""
    sms_record_url: str = ""
    sms_provider: str = "sms_record"
    sms_api_key: str = ""
    sms_base_url: str = ""
    sms_service: str = "ts"
    sms_country: str = ""
    sms_min_price: str = ""
    sms_max_price: str = ""
    sms_preferred_price: str = ""
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
    text = re.sub(r"(?i)(--sms-api-key\s+)\S+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(--proxy-url\s+)\S+", r"\1<redacted>", text)
    text = _mask_ba(text)
    return text


def sanitize_result(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("password", "secret", "access_token", "cookie", "api_key")):
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


def _load_project_env() -> dict[str, str]:
    result: dict[str, str] = {}
    path = PROJECT_ROOT / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return result
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def _env_value(*names: str) -> str:
    project_env = _load_project_env()
    for name in names:
        value = str(os.getenv(name) or project_env.get(name) or "").strip()
        if value:
            return value
    return ""


def normalize_sms_provider(value: str | None = None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"", "sms_record", "smscc", "record", "fixed_url"}:
        return "sms_record"
    if text in {"hero", "herosms", "hero_sms"}:
        return "hero_sms"
    if text in {"hero_sms_rent", "herosms_rent", "hero_rent", "hero_long", "hero_sms_long"}:
        return "hero_sms_rent"
    if text in {"smsbower", "sms_bower"}:
        return "smsbower"
    return text


def _default_sms_country(provider_country: str, paypal_country: str) -> str:
    raw = str(provider_country or "").strip()
    if raw:
        return raw
    return DEFAULT_SMS_COUNTRY_BY_PAYPAL_COUNTRY.get(str(paypal_country or "").strip().upper(), "187")


def _backend_sms_service() -> str:
    return _env_value("PAYPAL_SMS_SERVICE") or DEFAULT_PAYPAL_SMS_SERVICE


def _backend_sms_country(provider: str, paypal_country: str) -> str:
    # Country ID is always derived from the selected PayPal payment country.
    # Do not let the web payload or a global PAYPAL_SMS_COUNTRY override it.
    country = str(paypal_country or "").strip().upper()
    normalized = normalize_sms_provider(provider)
    if normalized in {"hero_sms", "hero_sms_rent"}:
        return (
            _env_value(f"PAYPAL_HERO_SMS_COUNTRY_{country}", f"PAYPAL_HEROSMS_COUNTRY_{country}")
            or DEFAULT_HEROSMS_COUNTRY_BY_PAYPAL_COUNTRY.get(country, "187")
        )
    if normalized == "smsbower":
        return (
            _env_value(f"PAYPAL_SMSBOWER_COUNTRY_{country}")
            or DEFAULT_SMSBOWER_COUNTRY_BY_PAYPAL_COUNTRY.get(country, "187")
        )
    return DEFAULT_SMS_COUNTRY_BY_PAYPAL_COUNTRY.get(country, "187")


def _backend_sms_base_url(provider: str) -> str:
    normalized = normalize_sms_provider(provider)
    if normalized in {"hero_sms", "hero_sms_rent"}:
        return (
            _env_value(
                "PAYPAL_HERO_SMS_BASE_URL",
                "PAYPAL_HEROSMS_BASE_URL",
                "OAUTH_HERO_SMS_BASE_URL",
                "GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL",
            )
            or DEFAULT_HEROSMS_BASE_URL
        )
    if normalized == "smsbower":
        return (
            _env_value(
                "PAYPAL_SMSBOWER_BASE_URL",
                "SMSBOWER_BASE_URL",
                "OAUTH_SMSBOWER_BASE_URL",
                "GOPAY_AUTO_SIGNUP_SMSBOWER_BASE_URL",
            )
            or DEFAULT_SMSBOWER_BASE_URL
        )
    return ""


def _backend_sms_api_key(provider: str) -> str:
    normalized = normalize_sms_provider(provider)
    if normalized in {"hero_sms", "hero_sms_rent"}:
        return _env_value(
            "PAYPAL_HERO_SMS_API_KEY",
            "PAYPAL_HEROSMS_API_KEY",
            "HERO_SMS_API_KEY",
            "HEROSMS_API_KEY",
            "OAUTH_HERO_SMS_API_KEY",
            "GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY",
        )
    if normalized == "smsbower":
        return _env_value(
            "PAYPAL_SMSBOWER_API_KEY",
            "SMSBOWER_API_KEY",
            "OAUTH_SMSBOWER_API_KEY",
            "GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY",
        )
    return ""


def build_protocol_command(cfg: PaypalProtocolRunConfig, *, engine_root: Path | None = None) -> tuple[list[str], dict[str, str], Path]:
    root = (engine_root or _engine_root()).resolve()
    main_py = _engine_main(root)
    ba_token = extract_ba_token(cfg.ba_token or cfg.paypal_link)
    if not ba_token:
        raise ValueError("缺少有效 PayPal BA token/link")
    country = str(cfg.country or "US").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        country = "US"
    if country not in SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES:
        raise ValueError("当前本地协议支付仅开放 US/GB/NL/BR")
    sms_provider = normalize_sms_provider(cfg.sms_provider)
    if sms_provider == "sms_record":
        if not str(cfg.phone or "").strip():
            raise ValueError("缺少 PayPal 注册手机号")
        if not str(cfg.sms_record_url or "").strip():
            raise ValueError("缺少 SMS record URL")
    elif sms_provider in {"hero_sms", "hero_sms_rent", "smsbower"}:
        if sms_provider == "hero_sms_rent" and not str(cfg.phone or "").strip():
            raise ValueError("缺少 HeroSMS 长效号码")
        # API key may be supplied by .env/environment; do not require it in the
        # HTTP request payload.
        pass
    else:
        raise ValueError("不支持的 PayPal 手机接码平台")

    cmd = [
        sys.executable,
        "-u",
        str(main_py),
        "--ba-token",
        ba_token,
        "--sms-record-wait",
        str(max(60, int(cfg.sms_record_wait_seconds or 300))),
        "--sms-record-poll",
        str(max(1.0, float(cfg.sms_record_poll_seconds or 3.0))),
        "--country",
        country,
        "--approval-path",
        "create-member-no-fi" if country == "US" else "auto",
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
    if sms_provider == "sms_record":
        cmd.extend([
            "--sms-provider",
            "sms-record",
            "--phone",
            str(cfg.phone).strip(),
            "--sms-record-url",
            str(cfg.sms_record_url).strip(),
        ])
    else:
        sms_service = _backend_sms_service()
        sms_country = _backend_sms_country(sms_provider, country)
        cmd.extend([
            "--sms-provider",
            "hero-sms-rent" if sms_provider == "hero_sms_rent" else ("hero-sms" if sms_provider == "hero_sms" else "smsbower"),
            "--sms-service",
            sms_service,
            "--sms-country",
            sms_country,
            "--sms-number-wait",
            "60",
        ])
        if sms_provider == "hero_sms_rent":
            cmd.extend(["--phone", str(cfg.phone).strip()])
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
    env["PAYPAL_APPROVAL_PATH"] = "create_member_no_fi" if country == "US" else "auto"
    env["PAYPAL_COUNTRY"] = country
    # The verified AutoTeam-F tuple is a normal preflight run, not strict lab
    # mode.  Parent shells may export PAYPAL_STRICT_BROWSER_RISK=1 while doing
    # research; do not let that leak into the web runner and reject otherwise
    # usable runs with diagnostic-only blockers such as mtr_sealedResult_missing.
    env["PAYPAL_STRICT_BROWSER_RISK"] = "0"
    env["PAYPAL_ALLOW_SYNTHETIC_CAPTCHA"] = "0"
    env["PAYPAL_SMS_PROVIDER"] = sms_provider
    env["PAYPAL_SMS_SERVICE"] = _backend_sms_service()
    env["PAYPAL_SMS_COUNTRY"] = _backend_sms_country(sms_provider, country)
    env["PAYPAL_SMS_NUMBER_WAIT_SECONDS"] = "60"
    if sms_provider in {"hero_sms", "hero_sms_rent", "smsbower"}:
        env["PAYPAL_SMS_BASE_URL"] = _backend_sms_base_url(sms_provider)
        if sms_provider in {"hero_sms", "hero_sms_rent"}:
            env["PAYPAL_HERO_SMS_BASE_URL"] = _backend_sms_base_url(sms_provider)
            key = _backend_sms_api_key(sms_provider)
            if key:
                env["PAYPAL_HERO_SMS_API_KEY"] = key
        elif sms_provider == "smsbower":
            env["PAYPAL_SMSBOWER_BASE_URL"] = _backend_sms_base_url(sms_provider)
            key = _backend_sms_api_key(sms_provider)
            if key:
                env["PAYPAL_SMSBOWER_API_KEY"] = key
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
    if terminal_record:
        message = "该 BA 已在本机进入 CreateMemberAccount 后于 member approve 阶段失败，属于不可安全重试状态；请使用 fresh BA"
        log(
            "检测到该 BA 曾在本机进入 CreateMemberAccount 后于 member approve 阶段失败；"
            "阻止重复协议支付，请使用 fresh BA。"
            + f" stage={terminal_record.get('stage') or '<unknown>'}"
        )
        return {
            "status": "failed",
            "returncode": None,
            "elapsed_s": 0,
            "ba_token": sanitize_log_text(ba_token),
            "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
            "country": str(cfg.country or "US").strip().upper() or "US",
            "engine": "bundled-local",
            "engine_root": str(cwd),
            "protocol_result": {"status": "failed", "terminal_ba_record": terminal_record},
            "message": message,
        }
    log("本地 PayPal 协议引擎启动：" + sanitize_log_text(" ".join(cmd)))
    started = time.monotonic()
    output_lines: list[str] = []
    suppress_result_log = False
    result_log_notice_sent = False

    def handle_output_line(line: str) -> None:
        nonlocal suppress_result_log, result_log_notice_sent
        clean = sanitize_log_text(line.rstrip("\n"))
        output_lines.append(clean)
        stripped = clean.strip()
        if stripped == "RESULT:":
            suppress_result_log = True
            if not result_log_notice_sent:
                log("本地协议引擎已返回 RESULT JSON，详情见结果面板。")
                result_log_notice_sent = True
            return
        if suppress_result_log and stripped.startswith("="):
            suppress_result_log = False
            return
        if stripped and not suppress_result_log:
            log(clean)

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    selector: selectors.BaseSelector | None = None
    line_queue: queue.Queue[str | None] | None = None
    reader_thread: threading.Thread | None = None
    try:
        assert proc.stdout is not None
        if os.name == "nt":
            line_queue = queue.Queue()

            def _reader() -> None:
                assert proc.stdout is not None
                try:
                    for queued_line in proc.stdout:
                        line_queue.put(queued_line)
                finally:
                    line_queue.put(None)

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()
        else:
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
            if line_queue is not None:
                lines: list[str | None] = []
                try:
                    lines.append(line_queue.get(timeout=0.2))
                    while True:
                        lines.append(line_queue.get_nowait())
                except queue.Empty:
                    pass
                for line in lines:
                    if line is None:
                        continue
                    handle_output_line(line)
            else:
                assert selector is not None
                events = selector.select(timeout=0.2)
                for key, _mask in events:
                    line = key.fileobj.readline()
                    if line:
                        handle_output_line(line)
            if proc.poll() is not None:
                if line_queue is not None:
                    if reader_thread is not None:
                        reader_thread.join(timeout=1)
                    while True:
                        try:
                            line = line_queue.get_nowait()
                        except queue.Empty:
                            break
                        if line is None:
                            continue
                        handle_output_line(line)
                else:
                    for line in proc.stdout.readlines():
                        handle_output_line(line)
                break
        rc = proc.wait(timeout=5)
    finally:
        if selector is not None:
            try:
                selector.close()
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
            elif "SMS provider OTP confirmation failed after all attempts" in output or "SMSBower OTP confirmation failed after all attempts" in output:
                failure_message = "手机接码平台 OTP 等待超时，未收到本次请求后的新验证码"
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
