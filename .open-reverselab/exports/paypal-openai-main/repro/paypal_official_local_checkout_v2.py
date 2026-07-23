#!/usr/bin/env python3
"""Local PayPal checkout verifier using official REST API shapes.

Production use talks to PayPal api-m.sandbox/live. Test use may point
PAYPAL_API_BASE_OVERRIDE at a local mock server to verify create/return/capture
control flow without storing real credentials.
"""
from __future__ import annotations
import argparse, base64, json, os, sys, time, urllib.error, urllib.parse, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any


def mask(v: str) -> str:
    return v[:6] + "…" + v[-4:] if len(v) > 14 else "***"


def http_json(method: str, url: str, *, headers: dict[str, str] | None = None, body: Any = None, basic: tuple[str, str] | None = None, timeout: int = 45) -> tuple[int, dict[str, str], Any]:
    h = dict(headers or {})
    data: bytes | None = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, separators=(",", ":")).encode()
            h.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            data = body.encode()
        elif isinstance(body, bytes):
            data = body
        else:
            raise TypeError(type(body))
    if basic:
        h["Authorization"] = "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try: obj = json.loads(raw)
            except Exception: obj = raw
            return r.status, dict(r.headers), obj
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try: obj = json.loads(raw)
        except Exception: obj = raw
        return e.code, dict(e.headers), obj


class PayPalOfficial:
    def __init__(self, env: str, client_id: str, secret: str, base_override: str = ""):
        self.env = env
        self.client_id = client_id
        self.secret = secret
        if base_override:
            self.base = base_override.rstrip("/")
        else:
            self.base = "https://api-m.sandbox.paypal.com" if env == "sandbox" else "https://api-m.paypal.com"
        self.access_token = ""

    def oauth(self) -> None:
        status, _, obj = http_json(
            "POST", self.base + "/v1/oauth2/token",
            headers={"Accept":"application/json","Accept-Language":"en_US","Content-Type":"application/x-www-form-urlencoded"},
            body="grant_type=client_credentials", basic=(self.client_id, self.secret),
        )
        if status >= 300 or not isinstance(obj, dict) or not obj.get("access_token"):
            raise RuntimeError(json.dumps({"stage":"oauth","status":status,"response":obj}, ensure_ascii=False))
        self.access_token = str(obj["access_token"])

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type":"application/json", "Prefer":"return=representation"}

    def create_order(self, amount: str, currency: str, return_url: str, cancel_url: str) -> dict[str, Any]:
        payload = {
            "intent":"CAPTURE",
            "purchase_units":[{"reference_id":"openai-paypal-main-local","amount":{"currency_code":currency,"value":amount}}],
            "payment_source":{"paypal":{"experience_context":{
                "payment_method_preference":"IMMEDIATE_PAYMENT_REQUIRED",
                "brand_name":"openai-paypal-main local verifier",
                "locale":"en-US",
                "landing_page":"LOGIN",
                "shipping_preference":"NO_SHIPPING",
                "user_action":"PAY_NOW",
                "return_url":return_url,
                "cancel_url":cancel_url,
            }}},
        }
        status, _, obj = http_json("POST", self.base + "/v2/checkout/orders", headers=self.headers, body=payload)
        if status >= 300 or not isinstance(obj, dict):
            raise RuntimeError(json.dumps({"stage":"create_order","status":status,"response":obj}, ensure_ascii=False))
        return obj

    def capture(self, order_id: str) -> dict[str, Any]:
        status, _, obj = http_json("POST", self.base + f"/v2/checkout/orders/{urllib.parse.quote(order_id)}/capture", headers=self.headers, body={})
        if status >= 300 or not isinstance(obj, dict):
            raise RuntimeError(json.dumps({"stage":"capture","status":status,"response":obj}, ensure_ascii=False))
        return obj


def approval_url(order: dict[str, Any]) -> str:
    for rel in ("payer-action", "approve"):
        for link in order.get("links", []) or []:
            if link.get("rel") == rel and link.get("href"):
                return str(link["href"])
    return ""


def wait_return(host: str, port: int, timeout: int) -> dict[str, str]:
    result: dict[str, str] = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None: return
        def do_GET(self) -> None:  # noqa: N802
            nonlocal result
            parsed = urllib.parse.urlsplit(self.path)
            qs = dict(urllib.parse.parse_qsl(parsed.query))
            result = {"path": parsed.path, **qs}
            body = b"PayPal return captured. You can close this window.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server = HTTPServer((host, port), Handler); server.timeout = 1
    deadline = time.time() + timeout
    while time.time() < deadline and not result: server.handle_request()
    server.server_close(); return result


