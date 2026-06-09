"""cloud-mail 后端的 MailProvider 实现。

实现基于 maillab/cloud-mail 仓库 mail-worker 源码现场验证(2026-04-25):
  - 鉴权:`POST /login` body `{email, password}` → `{code:200, data:{token}}`
            后续请求带 `Authorization: <jwt>` header(裸 JWT,**无 Bearer 前缀**)
  - 列出账户:`GET /account/list` → `{code:200, data:[Account...]}`
  - 创建账户:`POST /account/add` body `{email}` → `{code:200, data:Account}`
                注:cloud-mail 接受完整 email 地址,不像 cloudflare_temp_email 那样拆 prefix+domain
  - 删除账户:`DELETE /account/delete?accountId=N` → `{code:200}`
  - 邮件列表:`GET /email/list?accountId=N&size=10&emailId=0&allReceive=0&timeSort=0`
                → `{code:200, data:{list:[...], total, latestEmail}}`
  - 最新邮件:`GET /email/latest?accountId=N&emailId=0` → `{code:200, data:[...]}`
                按 emailId 降序最多返回 20 封
  - 删除邮件:`DELETE /email/delete?emailIds=1,2,3` → `{code:200}`(软删除)

Email 实体字段映射(已现场验证):
  emailId | sendEmail | name(发件人显示名) | subject | text(纯文本) |
  content(HTML body) | toEmail | accountId | createTime(ISO string) | messageId

⚠️ TODO(cloud-mail-verify) 标记的项是设计文档 §6 中尚未 100% 摸清的实施细节,
需要 implementer 在真实 cloud-mail 实例上跑一次 e2e 后回填。
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone

import requests

from autotoken.mail.base import (
    MailProvider,
    html_to_visible_text,
    normalize_email_addr,
)
from autotoken.settings.config import (
    CLOUD_MAIL_ADMIN_EMAIL,
    CLOUD_MAIL_ADMIN_PASSWORD,
    CLOUD_MAIL_API_URL,
    CLOUD_MAIL_DOMAIN,
)

logger = logging.getLogger(__name__)


def _parse_create_time(value) -> int | None:
    """cloud-mail createTime 是 SQL CURRENT_TIMESTAMP 生成的 ISO 字符串 / epoch 数字两种可能,统一返回 epoch seconds。

    已验证:entity/email.js 默认值 `CURRENT_TIMESTAMP`,Cloudflare D1/SQLite 返回为 ISO 字符串。
    若后续 cloud-mail 升级返回 epoch,这里也兼容。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # 大于 1e12 视为毫秒
        return int(value / 1000) if value > 1e12 else int(value)
    text = str(value).strip()
    if not text:
        return None
    # SQLite "YYYY-MM-DD HH:MM:SS" 或 ISO8601
    text_iso = text.replace(" ", "T") if "T" not in text and " " in text else text
    text_iso = text_iso.rstrip("Z")
    try:
        dt = datetime.fromisoformat(text_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        try:
            return int(float(text))
        except Exception:
            return None


class CloudMailProviderClient(MailProvider):
    """cloud-mail 后端客户端。"""

    provider_name = "cloud-mail"
    _TOKEN_LOCK = threading.Lock()
    _SHARED_TOKENS: dict[tuple[str, str], str] = {}

    def __init__(self):
        self.base_url = (CLOUD_MAIL_API_URL or "").rstrip("/")
        self.username = CLOUD_MAIL_ADMIN_EMAIL or ""
        self.password = CLOUD_MAIL_ADMIN_PASSWORD or ""
        self.session = requests.Session()
        self.token: str | None = None
        self._account_id_by_email: dict[str, int] = {}
        self._account_email_by_id: dict[str, str] = {}

    # ------------------------------------------------------------------ http

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        # 现场验证(security/security.js + const/constant.js):
        #   header 名 = Authorization;值 = 裸 JWT,**不**加 "Bearer "
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def _token_cache_key(self) -> tuple[str, str]:
        return self.base_url, self.username

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request_with_auth_retry("get", path, params=params)

    def _post(self, path: str, body: dict | None = None) -> dict:
        return self._request_with_auth_retry("post", path, body=body)

    def _delete(self, path: str, params: dict | None = None) -> dict:
        return self._request_with_auth_retry("delete", path, params=params)

    def _put(self, path: str, body: dict | None = None) -> dict:
        return self._request_with_auth_retry("put", path, body=body)

    def _request_with_auth_retry(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        request = getattr(self.session, method)
        kwargs = {"headers": self._headers(), "timeout": 30}
        if params is not None:
            kwargs["params"] = params
        if body is not None:
            kwargs["json"] = body

        r = request(self._url(path), **kwargs)
        if path != "/login" and r.status_code == 401:
            logger.warning("[cloud-mail] %s HTTP 401, 重新登录后重试一次", path)
            self.login(force=True)
            kwargs["headers"] = self._headers()
            r = request(self._url(path), **kwargs)

        resp = self._parse_response(r, path)
        if path != "/login" and self._looks_like_auth_invalid(resp):
            logger.warning("[cloud-mail] %s token 已失效, 重新登录后重试一次", path)
            self.login(force=True)
            kwargs["headers"] = self._headers()
            r = request(self._url(path), **kwargs)
            resp = self._parse_response(r, path)
        return resp

    @staticmethod
    def _looks_like_auth_invalid(resp: dict) -> bool:
        if not isinstance(resp, dict):
            return False
        message = str(resp.get("message") or resp.get("msg") or "").lower()
        return str(resp.get("code")) == "401" or "身份认证失效" in message or ("token" in message and "invalid" in message)

    @staticmethod
    def _parse_response(r: requests.Response, path: str) -> dict:
        if r.status_code == 404:
            # 协议错配嗅探:base_url 指向了 cloudflare_temp_email 服务器(只认 /admin/* 路由),
            # /login 之类的 maillab 路由会返回 404。给出可读切换提示。
            raise Exception(
                f"cloud-mail {path} 返回 HTTP 404 — 你的 CLOUD_MAIL_API_URL 可能指向 dreamhunter2333/cloudflare_temp_email 服务器,"
                "请改用 MAIL_PROVIDER=cloudflare_temp_email + CLOUDFLARE_TEMP_EMAIL_BASE_URL/CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD/CLOUDFLARE_TEMP_EMAIL_DOMAIN。"
            )
        if r.status_code != 200:
            raise Exception(f"cloud-mail {path} HTTP {r.status_code}: {(r.text or '')[:200]}")
        try:
            return r.json() or {}
        except Exception as exc:
            raise Exception(f"cloud-mail {path} 响应非 JSON: {exc}") from exc

    # ------------------------------------------------------------------ auth

    def login(self, *, force: bool = False) -> str:
        """POST /login,获得 JWT token。"""
        if not self.base_url:
            raise Exception("cloud-mail 登录失败: 未配置 CLOUD_MAIL_API_URL")
        if not self.username or not self.password:
            raise Exception("cloud-mail 登录失败: 未配置 CLOUD_MAIL_ADMIN_EMAIL / CLOUD_MAIL_ADMIN_PASSWORD")

        cache_key = self._token_cache_key()
        with self._TOKEN_LOCK:
            cached = self._SHARED_TOKENS.get(cache_key)
            if cached and not force:
                self.token = cached
                return cached

            # TODO(cloud-mail-verify): 部分部署启用了 Turnstile,登录可能要求 token 字段。
            # 目前按"无 captcha"的最常见情况实现;若启用 captcha,login() 会以 code!=200 失败,
            # 此时需要在 .env 里设置 MAILLAB_TURNSTILE_TOKEN(暂未实现)。
            body = {"email": self.username, "password": self.password}
            resp = self._post("/login", body)
            if resp.get("code") != 200:
                raise Exception(f"cloud-mail 登录失败: {resp.get('message') or resp}")

            data = resp.get("data") or {}
            token = data.get("token")
            if not token:
                raise Exception(f"cloud-mail 登录响应缺少 token 字段: {data}")
            self.token = token
            self._SHARED_TOKENS[cache_key] = token
            logger.info("[cloud-mail] 登录成功 (token=%s...)", str(token)[:10])
            return token

    def _ensure_login(self):
        if not self.token:
            self.login()

    # ------------------------------------------------------------------ accounts

    @staticmethod
    def _build_email_address(prefix: str | None, domain: str | None) -> tuple[str, str]:
        """cloud-mail 创建邮箱要给完整 email 地址,而不是 prefix+domain 分开。

        domain 解析优先级:
          1. 显式参数
          2. runtime_config.json
          3. 环境变量 CLOUD_MAIL_DOMAIN / MAILLAB_DOMAIN / CLOUDMAIL_DOMAIN(后两者兼容回落)
        """
        if domain:
            domain_clean = domain.lstrip("@").strip()
        else:
            try:
                from autotoken.settings.runtime_config import get_register_domain

                domain_clean = (get_register_domain() or "").lstrip("@").strip()
            except Exception:
                domain_clean = ""
            if not domain_clean:
                domain_clean = ((CLOUD_MAIL_DOMAIN or os.environ.get("CLOUDMAIL_DOMAIN") or "").lstrip("@").strip())

        if not domain_clean:
            raise Exception("创建邮箱失败: 未配置注册域名(CLOUD_MAIL_DOMAIN)")

        # cloud-mail 文档未严格说明 prefix 字符集,沿用 cloudflare_temp_email 的保守白名单。
        if not prefix:
            cleaned = uuid.uuid4().hex[:10]
        else:
            cleaned = re.sub(r"[^A-Za-z0-9._-]", "", str(prefix)).strip(".-_")
            cleaned = cleaned[:60] or uuid.uuid4().hex[:10]

        return cleaned, f"{cleaned}@{domain_clean}"

    def create_temp_email(self, prefix=None, domain=None):
        """POST /account/add body `{email}` → 返回 (accountId, email)。"""
        self._ensure_login()
        _, full_email = self._build_email_address(prefix, domain)

        # TODO(cloud-mail-verify): 若 cloud-mail 部署开启 addVerify,/account/add 会要求 token 字段。
        # 当前按"无验证"路径走;失败会以 code!=200 抛出,实施 e2e 时回填验证开关支持。
        resp = self._post("/account/add", {"email": full_email})
        if resp.get("code") != 200:
            raise Exception(f"创建邮箱失败: {resp.get('message') or resp}")
        data = resp.get("data") or {}
        account_id = data.get("accountId") or data.get("id")
        email = data.get("email") or full_email
        if not account_id:
            raise Exception(f"创建邮箱失败: 响应缺少 accountId: {data}")
        logger.info("[cloud-mail] 临时邮箱已创建: %s (accountId=%s)", email, account_id)
        return account_id, email

    # cloud-mail service/account-service.js list() 服务端硬 cap 30。请求 size > 30 也只能
    # 拿到 30 条,需要循环翻页(lastSort + accountId 游标)拉满。
    _ACCOUNT_LIST_PAGE_CAP = 30

    def list_accounts(self, size: int = 200):
        """GET /account/list → 返回 [{accountId, email, ...}, ...]。

        服务端单页 cap 30(account-service.js list);本方法循环翻页直到拿满 size 条
        或服务端不再返回新行。size=None / 0 表示尽量拉全。
        """
        self._ensure_login()
        target = int(size) if size else 0
        out: list[dict] = []
        last_sort = 0
        last_id = 0
        seen_ids: set[int] = set()
        # 防御:理论上 ceil(size / 30) 页就够,设上限避免恶意服务端无限翻页
        max_pages = max(1, (target // self._ACCOUNT_LIST_PAGE_CAP) + 2) if target else 50
        for _ in range(max_pages):
            params = {"size": self._ACCOUNT_LIST_PAGE_CAP}
            if last_sort or last_id:
                # service 用 lastSort + accountId 做游标,首页留空走默认降序
                params["lastSort"] = last_sort
                params["accountId"] = last_id
            resp = self._get("/account/list", params=params)
            if resp.get("code") != 200:
                break
            rows = resp.get("data") or []
            if not rows:
                break
            new_in_page = 0
            for row in rows:
                aid = row.get("accountId") or row.get("id")
                if aid is None or aid in seen_ids:
                    continue
                seen_ids.add(aid)
                new_in_page += 1
                out.append(
                    {
                        "accountId": aid,
                        "email": row.get("email"),
                        # cloud-mail 不返回 password(账户体系不基于密码,登录靠主账号 jwt)
                        "password": None,
                        "createTime": _parse_create_time(row.get("createTime")),
                        "updateTime": _parse_create_time(row.get("updateTime")),
                        # entity/account.js 实际列:accountId/email/name/status/
                        # latestEmailTime/createTime/userId/allReceive/sort/isDel
                        # 没有 mailCount/sendCount,只暴露真实字段
                        "name": row.get("name"),
                        "status": row.get("status"),
                        "latestEmailTime": _parse_create_time(row.get("latestEmailTime")),
                        "raw": row,
                    }
                )
                email = normalize_email_addr(row.get("email"))
                if email:
                    self._account_id_by_email[email] = aid
                    self._account_email_by_id[str(aid)] = email
                if target and len(out) >= target:
                    return out
            if new_in_page == 0:
                # 一整页都是已见过的 → 服务端已没新行
                break
            tail = rows[-1]
            last_sort = tail.get("sort") or 0
            last_id = tail.get("accountId") or tail.get("id") or 0
        return out

    def delete_account(self, account_id):
        """DELETE /account/delete?accountId=N。account_id 允许 email,自动解析。"""
        self._ensure_login()
        real_id = self._resolve_account_id(account_id)
        if not real_id:
            logger.warning("[cloud-mail] delete_account: 找不到对应的 accountId (%s)", account_id)
            return {"code": 404, "message": "account not found"}

        resp = self._delete("/account/delete", params={"accountId": real_id})
        code = resp.get("code", 200)
        if code == 200:
            logger.info("[cloud-mail] 临时邮箱已删除 (accountId=%s)", real_id)
            return {"code": 200}
        return {"code": code, "message": resp.get("message")}

    # ------------------------------------------------------------------ emails

    def _resolve_account_id(self, value):
        """把数字 id / email / 字符串 id 统一解析为数字 accountId。"""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            pass

        email_str = normalize_email_addr(value)
        if "@" not in email_str:
            return None
        cached = self._account_id_by_email.get(email_str)
        if cached:
            return cached

        for row in self.list_accounts(size=0):
            if normalize_email_addr(row.get("email")) == email_str:
                account_id = row.get("accountId")
                if account_id:
                    self._account_id_by_email[email_str] = account_id
                    self._account_email_by_id[str(account_id)] = email_str
                return account_id
        return None

    def _resolve_account_email(self, account_id):
        if not account_id:
            return None
        try:
            int(account_id)
        except (TypeError, ValueError):
            return str(account_id) if "@" in str(account_id) else None

        cached = self._account_email_by_id.get(str(account_id))
        if cached:
            return cached

        for row in self.list_accounts(size=0):
            if str(row.get("accountId")) == str(account_id):
                email = normalize_email_addr(row.get("email"))
                if email:
                    self._account_email_by_id[str(account_id)] = email
                    self._account_id_by_email[email] = row.get("accountId")
                return row.get("email")
        return None

    def _normalize_mail_record(self, row: dict, account_email_hint: str | None = None) -> dict:
        """cloud-mail email 行 → AutoToken 期望的 dict 字段集。

        字段映射(已验证 entity/email.js):
          emailId       → emailId
          accountEmail  → toEmail(cloud-mail 没有 accountEmail,用收件人地址)
          receiveEmail  → toEmail
          toEmail       → toEmail
          sendEmail     → sendEmail
          sender        → name(发件人显示名)
          subject       → subject
          text          → text(纯文本)
          content       → content(HTML body) — 若缺失则从 message 字段兜底
          messageId     → messageId
          createTime    → ISO string → epoch seconds
          raw           → 原始整行 dump
        """
        html_body = row.get("content") or row.get("message") or ""
        text_body = row.get("text") or ""
        if not text_body and html_body:
            text_body = html_to_visible_text(html_body)

        recipient = row.get("toEmail") or account_email_hint or ""

        return {
            "emailId": row.get("emailId"),
            "accountId": row.get("accountId"),
            "accountEmail": recipient,
            "receiveEmail": recipient,
            "toEmail": recipient,
            "sendEmail": row.get("sendEmail"),
            "sender": row.get("name") or row.get("sendEmail"),
            "subject": row.get("subject"),
            "text": text_body,
            "content": html_body,
            "messageId": row.get("messageId"),
            "createTime": _parse_create_time(row.get("createTime")),
            "raw": row,
        }

    def list_emails(self, account_id, size: int = 10, account_email_hint: str | None = None):
        """GET /email/list?accountId=N&type=0&size=10。

        响应:`{code:200, data:{list:[...], total, latestEmail}}`

        critical: type 必填。cloud-mail service/email-service.js list() where 子句含
        `eq(email.type, type)`,emailConst 中 RECEIVE=0 / SEND=1。type 缺省时 drizzle
        翻成 IS NULL,匹配不到任何行(收件全是 type=0)→ 列表永远为空。
        """
        self._ensure_login()
        real_id = self._resolve_account_id(account_id)
        if not real_id:
            return []

        resp = self._get(
            "/email/list",
            params={
                "accountId": real_id,
                "type": 0,  # RECEIVE = 0 (emailConst.type),不传会拿不到任何邮件
                "size": min(int(size or 10), 50),
                "emailId": 0,
                "timeSort": 0,
                "allReceive": 0,
            },
        )
        if resp.get("code") != 200:
            logger.warning(
                "[cloud-mail] /email/list 返回非 200: accountId=%s code=%s message=%s",
                real_id,
                resp.get("code"),
                resp.get("message") or resp,
            )
            return []
        data = resp.get("data") or {}
        rows = data.get("list") or []
        hint = normalize_email_addr(account_email_hint) if account_email_hint else self._resolve_account_email(real_id)
        return [self._normalize_mail_record(row, account_email_hint=hint) for row in rows]

    def get_latest_emails(self, account_id, email_id: int = 0, all_receive: int = 0):
        """GET /email/latest?accountId=N&emailId=cursor。"""
        self._ensure_login()
        real_id = self._resolve_account_id(account_id)
        if not real_id:
            return []
        resp = self._get(
            "/email/latest",
            params={"accountId": real_id, "emailId": email_id, "allReceive": all_receive},
        )
        if resp.get("code") != 200:
            logger.warning(
                "[cloud-mail] /email/latest 返回非 200: accountId=%s code=%s message=%s",
                real_id,
                resp.get("code"),
                resp.get("message") or resp,
            )
            return []
        rows = resp.get("data") or []
        hint = self._resolve_account_email(real_id)
        return [self._normalize_mail_record(row, account_email_hint=hint) for row in rows]

    def search_emails_by_recipient(self, to_email, size: int = 10, account_id=None):
        """cloud-mail 端没有"按 toEmail 过滤"的 query,只能先解析 accountId 再 list_emails。"""
        target = normalize_email_addr(to_email)
        if not target:
            return []
        real_id = account_id if account_id is not None else self._resolve_account_id(target)
        if not real_id:
            return []
        results = self.list_emails(real_id, size=size, account_email_hint=target)
        if not results:
            results = self.get_latest_emails(real_id, email_id=0, all_receive=0)
        # cloud-mail 列表已按 accountId 过滤,这里再做一次 toEmail 严格匹配兜底。
        out = []
        for em in results:
            em_to = normalize_email_addr(em.get("toEmail"))
            if em_to and em_to != target:
                continue
            if account_id is not None:
                em["accountId"] = account_id
            out.append(em)
        return out

    def delete_emails_for(self, to_email):
        """删除指定收件人全部邮件:list → DELETE /email/delete?emailIds=...。"""
        target = normalize_email_addr(to_email)
        if not target:
            return 0
        real_id = self._resolve_account_id(target)
        if not real_id:
            return 0

        emails = self.list_emails(real_id, size=100)
        ids = [str(em.get("emailId")) for em in emails if em.get("emailId")]
        if not ids:
            return 0

        try:
            resp = self._delete("/email/delete", params={"emailIds": ",".join(ids)})
            if resp.get("code") == 200:
                logger.info("[cloud-mail] 已删除 %s 的 %d 封邮件", target, len(ids))
                return len(ids)
        except Exception as exc:
            logger.warning("[cloud-mail] 批量删除失败,回退逐封删除: %s", exc)

        # 回退:逐封 DELETE
        deleted = 0
        for mid in ids:
            try:
                resp = self._delete("/email/delete", params={"emailIds": mid})
                if resp.get("code") == 200:
                    deleted += 1
            except Exception:
                pass
        return deleted


# 历史类名兼容别名。
MaillabClient = CloudMailProviderClient
