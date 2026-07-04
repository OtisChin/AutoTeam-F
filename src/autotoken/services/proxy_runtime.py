from __future__ import annotations

import json
import random
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from autotoken.settings.config import normalize_proxy_url

PROXY_POOL_TEXT_MAX_BYTES = 1 * 1024 * 1024
PROXY_POOL_MAX_ENTRIES = 5_000


def parse_proxy_pool_values(values: list[Any] | tuple[Any, ...] | None = None, text: str | None = None) -> list[str]:
    raw_text = str(text or "")
    if len(raw_text.encode("utf-8", errors="ignore")) > PROXY_POOL_TEXT_MAX_BYTES:
        raise ValueError("代理池文本过大，最多支持 1MB 文本")

    candidates = [str(raw_value or "") for raw_value in values or []]
    if raw_text:
        candidates.extend(re.split(r"[\r\n,]+", raw_text))
    if len(candidates) > PROXY_POOL_MAX_ENTRIES:
        raise ValueError(f"代理池条目过多，最多支持 {PROXY_POOL_MAX_ENTRIES} 条")

    proxies: list[str] = []
    seen: set[str] = set()
    for raw_proxy in candidates:
        proxy = str(raw_proxy or "").strip()
        if not proxy:
            continue
        if proxy.startswith("#"):
            continue
        if "#" in proxy:
            proxy = proxy.split("#", 1)[0].strip()
        if not proxy:
            continue
        normalized = proxy.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        proxies.append(proxy)
    return proxies


def is_proxy_api_url(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        parsed = urlsplit(raw)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = str(parsed.netloc or "").lower()
    if "cliproxy" in host or "1024proxy" in host:
        return True
    path = str(parsed.path or "").lower()
    return any(marker in path for marker in ("getporxy", "getproxy", "traffic", "/white/api"))


def infer_proxy_api_provider_from_url(value: str) -> str:
    try:
        host = str(urlsplit(str(value or "").strip()).netloc or "").lower()
    except Exception:
        return ""
    if "cliproxy" in host:
        return "cliproxy"
    if "1024proxy" in host:
        return "1024proxy"
    return ""


def normalize_proxy_api_provider(value: str) -> str:
    provider = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    if not provider:
        return "1024proxy"
    if provider in {"1024proxy", "1024"}:
        return "1024proxy"
    if provider in {"cliproxy", "cli"}:
        return "cliproxy"
    raise ValueError("代理 API 供应商暂只支持 1024proxy 或 cliproxy")


def default_proxy_api_url(provider: str, _proxy_url: str = "") -> str:
    normalized_provider = normalize_proxy_api_provider(provider)
    if normalized_provider == "1024proxy":
        return "https://white.1024proxy.com/white/api?region=JP&num=1&time=10&format=1&type=json"
    return "https://api.cliproxy.io/white/api?region=JP&num=1&time=30&format=n&type=json"


def default_paypal_proxy_api_url(provider: str, *, country: str = "US", protocol_no_card: bool = False) -> str:
    normalized_provider = normalize_proxy_api_provider(provider)
    region = re.sub(r"[^A-Za-z]", "", str(country or "US").strip().upper())[:2] or "US"
    if normalized_provider == "1024proxy":
        return f"https://white.1024proxy.com/white/api?region={region}&num=1&time=10&format=1&type=json"
    return f"https://api.cliproxy.io/white/api?region={region}&num=1&time=30&format=n&type=json"


def default_gopay_proxy_api_url(provider: str, _proxy_url: str = "") -> str:
    normalized_provider = normalize_proxy_api_provider(provider)
    if normalized_provider == "1024proxy":
        return "https://white.1024proxy.com/white/api?region=ID&num=1&time=10&format=1&type=json"
    return "https://api.cliproxy.io/white/api?region=ID&num=1&time=30&format=n&type=txt"


def proxy_api_url_with_region(api_url: str, region: str) -> str:
    raw = str(api_url or "").strip()
    if not raw:
        return ""
    target_region = re.sub(r"[^A-Za-z]", "", str(region or "").strip().upper())[:2]
    if not target_region:
        return raw
    parsed = urlsplit(raw)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    updated: list[tuple[str, str]] = []
    for key, value in pairs:
        if key.lower() == "region":
            updated.append((key, target_region))
            replaced = True
        else:
            updated.append((key, value))
    if not replaced:
        updated.append(("region", target_region))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(updated), parsed.fragment))


def proxy_url_for_region(proxy_url: str, region: str) -> str:
    proxy = str(proxy_url or "").strip()
    target_region = re.sub(r"[^A-Za-z]", "", str(region or "").strip().upper())[:2]
    if proxy and target_region and "region-" in proxy:
        return re.sub(r"region-[A-Za-z]{2}", f"region-{target_region}", proxy)
    return proxy


