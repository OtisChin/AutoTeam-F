"""Mail provider 工厂 + 向后兼容别名。

调用方继续用:
    from autoteam.mail import TemporaryEmailClient
    client = TemporaryEmailClient()  # 实际由 MAIL_PROVIDER 决定 provider

新代码也可以用更明确的:
    from autoteam.mail import get_mail_client
    client = get_mail_client()
"""

from __future__ import annotations

import os

from autoteam.mail.base import Account, Email, MailProvider

__all__ = [
    "Account",
    "Email",
    "MailProvider",
    "TemporaryEmailClient",
    "CloudMailClient",
    "get_mail_client",
]


def get_mail_client() -> MailProvider:
    """根据环境变量 MAIL_PROVIDER 返回对应 provider 实例。

    可选值:
      - cloudflare_temp_email(默认)
      - cloud-mail
      - outlook
      - luckmail
      - `cf_temp_email` / `maillab` 为历史别名

    任何拼写错误都会抛 ValueError 并列出可选值,避免静默走默认。
    """
    raw = (os.environ.get("MAIL_PROVIDER") or "cloudflare_temp_email").strip().lower()
    if raw in ("cf_temp_email", "cloudflare_temp_email", ""):
        from autoteam.mail.cloudflare_temp_email import CloudflareTempEmailClient

        return CloudflareTempEmailClient()
    if raw in ("maillab", "cloud-mail", "cloud_mail"):
        from autoteam.mail.cloud_mail import CloudMailProviderClient

        return CloudMailProviderClient()
    if raw in ("outlook", "microsoft_outlook", "hotmail"):
        from autoteam.mail.outlook import OutlookMailProvider

        return OutlookMailProvider()
    if raw in ("luckmail", "lucky_mail", "lucky-mail"):
        from autoteam.mail.luckmail import LuckMailProvider

        return LuckMailProvider()
    raise ValueError(f"未知 MAIL_PROVIDER={raw!r}(可选: cloudflare_temp_email | cloud-mail | outlook | luckmail)")


# 对外统一后的首选名字。
TemporaryEmailClient = get_mail_client

# 历史兼容别名:已有调用继续可用。
CloudMailClient = get_mail_client
