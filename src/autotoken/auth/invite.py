#!/usr/bin/env python3
import autotoken.core.display  # noqa: F401 — 自动设置虚拟显示器

"""
ChatGPT Team 自动邀请 + 注册工具（已禁用）

旧流程（临时邮箱 → Team 邀请 → 邀请链接注册 → 加入 workspace）已移除。
本模块仅保留 phone/duplicate 页面识别等直接注册流程仍复用的辅助函数。

用法:
    python invite.py
"""

import logging
import os
import sys
import time

from autotoken.storage.accounts import (
    SEAT_CHATGPT,
    SEAT_CODEX,
    SEAT_UNKNOWN,
)


def _seat_label_from_raw(raw_seat: str) -> str:
    """把 invite_member 返回的 _seat_type 字面量翻译成 accounts.SEAT_* 常量。"""
    return {
        "chatgpt": SEAT_CHATGPT,
        "usage_based": SEAT_CODEX,
    }.get(raw_seat or "", SEAT_UNKNOWN)


logger = logging.getLogger(__name__)

MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "180"))
SCREENSHOT_DIR = "screenshots"
TEAM_INVITE_REGISTER_DISABLED_MESSAGE = (
    "Team invite 注册链路已禁用；不再通过 Team 邀请链接创建账号。"
)


class RegisterBlocked(Exception):
    """
    注册流程被风控或确定性错误阻断时抛出；调用方按 reason 做分流处理：
    - is_phone=True: OpenAI 要求手机验证，当前账号放弃（用户明确不绕过）
    - is_duplicate=True: 邮箱已被占用，当前账号放弃，换邮箱重来
    - 其他: 单步逻辑错误，按现有 retry 流程处理
    """

    def __init__(self, step, reason, *, is_phone=False, is_duplicate=False, is_account_deactivated=False):
        super().__init__(f"[{step}] {reason}")
        self.step = step
        self.reason = reason
        self.is_phone = is_phone
        self.is_duplicate = is_duplicate
        self.is_account_deactivated = is_account_deactivated


# 手机验证页面的识别特征（URL 片段 + 页面文本）
# URL 是强信号；文本只匹配"动作 + phone"短语，不匹配裸 "phone number" / "sms"，避免
# 注册帮助区里偶尔出现的短语触发误报。
_PHONE_URL_HINTS = ("verify-phone", "add-phone", "/phone", "phone_verification", "phone-number")
_PHONE_TEXT_HINTS = (
    "verify your phone",
    "add your phone",
    "verify phone",
    "verification code to your phone",
    "add a phone number",
    "add a phone",
    "enter your phone",
    "phone verification",
    "we'll text you",
    "请输入手机号",
    "手机号码",
    "验证手机",
    "添加手机",
)

# 邮箱重复的识别特征（文案；各语言/版本都要覆盖）
_DUPLICATE_TEXT_HINTS = (
    "already have an account",
    "already exists",
    "already been used",
    "this user already exists",
    "please use a different email",
    "different email",
    "email is already taken",
    "account with this email",
    "该邮箱已被使用",
    "邮箱已存在",
    "请使用其他邮箱",
    "电子邮件已被使用",
)

# 账号已删除/停用页。验证码提交后 OpenAI 可能停留在 email-verification，
# 仅靠 URL 会被误判成仍在等待验证码，所以需要单独识别页面正文。
_ACCOUNT_DEACTIVATED_TEXT_HINTS = (
    "account_deactivated",
    "account deactivated",
    "account is deactivated",
    "deleted or deactivated",
    "deleted or disabled",
    "账户已被删除或停用",
    "账号已被删除或停用",
    "已被删除或停用",
    "账户已停用",
    "账号已停用",
)


