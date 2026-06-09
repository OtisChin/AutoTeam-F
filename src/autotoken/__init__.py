"""AutoTeam - ChatGPT Team 账号自动轮转管理工具"""

__version__ = "0.1.0"

import logging

from rich.logging import RichHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%H:%M:%S]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False, markup=True)],
)
