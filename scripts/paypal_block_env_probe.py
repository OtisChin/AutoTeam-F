"""PayPal BA block environment probe.

Diagnostic runner for comparing a stable, browser-like HTTP environment against the
normal PayPal BA extraction path.  It does not touch the app defaults; all
patches are process-local to this script.

Main differences from the normal route:
- one exact proxy URL is reused for every ChatGPT/Stripe stage
- account's saved oai_device_id is reused when available
- locale/timezone are aligned with the target country
- User-Agent / sec-ch-ua are made internally consistent with the selected mode
"""

from __future__ import annotations

import argparse
import select
import json
import re
import socket
import socketserver
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import unquote, urlsplit

from curl_cffi.requests import Session as CurlCffiSession
import socks

from autotoken.api_routes.us_paypal import _iter_auth_accounts, _load_token_for_email
from autotoken.payments.brazil_pix import short
from autotoken.payments import us_paypal as pp
from autotoken.services import chatgpt_session as chatgpt_session_service

COUNTRY_BROWSER_PROFILE: dict[str, dict[str, Any]] = {
    "GB": {"locale": "en-GB", "accept_language": "en-GB,en;q=0.9", "timezone": "Europe/London", "timezone_offset_min": 0, "platform": "Windows"},
    "US": {"locale": "en-US", "accept_language": "en-US,en;q=0.9", "timezone": "America/New_York", "timezone_offset_min": 300, "platform": "Windows"},
    "BR": {"locale": "pt-BR", "accept_language": "pt-BR,pt;q=0.9,en;q=0.8", "timezone": "America/Sao_Paulo", "timezone_offset_min": 180, "platform": "Windows"},
    "JP": {"locale": "ja-JP", "accept_language": "ja-JP,ja;q=0.9,en;q=0.8", "timezone": "Asia/Tokyo", "timezone_offset_min": -540, "platform": "Windows"},
    "TR": {"locale": "tr-TR", "accept_language": "tr-TR,tr;q=0.9,en;q=0.8", "timezone": "Europe/Istanbul", "timezone_offset_min": -180, "platform": "Windows"},
}


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    for chunk in str(value).replace("\r", "\n").replace(",", "\n").splitlines():
        item = chunk.strip()
        if item:
            out.append(item)
    return out


def load_proxies(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    values.extend(parse_list(args.proxy))
    if args.proxy_file:
        values.extend(parse_list(Path(args.proxy_file).read_text(encoding="utf-8")))
    if not values:
        raise SystemExit("缺少代理：--proxy 或 --proxy-file")
    return [pp.normalize_paypal_proxy_url(item) for item in values if str(item or "").strip()]


def proxy_for_account(proxies: list[str], index: int) -> str:
    if not proxies:
        raise SystemExit("缺少代理：--proxy 或 --proxy-file")
    return proxies[index % len(proxies)]


def auth_for_email(email: str) -> dict[str, Any]:
    target = email.strip().lower()
    for item in _iter_auth_accounts(include_paid=True):
        if str(item.get("email") or "").strip().lower() == target:
            auth_file = str(item.get("auth_file") or "")
            if auth_file and Path(auth_file).exists():
                try:
                    data = json.loads(Path(auth_file).read_text(encoding="utf-8"))
                    data["_auth_file"] = auth_file
                    return data
                except Exception:
                    pass
            return dict(item)
    return {}


def chrome_major_from_ua(ua: str, fallback: int = 136) -> int:
    m = re.search(r"(?:Chrome|Chromium|HeadlessChrome|Edg)/(\d+)", ua or "")
    if not m:
        return fallback
    try:
        return int(m.group(1))
    except Exception:
        return fallback


def platform_from_ua(ua: str, fallback: str = "Windows") -> str:
    text = ua or ""
    if "Macintosh" in text or "Mac OS X" in text:
        return "macOS"
    if "Linux" in text:
        return "Linux"
    if "Windows" in text:
        return "Windows"
    return fallback


def ua_for_mode(mode: str, auth_data: dict[str, Any]) -> str:
    if mode == "auth":
        ua = str(auth_data.get("user_agent") or "").strip()
        if ua:
            return ua
    if mode == "default":
        return str(pp.DEFAULT_USER_AGENT)
    # Match curl_cffi chrome136 impersonation to avoid the current 136 TLS / 146 header split.
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"


def sec_ch_ua(major: int) -> str:
    return f'"Google Chrome";v="{major}", "Chromium";v="{major}", "Not.A/Brand";v="24"'


def profile_for(country: str, auth_data: dict[str, Any], ua_mode: str) -> dict[str, Any]:
    country = pp.normalize_paypal_country(country, "GB")
    base = dict(COUNTRY_BROWSER_PROFILE.get(country) or COUNTRY_BROWSER_PROFILE["US"])
    ua = ua_for_mode(ua_mode, auth_data)
    locale = str(auth_data.get("oai_language") or "").replace("_", "-") if ua_mode == "auth" else ""
    if locale:
        base["locale"] = locale
        base["accept_language"] = str(auth_data.get("accept_language") or f"{locale},{locale.split('-')[0]};q=0.9,en;q=0.8")
    base["user_agent"] = ua
    base["chrome_major"] = chrome_major_from_ua(ua, 136)
    base["platform"] = platform_from_ua(ua, str(base.get("platform") or "Windows"))
    base["device_id"] = str(auth_data.get("oai_device_id") or auth_data.get("device_id") or "").strip()
    return base


def deterministic_device_id(email: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "autoteam-paypal-block-env:" + email.strip().lower()))