def extract_proxy_candidate_from_api_payload(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return ""
        try:
            return extract_proxy_candidate_from_api_payload(json.loads(text))
        except Exception:
            for raw_line in re.split(r"[\r\n,]+", text):
                line = str(raw_line or "").strip()
                if line:
                    return line
            return text
    if isinstance(payload, list):
        for item in payload:
            candidate = extract_proxy_candidate_from_api_payload(item)
            if candidate:
                return candidate
        return ""
    if isinstance(payload, dict):
        for key in (
            "proxy",
            "Proxy",
            "result",
            "data",
            "list",
            "proxies",
            "proxy_list",
            "proxyList",
            "host",
            "ip",
            "addr",
            "address",
        ):
            if key not in payload:
                continue
            value = payload.get(key)
            if key in {"host", "ip", "addr", "address"} and payload.get("port"):
                return f"{value}:{payload.get('port')}"
            candidate = extract_proxy_candidate_from_api_payload(value)
            if candidate:
                return candidate
        for value in payload.values():
            candidate = extract_proxy_candidate_from_api_payload(value)
            if candidate:
                return candidate
    return ""


def fetch_proxy_from_api_url(api_url: str, *, default_auth_scheme: str, provider: str = "") -> str:
    url = str(api_url or "").strip()
    if not url:
        return ""
    normalized_provider = normalize_proxy_api_provider(provider or infer_proxy_api_provider_from_url(url))
    try:
        resp = requests.get(url, timeout=30)
    except Exception as exc:
        raise RuntimeError(f"动态代理 API 请求失败: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"动态代理 API 返回 HTTP {resp.status_code}: {str(resp.text or '')[:160]}")
    content_type = str(resp.headers.get("content-type") or "").lower()
    payload: Any
    if "json" in content_type:
        try:
            payload = resp.json()
        except Exception:
            payload = resp.text
    else:
        text = str(resp.text or "").strip()
        if re.match(r"(?is)^\s*<!doctype\s+html\b|^\s*<html\b", text):
            raise RuntimeError(
                f"动态代理 API 返回 HTML 页面，请检查 {normalized_provider} API 地址、登录态/Token、白名单或套餐是否有效"
            )
        try:
            payload = json.loads(text)
        except Exception:
            payload = text
    candidate = extract_proxy_candidate_from_api_payload(payload)
    if not candidate:
        if normalized_provider == "cliproxy":
            return ""
        raise RuntimeError("动态代理 API 未返回可识别的代理")
    if "://" not in candidate and "@" not in candidate:
        candidate = f"{default_auth_scheme}://{candidate}"
    try:
        return normalize_proxy_url(candidate, default_auth_scheme=default_auth_scheme)
    except Exception as exc:
        if normalized_provider == "cliproxy":
            return ""
        raise RuntimeError(f"动态代理 API 返回的代理格式无效: {candidate} ({exc})") from exc


def build_oauth_proxy_selector(
    *,
    proxy_url: str | None = None,
    proxy_pool: list[Any] | tuple[Any, ...] | None = None,
    proxy_pool_text: str | None = None,
    proxy_api_provider: str | None = None,
    proxy_api_url: str | None = None,
    default_auth_scheme: str = "socks5h",
):
    raw_proxy_url = str(proxy_url or "").strip()
    try:
        normalized_proxy_url = normalize_proxy_url(raw_proxy_url) if raw_proxy_url else ""
    except Exception as exc:
        raise ValueError(f"OAuth 代理格式错误: {raw_proxy_url} ({exc})") from exc
    provider = normalize_proxy_api_provider(proxy_api_provider) if proxy_api_provider else ""
    api_url = str(proxy_api_url or "").strip()
    if provider and not api_url:
        api_url = default_proxy_api_url(provider, raw_proxy_url)

    normalized_pool: list[str] = []
    for raw_pool_proxy in parse_proxy_pool_values(proxy_pool, proxy_pool_text):
        if is_proxy_api_url(raw_pool_proxy):
            if not api_url:
                api_url = raw_pool_proxy
                provider = normalize_proxy_api_provider(provider or "1024proxy")
            continue
        try:
            normalized = normalize_proxy_url(raw_pool_proxy)
        except Exception as exc:
            raise ValueError(f"OAuth 代理池格式错误: {raw_pool_proxy} ({exc})") from exc
        if normalized and normalized not in normalized_pool:
            normalized_pool.append(normalized)

    def _select() -> str:
        if api_url:
            fetched_proxy = fetch_proxy_from_api_url(
                api_url,
                default_auth_scheme=default_auth_scheme,
                provider=provider or "1024proxy",
            )
            if fetched_proxy:
                return fetched_proxy
            return normalized_proxy_url
        if normalized_pool:
            return random.choice(normalized_pool)
        return normalized_proxy_url

    return _select, {
        "proxy_url_present": bool(normalized_proxy_url),
        "proxy_pool_count": len(normalized_pool),
        "proxy_api_provider": provider,
        "proxy_api_url_present": bool(api_url),
    }
