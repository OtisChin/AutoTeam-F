"""向后兼容 stub。

历史代码 / 外部脚本依然可以:
    from autoteam.cloudmail import CloudMailClient

实际实现已搬到 `autoteam.mail` 包,由 MAIL_PROVIDER 环境变量决定走哪个后端。
"""

from autoteam.mail import CloudMailClient  # noqa: F401  re-export