@contextmanager
def stable_paypal_environment(
    *,
    proxy_url: str,
    profile: dict[str, Any],
    device_id: str,
    impersonate: str,
    cookie_header: str = "",
    openai_sentinel_token: str = "",
    oai_telemetry: str = "",
) -> Iterator[None]:
    originals: dict[str, Any] = {
        "DEFAULT_USER_AGENT": pp.DEFAULT_USER_AGENT,
        "build_paypal_dynamic_proxy": pp.build_paypal_dynamic_proxy,
        "new_http_session": pp.new_http_session,
        "build_chatgpt_session": pp.build_chatgpt_session,
        "build_stripe_session": pp.build_stripe_session,
        "_browser_timezone_offset_min": pp._browser_timezone_offset_min,
        "stripe_init": pp.stripe_init,
        "page_get": pp.page_get,
        "_confirm_paypal_inline": pp._confirm_paypal_inline,
    }
    ua = str(profile["user_agent"])
    locale = str(profile["locale"])
    accept_language = str(profile["accept_language"])
    timezone = str(profile["timezone"])
    tz_offset = int(profile["timezone_offset_min"])
    major = int(profile["chrome_major"])
    platform = str(profile["platform"])
    seeded_cookie_header = str(cookie_header or "").strip()
    seeded_sentinel = str(openai_sentinel_token or "").strip()
    seeded_telemetry = str(oai_telemetry or "").strip()

    def patched_dynamic_proxy(_cfg: pp.PaypalJobConfig, stage_index: int, region: str | None = None) -> tuple[str, str]:
        return proxy_url, f"pinned-exact stage={stage_index} region={region or _cfg.region}"

    def patched_new_http_session(session_proxy: str = ""):
        try:
            session = CurlCffiSession(impersonate=impersonate)
        except Exception:
            session = originals["new_http_session"](session_proxy)
        if hasattr(session, "trust_env"):
            session.trust_env = False
        p = str(session_proxy or proxy_url or "").strip()
        if p:
            session.proxies.update({"http": p, "https": p})
        return session

    def apply_browser_headers(session: Any, *, chatgpt: bool) -> Any:
        headers = {
            "User-Agent": ua,
            "Accept-Language": accept_language,
            "sec-ch-ua": sec_ch_ua(major),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": f'"{platform}"',
        }
        if chatgpt:
            merged_cookie = chatgpt_session_service.merge_cookie_headers(seeded_cookie_header, f"oai-did={device_id}")
            headers.update({"oai-device-id": device_id, "oai-language": locale, "Cookie": merged_cookie or f"oai-did={device_id}"})
            if seeded_sentinel:
                headers["openai-sentinel-token"] = seeded_sentinel
            if seeded_telemetry:
                headers["OAI-Telemetry"] = seeded_telemetry
        session.headers.update(headers)
        return session

    def patched_build_chatgpt_session(access_token: str, session_proxy: str = "", _ignored_device_id: str = ""):
        session = originals["build_chatgpt_session"](access_token, session_proxy or proxy_url, device_id)
        return apply_browser_headers(session, chatgpt=True)

    def patched_build_stripe_session(session_proxy: str = ""):
        session = originals["build_stripe_session"](session_proxy or proxy_url)
        return apply_browser_headers(session, chatgpt=False)

    def patched_stripe_init(stripe, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
        resp = stripe.post(
            f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
            data={
                "browser_locale": locale,
                "browser_timezone": timezone,
                "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
                "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
                "elements_session_client[elements_init_source]": "custom_checkout",
                "elements_session_client[referrer_host]": "chatgpt.com",
                "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
                "elements_session_client[locale]": locale,
                "elements_session_client[is_aggregation_expected]": "false",
                "elements_options_client[saved_payment_method][enable_save]": "never",
                "elements_options_client[saved_payment_method][enable_redisplay]": "never",
                "key": stripe_pk,
                "_stripe_version": pp.PAYPAL_STRIPE_VERSION,
            },
            timeout=pp.TIMEOUT,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"stripe init failed: HTTP {resp.status_code} {short(resp.text)}")
        data = resp.json() or {}
        ctx["config_id"] = str(data.get("config_id") or ctx.get("config_id") or "")
        ctx["init_checksum"] = str(data.get("init_checksum") or "")
        ctx["elements_session_config_id"] = str(data.get("config_id") or ctx.get("elements_session_config_id") or uuid.uuid4())
        return data

    def patched_page_get(stripe, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
        resp = stripe.get(
            f"https://api.stripe.com/v1/payment_pages/{cs_id}",
            params={
                "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
                "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
                "elements_session_client[elements_init_source]": "custom_checkout",
                "elements_session_client[referrer_host]": "chatgpt.com",
                "elements_session_client[session_id]": ctx["elements_session_id"],
                "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
                "elements_session_client[locale]": locale,
                "elements_session_client[is_aggregation_expected]": "false",
                "elements_options_client[saved_payment_method][enable_save]": "never",
                "elements_options_client[saved_payment_method][enable_redisplay]": "never",
                "key": stripe_pk,
                "_stripe_version": pp.PAYPAL_STRIPE_VERSION,
            },
            timeout=pp.TIMEOUT,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"payment_pages get failed: HTTP {resp.status_code} {short(resp.text)}")
        return resp.json() or {}

    def patched_confirm_paypal_inline(stripe, *, cs_id: str, stripe_pk: str, ctx: dict[str, str], billing: dict[str, str], amount: str, return_url: str) -> dict[str, Any]:
        body = {
            "guid": ctx["guid"],
            "muid": ctx["muid"],
            "sid": ctx["sid"],
            "payment_method_data[type]": "paypal",
            "init_checksum": ctx["init_checksum"],
            "version": pp.PAYPAL_STRIPE_RUNTIME_VERSION,
            "expected_amount": amount,
            "expected_payment_method_type": "paypal",
            "return_url": return_url,
            "elements_session_client[session_id]": ctx["elements_session_id"],
            "elements_session_client[locale]": locale,
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[checkout_config_id]": ctx["config_id"],
            "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
            "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[merchant_integration_version]": "custom",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "consent[terms_of_service]": "accepted",
            "key": stripe_pk,
            "_stripe_version": pp.PAYPAL_STRIPE_VERSION,
        }
        body.update(
            {
                "payment_method_data[billing_details][name]": billing["name"],
                "payment_method_data[billing_details][email]": billing["email"],
                "payment_method_data[billing_details][address][country]": billing.get("country") or "US",
                "payment_method_data[billing_details][address][line1]": billing.get("line1") or "",
                "payment_method_data[billing_details][address][city]": billing.get("city") or "",
                "payment_method_data[billing_details][address][postal_code]": billing.get("postal_code") or "",
                "payment_method_data[billing_details][address][state]": billing.get("state") or "",
            }
        )
        resp = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=pp.TIMEOUT)
        ba_approve_url = pp.extract_paypal_ba_approve_url(resp.text)
        if ba_approve_url:
            return {"_ba_approve_url": ba_approve_url, "_raw_status": resp.status_code}
        if resp.status_code >= 400:
            raise RuntimeError(f"confirm failed: HTTP {resp.status_code} {short(resp.text)}")
        payload = resp.json() or {}
        ba_approve_url = pp.extract_paypal_ba_approve_url(payload)
        if ba_approve_url:
            payload["_ba_approve_url"] = ba_approve_url
        return payload

    pp.DEFAULT_USER_AGENT = ua
    pp.build_paypal_dynamic_proxy = patched_dynamic_proxy
    pp.new_http_session = patched_new_http_session
    pp.build_chatgpt_session = patched_build_chatgpt_session
    pp.build_stripe_session = patched_build_stripe_session
    pp._browser_timezone_offset_min = lambda: tz_offset
    pp.stripe_init = patched_stripe_init
    pp.page_get = patched_page_get
    pp._confirm_paypal_inline = patched_confirm_paypal_inline
    try:
        yield
    finally:
        for key, value in originals.items():
            setattr(pp, key, value)


def redact_proxy(proxy_url: str) -> str:
    return re.sub(r"(?i)(://)[^/@]+@", r"\1<proxy-auth>@", proxy_url or "")


def browser_proxy_config(proxy_url: str) -> dict[str, str] | None:
    raw = str(proxy_url or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.hostname:
        return {"server": raw.replace("socks5h://", "socks5://", 1)}
    scheme = "socks5" if parsed.scheme.lower() == "socks5h" else parsed.scheme
    server = f"{scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    cfg: dict[str, str] = {"server": server}
    if parsed.username:
        cfg["username"] = unquote(parsed.username)
    if parsed.password:
        cfg["password"] = unquote(parsed.password)
    return cfg


class _ThreadingTunnelServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _SocksConnectTunnelHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        remote = None
        try:
            self.request.settimeout(30)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                data += chunk
            head, _sep, _rest = data.partition(b"\r\n\r\n")
            first_line = head.split(b"\r\n", 1)[0].decode("latin1", "ignore")
            parts = first_line.split()
            if len(parts) < 3 or parts[0].upper() != "CONNECT":
                self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                return
            target = parts[1]
            if ":" not in target:
                self.request.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
            host, port_text = target.rsplit(":", 1)
            port = int(port_text)
            parsed = self.server.remote_proxy  # type: ignore[attr-defined]
            scheme = str(parsed.scheme or "").lower()
            proxy_type = socks.SOCKS5 if scheme in {"socks5", "socks5h"} else socks.SOCKS4
            remote = socks.socksocket()
            remote.settimeout(30)
            remote.set_proxy(
                proxy_type,
                str(parsed.hostname or ""),
                int(parsed.port or 0),
                rdns=(scheme in {"socks5h", "socks4a"}),
                username=unquote(parsed.username) if parsed.username else None,
                password=unquote(parsed.password) if parsed.password else None,
            )
            remote.connect((host, port))
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: autoteam-local-socks-tunnel\r\n\r\n")
            sockets = [self.request, remote]
            for sock in sockets:
                sock.settimeout(None)
            while True:
                readable, _w, _x = select.select(sockets, [], [], 60)
                if not readable:
                    continue
                for src in readable:
                    dst = remote if src is self.request else self.request
                    buf = src.recv(65536)
                    if not buf:
                        return
                    dst.sendall(buf)
        except Exception:
            try:
                self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            except Exception:
                pass
        finally:
            try:
                if remote is not None:
                    remote.close()
            except Exception:
                pass


@contextmanager
def playwright_proxy_context(proxy_url: str, log: Callable[[str], None]) -> Iterator[dict[str, str] | None]:
    parsed = urlsplit(str(proxy_url or "").strip())
    if parsed.scheme.lower() not in {"socks4", "socks4a", "socks5", "socks5h"}:
        yield browser_proxy_config(proxy_url)
        return
    server = _ThreadingTunnelServer(("127.0.0.1", 0), _SocksConnectTunnelHandler)
    server.remote_proxy = parsed  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    local_url = f"http://{host}:{port}"
    log(f"browser-seed local CONNECT tunnel: {local_url} -> {redact_proxy(proxy_url)}")
    try:
        yield {"server": local_url}
    finally:
        server.shutdown()
        server.server_close()


def playable_cookie_items(auth_data: dict[str, Any], *, device_id: str) -> list[dict[str, Any]]:
    now = time.time()
    cookies: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    raw_cookies = auth_data.get("cookies")
    if isinstance(raw_cookies, list):
        for item in raw_cookies:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "").strip()
            domain = str(item.get("domain") or "").strip()
            if not name or not value:
                continue
            if domain and "chatgpt.com" not in domain and "openai.com" not in domain:
                continue
            expires = item.get("expires")
            try:
                if expires is not None and float(expires) > 0 and float(expires) < now:
                    continue
            except Exception:
                pass
            cookie = {
                "name": name,
                "value": value,
                "domain": domain or ".chatgpt.com",
                "path": str(item.get("path") or "/"),
                "httpOnly": bool(item.get("httpOnly", False)),
                "secure": bool(item.get("secure", True)),
            }
            same_site = str(item.get("sameSite") or "").strip()
            if same_site in {"Strict", "Lax", "None"}:
                cookie["sameSite"] = same_site
            try:
                exp_float = float(expires)
                if exp_float > 0:
                    cookie["expires"] = exp_float
            except Exception:
                pass
            key = (cookie["name"], cookie["domain"], cookie["path"])
            if key not in seen:
                seen.add(key)
                cookies.append(cookie)
    if not cookies and str(auth_data.get("cookie_header") or "").strip():
        cookies.extend(chatgpt_session_service.playwright_cookie_items_from_header(str(auth_data.get("cookie_header") or "")))
    if device_id and not any(str(c.get("name") or "") == "oai-did" for c in cookies):
        cookies.append({"name": "oai-did", "value": device_id, "url": "https://chatgpt.com/"})
    return cookies


def cookie_header_from_browser_cookies(cookies: Any) -> str:
    chatgpt_cookies = []
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain") or "").lower()
        if "chatgpt.com" in domain or "openai.com" in domain:
            chatgpt_cookies.append(cookie)
    return chatgpt_session_service.cookie_header_from_cookie_items(chatgpt_cookies)


def collect_browser_seed(
    *,
    email: str,
    token: str,
    auth_data: dict[str, Any],
    profile: dict[str, Any],
    device_id: str,
    proxy_url: str,
    country: str,
    headed: bool,
    log: Callable[[str], None],
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(f"Playwright 不可用: {exc}") from exc

    locale = str(profile.get("locale") or "en-GB")
    timezone = str(profile.get("timezone") or "Europe/London")
    ua = str(profile.get("user_agent") or pp.DEFAULT_USER_AGENT)
    accept_language = str(profile.get("accept_language") or "en-GB,en;q=0.9")
    state: dict[str, Any] = {
        "ok": False,
        "cookie_header": "",
        "openai_sentinel_token": str(auth_data.get("openai_sentinel_token") or "").strip(),
        "oai_telemetry": "",
        "statuses": [],
        "request_headers": {},
        "browser_info": {},
    }
    log(f"browser-seed start headed={headed} proxy={redact_proxy(proxy_url)}")
    with sync_playwright() as p:
        with playwright_proxy_context(proxy_url, log) as proxy_cfg:
            browser = p.chromium.launch(headless=not headed, proxy=proxy_cfg)
            context = browser.new_context(
                user_agent=ua,
                locale=locale,
                timezone_id=timezone,
                extra_http_headers={"Accept-Language": accept_language},
            )
            cookies = playable_cookie_items(auth_data, device_id=device_id)
            if cookies:
                context.add_cookies(cookies)
                log(f"browser-seed injected cookies={len(cookies)}")
            page = context.new_page()

            def on_request(req: Any) -> None:
                try:
                    url = str(req.url or "")
                    if "chatgpt.com/backend-api" not in url:
                        return
                    headers = {str(k).lower(): str(v) for k, v in (req.headers or {}).items()}
                    if not state.get("request_headers"):
                        state["request_headers"] = {
                            k: headers.get(k, "")
                            for k in (
                                "user-agent",
                                "accept-language",
                                "sec-ch-ua",
                                "sec-ch-ua-mobile",
                                "sec-ch-ua-platform",
                                "oai-device-id",
                                "openai-sentinel-token",
                            )
                            if headers.get(k)
                        }
                except Exception:
                    pass

            def on_response(resp: Any) -> None:
                try:
                    if "backend-api/sentinel/req" not in str(resp.url or "") or int(resp.status or 0) != 200:
                        return
                    data = resp.json()
                    token_value = str((data or {}).get("token") or "").strip() if isinstance(data, dict) else ""
                    if token_value:
                        state["openai_sentinel_token"] = token_value
                except Exception:
                    pass

            page.on("request", on_request)
            page.on("response", on_response)
            try:
                page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                log(f"browser-seed goto warning: {type(exc).__name__}: {short(exc, 160)}")
            result = page.evaluate(
                """async ({token, country, deviceId}) => {
                    const statuses = [];
                    async function call(label, url, init = {}) {
                        try {
                            const headers = Object.assign({
                                "authorization": `Bearer ${token}`,
                                "content-type": "application/json",
                                "oai-device-id": deviceId,
                                "x-openai-target-path": new URL(url, location.origin).pathname,
                                "x-openai-target-route": new URL(url, location.origin).pathname
                            }, init.headers || {});
                            const resp = await fetch(url, Object.assign({
                                credentials: "include",
                                headers
                            }, init));
                            let text = "";
                            try { text = await resp.text(); } catch (_e) {}
                            statuses.push({label, status: resp.status, body: text.slice(0, 240)});
                        } catch (e) {
                            statuses.push({label, error: String(e).slice(0, 240)});
                        }
                    }
                    await call("accounts_check", `/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min=0`);
                    await call("countries", "/backend-api/checkout_pricing_config/countries");
                    await call("country_config", `/backend-api/checkout_pricing_config/configs/${country}`);
                    await call("sentinel_ping", "/backend-api/sentinel/ping", {method: "POST", body: "{}"});
                    let sentinel = "";
                    let telemetry = "";
                    try {
                        const script = document.createElement("script");
                        script.src = "/backend-api/sentinel/sdk.js";
                        await new Promise((resolve, reject) => {
                            script.onload = resolve;
                            script.onerror = () => reject(new Error("sentinel sdk load failed"));
                            document.head.appendChild(script);
                            setTimeout(() => reject(new Error("sentinel sdk timeout")), 15000);
                        });
                        const candidates = ["checkout_session_create", "checkout_session_approval", "payment_checkout", "checkout"];
                        for (const flow of candidates) {
                            try {
                                const value = await Promise.race([
                                    window.SentinelSDK.token(flow),
                                    new Promise((_, reject) => setTimeout(() => reject(new Error("token timeout")), 12000))
                                ]);
                                if (value) { sentinel = value; break; }
                            } catch (_e) {}
                        }
                        try { telemetry = window.SentinelSDK.timing ? await window.SentinelSDK.timing() : ""; } catch (_e) {}
                    } catch (e) {
                        statuses.push({label: "sentinel_sdk", error: String(e).slice(0, 240)});
                    }
                    return {
                        statuses,
                        sentinel,
                        telemetry,
                        browserInfo: {
                            userAgent: navigator.userAgent,
                            language: navigator.language,
                            languages: navigator.languages,
                            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                            platform: navigator.platform
                        }
                    };
                }""",
                {"token": token, "country": country, "deviceId": device_id},
            )
            if isinstance(result, dict):
                state["statuses"] = result.get("statuses") or []
                state["browser_info"] = result.get("browserInfo") or {}
                if str(result.get("sentinel") or "").strip():
                    state["openai_sentinel_token"] = str(result.get("sentinel") or "").strip()
                state["oai_telemetry"] = str(result.get("telemetry") or "").strip()
            browser_cookies = context.cookies()
            state["cookie_header"] = chatgpt_session_service.merge_cookie_headers(
                cookie_header_from_browser_cookies(browser_cookies),
                str(auth_data.get("cookie_header") or ""),
                f"oai-did={device_id}",
            )
            state["ok"] = bool(state["cookie_header"])
            context.close()
            browser.close()
    log(
        "browser-seed done "
        + " ".join(
            f"{str(item.get('label'))}={item.get('status', item.get('error', '-'))}"
            for item in (state.get("statuses") or [])
            if isinstance(item, dict)
        )
        + f" sentinel={bool(state.get('openai_sentinel_token'))} cookies={bool(state.get('cookie_header'))}"
    )
    return state


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_one(email: str, args: argparse.Namespace, proxy_url: str) -> dict[str, Any]:
    started = datetime.now().isoformat(timespec="seconds")
    logs: list[str] = []

    def log(message: str) -> None:
        line = str(message)
        logs.append(line)
        print(f"[{email}] {line}", flush=True)

    auth_data = auth_for_email(email)
    token = _load_token_for_email(email)
    profile = profile_for(args.country, auth_data, args.ua_mode)
    device_id = str(args.device_id or profile.get("device_id") or deterministic_device_id(email)).strip()
    profile["device_id"] = device_id
    browser_seed: dict[str, Any] = {}
    if bool(getattr(args, "browser_seed", False)):
        browser_seed = collect_browser_seed(
            email=email,
            token=token,
            auth_data=auth_data,
            profile=profile,
            device_id=device_id,
            proxy_url=proxy_url,
            country=args.country,
            headed=bool(getattr(args, "browser_headed", False)),
            log=log,
        )
    cfg = pp.PaypalJobConfig(
        access_token=token,
        local_proxy=str(args.local_proxy or ""),
        region=args.country,
        promo_region=args.promo_country or args.country,
        direct_proxies=[proxy_url],
        apply_promo=bool(args.apply_promo),
        only_oaics=bool(args.only_oaics),
    )
    meta = {
        "email": email,
        "country": args.country,
        "promo_country": args.promo_country or args.country,
        "apply_promo": bool(args.apply_promo),
        "only_oaics": bool(args.only_oaics),
        "proxy": redact_proxy(proxy_url),
        "proxy_mode": "pinned_exact_all_stages",
        "impersonate": args.impersonate,
        "ua_mode": args.ua_mode,
        "user_agent": profile.get("user_agent"),
        "chrome_major": profile.get("chrome_major"),
        "platform": profile.get("platform"),
        "locale": profile.get("locale"),
        "accept_language": profile.get("accept_language"),
        "timezone": profile.get("timezone"),
        "timezone_offset_min": profile.get("timezone_offset_min"),
        "device_id_source": "cli" if args.device_id else ("auth" if auth_data.get("oai_device_id") or auth_data.get("device_id") else "deterministic"),
        "auth_file": auth_data.get("_auth_file", ""),
        "browser_seed": bool(browser_seed),
        "browser_seed_cookie": bool(browser_seed.get("cookie_header")),
        "browser_seed_sentinel": bool(browser_seed.get("openai_sentinel_token")),
    }
    result: dict[str, Any] = {
        "ok": False,
        "started_at": started,
        "meta": meta,
        "browser_seed": {
            "ok": bool(browser_seed.get("ok")),
            "statuses": browser_seed.get("statuses") or [],
            "request_headers": browser_seed.get("request_headers") or {},
            "browser_info": browser_seed.get("browser_info") or {},
            "cookie_header_present": bool(browser_seed.get("cookie_header")),
            "openai_sentinel_token_present": bool(browser_seed.get("openai_sentinel_token")),
            "oai_telemetry_present": bool(browser_seed.get("oai_telemetry")),
        },
        "logs": logs,
    }
    try:
        with stable_paypal_environment(
            proxy_url=proxy_url,
            profile=profile,
            device_id=device_id,
            impersonate=args.impersonate,
            cookie_header=str(browser_seed.get("cookie_header") or ""),
            openai_sentinel_token=str(browser_seed.get("openai_sentinel_token") or ""),
            oai_telemetry=str(browser_seed.get("oai_telemetry") or ""),
        ):
            if args.dry_run:
                result.update({"ok": True, "dry_run": True})
            else:
                extracted = pp.generate_paypal_trial(cfg, log=log)
                fields = extracted.get("fields") if isinstance(extracted, dict) else {}
                result.update(
                    {
                        "ok": bool(extracted.get("ok") if isinstance(extracted, dict) else False),
                        "amount": extracted.get("amount") if isinstance(extracted, dict) else "",
                        "paypal_link": str((fields or {}).get("paypal_link") or (fields or {}).get("provider_redirect_url") or ""),
                        "ba_token": str((fields or {}).get("ba_token") or ""),
                        "fields": fields or {},
                        "billing": extracted.get("billing") if isinstance(extracted, dict) else {},
                    }
                )
    except Exception as exc:
        result.update({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        log(f"ERROR {type(exc).__name__}: {exc}")
    finally:
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Stable-environment PayPal BA block diagnostic runner")
    parser.add_argument("--email", action="append", default=[], help="Account email. Can be repeated or comma/newline separated.")
    parser.add_argument("--email-file", default="", help="File containing one email per line.")
    parser.add_argument("--proxy", default="", help="Proxy URL or host:port:user:pass. First proxy is pinned for all stages.")
    parser.add_argument("--proxy-file", default="", help="File containing proxies; first non-empty line is pinned.")
    parser.add_argument("--local-proxy", default="")
    parser.add_argument("--country", default="GB")
    parser.add_argument("--promo-country", default="", help="Defaults to --country to avoid country/IP switching.")
    parser.add_argument("--apply-promo", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--only-oaics", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--ua-mode", choices=["curl136", "auth", "default"], default="curl136")
    parser.add_argument("--impersonate", default="chrome136")
    parser.add_argument("--device-id", default="", help="Override oai-device-id. Default: auth file device id, else deterministic per email.")
    parser.add_argument("--browser-seed", action="store_true", help="Warm ChatGPT in a real Playwright browser first, then feed cookies/sentinel into protocol extraction.")
    parser.add_argument("--browser-headed", action="store_true", help="Show the seed browser window instead of headless mode.")
    parser.add_argument("--dry-run", action="store_true", help="Only print/save the selected environment, do not create checkout.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between accounts.")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    emails: list[str] = []
    for item in args.email or []:
        emails.extend(parse_list(item))
    if args.email_file:
        emails.extend(parse_list(Path(args.email_file).read_text(encoding="utf-8")))
    emails = list(dict.fromkeys([e.strip() for e in emails if e.strip()]))
    if not emails:
        raise SystemExit("缺少账号：--email 或 --email-file")

    args.country = pp.normalize_paypal_country(args.country, "GB")
    args.promo_country = pp.normalize_paypal_country(args.promo_country or args.country, args.country)
    proxies = load_proxies(args)
    out = Path(args.output or f"data/paypal_block_env_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    payload: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "script": "scripts/paypal_block_env_probe.py",
        "proxy_mode": "per_account_pinned",
        "proxy_count": len(proxies),
        "proxies": [redact_proxy(item) for item in proxies],
        "emails": emails,
        "results": [],
    }
    write_json(out, payload)
    print(f"输出: {out}", flush=True)
    print(
        f"mode=per-account-pinned proxy_count={len(proxies)} country={args.country} "
        f"promo_country={args.promo_country} ua_mode={args.ua_mode} impersonate={args.impersonate}",
        flush=True,
    )

    for index, email in enumerate(emails):
        proxy_url = proxy_for_account(proxies, index)
        print(f"[{email}] selected proxy {index % len(proxies) + 1}/{len(proxies)} {redact_proxy(proxy_url)}", flush=True)
        item = run_one(email, args, proxy_url)
        payload["results"].append(item)
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
        payload["summary"] = {
            "total": len(payload["results"]),
            "ok": sum(1 for r in payload["results"] if r.get("ok")),
            "failed": sum(1 for r in payload["results"] if not r.get("ok")),
            "success_emails": [r.get("meta", {}).get("email") for r in payload["results"] if r.get("ok")],
        }
        write_json(out, payload)
        time.sleep(max(0.0, float(getattr(args, "sleep", 0.0) or 0.0)))

    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["summary"] = {
        "total": len(payload["results"]),
        "ok": sum(1 for r in payload["results"] if r.get("ok")),
        "failed": sum(1 for r in payload["results"] if not r.get("ok")),
        "success_emails": [r.get("meta", {}).get("email") for r in payload["results"] if r.get("ok")],
    }
    write_json(out, payload)
    print("=== SUMMARY ===", flush=True)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2), flush=True)
    return 0 if payload["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
