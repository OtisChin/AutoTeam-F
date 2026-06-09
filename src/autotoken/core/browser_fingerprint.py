"""浏览器指纹随机化模块。

每次调用 generate_fingerprint() 生成一组内部一致的随机浏览器指纹参数，
通过 get_context_options() 传入 browser.new_context()，
通过 get_stealth_init_script() 注入 add_init_script() 实现深层属性覆盖。

v2: 增加 AudioContext 噪声、Client Hints、Font 指纹扰动、
    独立 user_data_dir 支持、更完善的 iframe/worker 防泄漏。
"""

from __future__ import annotations

import hashlib
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autotoken.core.files import read_json_file

# ---------------------------------------------------------------------------
# 指纹数据池
# ---------------------------------------------------------------------------

# 真实 Chrome User-Agent 模板（Windows / Mac）。
# Chrome 版本在 generate_fingerprint() 中用当前 Playwright Chromium 版本替换，
# 避免 UA / Client Hints 和实际浏览器版本差距过大触发 Cloudflare 风控。
_USER_AGENTS_WIN = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.91 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.77 Safari/537.36",
]

_USER_AGENTS_MAC = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

# 常见分辨率
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
    {"width": 1680, "height": 1050},
]

# 美国时区
_US_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
    "America/Anchorage",
    "Pacific/Honolulu",
]

# WebGL GPU 信息 (vendor, renderer)
_WEBGL_GPUS = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 2070 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 5700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Apple)", "ANGLE (Apple, Apple M1 Pro, OpenGL 4.1)"),
    ("Google Inc. (Apple)", "ANGLE (Apple, Apple M2, OpenGL 4.1)"),
    ("Google Inc. (Apple)", "ANGLE (Apple, Apple M3, OpenGL 4.1)"),
]

# 常见屏幕 colorDepth
_COLOR_DEPTHS = [24, 30, 32]

# hardwareConcurrency 选项
_HARDWARE_CONCURRENCIES = [4, 6, 8, 12, 16]

# deviceMemory 选项
_DEVICE_MEMORIES = [4, 8, 16]

# device scale factor
_DEVICE_SCALE_FACTORS = [1, 1.25, 1.5, 2]

# AudioContext sampleRate 选项
_AUDIO_SAMPLE_RATES = [44100, 48000]

# 常见字体列表（用于 font fingerprint 扰动）
_FONT_FAMILIES_WIN = [
    "Arial", "Calibri", "Cambria", "Consolas", "Courier New",
    "Georgia", "Impact", "Segoe UI", "Tahoma", "Times New Roman",
    "Trebuchet MS", "Verdana", "Lucida Console", "Palatino Linotype",
]
_FONT_FAMILIES_MAC = [
    "Arial", "Avenir", "Courier New", "Georgia", "Helvetica",
    "Helvetica Neue", "Lucida Grande", "Menlo", "Monaco",
    "Optima", "Palatino", "SF Pro", "Times New Roman", "Trebuchet MS",
]


# ---------------------------------------------------------------------------
# 指纹数据类
# ---------------------------------------------------------------------------


@dataclass
class BrowserFingerprint:
    """一组内部一致的浏览器指纹参数。"""

    user_agent: str
    platform: str  # "Win32" or "MacIntel"
    viewport: dict[str, int]
    screen_width: int
    screen_height: int
    device_scale_factor: float
    color_depth: int
    timezone_id: str
    locale: str
    accept_language: str
    languages: list[str]
    hardware_concurrency: int
    device_memory: int
    webgl_vendor: str
    webgl_renderer: str
    canvas_noise_seed: int
    audio_noise_seed: int
    audio_sample_rate: int
    font_families: list[str]
    # Chrome 版本号（从 UA 提取，用于 Client Hints）
    chrome_version: str
    chrome_version_full: str
    # 内部标识
    fingerprint_id: str = field(default_factory=lambda: "")


# ---------------------------------------------------------------------------
# 临时 user_data_dir 管理
# ---------------------------------------------------------------------------

_active_temp_dirs: list[str] = []
_TEMP_PROFILE_PREFIX = "pw_profile_"


def create_temp_user_data_dir() -> str:
    """创建一个临时的 Chromium user-data-dir，确保每次启动完全隔离。"""
    tmp = tempfile.mkdtemp(prefix=_TEMP_PROFILE_PREFIX)
    _active_temp_dirs.append(tmp)
    return tmp


