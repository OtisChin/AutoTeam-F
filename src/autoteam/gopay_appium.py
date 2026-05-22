"""GoPay Appium 自动化注册模块。

通过 Appium 驱动真实 GoPay APP 完成注册流程，绕过 cvs/v1/initiate 的服务端封锁。
APP 内部携带真实的 F4 反欺诈 token + Play Integrity attestation，不受 HTTP API rate limit 影响。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

GOPAY_PACKAGE = "com.gojek.gopay"
GOPAY_ACTIVITY = "com.gojek.gopay.MainActivity"
DEFAULT_APPIUM_URL = "http://127.0.0.1:4723"
DEFAULT_IMPLICIT_WAIT = 10
DEFAULT_NEW_COMMAND_TIMEOUT = 300

# UI 等待超时（秒）
SCREEN_TRANSITION_WAIT = 3.0
OTP_SCREEN_WAIT = 180.0  # hero-sms OTP delivery can take >60s
POST_ACTION_DELAY = 1.5


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class GopayAppiumError(RuntimeError):
    """Appium 自动化过程中的错误。"""


class GopayAppiumDriver:
    """通过 Appium 自动化 GoPay APP 完成注册。

    要求：
    - Android 模拟器/真机已启动，GoPay APP 已安装
    - Appium server 已运行在 appium_url
    - 设备已通过 adb 可见
    """

    def __init__(
        self,
        *,
        appium_url: str = DEFAULT_APPIUM_URL,
        adb_serial: str = "",
        apk_path: str = "",
        proxy_host: str = "",
        proxy_port: int = 0,
        implicit_wait: int = DEFAULT_IMPLICIT_WAIT,
        ldconsole_path: str = "",
        emulator_index: int = -1,
        log: Callable[[str], None] = logger.info,
    ):
        self.appium_url = appium_url or DEFAULT_APPIUM_URL
        self.adb_serial = adb_serial or _env_str("GOPAY_APPIUM_ADB_SERIAL") or _env_str("ANDROID_ADB_SERIAL")
        self.apk_path = apk_path or _env_str("GOPAY_APK_PATH")
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.implicit_wait = implicit_wait
        self.log = log
        self._driver: Any = None
        self._adb_path = _env_str("ADB_PATH") or _env_str("ANDROID_ADB_PATH") or "adb"
        # LDPlayer/雷电模拟器 配置
        self._ldconsole_path = (
            ldconsole_path
            or _env_str("LDCONSOLE_PATH")
            or self._find_ldconsole()
        )
        self._emulator_index = (
            emulator_index if emulator_index >= 0
            else int(_env_str("GOPAY_APPIUM_EMULATOR_INDEX", "-1"))
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def start_session(self, *, fresh: bool = True) -> None:
        """启动 Appium session，打开 GoPay APP。

        Args:
            fresh: 如果 True，先清除 APP 数据再启动（模拟全新安装）。
                   必须在创建 Appium session 之前执行，否则会导致 UiAutomator2 崩溃。
        """
        try:
            from appium import webdriver as appium_webdriver
            from appium.options.android import UiAutomator2Options
        except ImportError as e:
            raise GopayAppiumError(
                "缺少 Appium 依赖，请安装: pip install Appium-Python-Client"
            ) from e

        if fresh:
            self._adb_shell(f"am force-stop {GOPAY_PACKAGE}")
            time.sleep(1)
            self._adb_shell(f"pm clear {GOPAY_PACKAGE}")
            time.sleep(2)

        # 先手动启动 GoPay（不带 -W），Flutter 首次 pm clear 后启动非常慢
        # Appium 的 -W (wait) 模式会超时
        self.log("[gopay-appium] 预启动 GoPay APP...")
        self._adb_shell(f"am start -n {GOPAY_PACKAGE}/{GOPAY_ACTIVITY}")
        time.sleep(15)  # 等 Flutter 引擎初始化

        # Dismiss GMS popup if it appeared during launch (can happen multiple times)
        for _ in range(3):
            if not self._dismiss_gms_popup():
                break
            self._adb_shell(f"am start -n {GOPAY_PACKAGE}/{GOPAY_ACTIVITY}")
            time.sleep(3)

        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.app_package = GOPAY_PACKAGE
        options.app_activity = GOPAY_ACTIVITY
        options.no_reset = True
        options.new_command_timeout = DEFAULT_NEW_COMMAND_TIMEOUT
        options.auto_grant_permissions = True

        if self.adb_serial:
            options.udid = self.adb_serial

        if self.apk_path and os.path.isfile(self.apk_path):
            options.app = self.apk_path

        # 不重启已运行的 APP，直接连接
        options.set_capability("appium:adbExecTimeout", 120000)
        options.set_capability("appium:appWaitDuration", 120000)
        options.set_capability("appium:dontStopAppOnReset", True)
        options.set_capability("appium:appWaitForLaunch", False)

        self.log(f"[gopay-appium] 启动 Appium session: url={self.appium_url} serial={self.adb_serial or 'auto'}")

        try:
            self._driver = appium_webdriver.Remote(
                command_executor=self.appium_url,
                options=options,
            )
            self._driver.implicitly_wait(self.implicit_wait)
        except Exception as exc:
            raise GopayAppiumError(f"Appium 连接失败: {exc}") from exc

        self.log("[gopay-appium] Session 已建立，等待 APP 启动...")
        time.sleep(8)  # Flutter on Nox/模拟器启动较慢

    def close(self) -> None:
        """关闭 Appium session。"""
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    # ------------------------------------------------------------------
    # High-level signup flow
    # ------------------------------------------------------------------

    def signup(
        self,
        *,
        phone: str,
        country_code: str,
        name: str,
        pin: str,
        otp_provider: Callable[[str], str],
        pre_pin_otp_hook: Callable[[], None] | None = None,
    ) -> dict[str, str]:
        """执行完整注册流程。

        Returns:
            {"access_token": ..., "refresh_token": ..., "account_id": ...}
            如果无法从设备提取 token，返回空字符串值（调用方可通过 login 补充）。
        """
        if not self._driver:
            raise GopayAppiumError("Appium session 未启动")

        self.log(f"[gopay-appium] 开始注册: phone={country_code}{phone[:3]}***")

        # Step 1: 导航到注册页面
        self._navigate_to_signup()

        # Step 2: 输入手机号（含条款确认），返回当前页面文本
        all_text = self._enter_phone_number(phone, country_code)

        # Step 3: 检查技术错误 — 重试（transient server error）
        for gangguan_retry in range(3):
            if not self._is_technical_error(all_text):
                break
            wait_sec = 15 * (gangguan_retry + 1)
            self.log(f"[gopay-appium] 技术错误 (retry {gangguan_retry + 1}/3)，等待 {wait_sec}s 后重启...")
            try:
                self._click_button_by_desc("Oke", timeout=3)
            except Exception:
                pass
            time.sleep(2)
            self.close()
            time.sleep(wait_sec)
            self.start_session(fresh=True)
            self._navigate_to_signup()
            all_text = self._enter_phone_number(phone, country_code)

        # Step 4: 检查设备频率限制 — 自动重置设备并重试
        if self._check_device_rate_limit(all_text):
            self.log("[gopay-appium] 设备频率限制，重置设备标识...")
            self.close()
            self._reset_device_identity()
            self.start_session(fresh=True)
            self._navigate_to_signup()
            all_text = self._enter_phone_number(phone, country_code)

            # Handle technical errors after device reset
            for retry_i in range(3):
                if self._is_technical_error(all_text):
                    self.log(f"[gopay-appium] 重置后技术错误 (retry {retry_i + 1}/3)")
                    try:
                        self._click_button_by_desc("Oke", timeout=3)
                    except Exception:
                        pass
                    time.sleep(10)
                    self.close()
                    self.start_session(fresh=True)
                    self._navigate_to_signup()
                    all_text = self._enter_phone_number(phone, country_code)
                else:
                    break

            if self._check_device_rate_limit(all_text):
                raise GopayAppiumError("设备频率限制: 重置设备后仍被拦截")
            if self._is_technical_error(all_text):
                raise GopayAppiumError("技术错误: 重试后仍失败")

        # Step 5: 等待 OTP 输入页面出现（含 WhatsApp → SMS 切换）
        sms_switch_retry_used = False
        while True:
            try:
                self._wait_for_otp_screen()
                break
            except GopayAppiumError as exc:
                if sms_switch_retry_used or "SMS OTP 切换后仍为技术错误" not in str(exc):
                    raise
                sms_switch_retry_used = True
                self.log("[gopay-appium] SMS 切换后仍技术错误，重启 GoPay 并用同号码重试一次...")
                self.close()
                time.sleep(5)
                self.start_session(fresh=True)
                self._navigate_to_signup()
                all_text = self._enter_phone_number(phone, country_code)
                if self._is_technical_error(all_text):
                    raise
                if self._check_device_rate_limit(all_text):
                    raise GopayAppiumError("重启后触发设备频率限制")

        # Step 6: 获取并输入 OTP
        self.log("[gopay-appium] 等待 OTP...")
        otp = otp_provider("gopay_signup")
        if not otp:
            raise GopayAppiumError("OTP 未收到")
        self._enter_otp(otp)

        # Step 7: Post-OTP flow: Name → PIN → Home (with proper ordering)
        self._post_otp_flow(name, pin)

        # Step 8: 从主页进入 PIN 设置（如果注册时未设置 PIN）
        all_text = self._dump_descs("Check PIN status")
        pin_not_set = ("amankan saldomu" in all_text or "maksimalkan perlindunganmu" in all_text
                       or "pasang pin" in all_text or "secure your balance" in all_text
                       or "set up pin" in all_text or "maximize your protection" in all_text)
        if self._is_home_screen(all_text) and pin_not_set:
            self.log("[gopay-appium] 检测到 PIN 未设置，从主页进入 PIN 设置")
            self._setup_pin_from_home(pin, otp_provider, pre_pin_otp_hook)

        # Step 9: 尝试从设备存储提取 token
        tokens = self._extract_tokens()
        self.log(f"[gopay-appium] 注册完成，token提取: {'成功' if tokens.get('access_token') else '需要login补充'}")

        return tokens

    def _post_otp_flow(self, name: str, pin: str) -> None:
        """Handle the post-OTP flow: Name input → PIN setup → Home screen.

        Checks home screen BEFORE PIN to avoid false positive on "Amankan saldomu!"
        which contains "PIN" in the text.
        """
        for attempt in range(8):
            all_text = self._dump_descs(f"Post-OTP attempt {attempt + 1}")

            # Home/success check FIRST (prevents false PIN detection)
            if self._is_home_screen(all_text):
                self.log("[gopay-appium] 已到达主页！注册成功")
                return
            if any(ind in all_text for ind in ["selamat", "berhasil", "success", "welcome", "congratulations"]):
                self.log("[gopay-appium] 成功页面！")
                try:
                    self._click_next_button(timeout=3)
                except Exception:
                    pass
                time.sleep(SCREEN_TRANSITION_WAIT)
                continue

            # Name input
            if any(ind in all_text for ind in ["nama", "name", "isi data diri", "personal data", "your name"]):
                self._enter_name_if_needed(name)
                time.sleep(SCREEN_TRANSITION_WAIT)
                continue

            # PIN setup (only after confirming it's not the home screen)
            pin_indicators = ["buat pin", "create pin", "masukkan pin", "enter pin", "atur pin", "set up pin", "setup pin"]
            if any(ind in all_text for ind in pin_indicators):
                self._setup_pin(pin)
                time.sleep(SCREEN_TRANSITION_WAIT)
                continue

            time.sleep(3)

        # Final check
        all_text = self._dump_descs("Final state")
        if not self._is_home_screen(all_text):
            self.log("[gopay-appium] 警告：未确认到达主页")
            self._save_screenshot("post_otp_final")

    # ------------------------------------------------------------------
    # UI Navigation helpers
    # ------------------------------------------------------------------

    def _navigate_to_signup(self) -> None:
        """从启动画面导航到手机号输入页面。

        GoPay 使用统一入口（登录/注册合一），新号码自动走注册流程。
        首次启动可能显示位置权限页面，需要先跳过。
        """
        self.log("[gopay-appium] 导航到手机号输入页面")
        d = self._driver

        time.sleep(SCREEN_TRANSITION_WAIT)

        # 处理位置权限页面 — 点击 "Nanti aja" (稍后) 或 "Later" 跳过
        try:
            for skip_text in ["Nanti aja", "Later", "Not now", "Skip"]:
                later_els = d.find_elements("xpath", f"//*[contains(@content-desc, '{skip_text}')]")
                if later_els:
                    later_els[0].click()
                    self.log(f"[gopay-appium] 跳过位置权限页面: '{skip_text}'")
                    time.sleep(SCREEN_TRANSITION_WAIT)
                    break
        except Exception:
            pass

        # 处理 Android 系统权限弹窗
        self._dismiss_system_dialogs()

        # 查找入口：统一登录/注册按钮
        # 首页按钮: "Masukkan nomor HP-mu" (输入你的手机号)
        entry_descs = [
            "Masukkan nomor HP",
            "Enter your phone",
            "Masuk atau daftar",
            "Login or register",
            "Daftar", "Register", "Sign Up", "Sign up",
            "Masuk", "Login", "Log in",
        ]
        entry_found = False
        for desc_text in entry_descs:
            try:
                elements = d.find_elements("xpath", f"//*[contains(@content-desc, '{desc_text}')]")
                if elements:
                    for el in elements:
                        if el.get_attribute("clickable") == "true":
                            el.click()
                            entry_found = True
                            self.log(f"[gopay-appium] 点击入口按钮: '{desc_text}'")
                            break
                    if entry_found:
                        break
            except Exception:
                continue

        if not entry_found:
            # 可能已经在手机号输入页面了（有 "Nomor HP" 或 "Phone Number" 输入框）
            phone_input = d.find_elements("xpath", "//*[contains(@content-desc, 'Nomor HP') or contains(@content-desc, 'Phone')]")
            if phone_input:
                self.log("[gopay-appium] 已在手机号输入页面")
                return
            self._save_screenshot("navigate_signup_failed")
            raise GopayAppiumError("无法找到入口按钮")

        time.sleep(SCREEN_TRANSITION_WAIT)

        # 等待手机号输入页面加载（"Selamat datang di GoPay!" 或输入框出现）
        deadline = time.time() + 10.0
        while time.time() < deadline:
            els = d.find_elements("xpath", "//*[contains(@content-desc, 'Nomor HP') or contains(@content-desc, 'Phone')]")
            if els:
                self.log("[gopay-appium] 手机号输入页面已加载")
                return
            time.sleep(1.0)

        self._save_screenshot("phone_page_timeout")
        raise GopayAppiumError("手机号输入页面加载超时")

    def _dismiss_system_dialogs(self) -> None:
        """关闭 Android 系统弹窗（权限请求等）。"""
        d = self._driver
        try:
            # 中文/英文/印尼语 允许 按钮
            for text in ["允许", "Allow", "ALLOW", "Izinkan", "IZINKAN"]:
                els = d.find_elements("xpath", f"//*[contains(@text, '{text}')]")
                if els:
                    els[0].click()
                    self.log(f"[gopay-appium] 关闭系统弹窗: '{text}'")
                    time.sleep(1.0)
        except Exception:
            pass

    def _enter_phone_number(self, phone: str, country_code: str) -> str:
        """在注册页面输入手机号。

        Flutter 的输入框是 android.view.View 包裹的 android.widget.EditText。
        必须先 click EditText 弹出键盘，再用 ADB keyevent 逐字输入（触发 Flutter IME 事件）。
        直接 send_keys 到 View 或 EditText 都无法触发 Flutter 的 onChanged。

        Returns all_text (lowercased content-desc) of the page after submission.
        """
        self.log("[gopay-appium] 输入手机号")
        d = self._driver
        time.sleep(POST_ACTION_DELAY)

        # 去掉国家码前缀
        phone_digits = phone.lstrip("0")
        if phone_digits.startswith("62"):
            phone_digits = phone_digits[2:]

        # 查找真正的 EditText（在 "Nomor HP" View 内部）
        edit_texts = d.find_elements("class name", "android.widget.EditText")
        if not edit_texts:
            self._save_screenshot("phone_edittext_not_found")
            raise GopayAppiumError("无法找到手机号 EditText 输入框")

        # 点击 EditText 弹出键盘
        edit_texts[0].click()
        time.sleep(0.8)

        # 通过 ADB keyevent 逐字输入（KEYCODE_0=7 ... KEYCODE_9=16）
        for digit in phone_digits:
            if digit.isdigit():
                self._adb_shell(f"input keyevent {7 + int(digit)}")
                time.sleep(0.1)

        self.log(f"[gopay-appium] 已输入手机号: {phone_digits[:3]}***")
        time.sleep(POST_ACTION_DELAY)

        # 隐藏键盘
        try:
            d.hide_keyboard()
        except Exception:
            self._adb_shell("input keyevent 111")  # ESCAPE
        time.sleep(0.5)

        # 点击 "Lanjut" (继续) 按钮
        self._click_button_by_desc("Lanjut")
        time.sleep(SCREEN_TRANSITION_WAIT + 2)  # extra wait for server response

        # Lanjut 之后可能出现注册条款确认页面（"Signup Terms Summary"）
        return self._accept_terms_if_present()

    def _accept_terms_if_present(self) -> str:
        """如果出现注册条款确认页面，点击同意继续。

        Returns all_text (lowercased content-desc) of the page after terms handling.
        """
        d = self._driver
        time.sleep(POST_ACTION_DELAY)

        all_text = self._dump_descs("After Lanjut")

        if "terms" not in all_text and "penting" not in all_text and "important" not in all_text:
            return all_text

        self.log("[gopay-appium] 检测到注册条款页面，点击同意")
        try:
            self._click_button_by_desc("Lanjut", timeout=3)
        except Exception:
            pass

        # Wait for post-terms page, aggressively dismissing GMS popup
        self.log("[gopay-appium] 等待条款提交后页面加载...")
        for i in range(15):
            time.sleep(2)
            gms_dismissed = self._dismiss_gms_popup()
            if gms_dismissed:
                self._adb_shell(f"am start -n {GOPAY_PACKAGE}/{GOPAY_ACTIVITY}")
                time.sleep(3)
            try:
                descs = d.find_elements("xpath", "//*[@content-desc!='']")
                if descs:
                    first = (descs[0].get_attribute("content-desc") or "").lower()
                    if "terms" not in first and "penting" not in first:
                        break
            except Exception:
                pass

        all_text = self._dump_descs("After terms")

        # If page is empty, wait up to 30s for content
        if not all_text.strip():
            self.log("[gopay-appium] 页面空白，等待内容加载...")
            for _ in range(6):
                time.sleep(5)
                self._dismiss_gms_popup()
                all_text = self._dump_descs("Waiting...")
                if all_text.strip():
                    break

        return all_text

    def _wait_for_otp_screen(self) -> None:
        """等待 OTP 输入页面出现，然后始终尝试切换到 SMS OTP。

        GoPay 默认发送 WhatsApp OTP，hero-sms 只能接收 SMS，必须切换。
        GoPay may show the method selection page directly (not WhatsApp OTP first).
        """
        self.log("[gopay-appium] 等待 OTP 输入页面...")
        d = self._driver

        deadline = time.time() + OTP_SCREEN_WAIT
        while time.time() < deadline:
            try:
                descs = d.find_elements("xpath", "//*[@content-desc!='']")
                all_text = ""
                for el in descs:
                    try:
                        all_text += " " + (el.get_attribute("content-desc") or "").lower()
                    except Exception:
                        pass
            except Exception:
                time.sleep(1.0)
                continue

            # False positive: "tidak memerlukan OTP" = PIN page (already registered)
            if "tidak memerlukan otp" in all_text or "masukkin pin" in all_text or "ketik gopay pin" in all_text:
                raise GopayAppiumError("手机号已注册（PIN 页面），不是 OTP 页面")
            if self._is_cannot_continue_error(all_text):
                self._save_screenshot("cannot_continue")
                raise GopayAppiumError("GoPay 拒绝继续注册：请联系 Customer Service")

            otp_indicators = ["otp", "verifikasi", "verification", "kode", "code",
                              "masukkan kode", "enter code", "pilih metode", "choose method",
                              "select method"]
            if any(indicator in all_text for indicator in otp_indicators):
                self.log("[gopay-appium] OTP 输入页面已出现")
                self._switch_to_sms_otp(all_text)
                return

            # Handle errors during OTP wait
            if self._is_technical_error(all_text):
                self.log("[gopay-appium] OTP 等待中检测到技术错误，尝试关闭...")
                try:
                    self._click_button_by_desc("Oke", timeout=3)
                except Exception:
                    pass
                time.sleep(3)
                continue
            if self._is_rate_limited(all_text):
                raise GopayAppiumError("OTP 等待中检测到频率限制")

            remaining = int(deadline - time.time())
            self.log(f"[gopay-appium] 等待 OTP 页面... ({remaining}s)")
            time.sleep(3.0)

        self._check_for_error()
        self._save_screenshot("otp_screen_timeout")
        raise GopayAppiumError("等待 OTP 页面超时")

    def _switch_to_sms_otp(self, current_page_text: str = "") -> None:
        """从 WhatsApp OTP 切换到 SMS OTP。

        GoPay may show:
        1. WhatsApp OTP page with "Coba Metode Lainnya" button → click to get method selection
        2. Method selection page directly with "OTP via SMS" option
        """
        d = self._driver
        self.log("[gopay-appium] 切换到 SMS OTP...")

        all_text = current_page_text or self._dump_descs()

        # Check if already on method selection page (has "pilih metode" or "otp via sms")
        if "pilih metode" in all_text or "choose method" in all_text or "select method" in all_text or "otp via sms" in all_text:
            self.log("[gopay-appium] 已在方法选择页面")
            switch_clicked = True
        else:
            # Need to click "Coba Metode Lainnya" first
            switch_clicked = False
            for kw in ["Coba Metode Lainnya", "Coba metode lainnya", "Try Other Method"]:
                try:
                    self._click_button_by_desc(kw, timeout=3)
                    self.log(f"[gopay-appium] 点击: '{kw}'")
                    switch_clicked = True
                    break
                except Exception:
                    continue

            if not switch_clicked:
                self.log("[gopay-appium] 未找到切换按钮，继续使用当前方式")
                return

        time.sleep(SCREEN_TRANSITION_WAIT)

        # Select SMS option
        sms_keywords = ["OTP via SMS", "SMS", "sms", "Pesan singkat", "Text message"]
        for kw in sms_keywords:
            try:
                els = d.find_elements("xpath", f"//*[contains(@content-desc, '{kw}')]")
                for el in els:
                    try:
                        if el.get_attribute("clickable") == "true":
                            el.click()
                            self.log(f"[gopay-appium] 选择了 SMS 方式: '{kw}'")
                            time.sleep(SCREEN_TRANSITION_WAIT + 2)

                            # Handle technical errors after SMS switch
                            # If SMS switch still lands on technical error after retries, abort this attempt
                            final_sms_text = self._dump_descs("After SMS switch final")
                            if self._is_technical_error(final_sms_text):
                                raise GopayAppiumError("SMS OTP 切换后仍为技术错误")
                            return
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: click any non-WhatsApp clickable option
        self.log("[gopay-appium] SMS 选项未找到，尝试点击非 WhatsApp 选项")
        try:
            descs = d.find_elements("xpath", "//*[@content-desc!='']")
            for el in descs:
                try:
                    desc = (el.get_attribute("content-desc") or "").lower()
                    if (el.get_attribute("clickable") == "true" and desc
                            and "whatsapp" not in desc and "back" not in desc and "dismiss" not in desc):
                        el.click()
                        self.log(f"[gopay-appium] 点击了备选项: '{el.get_attribute('content-desc')}'")
                        time.sleep(SCREEN_TRANSITION_WAIT)
                        return
                except Exception:
                    continue
        except Exception:
            pass

    def _request_otp_resend_in_app(self) -> None:
        """Try to trigger OTP resend from the GoPay UI without leaving the OTP page."""
        for btn in ["Kirim Ulang", "Resend", "Kirim ulang", "Send again"]:
            try:
                self._click_button_by_desc(btn, timeout=2)
                self.log(f"[gopay-appium] 在 APP 内触发 OTP 重发: '{btn}'")
                time.sleep(3)
                return
            except Exception:
                continue

    def _enter_otp(self, otp: str) -> None:
        """在 OTP 页面输入验证码，使用 ADB keyevent 触发 Flutter IME。"""
        self.log(f"[gopay-appium] 输入 OTP: {otp}")
        d = self._driver
        time.sleep(POST_ACTION_DELAY)

        # Click EditText to focus + show keyboard
        edit_texts = d.find_elements("class name", "android.widget.EditText")
        if edit_texts:
            edit_texts[0].click()
            time.sleep(0.5)

        # 通过 ADB keyevent 输入 OTP 数字
        otp_digits = re.sub(r'\D', '', otp)[:6]
        for digit in otp_digits:
            self._adb_shell(f"input keyevent {7 + int(digit)}")
            time.sleep(0.1)

        time.sleep(SCREEN_TRANSITION_WAIT)

        # OTP 输入后可能自动提交，也可能需要点击确认
        try:
            self._click_next_button(timeout=3)
        except Exception:
            pass

        time.sleep(SCREEN_TRANSITION_WAIT)

    def _enter_name_if_needed(self, name: str) -> None:
        """如果出现名字输入页面，输入名字。

        名字输入页面特征: content-desc 含 "Nama" 或 "name" 或 "isi data diri"
        提交按钮: "Buat akun" (创建账号) 或 "Lanjut"
        输入方式: 与手机号相同 — click EditText 弹出键盘，ADB keyevent 逐字输入。
        """
        d = self._driver
        time.sleep(POST_ACTION_DELAY)

        all_text = self._dump_descs("Check name page")
        name_indicators = ["nama", "name", "isi data diri", "personal data", "your name"]
        if not any(ind in all_text for ind in name_indicators):
            self.log("[gopay-appium] 未检测到名字输入页面，跳过")
            return

        self.log(f"[gopay-appium] 输入名字: {name}")

        # 查找 EditText 输入框
        edit_texts = d.find_elements("class name", "android.widget.EditText")
        if edit_texts:
            edit_texts[0].click()
            time.sleep(0.5)

            # 通过 ADB keyevent 输入字母 (a=29 ... z=54)
            for ch in name:
                if ch.isalpha():
                    keycode = 29 + (ord(ch.lower()) - ord('a'))
                    if ch.isupper():
                        self._adb_shell(f"input keyevent --shift {keycode}")
                    else:
                        self._adb_shell(f"input keyevent {keycode}")
                elif ch == ' ':
                    self._adb_shell("input keyevent 62")  # KEYCODE_SPACE
                elif ch.isdigit():
                    self._adb_shell(f"input keyevent {7 + int(ch)}")
                time.sleep(0.05)

            time.sleep(POST_ACTION_DELAY)

            # 隐藏键盘
            try:
                d.hide_keyboard()
            except Exception:
                self._adb_shell("input keyevent 111")
            time.sleep(0.5)
        else:
            self._adb_input_text(name)
            time.sleep(POST_ACTION_DELAY)

        # 点击提交按钮: "Buat akun" (创建账号) 或 "Lanjut" 或 "Next"
        for btn_text in ["Buat akun", "Create account", "Lanjut", "Next", "Continue", "Submit"]:
            try:
                self._click_button_by_desc(btn_text, timeout=3)
                break
            except Exception:
                continue
        time.sleep(SCREEN_TRANSITION_WAIT)

    def _setup_pin(self, pin: str) -> None:
        """设置 6 位 PIN（通常需要输入两次）。

        IMPORTANT: Must check for home screen BEFORE PIN detection, because
        the home page contains "PIN" in text like "Amankan saldomu!" which
        triggers false PIN entry.
        """
        self.log("[gopay-appium] 等待 PIN 页面...")
        d = self._driver
        time.sleep(SCREEN_TRANSITION_WAIT)

        # Wait for PIN page — but check home screen first
        deadline = time.time() + 15.0
        pin_page_found = False
        while time.time() < deadline:
            all_text = self._dump_descs()

            # Home screen check FIRST (prevents false PIN detection)
            if self._is_home_screen(all_text):
                self.log("[gopay-appium] 已到达主页，跳过 PIN 设置（可能已完成）")
                return

            pin_indicators = ["buat pin", "create pin", "masukkan pin", "enter pin", "security pin", "atur pin", "set up pin", "setup pin", "pasang pin"]
            if any(ind in all_text for ind in pin_indicators):
                pin_page_found = True
                break
            time.sleep(1.0)

        if not pin_page_found:
            self.log("[gopay-appium] 未检测到 PIN 页面，可能已跳过")
            return

        # 输入 PIN（第一次）
        self.log("[gopay-appium] 输入 PIN（第一次）")
        self._input_pin_digits(pin)
        time.sleep(1)

        # 点击 "Lanjut" / "Next" / "Continue" / "Save"
        for btn in ["Lanjut", "Next", "Continue", "Simpan", "Save", "Konfirmasi", "Confirm"]:
            try:
                self._click_button_by_desc(btn, timeout=2)
                break
            except Exception:
                continue
        time.sleep(SCREEN_TRANSITION_WAIT)

        # Check if we landed on home screen after first PIN
        all_text = self._dump_descs()
        if self._is_home_screen(all_text):
            self.log("[gopay-appium] 已到达主页，PIN 设置完成")
            return

        # 输入 PIN（第二次确认）
        confirm_indicators = ["konfirmasi", "confirm", "ulangi", "re-enter", "masukkan ulang", "pin"]
        if any(ind in all_text for ind in confirm_indicators):
            self.log("[gopay-appium] 确认 PIN（第二次输入）")
            time.sleep(POST_ACTION_DELAY)
            self._input_pin_digits(pin)
            time.sleep(1)
            for btn in ["Simpan", "Save", "Konfirmasi", "Confirm", "Lanjut", "Next", "Continue"]:
                try:
                    self._click_button_by_desc(btn, timeout=2)
                    break
                except Exception:
                    continue
            time.sleep(SCREEN_TRANSITION_WAIT)

    def _input_pin_digits(self, pin: str) -> None:
        """输入 6 位 PIN 数字。

        GoPay PIN 页面使用自定义数字键盘（不是系统 EditText），
        每个数字是独立的 android.view.View，通过 content-desc ('0'-'9') 定位并点击。
        如果找不到自定义键盘，回退到 ADB keyevent。
        """
        d = self._driver

        # 尝试使用自定义键盘（每个数字是 content-desc='0'-'9' 的 android.view.View）
        for digit in pin:
            if not digit.isdigit():
                continue
            tapped = False
            try:
                els = d.find_elements("xpath", f"//*[@content-desc='{digit}']")
                for el in els:
                    try:
                        if (el.get_attribute("clickable") == "true"
                                and el.get_attribute("className") == "android.view.View"):
                            el.click()
                            tapped = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            if not tapped:
                # Fallback: ADB keyevent
                self._adb_shell(f"input keyevent {7 + int(digit)}")
            time.sleep(0.2)

    def _open_pin_setup_from_home(self) -> bool:
        """Open the home security flow and enter the PIN setup page."""
        current = self._dump_descs("PIN reopen current state")
        if "pasang pin" in current and "pin gopay" in current:
            return True
        if "pasang pin" in current and "maksimalkan perlindunganmu" in current:
            try:
                self._click_button_by_desc("Pasang PIN", timeout=5)
                time.sleep(5)
                self._dump_descs("PIN setup page")
                return True
            except Exception:
                return False

        # 点击 "Amankan saldomu!" 或 "Maksimalkan perlindunganmu"
        entry_clicked = False
        for entry_text in ["Amankan saldomu", "Maksimalkan", "Secure your balance", "Maximize"]:
            try:
                self._click_button_by_desc(entry_text, timeout=3)
                entry_clicked = True
                self.log(f"[gopay-appium] 点击了: '{entry_text}'")
                break
            except Exception:
                continue
        if not entry_clicked:
            self.log("[gopay-appium] 未找到 PIN 设置入口，可能 PIN 已设置")
            return False
        time.sleep(5)

        # 点击 "Pasang PIN" / "Set up PIN"
        pin_entry_clicked = False
        for pin_text in ["Pasang PIN", "Set up PIN", "Setup PIN", "Create PIN"]:
            try:
                self._click_button_by_desc(pin_text, timeout=3)
                pin_entry_clicked = True
                break
            except Exception:
                continue
        if not pin_entry_clicked:
            self.log("[gopay-appium] 未找到 'Pasang PIN'，可能 PIN 已设置")
            return False
        time.sleep(5)

        all_text = self._dump_descs("PIN setup page")
        if "pasang pin" not in all_text and "set up pin" not in all_text and "create pin" not in all_text:
            self.log("[gopay-appium] 不在 PIN 设置页面")
            return False
        return True

    def _setup_pin_from_home(self, pin: str, otp_provider: Callable[[str], str], pre_pin_otp_hook: Callable[[], None] | None = None) -> None:
        """从主页导航到 PIN 设置并完成设置。

        GoPay 注册后有时不强制设 PIN，需要主动从主页进入:
        主页 → "Amankan saldomu!" → "Pasang PIN" → 输入PIN → 确认PIN → OTP验证 → 完成

        PIN 规则: 不能是重复数字(111111)或连续数字(123456)。

        Args:
            pin: 6 位 PIN（不能是重复/连续数字）
            otp_provider: OTP 获取回调（用于 PIN 设置的 OTP 验证，必须是同一个手机号的 activation）
        """
        d = self._driver
        self.log("[gopay-appium] 从主页进入 PIN 设置...")

        if not self._open_pin_setup_from_home():
            return

        pin_setup_retry = 0
        while pin_setup_retry < 2:
            # 输入 PIN（第一次）
            self.log(f"[gopay-appium] 输入 PIN（第一次）: {'*' * len(pin)}")
            self._input_pin_digits(pin)
            time.sleep(1)

            # 点击 "Lanjut" / "Next" / "Continue"
            for btn in ["Lanjut", "Next", "Continue", "Save", "Simpan"]:
                try:
                    self._click_button_by_desc(btn, timeout=2)
                    break
                except Exception:
                    continue
            time.sleep(5)

            all_text = self._dump_descs("After first PIN")
            if self._is_technical_error(all_text):
                self.log("[gopay-appium] PIN 设置遇到技术错误，关闭后重新进入 PIN 流程...")
                for btn in ["Oke", "OK", "Try again", "Coba lagi"]:
                    try:
                        self._click_button_by_desc(btn, timeout=2)
                        break
                    except Exception:
                        continue
                time.sleep(3)
                pin_setup_retry += 1
                if pin_setup_retry >= 2 or not self._open_pin_setup_from_home():
                    break
                continue

            # 检查是否显示 PIN 规则警告（重复/连续数字被拒绝）
            if ("hindari" in all_text or "avoid" in all_text) and ("berulang" in all_text or "berurut" in all_text or "repeating" in all_text or "sequential" in all_text):
                self.log("[gopay-appium] PIN 被拒绝（重复/连续数字）！")
                raise GopayAppiumError(f"PIN '{pin}' 被拒绝: 不能使用重复或连续数字")

            # 确认 PIN（第二次输入）
            if any(ind in all_text for ind in ["konfirmasi", "confirm"]):
                self.log("[gopay-appium] 确认 PIN（第二次）")
                self._input_pin_digits(pin)
                time.sleep(1)
                for btn in ["Simpan", "Save", "Konfirmasi", "Confirm", "Lanjut", "Next", "Continue"]:
                    try:
                        self._click_button_by_desc(btn, timeout=2)
                        break
                    except Exception:
                        continue
                time.sleep(8)

            # PIN 设置后可能需要 OTP 验证
            all_text = self._dump_descs("After PIN confirm")
            if self._is_technical_error(all_text):
                self.log("[gopay-appium] PIN 确认后技术错误，关闭后重新进入 PIN 流程...")
                for btn in ["Oke", "OK", "Try again", "Coba lagi"]:
                    try:
                        self._click_button_by_desc(btn, timeout=2)
                        break
                    except Exception:
                        continue
                time.sleep(3)
                pin_setup_retry += 1
                if pin_setup_retry >= 2 or not self._open_pin_setup_from_home():
                    break
                continue
            break

        all_text = self._dump_descs("After PIN confirm")

        if any(ind in all_text for ind in ["otp", "verifikasi", "verification", "kode", "code", "masukkan otp", "enter otp"]):
            self.log("[gopay-appium] PIN 设置需要 OTP 验证")

            # 切换到 SMS（hero-sms 不支持 WhatsApp）
            if "coba metode lainnya" in all_text or "try other method" in all_text:
                try:
                    for btn in ["Coba Metode Lainnya", "Coba metode lainnya", "Try Other Method", "Try other method"]:
                        try:
                            self._click_button_by_desc(btn, timeout=2)
                            break
                        except Exception:
                            continue
                except Exception:
                    pass
                time.sleep(3)

                sms_all = self._dump_descs("PIN OTP method selection")
                if "otp via sms" in sms_all or "sms" in sms_all or "text message" in sms_all:
                    try:
                        els = d.find_elements("xpath", "//*[contains(@content-desc, 'OTP via SMS')]")
                        for el in els:
                            if el.get_attribute("clickable") == "true":
                                el.click()
                                self.log("[gopay-appium] 选择 SMS OTP 用于 PIN 验证")
                                break
                    except Exception:
                        pass
                    time.sleep(5)

            # 等待并输入 OTP
            self.log("[gopay-appium] 等待 PIN 验证 OTP...")
            self._request_otp_resend_in_app()
            if pre_pin_otp_hook:
                self.log("[gopay-appium] PIN 第二次 OTP 前请求重发/激活...")
                pre_pin_otp_hook()
            pin_otp = otp_provider("gopay_pin_otp")
            if not pin_otp:
                raise GopayAppiumError("PIN 验证 OTP 未收到")

            otp_digits = re.sub(r'\D', '', pin_otp)[:6]
            self.log(f"[gopay-appium] 输入 PIN 验证 OTP: {otp_digits}")

            # 点击 EditText 聚焦（如果有）
            edit_texts = d.find_elements("class name", "android.widget.EditText")
            if edit_texts:
                edit_texts[0].click()
                time.sleep(0.5)

            # 通过 ADB keyevent 输入 OTP（OTP 页面用的是 EditText，不是自定义键盘）
            for digit in otp_digits:
                self._adb_shell(f"input keyevent {7 + int(digit)}")
                time.sleep(0.1)
            time.sleep(5)

            # OTP 可能自动提交，也可能需要点击
            try:
                self._click_next_button(timeout=3)
            except Exception:
                pass
            time.sleep(5)

        # 检查是否成功
        all_text = self._dump_descs("After PIN OTP")
        if not all_text.strip() or "wlan" in all_text or "蓝牙" in all_text or "下午" in all_text:
            self.log("[gopay-appium] 检测到系统覆盖层，拉回 GoPay 前台...")
            self._bring_gopay_to_front()
            all_text = self._dump_descs("After bringing GoPay front")
        if self._is_home_screen(all_text):
            self.log("[gopay-appium] PIN 设置完成，已返回主页")
        elif "berhasil" in all_text or "selesai" in all_text or "sukses" in all_text or "success" in all_text or "done" in all_text or "completed" in all_text:
            self.log("[gopay-appium] PIN 设置成功！")
            try:
                self._click_next_button(timeout=3)
            except Exception:
                pass
        else:
            self.log("[gopay-appium] PIN 设置结果不确定")
            self._save_screenshot("pin_setup_result")

    # ------------------------------------------------------------------
    # Token extraction
    # ------------------------------------------------------------------

    def _bring_gopay_to_front(self) -> None:
        self._adb_shell(f"am start -n {GOPAY_PACKAGE}/{GOPAY_ACTIVITY}")
        time.sleep(3)

    def _extract_tokens(self) -> dict[str, str]:
        """从设备存储中提取 access_token / refresh_token。

        尝试多种策略：
        1. 读取 SharedPreferences / FlutterSecureStorage
        2. 读取 SQLite 数据库
        3. 返回空值（调用方通过 login_after_signup 补充）
        """
        result = {"access_token": "", "refresh_token": "", "account_id": ""}

        # 策略 1: root 模拟器读 SharedPreferences
        try:
            prefs_paths = [
                f"/data/data/{GOPAY_PACKAGE}/shared_prefs/FlutterSecureStorage.xml",
                f"/data/data/{GOPAY_PACKAGE}/shared_prefs/auth_prefs.xml",
                f"/data/data/{GOPAY_PACKAGE}/shared_prefs/gopay_prefs.xml",
                f"/data/data/{GOPAY_PACKAGE}/shared_prefs/{GOPAY_PACKAGE}_preferences.xml",
            ]
            for path in prefs_paths:
                content = self._adb_shell(f"su -c 'cat {path}' 2>/dev/null || run-as {GOPAY_PACKAGE} cat {path.split('/shared_prefs/')[1]} 2>/dev/null")
                if not content or "No such file" in content or "Permission denied" in content:
                    continue
                tokens = self._parse_tokens_from_xml(content)
                if tokens.get("access_token"):
                    result.update(tokens)
                    self.log(f"[gopay-appium] Token 从 SharedPreferences 提取成功: {path}")
                    return result
        except Exception as exc:
            logger.debug("[gopay-appium] SharedPreferences 提取失败: %s", exc)

        # 策略 2: 列出所有 shared_prefs 文件，逐个搜索
        try:
            file_list = self._adb_shell(
                f"su -c 'ls /data/data/{GOPAY_PACKAGE}/shared_prefs/' 2>/dev/null || "
                f"run-as {GOPAY_PACKAGE} ls shared_prefs/ 2>/dev/null"
            )
            if file_list and "No such file" not in file_list:
                for fname in file_list.strip().split("\n"):
                    fname = fname.strip()
                    if not fname or not fname.endswith(".xml"):
                        continue
                    content = self._adb_shell(
                        f"su -c 'cat /data/data/{GOPAY_PACKAGE}/shared_prefs/{fname}' 2>/dev/null || "
                        f"run-as {GOPAY_PACKAGE} cat shared_prefs/{fname} 2>/dev/null"
                    )
                    if not content:
                        continue
                    if "token" in content.lower() or "access" in content.lower():
                        tokens = self._parse_tokens_from_xml(content)
                        if tokens.get("access_token"):
                            result.update(tokens)
                            self.log(f"[gopay-appium] Token 从 {fname} 提取成功")
                            return result
        except Exception as exc:
            logger.debug("[gopay-appium] 文件列表提取失败: %s", exc)

        # 策略 3: 无法提取 — 返回空值，调用方使用 login_after_signup
        self.log("[gopay-appium] 无法从设备存储提取 token，需要通过 HTTP login 获取")
        return result

    def _parse_tokens_from_xml(self, xml_content: str) -> dict[str, str]:
        """从 SharedPreferences XML 中解析 token。"""
        result: dict[str, str] = {}
        # 标准 SharedPreferences 格式: <string name="key">value</string>
        token_patterns = [
            (r'name="(?:access_token|accessToken|auth_token)"[^>]*>([^<]+)', "access_token"),
            (r'name="(?:refresh_token|refreshToken)"[^>]*>([^<]+)', "refresh_token"),
            (r'name="(?:account_id|accountId|customer_id|customerId|resource_owner_id)"[^>]*>([^<]+)', "account_id"),
        ]
        for pattern, key in token_patterns:
            match = re.search(pattern, xml_content)
            if match:
                result[key] = match.group(1).strip()

        # Flutter secure storage 使用 key-value 格式可能不同
        if not result.get("access_token"):
            # 尝试匹配 JWT-like token (eyJ...)
            jwt_matches = re.findall(r'>(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)<', xml_content)
            if jwt_matches:
                result["access_token"] = jwt_matches[0]
                if len(jwt_matches) > 1:
                    result["refresh_token"] = jwt_matches[1]

        return result

    # ------------------------------------------------------------------
    # ADB helpers
    # ------------------------------------------------------------------

    def _reset_device_identity(self) -> None:
        """重置设备标识，绕过 GoPay 的设备级频率限制。

        GoPay 的 F4 反欺诈 SDK 读取系统级设备标识（IMEI, Android ID, MAC 等）进行指纹识别。
        仅清除 APP 数据 (pm clear) 不够。

        策略:
        1. 如果有 ldconsole（雷电模拟器），关闭实例 → modify 重置全部硬件标识 → 重新启动
        2. 否则退回 ADB 方式只改 ANDROID_ID + 清除 GMS（效果有限）
        """
        if self._ldconsole_path and self._emulator_index >= 0:
            self._reset_via_ldconsole()
        else:
            self._reset_via_adb()

    def _reset_via_ldconsole(self) -> None:
        """通过 ldconsole (雷电模拟器) 重置全部设备标识。

        WARNING: ldconsole modify 会破坏 GMS (Google Mobile Services) 内部状态，
        导致 Play Integrity attestation 失败，GoPay 会显示 "gangguan teknis"。
        使用后可能需要等待 GMS 自行恢复，或使用其他干净的模拟器实例。

        ldconsole modify 支持: --imei --imsi --simserial --androidid --mac --manufacturer --model
        但需要先关闭模拟器实例。
        """
        idx = self._emulator_index
        self.log(f"[gopay-appium] 通过 ldconsole 重置设备标识 (index={idx})...")

        # 关闭模拟器实例
        self._run_ldconsole("quit", f"--index {idx}")
        self.log("[gopay-appium] 等待模拟器关闭...")
        deadline = time.time() + 30
        while time.time() < deadline:
            output = self._run_ldconsole("isrunning", f"--index {idx}")
            if "stop" in output.lower() or "running" not in output.lower():
                break
            time.sleep(2)
        time.sleep(3)  # 确保完全关闭

        # 重置所有设备标识为随机值
        self._run_ldconsole(
            "modify",
            f"--index {idx} "
            f"--imei auto --imsi auto --simserial auto "
            f"--androidid auto --mac auto",
        )
        self.log("[gopay-appium] 设备标识已全部重置 (IMEI/IMSI/SIM/AndroidID/MAC)")

        # 重新启动模拟器
        self._run_ldconsole("launch", f"--index {idx}")
        self.log("[gopay-appium] 模拟器重新启动中...")

        # 等待 ADB 设备上线
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                result = subprocess.run(
                    [self._adb_path, "devices"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=10,
                )
                if self.adb_serial and self.adb_serial in result.stdout and "device" in result.stdout.split(self.adb_serial)[1].split("\n")[0]:
                    break
                # 如果没指定 serial，检查是否有任何 device
                if not self.adb_serial and "device" in result.stdout and "offline" not in result.stdout:
                    lines = [l for l in result.stdout.strip().split("\n") if "\tdevice" in l]
                    if lines:
                        break
            except Exception:
                pass
            time.sleep(3)
        else:
            raise GopayAppiumError("模拟器重启后 ADB 设备未上线")

        self.log("[gopay-appium] 模拟器已启动，ADB 已连接")
        time.sleep(5)  # 等系统稳定

        # 清除 GoPay APP 数据（不清除 GMS，GoPay 依赖它启动）
        self._adb_shell(f"pm clear {GOPAY_PACKAGE}")
        time.sleep(2)

    def _reset_via_adb(self) -> None:
        """ADB 方式重置设备标识（效果有限，无法改 IMEI/MAC）。

        WARNING: Do NOT clear GMS (com.google.android.gms) — this permanently
        corrupts Play Integrity state, causing all GoPay signup attempts to fail
        with "gangguan teknis" or silent redirect to welcome page.
        """
        self.log("[gopay-appium] 通过 ADB 重置设备标识（有限）...")

        new_android_id = os.urandom(8).hex()
        self._adb_shell(f"settings put secure android_id {new_android_id}")
        self.log(f"[gopay-appium] ANDROID_ID 已重置: {new_android_id}")

        # Only clear GoPay, never clear GMS/GSF
        self._adb_shell(f"pm clear {GOPAY_PACKAGE}")
        self.log("[gopay-appium] GoPay APP 数据已清除")
        time.sleep(2)

    def _run_ldconsole(self, command: str, args: str = "") -> str:
        """执行 ldconsole 命令。"""
        cmd_str = f'"{self._ldconsole_path}" {command} {args}'.strip()
        try:
            proc = subprocess.run(
                cmd_str,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30, shell=True,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            logger.debug("[gopay-appium] ldconsole %s %s → %s", command, args, output.strip())
            return output
        except Exception as exc:
            logger.debug("[gopay-appium] ldconsole failed: %s", exc)
            return ""

    @staticmethod
    def _find_ldconsole() -> str:
        """自动查找 ldconsole 路径。"""
        candidates = [
            "D:/leidian/LDPlayer9/ldconsole.exe",
            "D:/leidian/LDPlayer/ldconsole.exe",
            "C:/leidian/LDPlayer9/ldconsole.exe",
            "C:/Program Files/LDPlayer9/ldconsole.exe",
            "C:/Program Files (x86)/LDPlayer9/ldconsole.exe",
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        return ""

    def _adb_shell(self, command: str, timeout: int = 10) -> str:
        """执行 adb shell 命令。"""
        cmd = [self._adb_path]
        if self.adb_serial:
            cmd += ["-s", self.adb_serial]
        cmd += ["shell", command]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return (proc.stdout or "") + (proc.stderr or "")
        except Exception as exc:
            logger.debug("[gopay-appium] adb shell failed: %s", exc)
            return ""

    def _adb_input_text(self, text: str) -> None:
        """通过 ADB 输入文本。"""
        # adb shell input text 不支持空格等特殊字符，逐字符输入数字
        if text.isdigit():
            self._adb_shell(f"input text {text}")
        else:
            # 使用 ADB broadcast 或逐字符方式
            escaped = text.replace(" ", "%s").replace("'", "\\'")
            self._adb_shell(f"input text '{escaped}'")

    def _dismiss_gms_popup(self) -> bool:
        """Dismiss GMS RecoverPermissionActivity if it's blocking GoPay.

        GMS popup appears when Play Integrity state is inconsistent, blocks GoPay
        during critical API calls (e.g. terms submission). Must detect via dumpsys
        window focus since it's not in GoPay's accessibility tree.

        Returns True if a popup was dismissed.
        """
        focus = self._adb_shell("dumpsys window | grep mCurrentFocus")
        if "google.android.gms" in focus or "RecoverPermission" in focus:
            self.log("[gopay-appium] GMS popup detected, dismissing...")
            self._adb_shell("input keyevent 4")  # BACK
            time.sleep(1)
            self._adb_shell("input keyevent 4")  # BACK again
            time.sleep(1)
            return True
        return False

    def _dump_descs(self, label: str = "", limit: int = 20) -> str:
        """Dump content-desc of visible elements for debugging. Returns all text lowercased."""
        if not self._driver:
            return ""
        descs = self._driver.find_elements("xpath", "//*[@content-desc!='']")
        all_text = ""
        if label:
            self.log(f"[gopay-appium] --- {label} ---")
        for i, el in enumerate(descs[:limit]):
            try:
                d = el.get_attribute("content-desc") or ""
            except Exception:
                d = "<stale>"
            all_text += " " + d.lower()
        return all_text

    def _is_technical_error(self, text: str) -> bool:
        """Check for real technical errors (not normal page content like 'kendala nomor HP?')."""
        return any(k in text for k in [
            "gangguan teknis", "kendala teknis",
            "terjadi kendala teknis", "ada gangguan teknis",
            "technical issue", "technical error", "something went wrong",
        ])

    def _is_cannot_continue_error(self, text: str) -> bool:
        """Check for GoPay's terminal cannot-continue/customer-service block."""
        return any(k in text for k in [
            "ga bisa dilanjutin", "tidak bisa dilanjutkan",
            "cannot continue", "can't continue",
            "hubungi customer service", "contact customer service",
        ])

    def _is_rate_limited(self, text: str) -> bool:
        """Check for all known rate limit message variants."""
        return any(k in text for k in [
            "coba lagi setelah", "istirahat dulu", "terlalu banyak percobaan",
            "coba lagi dalam", "try again after", "too many attempts",
        ])

    def _is_home_screen(self, text: str) -> bool:
        """Check if we're on the GoPay home screen (registration complete)."""
        home_keywords = [
            "top up", "tarik tunai", "cash out", "withdraw",
            "transfer gratis", "free transfer", "transfer",
            "saldo", "balance",
            "bayar", "pay",
            "beranda", "home",
        ]
        return sum(1 for k in home_keywords if k in text) >= 2

    def _save_screenshot(self, name: str) -> None:
        """保存截图用于调试。"""
        if not self._driver:
            return
        try:
            from autoteam.paths import PROJECT_ROOT
            screenshot_dir = PROJECT_ROOT / "data" / "gopay_appium_screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = screenshot_dir / f"{name}_{int(time.time())}.png"
            self._driver.save_screenshot(str(path))
            self.log(f"[gopay-appium] 截图已保存: {path}")
        except Exception as exc:
            logger.debug("[gopay-appium] 截图保存失败: %s", exc)

    # ------------------------------------------------------------------
    # UI utility methods
    # ------------------------------------------------------------------

    def _click_button_by_desc(self, desc_text: str, timeout: int = 5) -> None:
        """通过 content-desc 查找并点击已启用按钮。"""
        d = self._driver
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                elements = d.find_elements("xpath", f"//*[contains(@content-desc, '{desc_text}')]")
                for el in elements:
                    enabled = ""
                    try:
                        enabled = el.get_attribute("enabled") or ""
                    except Exception:
                        pass
                    if (el.get_attribute("clickable") == "true" or el.tag_name == "android.widget.Button") and str(enabled).lower() != "false":
                        el.click()
                        self.log(f"[gopay-appium] 点击按钮: '{desc_text}'")
                        return
            except Exception:
                pass
            time.sleep(0.5)
        raise GopayAppiumError(f"无法找到按钮: '{desc_text}'")

    def _click_next_button(self, timeout: int = 5) -> None:
        """查找并点击 "继续"/"下一步" 按钮。"""
        d = self._driver
        next_descs = [
            "Lanjut", "Lanjutkan", "Next", "Continue", "Kirim",
            "Send", "Verifikasi", "Verify", "Submit", "OK", "Konfirmasi",
            "Confirm", "Setuju", "Agree",
        ]

        deadline = time.time() + timeout
        while time.time() < deadline:
            for desc_text in next_descs:
                try:
                    elements = d.find_elements("xpath", f"//*[contains(@content-desc, '{desc_text}')]")
                    for el in elements:
                        if el.get_attribute("clickable") == "true" or el.tag_name == "android.widget.Button":
                            el.click()
                            self.log(f"[gopay-appium] 点击按钮: '{desc_text}'")
                            return
                except Exception:
                    continue
            # 也尝试 text 属性（系统原生按钮）
            for desc_text in next_descs:
                try:
                    elements = d.find_elements("xpath", f"//*[contains(@text, '{desc_text}')]")
                    for el in elements:
                        if el.get_attribute("clickable") == "true":
                            el.click()
                            self.log(f"[gopay-appium] 点击按钮(text): '{desc_text}'")
                            return
                except Exception:
                    continue
            time.sleep(0.5)

        raise GopayAppiumError("无法找到 '继续' 按钮")

    def _check_for_error(self, all_text: str = "") -> str | None:
        """检查页面上是否有错误提示。Returns error type or None."""
        if not all_text:
            if not self._driver:
                return None
            all_text = self._dump_descs()
        if self._is_technical_error(all_text):
            self.log("[gopay-appium] 检测到技术错误")
            self._save_screenshot("technical_error")
            return "technical_error"
        if self._is_rate_limited(all_text):
            self.log("[gopay-appium] 检测到频率限制")
            self._save_screenshot("rate_limited")
            return "rate_limited"
        return None

    def _check_device_rate_limit(self, all_text: str = "") -> bool:
        """检查是否触发了设备频率限制。

        GoPay 在同一设备短时间内尝试过多不同号码时显示多种消息:
        - "Coba lagi setelah 60 menit, ya"
        - "Istirahat duluuu"
        - "Terlalu banyak percobaan"
        - "Coba lagi dalam X menit"

        Args:
            all_text: pre-fetched lowercased page text. If empty, reads from screen.

        Returns:
            True if rate limited (caller should reset device and restart).
        """
        if not all_text:
            if not self._driver:
                return False
            all_text = self._dump_descs()
        return self._is_rate_limited(all_text)

    def get_page_info(self) -> dict[str, Any]:
        """获取当前页面信息（用于调试）。"""
        if not self._driver:
            return {"error": "no session"}
        try:
            return {
                "activity": self._driver.current_activity,
                "package": self._driver.current_package,
                "page_source_length": len(self._driver.page_source),
            }
        except Exception as exc:
            return {"error": str(exc)}
