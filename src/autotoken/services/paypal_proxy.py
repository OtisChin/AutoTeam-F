"""PayPal task proxy preparation and selection helpers."""

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from autotoken.services import proxy_runtime
from autotoken.settings.config import normalize_proxy_url

PAYPAL_TUNNEL_ERROR_HINTS = (
    "err_tunnel_connection_failed",
    "tunnel connection failed",
)


@dataclass(frozen=True)
class PayPalProxyRuntime:
    proxy_api_url: str
    proxy_api_provider: str
    normalized_proxy_url: str
    normalized_proxy_pool: list[str]
    bind_proxy_url: str
    provider_proxy_url: str = ""


def is_paypal_tunnel_connection_error(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and any(hint in text for hint in PAYPAL_TUNNEL_ERROR_HINTS)


def paypal_protocol_socks_invalid_response(value: Any) -> bool:
    text = str(value or "").lower()
    return (
        "curl: (97)" in text
        or "invalid version in initial socks5 response" in text
        or "received invalid version in initial socks5 response" in text
    )


def paypal_protocol_http_proxy_fallback_url(proxy_url: str | None) -> str:
    try:
        normalized = normalize_proxy_url(proxy_url)
    except Exception:
        return ""
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"socks5", "socks5h"}:
        return ""
    if not (parsed.username or parsed.password):
        return ""
    return urlunsplit(("http", parsed.netloc, "", "", ""))


def paypal_requests_proxy_map(proxy_url: str | None) -> dict[str, str]:
    raw = str(proxy_url or "").strip()
    if not raw:
        return {}
    try:
        normalized = normalize_proxy_url(raw)
    except Exception:
        normalized = raw
    if normalized.lower().startswith("socks5://"):
        normalized = f"socks5h://{normalized[len('socks5://') :]}"
    return {"http": normalized, "https": normalized}


def paypal_proxy_exit_location(
    proxy_url: str | None,
    *,
    session_factory: Callable[[], Any] = requests.Session,
    on_error: Callable[[Exception], None] | None = None,
) -> dict[str, str]:
    """Best-effort proxy geo probe used only to choose JP signup address."""
    proxies = paypal_requests_proxy_map(proxy_url)
    if not proxies:
        return {}
    try:
        session = session_factory()
        session.trust_env = False
        session.proxies = proxies
        resp = session.get(
            "http://ip-api.com/json/?fields=status,countryCode,regionName,city,query",
            timeout=12,
        )
        if int(getattr(resp, "status_code", 0) or 0) >= 400:
            return {}
        payload = resp.json()
        if str(payload.get("status") or "").lower() == "fail":
            return {}
        return {
            "country_code": str(payload.get("countryCode") or "").strip().upper(),
            "region": str(payload.get("regionName") or "").strip(),
            "city": str(payload.get("city") or "").strip(),
            "ip": str(payload.get("query") or "").strip(),
        }
    except Exception as exc:
        if on_error:
            on_error(exc)
        return {}


