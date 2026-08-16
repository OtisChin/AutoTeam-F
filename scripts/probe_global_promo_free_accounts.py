"""Probe latest free auth accounts for zero-amount trial promo eligibility.

This script only creates/reads checkout sessions and validates amount snapshots.
It never confirms a payment method, approves a checkout, or persists payment links.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from autotoken.api_routes.us_paypal import _iter_auth_accounts, _load_token_for_email
from autotoken.payments.brazil_pix import short
from autotoken.payments.us_paypal import (
    DEFAULT_STRIPE_PK,
    PAYPAL_COUNTRY_CURRENCIES,
    PaypalJobConfig,
    amount_info,
    build_chatgpt_session,
    build_paypal_dynamic_proxy,
    build_stripe_session,
    extract_pk,
    fetch_oaics_checkout_session,
    is_checkout_session_id,
    is_openai_custom_checkout_session_id,
    is_zero_amount,
    normalize_paypal_country,
    normalize_paypal_proxy_url,
    oaics_amount_observations,
    oaics_custom_payment_methods,
    oaics_payment_method_types,
    paypal_billing,
    pix_proxy_context,
    pmt_info,
    stripe_init,
    submit_oaics_checkout_taxes,
    verify_oaics_zero_snapshot,
    warm_chatgpt_checkout_context,
)
from autotoken.storage import accounts as account_store

DEFAULT_COUNTRIES = ["US", "GB", "JP", "BR", "ID", "VN", "TH", "PH", "TR"]
BAD_STATUSES = {
    account_store.STATUS_PLUS,
    account_store.STATUS_AUTH_INVALID,
    account_store.STATUS_FAIL,
    account_store.STATUS_ORPHAN,
}
PRINT_LOCK = threading.Lock()
WRITE_LOCK = threading.Lock()


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    items: list[str] = []
    for chunk in str(value).replace("\r", "\n").replace(",", "\n").splitlines():
        item = chunk.strip()
        if item:
            items.append(item)
    return items


def parse_countries(value: str | None) -> list[str]:
    raw = parse_list(value) or DEFAULT_COUNTRIES
    seen: set[str] = set()
    countries: list[str] = []
    for item in raw:
        country = normalize_paypal_country(item, "").upper()
        if len(country) == 2 and country not in seen:
            seen.add(country)
            countries.append(country)
    return countries or DEFAULT_COUNTRIES


def country_currency(country: str) -> str:
    return PAYPAL_COUNTRY_CURRENCIES.get(str(country or "").upper(), "USD")


def latest_free_auth_accounts(limit: int, exclude_emails: set[str] | None = None) -> list[dict[str, Any]]:
    dashboard = {
        str(item.get("email") or "").strip().lower(): item
        for item in account_store.load_accounts()
        if str(item.get("email") or "").strip()
    }
    selected: list[dict[str, Any]] = []
    exclude_emails = {str(e or "").strip().lower() for e in (exclude_emails or set()) if str(e or "").strip()}
    for auth in _iter_auth_accounts(include_paid=False):
        email = str(auth.get("email") or "").strip()
        if not email:
            continue
        if email.lower() in exclude_emails:
            continue
        account = dashboard.get(email.lower()) or {}
        account_type = str(account.get("account_type") or account_store.ACCOUNT_TYPE_FREE).strip().lower()
        status = str(account.get("status") or "").strip().lower()
        if account_type != account_store.ACCOUNT_TYPE_FREE:
            continue
        if status in BAD_STATUSES:
            continue
        row = dict(auth)
        row["status"] = status or account.get("status") or ""
        row["account_type"] = account_type
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def log(msg: str) -> None:
    with PRINT_LOCK:
        print(msg, flush=True)


def write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with WRITE_LOCK:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def create_checkout_probe(
    *,
    token: str,
    proxy_url: str,
    email: str,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    currency = country_currency(country)
    cg = build_chatgpt_session(token, proxy_url, device_id)
    warm_chatgpt_checkout_context(cg, country, lambda _m: None)
    body = {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {"country": country, "currency": currency},
        "checkout_ui_mode": "custom",
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
    }
    resp = cg.post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=body,
        headers={"x-openai-target-path": "/backend-api/payments/checkout", "x-openai-target-route": "/backend-api/payments/checkout"},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"checkout HTTP {resp.status_code}: {short(resp.text, 500)}")
    payload = resp.json() or {}
    cs_id = str(payload.get("checkout_session_id") or payload.get("session_id") or payload.get("id") or "")
    processor = str(payload.get("processor_entity") or "openai_llc")
    pk = extract_pk(payload) or DEFAULT_STRIPE_PK
    return {"raw": payload, "cs_id": cs_id, "processor": processor, "pk": pk, "currency": currency}


def probe_oaics(
    *,
    token: str,
    proxy_url: str,
    email: str,
    country: str,
    currency: str,
    cs_id: str,
    processor: str,
    device_id: str,
) -> dict[str, Any]:
    cg = build_chatgpt_session(token, proxy_url, device_id)
    state = fetch_oaics_checkout_session(cg, token, cs_id, processor, country=country, device_id=device_id)
    billing = paypal_billing(email, country)
    taxes = submit_oaics_checkout_taxes(
        cg,
        token,
        cs_id,
        processor,
        billing=billing,
        country=country,
        currency=currency,
        device_id=device_id,
    )
    merged: dict[str, Any] = dict(state)
    merged.update(taxes)
    observations = oaics_amount_observations(merged)
    amount = 0
    try:
        amount = verify_oaics_zero_snapshot(merged, cs_id=cs_id, currency=currency)
        zero = True
        error = ""
    except Exception as exc:
        zero = False
        error = short(exc, 500)
        nonzero = [amt for _label, amt in observations if amt != 0]
        if nonzero:
            amount = nonzero[0]
    return {
        "country": country,
        "currency": currency,
        "checkout_session_id": cs_id,
        "checkout_prefix": "oaics",
        "processor": processor,
        "amount": str(amount),
        "zero": bool(zero),
        "payment_method_types": oaics_payment_method_types(merged),
        "custom_payment_methods": [str(item.get("id") or "") for item in oaics_custom_payment_methods(merged)],
        "amount_observations": [{"path": label, "amount": amt} for label, amt in observations],
        "error": error,
    }


def probe_cs(*, proxy_url: str, country: str, currency: str, cs_id: str, pk: str, processor: str) -> dict[str, Any]:
    stripe = build_stripe_session(proxy_url)
    ctx = {
        "stripe_js_id": str(uuid.uuid4()),
        "client_session_id": str(uuid.uuid4()),
        "guid": uuid.uuid4().hex,
        "muid": uuid.uuid4().hex,
        "sid": uuid.uuid4().hex,
        "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_config_id": str(uuid.uuid4()),
        "config_id": "",
        "init_checksum": "",
    }
    payload = stripe_init(stripe, cs_id, pk, ctx)
    amount = amount_info(payload)
    pmt, ordered, has_paypal = pmt_info(payload)
    return {
        "country": country,
        "currency": currency,
        "checkout_session_id": cs_id,
        "checkout_prefix": "cs",
        "processor": processor,
        "amount": amount,
        "zero": is_zero_amount(amount),
        "payment_method_types": pmt,
        "ordered_payment_method_types": ordered,
        "has_paypal": has_paypal,
        "error": "",
    }


def probe_country(
    *,
    email: str,
    token: str,
    country: str,
    proxy_seed: str,
    local_proxy: str,
    account_index: int,
    country_index: int,
) -> dict[str, Any]:
    started = time.time()
    device_id = str(uuid.uuid4())
    cfg = PaypalJobConfig(access_token=token, region=country, promo_region=country, direct_proxies=[proxy_seed], local_proxy=local_proxy, apply_promo=True)
    dyn, sid = build_paypal_dynamic_proxy(cfg, account_index * 100 + country_index, country)
    try:
        with pix_proxy_context(local_proxy, dyn, lambda _m: None) as chain:
            checkout = create_checkout_probe(token=token, proxy_url=chain.url, email=email, country=country, device_id=device_id)
            cs_id = checkout["cs_id"]
            if is_openai_custom_checkout_session_id(cs_id):
                result = probe_oaics(
                    token=token,
                    proxy_url=chain.url,
                    email=email,
                    country=country,
                    currency=checkout["currency"],
                    cs_id=cs_id,
                    processor=checkout["processor"],
                    device_id=device_id,
                )
            elif is_checkout_session_id(cs_id):
                result = probe_cs(
                    proxy_url=chain.url,
                    country=country,
                    currency=checkout["currency"],
                    cs_id=cs_id,
                    pk=checkout["pk"],
                    processor=checkout["processor"],
                )
            else:
                raise RuntimeError(f"checkout missing cs_id: {short(checkout['raw'], 500)}")
            result["sid"] = sid
            result["elapsed_seconds"] = round(time.time() - started, 3)
            return result
    except Exception as exc:
        return {
            "country": country,
            "currency": country_currency(country),
            "checkout_prefix": "error",
            "amount": "",
            "zero": False,
            "error": short(exc, 800),
            "sid": sid,
            "elapsed_seconds": round(time.time() - started, 3),
        }


def probe_account(
    *,
    auth: dict[str, Any],
    account_index: int,
    countries: list[str],
    proxies: list[str],
    local_proxy: str,
    stop_on_first_fail: bool,
) -> dict[str, Any]:
    email = str(auth.get("email") or "").strip()
    started = time.time()
    token = _load_token_for_email(email)
    if not token:
        return {
            "email": email,
            "updated_at": auth.get("updated_at"),
            "status": auth.get("status"),
            "account_type": auth.get("account_type"),
            "global_promo": False,
            "partial_promo": False,
            "countries": [],
            "error": "missing access token",
            "elapsed_seconds": round(time.time() - started, 3),
        }
    country_results: list[dict[str, Any]] = []
    for country_index, country in enumerate(countries):
        proxy_seed = proxies[(account_index + country_index) % len(proxies)] if proxies else ""
        result = probe_country(
            email=email,
            token=token,
            country=country,
            proxy_seed=proxy_seed,
            local_proxy=local_proxy,
            account_index=account_index,
            country_index=country_index,
        )
        country_results.append(result)
        marker = "0" if result.get("zero") else "X"
        log(f"[{account_index + 1:03d}] {email} {country} {marker} {result.get('checkout_prefix')} amount={result.get('amount')} err={result.get('error') or '-'}")
        if stop_on_first_fail and not result.get("zero"):
            break
    global_promo = len(country_results) == len(countries) and all(bool(item.get("zero")) for item in country_results)
    partial_promo = any(bool(item.get("zero")) for item in country_results)
    return {
        "email": email,
        "updated_at": auth.get("updated_at"),
        "status": auth.get("status"),
        "account_type": auth.get("account_type"),
        "global_promo": global_promo,
        "partial_promo": partial_promo,
        "countries": country_results,
        "elapsed_seconds": round(time.time() - started, 3),
    }


def summarize(results: list[dict[str, Any]], selected_count: int, countries: list[str]) -> dict[str, Any]:
    completed = len(results)
    global_items = [item for item in results if item.get("global_promo")]
    partial_items = [item for item in results if item.get("partial_promo") and not item.get("global_promo")]
    no_items = [item for item in results if not item.get("partial_promo")]
    error_accounts = [
        item for item in results
        if item.get("error") or any((not c.get("zero") and c.get("error")) for c in item.get("countries") or [])
    ]
    by_country: dict[str, dict[str, int]] = {c: {"zero": 0, "nonzero": 0, "error": 0, "tested": 0} for c in countries}
    prefix_counts: dict[str, int] = {}
    for item in results:
        for c in item.get("countries") or []:
            country = str(c.get("country") or "")
            if country not in by_country:
                by_country[country] = {"zero": 0, "nonzero": 0, "error": 0, "tested": 0}
            by_country[country]["tested"] += 1
            if c.get("zero"):
                by_country[country]["zero"] += 1
            elif c.get("error"):
                by_country[country]["error"] += 1
            else:
                by_country[country]["nonzero"] += 1
            prefix = str(c.get("checkout_prefix") or "unknown")
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
    return {
        "selected": selected_count,
        "completed": completed,
        "countries": countries,
        "global_promo": len(global_items),
        "partial_promo": len(partial_items),
        "no_promo": len(no_items),
        "error_accounts": len(error_accounts),
        "global_promo_emails": [item.get("email") for item in global_items],
        "by_country": by_country,
        "checkout_prefix_counts": prefix_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    parser.add_argument("--proxy", action="append", default=[])
    parser.add_argument("--proxy-file", default="")
    parser.add_argument("--exclude-results", action="append", default=[])
    parser.add_argument("--local-proxy", default="")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--output", default="")
    parser.add_argument("--stop-on-first-fail", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    countries = parse_countries(args.countries)
    proxy_values: list[str] = []
    for item in args.proxy or []:
        proxy_values.extend(parse_list(item))
    env_proxy = os.environ.get("GLOBAL_PROMO_PROXIES") or os.environ.get("GLOBAL_PROMO_PROXY") or ""
    proxy_values.extend(parse_list(env_proxy))
    if args.proxy_file:
        proxy_values.extend(parse_list(Path(args.proxy_file).read_text(encoding="utf-8")))
    proxies = [normalize_paypal_proxy_url(item) for item in proxy_values if str(item or "").strip()]
    if not proxies:
        raise SystemExit("missing proxy: use --proxy/--proxy-file or GLOBAL_PROMO_PROXIES")

    exclude_emails: set[str] = set()
    for result_path in args.exclude_results or []:
        try:
            data = json.loads(Path(result_path).read_text(encoding="utf-8"))
            for item in data.get("results") or []:
                email = str(item.get("email") or "").strip().lower()
                if email:
                    exclude_emails.add(email)
        except Exception:
            pass
    all_selected = latest_free_auth_accounts(max(1, int(args.offset) + int(args.limit)), exclude_emails=exclude_emails)
    selected = all_selected[max(0, int(args.offset)): max(0, int(args.offset)) + max(1, int(args.limit))]
    out = Path(args.output or f"data/global_promo_probe_{_now_stamp()}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "limit": args.limit,
        "offset": args.offset,
        "countries": countries,
        "stop_on_first_fail": bool(args.stop_on_first_fail),
        "selected_accounts": len(selected),
        "results": [],
        "summary": summarize([], len(selected), countries),
    }
    write_snapshot(out, payload)
    log(f"输出: {out}")
    log(f"selected={len(selected)} countries={','.join(countries)} concurrency={args.concurrency} stop_on_first_fail={args.stop_on_first_fail}")

    results: list[dict[str, Any]] = []
    max_workers = max(1, min(int(args.concurrency), 10))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                probe_account,
                auth=auth,
                account_index=index,
                countries=countries,
                proxies=proxies,
                local_proxy=str(args.local_proxy or ""),
                stop_on_first_fail=bool(args.stop_on_first_fail),
            )
            for index, auth in enumerate(selected)
        ]
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            results.append(item)
            payload["results"] = sorted(results, key=lambda r: str(r.get("updated_at") or ""), reverse=True)
            payload["summary"] = summarize(results, len(selected), countries)
            payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
            write_snapshot(out, payload)
            s = payload["summary"]
            log(f"progress {len(results)}/{len(selected)} global={s['global_promo']} partial={s['partial_promo']} no={s['no_promo']} errors={s['error_accounts']}")

    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["results"] = sorted(results, key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    payload["summary"] = summarize(results, len(selected), countries)
    write_snapshot(out, payload)
    s = payload["summary"]
    log("=== SUMMARY ===")
    log(json.dumps(s, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
