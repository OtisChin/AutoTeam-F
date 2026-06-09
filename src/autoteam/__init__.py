"""Backward-compatible import alias for the renamed ``autotoken`` package."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys

_REORGANIZED_SUBMODULE_ALIASES = {
    "account_hub": "autotoken.integrations.account_hub",
    "account_ops": "autotoken.storage.account_ops",
    "accounts": "autotoken.storage.accounts",
    "admin_state": "autotoken.settings.admin_state",
    "api": "autotoken.interfaces.api",
    "auth_index": "autotoken.storage.auth_index",
    "auth_prompts": "autotoken.auth.auth_prompts",
    "auth_session_store": "autotoken.storage.auth_session_store",
    "auth_storage": "autotoken.storage.auth_storage",
    "bind_audit": "autotoken.payments.bind_audit",
    "bind_executor": "autotoken.payments.bind_executor",
    "browser_fingerprint": "autotoken.core.browser_fingerprint",
    "cancel_signal": "autotoken.core.cancel_signal",
    "card_pool": "autotoken.payments.card_pool",
    "chatgpt_api": "autotoken.integrations.chatgpt_api",
    "cli": "autotoken.interfaces.cli",
    "cloudmail": "autotoken.mail",
    "codex_auth": "autotoken.auth.codex_auth",
    "config": "autotoken.settings.config",
    "cpa_sync": "autotoken.integrations.cpa_sync",
    "display": "autotoken.core.display",
    "gopay_appium": "autotoken.payments.gopay_appium",
    "gopay_auto_register": "autotoken.payments.gopay_auto_register",
    "gopay_executor": "autotoken.payments.gopay_executor",
    "identity": "autotoken.core.identity",
    "invite": "autotoken.auth.invite",
    "manager": "autotoken.interfaces.manager",
    "manual_account": "autotoken.auth.manual_account",
    "oauth_phone_pool": "autotoken.auth.oauth_phone_pool",
    "oauth_phone_records": "autotoken.auth.oauth_phone_records",
    "paths": "autotoken.core.paths",
    "paypal_bind_executor": "autotoken.payments.paypal_bind_executor",
    "paypal_protocol_signup": "autotoken.payments.paypal_protocol_signup",
    "protocol_register": "autotoken.auth.protocol_register",
    "proxy_bridge": "autotoken.integrations.proxy_bridge",
    "register_failures": "autotoken.storage.register_failures",
    "rekberinaja": "autotoken.integrations.rekberinaja",
    "roxybrowser_client": "autotoken.integrations.roxybrowser_client",
    "runtime_config": "autotoken.settings.runtime_config",
    "session_cpa_converter": "autotoken.integrations.session_cpa_converter",
    "setup_wizard": "autotoken.settings.setup_wizard",
    "sqlite_store": "autotoken.storage.sqlite_store",
    "sub2api_converter": "autotoken.integrations.sub2api_converter",
    "textio": "autotoken.core.textio",
    "trade": "autotoken.commerce.trade",
    "whatsapp_otp": "autotoken.payments.whatsapp_otp",
}


class _AutoteamAliasLoader(importlib.abc.Loader):
    def __init__(self, fullname: str, canonical_name: str):
        self.fullname = fullname
        self.canonical_name = canonical_name
        self._canonical_metadata = {}

    def create_module(self, spec):
        module = importlib.import_module(self.canonical_name)
        self._canonical_metadata = {
            "__name__": getattr(module, "__name__", self.canonical_name),
            "__loader__": getattr(module, "__loader__", None),
            "__package__": getattr(module, "__package__", None),
            "__spec__": getattr(module, "__spec__", None),
            "__path__": getattr(module, "__path__", None),
        }
        sys.modules[self.fullname] = module
        return module

    def exec_module(self, module) -> None:
        for attr, value in self._canonical_metadata.items():
            if value is not None:
                setattr(module, attr, value)
        return None


class _AutoteamAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        if not fullname.startswith("autoteam."):
            return None
        if fullname == "autoteam.__main__":
            return None
        legacy_suffix = fullname[len("autoteam.") :]
        canonical_name = _REORGANIZED_SUBMODULE_ALIASES.get(legacy_suffix, "autotoken." + legacy_suffix)
        canonical_spec = importlib.util.find_spec(canonical_name)
        if canonical_spec is None:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            _AutoteamAliasLoader(fullname, canonical_name),
            origin=canonical_spec.origin,
            is_package=canonical_spec.submodule_search_locations is not None,
        )


if not any(isinstance(finder, _AutoteamAliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _AutoteamAliasFinder())

_autotoken = importlib.import_module("autotoken")
sys.modules[__name__] = _autotoken