def _is_managed_temp_user_data_dir(path: str) -> bool:
    if path not in _active_temp_dirs:
        return False
    try:
        resolved = Path(path).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        return resolved.name.startswith(_TEMP_PROFILE_PREFIX) and resolved.is_relative_to(temp_root)
    except Exception:
        return False


def cleanup_temp_user_data_dir(path: str) -> None:
    """清理临时 user-data-dir。"""
    if _is_managed_temp_user_data_dir(path):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass
    if path in _active_temp_dirs:
        _active_temp_dirs.remove(path)


def cleanup_all_temp_dirs() -> None:
    """清理所有残留的临时目录。"""
    for p in list(_active_temp_dirs):
        cleanup_temp_user_data_dir(p)


# ---------------------------------------------------------------------------
# 辅助：从 UA 提取 Chrome 版本
# ---------------------------------------------------------------------------

_CHROME_VER_RE = re.compile(r"Chrome/(\d+)\.(\d+)\.(\d+)\.(\d+)")
_CHROME_VERSION_FULL_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_CHROME_VERSION_FALLBACK_FULL = "145.0.0.0"
_playwright_chromium_version_full: str | None = None


def _extract_chrome_version(ua: str) -> tuple[str, str]:
    """从 UA 中提取 Chrome 主版本和完整版本。"""
    m = _CHROME_VER_RE.search(ua)
    if m:
        return m.group(1), f"{m.group(1)}.{m.group(2)}.{m.group(3)}.{m.group(4)}"
    return _CHROME_VERSION_FALLBACK_FULL.split(".", 1)[0], _CHROME_VERSION_FALLBACK_FULL


def _detect_playwright_chromium_version_full() -> str:
    """读取 Playwright 自带 Chromium 的真实版本号。"""
    global _playwright_chromium_version_full
    if _playwright_chromium_version_full:
        return _playwright_chromium_version_full

    version = ""
    try:
        import playwright

        browsers_json = Path(playwright.__file__).resolve().parent / "driver" / "package" / "browsers.json"
        payload = read_json_file(browsers_json, {})
        for browser in payload.get("browsers", []):
            if not isinstance(browser, dict):
                continue
            if browser.get("name") != "chromium":
                continue
            candidate = str(browser.get("browserVersion") or "").strip()
            if _CHROME_VERSION_FULL_RE.fullmatch(candidate):
                version = candidate
                break
    except Exception:
        version = ""

    _playwright_chromium_version_full = version or _CHROME_VERSION_FALLBACK_FULL
    return _playwright_chromium_version_full


def _with_current_chromium_version(user_agent: str) -> str:
    version = _detect_playwright_chromium_version_full()
    return _CHROME_VER_RE.sub(f"Chrome/{version}", user_agent, count=1)


# ---------------------------------------------------------------------------
# 指纹生成
# ---------------------------------------------------------------------------


