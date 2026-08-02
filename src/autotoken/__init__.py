"""AutoToken - ChatGPT Team 账号自动轮转管理工具"""

__version__ = "0.1.0"

import logging

from rich.logging import RichHandler

from autotoken.core.env import install_legacy_env_aliases

install_legacy_env_aliases()


class _NoTracebackFilter(logging.Filter):
    """把 exception 日志压成一行摘要，避免后端/前端日志刷出 Traceback。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc_type, exc, _tb = record.exc_info
            message = record.getMessage()
            if exc_type is not None and exc is not None:
                summary = f"{exc_type.__name__}: {exc}"
                if summary not in message:
                    message = f"{message}: {summary}"
            record.msg = message
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def install_no_traceback_filter(handler: logging.Handler) -> logging.Handler:
    """给日志 handler 安装 Traceback 过滤器。"""

    if not any(isinstance(item, _NoTracebackFilter) for item in handler.filters):
        handler.addFilter(_NoTracebackFilter())
    return handler


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%H:%M:%S]",
    handlers=[install_no_traceback_filter(RichHandler(rich_tracebacks=False, show_path=False, markup=True))],
)

for _handler in logging.getLogger().handlers:
    install_no_traceback_filter(_handler)
