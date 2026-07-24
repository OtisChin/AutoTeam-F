from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import httpx
from loguru import logger

SMSBOWER_API_URL = "https://smsbower.page/stubs/handler_api.php"
SMSBOWER_DEFAULT_SERVICE = "ts"
SMSBOWER_DEFAULT_COUNTRY = "73"
SMSBOWER_DEFAULT_WAIT_SECONDS = 30.0
SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS = 2.0
SMSBOWER_DEFAULT_MAX_CHANNEL_FAILURES = 3
SMSBOWER_DEFAULT_ACTIVATION_TTL_SECONDS = 20 * 60
SMSBOWER_DEFAULT_MAX_ATTEMPTS = 12
HEROSMS_API_URL = "https://hero-sms.com/stubs/handler_api.php"
PAYPAL_SMS_DEFAULT_SERVICE = "ts"
PAYPAL_SMS_DEFAULT_COUNTRY = "187"
PAYPAL_SMS_COUNTRY_BY_PAYPAL_COUNTRY = {
    "US": "187",
    "GB": "16",
    "NL": "48",
    "BR": "73",
    "CA": "36",
    "ID": "6",
    "JP": "182",
    "MX": "54",
    "PH": "4",
    "TH": "52",
}
PAYPAL_SMS_COUNTRY_DIAL_CODES = {
    "12": "1",
    "187": "1",
    "36": "1",
    "16": "44",
    "48": "31",
    "73": "55",
    "6": "62",
    "182": "81",
    "54": "52",
    "4": "63",
    "52": "66",
    "33": "57",
}


class SMSBowerApiError(RuntimeError):
    pass


@dataclass
class SMSBowerProviderPrice:
    provider_id: str
    price: float
    count: int


@dataclass
class SMSBowerActivation:
    activation_id: str
    phone_number: str
    provider_id: str
    price: float
    expires_at: float
    reused: bool = False
    provider_name: str = ""
    service: str = ""
    country: str = ""
    last_code: str = ""
    use_count: int = 0


class SMSBowerClientProtocol(Protocol):
    def get_provider_prices(self, service: str, country: str) -> list[SMSBowerProviderPrice] | list[dict[str, object]]: ...

    def get_number_v2(
        self,
        *,
        service: str,
        country: str,
        provider_id: str,
        max_price: float,
    ) -> dict[str, object]: ...

    def get_status(self, activation_id: str) -> str: ...

    def set_status(self, activation_id: str, status: int) -> str: ...


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_dotenv_value(name: str) -> str:
    if os.getenv(name):
        return os.getenv(name, "").strip()
    for env_path in (Path.cwd() / ".env", _project_root() / ".env"):
        try:
            if not env_path.exists():
                continue
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _load_dotenv_value(name)
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "smsbower"}


def _env_float(name: str, default: float, min_value: float, max_value: float) -> float:
    raw = _load_dotenv_value(name)
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(min_value, min(value, max_value))


def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = _load_dotenv_value(name)
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(min_value, min(value, max_value))


def _digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_brazil_phone(value: object) -> str:
    digits = _digits(value)
    if not digits:
        raise SMSBowerApiError("SMSBower returned an empty phone number")
    if digits.startswith("55"):
        return f"+{digits}"
    return f"+55{digits}"


def _parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _parse_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _safe_api_error(action: str, status_code: int, body: object) -> SMSBowerApiError:
    text = str(body or "").strip()
    if len(text) > 300:
        text = text[:300] + "..."
    return SMSBowerApiError(f"{action} HTTP {status_code}: {text or '<empty response>'}")


class SMSBowerClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = SMSBOWER_API_URL,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise SMSBowerApiError("SMSBower API key is not configured")
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def _request_text(self, action: str, params: dict[str, object] | None = None) -> str:
        query: dict[str, str] = {"api_key": self.api_key, "action": action}
        for key, value in (params or {}).items():
            query[key] = str(value)
        with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds), trust_env=False) as client:
            response = client.get(self.base_url, params=query)
        text = (response.text or "").strip()
        if response.status_code >= 400:
            raise _safe_api_error(action, response.status_code, text)
        if text in {"BAD_KEY", "BAD_ACTION", "BAD_SERVICE", "BAD_COUNTRY"}:
            raise SMSBowerApiError(text)
        return text

    def _request_json(self, action: str, params: dict[str, object] | None = None) -> object:
        text = self._request_text(action, params)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SMSBowerApiError(text) from exc

    def get_provider_prices(self, service: str, country: str) -> list[SMSBowerProviderPrice]:
        data = self._request_json("getPricesV3", {"service": service, "country": country})
        providers = self._extract_price_nodes(data, service, country)
        prices = [
            SMSBowerProviderPrice(
                provider_id=str(item.get("provider_id") or key),
                price=_parse_float(item.get("price")),
                count=_parse_int(item.get("count")),
            )
            for key, item in providers
            if isinstance(item, dict)
        ]
        return sorted(
            [item for item in prices if item.provider_id and item.price > 0 and item.count > 0],
            key=lambda item: (item.price, item.provider_id),
        )

    def _extract_price_nodes(
        self,
        data: object,
        service: str,
        country: str,
    ) -> list[tuple[str, dict[str, object]]]:
        if not isinstance(data, dict):
            raise SMSBowerApiError(f"Unexpected getPricesV3 response: {data!r}")
        country_node = data.get(country)
        if isinstance(country_node, dict):
            service_node = country_node.get(service)
            if isinstance(service_node, dict):
                return [
                    (str(key), value)
                    for key, value in service_node.items()
                    if isinstance(value, dict)
                ]
        for maybe_country in data.values():
            if not isinstance(maybe_country, dict):
                continue
            for maybe_service in maybe_country.values():
                if not isinstance(maybe_service, dict):
                    continue
                matches = [
                    (str(key), value)
                    for key, value in maybe_service.items()
                    if isinstance(value, dict) and "price" in value and "count" in value
                ]
                if matches:
                    return matches
        raise SMSBowerApiError(f"No provider prices for service={service} country={country}")

    def get_number_v2(
        self,
        *,
        service: str,
        country: str,
        provider_id: str,
        max_price: float,
    ) -> dict[str, object]:
        data = self._request_json(
            "getNumberV2",
            {
                "service": service,
                "country": country,
                "providerIds": provider_id,
                "maxPrice": max_price,
            },
        )
        if not isinstance(data, dict) or not data.get("activationId") or not data.get("phoneNumber"):
            raise SMSBowerApiError(f"Unexpected getNumberV2 response: {data!r}")
        return data

    def get_status(self, activation_id: str) -> str:
        return self._request_text("getStatus", {"id": activation_id})

    def set_status(self, activation_id: str, status: int) -> str:
        return self._request_text("setStatus", {"id": activation_id, "status": status})


class SMSBowerActivationStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _project_root() / "cache" / "smsbower_numbers.json"

    def _empty(self) -> dict[str, object]:
        return {"activations": [], "provider_failures": {}}

    def load(self) -> dict[str, object]:
        try:
            if not self.path.exists():
                return self._empty()
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("activations", [])
                data.setdefault("provider_failures", {})
                return data
        except Exception as exc:
            logger.warning("SMSBower cache read failed: {}", exc)
        return self._empty()

    def save(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def reusable_activation(
        self,
        now: float | None = None,
        *,
        provider_name: str = "",
        service: str = "",
        country: str = "",
        phone_number: str = "",
        max_uses: int = 0,
    ) -> SMSBowerActivation | None:
        now = time.time() if now is None else now
        data = self.load()
        activations = data.get("activations")
        if not isinstance(activations, list):
            return None
        fresh_rows: list[dict[str, object]] = []
        selected: SMSBowerActivation | None = None
        expected_provider = str(provider_name or "").strip()
        expected_service = str(service or "").strip()
        expected_country = str(country or "").strip()
        expected_phone_digits = _digits(phone_number)
        for row in activations:
            if not isinstance(row, dict):
                continue
            expires_at = _parse_float(row.get("expires_at"))
            if expires_at <= now:
                continue
            fresh_rows.append(row)
            if expected_provider and str(row.get("provider_name") or row.get("provider_id") or "").strip() != expected_provider:
                continue
            if expected_service and str(row.get("service") or "").strip() not in {"", expected_service}:
                continue
            if expected_country and str(row.get("country") or "").strip() not in {"", expected_country}:
                continue
            if expected_phone_digits:
                value_digits = _digits(row.get("phone_number"))
                if not value_digits or not value_digits.endswith(expected_phone_digits[-10:]):
                    continue
            use_count = _parse_int(row.get("use_count"))
            if max_uses > 0 and use_count >= max_uses:
                continue
            if selected is None:
                selected = SMSBowerActivation(
                    activation_id=str(row.get("activation_id") or ""),
                    phone_number=str(row.get("phone_number") or ""),
                    provider_id=str(row.get("provider_id") or ""),
                    price=_parse_float(row.get("price")),
                    expires_at=expires_at,
                    reused=True,
                    provider_name=str(row.get("provider_name") or row.get("provider_id") or ""),
                    service=str(row.get("service") or ""),
                    country=str(row.get("country") or ""),
                    last_code=str(row.get("last_code") or ""),
                    use_count=use_count,
                )
        if len(fresh_rows) != len(activations):
            data["activations"] = fresh_rows
            self.save(data)
        if selected and selected.activation_id and selected.phone_number:
            return selected
        return None

    def remember_success(
        self,
        *,
        activation_id: str,
        phone_number: str,
        provider_id: str,
        price: float,
        expires_at: float,
        provider_name: str = "",
        service: str = "",
        country: str = "",
        last_code: str = "",
        increment_use: bool = True,
    ) -> None:
        data = self.load()
        activations = data.get("activations")
        rows = [row for row in activations if isinstance(row, dict)] if isinstance(activations, list) else []
        existing = next((row for row in rows if str(row.get("activation_id") or "") == activation_id), {})
        previous_use_count = _parse_int(existing.get("use_count")) if isinstance(existing, dict) else 0
        use_count = previous_use_count + 1 if increment_use else previous_use_count
        rows = [row for row in rows if str(row.get("activation_id") or "") != activation_id]
        rows.insert(
            0,
            {
                "activation_id": activation_id,
                "phone_number": phone_number,
                "provider_id": provider_id,
                "price": price,
                "expires_at": expires_at,
                "provider_name": provider_name or provider_id,
                "service": service,
                "country": country,
                "last_code": last_code,
                "use_count": use_count,
                "last_used_at": time.time(),
            },
        )
        data["activations"] = rows[:20]
        failures = data.get("provider_failures")
        if isinstance(failures, dict):
            failures[str(provider_id)] = 0
        self.save(data)

    def remember_activation(
        self,
        activation: SMSBowerActivation,
        *,
        last_code: str = "",
        increment_use: bool = True,
    ) -> None:
        self.remember_success(
            activation_id=activation.activation_id,
            phone_number=activation.phone_number,
            provider_id=activation.provider_id,
            price=activation.price,
            expires_at=activation.expires_at,
            provider_name=activation.provider_name or activation.provider_id,
            service=activation.service,
            country=activation.country,
            last_code=last_code or activation.last_code,
            increment_use=increment_use,
        )

    def abandon(self, activation_id: str) -> None:
        data = self.load()
        activations = data.get("activations")
        if isinstance(activations, list):
            data["activations"] = [
                row
                for row in activations
                if not isinstance(row, dict) or str(row.get("activation_id") or "") != activation_id
            ]
            self.save(data)

    def provider_failure_count(self, provider_id: str) -> int:
        failures = self.load().get("provider_failures")
        if not isinstance(failures, dict):
            return 0
        return _parse_int(failures.get(str(provider_id)))

    def record_failure(self, provider_id: str) -> None:
        data = self.load()
        failures = data.get("provider_failures")
        if not isinstance(failures, dict):
            failures = {}
            data["provider_failures"] = failures
        key = str(provider_id)
        failures[key] = _parse_int(failures.get(key)) + 1
        self.save(data)


class SMSBowerOtpProvider:
    def __init__(
        self,
        *,
        client: SMSBowerClientProtocol,
        store: SMSBowerActivationStore | None = None,
        service: str = SMSBOWER_DEFAULT_SERVICE,
        country: str = SMSBOWER_DEFAULT_COUNTRY,
        wait_seconds: float = SMSBOWER_DEFAULT_WAIT_SECONDS,
        poll_interval_seconds: float = SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS,
        max_channel_failures: int = SMSBOWER_DEFAULT_MAX_CHANNEL_FAILURES,
        activation_ttl_seconds: int = SMSBOWER_DEFAULT_ACTIVATION_TTL_SECONDS,
        max_attempts: int = SMSBOWER_DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self.client = client
        self.store = store or SMSBowerActivationStore()
        self.service = service
        self.country = country
        self.wait_seconds = max(1.0, float(wait_seconds)) if wait_seconds >= 1 else float(wait_seconds)
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.max_channel_failures = max(1, int(max_channel_failures))
        self.activation_ttl_seconds = max(60, int(activation_ttl_seconds))
        self.max_attempts = max(1, int(max_attempts))

    def reserve_number(self) -> SMSBowerActivation:
        reusable = self.store.reusable_activation(service=self.service, country=self.country)
        if reusable is not None:
            logger.info("Reusing active SMSBower phone from provider {}", reusable.provider_id)
            self._set_status(reusable.activation_id, 3)
            return reusable
        return self._purchase_new_number()

    def _purchase_new_number(self) -> SMSBowerActivation:
        prices = self._get_provider_prices()
        if not prices:
            raise SMSBowerApiError("SMSBower has no PayPal Brazil providers with available numbers")
        last_error: Exception | None = None
        for price in prices:
            if self.store.provider_failure_count(price.provider_id) >= self.max_channel_failures:
                logger.info("Skipping SMSBower provider {} after repeated failures", price.provider_id)
                continue
            try:
                data = self._get_number_v2(price)
                activation = SMSBowerActivation(
                    activation_id=str(data["activationId"]),
                    phone_number=normalize_brazil_phone(data["phoneNumber"]),
                    provider_id=str(data.get("activationOperator") or data.get("provider_id") or price.provider_id),
                    price=_parse_float(data.get("activationCost"), price.price),
                    expires_at=time.time() + self.activation_ttl_seconds,
                    reused=False,
                    provider_name="smsbower",
                    service=self.service,
                    country=self.country,
                )
                logger.info(
                    "Reserved SMSBower PayPal Brazil number provider={} price={}",
                    activation.provider_id,
                    activation.price,
                )
                return activation
            except Exception as exc:
                last_error = exc
                self.store.record_failure(price.provider_id)
                logger.warning("SMSBower provider {} failed: {}", price.provider_id, exc)
        if last_error is not None:
            raise SMSBowerApiError(f"SMSBower could not reserve a PayPal Brazil number: {last_error}") from last_error
        raise SMSBowerApiError("SMSBower providers are all blocked by failure thresholds")

    def mark_sms_sent(self, activation: SMSBowerActivation) -> None:
        if activation.reused:
            return
        self._set_status(activation.activation_id, 1)

    def wait_for_code(self, activation: SMSBowerActivation, timeout_seconds: float | None = None) -> str | None:
        deadline = time.time() + (self.wait_seconds if timeout_seconds is None else float(timeout_seconds))
        while time.time() <= deadline:
            status = self._get_status(activation.activation_id)
            code = self._code_from_status(status)
            if code:
                if activation.reused and activation.last_code and code == activation.last_code:
                    logger.debug("Ignoring stale SMSBower OTP code for reused activation {}", activation.activation_id)
                    time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.time())))
                    continue
                activation.last_code = code
                activation.use_count = int(activation.use_count or 0) + 1
                self.store.remember_success(
                    activation_id=activation.activation_id,
                    phone_number=activation.phone_number,
                    provider_id=activation.provider_id,
                    price=activation.price,
                    expires_at=activation.expires_at,
                    provider_name=activation.provider_name or "smsbower",
                    service=self.service,
                    country=self.country,
                    last_code=code,
                    increment_use=False,
                )
                return code
            if status in {"STATUS_CANCEL", "NO_ACTIVATION"}:
                self.store.abandon(activation.activation_id)
                return None
            time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.time())))
        return None

    def abandon(self, activation: SMSBowerActivation, reason: str) -> None:
        logger.warning(
            "Abandoning SMSBower activation provider={} reused={} reason={}",
            activation.provider_id,
            activation.reused,
            reason,
        )
        if _env_bool("PAYPAL_SMS_CANCEL_ON_ABANDON", default=not activation.reused):
            try:
                self._set_status(activation.activation_id, 8)
            except Exception as exc:
                logger.warning("SMSBower activation cancel failed: {}", exc)
            self.store.abandon(activation.activation_id)
        elif activation.reused:
            self.store.remember_activation(activation)
        self.store.record_failure(activation.provider_id)

    def register_confirmation_result(self, activation: SMSBowerActivation, confirmed: bool) -> None:
        if confirmed:
            self.store.remember_success(
                activation_id=activation.activation_id,
                phone_number=activation.phone_number,
                provider_id=activation.provider_id,
                price=activation.price,
                expires_at=activation.expires_at,
                provider_name=activation.provider_name or "smsbower",
                service=self.service,
                country=self.country,
                last_code=activation.last_code,
            )
            if not _env_bool("PAYPAL_SMS_FINALIZE_ON_SUCCESS", default=False):
                try:
                    self._set_status(activation.activation_id, 3)
                except Exception as exc:
                    logger.debug("SMSBower setStatus(3) after success soft-failed: {}", exc)
                return
            try:
                self._set_status(activation.activation_id, 6)
            except Exception as exc:
                logger.warning("SMSBower activation finalize failed: {}", exc)
            return
        self.abandon(activation, "paypal_rejected_code")

    def _get_provider_prices(self) -> list[SMSBowerProviderPrice]:
        values = self.client.get_provider_prices(self.service, self.country)
        prices: list[SMSBowerProviderPrice] = []
        for value in values:
            if isinstance(value, SMSBowerProviderPrice):
                prices.append(value)
            elif isinstance(value, dict):
                prices.append(
                    SMSBowerProviderPrice(
                        provider_id=str(value.get("provider_id") or ""),
                        price=_parse_float(value.get("price")),
                        count=_parse_int(value.get("count")),
                    )
                )
        return sorted(
            [item for item in prices if item.provider_id and item.count > 0],
            key=lambda item: (item.price, item.provider_id),
        )

    def _get_number_v2(self, price: SMSBowerProviderPrice) -> dict[str, object]:
        result = self.client.get_number_v2(
            service=self.service,
            country=self.country,
            provider_id=price.provider_id,
            max_price=price.price,
        )
        if isinstance(result, dict):
            return result
        raise SMSBowerApiError(f"Unexpected getNumberV2 response: {result!r}")

    def _get_status(self, activation_id: str) -> str:
        return str(self.client.get_status(activation_id))

    def _set_status(self, activation_id: str, status: int) -> str:
        return str(self.client.set_status(activation_id, status))

    @staticmethod
    def _code_from_status(status: str) -> str:
        if not status.startswith("STATUS_OK:"):
            return ""
        code = status.split(":", 1)[1].strip().strip("'").strip('"')
        match = re.search(r"\d{4,8}", code)
        return match.group(0) if match else code