def generate_fingerprint(
    *,
    force_platform: str | None = None,
    force_locale: str | None = None,
    force_timezone: str | None = None,
) -> BrowserFingerprint:
    """生成一组随机但内部一致的浏览器指纹。

    Parameters
    ----------
    force_platform : "win" | "mac" | None
        强制选择平台。None 时随机（70% Win, 30% Mac）。
    force_locale : str | None
        强制 locale，默认 "en-US"。
    force_timezone : str | None
        强制时区，默认从美国时区池随机。
    """
    # 平台选择
    if force_platform == "mac":
        is_win = False
    elif force_platform == "win":
        is_win = True
    else:
        is_win = random.random() < 0.70

    # UA
    if is_win:
        user_agent = _with_current_chromium_version(random.choice(_USER_AGENTS_WIN))
        platform = "Win32"
    else:
        user_agent = _with_current_chromium_version(random.choice(_USER_AGENTS_MAC))
        platform = "MacIntel"

    # Chrome version from UA
    chrome_version, chrome_version_full = _extract_chrome_version(user_agent)

    # Viewport & screen
    viewport = random.choice(_VIEWPORTS)
    # 屏幕尺寸 >= viewport（模拟有 taskbar 等）
    screen_width = viewport["width"] + random.choice([0, 0, 0, 80, 120])
    screen_height = viewport["height"] + random.choice([0, 0, 40, 60, 80])
    device_scale_factor = random.choice(_DEVICE_SCALE_FACTORS)
    # Mac 通常 Retina
    if not is_win:
        device_scale_factor = random.choice([1.5, 2, 2])
    color_depth = random.choice(_COLOR_DEPTHS)

    # Locale & timezone
    locale = force_locale or "en-US"
    timezone_id = force_timezone or random.choice(_US_TIMEZONES)
    accept_language = "en-US,en;q=0.9"
    languages = ["en-US", "en"]

    # Hardware
    hardware_concurrency = random.choice(_HARDWARE_CONCURRENCIES)
    device_memory = random.choice(_DEVICE_MEMORIES)

    # WebGL
    gpu = random.choice(_WEBGL_GPUS)
    # 确保平台匹配
    if is_win:
        win_gpus = [g for g in _WEBGL_GPUS if "Apple" not in g[1]]
        gpu = random.choice(win_gpus) if win_gpus else gpu
    else:
        mac_gpus = [g for g in _WEBGL_GPUS if "Apple" in g[1] or "Intel" in g[1]]
        gpu = random.choice(mac_gpus) if mac_gpus else gpu

    webgl_vendor = gpu[0]
    webgl_renderer = gpu[1]

    # Canvas noise seed (每次不同)
    canvas_noise_seed = int(time.time() * 1000) ^ random.getrandbits(32)

    # Audio
    audio_noise_seed = random.getrandbits(32)
    audio_sample_rate = random.choice(_AUDIO_SAMPLE_RATES)

    # Fonts
    if is_win:
        font_families = random.sample(_FONT_FAMILIES_WIN, k=random.randint(8, 12))
    else:
        font_families = random.sample(_FONT_FAMILIES_MAC, k=random.randint(8, 12))

    # fingerprint ID
    fp_id = hashlib.md5(
        f"{user_agent}{viewport}{canvas_noise_seed}{webgl_renderer}{audio_noise_seed}".encode()
    ).hexdigest()[:12]

    return BrowserFingerprint(
        user_agent=user_agent,
        platform=platform,
        viewport=viewport,
        screen_width=screen_width,
        screen_height=screen_height,
        device_scale_factor=device_scale_factor,
        color_depth=color_depth,
        timezone_id=timezone_id,
        locale=locale,
        accept_language=accept_language,
        languages=languages,
        hardware_concurrency=hardware_concurrency,
        device_memory=device_memory,
        webgl_vendor=webgl_vendor,
        webgl_renderer=webgl_renderer,
        canvas_noise_seed=canvas_noise_seed,
        audio_noise_seed=audio_noise_seed,
        audio_sample_rate=audio_sample_rate,
        font_families=font_families,
        chrome_version=chrome_version,
        chrome_version_full=chrome_version_full,
        fingerprint_id=fp_id,
    )


# ---------------------------------------------------------------------------
# Context options (传给 browser.new_context())
# ---------------------------------------------------------------------------


def get_context_options(fp: BrowserFingerprint) -> dict[str, Any]:
    """返回可直接 **解包传给 browser.new_context() 的参数字典。"""
    # Client Hints headers — PayPal/Cloudflare 重点检测这些
    sec_ch_ua = f'"Chromium";v="{fp.chrome_version}", "Google Chrome";v="{fp.chrome_version}", "Not-A.Brand";v="99"'
    sec_ch_ua_platform = '"Windows"' if fp.platform == "Win32" else '"macOS"'

    return {
        "viewport": fp.viewport,
        "user_agent": fp.user_agent,
        "locale": fp.locale,
        "timezone_id": fp.timezone_id,
        "device_scale_factor": fp.device_scale_factor,
        "extra_http_headers": {
            "Accept-Language": fp.accept_language,
            "Sec-CH-UA": sec_ch_ua,
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": sec_ch_ua_platform,
        },
        "color_scheme": random.choice(["light", "light", "light", "dark"]),
    }


# ---------------------------------------------------------------------------
# Stealth init script
# ---------------------------------------------------------------------------


