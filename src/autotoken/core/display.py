"""自动设置虚拟显示器（无头服务器）— 在 import 时执行，Windows/macOS 跳过"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


def _start_xvfb_process_fallback() -> None:
    subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x800x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    os.environ["DISPLAY"] = ":99"


def _ensure_virtual_display() -> None:
    # Windows 和 macOS 不需要虚拟显示器（有真实显示器或 Playwright 自带 headless）
    if sys.platform != "linux" or os.environ.get("DISPLAY"):
        return
    try:
        from xvfbwrapper import Xvfb

        _vdisplay = Xvfb(width=1280, height=800)
        _vdisplay.start()
    except (ImportError, OSError):
        try:
            _start_xvfb_process_fallback()
        except Exception:
            pass


_ensure_virtual_display()
