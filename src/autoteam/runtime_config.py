"""运行时可变配置（由面板写入，重启后仍生效）。

与 admin_state.py 区分：admin_state 只放管理员登录态（session/password/...），白名单字段严格；
本模块放"用户在面板里可以调的业务配置"，目前只有 register_domain（子号注册用的临时邮箱域名），
将来可以扩 batch_size、cool_down 等。持久化到项目根 `runtime_config.json`。
"""

import json
import logging
import os
import re
import threading
import time

from autoteam.paths import PROJECT_ROOT
from autoteam.textio import read_text, write_text

logger = logging.getLogger(__name__)

RUNTIME_CONFIG_FILE = PROJECT_ROOT / "runtime_config.json"
RUNTIME_CONFIG_MODE = 0o666

_LOCK = threading.Lock()


def _load():
    if not RUNTIME_CONFIG_FILE.exists():
        return {}
    try:
        raw = read_text(RUNTIME_CONFIG_FILE).strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        # 静默吞会把用户在面板里设的 register_domain 等覆盖值丢掉,下一轮 _save 会把
        # 损坏文件写回空 dict。保留一份 .corrupt-<ts>.json 便于事后排查。
        corrupt_path = RUNTIME_CONFIG_FILE.with_suffix(f".corrupt-{int(time.time())}.json")
        try:
            RUNTIME_CONFIG_FILE.rename(corrupt_path)
            logger.error("[runtime_config] 解析失败, 已保留原文件为 %s: %s", corrupt_path.name, exc)
        except Exception as rename_exc:
            logger.error("[runtime_config] 解析失败且无法重命名 (%s): %s", exc, rename_exc)
        return {}


def _save(data):
    target = RUNTIME_CONFIG_FILE.resolve()
    write_text(target, json.dumps(data, indent=2, ensure_ascii=False))
    try:
        os.chmod(target, RUNTIME_CONFIG_MODE)
    except Exception:
        pass


def get(key, default=None):
    with _LOCK:
        return _load().get(key, default)


def set_value(key, value):
    with _LOCK:
        data = _load()
        data[key] = value
        _save(data)
        return data


def get_register_domain():
    """返回用于子号注册的临时邮箱域名。

    优先级：runtime_config.json 的 register_domain → register_domains[0] →
    环境变量 CLOUD_MAIL_DOMAIN / CLOUDFLARE_TEMP_EMAIL_DOMAIN（向后兼容）。
    返回值已 lstrip "@"。
    """
    from autoteam.config import CLOUD_MAIL_DOMAIN, CLOUDFLARE_TEMP_EMAIL_DOMAIN

    override = (get("register_domain") or "").strip()
    if override:
        return override.lstrip("@").strip()
    domains = get_register_domains()
    if domains:
        return domains[0]
    return (CLOUD_MAIL_DOMAIN or CLOUDFLARE_TEMP_EMAIL_DOMAIN or "").lstrip("@").strip()


def set_register_domain(domain):
    """写入 register_domain 覆盖值。空串表示清除 override 走环境变量。"""
    cleaned = (domain or "").strip().lstrip("@").strip()
    set_value("register_domain", cleaned)
    return cleaned


def _normalize_domain(domain):
    return (domain or "").strip().lstrip("@").strip()


def _split_domains(raw):
    if isinstance(raw, list):
        values = raw
    else:
        values = re.split(r"[\s,;|]+", str(raw or ""))

    out = []
    seen = set()
    for value in values:
        cleaned = _normalize_domain(value)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
    return out


def get_register_domains():
    """返回可用于子号注册的域名列表。

    支持 runtime_config.json 的 register_domains 数组 / 字符串，以及环境变量里
    逗号、空格、分号分隔的多域名写法。
    """
    from autoteam.config import CLOUD_MAIL_DOMAIN, CLOUDFLARE_TEMP_EMAIL_DOMAIN

    runtime_domains = _split_domains(get("register_domains"))
    if runtime_domains:
        return runtime_domains

    return _split_domains(CLOUD_MAIL_DOMAIN or CLOUDFLARE_TEMP_EMAIL_DOMAIN or "")


def set_register_domains(domains):
    """写入可选注册域名列表，返回清洗后的唯一域名列表。"""
    cleaned = _split_domains(domains)
    set_value("register_domains", cleaned)

    current = _normalize_domain(get("register_domain"))
    if current and current not in cleaned:
        set_value("register_domain", cleaned[0] if cleaned else "")

    return cleaned
