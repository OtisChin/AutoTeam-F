"""Register-domain configuration HTTP routes."""

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotoken.api_routes.input_limits import validate_list_payload_limit

logger = logging.getLogger(__name__)
REGISTER_DOMAINS_MAX_ITEMS = 200


class RegisterDomainParams(BaseModel):
    domain: str
    verify: bool = True


class RegisterDomainsParams(BaseModel):
    domains: list[str]
    selected: str | None = None


def _clean_domain(value: str | None) -> str:
    return (value or "").strip().lstrip("@").strip()


def create_register_domain_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/config/register-domain")
    def get_register_domain_api():
        """Read the temporary-email domain used for account registration."""
        from autotoken.settings.config import CLOUD_MAIL_DOMAIN, CLOUDFLARE_TEMP_EMAIL_DOMAIN
        from autotoken.settings.runtime_config import get, get_register_domain, get_register_domains

        override = (get("register_domain") or "").strip()
        return {
            "domain": get_register_domain(),
            "domains": get_register_domains(),
            "override": override,
            "env_default": (CLOUD_MAIL_DOMAIN or CLOUDFLARE_TEMP_EMAIL_DOMAIN or "").lstrip("@").strip(),
        }

    @router.put("/api/config/register-domain")
    def put_register_domain_api(params: RegisterDomainParams):
        """Update the account registration domain, optionally probing mail-provider support."""
        from autotoken.mail import TemporaryEmailClient
        from autotoken.settings.runtime_config import set_register_domain

        cleaned = _clean_domain(params.domain)
        if not cleaned:
            raise HTTPException(status_code=400, detail="域名不能为空")

        leaked_probe = None
        if params.verify:
            probe_prefix = f"probe{int(time.time())}"
            acct_id = None
            probe_email = None
            try:
                client = TemporaryEmailClient()
                client.login()
                acct_id, probe_email = client.create_temp_email(prefix=probe_prefix, domain=cleaned)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"域名验证失败: {exc}") from exc
            try:
                if acct_id is not None:
                    client.delete_account(acct_id)
            except Exception as exc:
                logger.warning("[config] 删除域名探测邮箱失败 (%s, id=%s): %s", probe_email, acct_id, exc)
                leaked_probe = {"email": probe_email, "acct_id": acct_id, "error": str(exc)}

        set_register_domain(cleaned)
        logger.info("[config] register_domain 已切换为 @%s", cleaned)
        resp = {"message": f"注册域名已切换为 @{cleaned}", "domain": cleaned}
        if leaked_probe:
            resp["warning"] = (
                f"域名已保存,但探测邮箱 {leaked_probe['email']} 回收失败,请手动在临时邮箱服务中删除"
                f" (id={leaked_probe['acct_id']}): {leaked_probe['error']}"
            )
            resp["leaked_probe"] = leaked_probe
        return resp

    @router.put("/api/config/register-domains")
    def put_register_domains_api(params: RegisterDomainsParams):
        """Save the allowed account registration domains and active selected domain."""
        from autotoken.settings.runtime_config import set_register_domain, set_register_domains

        validate_list_payload_limit(params.domains, max_items=REGISTER_DOMAINS_MAX_ITEMS, label="注册域名")
        cleaned = []
        seen = set()
        for domain in params.domains or []:
            value = _clean_domain(domain)
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(value)

        if not cleaned:
            raise HTTPException(status_code=400, detail="domains 不能为空")

        selected = _clean_domain(params.selected)
        if selected and selected not in cleaned:
            raise HTTPException(status_code=400, detail="selected 必须在 domains 列表中")

        saved = set_register_domains(cleaned)
        active = set_register_domain(selected or saved[0])
        return {
            "message": f"已保存 {len(saved)} 个注册域名",
            "domains": saved,
            "selected": active,
        }

    return router
