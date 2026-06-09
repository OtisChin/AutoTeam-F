"""Rekberinaja saldo-based GoPay top-up client."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = "https://api.rekberinaja.com/api"
DEFAULT_STORE = "rekberinaja"
DEFAULT_GOPAY_PRODUCT_ID = "5668ba3f-9b70-409d-9079-e0aafa798e69"
DEFAULT_GOPAY_SERVICE_ID = "81b3fe9a-13ee-11f1-aa7e-c81f66de8b22"  # Go Pay 1.000


class RekberinajaError(RuntimeError):
    """Raised when Rekberinaja cannot complete a top-up flow."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "",
        transaction_id: str = "",
        status: str = "",
        debited_possible: bool = False,
    ):
        super().__init__(message)
        self.stage = stage
        self.transaction_id = transaction_id
        self.status = status
        self.debited_possible = debited_possible


@dataclass(frozen=True)
class RekberinajaConfig:
    enabled: bool = False
    transfer_enabled: bool = False
    email: str = ""
    password: str = ""
    base_url: str = DEFAULT_BASE_URL
    store: str = DEFAULT_STORE
    product_id: str = DEFAULT_GOPAY_PRODUCT_ID
    gopay_service_id: str = DEFAULT_GOPAY_SERVICE_ID
    min_balance: int = 5000
    poll_interval: float = 5.0
    poll_timeout: float = 180.0
    invoice_email: str = ""


def _env_bool(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(str(os.environ.get(name, "") or default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, "") or default))
    except Exception:
        return default


