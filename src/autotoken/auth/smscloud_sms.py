"""SMS Cloud dynamic SMS provider integration."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin

import requests

SMSCLOUD_DEFAULT_BASE_URL = "https://smscloud.sbs/api/system"
SMSCLOUD_DEFAULT_SERVICE = "dr"


def _base_url(value: str | None = None) -> str:
    return str(value or SMSCLOUD_DEFAULT_BASE_URL).strip().rstrip("/") + "/"


def _request_json(base_url: str, api_key: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = urljoin(_base_url(base_url), path.lstrip("/"))
    response = requests.get(
        url,
        params=params or {},
        headers={"apiKey": api_key, "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"SMSCloud 返回非 JSON: {str(response.text or '')[:200]}") from exc
    if int(payload.get("code") or 0) != 0:
        raise RuntimeError(str(payload.get("message") or payload.get("msg") or payload))
    return payload


def _price_limit(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _price_text(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _free_price_map(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json

            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _smscloud_inventory_price_candidates(
    *,
    base_url: str,
    api_key: str,
    service: str,
    country: str,
    min_price: str = "",
    max_price: str = "",
) -> list[str]:
    floor = _price_limit(min_price)
    ceiling = _price_limit(max_price)
    if floor is None and ceiling is None:
        return []
    try:
        payload = _request_json(
            base_url,
            api_key,
            "/public/sms/getInventory",
            params={"serviceCode": str(service or SMSCLOUD_DEFAULT_SERVICE).strip() or SMSCLOUD_DEFAULT_SERVICE},
        )
    except Exception:
        return [_price_text(ceiling)]
    prices: set[float] = set()
    for row in payload.get("data") or []:
        if not isinstance(row, dict) or str(row.get("country") or "").strip() != str(country or "").strip():
            continue
        for raw in [row.get("retailPrice"), *_free_price_map(row.get("freePriceMap")).keys()]:
            price = _price_limit(raw)
            if price is None:
                continue
            if floor is not None and price < floor:
                continue
            if ceiling is not None and price > ceiling:
                continue
            if price is not None:
                prices.add(price)
        break
    if not prices:
        if ceiling is not None:
            return [_price_text(ceiling)]
        return [_price_text(floor)] if floor is not None else []
    return [_price_text(price) for price in sorted(prices)]


def query_smscloud_countries(*, base_url: str, api_key: str, service_code: str = SMSCLOUD_DEFAULT_SERVICE) -> dict[str, Any]:
    try:
        payload = _request_json(base_url, api_key, "/public/sms/countries")
        options = []
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            country_id = str(item.get("id") or "").strip()
            if not country_id:
                continue
            chn = str(item.get("chn") or "").strip()
            eng = str(item.get("eng") or "").strip()
            phone_code = str(item.get("phoneCode") or "").strip()
            label_parts = [part for part in (chn, eng, phone_code, country_id) if part]
            options.append({"value": country_id, "label": " / ".join(label_parts)})
        return {"options": options}
    except Exception as exc:
        return {"options": [], "error": str(exc)}


def acquire_smscloud_number(
    *,
    base_url: str,
    api_key: str,
    service: str = SMSCLOUD_DEFAULT_SERVICE,
    country: str,
    min_price: str = "",
    max_price: str = "",
) -> tuple[dict[str, Any] | None, str]:
    if not api_key:
        return None, "缺少 OAUTH_SMSCLOUD_API_KEY 配置"
    if not str(country or "").strip() or str(country).strip().lower() == "all":
        return None, "SMSCloud 取号必须指定国家 ID"
    price_candidates = _smscloud_inventory_price_candidates(
        base_url=base_url,
        api_key=api_key,
        service=str(service or SMSCLOUD_DEFAULT_SERVICE).strip() or SMSCLOUD_DEFAULT_SERVICE,
        country=str(country).strip(),
        min_price=min_price,
        max_price=max_price,
    )
    if not price_candidates:
        price_candidates = [""]
    attempted_prices: list[str] = []
    last_error = ""
    try:
        for candidate_price in price_candidates:
            if candidate_price:
                attempted_prices.append(candidate_price)
            try:
                payload = _request_json(
                    base_url,
                    api_key,
                    "/public/sms/flexible",
                    params={
                        "countryCode": str(country).strip(),
                        "serviceCode": str(service or SMSCLOUD_DEFAULT_SERVICE).strip() or SMSCLOUD_DEFAULT_SERVICE,
                        **({"maxPrice": candidate_price} if candidate_price else {}),
                    },
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            if not data or not str(data.get("id") or "").strip() or not str(data.get("phoneNumber") or "").strip():
                last_error = f"SMSCloud 返回无效取号数据: {payload!r}"
                continue
            floor = _price_limit(min_price)
            actual_price = _price_limit(data.get("creditAmount"))
            if floor is not None and actual_price is not None and actual_price < floor:
                order_id = str(data.get("id") or "")
                try:
                    _request_json(base_url, api_key, f"/public/sms/orders/cancel/{order_id}")
                except Exception:
                    pass
                last_error = f"SMSCloud 取号价格 {actual_price:g} 低于最低价格 {floor:g}"
                continue
            data["_requestedMaxPrice"] = candidate_price
            return data, ""
        if last_error and attempted_prices:
            return None, f"{last_error}；已尝试价档: {', '.join(attempted_prices)}"
        return None, last_error or "SMSCloud 未返回可用号码"
    except Exception as exc:
        return None, str(exc)


class SMSCloudActivation:
    def __init__(self, *, order_id: str, base_url: str, api_key: str, log=print):
        self.order_id = str(order_id or "").strip()
        self.base_url = _base_url(base_url)
        self.api_key = str(api_key or "").strip()
        self.log = log
        self.used_codes: set[str] = set()

    def wait_code(self, *, timeout_sec: int = 120, label: str = "", max_resends: int = 0) -> str:
        deadline = time.time() + max(5, int(timeout_sec or 120))
        resend_after = max(0, int(timeout_sec or 120) // max(1, int(max_resends or 0) + 1)) if max_resends else 0
        resend_count = 0
        next_resend_at = time.time() + resend_after if resend_after else 0
        while time.time() < deadline:
            payload = _request_json(self.base_url, self.api_key, f"/public/sms/orders/sync/{self.order_id}")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            code = str(data.get("code") or "").strip()
            if not code:
                text = str(data.get("text") or "")
                match = re.search(r"\b(\d{4,8})\b", text)
                code = match.group(1) if match else ""
            if code and code not in self.used_codes:
                self.used_codes.add(code)
                return code
            if resend_after and resend_count < max_resends and time.time() >= next_resend_at:
                try:
                    self.resend()
                except Exception as exc:
                    if callable(self.log):
                        self.log(
                            "SMSCloud 重发请求失败，继续等待验证码: activation=%s error=%s",
                            self.order_id,
                            exc,
                        )
                resend_count += 1
                next_resend_at = time.time() + resend_after
            time.sleep(3)
        raise TimeoutError(f"SMSCloud 等待验证码超时({timeout_sec}s): {label or self.order_id}")

    def cancel(self) -> None:
        if self.order_id:
            _request_json(self.base_url, self.api_key, f"/public/sms/orders/cancel/{self.order_id}")

    def finish(self) -> None:
        if self.order_id:
            _request_json(self.base_url, self.api_key, f"/public/sms/orders/finish/{self.order_id}")

    def resend(self) -> None:
        if self.order_id:
            _request_json(self.base_url, self.api_key, f"/public/sms/orders/resend/{self.order_id}")