def smsbower_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    provider = (_load_dotenv_value("PAYPAL_SMS_PROVIDER") or _load_dotenv_value("SMS_PROVIDER")).strip().lower()
    if provider:
        return provider == "smsbower"
    return _env_bool("PAYPAL_SMSBOWER_ENABLED") or _env_bool("SMSBOWER_ENABLED")


def build_smsbower_provider(*, enabled: bool | None = None, api_key: str | None = None) -> SMSBowerOtpProvider | None:
    if not smsbower_enabled(enabled):
        return None
    resolved_key = (
        api_key
        or _load_dotenv_value("SMSBOWER_API_KEY")
        or _load_dotenv_value("PAYPAL_SMSBOWER_API_KEY")
    )
    client = SMSBowerClient(resolved_key)
    return SMSBowerOtpProvider(
        client=client,
        wait_seconds=_env_float("SMSBOWER_WAIT_SECONDS", SMSBOWER_DEFAULT_WAIT_SECONDS, 1.0, 300.0),
        poll_interval_seconds=_env_float(
            "SMSBOWER_POLL_INTERVAL_SECONDS",
            SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS,
            0.2,
            30.0,
        ),
        max_channel_failures=_env_int(
            "SMSBOWER_MAX_CHANNEL_FAILURES",
            SMSBOWER_DEFAULT_MAX_CHANNEL_FAILURES,
            1,
            20,
        ),
        activation_ttl_seconds=_env_int(
            "SMSBOWER_ACTIVATION_TTL_SECONDS",
            SMSBOWER_DEFAULT_ACTIVATION_TTL_SECONDS,
            60,
            24 * 60 * 60,
        ),
        max_attempts=_env_int("SMSBOWER_MAX_ATTEMPTS", SMSBOWER_DEFAULT_MAX_ATTEMPTS, 1, 100),
    )