def load_rekberinaja_config() -> RekberinajaConfig:
    return RekberinajaConfig(
        enabled=_env_bool("REKBERINAJA_ENABLED", False),
        transfer_enabled=_env_bool("REKBERINAJA_TRANSFER_ENABLED", False),
        email=str(os.environ.get("REKBERINAJA_EMAIL") or "").strip(),
        password=str(os.environ.get("REKBERINAJA_PASSWORD") or "").strip(),
        base_url=str(os.environ.get("REKBERINAJA_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
        store=str(os.environ.get("REKBERINAJA_STORE") or DEFAULT_STORE).strip() or DEFAULT_STORE,
        product_id=str(os.environ.get("REKBERINAJA_GOPAY_PRODUCT_ID") or DEFAULT_GOPAY_PRODUCT_ID).strip(),
        gopay_service_id=str(os.environ.get("REKBERINAJA_GOPAY_SERVICE_ID") or DEFAULT_GOPAY_SERVICE_ID).strip(),
        min_balance=max(0, _env_int("REKBERINAJA_MIN_BALANCE", 5000)),
        poll_interval=max(1.0, _env_float("REKBERINAJA_POLL_INTERVAL", 5.0)),
        poll_timeout=max(10.0, _env_float("REKBERINAJA_POLL_TIMEOUT", 180.0)),
        invoice_email=str(os.environ.get("REKBERINAJA_INVOICE_EMAIL") or "").strip(),
    )


def is_rekberinaja_enabled(config: RekberinajaConfig | None = None) -> bool:
    cfg = config or load_rekberinaja_config()
    return bool(cfg.enabled and cfg.transfer_enabled)


def format_gopay_phone_for_rekberinaja(phone_number: str) -> str:
    digits = "".join(ch for ch in str(phone_number or "") if ch.isdigit())
    if not digits:
        raise RekberinajaError("Rekberinaja 充值缺少 GoPay 手机号")
    if digits.startswith("62"):
        return "0" + digits[2:]
    if digits.startswith("8"):
        return "0" + digits
    return digits


class RekberinajaClient:
    def __init__(
        self,
        config: RekberinajaConfig | None = None,
        *,
        session: requests.Session | None = None,
        progress: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.config = config or load_rekberinaja_config()
        self.session = session or requests.Session()
        self.progress = progress
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-STORE": self.config.store,
                "X-DEVICE-ID": uuid.uuid4().hex,
            }
        )

    def _emit(self, stage: str, **payload: Any) -> None:
        if not self.progress:
            return
        try:
            self.progress(stage, payload)
        except Exception:
            pass

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self.config.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
        except requests.RequestException as exc:
            raise RekberinajaError(f"Rekberinaja 请求失败: {exc}", stage=f"{method} {path}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RekberinajaError(
                f"Rekberinaja 返回非 JSON: HTTP {response.status_code}",
                stage=f"{method} {path}",
            ) from exc

        if response.status_code >= 400 or not payload.get("status"):
            message = payload.get("message") if isinstance(payload, dict) else ""
            raise RekberinajaError(message or f"Rekberinaja HTTP {response.status_code}", stage=f"{method} {path}")
        return payload

    def login(self) -> dict[str, Any]:
        if not self.config.email or not self.config.password:
            raise RekberinajaError("缺少 REKBERINAJA_EMAIL 或 REKBERINAJA_PASSWORD 配置", stage="login")
        self._emit("rekberinaja_login_started", message="正在登录 Rekberinaja")
        payload = self._request(
            "POST",
            "auth/login",
            json={"email": self.config.email, "password": self.config.password},
        )
        data = payload.get("data") or {}
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise RekberinajaError("Rekberinaja 登录未返回 access_token", stage="login")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self._emit("rekberinaja_login_done", message="Rekberinaja 登录成功")
        return data

    def get_balance(self) -> int:
        payload = self._request("GET", "user/balance")
        data = payload.get("data") or {}
        try:
            balance = int(float(data.get("balance") or 0))
        except Exception:
            balance = 0
        self._emit(
            "rekberinaja_balance_checked",
            balance=balance,
            min_balance=self.config.min_balance,
            message=f"Rekberinaja 余额检查完成：{balance} IDR",
        )
        return balance

    def create_gopay_order(self, phone_number: str) -> str:
        target = format_gopay_phone_for_rekberinaja(phone_number)
        self._emit(
            "rekberinaja_order_create_started",
            phone_number=target,
            service_id=self.config.gopay_service_id,
            message="正在创建 Rekberinaja GoPay 充值订单",
        )
        payload = {
            "product_id": self.config.product_id,
            "service_id": self.config.gopay_service_id,
            "promo_code": "",
            "use_poin": False,
            "data": target,
            "payment_method": "saldo",
            "invoice_email": self.config.invoice_email,
        }
        response = self._request("POST", "transaction/product/checkout", json=payload)
        transaction_id = str((response.get("data") or {}).get("transaction_id") or "").strip()
        if not transaction_id:
            raise RekberinajaError("Rekberinaja 下单成功但未返回 transaction_id", stage="create_order")
        self._emit(
            "rekberinaja_order_created",
            transaction_id=transaction_id,
            phone_number=target,
            message=f"Rekberinaja 充值订单已创建：{transaction_id}",
        )
        return transaction_id

    def pay_with_saldo(self, transaction_id: str) -> dict[str, Any]:
        self._emit(
            "rekberinaja_saldo_pay_started",
            transaction_id=transaction_id,
            message=f"正在使用 Rekberinaja 站内余额支付订单：{transaction_id}",
        )
        response = self._request("GET", f"transaction/{transaction_id}/pay")
        self._emit(
            "rekberinaja_saldo_pay_done",
            transaction_id=transaction_id,
            message=f"Rekberinaja 站内支付已提交：{transaction_id}",
        )
        return response

    def get_order_product(self, transaction_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"transaction/{transaction_id}/order-product")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise RekberinajaError(
                "Rekberinaja 订单状态返回格式异常",
                stage="poll_order",
                transaction_id=transaction_id,
                debited_possible=True,
            )
        return data

    def wait_order_completed(self, transaction_id: str) -> dict[str, Any]:
        deadline = time.time() + self.config.poll_timeout
        last_order: dict[str, Any] = {}
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            last_order = self.get_order_product(transaction_id)
            status = str(last_order.get("status") or "").lower()
            message = str(last_order.get("message") or last_order.get("status_message") or "").strip()
            self._emit(
                "rekberinaja_order_poll",
                transaction_id=transaction_id,
                attempt=attempt,
                status=status,
                order_message=message,
                message=f"Rekberinaja 订单轮询：{transaction_id} status={status or '-'}",
            )
            if status == "completed":
                self._emit(
                    "rekberinaja_order_completed",
                    transaction_id=transaction_id,
                    status=status,
                    message=f"Rekberinaja GoPay 充值订单已完成：{transaction_id}",
                )
                return last_order
            if status == "fail":
                message = message or "订单失败"
                summary = _summarize_order_for_error(last_order)
                self._emit(
                    "rekberinaja_order_failed",
                    transaction_id=transaction_id,
                    status=status,
                    order_message=message,
                    order_summary=summary,
                    message=f"Rekberinaja GoPay 充值订单失败：{transaction_id}，{message}",
                    level="warn",
                )
                raise RekberinajaError(
                    f"Rekberinaja GoPay 充值失败: transaction_id={transaction_id} status={status} message={message} summary={summary}",
                    stage="poll_order",
                    transaction_id=transaction_id,
                    status=status,
                    debited_possible=True,
                )
            time.sleep(self.config.poll_interval)
        summary = _summarize_order_for_error(last_order)
        raise RekberinajaError(
            f"Rekberinaja GoPay 充值超时: transaction_id={transaction_id} summary={summary}",
            stage="poll_order",
            transaction_id=transaction_id,
            status=str(last_order.get("status") or ""),
            debited_possible=True,
        )

    def top_up_gopay(self, phone_number: str) -> dict[str, Any]:
        self.login()
        balance = self.get_balance()
        if balance < self.config.min_balance:
            raise RekberinajaError(
                f"Rekberinaja 余额不足: 当前 {balance} IDR，最低要求 {self.config.min_balance} IDR",
                stage="balance",
            )
        transaction_id = self.create_gopay_order(phone_number)
        self.pay_with_saldo(transaction_id)
        return {
            "transaction_id": transaction_id,
            "phone_number": format_gopay_phone_for_rekberinaja(phone_number),
            "balance_before": balance,
            "status": "submitted",
        }


def fund_gopay_wallet_if_enabled(
    phone_number: str,
    *,
    config: RekberinajaConfig | None = None,
    log: Callable[[str], None] | None = None,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    cfg = config or load_rekberinaja_config()
    if not cfg.enabled:
        return None
    client = RekberinajaClient(cfg, progress=progress)
    result = client.top_up_gopay(phone_number)
    if log:
        log(f"Rekberinaja GoPay top-up completed: transaction_id={result.get('transaction_id')}")
    return result


def _summarize_order_for_error(order: dict[str, Any]) -> str:
    if not isinstance(order, dict) or not order:
        return "-"
    summary: dict[str, Any] = {}
    for key in (
        "id",
        "transaction_id",
        "trx_id",
        "status",
        "message",
        "status_message",
        "serial_number",
        "sn",
        "ref_id",
        "reference",
    ):
        value = order.get(key)
        if value not in (None, ""):
            summary[key] = value
    return ", ".join(f"{key}={value}" for key, value in summary.items()) or "-"
