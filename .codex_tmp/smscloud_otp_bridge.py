from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from autoteam.gopay_auto_register import (
    _smscloud_base_url,
    _smscloud_extract_code,
    _smscloud_find_order,
    _smscloud_request,
)


def read_env(path: str = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


class SmsCloudOtpHandler(BaseHTTPRequestHandler):
    activation_id = ""
    base_url = ""
    token = ""
    ignored_codes: set[str] = set()

    def log_message(self, fmt: str, *args):
        return

    def do_GET(self):
        if self.path.split("?", 1)[0] not in {"/", "/otp"}:
            self.send_response(404)
            self.end_headers()
            return
        ok, data, message = _smscloud_request(
            self.base_url,
            self.token,
            "get",
            "/system/app/sms/myNumber",
            timeout=20,
        )
        payload = {"ok": False, "data": {"status": "pending"}}
        if not ok:
            payload = {"ok": False, "data": {"status": "error", "message": message or "smscloud error"}}
        else:
            order = _smscloud_find_order(data, self.activation_id)
            code = _smscloud_extract_code(order, ignored_codes=self.ignored_codes) if order else ""
            if code:
                payload = {"ok": True, "data": {"otp": code, "activation_id": self.activation_id}}
            elif order:
                payload = {"ok": False, "data": {"status": "stale" if self.ignored_codes else "pending"}}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--activation-id", required=True)
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--ignore", default="")
    args = parser.parse_args()

    env = read_env()
    SmsCloudOtpHandler.activation_id = args.activation_id
    SmsCloudOtpHandler.base_url = _smscloud_base_url(
        env.get("GOPAY_AUTO_SIGNUP_SMSCLOUD_BASE_URL", "https://smscloud.sbs/api")
    )
    SmsCloudOtpHandler.token = env.get("GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN", "")
    SmsCloudOtpHandler.ignored_codes = {
        code for code in re.split(r"[,\s]+", args.ignore) if re.fullmatch(r"\d{4,8}", code or "")
    }
    server = ThreadingHTTPServer(("127.0.0.1", args.port), SmsCloudOtpHandler)
    print(f"smscloud bridge listening on http://127.0.0.1:{args.port}/otp", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