def activation_to_public_dict(activation: SMSBowerActivation) -> dict[str, object]:
    payload = asdict(activation)
    payload["phone_number"] = "*" * max(0, len(activation.phone_number) - 4) + activation.phone_number[-4:]
    return payload


def normalize_paypal_sms_provider(raw: object = "") -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"", "manual", "interactive", "none"}:
        return ""
    if value in {"sms_record", "smscc", "record", "fixed_url"}:
        return "sms_record"
    if value in {"hero", "herosms", "hero_sms"}:
        return "hero_sms"
    if value in {"hero_sms_rent", "herosms_rent", "hero_rent", "hero_long", "hero_sms_long"}:
        return "hero_sms_rent"
    if value in {"smsbower", "sms_bower"}:
        return "smsbower"
    return value


def normalize_paypal_sms_country(raw: object = "", *, paypal_country: str = "US") -> str:
    value = str(raw or "").strip().lower()
    if not value:
        paypal = str(paypal_country or "").strip().upper()
        return PAYPAL_SMS_COUNTRY_BY_PAYPAL_COUNTRY.get(paypal, PAYPAL_SMS_DEFAULT_COUNTRY)
    if value and re.fullmatch(r"\d+", value):
        return value
    if value in {"us", "usa", "united_states", "united states", "+1"}:
        return "187" if str(paypal_country or "").strip().upper() == "US" else PAYPAL_SMS_DEFAULT_COUNTRY
    if value in {"gb", "uk", "gbr", "united_kingdom", "united kingdom", "great_britain", "great britain", "+44"}:
        return "16"
    if value in {"nl", "nld", "netherlands", "holland", "nederland", "+31"}:
        return "48"
    if value in {"br", "bra", "brazil", "brasil", "+55"}:
        return "73"
    if value in {"ca", "can", "canada"}:
        return "36"
    if value in {"id", "idn", "indonesia", "+62"}:
        return "6"
    if value in {"jp", "jpn", "japan", "+81"}:
        return "182"
    if value in {"mx", "mex", "mexico"}:
        return "54"
    if value in {"ph", "phl", "philippines", "+63"}:
        return "4"
    if value in {"th", "tha", "thailand", "+66"}:
        return "52"
    if value in {"co", "colombia", "+57"}:
        return "33"
    return value


def normalize_sms_activate_phone(value: object, *, country: str) -> str:
    digits = _digits(value)
    if not digits:
        raise SMSBowerApiError("SMS provider returned an empty phone number")
    dial_code = PAYPAL_SMS_COUNTRY_DIAL_CODES.get(str(country or "").strip(), "")
    if dial_code and not digits.startswith(dial_code):
        digits = f"{dial_code}{digits}"
    return f"+{digits}"