def prepare_paypal_proxy_runtime(
    *,
    proxy_url: str | None,
    proxy_pool: list[Any] | tuple[Any, ...] | None,
    proxy_pool_text: str | None,
    proxy_api_provider: str | None,
    proxy_api_url: str | None,
    paypal_country: str,
    protocol_no_card: bool,
    paypal_ba_proxy_region: str,
    default_proxy_entry: Callable[[str], str],
    paypal_jp_proxy_url: str | None = None,
    paypal_us_proxy_url: str | None = None,
) -> PayPalProxyRuntime:
    raw_proxy_url = str(proxy_url or "").strip()
    api_url = str(proxy_api_url or "").strip()
    provider = proxy_runtime.normalize_proxy_api_provider(proxy_api_provider) if proxy_api_provider else ""
    if api_url and not provider:
        provider = proxy_runtime.infer_proxy_api_provider_from_url(api_url)
    if provider and not api_url:
        api_url = proxy_runtime.default_paypal_proxy_api_url(
            provider,
            country=paypal_country,
            protocol_no_card=protocol_no_card,
        )

    raw_proxy_pool = proxy_runtime.parse_proxy_pool_values(proxy_pool, proxy_pool_text)
    static_proxy_pool: list[str] = []
    for raw_proxy_entry in raw_proxy_pool:
        if proxy_runtime.is_proxy_api_url(raw_proxy_entry):
            if not api_url:
                api_url = raw_proxy_entry
                provider = proxy_runtime.normalize_proxy_api_provider(
                    proxy_api_provider or proxy_runtime.infer_proxy_api_provider_from_url(api_url) or "1024proxy"
                )
            continue
        static_proxy_pool.append(raw_proxy_entry)

    if protocol_no_card and api_url:
        api_url = proxy_runtime.proxy_api_url_with_region(api_url, paypal_ba_proxy_region)

    try:
        normalized_proxy_url = normalize_proxy_url(raw_proxy_url) if raw_proxy_url else ""
    except Exception as exc:
        raise ValueError(f"代理格式错误: {raw_proxy_url} ({exc})") from exc

    def normalize_sticky_proxy(raw_value: str | None, label: str) -> str:
        raw = str(raw_value or "").strip()
        if not raw:
            return ""
        try:
            return normalize_proxy_url(raw)
        except Exception as exc:
            raise ValueError(f"{label} sticky 代理格式错误: {raw} ({exc})") from exc

    jp_proxy_url = normalize_sticky_proxy(paypal_jp_proxy_url, "JP")
    us_proxy_url = normalize_sticky_proxy(paypal_us_proxy_url, "US")
    provider_proxy_url = ""
    explicit_selected_proxy = ""
    if protocol_no_card:
        ba_region = str(paypal_ba_proxy_region or "").strip().upper()
        explicit_selected_proxy = us_proxy_url if ba_region == "US" else jp_proxy_url
        provider_proxy_url = us_proxy_url
    else:
        country = str(paypal_country or "").strip().upper()
        if country == "JP":
            explicit_selected_proxy = jp_proxy_url
        elif country == "US":
            explicit_selected_proxy = us_proxy_url

    if explicit_selected_proxy:
        normalized_proxy_url = explicit_selected_proxy

    if not normalized_proxy_url and provider:
        default_entry = default_proxy_entry(provider)
        if default_entry:
            try:
                normalized_proxy_url = normalize_proxy_url(default_entry)
            except Exception as exc:
                raise ValueError(f"默认代理格式错误: {default_entry} ({exc})") from exc

    if protocol_no_card and normalized_proxy_url:
        normalized_proxy_url = proxy_runtime.proxy_url_for_region(normalized_proxy_url, paypal_ba_proxy_region)

    normalized_proxy_pool: list[str] = []
    for raw_pool_proxy in static_proxy_pool:
        try:
            normalized = normalize_proxy_url(raw_pool_proxy)
        except Exception as exc:
            raise ValueError(f"动态代理池格式错误: {raw_pool_proxy} ({exc})") from exc
        if protocol_no_card and normalized:
            normalized = proxy_runtime.proxy_url_for_region(normalized, paypal_ba_proxy_region)
        if normalized and normalized not in normalized_proxy_pool:
            normalized_proxy_pool.append(normalized)

    return PayPalProxyRuntime(
        proxy_api_url=api_url,
        proxy_api_provider=provider,
        normalized_proxy_url=normalized_proxy_url,
        normalized_proxy_pool=normalized_proxy_pool,
        bind_proxy_url=normalized_proxy_url,
        provider_proxy_url=provider_proxy_url,
    )


def select_paypal_proxy(
    runtime: PayPalProxyRuntime,
    *,
    fetch_proxy_from_api_url: Callable[..., str],
    default_auth_scheme: str,
) -> str:
    if runtime.proxy_api_url:
        fetched_proxy = fetch_proxy_from_api_url(
            runtime.proxy_api_url,
            default_auth_scheme=default_auth_scheme,
            provider=runtime.proxy_api_provider,
        )
        if fetched_proxy:
            return fetched_proxy
        if runtime.bind_proxy_url:
            return runtime.bind_proxy_url
        raise RuntimeError("Cliproxy API 已触发换 IP，但未返回代理；请同时填写代理 URL 作为连接入口")
    if runtime.normalized_proxy_pool:
        return random.choice(runtime.normalized_proxy_pool)
    return runtime.bind_proxy_url


