"""手动添加账号：本地自动接收回调，失败时也支持手动粘贴回调 URL。"""

import logging
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autotoken.auth.codex_auth import (
    CODEX_CALLBACK_PORT,
    _build_auth_url,
    _exchange_auth_code,
    _generate_pkce,
    _OAuthHelperServer,
    check_codex_quota,
    login_codex_via_browser,
    quota_result_quota_info,
    quota_result_resets_at,
    save_auth_file,
)
from autotoken.core.oauth_helper import oauth_helper_auth_url
from autotoken.storage.accounts import (
    ACCOUNT_TYPE_FREE,
    ACCOUNT_TYPE_PLUS,
    ACCOUNT_TYPE_PRO,
    ACCOUNT_TYPE_TEAM,
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_STANDBY,
    add_account,
    find_account,
    load_accounts,
    update_account,
)

logger = logging.getLogger(__name__)

MANUAL_ACCOUNT_TIMEOUT_SECONDS = int(os.environ.get("MANUAL_ACCOUNT_OAUTH_TIMEOUT", "900"))


SUCCESS_HTML = """<html><head><meta charset="utf-8"><title>Authentication successful</title></head>
<body><h1>Authentication successful!</h1><p>You can close this window.</p></body></html>"""

ERROR_HTML = """<html><head><meta charset="utf-8"><title>Authentication failed</title></head>
<body><h1>Authentication failed</h1><p>%s</p></body></html>"""


def parse_oauth_callback_url(input_text: str) -> dict:
    """从回调 URL 中解析 code/state/error。"""
    trimmed = (input_text or "").strip()
    if not trimmed:
        raise ValueError("回调 URL 不能为空")

    candidate = trimmed
    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = "http://localhost" + candidate
        elif "=" in candidate:
            candidate = "http://localhost/?" + candidate
        elif any(ch in candidate for ch in "/?#:"):
            candidate = "http://" + candidate
        else:
            raise ValueError("无效的回调 URL")

    parsed_url = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed_url.query)
    fragment = urllib.parse.parse_qs(parsed_url.fragment)

    def get_value(name):
        return (query.get(name) or fragment.get(name) or [""])[0].strip()

    code = get_value("code")
    state = get_value("state")
    error = get_value("error") or get_value("error_description")

    if not code and not error:
        raise ValueError("回调 URL 中缺少 code")

    return {
        "code": code,
        "state": state,
        "error": error,
        "raw_url": candidate,
    }


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class _OAuthCallbackServer:
    def __init__(self, flow, port=CODEX_CALLBACK_PORT):
        self.flow = flow
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        flow = self.flow

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if not self.path.startswith("/auth/callback"):
                    self.send_error(404)
                    return

                host = self.headers.get("Host", f"localhost:{self.server.server_port}")
                raw_url = f"http://{host}{self.path}"

                try:
                    flow.record_callback(raw_url, source="auto")
                    body = SUCCESS_HTML
                    status = 200
                except Exception as exc:
                    body = ERROR_HTML % str(exc)
                    status = 400

                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, _format, *_args):
                return

        self.server = _ReusableThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info("[手动添加] 本地回调服务已启动: http://127.0.0.1:%d/auth/callback", self.port)

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.thread = None


