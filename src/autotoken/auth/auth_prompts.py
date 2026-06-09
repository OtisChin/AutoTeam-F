import logging
import time

logger = logging.getLogger(__name__)

_PASSKEY_URL_HINTS = (
    "create-account-enroll-passkey",
    "enroll-passkey",
)

_PASSKEY_TEXT_HINTS = (
    "passkey",
    "security key",
    "通行密钥",
    "安全密钥",
    "改用密码",
)

_PASSKEY_PAGE_TEXT_HINTS = (
    "create account",
    "add passkey",
    "use passkey",
    "创建账户",
    "创建帐户",
    "添加通行密钥",
    "使用通行密钥",
)

_PASSKEY_SKIP_TEXT_HINTS = (
    "skip",
    "not now",
    "以后再说",
    "稍后",
    "跳过",
)

_PASSKEY_SKIP_SELECTORS = [
    'button:has-text("Skip")',
    'a:has-text("Skip")',
    'button:has-text("跳过")',
    'a:has-text("跳过")',
    'button:has-text("Not now")',
    'a:has-text("Not now")',
    'button:has-text("以后再说")',
    'a:has-text("以后再说")',
    'button:has-text("稍后")',
    'a:has-text("稍后")',
    'button:has-text("Use password instead")',
    'button:has-text("改用密码")',
    '[role="button"]:has-text("Skip")',
    '[role="button"]:has-text("跳过")',
]


def page_has_passkey_prompt(page) -> bool:
    try:
        url = (page.url or "").lower()
        if any(hint in url for hint in _PASSKEY_URL_HINTS):
            return True
        body = page.inner_text("body")[:2500].lower()
        has_passkey_text = any(hint in body for hint in _PASSKEY_TEXT_HINTS)
        has_page_text = any(hint in body for hint in _PASSKEY_PAGE_TEXT_HINTS)
        has_skip_text = any(hint in body for hint in _PASSKEY_SKIP_TEXT_HINTS)
        return has_passkey_text and (has_page_text or has_skip_text)
    except Exception as exc:
        logger.debug("[Auth] 检测通行密钥页失败: %s", exc)
        return False


def dismiss_passkey_prompt(page, *, timeout=3000) -> bool:
    """在通行密钥创建页点击“跳过”。"""
    if not page_has_passkey_prompt(page):
        return False

    logger.info("[Auth] 检测到通行密钥创建页，尝试点击跳过")
    for selector in _PASSKEY_SKIP_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=timeout):
                locator.click()
                time.sleep(1)
                return True
        except Exception:
            continue

    try:
        skip_text = page.get_by_text("跳过", exact=True).first
        if skip_text.is_visible(timeout=timeout):
            skip_text.click()
            time.sleep(1)
            return True
    except Exception:
        pass

    logger.warning("[Auth] 检测到通行密钥页，但未找到跳过按钮 | URL=%s", getattr(page, "url", ""))
    return False
