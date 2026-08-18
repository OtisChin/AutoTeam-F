"""Mail provider 工厂 + 向后兼容别名。

调用方继续用:
    from autotoken.mail import TemporaryEmailClient
    client = TemporaryEmailClient()  # 实际由 MAIL_PROVIDER 决定 provider

新代码也可以用更明确的:
    from autotoken.mail import get_mail_client
    client = get_mail_client()
"""

from __future__ import annotations

import os

from autotoken.mail.base import Account, Email, MailProvider

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
      - icloud
      - generic-api
      - luckmail
      - `cf_temp_email` / `maillab` 为历史别名

    任何拼写错误都会抛 ValueError 并列出可选值,避免静默走默认。
    """
    raw = (os.environ.get("MAIL_PROVIDER") or "cloudflare_temp_email").strip().lower()
    if raw in ("cf_temp_email", "cloudflare_temp_email", ""):
        from autotoken.mail.cloudflare_temp_email import CloudflareTempEmailClient

        return CloudflareTempEmailClient()
    if raw in ("maillab", "cloud-mail", "cloud_mail"):
        from autotoken.mail.cloud_mail import CloudMailProviderClient

        return CloudMailProviderClient()
    if raw in ("outlook", "microsoft_outlook", "hotmail"):
        from autotoken.mail.outlook import OutlookMailProvider

        return OutlookMailProvider()
    if raw in ("icloud", "icloud.com", "apple_icloud", "apple-icloud"):
        from autotoken.mail.icloud import ICloudMailProvider

        return ICloudMailProvider()
    if raw in ("generic-api", "generic_api", "genericapi", "通用api", "通用-api"):
        from autotoken.mail.generic_api import GenericApiMailProvider

        return GenericApiMailProvider()
    if raw in ("mail.com", "mailcom", "mail_com"):
        from autotoken.mail.mailcom import MailComMailProvider

        return MailComMailProvider()
    if raw in ("luckmail", "lucky_mail", "lucky-mail"):
        from autotoken.mail.luckmail import LuckMailProvider

        return LuckMailProvider()
    raise ValueError(
        f"未知 MAIL_PROVIDER={raw!r}(可选: cloudflare_temp_email | cloud-mail | outlook | icloud | generic-api | mail.com | luckmail)"
    )


# 对外统一后的首选名字。
TemporaryEmailClient = get_mail_client

# 历史兼容别名:已有调用继续可用。
CloudMailClient = get_mail_client