class ManualAccountFlow:
    """参考 CLIProxyAPI：自动接回调，手动粘贴回调 URL 作为兜底。"""

    def __init__(self, *, email: str = "", password: str = "", auto_open_helper: bool = False):
        self.email = (email or "").strip().lower()
        self.password = password or ""
        self.code_verifier, code_challenge = _generate_pkce()
        self.state = secrets.token_urlsafe(16)
        self.direct_auth_url = _build_auth_url(code_challenge, self.state, native_oauth=True)
        self.auth_url = self.direct_auth_url
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._server = None
        self._helper_server = None
        self._helper_thread = None
        self._auto_open_helper = bool(auto_open_helper)
        self._auto_thread = None
        self._mail_client = None
        self._latest_email_id = 0
        self._submitted_codes: set[str] = set()
        self._helper_available = False
        self._helper_error = ""
        self._playwright_available = False
        self._playwright_error = ""
        self._otp_status = "idle"
        self._callback_payload = None
        self._callback_source = ""
        self._callback_received_at = None
        self._status = "pending_callback"
        self._message = ""
        self._error = ""
        self._account = None
        self._auto_callback_available = False
        self._auto_callback_error = ""
        self._finalized = False

    def _mark_timed_out_if_needed(self):
        if self._finalized or self._status != "pending_callback":
            return None
        timeout = max(60, MANUAL_ACCOUNT_TIMEOUT_SECONDS)
        if time.time() - self.started_at < timeout:
            return None

        self._status = "error"
        self._error = "OAuth 登录等待超时，未收到回调。请重新生成链接后再登录。"
        self._message = self._error
        self._finalized = True
        server = self._server
        helper_server = self._helper_server
        self._server = None
        self._helper_server = None
        logger.warning("[手动添加] OAuth 等待回调超时，已释放流程")
        return [item for item in (server, helper_server) if item]

    def _helper_auth_url(self) -> str:
        if not self._helper_server:
            return ""
        return oauth_helper_auth_url(self._helper_server.token, self._helper_server.port, self.direct_auth_url)

    def _prime_latest_email_id(self):
        if not self._mail_client or not self.email:
            return
        try:
            emails = self._mail_client.search_emails_by_recipient(self.email, size=1)
            if emails:
                self._latest_email_id = int(emails[0].get("emailId") or 0)
        except Exception as exc:
            logger.warning("[手动添加] 初始化验证码邮件快照失败: %s", exc)
            self._latest_email_id = 0

    def _poll_email_otp_once(self):
        if not self._mail_client or not self.email:
            return "", 0
        try:
            emails = self._mail_client.search_emails_by_recipient(self.email, size=10)
        except Exception as exc:
            logger.warning("[手动添加] 查询验证码失败: %s", exc)
            return "", 0

        for item in emails:
            try:
                email_id = int(item.get("emailId") or 0)
            except Exception:
                email_id = 0
            code = self._mail_client.extract_verification_code(item)
            if code:
                return str(code), email_id
        return "", 0

    def _helper_worker(self):
        while True:
            with self._lock:
                done = self._finalized or self._status != "pending_callback"
            if done:
                return
            server = self._helper_server
            if not server:
                return

            if server.phone_required_url:
                with self._lock:
                    self._status = "error"
                    self._error = f"OAuth 需要手机号验证: {server.phone_required_url}"
                    self._message = self._error
                    self._finalized = True
                return

            if server.auth_code:
                callback_url = server.callback_url or (
                    f"http://localhost:{CODEX_CALLBACK_PORT}/auth/callback?code={urllib.parse.quote(server.auth_code)}"
                    f"&state={urllib.parse.quote(self.state)}"
                )
                try:
                    self.record_callback(callback_url, source="auto")
                    self.maybe_finalize()
                except Exception as exc:
                    with self._lock:
                        self._status = "error"
                        self._error = str(exc)
                        self._message = str(exc)
                        self._finalized = True
                return

            code, email_id = self._poll_email_otp_once()
            if code:
                server.otp = code
                self._submitted_codes.add(code)
                self._latest_email_id = max(self._latest_email_id, email_id)
                with self._lock:
                    self._otp_status = "filled"
                    self._message = "已从邮箱服务获取验证码，正在等待浏览器回填并完成 OAuth..."
                logger.info("[手动添加] 已获取邮箱验证码: %s", code)
                time.sleep(4)
                continue

            with self._lock:
                if self._otp_status == "idle":
                    self._otp_status = "waiting"
            time.sleep(3)

    def _start_helper_if_possible(self):
        if not self.email:
            return
        try:
            from autotoken.mail import TemporaryEmailClient

            self._mail_client = TemporaryEmailClient()
            self._mail_client.login()
            self._prime_latest_email_id()

            self._helper_server = _OAuthHelperServer(
                email=self.email,
                password=self.password,
                token=secrets.token_urlsafe(18),
            ).start()
            self.auth_url = self._helper_auth_url() or self.direct_auth_url
            self._helper_available = True
            self._helper_thread = threading.Thread(target=self._helper_worker, daemon=True)
            self._helper_thread.start()
            logger.info("[手动添加] 自动取码 helper 已启动: %s", self.email)
        except Exception as exc:
            self._helper_available = False
            self._helper_error = str(exc)
            self.auth_url = self.direct_auth_url
            logger.warning("[手动添加] 自动取码 helper 启动失败: %s", exc)

    def _run_playwright_oauth(self):
        try:
            from autotoken.mail import TemporaryEmailClient
            from autotoken.storage.accounts import find_account, load_accounts

            mail_client = TemporaryEmailClient()
            mail_client.login()
            with self._lock:
                if self._finalized:
                    return
                self._otp_status = "waiting"
                self._message = "Playwright OAuth 已启动，正在等待邮箱验证码..."

            bundle = login_codex_via_browser(
                self.email,
                self.password,
                mail_client=mail_client,
                use_personal=True,
                native_oauth=True,
                headless=False,
                mail_account_id=(find_account(load_accounts(), self.email) or {}).get("cloudmail_account_id"),
            )
            if not bundle:
                raise RuntimeError("Playwright OAuth 未返回 token bundle")

            result = self._finalize_account(bundle)
            with self._lock:
                self._status = "completed"
                self._message = result["message"]
                self._account = result["account"]
                self._error = ""
                self._otp_status = "completed"
                self._finalized = True
            logger.info("[手动添加] Playwright OAuth 完成: %s", result["account"]["email"])
        except Exception as exc:
            with self._lock:
                if self._finalized:
                    return
                self._status = "error"
                self._error = str(exc)
                self._message = str(exc)
                self._playwright_error = str(exc)
                self._finalized = True
            logger.error("[手动添加] Playwright OAuth 失败: %s", exc)
        finally:
            if self._server:
                self._server.stop()
                self._server = None
            if self._helper_server:
                self._helper_server.stop()
                self._helper_server = None

    def _start_playwright_oauth_if_possible(self):
        if not self.email:
            return
        self._playwright_available = True
        self._auto_thread = threading.Thread(target=self._run_playwright_oauth, daemon=True)
        self._auto_thread.start()

    def start(self):
        try:
            self._server = _OAuthCallbackServer(self)
            self._server.start()
            self._auto_callback_available = True
            self._message = (
                "已生成 OAuth 链接；若当前机器可访问 localhost:1455，将自动接收回调。否则请手动粘贴回调 URL。"
            )
        except OSError as exc:
            self._auto_callback_available = False
            self._auto_callback_error = str(exc)
            self._message = f"本地自动回调服务启动失败（{exc}），请改用手动粘贴回调 URL。"
            logger.warning("[手动添加] 本地回调服务启动失败: %s", exc)

        if self.email:
            self._start_playwright_oauth_if_possible()
            self._message = "已启动 Playwright OAuth；系统会从邮箱服务读取验证码并自动填写。"

        logger.info("[手动添加] 已生成 OAuth 链接")
        return self.status()

    def record_callback(self, callback_url, source="manual"):
        parsed = parse_oauth_callback_url(callback_url)
        if parsed.get("state") and parsed["state"] != self.state:
            raise ValueError("OAuth state 不匹配")

        with self._lock:
            if self._finalized:
                raise ValueError("OAuth 流程已结束，请重新生成链接")
            self._callback_payload = parsed
            self._callback_source = source
            self._callback_received_at = time.time()
            self._message = "已收到 OAuth 回调，正在完成认证..."
            logger.info("[手动添加] 已收到%s回调", "自动" if source == "auto" else "手动")

    def submit_callback(self, callback_url):
        self.record_callback(callback_url, source="manual")
        self.maybe_finalize()
        return self.status()

    def maybe_finalize(self):
        with self._lock:
            if self._finalized or not self._callback_payload:
                return
            payload = dict(self._callback_payload)

        try:
            if payload.get("error"):
                raise RuntimeError(f"OAuth 返回错误: {payload['error']}")

            bundle = _exchange_auth_code(payload["code"], self.code_verifier)
            if not bundle:
                raise RuntimeError("OAuth code 交换 token 失败")

            result = self._finalize_account(bundle)
            with self._lock:
                self._status = "completed"
                self._message = result["message"]
                self._account = result["account"]
                self._error = ""
                self._finalized = True
            logger.info("[手动添加] 完成: %s", result["account"]["email"])
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._error = str(exc)
                self._message = str(exc)
                self._finalized = True
            logger.error("[手动添加] 失败: %s", exc)
        finally:
            if self._server:
                self._server.stop()
                self._server = None
            if self._helper_server:
                self._helper_server.stop()
                self._helper_server = None

    def _finalize_account(self, bundle):
        email = (bundle.get("email") or "").lower()
        if not email:
            raise RuntimeError("OAuth token 中缺少邮箱")

        auth_file = save_auth_file(bundle)
        plan_type = bundle.get("plan_type") or "unknown"
        normalized_plan = str(plan_type or "unknown").strip().lower()
        account_status = STATUS_ACTIVE if normalized_plan in {"free", "team", "plus", "pro"} else STATUS_STANDBY
        # plan_type=team → 拿到 Team bundle,同时 PATCH 成功意味着完整 ChatGPT 席位;
        # 其它 plan_type(free/plus/unknown)按 codex 处理,下游 fill 会据此做差异化判断。
        seat_label = "chatgpt" if normalized_plan == "team" else "codex"
        account_type = {
            "free": ACCOUNT_TYPE_FREE,
            "team": ACCOUNT_TYPE_TEAM,
            "plus": ACCOUNT_TYPE_PLUS,
            "pro": ACCOUNT_TYPE_PRO,
        }.get(normalized_plan, ACCOUNT_TYPE_FREE)

        accounts = load_accounts()
        account = find_account(accounts, email)
        if not account:
            add_account(email, "", seat_type=seat_label)

        update_fields = {
            "status": account_status,
            "account_type": account_type,
            "seat_type": seat_label,
            "auth_file": auth_file,
            "quota_exhausted_at": None,
            "quota_resets_at": None,
            "last_active_at": time.time(),
        }

        token = bundle.get("access_token")
        account_id = bundle.get("account_id")
        if token and account_id:
            quota_status, quota_info = check_codex_quota(token, account_id=account_id)
            if quota_status == "ok" and isinstance(quota_info, dict):
                update_fields["last_quota"] = quota_info
            elif quota_status == "exhausted":
                snapshot = quota_result_quota_info(quota_info)
                if snapshot:
                    update_fields["last_quota"] = snapshot
                update_fields["status"] = STATUS_EXHAUSTED
                update_fields["quota_exhausted_at"] = time.time()
                update_fields["quota_resets_at"] = quota_result_resets_at(quota_info) or int(time.time() + 18000)

        update_account(email, **update_fields)
        logger.info("[手动添加] 自动 CPA 同步已禁用，需要时请手动执行“同步 CPA”")

        return {
            "status": "completed",
            "message": f"已添加账号 {email}",
            "account": {
                "email": email,
                "plan_type": plan_type,
                "status": account_status,
                "auth_file": auth_file,
            },
        }

    def status(self):
        self.maybe_finalize()
        servers_to_stop = []
        with self._lock:
            servers_to_stop = self._mark_timed_out_if_needed() or []
            status = {
                "in_progress": self._status == "pending_callback",
                "status": self._status,
                "state": self.state,
                "auth_url": self.auth_url,
                "direct_auth_url": self.direct_auth_url,
                "email": self.email,
                "started_at": self.started_at,
                "message": self._message,
                "error": self._error,
                "account": self._account,
                "callback_received": self._callback_received_at is not None,
                "callback_source": self._callback_source,
                "auto_callback_available": self._auto_callback_available,
                "auto_callback_error": self._auto_callback_error,
                "helper_available": self._helper_available,
                "helper_error": self._helper_error,
                "playwright_available": self._playwright_available,
                "playwright_error": self._playwright_error,
                "otp_status": self._otp_status,
            }
        for server_to_stop in servers_to_stop:
            server_to_stop.stop()
        return status

    def stop(self):
        if self._server:
            self._server.stop()
            self._server = None
        if self._helper_server:
            self._helper_server.stop()
            self._helper_server = None