class SmsActivateClient:
    """SMS-Activate compatible client used by HeroSMS and SMSBower."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise SMSBowerApiError("SMS provider API key is not configured")
        self.base_url = (base_url or "").strip() or SMSBOWER_API_URL
        self.timeout_seconds = timeout_seconds

    def request_text(self, action: str, params: dict[str, object] | None = None) -> str:
        query: dict[str, str] = {"api_key": self.api_key, "action": action}
        for key, value in (params or {}).items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                query[key] = text
        with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds), trust_env=False) as client:
            response = client.get(self.base_url, params=query)
        text = (response.text or "").strip()
        if response.status_code >= 400:
            raise _safe_api_error(action, response.status_code, text)
        if text in {"BAD_KEY", "BAD_ACTION", "BAD_SERVICE", "BAD_COUNTRY"}:
            raise SMSBowerApiError(text)
        return text

    def request_json_or_text(self, action: str, params: dict[str, object] | None = None) -> object:
        text = self.request_text(action, params)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def get_status(self, activation_id: str) -> str:
        return self.request_text("getStatus", {"id": activation_id})

    def set_status(self, activation_id: str, status: int) -> str:
        return self.request_text("setStatus", {"id": activation_id, "status": status})


class SmsActivateOtpProvider:
    """Acquire PayPal OTP numbers through a SMS-Activate compatible API."""

    def __init__(
        self,
        *,
        client: SmsActivateClient,
        provider_name: str,
        store: SMSBowerActivationStore | None = None,
        service: str = PAYPAL_SMS_DEFAULT_SERVICE,
        country: str = PAYPAL_SMS_DEFAULT_COUNTRY,
        wait_seconds: float = SMSBOWER_DEFAULT_WAIT_SECONDS,
        poll_interval_seconds: float = SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS,
        activation_ttl_seconds: int = SMSBOWER_DEFAULT_ACTIVATION_TTL_SECONDS,
        max_attempts: int = SMSBOWER_DEFAULT_MAX_ATTEMPTS,
        min_price: str = "",
        max_price: str = "",
        preferred_price: str = "",
        reuse_enabled: bool = True,
        reuse_max_uses: int = 5,
        finalize_on_success: bool = False,
        cancel_on_abandon: bool = False,
    ) -> None:
        self.client = client
        self.provider_name = normalize_paypal_sms_provider(provider_name) or provider_name
        self.store = store or SMSBowerActivationStore(_project_root() / "cache" / "paypal_sms_activate_numbers.json")
        self.service = str(service or PAYPAL_SMS_DEFAULT_SERVICE).strip()
        self.country = str(country or PAYPAL_SMS_DEFAULT_COUNTRY).strip()
        self.wait_seconds = max(1.0, float(wait_seconds)) if wait_seconds >= 1 else float(wait_seconds)
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.activation_ttl_seconds = max(60, int(activation_ttl_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.min_price = str(min_price or "").strip()
        self.max_price = str(max_price or "").strip()
        self.preferred_price = str(preferred_price or "").strip()
        self.reuse_enabled = bool(reuse_enabled)
        self.reuse_max_uses = max(1, int(reuse_max_uses))
        self.finalize_on_success = bool(finalize_on_success)
        self.cancel_on_abandon = bool(cancel_on_abandon)

    def reserve_number(self) -> SMSBowerActivation:
        if self.reuse_enabled:
            reusable = self.store.reusable_activation(
                provider_name=self.provider_name,
                service=self.service,
                country=self.country,
                max_uses=self.reuse_max_uses,
            )
            if reusable is not None:
                logger.info(
                    "Reusing active {} phone country={} service={} activation={} uses={}",
                    self.provider_name,
                    self.country,
                    self.service,
                    reusable.activation_id,
                    reusable.use_count,
                )
                try:
                    self.client.set_status(reusable.activation_id, 3)
                except Exception as exc:
                    logger.debug("{} setStatus(3) for reused number soft-failed: {}", self.provider_name, exc)
                return reusable
        params = self._number_params()
        payload = self._request_number(params)
        activation = self._activation_from_payload(payload)
        logger.info(
            "Reserved {} PayPal number country={} service={} activation={} price={}",
            self.provider_name,
            self.country,
            self.service,
            activation.activation_id,
            activation.price,
        )
        return activation

    def _number_params(self) -> dict[str, object]:
        params: dict[str, object] = {"service": self.service, "country": self.country}
        if self.min_price and self.preferred_price and self.min_price == self.preferred_price:
            params["minPrice"] = self.preferred_price
            params["maxPrice"] = self.preferred_price
        elif self.preferred_price:
            params["maxPrice"] = self.preferred_price
        else:
            if self.min_price:
                params["minPrice"] = self.min_price
            if self.max_price:
                params["maxPrice"] = self.max_price
        return params

    def _request_number(self, params: dict[str, object]) -> object:
        last_error = ""
        for action in ("getNumberV2", "getNumber"):
            try:
                payload = self.client.request_json_or_text(action, params)
            except Exception as exc:
                last_error = str(exc)
                continue
            activation_id, phone = self._parse_number_payload(payload)
            if activation_id and phone:
                return payload
            text = str(payload or "").strip()
            last_error = text or f"{action} returned empty response"
            if re.search(r"\b(?:NO_NUMBERS|WRONG_MAX_PRICE|NO_BALANCE|BAD_KEY|BAD_SERVICE|BAD_COUNTRY|NO_ACTIVATION)\b", last_error, re.I):
                continue
        raise SMSBowerApiError(f"{self.provider_name} could not reserve PayPal number: {last_error}")

    def _activation_from_payload(self, payload: object) -> SMSBowerActivation:
        activation_id, phone = self._parse_number_payload(payload)
        if not activation_id or not phone:
            raise SMSBowerApiError(f"Unexpected getNumber response: {payload!r}")
        price = 0.0
        provider_id = self.provider_name
        if isinstance(payload, dict):
            price = _parse_float(
                payload.get("activationCost")
                or payload.get("price")
                or payload.get("cost")
                or payload.get("activation_cost")
            )
            provider_id = str(payload.get("activationOperator") or payload.get("operator") or provider_id)
        return SMSBowerActivation(
            activation_id=activation_id,
            phone_number=normalize_sms_activate_phone(phone, country=self.country),
            provider_id=provider_id,
            price=price,
            expires_at=time.time() + self.activation_ttl_seconds,
            reused=False,
            provider_name=self.provider_name,
            service=self.service,
            country=self.country,
        )

    @staticmethod
    def _parse_number_payload(payload: object) -> tuple[str, str]:
        if isinstance(payload, dict):
            activation_id = str(
                payload.get("activationId")
                or payload.get("activation_id")
                or payload.get("id")
                or ""
            ).strip()
            phone = str(
                payload.get("phoneNumber")
                or payload.get("phone")
                or payload.get("number")
                or ""
            ).strip()
            return activation_id, phone
        line = str(payload or "").strip()
        if line.upper().startswith("ACCESS_NUMBER:"):
            parts = line.split(":", 2)
            if len(parts) >= 3:
                return parts[1].strip(), parts[2].strip()
        return "", ""

    def mark_sms_sent(self, activation: SMSBowerActivation) -> None:
        # SMS-Activate-compatible APIs use status=1 as "SMS sent" in many
        # implementations; HeroSMS docs only require 3/6/8, so failure here is
        # non-fatal.
        try:
            self.client.set_status(activation.activation_id, 1)
        except Exception as exc:
            logger.debug("{} setStatus(1) soft-failed: {}", self.provider_name, exc)

    def wait_for_code(self, activation: SMSBowerActivation, timeout_seconds: float | None = None) -> str | None:
        deadline = time.time() + (self.wait_seconds if timeout_seconds is None else float(timeout_seconds))
        while time.time() <= deadline:
            try:
                status = self.client.get_status(activation.activation_id)
            except Exception as exc:
                logger.debug("{} getStatus soft-failed: {}", self.provider_name, exc)
                status = ""
            code = SMSBowerOtpProvider._code_from_status(status)
            if code:
                if activation.reused and activation.last_code and code == activation.last_code:
                    logger.debug("Ignoring stale {} OTP code for reused activation {}", self.provider_name, activation.activation_id)
                    time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.time())))
                    continue
                activation.last_code = code
                activation.use_count = int(activation.use_count or 0) + 1
                if self.reuse_enabled:
                    self.store.remember_activation(activation, last_code=code, increment_use=False)
                return code
            if str(status or "").strip().upper() in {"STATUS_CANCEL", "NO_ACTIVATION", "ACCESS_CANCEL"}:
                self.store.abandon(activation.activation_id)
                return None
            time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.time())))
        return None

    def abandon(self, activation: SMSBowerActivation, reason: str) -> None:
        logger.warning(
            "Abandoning {} activation provider={} reason={}",
            self.provider_name,
            activation.provider_id,
            reason,
        )
        if str(reason or "").strip().lower() == "sms_timeout":
            # A timed-out number must not be selected again in the same auto
            # OTP flow.  The caller expects "60 seconds without an OTP" to mean
            # "switch to a different number"; keeping it in the reusable cache
            # causes reserve_number() to immediately pick the same activation
            # again.
            self.store.abandon(activation.activation_id)
            self.store.record_failure(activation.provider_id)
            if not activation.reused:
                try:
                    self.client.set_status(activation.activation_id, 8)
                except Exception as exc:
                    logger.debug("{} activation cancel after sms_timeout soft-failed: {}", self.provider_name, exc)
            logger.info("{} activation={} removed from reuse cache after sms_timeout", self.provider_name, activation.activation_id)
            return
        if self.cancel_on_abandon and not activation.reused:
            try:
                self.client.set_status(activation.activation_id, 8)
            except Exception as exc:
                logger.warning("{} activation cancel failed: {}", self.provider_name, exc)
            self.store.abandon(activation.activation_id)
        elif self.reuse_enabled:
            self.store.remember_activation(activation)
            logger.info("Keeping {} activation={} reusable after {}", self.provider_name, activation.activation_id, reason)
        else:
            self.store.record_failure(activation.provider_id)

    def register_confirmation_result(self, activation: SMSBowerActivation, confirmed: bool) -> None:
        if confirmed:
            if self.reuse_enabled:
                self.store.remember_activation(activation)
            if self.finalize_on_success:
                try:
                    self.client.set_status(activation.activation_id, 6)
                except Exception as exc:
                    logger.warning("{} activation finalize failed: {}", self.provider_name, exc)
            else:
                try:
                    self.client.set_status(activation.activation_id, 3)
                except Exception as exc:
                    logger.debug("{} setStatus(3) after success soft-failed: {}", self.provider_name, exc)
            return
        if self.cancel_on_abandon:
            try:
                self.client.set_status(activation.activation_id, 8)
            except Exception as exc:
                logger.warning("{} activation cancel failed: {}", self.provider_name, exc)
            self.store.abandon(activation.activation_id)
        elif self.reuse_enabled:
            self.store.remember_activation(activation)


def _sms_provider_base_url(provider: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    if provider in {"hero_sms", "hero_sms_rent"}:
        return (
            _load_dotenv_value("PAYPAL_HERO_SMS_BASE_URL")
            or _load_dotenv_value("PAYPAL_HEROSMS_BASE_URL")
            or _load_dotenv_value("OAUTH_HERO_SMS_BASE_URL")
            or _load_dotenv_value("GOPAY_AUTO_SIGNUP_HERO_SMS_BASE_URL")
            or HEROSMS_API_URL
        )
    return (
        _load_dotenv_value("PAYPAL_SMSBOWER_BASE_URL")
        or _load_dotenv_value("SMSBOWER_BASE_URL")
        or _load_dotenv_value("OAUTH_SMSBOWER_BASE_URL")
        or _load_dotenv_value("GOPAY_AUTO_SIGNUP_SMSBOWER_BASE_URL")
        or SMSBOWER_API_URL
    )


def _sms_provider_api_key(provider: str, explicit: str | None = None) -> str:
    if explicit:
        return str(explicit).strip()
    if provider in {"hero_sms", "hero_sms_rent"}:
        return (
            _load_dotenv_value("PAYPAL_HEROSMS_API_KEY")
            or _load_dotenv_value("PAYPAL_HERO_SMS_API_KEY")
            or _load_dotenv_value("HERO_SMS_API_KEY")
            or _load_dotenv_value("HEROSMS_API_KEY")
            or _load_dotenv_value("OAUTH_HERO_SMS_API_KEY")
            or _load_dotenv_value("GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY")
        )
    return (
        _load_dotenv_value("PAYPAL_SMSBOWER_API_KEY")
        or _load_dotenv_value("SMSBOWER_API_KEY")
        or _load_dotenv_value("OAUTH_SMSBOWER_API_KEY")
        or _load_dotenv_value("GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY")
    )


def _sms_provider_country(provider: str, paypal_country: str, explicit: str = "") -> str:
    if explicit:
        return normalize_paypal_sms_country(explicit, paypal_country=paypal_country)
    paypal = str(paypal_country or "").strip().upper()
    hero_provider = provider in {"hero_sms", "hero_sms_rent"}
    env_prefixes = (
        ("PAYPAL_HERO_SMS", "PAYPAL_HEROSMS")
        if hero_provider
        else ("PAYPAL_SMSBOWER",)
    )
    for prefix in env_prefixes:
        country = _load_dotenv_value(f"{prefix}_COUNTRY_{paypal}")
        if country:
            return normalize_paypal_sms_country(country, paypal_country=paypal)
    return PAYPAL_SMS_COUNTRY_BY_PAYPAL_COUNTRY.get(paypal, PAYPAL_SMS_DEFAULT_COUNTRY)


def build_sms_activate_provider(
    *,
    provider: str,
    enabled: bool | None = None,
    api_key: str | None = None,
    base_url: str = "",
    service: str = "",
    country: str = "",
    paypal_country: str = "US",
    wait_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
    min_price: str = "",
    max_price: str = "",
    preferred_price: str = "",
) -> SmsActivateOtpProvider | None:
    normalized = normalize_paypal_sms_provider(provider)
    if normalized not in {"hero_sms", "hero_sms_rent", "smsbower"}:
        return None
    if enabled is False:
        return None
    resolved_key = _sms_provider_api_key(normalized, api_key)
    resolved_base_url = _sms_provider_base_url(normalized, base_url or _load_dotenv_value(f"PAYPAL_{normalized.upper()}_BASE_URL"))
    resolved_service = str(
        service
        or _load_dotenv_value("PAYPAL_SMS_SERVICE")
        or _load_dotenv_value(f"PAYPAL_{normalized.upper()}_SERVICE")
        or PAYPAL_SMS_DEFAULT_SERVICE
    ).strip()
    resolved_country = _sms_provider_country(normalized, paypal_country, country)
    return SmsActivateOtpProvider(
        client=SmsActivateClient(resolved_key, base_url=resolved_base_url),
        provider_name=normalized,
        store=SMSBowerActivationStore(_project_root() / "cache" / f"paypal_{normalized}_numbers.json"),
        service=resolved_service,
        country=resolved_country,
        wait_seconds=wait_seconds
        if wait_seconds is not None
        else _env_float("PAYPAL_SMS_WAIT_SECONDS", SMSBOWER_DEFAULT_WAIT_SECONDS, 1.0, 900.0),
        poll_interval_seconds=poll_interval_seconds
        if poll_interval_seconds is not None
        else _env_float("PAYPAL_SMS_POLL_INTERVAL_SECONDS", SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS, 0.2, 30.0),
        activation_ttl_seconds=_env_int(
            "PAYPAL_SMS_ACTIVATION_TTL_SECONDS",
            SMSBOWER_DEFAULT_ACTIVATION_TTL_SECONDS,
            60,
            24 * 60 * 60,
        ),
        max_attempts=_env_int("PAYPAL_SMS_MAX_ATTEMPTS", SMSBOWER_DEFAULT_MAX_ATTEMPTS, 1, 100),
        min_price=min_price or _load_dotenv_value("PAYPAL_SMS_MIN_PRICE"),
        max_price=max_price or _load_dotenv_value("PAYPAL_SMS_MAX_PRICE"),
        preferred_price=preferred_price or _load_dotenv_value("PAYPAL_SMS_PREFERRED_PRICE"),
        reuse_enabled=_env_bool("PAYPAL_SMS_REUSE_ENABLED", default=True),
        reuse_max_uses=_env_int("PAYPAL_SMS_REUSE_MAX_USES", 5, 1, 50),
        finalize_on_success=_env_bool("PAYPAL_SMS_FINALIZE_ON_SUCCESS", default=False),
        cancel_on_abandon=_env_bool("PAYPAL_SMS_CANCEL_ON_ABANDON", default=False),
    )


def _hero_sms_web_base_url() -> str:
    return (
        _load_dotenv_value("PAYPAL_HERO_SMS_WEB_BASE_URL")
        or _load_dotenv_value("PAYPAL_HEROSMS_WEB_BASE_URL")
        or _load_dotenv_value("HERO_SMS_WEB_BASE_URL")
        or "https://hero-sms.com"
    ).rstrip("/")


class HeroSmsWebClient:
    """Small client for HeroSMS' browser REST API.

    The public API key used by ``stubs/handler_api.php`` does not authenticate
    browser REST endpoints such as ``/api/v1/activations``.  These endpoints
    require the same authenticated browser session cookies as the web UI.
    """

    def __init__(
        self,
        *,
        base_url: str = "",
        cookie: str = "",
        bearer_token: str = "",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.base_url = (base_url or _hero_sms_web_base_url()).rstrip("/")
        self.cookie = str(cookie or "").strip()
        self.bearer_token = str(bearer_token or "").strip()
        self.timeout_seconds = timeout_seconds

    @property
    def has_credentials(self) -> bool:
        return bool(self.cookie or self.bearer_token)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> object:
        if not self.has_credentials:
            raise SMSBowerApiError("HeroSMS web session is not configured")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        url = self.base_url + (path if path.startswith("/") else f"/{path}")
        with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds), follow_redirects=True, trust_env=False) as client:
            response = client.request(method.upper(), url, params=params, json=body, headers=headers)
        if response.status_code >= 400:
            raise _safe_api_error(f"{method.upper()} {path}", response.status_code, response.text)
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise SMSBowerApiError(f"HeroSMS web API returned non-JSON for {path}: {response.text[:120]}") from exc

    def get_active_activations(self) -> object:
        return self.request_json("GET", "/api/v1/activations", params={"page": 1, "size": 100})

    def get_activation(self, activation_id: str) -> object:
        return self.request_json("GET", f"/api/v1/activations/{activation_id}")

    def patch_sms(self) -> object:
        return self.request_json("PATCH", "/api/v1/get-sms")

    def request_extra_sms(self, activation_id: str) -> object:
        return self.request_json("POST", f"/api/v1/activations/{activation_id}/request-extra-sms")


def _load_hero_sms_web_client() -> HeroSmsWebClient | None:
    cookie = (
        _load_dotenv_value("PAYPAL_HERO_SMS_COOKIE")
        or _load_dotenv_value("PAYPAL_HEROSMS_COOKIE")
        or _load_dotenv_value("HERO_SMS_COOKIE")
    )
    bearer = (
        _load_dotenv_value("PAYPAL_HERO_SMS_BEARER_TOKEN")
        or _load_dotenv_value("PAYPAL_HEROSMS_BEARER_TOKEN")
        or _load_dotenv_value("HERO_SMS_BEARER_TOKEN")
    )
    client = HeroSmsWebClient(cookie=cookie, bearer_token=bearer)
    return client if client.has_credentials else None


class HeroSmsRentOtpProvider:
    """Use an already-purchased HeroSMS long-term/rental number for PayPal OTP."""

    def __init__(
        self,
        *,
        client: SmsActivateClient,
        phone_number: str,
        activation_id: str = "",
        store: SMSBowerActivationStore | None = None,
        web_client: HeroSmsWebClient | None = None,
        country: str = PAYPAL_SMS_DEFAULT_COUNTRY,
        wait_seconds: float = SMSBOWER_DEFAULT_WAIT_SECONDS,
        poll_interval_seconds: float = SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.client = client
        phone_text, inline_activation_id = self._split_phone_activation_ref(phone_number)
        self.phone_number = normalize_sms_activate_phone(phone_text, country=country)
        self.activation_id = str(activation_id or inline_activation_id or "").strip()
        self.store = store or SMSBowerActivationStore(_project_root() / "cache" / "paypal_hero_sms_rent_numbers.json")
        self.web_client = web_client
        self.country = str(country or PAYPAL_SMS_DEFAULT_COUNTRY).strip()
        self.wait_seconds = max(1.0, float(wait_seconds)) if wait_seconds >= 1 else float(wait_seconds)
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.max_attempts = 1

    @staticmethod
    def _split_phone_activation_ref(value: object) -> tuple[str, str]:
        text = str(value or "").strip()
        for sep in ("#", "|", ","):
            if sep in text:
                phone, ref = text.split(sep, 1)
                ref = ref.strip()
                if ref:
                    return phone.strip(), ref
        match = re.match(r"(?i)^\s*id[:=]([A-Za-z0-9_-]+)\s+(.+)$", text)
        if match:
            return match.group(2).strip(), match.group(1).strip()
        return text, ""

    def reserve_number(self) -> SMSBowerActivation:
        rent_id = self._find_rent_id_by_phone()
        if not rent_id:
            raise SMSBowerApiError(
                "HeroSMS rent number not found in reusable cache/web session: "
                f"{self._masked_phone()}. Configure PAYPAL_HERO_SMS_RENT_ACTIVATION_ID, "
                "enter '<phone>#<activation_id>', or configure PAYPAL_HERO_SMS_COOKIE for web REST lookup."
            )
        return SMSBowerActivation(
            activation_id=rent_id,
            phone_number=self.phone_number,
            provider_id="hero_sms_rent",
            price=0.0,
            expires_at=time.time() + 24 * 60 * 60,
            reused=True,
            provider_name="hero_sms_rent",
            country=self.country,
        )

    def _masked_phone(self) -> str:
        return "*" * max(0, len(self.phone_number) - 4) + self.phone_number[-4:]

    def _find_rent_id_by_phone(self) -> str:
        if self.activation_id:
            return self.activation_id
        env_id = (
            _load_dotenv_value("PAYPAL_HERO_SMS_RENT_ACTIVATION_ID")
            or _load_dotenv_value("PAYPAL_HEROSMS_RENT_ACTIVATION_ID")
            or _load_dotenv_value("HERO_SMS_RENT_ACTIVATION_ID")
        )
        if env_id:
            return env_id.strip()
        reusable = self.store.reusable_activation(
            provider_name="hero_sms_rent",
            country=self.country,
            phone_number=self.phone_number,
        ) or SMSBowerActivationStore(_project_root() / "cache" / "paypal_hero_sms_numbers.json").reusable_activation(
            provider_name="hero_sms",
            country=self.country,
            phone_number=self.phone_number,
        )
        if reusable is not None:
            return reusable.activation_id
        if self.web_client is not None:
            try:
                payload = self.web_client.get_active_activations()
                rent_id = self._rent_id_from_payload(payload)
                if rent_id:
                    return rent_id
            except Exception as exc:
                logger.debug("HeroSMS web activation lookup soft-failed: {}", exc)
        if not _env_bool("PAYPAL_HERO_SMS_RENT_ALLOW_LEGACY_ACTIONS", default=False):
            return ""
        for action in ("getRentList", "getRentStatus"):
            try:
                payload = self.client.request_json_or_text(action, {} if action == "getRentList" else {"phone": self.phone_number})
            except Exception as exc:
                logger.debug("HeroSMS rent {} lookup soft-failed: {}", action, exc)
                continue
            rent_id = self._rent_id_from_payload(payload)
            if rent_id:
                return rent_id
        return ""

    def _rent_id_from_payload(self, payload: object) -> str:
        phone_digits = _digits(self.phone_number)

        def walk(value: object) -> str:
            if isinstance(value, dict):
                value_phone = _digits(
                    value.get("phone")
                    or value.get("phoneNumber")
                    or value.get("number")
                    or value.get("phone_number")
                )
                if value_phone and value_phone.endswith(phone_digits[-10:]):
                    rent_id = str(
                        value.get("id")
                        or value.get("rentId")
                        or value.get("rent_id")
                        or value.get("activationId")
                        or value.get("activation_id")
                        or ""
                    ).strip()
                    if rent_id:
                        return rent_id
                for child in value.values():
                    found = walk(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = walk(child)
                    if found:
                        return found
            return ""

        return walk(payload)

    def mark_sms_sent(self, activation: SMSBowerActivation) -> None:
        try:
            self.client.set_status(activation.activation_id, 3)
        except Exception as exc:
            logger.debug("HeroSMS rent setStatus(3) soft-failed: {}", exc)
        if self.web_client is not None:
            try:
                self.web_client.request_extra_sms(activation.activation_id)
            except Exception as exc:
                logger.debug("HeroSMS rent request-extra-sms soft-failed: {}", exc)

    def wait_for_code(self, activation: SMSBowerActivation, timeout_seconds: float | None = None) -> str | None:
        deadline = time.time() + (self.wait_seconds if timeout_seconds is None else float(timeout_seconds))
        while time.time() <= deadline:
            try:
                payload: object = self.client.get_status(activation.activation_id)
            except Exception as exc:
                logger.debug("HeroSMS rent getStatus soft-failed: {}", exc)
                payload = ""
            code = self._code_from_payload(payload)
            if not code and self.web_client is not None:
                try:
                    self.web_client.patch_sms()
                except Exception as exc:
                    logger.debug("HeroSMS patchSMS soft-failed: {}", exc)
                try:
                    payload = self.web_client.get_activation(activation.activation_id)
                    code = self._code_from_payload(payload)
                except Exception as exc:
                    logger.debug("HeroSMS web activation status soft-failed: {}", exc)
            if code:
                if activation.last_code and code == activation.last_code:
                    logger.debug("Ignoring stale HeroSMS rent OTP code for activation {}", activation.activation_id)
                    time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.time())))
                    continue
                activation.last_code = code
                self.store.remember_activation(activation, last_code=code, increment_use=False)
                return code
            time.sleep(min(self.poll_interval_seconds, max(0.0, deadline - time.time())))
        return None

    def _code_from_payload(self, payload: object) -> str:
        if isinstance(payload, str):
            return SMSBowerOtpProvider._code_from_status(payload)
        if isinstance(payload, dict):
            for key in ("code", "smsCode", "sms_code", "otp"):
                code = str(payload.get(key) or "").strip()
                if re.fullmatch(r"\d{4,8}", code):
                    return code
            for key in ("text", "sms", "message", "lastSms"):
                text = str(payload.get(key) or "")
                match = re.search(r"\d{4,8}", text)
                if match:
                    return match.group(0)
            for child in payload.values():
                code = self._code_from_payload(child)
                if code:
                    return code
        if isinstance(payload, list):
            for child in payload:
                code = self._code_from_payload(child)
                if code:
                    return code
        return ""

    def abandon(self, activation: SMSBowerActivation, reason: str) -> None:
        self.store.remember_activation(activation, increment_use=False)
        logger.info("Keeping HeroSMS rent activation={} reason={}", activation.activation_id, reason)

    def register_confirmation_result(self, activation: SMSBowerActivation, confirmed: bool) -> None:
        self.store.remember_activation(activation, increment_use=confirmed)
        try:
            self.client.set_status(activation.activation_id, 3)
        except Exception as exc:
            logger.debug("HeroSMS rent setStatus(3) after confirmation soft-failed: {}", exc)
        logger.info("HeroSMS rent activation={} confirmed={}", activation.activation_id, confirmed)


def build_hero_sms_rent_provider(
    *,
    phone_number: str,
    api_key: str | None = None,
    base_url: str = "",
    country: str = "",
    paypal_country: str = "US",
    wait_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
) -> HeroSmsRentOtpProvider:
    resolved_key = _sms_provider_api_key("hero_sms_rent", api_key)
    resolved_base_url = _sms_provider_base_url("hero_sms_rent", base_url or _load_dotenv_value("PAYPAL_HERO_SMS_BASE_URL"))
    resolved_country = _sms_provider_country("hero_sms_rent", paypal_country, country)
    return HeroSmsRentOtpProvider(
        client=SmsActivateClient(resolved_key, base_url=resolved_base_url),
        phone_number=phone_number,
        activation_id=(
            _load_dotenv_value("PAYPAL_HERO_SMS_RENT_ACTIVATION_ID")
            or _load_dotenv_value("PAYPAL_HEROSMS_RENT_ACTIVATION_ID")
            or _load_dotenv_value("HERO_SMS_RENT_ACTIVATION_ID")
        ),
        store=SMSBowerActivationStore(_project_root() / "cache" / "paypal_hero_sms_rent_numbers.json"),
        web_client=_load_hero_sms_web_client(),
        country=resolved_country,
        wait_seconds=wait_seconds
        if wait_seconds is not None
        else _env_float("PAYPAL_SMS_WAIT_SECONDS", SMSBOWER_DEFAULT_WAIT_SECONDS, 1.0, 900.0),
        poll_interval_seconds=poll_interval_seconds
        if poll_interval_seconds is not None
        else _env_float("PAYPAL_SMS_POLL_INTERVAL_SECONDS", SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS, 0.2, 30.0),
    )
