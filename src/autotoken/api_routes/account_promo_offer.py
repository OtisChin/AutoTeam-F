"""Dashboard promo/trial payment-method check task routes."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.api_routes.account_overview import normalize_chatgpt_trial_eligibility, query_chatgpt_account_check
from autotoken.services import proxy_runtime
from autotoken.services.promo_offer_check import (
    PROMO_PAYMENT_ROUTES,
    detect_promo_payment_method,
    promo_payment_method_options,
    route_for_promo_method,
)
from autotoken.storage.auth_files import read_auth_json_file, trusted_auth_or_session_path


class PromoOfferCheckParams(BaseModel):
    emails: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    proxy_url: str = Field("", validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_api_provider: str = Field("cliproxy", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_api_enabled: bool = Field(True, validation_alias=AliasChoices("proxy_api_enabled", "proxyApiEnabled"))
    concurrency: int = 4
    verify_proxy_country: bool = Field(True, validation_alias=AliasChoices("verify_proxy_country", "verifyProxyCountry"))


def _extract_access_token(auth_data: dict[str, Any]) -> str:
    data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
    return str(
        auth_data.get("access_token", "")
        or auth_data.get("accessToken", "")
        or auth_data.get("chatgpt_access_token", "")
        or data.get("access_token", "")
        or data.get("accessToken", "")
        or data.get("chatgpt_access_token", "")
        or ""
    ).strip()


def _extract_account_id(auth_data: dict[str, Any]) -> str:
    account = auth_data.get("account") if isinstance(auth_data.get("account"), dict) else {}
    data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
    data_account = data.get("account") if isinstance(data.get("account"), dict) else {}
    return str(
        auth_data.get("account_id", "")
        or auth_data.get("accountId", "")
        or account.get("id")
        or data.get("account_id", "")
        or data.get("accountId", "")
        or data_account.get("id")
        or ""
    ).strip()


def _extract_device_id(auth_data: dict[str, Any], email: str) -> str:
    data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
    return str(
        auth_data.get("device_id")
        or auth_data.get("deviceId")
        or data.get("device_id")
        or data.get("deviceId")
        or uuid.uuid5(uuid.NAMESPACE_DNS, f"autoteam-promo-check:{email}")
    ).strip()


def _extract_session_cookie(auth_data: dict[str, Any]) -> str:
    data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
    return str(
        auth_data.get("cookie_header")
        or auth_data.get("cookieHeader")
        or auth_data.get("session_cookie")
        or auth_data.get("sessionCookie")
        or data.get("cookie_header")
        or data.get("cookieHeader")
        or data.get("session_cookie")
        or data.get("sessionCookie")
        or ""
    ).strip()


def _clean_methods(methods: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in methods or []:
        route = route_for_promo_method(item)
        if route and route.method not in seen:
            seen.add(route.method)
            cleaned.append(route.method)
    return cleaned


def _route_summary(route_result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "method": str(route_result.get("method") or ""),
        "country": str(route_result.get("country") or ""),
        "currency": str(route_result.get("currency") or ""),
        "locale": str(route_result.get("locale") or ""),
        "label": str(route_result.get("label") or ""),
        "status": str(route_result.get("status") or "unknown"),
        "state": str(route_result.get("state") or ""),
        "methods": [str(item) for item in (route_result.get("methods") or []) if str(item or "").strip()],
        "checked_at": route_result.get("checked_at") or time.time(),
        "exit": str(route_result.get("exit") or ""),
        "http_status": int(route_result.get("http_status") or 0),
        "session_type": str(route_result.get("session_type") or ""),
    }
    if route_result.get("error"):
        summary["error"] = str(route_result.get("error") or "")[:300]
    if route_result.get("amount_minor") is not None:
        summary["amount_minor"] = route_result.get("amount_minor")
    if route_result.get("amount_currency"):
        summary["amount_currency"] = route_result.get("amount_currency")
    return summary


def _aggregate_method_status(routes: list[dict[str, Any]]) -> tuple[str, str]:
    if any(route.get("status") == "available" for route in routes):
        incomplete = any(route.get("status") not in {"available", "not_returned"} for route in routes)
        return ("partial", "partial") if incomplete else ("available", "payment_methods_available")
    if any(route.get("status") == "token_invalid" for route in routes):
        return "token_invalid", "token_invalid"
    if any(route.get("status") == "already_paid" for route in routes):
        return "already_paid", "already_paid"
    if routes and all(route.get("status") == "not_returned" for route in routes):
        return "not_returned", "payment_methods_empty"
    if routes:
        last = routes[-1]
        return str(last.get("status") or "unknown"), str(last.get("state") or "unknown")
    return "disabled", "no_methods"


def _build_proxy_selector_for_country(params: PromoOfferCheckParams, country: str) -> tuple[Callable[[], str], dict[str, Any]]:
    provider = proxy_runtime.normalize_proxy_api_provider(params.proxy_api_provider or "cliproxy")
    api_url = str(params.proxy_api_url or "").strip()
    if params.proxy_api_enabled:
        if api_url:
            api_url = proxy_runtime.proxy_api_url_with_region(api_url, country)
        else:
            api_url = proxy_runtime.default_proxy_api_url(provider, country=country)
    else:
        api_url = ""
    pool_values = proxy_runtime.parse_proxy_pool_values(params.proxy_pool, params.proxy_pool_text)
    routed_pool = [proxy_runtime.proxy_url_for_region(item, country) for item in pool_values]
    selector, meta = proxy_runtime.build_oauth_proxy_selector(
        proxy_url=proxy_runtime.proxy_url_for_region(params.proxy_url, country),
        proxy_pool=routed_pool,
        proxy_api_provider=provider if params.proxy_api_enabled else "",
        proxy_api_url=api_url,
        proxy_api_country=country,
        default_auth_scheme=proxy_runtime.default_proxy_auth_scheme(provider),
    )
    meta["country"] = country
    return selector, meta


def create_account_promo_offer_router(
    *,
    start_task: Callable[..., dict[str, Any]],
    normalize_email: Callable[[str | None], str],
    is_main_account_email: Callable[[str | None], bool],
    resolve_status_auth_file: Callable[[dict], str | None],
    append_task_progress: Callable[[str | None, dict], Any],
    logger: Any,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/accounts/promo-offer-check/options")
    def get_promo_offer_check_options() -> dict[str, Any]:
        return {"methods": promo_payment_method_options()}

    @router.post("/api/accounts/promo-offer-check", status_code=202)
    def post_accounts_promo_offer_check(params: PromoOfferCheckParams):
        from autotoken.storage.accounts import find_account, load_accounts

        methods = _clean_methods(params.methods)
        if not methods:
            methods = list(PROMO_PAYMENT_ROUTES.keys())
        concurrency = max(1, min(10, int(params.concurrency or 4)))
        verify_proxy_country = bool(params.verify_proxy_country)
        account_list = load_accounts()
        emails: list[str] = []
        seen: set[str] = set()
        for item in params.emails or []:
            email = normalize_email(item)
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
        if not emails:
            for acc in account_list:
                email = normalize_email(acc.get("email"))
                if email and email not in seen and not is_main_account_email(email):
                    seen.add(email)
                    emails.append(email)

        accounts_by_email: dict[str, dict] = {}
        missing: list[str] = []
        for email in emails:
            acc = find_account(account_list, email)
            if not acc:
                missing.append(email)
                continue
            accounts_by_email[email] = acc
        if not accounts_by_email:
            raise HTTPException(status_code=404, detail="账号不存在")

        selectors: dict[str, Callable[[], str]] = {}
        proxy_meta: dict[str, dict[str, Any]] = {}
        for method in methods:
            route = route_for_promo_method(method)
            if not route:
                continue
            selector, meta = _build_proxy_selector_for_country(params, route.country)
            selectors[method] = selector
            proxy_meta[method] = meta

        def _run(task_id: str = ""):
            from autotoken.storage.accounts import update_account

            total = len(accounts_by_email)
            completed = 0
            eligible = []
            ineligible = []
            payment_available = []
            failed = []
            skipped = []
            progress_lock = threading.Lock()

            def progress(payload: dict[str, Any]) -> None:
                append_task_progress(task_id, payload)

            def _load_auth(acc: dict, email: str) -> tuple[str, dict[str, Any]]:
                auth_path = trusted_auth_or_session_path(resolve_status_auth_file(acc))
                if not auth_path or not Path(auth_path).exists():
                    raise RuntimeError("缺少 auth_session/auth_file")
                auth_data = read_auth_json_file(auth_path)
                if not isinstance(auth_data, dict):
                    raise RuntimeError("认证文件格式异常")
                return str(auth_path), auth_data

            def _run_one(index: int, email: str, acc: dict) -> dict[str, Any]:
                started_at = time.time()
                try:
                    _auth_path, auth_data = _load_auth(acc, email)
                    access_token = _extract_access_token(auth_data)
                    if not access_token:
                        return {"kind": "failed", "email": email, "index": index, "reason": "missing_access_token", "message": f"查优惠失败，缺少 access_token: {email}"}
                    account_id = _extract_account_id(auth_data)
                    device_id = _extract_device_id(auth_data, email)
                    session_cookie = _extract_session_cookie(auth_data)
                    route_results: list[dict[str, Any]] = []
                    found_methods: list[str] = []
                    trial_update: dict[str, Any] | None = None
                    saw_trial = False
                    last_error = ""
                    for method in methods:
                        route = route_for_promo_method(method)
                        if not route:
                            continue
                        progress(
                            {
                                "stage": "promo_offer_account_method_start",
                                "email": email,
                                "account_index": index,
                                "current": completed,
                                "total": total,
                                "method": method,
                                "country": route.country,
                                "message": f"查优惠中: {email} / {method}，先检测试用资格",
                                "level": "info",
                            }
                        )
                        proxy_url = ""
                        try:
                            proxy_url = selectors[method]()
                            if not proxy_url:
                                raise RuntimeError("未获取到代理")
                            trial_result = query_chatgpt_account_check(
                                access_token,
                                account_id=account_id,
                                proxy_url=proxy_url,
                                device_id=device_id,
                            )
                            trial = normalize_chatgpt_trial_eligibility(trial_result.get("raw") or {}, account_id=account_id)
                            trial_update = {
                                "trial_eligible": bool(trial.get("trial_eligible")),
                                "trial_available_plans": [str(item) for item in (trial.get("trial_available_plans") or []) if str(item or "").strip()],
                                "trial_checked_at": trial.get("trial_checked_at") or time.time(),
                                "trial_detection_source": f"promo_offer_check:{method}",
                                "trial_detection_reason": trial.get("trial_detection_reason") or "",
                                "trial_status": trial.get("trial_status") or "",
                                "trial_label": trial.get("trial_label") or "",
                                "trial_promo_campaign_id": trial.get("trial_promo_campaign_id") or "",
                                "promo_checked_at": time.time(),
                            }
                            if not trial.get("trial_eligible"):
                                route_results.append(
                                    {
                                        "method": method,
                                        "country": route.country,
                                        "currency": route.currency,
                                        "locale": route.locale,
                                        "label": route.label,
                                        "status": "trial_ineligible",
                                        "state": trial.get("trial_status") or "trial_ineligible",
                                        "methods": [],
                                        "checked_at": time.time(),
                                        "exit": "",
                                        "http_status": 0,
                                        "session_type": "",
                                        "error": trial.get("trial_detection_reason") or "无 Plus 试用资格",
                                    }
                                )
                                continue
                            saw_trial = True
                            payment = detect_promo_payment_method(
                                access_token=access_token,
                                account_id=account_id,
                                method=method,
                                proxy_url=proxy_url,
                                device_id=device_id,
                                session_cookie=session_cookie,
                                verify_proxy_country=verify_proxy_country,
                            )
                            route_summary = _route_summary(payment)
                            route_results.append(route_summary)
                            if route_summary.get("status") == "available" and method in (route_summary.get("methods") or []):
                                found_methods.append(method)
                            elif method in (route_summary.get("methods") or []):
                                found_methods.append(method)
                            if route_summary.get("error"):
                                last_error = str(route_summary.get("error") or "")
                        except Exception as exc:
                            last_error = str(exc)[:300]
                            route_results.append(
                                {
                                    "method": method,
                                    "country": route.country if route else "",
                                    "currency": route.currency if route else "",
                                    "locale": route.locale if route else "",
                                    "label": route.label if route else method,
                                    "status": "unknown",
                                    "state": "exception",
                                    "methods": [],
                                    "checked_at": time.time(),
                                    "exit": "",
                                    "http_status": 0,
                                    "session_type": "",
                                    "error": last_error,
                                }
                            )
                            logger.warning("[查优惠] %s/%s 检测失败: %s", email, method, exc)
                    found_methods = list(dict.fromkeys(found_methods))
                    payment_status, payment_state = _aggregate_method_status(route_results)
                    update_payload = {
                        "promo_checked_at": time.time(),
                        "promo_selected_methods": methods,
                        "promo_payment_methods": found_methods,
                        "promo_payment_status": payment_status,
                        "promo_payment_state": payment_state,
                        "promo_payment_routes": route_results,
                        "promo_payment_error": last_error,
                    }
                    if trial_update:
                        update_payload.update(trial_update)
                    update_account(email, **update_payload)
                    if found_methods:
                        return {"kind": "payment_available", "email": email, "index": index, "methods": found_methods, "routes": route_results, "message": f"查优惠完成，可用支付方式 {','.join(found_methods)}: {email}"}
                    if saw_trial:
                        return {"kind": "eligible", "email": email, "index": index, "routes": route_results, "message": f"查优惠完成，有试用资格但未返回所选支付方式: {email}"}
                    return {"kind": "ineligible", "email": email, "index": index, "routes": route_results, "message": f"查优惠完成，暂无 Plus 试用资格: {email}"}
                except Exception as exc:
                    return {"kind": "failed", "email": email, "index": index, "reason": "exception", "error": str(exc), "message": f"查优惠异常: {email}: {exc}", "elapsed": time.time() - started_at}

            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="promo-offer-check") as executor:
                future_map = {
                    executor.submit(_run_one, index, email, acc): (index, email)
                    for index, (email, acc) in enumerate(accounts_by_email.items(), start=1)
                }
                for future in as_completed(future_map):
                    index, email = future_map[future]
                    try:
                        item = future.result()
                    except Exception as exc:
                        item = {"kind": "failed", "email": email, "index": index, "reason": "exception", "error": str(exc), "message": f"查优惠异常: {email}: {exc}"}
                    with progress_lock:
                        completed += 1
                        kind = str(item.get("kind") or "failed")
                        if kind == "payment_available":
                            payment_available.append({"email": email, "methods": item.get("methods") or []})
                            eligible.append(email)
                            level = "info"
                        elif kind == "eligible":
                            eligible.append(email)
                            level = "info"
                        elif kind == "ineligible":
                            ineligible.append(email)
                            level = "warn"
                        elif kind == "skipped":
                            skipped.append({"email": email, "reason": item.get("reason") or "skipped"})
                            level = "warn"
                        else:
                            failed.append({"email": email, "reason": item.get("reason") or "failed", "error": item.get("error") or ""})
                            level = "error"
                        progress(
                            {
                                "stage": "promo_offer_account_done",
                                "email": email,
                                "account_index": index,
                                "current": completed,
                                "total": total,
                                "eligible": len(eligible),
                                "ineligible": len(ineligible),
                                "payment_available": len(payment_available),
                                "failed": len(failed),
                                "skipped": len(skipped),
                                "message": item.get("message") or f"查优惠完成: {email}",
                                "level": level,
                            }
                        )
            return {
                "eligible": eligible,
                "ineligible": ineligible,
                "payment_available": payment_available,
                "failed": failed,
                "skipped": skipped,
                "missing": missing,
                "total": total,
                "methods": methods,
                "proxy_meta": proxy_meta,
                "concurrency": concurrency,
            }

        return start_task(
            "promo-offer-check",
            _run,
            {
                "emails": emails,
                "methods": methods,
                "missing": missing,
                "concurrency": concurrency,
                "proxy_api_enabled": bool(params.proxy_api_enabled),
                "proxy_api_provider": params.proxy_api_provider,
                "proxy_api_url_present": bool(str(params.proxy_api_url or "").strip()),
                "proxy_pool_count": len(params.proxy_pool or []) + len(proxy_runtime.parse_proxy_pool_values(text=params.proxy_pool_text)),
                "verify_proxy_country": verify_proxy_country,
            },
            pass_task_id=True,
        )

    return router