def emit(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2), flush=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=os.getenv("PAYPAL_ENV", "sandbox"), choices=["sandbox", "live"])
    ap.add_argument("--client-id", default=os.getenv("PAYPAL_CLIENT_ID", ""))
    ap.add_argument("--secret", default=os.getenv("PAYPAL_CLIENT_SECRET", ""))
    ap.add_argument("--api-base-override", default=os.getenv("PAYPAL_API_BASE_OVERRIDE", ""))
    ap.add_argument("--amount", default=os.getenv("PAYPAL_AMOUNT", "0.01"))
    ap.add_argument("--currency", default=os.getenv("PAYPAL_CURRENCY", "USD"))
    ap.add_argument("--order-id", default=os.getenv("PAYPAL_ORDER_ID", ""))
    ap.add_argument("--auto-wait", action="store_true", default=os.getenv("PAYPAL_AUTO_WAIT", "").lower() in {"1","true","yes","on"})
    ap.add_argument("--auto-open", action="store_true", default=os.getenv("PAYPAL_AUTO_OPEN", "").lower() in {"1","true","yes","on"})
    ap.add_argument("--callback-host", default=os.getenv("PAYPAL_CALLBACK_HOST", "127.0.0.1"))
    ap.add_argument("--callback-port", type=int, default=int(os.getenv("PAYPAL_CALLBACK_PORT", "8765")))
    ap.add_argument("--wait-timeout", type=int, default=int(os.getenv("PAYPAL_WAIT_TIMEOUT", "900")))
    ns = ap.parse_args(argv)
    if not ns.client_id or not ns.secret:
        emit({"ok":False,"stage":"config","error":"missing PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET"}); return 2
    pp = PayPalOfficial(ns.env, ns.client_id, ns.secret, ns.api_base_override)
    emit({"stage":"oauth","env":ns.env,"client_id":mask(ns.client_id),"base":pp.base})
    try: pp.oauth()
    except Exception as exc:
        try: detail=json.loads(str(exc))
        except Exception: detail={"stage":"oauth","error":str(exc)}
        emit({"ok":False, **detail}); return 1
    if ns.order_id:
        try: cap=pp.capture(ns.order_id)
        except Exception as exc:
            try: detail=json.loads(str(exc))
            except Exception: detail={"stage":"capture","error":str(exc)}
            emit({"ok":False, **detail}); return 1
        status=cap.get("status"); emit({"ok":status=="COMPLETED","stage":"captured","order_id":ns.order_id,"capture_status":status,"response":cap})
        return 0 if status=="COMPLETED" else 1
    return_url=f"http://{ns.callback_host}:{ns.callback_port}/return"; cancel_url=f"http://{ns.callback_host}:{ns.callback_port}/cancel"
    try: order=pp.create_order(ns.amount, ns.currency.upper(), return_url, cancel_url)
    except Exception as exc:
        try: detail=json.loads(str(exc))
        except Exception: detail={"stage":"create_order","error":str(exc)}
        emit({"ok":False, **detail}); return 1
    url=approval_url(order); order_id=str(order.get("id") or "")
    emit({"ok":True,"stage":"created","order_id":order_id,"order_status":order.get("status"),"approval_url":url})
    if ns.auto_open and url: webbrowser.open(url)
    if ns.auto_wait:
        emit({"stage":"waiting_for_buyer_return","return_url":return_url,"timeout_seconds":ns.wait_timeout})
        ret=wait_return(ns.callback_host, ns.callback_port, ns.wait_timeout)
        if not ret or ret.get("path") != "/return": emit({"ok":False,"stage":"approval_wait","return":ret}); return 1
        capture_id=ret.get("token") or order_id
        try: cap=pp.capture(str(capture_id))
        except Exception as exc:
            try: detail=json.loads(str(exc))
            except Exception: detail={"stage":"capture","error":str(exc)}
            emit({"ok":False, **detail}); return 1
        status=cap.get("status"); emit({"ok":status=="COMPLETED","stage":"created_approved_captured","order_id":capture_id,"capture_status":status,"response":cap})
        return 0 if status=="COMPLETED" else 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