def get_stealth_init_script(fp: BrowserFingerprint) -> str:
    """生成完整的 stealth init script JS 字符串。"""

    import json

    languages_js = json.dumps(fp.languages)
    webgl_vendor_js = json.dumps(fp.webgl_vendor)
    webgl_renderer_js = json.dumps(fp.webgl_renderer)
    platform_js = json.dumps(fp.platform)
    sec_ch_ua_platform_js = json.dumps("Windows" if fp.platform == "Win32" else "macOS")

    script = f"""
(() => {{
  // ===== 1. Remove webdriver flag =====
  Object.defineProperty(navigator, 'webdriver', {{
    get: () => undefined,
    configurable: true,
  }});
  // Also delete from prototype
  delete Object.getPrototypeOf(navigator).webdriver;

  // ===== 2. Mock window.chrome =====
  if (!window.chrome) {{
    window.chrome = {{}};
  }}
  if (!window.chrome.runtime) {{
    window.chrome.runtime = {{
      connect: function(extId) {{
        return {{
          name: '',
          sender: undefined,
          onMessage: {{ addListener: function() {{}}, removeListener: function() {{}}, hasListeners: function() {{ return false; }} }},
          onDisconnect: {{ addListener: function() {{}}, removeListener: function() {{}}, hasListeners: function() {{ return false; }} }},
          postMessage: function() {{}},
          disconnect: function() {{}},
        }};
      }},
      sendMessage: function() {{}},
      onMessage: {{ addListener: function() {{}}, removeListener: function() {{}}, hasListeners: function() {{ return false; }} }},
      onConnect: {{ addListener: function() {{}}, removeListener: function() {{}}, hasListeners: function() {{ return false; }} }},
      id: undefined,
      getManifest: function() {{ return undefined; }},
      getURL: function(path) {{ return ''; }},
      getPlatformInfo: function(cb) {{ if(cb) cb({{os: 'win', arch: 'x86-64', nacl_arch: 'x86-64'}}); }},
    }};
  }}
  // app 对象 (某些检测脚本会检查)
  if (!window.chrome.app) {{
    window.chrome.app = {{
      isInstalled: false,
      InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
      RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }},
      getDetails: function() {{ return null; }},
      getIsInstalled: function() {{ return false; }},
    }};
  }}
  window.chrome.loadTimes = function() {{
    return {{
      commitLoadTime: Date.now() / 1000 - Math.random() * 2,
      connectionInfo: "h2",
      finishDocumentLoadTime: Date.now() / 1000 - Math.random(),
      finishLoadTime: Date.now() / 1000 - Math.random() * 0.5,
      firstPaintAfterLoadTime: 0,
      firstPaintTime: Date.now() / 1000 - Math.random() * 1.5,
      navigationType: "Other",
      npnNegotiatedProtocol: "h2",
      requestTime: Date.now() / 1000 - Math.random() * 3,
      startLoadTime: Date.now() / 1000 - Math.random() * 2.5,
      wasAlternateProtocolAvailable: false,
      wasFetchedViaSpdy: true,
      wasNpnNegotiated: true,
    }};
  }};
  window.chrome.csi = function() {{
    return {{
      onloadT: Date.now(),
      pageT: Math.random() * 1000 + 500,
      startE: Date.now() - Math.floor(Math.random() * 3000),
      tran: 15,
    }};
  }};

  // ===== 3. Navigator properties =====
  Object.defineProperty(navigator, 'hardwareConcurrency', {{
    get: () => {fp.hardware_concurrency},
    configurable: true,
  }});
  Object.defineProperty(navigator, 'deviceMemory', {{
    get: () => {fp.device_memory},
    configurable: true,
  }});
  Object.defineProperty(navigator, 'platform', {{
    get: () => {platform_js},
    configurable: true,
  }});
  Object.defineProperty(navigator, 'languages', {{
    get: () => Object.freeze({languages_js}),
    configurable: true,
  }});
  Object.defineProperty(navigator, 'maxTouchPoints', {{
    get: () => 0,
    configurable: true,
  }});

  // ===== 4. Client Hints API (navigator.userAgentData) =====
  if (!navigator.userAgentData) {{
    Object.defineProperty(navigator, 'userAgentData', {{
      get: () => ({{
        brands: [
          {{ brand: "Chromium", version: "{fp.chrome_version}" }},
          {{ brand: "Google Chrome", version: "{fp.chrome_version}" }},
          {{ brand: "Not-A.Brand", version: "99" }},
        ],
        mobile: false,
        platform: {sec_ch_ua_platform_js},
        getHighEntropyValues: function(hints) {{
          return Promise.resolve({{
            brands: this.brands,
            mobile: false,
            platform: {sec_ch_ua_platform_js},
            platformVersion: {json.dumps("15.0.0" if fp.platform == "Win32" else "14.5.0")},
            architecture: "x86",
            bitness: "64",
            model: "",
            uaFullVersion: "{fp.chrome_version_full}",
            fullVersionList: this.brands.map(b => ({{...b, version: "{fp.chrome_version_full}"}})),
          }});
        }},
        toJSON: function() {{
          return {{ brands: this.brands, mobile: this.mobile, platform: this.platform }};
        }},
      }}),
      configurable: true,
    }});
  }}

  // ===== 5. Plugins (simulate Chrome default plugins) =====
  const makePlugin = (name, filename, description, mimeType) => {{
    const mt = {{ type: mimeType, suffixes: "", description, enabledPlugin: null }};
    const plugin = {{
      name,
      filename,
      description,
      length: 1,
      0: mt,
      item: (i) => i === 0 ? mt : null,
      namedItem: (n) => n === mimeType ? mt : null,
      [Symbol.iterator]: function*() {{ yield mt; }},
    }};
    mt.enabledPlugin = plugin;
    return plugin;
  }};

  const fakePlugins = [
    makePlugin("Chrome PDF Plugin", "internal-pdf-viewer", "Portable Document Format", "application/x-google-chrome-pdf"),
    makePlugin("Chrome PDF Viewer", "mhjfbmdgcfjbbpaeojofohoefgiehjai", "Portable Document Format", "application/pdf"),
    makePlugin("Native Client", "internal-nacl-plugin", "", "application/x-nacl"),
    makePlugin("Chromium PDF Plugin", "internal-pdf-viewer", "Portable Document Format", "application/x-google-chrome-pdf"),
    makePlugin("Chromium PDF Viewer", "mhjfbmdgcfjbbpaeojofohoefgiehjai", "", "application/pdf"),
  ];

  Object.defineProperty(navigator, 'plugins', {{
    get: () => {{
      const arr = fakePlugins;
      arr.item = (i) => arr[i] || null;
      arr.namedItem = (name) => arr.find(p => p.name === name) || null;
      arr.refresh = () => {{}};
      return arr;
    }},
    configurable: true,
  }});

  Object.defineProperty(navigator, 'mimeTypes', {{
    get: () => {{
      const mimes = fakePlugins.map(p => p[0]);
      mimes.item = (i) => mimes[i] || null;
      mimes.namedItem = (name) => mimes.find(m => m.type === name) || null;
      return mimes;
    }},
    configurable: true,
  }});

  // ===== 6. Screen properties =====
  const screenProps = {{
    width: {fp.screen_width},
    height: {fp.screen_height},
    availWidth: {fp.screen_width},
    availHeight: {fp.screen_height - random.randint(30, 60)},
    colorDepth: {fp.color_depth},
    pixelDepth: {fp.color_depth},
  }};
  for (const [key, value] of Object.entries(screenProps)) {{
    Object.defineProperty(screen, key, {{ get: () => value, configurable: true }});
  }}
  // outerWidth/outerHeight
  Object.defineProperty(window, 'outerWidth', {{ get: () => {fp.viewport["width"]}, configurable: true }});
  Object.defineProperty(window, 'outerHeight', {{ get: () => {fp.viewport["height"] + random.randint(60, 100)}, configurable: true }});
  Object.defineProperty(window, 'innerWidth', {{ get: () => {fp.viewport["width"]}, configurable: true }});
  Object.defineProperty(window, 'innerHeight', {{ get: () => {fp.viewport["height"]}, configurable: true }});

  // ===== 7. Canvas fingerprint noise =====
  const NOISE_SEED = {fp.canvas_noise_seed};
  function mulberry32(a) {{
    return function() {{
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    }};
  }}
  const noiseRng = mulberry32(NOISE_SEED);

  // Patch toDataURL
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(...args) {{
    const ctx = this.getContext('2d');
    if (ctx && this.width > 0 && this.height > 0) {{
      try {{
        const w = Math.min(this.width, 32);
        const h = Math.min(this.height, 32);
        const imageData = ctx.getImageData(0, 0, w, h);
        for (let i = 0; i < imageData.data.length; i += 4) {{
          imageData.data[i] = (imageData.data[i] + Math.floor((noiseRng() - 0.5) * 4)) & 0xFF;
          imageData.data[i+1] = (imageData.data[i+1] + Math.floor((noiseRng() - 0.5) * 4)) & 0xFF;
        }}
        ctx.putImageData(imageData, 0, 0);
      }} catch(e) {{}}
    }}
    return origToDataURL.apply(this, args);
  }};

  // Patch toBlob
  const origToBlob = HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob = function(callback, ...args) {{
    const ctx = this.getContext('2d');
    if (ctx && this.width > 0 && this.height > 0) {{
      try {{
        const w = Math.min(this.width, 32);
        const h = Math.min(this.height, 32);
        const imageData = ctx.getImageData(0, 0, w, h);
        for (let i = 0; i < imageData.data.length; i += 4) {{
          imageData.data[i + 1] = (imageData.data[i + 1] + Math.floor((noiseRng() - 0.5) * 4)) & 0xFF;
          imageData.data[i + 2] = (imageData.data[i + 2] + Math.floor((noiseRng() - 0.5) * 4)) & 0xFF;
        }}
        ctx.putImageData(imageData, 0, 0);
      }} catch(e) {{}}
    }}
    return origToBlob.call(this, callback, ...args);
  }};

  // Patch getImageData (for direct fingerprinting)
  const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
    const imageData = origGetImageData.apply(this, args);
    if (imageData && imageData.data && imageData.data.length > 0) {{
      // Only perturb small reads (fingerprinting typically reads small areas)
      if (imageData.data.length <= 32 * 32 * 4) {{
        for (let i = 0; i < imageData.data.length; i += 4) {{
          imageData.data[i] = (imageData.data[i] + Math.floor((noiseRng() - 0.5) * 2)) & 0xFF;
        }}
      }}
    }}
    return imageData;
  }};

  // ===== 8. WebGL fingerprint =====
  const getParameterOrig = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(param) {{
    if (param === 0x9245) return {webgl_vendor_js};
    if (param === 0x9246) return {webgl_renderer_js};
    return getParameterOrig.call(this, param);
  }};
  if (typeof WebGL2RenderingContext !== 'undefined') {{
    const getParameter2Orig = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {{
      if (param === 0x9245) return {webgl_vendor_js};
      if (param === 0x9246) return {webgl_renderer_js};
      return getParameter2Orig.call(this, param);
    }};
  }}

  // WebGL getExtension shim (some fingerprinters use this)
  const origGetExtension = WebGLRenderingContext.prototype.getExtension;
  WebGLRenderingContext.prototype.getExtension = function(name) {{
    const ext = origGetExtension.call(this, name);
    if (name === 'WEBGL_debug_renderer_info' && ext) {{
      return new Proxy(ext, {{
        get(target, prop) {{
          if (prop === 'UNMASKED_VENDOR_WEBGL') return 0x9245;
          if (prop === 'UNMASKED_RENDERER_WEBGL') return 0x9246;
          return Reflect.get(target, prop);
        }}
      }});
    }}
    return ext;
  }};

  // ===== 9. AudioContext fingerprint noise =====
  const AUDIO_SEED = {fp.audio_noise_seed};
  const audioRng = mulberry32(AUDIO_SEED);

  const origCreateOscillator = (window.AudioContext || window.webkitAudioContext || function(){{}}).prototype.createOscillator;
  const OrigAudioContext = window.AudioContext || window.webkitAudioContext;

  if (OrigAudioContext) {{
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(channel) {{
      const data = origGetChannelData.call(this, channel);
      // Add tiny noise to audio buffer (changes AudioContext fingerprint)
      if (data && data.length > 0 && data.length <= 44100) {{
        for (let i = 0; i < data.length; i += 100) {{
          data[i] = data[i] + (audioRng() - 0.5) * 0.0001;
        }}
      }}
      return data;
    }};

    // Override sampleRate
    const origSampleRate = Object.getOwnPropertyDescriptor(BaseAudioContext.prototype, 'sampleRate');
    if (origSampleRate) {{
      Object.defineProperty(BaseAudioContext.prototype, 'sampleRate', {{
        get: function() {{
          return {fp.audio_sample_rate};
        }},
        configurable: true,
      }});
    }}
  }}

  // ===== 10. Permissions API =====
  if (typeof Permissions !== 'undefined' && Permissions.prototype.query) {{
    const origQuery = Permissions.prototype.query;
    Permissions.prototype.query = function(params) {{
      if (params && params.name === 'notifications') {{
        return Promise.resolve({{ state: 'prompt', onchange: null }});
      }}
      if (params && params.name === 'midi') {{
        return Promise.resolve({{ state: 'prompt', onchange: null }});
      }}
      return origQuery.call(this, params);
    }};
  }}

  // ===== 11. Connection API =====
  if (navigator.connection) {{
    const connProps = {{
      rtt: {random.choice([50, 75, 100, 150])},
      downlink: {random.choice([5, 7.5, 10, 15, 20, 25])},
      effectiveType: '4g',
      saveData: false,
    }};
    for (const [key, value] of Object.entries(connProps)) {{
      try {{
        Object.defineProperty(navigator.connection, key, {{ get: () => value, configurable: true }});
      }} catch(e) {{}}
    }}
  }}

  // ===== 12. Document visibility =====
  Object.defineProperty(document, 'hidden', {{ get: () => false, configurable: true }});
  Object.defineProperty(document, 'visibilityState', {{ get: () => 'visible', configurable: true }});

  // ===== 13. Battery API — 隐藏或返回正常值 =====
  if (navigator.getBattery) {{
    navigator.getBattery = function() {{
      return Promise.resolve({{
        charging: true,
        chargingTime: 0,
        dischargingTime: Infinity,
        level: 1.0,
        addEventListener: function() {{}},
        removeEventListener: function() {{}},
      }});
    }};
  }}

  // ===== 14. Font fingerprint defense =====
  // 通过覆盖 measureText 添加微小随机偏移
  const origMeasureText = CanvasRenderingContext2D.prototype.measureText;
  CanvasRenderingContext2D.prototype.measureText = function(text) {{
    const metrics = origMeasureText.call(this, text);
    // Wrap in proxy to add noise to width
    return new Proxy(metrics, {{
      get(target, prop) {{
        const val = typeof target[prop] === 'function' ? target[prop].bind(target) : target[prop];
        if (prop === 'width' && typeof val === 'number') {{
          return val + (noiseRng() - 0.5) * 0.1;
        }}
        if (prop === 'actualBoundingBoxRight' && typeof val === 'number') {{
          return val + (noiseRng() - 0.5) * 0.05;
        }}
        return val;
      }}
    }});
  }};

  // ===== 15. Prevent Playwright-specific detection =====
  // Remove __playwright and __pw_ markers
  delete window.__playwright;
  delete window.__pw_manual;
  delete window._playwright;

  // Patch Function.prototype.toString to hide overrides
  const origFuncToString = Function.prototype.toString;
  const nativeToStringSignature = 'function toString() {{ [native code] }}';
  const overrides = new Set([
    HTMLCanvasElement.prototype.toDataURL,
    HTMLCanvasElement.prototype.toBlob,
    CanvasRenderingContext2D.prototype.getImageData,
    CanvasRenderingContext2D.prototype.measureText,
  ]);
  Function.prototype.toString = function() {{
    if (overrides.has(this)) {{
      return `function ${{this.name || ''}}() {{ [native code] }}`;
    }}
    return origFuncToString.call(this);
  }};
  // Make our toString also appear native
  overrides.add(Function.prototype.toString);

  // ===== 16. WebRTC leak prevention =====
  // Prevent local IP leak via WebRTC
  if (window.RTCPeerConnection) {{
    const origRTC = window.RTCPeerConnection;
    window.RTCPeerConnection = function(config, constraints) {{
      if (config && config.iceServers) {{
        config.iceServers = [];
      }}
      return new origRTC(config, constraints);
    }};
    window.RTCPeerConnection.prototype = origRTC.prototype;
  }}

  // ===== 17. Notification API =====
  if (window.Notification) {{
    Object.defineProperty(Notification, 'permission', {{
      get: () => 'default',
      configurable: true,
    }});
  }}

}})();
"""
    return script


# ---------------------------------------------------------------------------
# 便捷函数：一步完成 context 创建 + stealth 注入
# ---------------------------------------------------------------------------


def apply_fingerprint_to_context(context: Any, fp: BrowserFingerprint) -> None:
    """将 stealth init script 注入到已有的 browser context。"""
    add_init_script = getattr(context, "add_init_script", None)
    if callable(add_init_script):
        add_init_script(script=get_stealth_init_script(fp))
