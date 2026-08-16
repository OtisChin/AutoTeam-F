"""Local PayPal Billing Agreement protocol approval runner.

This module deliberately runs the vendored protocol engine in this repository.
It must not call third-party wrapper services.
"""

import hashlib
import importlib
import importlib.util
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
from types import ModuleType
from typing import Any
from urllib.parse import quote
import urllib.request

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
PHONE_INPUT_SETTLE_SECONDS = 2.0
TERMINAL_BA_FILE = PROJECT_ROOT / "data" / "paypal_protocol_terminal_ba.json"
SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES = {"US", "GB", "NL", "BR", "AU", "CA", "ID", "JP", "MX", "PH", "TH"}
SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES_TEXT = "AU/BR/CA/GB/ID/JP/MX/PH/TH/NL/US"
DEFAULT_SMS_COUNTRY_BY_PAYPAL_COUNTRY = {
    "US": "187",
    "GB": "16",
    "NL": "48",
    "BR": "73",
    "AU": "175",
    "CA": "36",
    "ID": "6",
    "JP": "182",
    "MX": "54",
    "PH": "4",
    "TH": "52",
}
DEFAULT_HEROSMS_COUNTRY_BY_PAYPAL_COUNTRY = dict(DEFAULT_SMS_COUNTRY_BY_PAYPAL_COUNTRY)
DEFAULT_SMSBOWER_COUNTRY_BY_PAYPAL_COUNTRY = dict(DEFAULT_SMS_COUNTRY_BY_PAYPAL_COUNTRY)
DEFAULT_PAYPAL_SMS_SERVICE = "ts"
DEFAULT_HEROSMS_BASE_URL = "https://hero-sms.com/stubs/handler_api.php"
DEFAULT_SMSBOWER_BASE_URL = "https://smsbower.page/stubs/handler_api.php"
DEFAULT_SIGNUP_CARD_COUNTRIES = {"US", "GB"}
WEB_MODULE_NAME = "_autoteam_paypal_agreement_protocol_web"

_WEB_MODULE_LOCK = threading.Lock()
_WEB_MODULE: ModuleType | None = None
_WEB_MODULE_ROOT: Path | None = None


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
    phone_pool_reuse_enabled: bool = False
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
    return f"socks5h://{raw}"


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
        raise ValueError(f"当前 PayPal 协议支付仅开放 {SUPPORTED_PAYPAL_PROTOCOL_COUNTRIES_TEXT}")
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
        "signup-card" if country in DEFAULT_SIGNUP_CARD_COUNTRIES else "auto",
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
    env["PAYPAL_APPROVAL_PATH"] = "signup_card" if country in DEFAULT_SIGNUP_CARD_COUNTRIES else "auto"
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
    env["PAYPAL_SMS_REUSE_ENABLED"] = "1" if bool(cfg.phone_pool_reuse_enabled) else "0"
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