def select_paypal_provider_proxy(
    runtime: PayPalProxyRuntime,
    *,
    selected_proxy_url: str,
    protocol_no_card: bool,
    fetch_proxy_from_api_url: Callable[..., str],
    default_auth_scheme: str,
) -> str:
    selected = str(selected_proxy_url or "").strip()
    if not protocol_no_card:
        return ""
    if runtime.provider_proxy_url:
        return runtime.provider_proxy_url
    if runtime.proxy_api_url:
        provider_api_url = proxy_runtime.proxy_api_url_with_region(runtime.proxy_api_url, "US")
        fetched_proxy = fetch_proxy_from_api_url(
            provider_api_url,
            default_auth_scheme=default_auth_scheme,
            provider=runtime.proxy_api_provider,
        )
        if fetched_proxy:
            return fetched_proxy
    derived = proxy_runtime.proxy_url_for_region(selected, "US")
    return derived if derived else selected


def paypal_proxy_selected_progress(
    *,
    email: str,
    current: int,
    total: int,
    proxy_label: str,
    proxy_pool_count: int,
    proxy_api_url_present: bool,
    proxy_api_provider: str,
    selected_proxy_summary: str,
    using_proxy_api: bool,
    retry_round: int | None = None,
    ba_attempt: int | None = None,
    ba_retry: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": "paypal_proxy_api_selected" if using_proxy_api else "paypal_proxy_selected",
        "email": email,
        "current": current,
        "total": total,
        "proxy_label": proxy_label,
        "proxy_pool_count": proxy_pool_count,
        "proxy_api_url_present": proxy_api_url_present,
        "proxy_api_provider": proxy_api_provider,
        "message": _paypal_proxy_selected_message(
            proxy_api_provider=proxy_api_provider,
            selected_proxy_summary=selected_proxy_summary,
            using_proxy_api=using_proxy_api,
            ba_retry=ba_retry,
        ),
    }
    if retry_round is not None:
        payload["retry_round"] = retry_round
    if ba_attempt is not None:
        payload["ba_attempt"] = ba_attempt
    return payload


def _paypal_proxy_selected_message(
    *,
    proxy_api_provider: str,
    selected_proxy_summary: str,
    using_proxy_api: bool,
    ba_retry: bool,
) -> str:
    if ba_retry:
        if using_proxy_api:
            return f"PayPal BA 重试已通过 {proxy_api_provider} API 轮换代理: {selected_proxy_summary}"
        return f"PayPal BA 重试已从动态代理池随机选择代理: {selected_proxy_summary}"
    if using_proxy_api:
        return f"已通过 {proxy_api_provider} API 轮换代理: {selected_proxy_summary}"
    return f"已从动态代理池随机选择代理: {selected_proxy_summary}"


def paypal_proxy_api_failed_progress(
    *,
    email: str,
    current: int,
    total: int,
    proxy_label: str,
    proxy_api_provider: str,
    error: Any,
) -> dict[str, Any]:
    return {
        "stage": "paypal_proxy_api_failed",
        "email": email,
        "current": current,
        "total": total,
        "proxy_label": proxy_label,
        "proxy_api_provider": proxy_api_provider,
        "message": f"动态代理 API 获取失败: {error}",
        "level": "error",
    }


def paypal_proxy_api_probe_progress(
    *,
    email: str,
    current: int,
    total: int,
    proxy_label: str,
    proxy_api_provider: str,
    exit_ip: str,
) -> dict[str, Any]:
    return {
        "stage": "paypal_proxy_api_probe",
        "email": email,
        "current": current,
        "total": total,
        "proxy_label": proxy_label,
        "proxy_api_provider": proxy_api_provider,
        "message": f"代理出口 IP 探测成功: {exit_ip}",
    }
