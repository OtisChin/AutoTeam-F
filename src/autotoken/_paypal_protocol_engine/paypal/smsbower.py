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
PAYPAL_SMS_COUNTRY_BY_PAYPAL_COUNTRY = {"US": "187", "GB": "16", "NL": "48", "BR": "73"}
PAYPAL_SMS_COUNTRY_DIAL_CODES = {
    "12": "1",
    "187": "1",
    "16": "44",
    "48": "31",
    "73": "55",
    "6": "62",
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

    def reusable_activation(self, now: float | None = None) -> SMSBowerActivation | None:
        now = time.time() if now is None else now
        data = self.load()
        activations = data.get("activations")
        if not isinstance(activations, list):
            return None
        fresh_rows: list[dict[str, object]] = []
        selected: SMSBowerActivation | None = None
        for row in activations:
            if not isinstance(row, dict):
                continue
            expires_at = _parse_float(row.get("expires_at"))
            if expires_at <= now:
                continue
            fresh_rows.append(row)
            if selected is None:
                selected = SMSBowerActivation(
                    activation_id=str(row.get("activation_id") or ""),
                    phone_number=str(row.get("phone_number") or ""),
                    provider_id=str(row.get("provider_id") or ""),
                    price=_parse_float(row.get("price")),
                    expires_at=expires_at,
                    reused=True,
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
    ) -> None:
        data = self.load()
        activations = data.get("activations")
        rows = [row for row in activations if isinstance(row, dict)] if isinstance(activations, list) else []
        rows = [row for row in rows if str(row.get("activation_id") or "") != activation_id]
        rows.insert(
            0,
            {
                "activation_id": activation_id,
                "phone_number": phone_number,
                "provider_id": provider_id,
                "price": price,
                "expires_at": expires_at,
            },
        )
        data["activations"] = rows[:20]
        failures = data.get("provider_failures")
        if isinstance(failures, dict):
            failures[str(provider_id)] = 0
        self.save(data)

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
        reusable = self.store.reusable_activation()
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
                self.store.remember_success(
                    activation_id=activation.activation_id,
                    phone_number=activation.phone_number,
                    provider_id=activation.provider_id,
                    price=activation.price,
                    expires_at=activation.expires_at,
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
        try:
            self._set_status(activation.activation_id, 8)
        except Exception as exc:
            logger.warning("SMSBower activation cancel failed: {}", exc)
        self.store.abandon(activation.activation_id)
        self.store.record_failure(activation.provider_id)

    def register_confirmation_result(self, activation: SMSBowerActivation, confirmed: bool) -> None:
        if confirmed:
            self.store.remember_success(
                activation_id=activation.activation_id,
                phone_number=activation.phone_number,
                provider_id=activation.provider_id,
                price=activation.price,
                expires_at=activation.expires_at,
            )
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
        return {"US": "187", "GB": "16", "NL": "48", "BR": "73"}.get(paypal, PAYPAL_SMS_DEFAULT_COUNTRY)
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
    if value in {"id", "idn", "indonesia", "+62"}:
        return "6"
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
        service: str = PAYPAL_SMS_DEFAULT_SERVICE,
        country: str = PAYPAL_SMS_DEFAULT_COUNTRY,
        wait_seconds: float = SMSBOWER_DEFAULT_WAIT_SECONDS,
        poll_interval_seconds: float = SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS,
        activation_ttl_seconds: int = SMSBOWER_DEFAULT_ACTIVATION_TTL_SECONDS,
        max_attempts: int = SMSBOWER_DEFAULT_MAX_ATTEMPTS,
        min_price: str = "",
        max_price: str = "",
        preferred_price: str = "",
    ) -> None:
        self.client = client
        self.provider_name = normalize_paypal_sms_provider(provider_name) or provider_name
        self.service = str(service or PAYPAL_SMS_DEFAULT_SERVICE).strip()
        self.country = str(country or PAYPAL_SMS_DEFAULT_COUNTRY).strip()
        self.wait_seconds = max(1.0, float(wait_seconds)) if wait_seconds >= 1 else float(wait_seconds)
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.activation_ttl_seconds = max(60, int(activation_ttl_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.min_price = str(min_price or "").strip()
        self.max_price = str(max_price or "").strip()
        self.preferred_price = str(preferred_price or "").strip()

    def reserve_number(self) -> SMSBowerActivation:
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
                return code
            if str(status or "").strip().upper() in {"STATUS_CANCEL", "NO_ACTIVATION", "ACCESS_CANCEL"}:
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
        try:
            self.client.set_status(activation.activation_id, 8)
        except Exception as exc:
            logger.warning("{} activation cancel failed: {}", self.provider_name, exc)

    def register_confirmation_result(self, activation: SMSBowerActivation, confirmed: bool) -> None:
        try:
            self.client.set_status(activation.activation_id, 6 if confirmed else 8)
        except Exception as exc:
            logger.warning("{} activation finalize failed: {}", self.provider_name, exc)


def _sms_provider_base_url(provider: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    if provider in {"hero_sms", "hero_sms_rent"}:
        return HEROSMS_API_URL
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
    )


class HeroSmsRentOtpProvider:
    """Use an already-purchased HeroSMS long-term/rental number for PayPal OTP."""

    def __init__(
        self,
        *,
        client: SmsActivateClient,
        phone_number: str,
        country: str = PAYPAL_SMS_DEFAULT_COUNTRY,
        wait_seconds: float = SMSBOWER_DEFAULT_WAIT_SECONDS,
        poll_interval_seconds: float = SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.client = client
        self.phone_number = normalize_sms_activate_phone(phone_number, country=country)
        self.country = str(country or PAYPAL_SMS_DEFAULT_COUNTRY).strip()
        self.wait_seconds = max(1.0, float(wait_seconds)) if wait_seconds >= 1 else float(wait_seconds)
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.max_attempts = 1

    def reserve_number(self) -> SMSBowerActivation:
        rent_id = self._find_rent_id_by_phone()
        if not rent_id:
            raise SMSBowerApiError(f"HeroSMS rent number not found in active rents: {self._masked_phone()}")
        return SMSBowerActivation(
            activation_id=rent_id,
            phone_number=self.phone_number,
            provider_id="hero_sms_rent",
            price=0.0,
            expires_at=time.time() + 24 * 60 * 60,
            reused=True,
        )

    def _masked_phone(self) -> str:
        return "*" * max(0, len(self.phone_number) - 4) + self.phone_number[-4:]

    def _find_rent_id_by_phone(self) -> str:
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
        _ = activation

    def wait_for_code(self, activation: SMSBowerActivation, timeout_seconds: float | None = None) -> str | None:
        deadline = time.time() + (self.wait_seconds if timeout_seconds is None else float(timeout_seconds))
        while time.time() <= deadline:
            try:
                payload = self.client.request_json_or_text("getRentStatus", {"id": activation.activation_id})
            except Exception as exc:
                logger.debug("HeroSMS getRentStatus soft-failed: {}", exc)
                payload = ""
            code = self._code_from_payload(payload)
            if code:
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
        logger.info("Keeping HeroSMS rent activation={} reason={}", activation.activation_id, reason)

    def register_confirmation_result(self, activation: SMSBowerActivation, confirmed: bool) -> None:
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
        country=resolved_country,
        wait_seconds=wait_seconds
        if wait_seconds is not None
        else _env_float("PAYPAL_SMS_WAIT_SECONDS", SMSBOWER_DEFAULT_WAIT_SECONDS, 1.0, 900.0),
        poll_interval_seconds=poll_interval_seconds
        if poll_interval_seconds is not None
        else _env_float("PAYPAL_SMS_POLL_INTERVAL_SECONDS", SMSBOWER_DEFAULT_POLL_INTERVAL_SECONDS, 0.2, 30.0),
    )
