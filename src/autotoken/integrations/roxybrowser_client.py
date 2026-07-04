"""Minimal RoxyBrowser API client used to launch browser-backed tasks."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

import requests

from autotoken.settings.config import normalize_proxy_url

logger = logging.getLogger(__name__)

_RESERVED_PROFILE_LOCK = threading.RLock()
_RESERVED_PROFILE_IDS: set[str] = set()
DEFAULT_ROXYBROWSER_OS = "Windows"
DEFAULT_ROXYBROWSER_OS_VERSION = "10"
PROJECT_WINDOW_NAME_PREFIX = "autotoken-"


def _normalize_api_host(api_host: str | None) -> str:
    raw = str(api_host or "").strip().rstrip("/")
    if not raw:
        raw = "http://127.0.0.1:50000"
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.port is None:
        raise ValueError("RoxyBrowser API host 格式无效，请使用 http://127.0.0.1:50000")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}:{parsed.port}"


def _safe_text_excerpt(text: str, limit: int = 240) -> str:
    excerpt = str(text or "").strip().replace("\n", " ")
    return excerpt[:limit]


def _response_excerpt(resp: requests.Response) -> str:
    try:
        return _safe_text_excerpt(resp.text)
    except Exception:
        return ""


def _find_first_mapping(payload: Any, required_keys: tuple[str, ...]) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        if all(key in payload for key in required_keys):
            return payload
        for value in payload.values():
            found = _find_first_mapping(value, required_keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_first_mapping(item, required_keys)
            if found:
                return found
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("rows", "list", "data", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    for key in ("rows", "list", "data", "items"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _extract_total(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = [payload.get("total")]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("total"))
    for value in candidates:
        try:
            total = int(value)
        except Exception:
            continue
        if total >= 0:
            return total
    return None


def _extract_data_dict(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _extract_dir_id(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("dirId", "dir_id", "id", "browserId"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("dirId", "dir_id", "id", "browserId"):
                value = data.get(key)
                if value not in (None, ""):
                    return str(value).strip()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    value = _extract_dir_id(item)
                    if value:
                        return value
    return ""


def _extract_connection_mapping(payload: Any) -> dict[str, Any] | None:
    return _find_first_mapping(payload, ("ws", "http")) or _find_first_mapping(
        payload,
        ("webSocketDebuggerUrl",),
    )


def _roxybrowser_window_quota_insufficient(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return any(
        marker in text
        for marker in (
            "窗口额度不足",
            "window quota",
            "profile quota",
            "insufficient quota",
            "quota insufficient",
            "limit exceeded",
        )
    )


def _row_open_status(row: dict[str, Any]) -> bool:
    for key in ("openStatus", "open_status", "isOpen", "opened", "running"):
        if key not in row:
            continue
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "open", "opened", "running", "run"}:
            return True
        if text in {"0", "false", "no", "close", "closed", "stop", "stopped"}:
            return False
    for key in ("status", "browserStatus", "browser_status"):
        text = str(row.get(key) or "").strip().lower()
        if text in {"open", "opened", "running", "run"}:
            return True
        if text in {"close", "closed", "stop", "stopped"}:
            return False
    return False


def _is_project_managed_profile(profile: dict[str, Any]) -> bool:
    name = str(profile.get("window_name") or profile.get("name") or "").strip().lower()
    return name.startswith(PROJECT_WINDOW_NAME_PREFIX)


def _normalize_proxy_info(proxy_url: str | None) -> dict[str, Any] | None:
    raw = str(proxy_url or "").strip()
    if not raw:
        return None
    normalized = normalize_proxy_url(raw, default_auth_scheme="socks5h")
    parsed = urlsplit(normalized)
    if not parsed.hostname or parsed.port is None:
        raise ValueError("RoxyBrowser 代理 URL 格式无效")
    host = parsed.hostname
    ip_type = "IPV6" if ":" in host else "IPV4"
    if parsed.scheme in {"socks5", "socks5h"}:
        category = "SOCKS5"
    elif parsed.scheme == "https":
        category = "HTTPS"
    else:
        category = "HTTP"
    proxy_info: dict[str, Any] = {
        "moduleId": 0,
        "proxyMethod": "custom",
        "proxyCategory": category,
        "protocol": category,
        "ipType": ip_type,
        "host": host,
        "port": int(parsed.port),
    }
    if parsed.username:
        proxy_info["proxyUserName"] = unquote(parsed.username)
    if parsed.password:
        proxy_info["proxyPassword"] = unquote(parsed.password)
    return proxy_info


def _coerce_workspace_id(value: str | int) -> int | str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    try:
        return int(raw)
    except Exception:
        return raw


def _default_roxybrowser_fingerprint() -> dict[str, str]:
    os_name = str(os.environ.get("ROXYBROWSER_DEFAULT_OS") or DEFAULT_ROXYBROWSER_OS).strip()
    os_version = str(os.environ.get("ROXYBROWSER_DEFAULT_OS_VERSION") or DEFAULT_ROXYBROWSER_OS_VERSION).strip()
    result: dict[str, str] = {}
    if os_name:
        result["os"] = os_name
    if os_version:
        result["osVersion"] = os_version
    return result


@dataclass(slots=True)
class RoxyBrowserLaunchResult:
    workspace_id: str
    dir_id: str
    connection: dict[str, Any]
    created_profile: bool
    reused_existing_profile: bool = False
    requested_os: str = ""
    requested_os_version: str = ""


class RoxyBrowserClient:
    def __init__(
        self,
        api_host: str | None = None,
        token: str | None = None,
        *,
        timeout: int = 30,
    ) -> None:
        self.api_host = _normalize_api_host(api_host)
        self.token = str(token or "").strip()
        if not self.token:
            raise ValueError("RoxyBrowser API token is required (set ROXYBROWSER_API_TOKEN)")
        self.timeout = max(1, int(timeout or 30))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "token": self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.api_host}{path}"
        resp = self.session.request(
            method.upper(),
            url,
            params=params,
            json=json_body,
            timeout=timeout or self.timeout,
        )
        if not resp.ok:
            raise RuntimeError(
                f"RoxyBrowser API {path} HTTP {resp.status_code}: {_response_excerpt(resp)}"
            )
        try:
            payload = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"RoxyBrowser API {path} 返回非 JSON 响应: {_response_excerpt(resp)}"
            ) from exc
        if isinstance(payload, dict) and "code" in payload and payload.get("code") not in (0, "0", None):
            raise RuntimeError(str(payload.get("msg") or payload.get("message") or f"RoxyBrowser API {path} 失败"))
        return payload if isinstance(payload, dict) else {"data": payload}

    def workspace_list(self, *, page_index: int = 1, page_size: int = 100) -> dict[str, Any]:
        return self._request(
            "GET",
            "/browser/workspace",
            params={"page_index": max(1, int(page_index or 1)), "page_size": max(1, int(page_size or 100))},
        )

    def profile_list(self, *, workspace_id: str | int, page_index: int = 1, page_size: int = 100) -> dict[str, Any]:
        return self._request(
            "GET",
            "/browser/list_v3",
            params={
                "workspaceId": _coerce_workspace_id(workspace_id),
                "page_index": max(1, int(page_index or 1)),
                "page_size": max(1, int(page_size or 100)),
            },
        )

    def list_workspaces(self) -> list[dict[str, str]]:
        rows: list[dict[str, Any]] = []
        page_index = 1
        page_size = 100
        total: int | None = None
        while True:
            payload = self.workspace_list(page_index=page_index, page_size=page_size)
            page_rows = _extract_rows(payload)
            rows.extend(page_rows)
            total = _extract_total(payload) if total is None else total
            if not page_rows:
                break
            if total is not None and len(rows) >= total:
                break
            if len(page_rows) < page_size:
                break
            page_index += 1
        workspaces: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for row in rows:
            workspace_id = next(
                (
                    str(row.get(key) or "").strip()
                    for key in ("workspaceId", "workspace_id", "id")
                    if str(row.get(key) or "").strip()
                ),
                "",
            )
            if not workspace_id:
                continue
            if workspace_id in seen_ids:
                continue
            seen_ids.add(workspace_id)
            name = next(
                (
                    str(row.get(key) or "").strip()
                    for key in ("workspaceName", "workspace_name", "windowName", "name", "title")
                    if str(row.get(key) or "").strip()
                ),
                f"Workspace {workspace_id}",
            )
            workspaces.append({"id": workspace_id, "name": name})
        return workspaces

    def list_profiles(self, workspace_id: str | int | None = None) -> list[dict[str, Any]]:
        resolved_workspace_id = str(workspace_id or "").strip()
        if not resolved_workspace_id:
            raise RuntimeError("列出窗口需要 workspace_id")
        rows: list[dict[str, Any]] = []
        page_index = 1
        page_size = 100
        total: int | None = None
        while True:
            payload = self.profile_list(workspace_id=resolved_workspace_id, page_index=page_index, page_size=page_size)
            data = _extract_data_dict(payload) or {}
            page_rows = _extract_rows(payload)
            rows.extend(page_rows)
            if total is None:
                total = _extract_total(payload)
                if total is None:
                    total = _extract_total(data)
            if not page_rows:
                break
            if total is not None and len(rows) >= total:
                break
            if len(page_rows) < page_size:
                break
            page_index += 1
        profiles: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in rows:
            dir_id = next(
                (
                    str(row.get(key) or "").strip()
                    for key in ("dirId", "dir_id", "id", "browserId")
                    if str(row.get(key) or "").strip()
                ),
                "",
            )
            if not dir_id or dir_id in seen_ids:
                continue
            seen_ids.add(dir_id)
            name = next(
                (
                    str(row.get(key) or "").strip()
                    for key in ("windowName", "window_name", "name", "title", "windowRemark", "remark")
                    if str(row.get(key) or "").strip()
                ),
                f"Window {dir_id}",
            )
            workspace_label = next(
                (
                    str(row.get(key) or "").strip()
                    for key in ("workspaceName", "workspace_name", "projectName")
                    if str(row.get(key) or "").strip()
                ),
                "",
            )
            label = f"{name}"
            if workspace_label and workspace_label not in name:
                label = f"{name} · {workspace_label}"
            profiles.append(
                {
                    "id": dir_id,
                    "name": label,
                    "window_name": name,
                    "workspace_id": resolved_workspace_id,
                    "open_status": _row_open_status(row),
                }
            )
        return profiles

    def list_all_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for workspace in self.list_workspaces():
            workspace_id = workspace["id"]
            workspace_name = workspace.get("name") or workspace_id
            for profile in self.list_profiles(workspace_id):
                profile_id = profile["id"]
                if profile_id in seen_ids:
                    continue
                seen_ids.add(profile_id)
                profiles.append(
                    {
                        **profile,
                        "workspace_id": workspace_id,
                        "workspace_name": workspace_name,
                    }
                )
        return profiles

    def reserve_available_profile(self, workspace_id: str | int) -> dict[str, Any] | None:
        resolved_workspace_id = str(workspace_id or "").strip()
        if not resolved_workspace_id:
            return None
        with _RESERVED_PROFILE_LOCK:
            for profile in self.list_profiles(resolved_workspace_id):
                profile_id = str(profile.get("id") or "").strip()
                if not profile_id or profile_id in _RESERVED_PROFILE_IDS:
                    continue
                if bool(profile.get("open_status")):
                    continue
                _RESERVED_PROFILE_IDS.add(profile_id)
                return profile
        return None

    def release_profile_reservation(self, dir_id: str | None) -> None:
        profile_id = str(dir_id or "").strip()
        if not profile_id:
            return
        with _RESERVED_PROFILE_LOCK:
            _RESERVED_PROFILE_IDS.discard(profile_id)

    def resolve_workspace_id(self, workspace_id: str | int | None = None) -> str:
        explicit = str(workspace_id or "").strip()
        if explicit:
            return explicit
        workspaces = self.list_workspaces()
        if not workspaces:
            raise RuntimeError("未找到可用的 RoxyBrowser workspace；请先在客户端创建工作空间")
        return workspaces[0]["id"]

    def resolve_profile(self, profile_id: str | int | None = None, workspace_id: str | int | None = None) -> tuple[str, str]:
        explicit_profile_id = str(profile_id or "").strip()
        resolved_workspace_id = str(workspace_id or "").strip()
        if explicit_profile_id:
            if resolved_workspace_id:
                return resolved_workspace_id, explicit_profile_id
            workspaces = self.list_workspaces()
            for workspace in workspaces:
                candidate_profiles = self.list_profiles(workspace["id"])
                if any(profile["id"] == explicit_profile_id for profile in candidate_profiles):
                    return workspace["id"], explicit_profile_id
            raise RuntimeError("未找到指定的 RoxyBrowser 窗口，请刷新列表后重新选择")
        resolved_workspace_id = self.resolve_workspace_id(resolved_workspace_id or None)
        profiles = self.list_profiles(resolved_workspace_id)
        if not profiles:
            raise RuntimeError("未找到可用的 RoxyBrowser 窗口；请先在客户端创建窗口")
        return resolved_workspace_id, profiles[0]["id"]

    def browser_create(
        self,
        *,
        workspace_id: str,
        window_name: str,
        proxy_url: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "workspaceId": _coerce_workspace_id(workspace_id),
            "windowName": window_name,
        }
        payload.update(_default_roxybrowser_fingerprint())
        proxy_info = _normalize_proxy_info(proxy_url)
        if proxy_info:
            payload["proxyInfo"] = proxy_info
        payload["fingerInfo"] = {
            "clearCacheFile": False,
            "clearCookie": False,
            "clearHistory": False,
            "randomFingerprint": True,
            "syncTab": False,
            "syncCookie": False,
            "portScanProtect": False,
        }
        return self._request("POST", "/browser/create", json_body=payload)

    def browser_mdf(
        self,
        *,
        workspace_id: str,
        dir_id: str,
        window_name: str | None = None,
        proxy_url: str | None = None,
        apply_default_fingerprint: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "workspaceId": _coerce_workspace_id(workspace_id),
            "dirId": dir_id,
        }
        if apply_default_fingerprint:
            payload.update(_default_roxybrowser_fingerprint())
        if window_name:
            payload["windowName"] = window_name
        proxy_info = _normalize_proxy_info(proxy_url)
        if proxy_info:
            payload["proxyInfo"] = proxy_info
        return self._request("POST", "/browser/mdf", json_body=payload)

    def browser_open(
        self,
        dir_id: str,
        *,
        workspace_id: str | int | None = None,
        args: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"dirId": dir_id, "args": list(args or [])}
        if workspace_id not in (None, ""):
            payload["workspaceId"] = _coerce_workspace_id(workspace_id)
        return self._request("POST", "/browser/open", json_body=payload)

    def browser_close(self, dir_id: str, *, release_reservation: bool = True) -> dict[str, Any]:
        try:
            return self._request("POST", "/browser/close", json_body={"dirId": dir_id})
        finally:
            if release_reservation:
                self.release_profile_reservation(dir_id)

    def browser_clear_local_cache(self, dir_ids: list[str]) -> dict[str, Any]:
        clean_dir_ids = [str(dir_id).strip() for dir_id in dir_ids if str(dir_id).strip()]
        if not clean_dir_ids:
            raise ValueError("RoxyBrowser 清理缓存需要 dirId")
        return self._request("POST", "/browser/clear_local_cache", json_body={"dirIds": clean_dir_ids})

    def browser_clear_server_cache(self, workspace_id: str | int, dir_ids: list[str]) -> dict[str, Any]:
        clean_dir_ids = [str(dir_id).strip() for dir_id in dir_ids if str(dir_id).strip()]
        if not clean_dir_ids:
            raise ValueError("RoxyBrowser 清理缓存需要 dirId")
        return self._request(
            "POST",
            "/browser/clear_server_cache",
            json_body={"workspaceId": _coerce_workspace_id(workspace_id), "dirIds": clean_dir_ids},
        )

    def clear_profile_cache(self, workspace_id: str | int, dir_ids: list[str]) -> None:
        clean_dir_ids = [str(dir_id).strip() for dir_id in dir_ids if str(dir_id).strip()]
        if not clean_dir_ids:
            return
        self.browser_clear_local_cache(clean_dir_ids)
        self.browser_clear_server_cache(workspace_id, clean_dir_ids)
        logger.info(
            "RoxyBrowser profile data cleared: workspace_id=%s dir_ids=%s",
            workspace_id,
            ",".join(clean_dir_ids),
        )

    def browser_delete(self, workspace_id: str, dir_ids: list[str]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/browser/delete",
            json_body={"workspaceId": _coerce_workspace_id(workspace_id), "dirIds": dir_ids},
        )

    def cleanup_project_profiles_for_quota(self, workspace_id: str | int) -> list[str]:
        """Delete every unreserved profile created by this project to free window slots."""
        resolved_workspace_id = str(workspace_id or "").strip()
        if not resolved_workspace_id:
            return []
        reserved_for_cleanup: list[str] = []
        with _RESERVED_PROFILE_LOCK:
            for profile in self.list_profiles(resolved_workspace_id):
                dir_id = str(profile.get("id") or "").strip()
                if not dir_id or dir_id in _RESERVED_PROFILE_IDS:
                    continue
                if not _is_project_managed_profile(profile):
                    continue
                _RESERVED_PROFILE_IDS.add(dir_id)
                reserved_for_cleanup.append(dir_id)
        if not reserved_for_cleanup:
            return []
        deleted_dir_ids: list[str] = []
        try:
            for dir_id in reserved_for_cleanup:
                try:
                    self.browser_close(dir_id, release_reservation=False)
                except Exception:
                    pass
            self.browser_delete(resolved_workspace_id, reserved_for_cleanup)
            deleted_dir_ids = list(reserved_for_cleanup)
            logger.info(
                "RoxyBrowser deleted project-created profiles after create quota failure: workspace_id=%s dir_ids=%s",
                resolved_workspace_id,
                ",".join(deleted_dir_ids),
            )
            return deleted_dir_ids
        finally:
            for dir_id in reserved_for_cleanup:
                self.release_profile_reservation(dir_id)

    def browser_connection_info(self, dir_ids: list[str] | None = None) -> dict[str, Any]:
        params = {}
        if dir_ids:
            params["dirIds"] = ",".join(str(dir_id).strip() for dir_id in dir_ids if str(dir_id).strip())
        return self._request("GET", "/browser/connection_info", params=params or None)

    def launch(
        self,
        *,
        window_name: str | None = None,
        proxy_url: str | None = None,
        workspace_id: str | int | None = None,
        dir_id: str | None = None,
        args: list[str] | None = None,
        clear_profile_data: bool = False,
        force_new_profile: bool = False,
    ) -> RoxyBrowserLaunchResult:
        resolved_dir_id = str(dir_id or "").strip()
        reserved_profile_id = ""
        requested_fingerprint = _default_roxybrowser_fingerprint()
        if resolved_dir_id:
            resolved_workspace_id = self.resolve_profile(resolved_dir_id, workspace_id)[0]
        else:
            resolved_workspace_id = self.resolve_workspace_id(workspace_id)
        created_profile = False
        reused_existing_profile = False
        launch_name = window_name or f"autotoken-{uuid.uuid4().hex[:8]}"
        try:
            if resolved_dir_id:
                if clear_profile_data:
                    try:
                        self.browser_close(resolved_dir_id)
                    except Exception:
                        pass
                    self.clear_profile_cache(resolved_workspace_id, [resolved_dir_id])
                if str(proxy_url or "").strip() or _default_roxybrowser_fingerprint():
                    self.browser_mdf(
                        workspace_id=resolved_workspace_id,
                        dir_id=resolved_dir_id,
                        proxy_url=proxy_url,
                    )
            else:
                with _RESERVED_PROFILE_LOCK:
                    reusable_profile = None if force_new_profile else self.reserve_available_profile(resolved_workspace_id)
                    if reusable_profile:
                        resolved_dir_id = str(reusable_profile.get("id") or "").strip()
                        reserved_profile_id = resolved_dir_id
                        reused_existing_profile = True
                        logger.info(
                            "RoxyBrowser reusing idle profile before creating new one: workspace_id=%s dir_id=%s",
                            resolved_workspace_id,
                            resolved_dir_id,
                        )
                        if clear_profile_data:
                            try:
                                self.browser_close(resolved_dir_id, release_reservation=False)
                            except Exception:
                                pass
                            self.clear_profile_cache(resolved_workspace_id, [resolved_dir_id])
                        if str(proxy_url or "").strip() or _default_roxybrowser_fingerprint():
                            self.browser_mdf(
                                workspace_id=resolved_workspace_id,
                                dir_id=resolved_dir_id,
                                proxy_url=proxy_url,
                            )
                    else:
                        try:
                            created = self.browser_create(
                                workspace_id=resolved_workspace_id,
                                window_name=launch_name,
                                proxy_url=proxy_url,
                            )
                            resolved_dir_id = _extract_dir_id(created)
                            if not resolved_dir_id:
                                raise RuntimeError("RoxyBrowser browser_create 未返回 dirId")
                            created_profile = True
                            reserved_profile_id = resolved_dir_id
                            _RESERVED_PROFILE_IDS.add(resolved_dir_id)
                        except Exception as exc:
                            if not _roxybrowser_window_quota_insufficient(exc):
                                raise
                            cleaned_dir_ids = self.cleanup_project_profiles_for_quota(resolved_workspace_id)
                            if not cleaned_dir_ids:
                                raise RuntimeError(
                                    "RoxyBrowser 没有可清理的本项目窗口，且新建窗口额度不足；请关闭空闲窗口、提高窗口额度，或改用指定窗口"
                                ) from exc
                            try:
                                created = self.browser_create(
                                    workspace_id=resolved_workspace_id,
                                    window_name=launch_name,
                                    proxy_url=proxy_url,
                                )
                                resolved_dir_id = _extract_dir_id(created)
                                if not resolved_dir_id:
                                    raise RuntimeError("RoxyBrowser browser_create 未返回 dirId")
                                created_profile = True
                                reserved_profile_id = resolved_dir_id
                                _RESERVED_PROFILE_IDS.add(resolved_dir_id)
                            except Exception as retry_exc:
                                if _roxybrowser_window_quota_insufficient(retry_exc):
                                    raise RuntimeError(
                                        f"RoxyBrowser 已自动清理 {len(cleaned_dir_ids)} 个本项目窗口，但新建窗口额度仍不足；请关闭更多空闲窗口或提高窗口额度"
                                    ) from retry_exc
                                raise

            open_result = self.browser_open(resolved_dir_id, workspace_id=resolved_workspace_id, args=args or [])
            connection = _extract_connection_mapping(open_result) or {}
            if not connection:
                # open 返回值里没有连接信息时，再查一次 connection_info。
                for _ in range(10):
                    info_payload = self.browser_connection_info([resolved_dir_id])
                    connection = _extract_connection_mapping(info_payload) or {}
                    if connection:
                        break
                    time.sleep(0.5)
            if not connection:
                raise RuntimeError("RoxyBrowser 未返回可用的调试连接信息")
            return RoxyBrowserLaunchResult(
                workspace_id=resolved_workspace_id,
                dir_id=resolved_dir_id,
                connection=connection,
                created_profile=created_profile,
                reused_existing_profile=reused_existing_profile,
                requested_os=str(requested_fingerprint.get("os") or ""),
                requested_os_version=str(requested_fingerprint.get("osVersion") or ""),
            )
        except Exception:
            if reserved_profile_id:
                self.release_profile_reservation(reserved_profile_id)
            if created_profile and resolved_workspace_id and resolved_dir_id:
                try:
                    self.browser_close(resolved_dir_id)
                except Exception:
                    pass
                try:
                    self.browser_delete(resolved_workspace_id, [resolved_dir_id])
                except Exception:
                    pass
            raise


def pick_roxybrowser_endpoint(connection: dict[str, Any]) -> str:
    ws = str(connection.get("ws") or connection.get("webSocketDebuggerUrl") or "").strip()
    http = str(connection.get("http") or connection.get("httpUrl") or "").strip()
    if http:
        if "://" not in http:
            http = f"http://{http}"
        return http
    if ws:
        return ws
    raise RuntimeError("RoxyBrowser connection info 缺少 ws/http endpoint")
