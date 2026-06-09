"""browser_fingerprint 模块的单元测试。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import playwright

from autotoken.browser_fingerprint import (
    BrowserFingerprint,
    cleanup_temp_user_data_dir,
    create_temp_user_data_dir,
    generate_fingerprint,
    get_context_options,
    get_stealth_init_script,
)
from autotoken.core import browser_fingerprint as browser_fingerprint_module
from autotoken.core.files import READ_JSON_FILE_MAX_BYTES


def _bundled_chromium_version() -> str:
    browsers_json = Path(playwright.__file__).resolve().parent / "driver" / "package" / "browsers.json"
    payload = json.loads(browsers_json.read_text(encoding="utf-8"))
    for browser in payload.get("browsers", []):
        if isinstance(browser, dict) and browser.get("name") == "chromium":
            return str(browser.get("browserVersion") or "")
    return ""


class TestGenerateFingerprint:
    """generate_fingerprint() 基础行为。"""

    def test_returns_fingerprint_instance(self):
        fp = generate_fingerprint()
        assert isinstance(fp, BrowserFingerprint)

    def test_each_call_differs(self):
        """连续生成的指纹应该不完全相同。"""
        fps = [generate_fingerprint() for _ in range(20)]
        # canvas_noise_seed 每次不同
        seeds = {fp.canvas_noise_seed for fp in fps}
        assert len(seeds) >= 10, f"too few unique seeds: {len(seeds)}"
        # fingerprint_id 也应有差异
        ids = {fp.fingerprint_id for fp in fps}
        assert len(ids) >= 5, f"too few unique ids: {len(ids)}"

    def test_ua_platform_consistency_win(self):
        fp = generate_fingerprint(force_platform="win")
        assert "Windows" in fp.user_agent
        assert fp.platform == "Win32"

    def test_ua_platform_consistency_mac(self):
        fp = generate_fingerprint(force_platform="mac")
        assert "Macintosh" in fp.user_agent
        assert fp.platform == "MacIntel"

    def test_force_locale(self):
        fp = generate_fingerprint(force_locale="ja-JP")
        assert fp.locale == "ja-JP"

    def test_force_timezone(self):
        fp = generate_fingerprint(force_timezone="America/Chicago")
        assert fp.timezone_id == "America/Chicago"

    def test_viewport_is_dict(self):
        fp = generate_fingerprint()
        assert "width" in fp.viewport
        assert "height" in fp.viewport
        assert fp.viewport["width"] > 0
        assert fp.viewport["height"] > 0

    def test_screen_gte_viewport(self):
        for _ in range(20):
            fp = generate_fingerprint()
            assert fp.screen_width >= fp.viewport["width"]
            assert fp.screen_height >= fp.viewport["height"]

    def test_webgl_platform_match_win(self):
        """Windows 平台不应选到 Apple GPU。"""
        for _ in range(30):
            fp = generate_fingerprint(force_platform="win")
            assert "Apple" not in fp.webgl_renderer, fp.webgl_renderer

    def test_webgl_platform_match_mac(self):
        """Mac 平台应选到 Apple 或 Intel GPU。"""
        for _ in range(30):
            fp = generate_fingerprint(force_platform="mac")
            assert "Apple" in fp.webgl_renderer or "Intel" in fp.webgl_renderer, fp.webgl_renderer

    def test_hardware_concurrency_range(self):
        for _ in range(20):
            fp = generate_fingerprint()
            assert fp.hardware_concurrency in (4, 6, 8, 12, 16)

    def test_device_memory_range(self):
        for _ in range(20):
            fp = generate_fingerprint()
            assert fp.device_memory in (4, 8, 16)

    def test_fingerprint_id_is_hex(self):
        fp = generate_fingerprint()
        assert re.fullmatch(r"[0-9a-f]{12}", fp.fingerprint_id), fp.fingerprint_id

    # --- v2 新增字段 ---

    def test_chrome_version_extracted(self):
        fp = generate_fingerprint()
        assert fp.chrome_version.isdigit()
        assert "." in fp.chrome_version_full

    def test_chrome_version_matches_ua(self):
        fp = generate_fingerprint()
        assert f"Chrome/{fp.chrome_version_full}" in fp.user_agent or f"Chrome/{fp.chrome_version}." in fp.user_agent

    def test_chrome_version_matches_playwright_bundle(self):
        fp = generate_fingerprint()
        bundled_version = _bundled_chromium_version()
        assert bundled_version
        assert fp.chrome_version_full == bundled_version
        assert f"Chrome/{bundled_version}" in fp.user_agent

    def test_chromium_version_detection_falls_back_for_oversized_browser_metadata(self, tmp_path, monkeypatch):
        fake_package = tmp_path / "playwright"
        fake_package.mkdir()
        browsers_json = fake_package / "driver" / "package" / "browsers.json"
        browsers_json.parent.mkdir(parents=True)
        browsers_json.write_text("x" * (READ_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")
        monkeypatch.setattr(playwright, "__file__", str(fake_package / "__init__.py"))
        monkeypatch.setattr(browser_fingerprint_module, "_playwright_chromium_version_full", None)

        assert browser_fingerprint_module._detect_playwright_chromium_version_full() == "145.0.0.0"

    def test_audio_noise_seed_differs(self):
        fps = [generate_fingerprint() for _ in range(20)]
        seeds = {fp.audio_noise_seed for fp in fps}
        assert len(seeds) >= 10

    def test_audio_sample_rate_valid(self):
        for _ in range(20):
            fp = generate_fingerprint()
            assert fp.audio_sample_rate in (44100, 48000)

    def test_font_families_populated(self):
        fp = generate_fingerprint()
        assert len(fp.font_families) >= 8

    def test_font_families_platform_match_win(self):
        for _ in range(10):
            fp = generate_fingerprint(force_platform="win")
            # Windows 不会出现 Mac-only 字体
            assert "Menlo" not in fp.font_families
            assert "SF Pro" not in fp.font_families

    def test_font_families_platform_match_mac(self):
        for _ in range(10):
            fp = generate_fingerprint(force_platform="mac")
            # Mac 不会出现 Windows-only 字体
            assert "Segoe UI" not in fp.font_families
            assert "Calibri" not in fp.font_families


class TestGetContextOptions:
    """get_context_options() 返回结构。"""

    def test_returns_dict(self):
        fp = generate_fingerprint()
        opts = get_context_options(fp)
        assert isinstance(opts, dict)

    def test_contains_required_keys(self):
        fp = generate_fingerprint()
        opts = get_context_options(fp)
        for key in ("viewport", "user_agent", "locale", "timezone_id", "device_scale_factor", "extra_http_headers"):
            assert key in opts, f"missing key: {key}"

    def test_viewport_matches(self):
        fp = generate_fingerprint()
        opts = get_context_options(fp)
        assert opts["viewport"] == fp.viewport

    def test_user_agent_matches(self):
        fp = generate_fingerprint()
        opts = get_context_options(fp)
        assert opts["user_agent"] == fp.user_agent

    def test_color_scheme_valid(self):
        fp = generate_fingerprint()
        opts = get_context_options(fp)
        assert opts.get("color_scheme") in ("light", "dark")

    def test_contains_client_hints_headers(self):
        """v2: extra_http_headers 中应包含 Sec-CH-UA 等 Client Hints。"""
        fp = generate_fingerprint()
        opts = get_context_options(fp)
        headers = opts["extra_http_headers"]
        assert "Sec-CH-UA" in headers
        assert "Sec-CH-UA-Mobile" in headers
        assert headers["Sec-CH-UA-Mobile"] == "?0"
        assert "Sec-CH-UA-Platform" in headers

    def test_client_hints_platform_matches_fingerprint(self):
        fp_win = generate_fingerprint(force_platform="win")
        opts_win = get_context_options(fp_win)
        assert '"Windows"' in opts_win["extra_http_headers"]["Sec-CH-UA-Platform"]

        fp_mac = generate_fingerprint(force_platform="mac")
        opts_mac = get_context_options(fp_mac)
        assert '"macOS"' in opts_mac["extra_http_headers"]["Sec-CH-UA-Platform"]

    def test_client_hints_version_matches_ua(self):
        fp = generate_fingerprint()
        opts = get_context_options(fp)
        sec_ch_ua = opts["extra_http_headers"]["Sec-CH-UA"]
        assert fp.chrome_version in sec_ch_ua


class TestGetStealthInitScript:
    """get_stealth_init_script() JS 生成。"""

    def test_returns_string(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert isinstance(script, str)
        assert len(script) > 500

    def test_contains_webdriver_override(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "webdriver" in script

    def test_contains_chrome_mock(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "window.chrome" in script

    def test_contains_hardware_concurrency(self):
        fp = generate_fingerprint(force_platform="win")
        fp.hardware_concurrency = 12
        script = get_stealth_init_script(fp)
        assert "hardwareConcurrency" in script
        assert "12" in script

    def test_contains_webgl_vendor(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "0x9245" in script  # UNMASKED_VENDOR_WEBGL
        assert "0x9246" in script  # UNMASKED_RENDERER_WEBGL
        # 实际 vendor 值应出现在脚本中
        assert fp.webgl_vendor in script or json.dumps(fp.webgl_vendor) in script

    def test_contains_canvas_noise(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "NOISE_SEED" in script
        assert str(fp.canvas_noise_seed) in script

    def test_contains_plugins(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "Chrome PDF Plugin" in script

    def test_contains_platform(self):
        fp = generate_fingerprint(force_platform="win")
        script = get_stealth_init_script(fp)
        assert '"Win32"' in script

    def test_different_fingerprints_produce_different_scripts(self):
        fp1 = generate_fingerprint()
        fp2 = generate_fingerprint()
        s1 = get_stealth_init_script(fp1)
        s2 = get_stealth_init_script(fp2)
        # canvas noise seed 几乎一定不同
        assert s1 != s2

    # --- v2 新增 ---

    def test_contains_audio_context_noise(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "AUDIO_SEED" in script
        assert str(fp.audio_noise_seed) in script
        assert "getChannelData" in script

    def test_contains_client_hints_api(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "userAgentData" in script
        assert "getHighEntropyValues" in script
        assert fp.chrome_version in script

    def test_contains_battery_api(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "getBattery" in script

    def test_contains_font_defense(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "measureText" in script

    def test_contains_webrtc_protection(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "RTCPeerConnection" in script

    def test_contains_playwright_marker_removal(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "__playwright" in script

    def test_contains_function_tostring_patch(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "native code" in script

    def test_contains_chrome_app(self):
        fp = generate_fingerprint()
        script = get_stealth_init_script(fp)
        assert "chrome.app" in script


class TestTempUserDataDir:
    """临时 user_data_dir 管理。"""

    def test_create_returns_existing_dir(self):
        path = create_temp_user_data_dir()
        try:
            assert os.path.isdir(path)
        finally:
            cleanup_temp_user_data_dir(path)

    def test_cleanup_removes_dir(self):
        path = create_temp_user_data_dir()
        assert os.path.isdir(path)
        cleanup_temp_user_data_dir(path)
        assert not os.path.exists(path)

    def test_each_call_creates_unique_dir(self):
        dirs = [create_temp_user_data_dir() for _ in range(5)]
        try:
            assert len(set(dirs)) == 5
        finally:
            for d in dirs:
                cleanup_temp_user_data_dir(d)

    def test_cleanup_ignores_unmanaged_directory(self, tmp_path):
        target = tmp_path / "not-managed"
        target.mkdir()
        (target / "file.txt").write_text("keep", encoding="utf-8")

        cleanup_temp_user_data_dir(str(target))

        assert target.exists()
        assert (target / "file.txt").exists()