def detect_phone_verification(page):
    """若当前页面要求手机验证返回 True。URL 命中优先；文本命中需配合电话输入框。"""
    try:
        url = (page.url or "").lower()
        if any(hint in url for hint in _PHONE_URL_HINTS):
            return True
        body = page.inner_text("body")[:1500].lower()
        if not any(hint in body for hint in _PHONE_TEXT_HINTS):
            return False
        # 仅当页面上真的有电话输入控件时才判为阻塞；否则可能是说明文字/footer
        try:
            tel_input = page.locator('input[type="tel"], input[name*="phone" i], input[autocomplete*="tel" i]').first
            if tel_input.is_visible(timeout=500):
                return True
        except Exception as exc:
            logger.debug("[注册] detect_phone tel_input 探测异常: %s", exc)
        return False
    except Exception as exc:
        logger.debug("[注册] detect_phone_verification 异常（当作未阻塞处理）: %s", exc)
        return False


def detect_duplicate_email(page):
    """若当前页面提示邮箱已被占用返回 True。"""
    try:
        body = page.inner_text("body")[:1500].lower()
        return any(hint in body for hint in _DUPLICATE_TEXT_HINTS)
    except Exception as exc:
        logger.debug("[注册] detect_duplicate_email 异常（当作无 duplicate 处理）: %s", exc)
        return False


def detect_account_deactivated(page):
    """若当前页面提示账号已删除/停用返回 True。"""
    try:
        url = (page.url or "").lower()
        if "account_deactivated" in url:
            return True
        body = page.inner_text("body")[:1500].lower()
        return any(hint in body for hint in _ACCOUNT_DEACTIVATED_TEXT_HINTS)
    except Exception as exc:
        logger.debug("[注册] detect_account_deactivated 异常（当作无 deactivated 处理）: %s", exc)
        return False


def assert_not_blocked(page, step):
    """任何步骤后调用，检测到阻断项立刻 raise。"""
    if detect_account_deactivated(page):
        logger.error("[注册] [%s] OpenAI 返回 account_deactivated，放弃当前账号 | URL=%s", step, page.url)
        raise RegisterBlocked(step, "account_deactivated", is_account_deactivated=True)
    if detect_phone_verification(page):
        logger.error("[注册] [%s] 触发 add-phone 手机验证，放弃当前账号 | URL=%s", step, page.url)
        raise RegisterBlocked(step, "add-phone 手机验证", is_phone=True)
    if detect_duplicate_email(page):
        logger.error("[注册] [%s] 邮箱已被占用，放弃当前账号 | URL=%s", step, page.url)
        raise RegisterBlocked(step, "duplicate email", is_duplicate=True)


def screenshot(page, name):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = f"{SCREENSHOT_DIR}/{name}"
    page.screenshot(path=path, full_page=True)
    logger.debug("[截图] %s", path)


def find_and_click(page, selectors, label="元素", timeout=3000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=timeout):
                logger.debug("[注册] 找到%s: %s", label, sel)
                loc.click()
                return True
        except Exception:
            continue
    return False


def find_visible(page, selectors, label="元素", timeout=3000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=timeout):
                logger.debug("[注册] 找到%s: %s", label, sel)
                return loc
        except Exception:
            continue
    return None


def wait_for_cloudflare(page, max_wait=60):
    for i in range(max_wait // 5):
        html = page.content()[:2000].lower()
        if "verify you are human" not in html and "challenge" not in page.url:
            return True
        logger.info("[注册] 等待 Cloudflare... (%ds)", i * 5)
        time.sleep(5)
    return False


def register_with_invite(page, invite_link, email, mail_client, password=None):
    """旧 Team 邀请链接注册入口，已禁用。"""
    raise RuntimeError(TEAM_INVITE_REGISTER_DISABLED_MESSAGE)


def run():
    """旧 Team 邀请注册命令入口，已禁用。"""
    raise RuntimeError(TEAM_INVITE_REGISTER_DISABLED_MESSAGE)


def main():
    logger.info("ChatGPT Team 自动邀请 + 注册工具")
    result = run()
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
