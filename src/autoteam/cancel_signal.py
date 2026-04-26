"""协作式任务取消信号。

Playwright 流在独立线程里跑,无法安全中断浏览器操作本身;但可以在"批次之间/账号之间"
这种安全边界检查一个共享 `threading.Event`,请求取消后就不再开始下一轮工作。

api.py 在 _run_task 开始前 reset(),结束后读一下 is_cancelled() 决定任务终态;
/api/tasks/cancel 接口调 request_cancel();
manager.py 的长流程(_cmd_fill_personal / cmd_rotate / cmd_fill ...)在循环体开头调 is_cancelled()。
"""

import logging
import threading

logger = logging.getLogger(__name__)

_event = threading.Event()


def reset() -> None:
    """任务开始前清零,避免上一次的 cancel 标记泄漏到下一次。"""
    _event.clear()


def request_cancel(reason: str = "") -> None:
    """外部调用,请求当前任务在下一个安全点退出。"""
    logger.warning("[Cancel] 收到取消请求%s", f": {reason}" if reason else "")
    _event.set()


def is_cancelled() -> bool:
    return _event.is_set()