def _protocol_internal_base_url() -> str:
    explicit = str(
        os.getenv("PAYPAL_PROTOCOL_INTERNAL_BASE_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")
    api_base = str(
        os.getenv("AUTOTEAM_API_BASE_URL")
        or os.getenv("AUTOTOKEN_API_BASE_URL")
        or os.getenv("AUTOTOKEN_LOCAL_BASE_URL")
        or ""
    ).strip()
    if api_base:
        return api_base.rstrip("/")
    port = str(os.getenv("AUTOTEAM_API_PORT") or os.getenv("AUTOTOKEN_API_PORT") or os.getenv("API_PORT") or "8799").strip()
    if not re.fullmatch(r"\d{2,5}", port):
        port = "8799"
    return f"http://127.0.0.1:{port}"


def _load_engine_web_module(root: Path) -> ModuleType:
    """Load the PayPal protocol engine's local web runner as an in-process module."""
    global _WEB_MODULE, _WEB_MODULE_ROOT
    resolved_root = root.resolve()
    web_py = resolved_root / "web.py"
    if not web_py.exists():
        raise RuntimeError(f"本地 PayPal 协议引擎 web.py 不存在: {web_py}")
    internal_base = _protocol_internal_base_url()
    os.environ.setdefault("PAYPAL_PROTOCOL_INTERNAL_BASE_URL", internal_base)
    with _WEB_MODULE_LOCK:
        if _WEB_MODULE is not None and _WEB_MODULE_ROOT == resolved_root:
            try:
                setattr(_WEB_MODULE, "PAYPAL_PROTOCOL_INTERNAL_BASE", str(os.getenv("PAYPAL_PROTOCOL_INTERNAL_BASE_URL") or internal_base).rstrip("/"))
            except Exception:
                pass
            return _WEB_MODULE
        root_text = str(resolved_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        spec = importlib.util.spec_from_file_location(WEB_MODULE_NAME, web_py)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载本地 PayPal 协议引擎: {web_py}")
        module = importlib.util.module_from_spec(spec)
        previous_config_module = sys.modules.get("config")
        try:
            # The vendored PayPal engine uses legacy top-level imports such as
            # `from config import USER_AGENT`.  The main application also has
            # another protocol component with a top-level `config.py`; when
            # that component has already been imported, Python may otherwise
            # reuse the wrong sys.modules["config"] and fail before the PayPal
            # engine starts.
            sys.modules.pop("config", None)
            sys.modules[WEB_MODULE_NAME] = module
            spec.loader.exec_module(module)
        finally:
            if previous_config_module is not None:
                sys.modules["config"] = previous_config_module
            else:
                sys.modules.pop("config", None)
        try:
            setattr(module, "PAYPAL_PROTOCOL_INTERNAL_BASE", str(os.getenv("PAYPAL_PROTOCOL_INTERNAL_BASE_URL") or internal_base).rstrip("/"))
        except Exception:
            pass
        _WEB_MODULE = module
        _WEB_MODULE_ROOT = resolved_root
        return module


def _extract_sms_code(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("code", "smsCode", "sms_code", "otp", "pin"):
            code = str(value.get(key) or "").strip()
            if re.fullmatch(r"\d{4,8}", code):
                return code
        for key in ("text", "sms", "message", "lastSms", "content"):
            match = re.search(r"\b\d{4,8}\b", str(value.get(key) or ""))
            if match:
                return match.group(0)
        for child in value.values():
            code = _extract_sms_code(child)
            if code:
                return code
    elif isinstance(value, list):
        for child in value:
            code = _extract_sms_code(child)
            if code:
                return code
    else:
        match = re.search(r"\b\d{4,8}\b", str(value or ""))
        if match:
            return match.group(0)
    return ""


def _read_sms_record_code(record_url: str, timeout_seconds: float, poll_seconds: float) -> str:
    url = str(record_url or "").strip()
    if not url:
        return ""
    deadline = time.monotonic() + max(1.0, float(timeout_seconds or 1.0))
    interval = max(0.2, float(poll_seconds or 3.0))
    while time.monotonic() <= deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoToken/PayPalProtocolSmsRecord"})
            with urllib.request.urlopen(req, timeout=min(20.0, max(1.0, deadline - time.monotonic()))) as resp:
                body = resp.read(1024 * 1024).decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(body)
            except Exception:
                payload = body
            code = _extract_sms_code(payload)
            if code:
                return code
        except Exception:
            pass
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    return ""


def _load_paypal_sms_provider_module(root: Path) -> ModuleType:
    root_text = str(root.resolve())
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return importlib.import_module("paypal.smsbower")


def _build_protocol_sms_provider(cfg: PaypalProtocolRunConfig, *, engine_root: Path) -> Any:
    sms_provider = normalize_sms_provider(cfg.sms_provider)
    if sms_provider == "sms_record":
        return None
    providers = _load_paypal_sms_provider_module(engine_root)
    wait_seconds = max(1.0, float(cfg.sms_record_wait_seconds or 300))
    poll_seconds = max(0.2, float(cfg.sms_record_poll_seconds or 3.0))
    country = str(cfg.country or "US").strip().upper() or "US"
    if sms_provider == "hero_sms_rent":
        return providers.build_hero_sms_rent_provider(
            phone_number=str(cfg.phone or "").strip(),
            base_url=_backend_sms_base_url(sms_provider),
            country=_backend_sms_country(sms_provider, country),
            paypal_country=country,
            wait_seconds=wait_seconds,
            poll_interval_seconds=poll_seconds,
            reuse_enabled=bool(cfg.phone_pool_reuse_enabled),
        )
    if sms_provider in {"hero_sms", "smsbower"}:
        return providers.build_sms_activate_provider(
            provider=sms_provider,
            enabled=True,
            base_url=_backend_sms_base_url(sms_provider),
            service=_backend_sms_service(),
            country=_backend_sms_country(sms_provider, country),
            paypal_country=country,
            wait_seconds=wait_seconds,
            poll_interval_seconds=poll_seconds,
            min_price=cfg.sms_min_price,
            max_price=cfg.sms_max_price,
            preferred_price=cfg.sms_preferred_price,
            reuse_enabled=bool(cfg.phone_pool_reuse_enabled),
        )
    raise ValueError("不支持的 PayPal 手机接码平台")


def _job_snapshot(job: Any, *, log_offset: int = 0) -> dict[str, Any]:
    try:
        data = job.to_dict(include_logs=True, log_offset=log_offset)
        return data if isinstance(data, dict) else {}
    except TypeError:
        data = job.to_dict()
        return data if isinstance(data, dict) else {}


def _awaiting_prompt(snapshot: dict[str, Any]) -> str:
    for key in ("awaiting_prompt", "prompt", "input_prompt"):
        value = str(snapshot.get(key) or "").strip()
        if value:
            return value
    return ""


def _prompt_requests_new_phone(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    if any(
        marker in text
        for marker in (
            "发送验证码失败",
            "failed to initiate otp",
            "failed to send",
            "phone timed out",
            "retryable with a clean task/session",
        )
    ):
        return True
    return bool(
        re.search(r"请(?:重新)?输入新(?:的)?手机(?:号|号码)", text)
        or re.search(r"(?:enter|input|provide|submit)\s+(?:a\s+)?(?:new|different)\s+phone", text)
    )


def _stop_before_otp_enabled() -> bool:
    return str(os.getenv("PAYPAL_PROTOCOL_STOP_BEFORE_OTP") or "").strip().lower() in {"1", "true", "yes", "on"}


def _abandon_otp_activation(otp_provider: Any, activation: Any, reason: str) -> None:
    if otp_provider is None or activation is None:
        return
    if hasattr(otp_provider, "abandon"):
        try:
            otp_provider.abandon(activation, reason)
            return
        except Exception:
            pass
    if hasattr(otp_provider, "register_confirmation_result"):
        try:
            otp_provider.register_confirmation_result(activation, False)
        except Exception:
            pass


def _run_paypal_protocol_web_payment(
    cfg: PaypalProtocolRunConfig,
    *,
    log: LogFn,
    cancel_check: Callable[[], bool],
) -> dict[str, Any]:
    root = _engine_root()
    web = _load_engine_web_module(root)
    ba_token = extract_ba_token(cfg.ba_token or cfg.paypal_link)
    if not ba_token:
        raise ValueError("缺少有效 PayPal BA token/link")
    country = str(cfg.country or "US").strip().upper() or "US"
    sms_provider = normalize_sms_provider(cfg.sms_provider)
    phone = str(cfg.phone or "").strip()
    otp_provider = None
    activation = None
    if sms_provider == "sms_record":
        if not phone:
            raise ValueError("缺少 PayPal 注册手机号")
        if not str(cfg.sms_record_url or "").strip():
            raise ValueError("缺少 SMS record URL")
    else:
        otp_provider = _build_protocol_sms_provider(cfg, engine_root=root)
        if otp_provider is None:
            raise ValueError("不支持的 PayPal 手机接码平台")
        activation = otp_provider.reserve_number()
        phone = str(getattr(activation, "phone_number", None) or phone or "").strip()
        if not phone:
            raise RuntimeError("手机号供应商未返回可用号码")

    proxy = normalize_proxy_url(cfg.proxy_url)
    owner_device_id = f"autoteam-local-{os.getpid()}-{threading.get_ident()}-{int(time.time() * 1000)}"
    job = web.create_job(
        owner_device_id=owner_device_id,
        ba_token=ba_token,
        phone=phone,
        debug=bool(cfg.debug),
        max_card_attempts=5,
        manual_funding=False,
        agreement_only=False,
        country=country,
        buyer_mode="identity_elevation",
        proxy_pool=[proxy] if proxy else [],
        exclude_public_metrics=True,
    )
    log(f"PayPal协议任务已创建：{getattr(job, 'id', '<unknown>')}")
    started = time.monotonic()
    timeout = max(60, int(cfg.timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
    log_offset = 0
    otp_submitted = False
    phone_input_settle_until = 0.0
    last_snapshot: dict[str, Any] = {}
    confirmed = False
    try:
        while True:
            if cancel_check():
                try:
                    job.cancel()
                except Exception:
                    pass
                return {"status": "cancelled", "message": "任务已取消", "elapsed_s": round(time.monotonic() - started, 1)}
            if time.monotonic() - started > timeout:
                try:
                    job.cancel()
                except Exception:
                    pass
                raise TimeoutError(f"PayPal 协议支付超时: {timeout}s")

            snapshot = _job_snapshot(job, log_offset=log_offset)
            if snapshot:
                last_snapshot = snapshot
            logs = snapshot.get("logs") if isinstance(snapshot.get("logs"), list) else []
            log_offset += len(logs)
            for entry in logs:
                message = entry.get("message") if isinstance(entry, dict) else entry
                if message:
                    log(str(message))

            status = str(snapshot.get("status") or getattr(job, "status", "") or "").strip().lower()
            if status in {"completed", "failed", "cancelled"}:
                break

            if snapshot.get("awaiting_otp") or status == "awaiting_otp":
                prompt = _awaiting_prompt(snapshot)
                if _stop_before_otp_enabled():
                    try:
                        job.cancel()
                    except Exception:
                        pass
                    log("已按测试开关在 OTP 输入前停止，未读取或提交验证码。")
                    return {
                        "status": "awaiting_otp",
                        "returncode": None,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "ba_token": sanitize_log_text(ba_token),
                        "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
                        "country": country,
                        "engine": "paypal-protocol",
                        "engine_root": str(root),
                        "protocol_result": sanitize_result(last_snapshot.get("result") or {}),
                        "awaiting_prompt": sanitize_log_text(prompt),
                        "message": "已按测试开关在 OTP 输入前停止",
                    }
                if _prompt_requests_new_phone(prompt):
                    if sms_provider == "sms_record":
                        try:
                            job.cancel()
                        except Exception:
                            pass
                        return {
                            "status": "failed",
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "ba_token": sanitize_log_text(ba_token),
                            "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
                            "country": country,
                            "engine": "paypal-protocol",
                            "engine_root": str(root),
                            "protocol_result": sanitize_result(last_snapshot.get("result") or {}),
                            "message": "PayPal 要求换号，但 sms_record 固定号码无法自动换号",
                        }
                    _abandon_otp_activation(otp_provider, activation, "paypal_requested_new_phone")
                    try:
                        activation = otp_provider.reserve_number() if otp_provider is not None and hasattr(otp_provider, "reserve_number") else None
                    except Exception as exc:
                        try:
                            job.cancel()
                        except Exception:
                            pass
                        return {
                            "status": "failed",
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "ba_token": sanitize_log_text(ba_token),
                            "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
                            "country": country,
                            "engine": "paypal-protocol",
                            "engine_root": str(root),
                            "protocol_result": sanitize_result(last_snapshot.get("result") or {}),
                            "message": sanitize_log_text(str(exc)),
                        }
                    phone = str(getattr(activation, "phone_number", None) or "").strip()
                    if not phone:
                        try:
                            job.cancel()
                        except Exception:
                            pass
                        return {
                            "status": "failed",
                            "elapsed_s": round(time.monotonic() - started, 1),
                            "ba_token": sanitize_log_text(ba_token),
                            "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
                            "country": country,
                            "engine": "paypal-protocol",
                            "engine_root": str(root),
                            "protocol_result": sanitize_result(last_snapshot.get("result") or {}),
                            "message": "PayPal 要求换号，但手机号供应商未返回新的可用号码",
                        }
                    job.submit_input(phone)
                    otp_submitted = False
                    phone_input_settle_until = time.monotonic() + max(0.0, float(PHONE_INPUT_SETTLE_SECONDS))
                    log("PayPal 要求换号，已提交新的接码号码。")
                    continue

                if otp_submitted:
                    time.sleep(0.5)
                    continue

                if time.monotonic() < phone_input_settle_until:
                    time.sleep(0.2)
                    continue

                if sms_provider == "sms_record":
                    code = _read_sms_record_code(
                        str(cfg.sms_record_url or ""),
                        cfg.sms_record_wait_seconds,
                        cfg.sms_record_poll_seconds,
                    )
                else:
                    if otp_provider is not None and activation is not None and hasattr(otp_provider, "mark_sms_sent"):
                        otp_provider.mark_sms_sent(activation)
                    code = (
                        otp_provider.wait_for_code(activation, timeout_seconds=cfg.sms_record_wait_seconds)
                        if otp_provider is not None and activation is not None and hasattr(otp_provider, "wait_for_code")
                        else ""
                    )
                if not code:
                    if sms_provider != "sms_record" and otp_provider is not None and activation is not None:
                        _abandon_otp_activation(otp_provider, activation, "sms_timeout")
                    try:
                        job.cancel()
                    except Exception:
                        pass
                    message = "手机接码平台 OTP 等待超时，本轮 PayPal 协议支付已停止，请重试换号"
                    log(message)
                    return {
                        "status": "failed",
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "ba_token": sanitize_log_text(ba_token),
                        "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
                        "country": country,
                        "engine": "paypal-protocol",
                        "engine_root": str(root),
                        "protocol_result": sanitize_result(last_snapshot.get("result") or {}),
                        "message": message,
                    }
                job.submit_input(str(code))
                otp_submitted = True
                log("已从接码通道获取验证码并提交到 PayPal协议任务。")
                continue

            if snapshot.get("awaiting_captcha") or status == "awaiting_captcha":
                return {
                    "status": "failed",
                    "elapsed_s": round(time.monotonic() - started, 1),
                    "ba_token": sanitize_log_text(ba_token),
                    "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
                    "country": country,
                    "engine": "paypal-protocol",
                    "engine_root": str(root),
                    "protocol_result": sanitize_result(snapshot.get("result") or {}),
                    "message": "PayPal协议需要人工 CAPTCHA/浏览器输入，AutoTeam 后台任务无法继续",
                }
            time.sleep(0.5)

        snapshot = last_snapshot or _job_snapshot(job)
        status = str(snapshot.get("status") or getattr(job, "status", "") or "").strip().lower()
        parsed = sanitize_result(snapshot.get("result") or {})
        ok = status == "completed" and (
            not isinstance(parsed, dict)
            or str(parsed.get("status") or "success").strip().lower() == "success"
        )
        confirmed = bool(ok)
        result = {
            "status": "success" if ok else ("cancelled" if status == "cancelled" else "failed"),
            "returncode": 0 if ok else 1,
            "elapsed_s": round(time.monotonic() - started, 1),
            "ba_token": sanitize_log_text(ba_token),
            "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
            "country": country,
            "engine": "paypal-protocol",
            "engine_root": str(root),
            "protocol_result": parsed,
        }
        if not ok:
            result["message"] = (
                snapshot.get("error")
                or snapshot.get("stage")
                or (parsed.get("error") if isinstance(parsed, dict) else "")
                or "PayPal协议执行失败"
            )
        return result
    finally:
        if otp_provider is not None and activation is not None and hasattr(otp_provider, "register_confirmation_result"):
            try:
                otp_provider.register_confirmation_result(activation, confirmed)
            except Exception:
                pass


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
    ba_token = extract_ba_token(cfg.ba_token or cfg.paypal_link)
    engine_root = _engine_root()
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
            "engine": "paypal-protocol",
            "engine_root": str(engine_root),
            "protocol_result": {"status": "failed", "terminal_ba_record": terminal_record},
            "message": message,
        }
    try:
        result = _run_paypal_protocol_web_payment(cfg, log=log, cancel_check=cancel_check)
    except Exception as exc:
        result = {
            "status": "failed",
            "returncode": None,
            "elapsed_s": 0,
            "ba_token": sanitize_log_text(ba_token),
            "paypal_link": sanitize_log_text(paypal_approve_url(ba_token)),
            "country": str(cfg.country or "US").strip().upper() or "US",
            "engine": "paypal-protocol",
            "engine_root": str(engine_root),
            "protocol_result": {"status": "failed"},
            "message": sanitize_log_text(str(exc)),
        }
    if result.get("status") != "success" and _member_approve_terminal_after_create("", result.get("protocol_result") if isinstance(result.get("protocol_result"), dict) else {}):
        try:
            remember_terminal_ba(
                ba_token,
                reason=str(result.get("message") or "member approve failed after CreateMemberAccount"),
            )
            log("已记录该 BA 的本机终态：CreateMemberAccount 后 member approve 失败；后续将阻止重复重跑。")
        except Exception:
            pass
    return sanitize_result(result)
