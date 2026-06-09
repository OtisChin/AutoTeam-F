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
_local = threading.local()


def _active_event() -> threading.Event:
    event = getattr(_local, "event", None)
    return event if hasattr(event, "is_set") and hasattr(event, "set") else _event


def set_current_event(event: threading.Event) -> None:
    """Bind a task-scoped cancel event to the current worker thread."""
    _local.event = event


def clear_current_event() -> None:
    if hasattr(_local, "event"):
        delattr(_local, "event")


def reset() -> None:
    """任务开始前清零,避免上一次的 cancel 标记泄漏到下一次。"""
    _active_event().clear()


def request_cancel(reason: str = "") -> None:
    """外部调用,请求当前任务在下一个安全点退出。"""
    logger.warning("[Cancel] 收到取消请求%s", f": {reason}" if reason else "")
    _active_event().set()


def request_cancel_event(event: threading.Event, reason: str = "") -> None:
    logger.warning("[Cancel] 收到取消请求%s", f": {reason}" if reason else "")
    event.set()


def is_cancelled() -> bool:
    return _active_event().is_set()
