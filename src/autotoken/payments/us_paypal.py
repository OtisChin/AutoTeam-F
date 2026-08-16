"""US PayPal checkout link extraction core."""

from __future__ import annotations

import random
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from curl_cffi.requests import Session as CurlCffiSession

from autotoken.payments.brazil_pix import (
    DEFAULT_STRIPE_PK,
    DEFAULT_USER_AGENT,
    TIMEOUT,
    build_kookeey_proxy,
    extract_pk,
    pix_proxy_context,
    pix_proxy_with_fresh_sid,
    short,
    to_openai_pay_url,
)

LogFn = Callable[[str], None]

PAYPAL_STRIPE_VERSION = "2020-08-27;custom_checkout_beta=v1; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
PAYPAL_STRIPE_RUNTIME_VERSION = "81274c9437"
PAYPAL_BA_APPROVE_BASE = "https://www.paypal.com/agreements/approve"
PAYPAL_CHECKOUT_SESSION_PREFIXES = ("cs_",)
PAYPAL_BA_TOKEN_RE = re.compile(r"(?i)ba_token[=:%22'\\\s]+(?P<token>BA-[A-Za-z0-9_-]+)")
PAYPAL_BA_APPROVE_RE = re.compile(
    r"(?i)(?:(?:https?:)?//)?(?:www\.)?paypal\.com/agreements/approve\?[^\\\s\"'<>]*?ba_token=(?P<token>BA-[A-Za-z0-9_-]+)"
)

US_ADDRESSES = [
    # Prefer states without statewide sales tax so ChatGPT approval and Stripe amount stay aligned.
    ('John', 'Miller', '1307 Shallcross Avenue', 'Wilmington', 'DE', '19806'),
    ('Sarah', 'Clark', '214 S Bradford Street', 'Dover', 'DE', '19904'),
    ('Emily', 'Lewis', '705 N Harrison Street', 'Wilmington', 'DE', '19805'),
    ('James', 'Anderson', '38 W Park Place', 'Newark', 'DE', '19711'),
    ('Robert', 'Thomas', '127 Delaware Avenue', 'Lewes', 'DE', '19958'),
    ('Michael', 'Harris', '24 Lake Avenue', 'Rehoboth Beach', 'DE', '19971'),
    ('Jennifer', 'Walker', '317 N Walnut Street', 'Milford', 'DE', '19963'),
    ('David', 'Young', '19 Columbia Avenue', 'New Castle', 'DE', '19720'),
    ('Ashley', 'King', '407 S Bedford Street', 'Georgetown', 'DE', '19947'),
    ('Matthew', 'Wright', '83 E Green Street', 'Middletown', 'DE', '19709'),
    ('Amanda', 'Lopez', '62 N Union Street', 'Smyrna', 'DE', '19977'),
    ('Daniel', 'Hill', '118 W 6th Street', 'Laurel', 'DE', '19956'),
    ('Jessica', 'Scott', '44 Chestnut Street', 'Milton', 'DE', '19968'),
    ('Andrew', 'Green', '236 S State Street', 'Dover', 'DE', '19901'),
    ('Mary', 'Adams', '15 W Commerce Street', 'Smyrna', 'DE', '19977'),
    ('William', 'Baker', '506 W 7th Street', 'Wilmington', 'DE', '19801'),
    ('Lauren', 'Nelson', '121 Academy Street', 'Newark', 'DE', '19711'),
    ('Joseph', 'Carter', '72 Park Avenue', 'Seaford', 'DE', '19973'),
    ('Megan', 'Mitchell', '29 The Strand', 'New Castle', 'DE', '19720'),
    ('Elizabeth', 'Perez', '208 W Pine Street', 'Georgetown', 'DE', '19947'),
    ('John', 'Miller', '91 Kings Highway', 'Lewes', 'DE', '19958'),
    ('Sarah', 'Clark', '64 Hickman Street', 'Rehoboth Beach', 'DE', '19971'),
    ('Emily', 'Lewis', '312 N Church Street', 'Milford', 'DE', '19963'),
    ('James', 'Anderson', '46 W Frazier Street', 'Smyrna', 'DE', '19977'),
    ('Robert', 'Thomas', '203 Delaware Street', 'New Castle', 'DE', '19720'),
    ('Michael', 'Harris', '48 School Street', 'Concord', 'NH', '03301'),
    ('Jennifer', 'Walker', '12 Ash Street', 'Portsmouth', 'NH', '03801'),
    ('David', 'Young', '73 Pine Street', 'Manchester', 'NH', '03103'),
    ('Ashley', 'King', '19 Grove Street', 'Peterborough', 'NH', '03458'),
    ('Matthew', 'Wright', '142 Pleasant Street', 'Concord', 'NH', '03301'),
    ('Amanda', 'Lopez', '31 Court Street', 'Exeter', 'NH', '03833'),
    ('Daniel', 'Hill', '86 Hanover Street', 'Lebanon', 'NH', '03766'),
    ('Jessica', 'Scott', '27 Summer Street', 'Dover', 'NH', '03820'),
    ('Andrew', 'Green', '114 Maple Street', 'Keene', 'NH', '03431'),
    ('Mary', 'Adams', '55 Central Street', 'Claremont', 'NH', '03743'),
    ('William', 'Baker', '18 High Street', 'Plymouth', 'NH', '03264'),
    ('Lauren', 'Nelson', '92 Union Street', 'Littleton', 'NH', '03561'),
    ('Joseph', 'Carter', '146 Pearl Street', 'Manchester', 'NH', '03104'),
    ('Megan', 'Mitchell', '33 Lincoln Avenue', 'Portsmouth', 'NH', '03801'),
    ('Elizabeth', 'Perez', '65 Franklin Street', 'Concord', 'NH', '03301'),
    ('John', 'Miller', '24 Grove Street', 'Dover', 'NH', '03820'),
    ('Sarah', 'Clark', '138 Water Street', 'Exeter', 'NH', '03833'),
    ('Emily', 'Lewis', '57 Roxbury Street', 'Keene', 'NH', '03431'),
    ('James', 'Anderson', '81 Pleasant Street', 'Laconia', 'NH', '03246'),
    ('Robert', 'Thomas', '39 Washington Street', 'Rochester', 'NH', '03867'),
    ('Michael', 'Harris', '204 Main Street', 'Nashua', 'NH', '03060'),
    ('Jennifer', 'Walker', '17 Prospect Street', 'Hanover', 'NH', '03755'),
    ('David', 'Young', '76 Elm Street', 'Milford', 'NH', '03055'),
    ('Ashley', 'King', '28 Park Street', 'Berlin', 'NH', '03570'),
    ('Matthew', 'Wright', '101 High Street', 'Somersworth', 'NH', '03878'),
    ('Amanda', 'Lopez', '718 S 3rd Street W', 'Missoula', 'MT', '59801'),
    ('Daniel', 'Hill', '311 N Tracy Avenue', 'Bozeman', 'MT', '59715'),
    ('Jessica', 'Scott', '92 S Rodney Street', 'Helena', 'MT', '59601'),
    ('Andrew', 'Green', '514 4th Avenue N', 'Great Falls', 'MT', '59401'),
    ('Mary', 'Adams', '1719 Poly Drive', 'Billings', 'MT', '59102'),
    ('William', 'Baker', '836 2nd Avenue E', 'Kalispell', 'MT', '59901'),
    ('Lauren', 'Nelson', '409 W Granite Street', 'Butte', 'MT', '59701'),
    ('Joseph', 'Carter', '122 S Yellowstone Street', 'Livingston', 'MT', '59047'),
    ('Megan', 'Mitchell', '215 S 7th Street', 'Miles City', 'MT', '59301'),
    ('Elizabeth', 'Perez', '64 Highland Park Drive', 'Havre', 'MT', '59501'),
    ('John', 'Miller', '928 Gerald Avenue', 'Missoula', 'MT', '59801'),
    ('Sarah', 'Clark', '47 W Koch Street', 'Bozeman', 'MT', '59715'),
    ('Emily', 'Lewis', '203 N Benton Avenue', 'Helena', 'MT', '59601'),
    ('James', 'Anderson', '725 3rd Avenue N', 'Great Falls', 'MT', '59401'),
    ('Robert', 'Thomas', '2502 1st Avenue N', 'Billings', 'MT', '59101'),
    ('Michael', 'Harris', '319 5th Street E', 'Kalispell', 'MT', '59901'),
    ('Jennifer', 'Walker', '37 W Silver Street', 'Butte', 'MT', '59701'),
    ('David', 'Young', '109 S H Street', 'Livingston', 'MT', '59047'),
    ('Ashley', 'King', '713 Palmer Street', 'Miles City', 'MT', '59301'),
    ('Matthew', 'Wright', '426 3rd Street', 'Havre', 'MT', '59501'),
    ('Amanda', 'Lopez', '1420 S 5th Street W', 'Missoula', 'MT', '59801'),
    ('Daniel', 'Hill', '611 W Story Street', 'Bozeman', 'MT', '59715'),
    ('Jessica', 'Scott', '416 N Ewing Street', 'Helena', 'MT', '59601'),
    ('Andrew', 'Green', '1801 4th Avenue N', 'Great Falls', 'MT', '59401'),
    ('Mary', 'Adams', '612 Clark Avenue', 'Billings', 'MT', '59101'),
    ('William', 'Baker', '2834 SE Belmont Street', 'Portland', 'OR', '97214'),
    ('Lauren', 'Nelson', '1340 Ferry Street', 'Eugene', 'OR', '97401'),
    ('Joseph', 'Carter', '721 NW 23rd Avenue', 'Portland', 'OR', '97210'),
    ('Megan', 'Mitchell', '364 Lincoln Street', 'Ashland', 'OR', '97520'),
    ('Elizabeth', 'Perez', '524 NW 10th Street', 'Corvallis', 'OR', '97330'),
    ('John', 'Miller', '1820 NE 8th Street', 'Bend', 'OR', '97701'),
    ('Sarah', 'Clark', '77 High Street SE', 'Salem', 'OR', '97301'),
    ('Emily', 'Lewis', '421 Siskiyou Boulevard', 'Ashland', 'OR', '97520'),
    ('James', 'Anderson', '936 Oak Street', 'Hood River', 'OR', '97031'),
    ('Robert', 'Thomas', '210 Washington Street', 'The Dalles', 'OR', '97058'),
    ('Michael', 'Harris', '1580 Pearl Street', 'Eugene', 'OR', '97401'),
    ('Jennifer', 'Walker', '622 NW 12th Avenue', 'Portland', 'OR', '97209'),
    ('David', 'Young', '425 NW 6th Street', 'Corvallis', 'OR', '97330'),
    ('Ashley', 'King', '1445 NW Harmon Boulevard', 'Bend', 'OR', '97703'),
    ('Matthew', 'Wright', '286 Chemeketa Street NE', 'Salem', 'OR', '97301'),
    ('Amanda', 'Lopez', '91 N 2nd Street', 'Ashland', 'OR', '97520'),
    ('Daniel', 'Hill', '1105 Columbia Street', 'Hood River', 'OR', '97031'),
    ('Jessica', 'Scott', '417 E 7th Street', 'The Dalles', 'OR', '97058'),
    ('Andrew', 'Green', '1955 Potter Street', 'Eugene', 'OR', '97405'),
    ('Mary', 'Adams', '2534 NE 32nd Avenue', 'Portland', 'OR', '97212'),
    ('William', 'Baker', '1045 NW Van Buren Avenue', 'Corvallis', 'OR', '97330'),
    ('Lauren', 'Nelson', '608 NW Congress Street', 'Bend', 'OR', '97703'),
    ('Joseph', 'Carter', '742 Mill Street SE', 'Salem', 'OR', '97301'),
    ('Megan', 'Mitchell', '137 Morton Street', 'Ashland', 'OR', '97520'),
    ('Elizabeth', 'Perez', '1309 Pine Street', 'Hood River', 'OR', '97031'),
]

PAYPAL_COUNTRY_CURRENCIES = {
    "BA": "EUR",
    "US": "USD",
    "GB": "GBP",
    "CA": "CAD",
    "AU": "AUD",
    "JP": "JPY",
    "BR": "BRL",
    "ID": "IDR",
    "VN": "VND",
    "TH": "THB",
    "PH": "PHP",
    "TR": "USD",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "NL": "EUR",
    "IE": "EUR",
    "PT": "EUR",
    "AT": "EUR",
    "BE": "EUR",
    "FI": "EUR",
    "SG": "SGD",
    "HK": "HKD",
    "TW": "TWD",
    "KR": "KRW",
    "MX": "MXN",
    "NZ": "NZD",
}

PAYPAL_COUNTRY_BILLING_PRESETS = {
    "GB": ("Olivia Brown", "221B Baker Street", "London", "", "NW1 6XE"),
    "CA": ("Noah Wilson", "100 Queen Street W", "Toronto", "ON", "M5H 2N2"),
    "AU": ("Charlotte Taylor", "42 Victoria Street", "Paddington", "NSW", "2021"),
    "JP": ("Yuki Tanaka", "1-1 Chiyoda", "Tokyo", "", "100-0001"),
    "BR": ("Lucas Silva", "Rua da Consolacao 787", "Sao Paulo", "SP", "01301-000"),
    "ID": ("Adi Pratama", "Jalan Kemang Raya 12", "Jakarta Selatan", "DKI Jakarta", "12730"),
    "VN": ("Minh Nguyen", "1 Dong Khoi", "Ho Chi Minh City", "", "700000"),
    "TH": ("Niran Chai", "1 Sukhumvit Road", "Bangkok", "", "10110"),
    "PH": ("Miguel Santos", "120 Makati Avenue", "Makati", "Metro Manila", "1210"),
    "TR": ("Ahmet Yilmaz", "Istiklal Caddesi 1", "Istanbul", "", "34433"),
    "DE": ("Lukas Weber", "Unter den Linden 1", "Berlin", "", "10117"),
    "FR": ("Emma Martin", "10 Rue de Rivoli", "Paris", "", "75004"),
    "IT": ("Marco Rossi", "Via del Corso 1", "Rome", "", "00186"),
    "ES": ("Lucia Garcia", "Calle de Alcala 1", "Madrid", "", "28014"),
    "NL": ("Daan de Vries", "Eerste Jan Steenstraat 84", "Amsterdam", "Noord-Holland", "1072 NP"),
    "SG": ("Wei Tan", "1 Raffles Place", "Singapore", "", "048616"),
    "HK": ("Ho Chan", "1 Connaught Road Central", "Hong Kong", "", "000000"),
    "TW": ("Chen Lin", "No. 1 Xinyi Road", "Taipei", "", "100"),
    "KR": ("Min Kim", "1 Sejong-daero", "Seoul", "", "04524"),
    "MX": ("Sofia Hernandez", "Avenida Reforma 1", "Ciudad de Mexico", "", "06000"),
    "NZ": ("Amelia Smith", "1 Queen Street", "Auckland", "", "1010"),
}

PAYPAL_COUNTRY_BILLING_ALIASES = {
    "BA": "DE",
    "BR": "DE",
    "ID": "DE",
    "JP": "DE",
    "TH": "DE",
    "TR": "US",
}

PAYPAL_CHECKOUT_BILLING_ALIASES = {
    "BA": "DE",
    "BR": "DE",
    "ID": "DE",
    "JP": "DE",
    "TH": "DE",
    "TR": "US",
}


@dataclass
class PaypalJobConfig:
    access_token: str
    local_proxy: str = ""
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = "US"
    promo_region: str = "JP"
    direct_proxies: list[str] = field(default_factory=list)
    apply_promo: bool = False
    preflighted_checkout_proxy_url: str = ""
    preflighted_promo_proxy_url: str = ""
    only_oaics: bool = False


class PaypalOnlyOaicsSkipped(RuntimeError):
    """Raised when only-oaics mode sees a non-OAICS checkout session."""


def normalize_paypal_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    parts = raw.split(":", 3)
    if len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        return f"socks5h://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return f"http://{raw}"


def paypal_proxy_with_fresh_sid(proxy_url: str, region: str = "US") -> tuple[str, str]:
    fresh = uuid.uuid4().hex[:8]
    target_region = str(region or "US").strip().upper() or "US"
    proxy = str(proxy_url or "").strip()
    if not proxy:
        return "", ""

    refreshed, region_count = re.subn(
        r"([_-]region[-_])[A-Z]{2}([:@/?#&-])",
        lambda m: f"{m.group(1)}{target_region}{m.group(2)}",
        proxy,
        count=1,
        flags=re.I,
    )
    refreshed, sid_count = re.subn(r"(sid-)[^-:@/?#]+(-t-)", rf"\g<1>{fresh}\g<2>", refreshed, count=1, flags=re.I)
    refreshed, session_count = re.subn(
        r"(-session-)[^-:@/?#]+",
        rf"\g<1>{fresh}",
        refreshed,
        count=1,
        flags=re.I,
    )
    if sid_count or session_count:
        return refreshed, fresh

    if "711proxy" in refreshed.lower() and "-session-" not in refreshed.lower():
        refreshed_with_session, injected_count = re.subn(
            r"([_-]region[-_][A-Z]{2})(?=[:@/?#&-])",
            rf"\g<1>-session-{fresh}-sessTime-180-sessAuto-1",
            refreshed,
            count=1,
            flags=re.I,
        )
        if injected_count:
            return refreshed_with_session, fresh

    refreshed_kookeey, kookeey_count = re.subn(
        r"(:[^:@/?#]*-)[A-Z]{2}-[A-Za-z0-9]{4,32}(@)",
        lambda m: f"{m.group(1)}{target_region}-{fresh}{m.group(2)}",
        refreshed,
        count=1,
        flags=re.I,
    )
    if kookeey_count:
        return refreshed_kookeey, fresh

    refreshed_ipweb, ipweb_count = re.subn(
        r"(B_\d+_)[A-Z]{2}(_(?:[^:@/?#]*_)*[A-Za-z0-9]+)(?=[:@/?#])",
        lambda m: f"{m.group(1)}{target_region}{m.group(2)}",
        refreshed,
        count=1,
        flags=re.I,
    )
    if ipweb_count:
        return refreshed_ipweb, "static"

    if region_count:
        return refreshed, "static"

    proxy_fallback, sid = pix_proxy_with_fresh_sid(proxy, target_region)
    if sid != "static":
        return proxy_fallback, sid
    return proxy_fallback, sid


def align_paypal_proxy_region(proxy_url: str, region: str = "US") -> str:
    target = str(region or "US").strip().upper() or "US"
    return re.sub(
        r"([_-]region[-_])[A-Z]{2}([:@/?#&-])",
        lambda m: f"{m.group(1)}{target}{m.group(2)}",
        proxy_url,
        count=1,
        flags=re.I,
    )


def build_paypal_dynamic_proxy(cfg: PaypalJobConfig, stage_index: int, region: str | None = None) -> tuple[str, str]:
    target_region = str(region or cfg.region or "US").strip().upper() or "US"
    preflighted = normalize_paypal_proxy_url(getattr(cfg, "preflighted_checkout_proxy_url", ""))
    if stage_index == 0 and preflighted and target_region == (str(cfg.region or "US").strip().upper() or "US"):
        return preflighted, f"preflighted region={target_region}"
    preflighted_promo = normalize_paypal_proxy_url(getattr(cfg, "preflighted_promo_proxy_url", ""))
    if preflighted_promo and target_region == (str(cfg.promo_region or "JP").strip().upper() or "JP"):
        return preflighted_promo, f"preflighted region={target_region}"
    direct = [
        align_paypal_proxy_region(normalize_paypal_proxy_url(item), target_region)
        for item in (cfg.direct_proxies or [])
        if str(item or "").strip()
    ]
    if direct:
        idx = stage_index % len(direct)
        proxy, sid = paypal_proxy_with_fresh_sid(direct[idx], target_region)
        suffix = f" sid={sid}" if sid and sid != "static" else " static"
        return proxy, f"direct-{idx + 1} region={target_region}{suffix}"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, target_region)


def new_http_session(proxy_url: str = "") -> requests.Session:
    try:
        session = CurlCffiSession(impersonate="chrome136")
    except Exception:
        session = requests.Session()
    if hasattr(session, "trust_env"):
        session.trust_env = False
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


def build_chatgpt_session(access_token: str, proxy_url: str = "", device_id: str = "") -> requests.Session:
    device_id = str(device_id or uuid.uuid4())
    session = new_http_session(proxy_url)
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": "en-US",
            "sec-ch-ua": '"Google Chrome";v="146", "Chromium";v="146", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )
    return session


def _browser_timezone_offset_min() -> int:
    local_utc_offset_seconds = -time.timezone
    if time.daylight and time.localtime().tm_isdst > 0:
        local_utc_offset_seconds = -time.altzone
    return int(-local_utc_offset_seconds / 60)


def warm_chatgpt_checkout_context(chatgpt: requests.Session, country: str, log: LogFn | None = None) -> None:
    """Prime ChatGPT backend context before creating a payment checkout."""

    log = log or (lambda _m: None)
    getter = getattr(chatgpt, "get", None)
    poster = getattr(chatgpt, "post", None)
    if not callable(getter):
        return
    target_country = normalize_paypal_country(country, "US")
    warmups = [
        (
            f"https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min={_browser_timezone_offset_min()}",
            "/backend-api/accounts/check/v4-2023-04-27",
        ),
        ("https://chatgpt.com/backend-api/accounts/domain-density-eligibility", "/backend-api/accounts/domain-density-eligibility"),
        ("https://chatgpt.com/backend-api/checkout_pricing_config/countries", "/backend-api/checkout_pricing_config/countries"),
        (
            f"https://chatgpt.com/backend-api/checkout_pricing_config/configs/{target_country}",
            f"/backend-api/checkout_pricing_config/configs/{target_country}",
        ),
    ]
    statuses: list[str] = []
    for url, target_path in warmups:
        try:
            resp = getter(
                url,
                headers={"x-openai-target-path": target_path, "x-openai-target-route": target_path},
                timeout=8,
            )
            statuses.append(f"{target_path.rsplit('/', 1)[-1]}={getattr(resp, 'status_code', 0)}")
        except Exception as exc:
            statuses.append(f"{target_path.rsplit('/', 1)[-1]}={type(exc).__name__}")
    if callable(poster):
        try:
            resp = poster(
                "https://chatgpt.com/backend-api/sentinel/ping",
                json={},
                headers={
                    "x-openai-target-path": "/backend-api/sentinel/ping",
                    "x-openai-target-route": "/backend-api/sentinel/ping",
                },
                timeout=8,
            )
            statuses.append(f"sentinel={getattr(resp, 'status_code', 0)}")
        except Exception as exc:
            statuses.append(f"sentinel={type(exc).__name__}")
    log("checkout warmup: " + " ".join(statuses))


def build_stripe_session(proxy_url: str = "") -> requests.Session:
    session = new_http_session(proxy_url)
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://pay.openai.com",
            "Referer": "https://pay.openai.com/",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }
    )
    return session


def normalize_paypal_country(value: str, default: str = "US") -> str:
    country = str(value or default or "US").strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else default


def paypal_currency_for_country(country: str) -> str:
    country_code = normalize_paypal_country(country)
    billing_country = PAYPAL_COUNTRY_BILLING_ALIASES.get(country_code, country_code)
    return PAYPAL_COUNTRY_CURRENCIES.get(billing_country, "USD")


def paypal_checkout_billing_details_for_country(country: str) -> dict[str, str]:
    country_code = normalize_paypal_country(country)
    checkout_country = PAYPAL_CHECKOUT_BILLING_ALIASES.get(country_code, country_code)
    return {
        "country": checkout_country,
        "currency": PAYPAL_COUNTRY_CURRENCIES.get(checkout_country, "USD"),
    }


def paypal_billing(account_email: str = "", country: str = "US") -> dict[str, str]:
    country_code = normalize_paypal_country(country)
    billing_country = PAYPAL_COUNTRY_BILLING_ALIASES.get(country_code, country_code)
    if billing_country != "US" and billing_country in PAYPAL_COUNTRY_BILLING_PRESETS:
        name, line1, city, state, postal = PAYPAL_COUNTRY_BILLING_PRESETS[billing_country]
        return {
            "name": name,
            "email": account_email or f"paypal.{country_code.lower()}.{random.randint(1000, 9999)}@example.com",
            "country": billing_country,
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal,
        }
    first, last, line1, city, state, postal = random.choice(US_ADDRESSES)
    suffix = random.randint(1000, 9999)
    return {
        "name": f"{first} {last}",
        "email": account_email or f"{first.lower()}.{last.lower()}{suffix}@example.com",
        "country": billing_country,
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal,
    }


def us_billing(account_email: str = "") -> dict[str, str]:
    return paypal_billing(account_email, "US")


def pmt_info(payload: dict[str, Any]) -> tuple[list[Any], list[Any], bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    methods = [str(item).lower() for item in list(pmt) + list(ordered)]
    return pmt, ordered, "paypal" in methods


def amount_info(payload: dict[str, Any]) -> str:
    total_summary = payload.get("total_summary") if isinstance(payload.get("total_summary"), dict) else {}
    invoice = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else {}
    if total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    if invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    return "0"


def is_zero_amount(value: Any) -> bool:
    text = str(value if value is not None else "").strip()
    if not text:
        return False
    try:
        return float(text) == 0.0
    except Exception:
        return text in {"0", "0.0", "0.00"}


def is_checkout_session_id(value: Any) -> bool:
    return str(value or "").startswith(PAYPAL_CHECKOUT_SESSION_PREFIXES)


def is_openai_custom_checkout_session_id(value: Any) -> bool:
    return str(value or "").startswith("oaics_")


def promo_currency_for_region(region: str) -> str:
    return {"JP": "JPY", "GB": "GBP", "BR": "BRL", "VN": "VND", "TH": "THB", "PH": "PHP", "TR": "USD"}.get(str(region or "").strip().upper(), "USD")


def _ctx() -> dict[str, str]:
    return {
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


def stripe_init(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data={
            "browser_locale": "en-US",
            "browser_timezone": "America/Los_Angeles",
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[locale]": "en-US",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": PAYPAL_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"stripe init failed: HTTP {resp.status_code} {short(resp.text)}")
    data = resp.json() or {}
    ctx["config_id"] = str(data.get("config_id") or ctx.get("config_id") or "")
    ctx["init_checksum"] = str(data.get("init_checksum") or "")
    ctx["elements_session_config_id"] = str(data.get("config_id") or ctx.get("elements_session_config_id") or uuid.uuid4())
    return data


def stripe_update_tax_region(stripe: requests.Session, cs_id: str, stripe_pk: str, billing: dict[str, str]) -> None:
    bodies = [{"eid": "NA", "tax_region[country]": billing["country"], "key": stripe_pk}]
    if billing.get("state"):
        bodies.append({"eid": "NA", "tax_region[country]": billing["country"], "tax_region[state]": billing["state"], "key": stripe_pk})
    for body in bodies:
        resp = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}", data=body, timeout=TIMEOUT)
        if resp.status_code >= 400:
            raise RuntimeError(f"stripe tax region update failed: HTTP {resp.status_code} {short(resp.text)}")


def page_get(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict[str, str]) -> dict[str, Any]:
    resp = stripe.get(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}",
        params={
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[session_id]": ctx["elements_session_id"],
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[locale]": "en-US",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": PAYPAL_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"payment_pages get failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def find_submission_attempt(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("submission_attempt", "latest_attempt", "submission"):
        val = payload.get(key)
        if isinstance(val, dict) and val:
            return val
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    val = session.get("submission_attempt")
    return val if isinstance(val, dict) else {}


def _iter_text_values(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, str):
        values.append(payload)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                values.append(key)
            if isinstance(value, (str, int, float)):
                values.append(f"{key}={value}")
            values.extend(_iter_text_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_text_values(item))
    return values


def is_paypal_ba_approve_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if not (host == "paypal.com" or host.endswith(".paypal.com")):
        return False
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return parsed.path.rstrip("/").lower() == "/agreements/approve" and bool(str(query.get("ba_token") or "").strip())


def paypal_ba_approve_url_from_token(token: str) -> str:
    token = str(token or "").strip().strip(" \t\r\n\"'<>),.;]}")
    return f"{PAYPAL_BA_APPROVE_BASE}?ba_token={quote(token, safe='')}" if token else ""


def extract_paypal_ba_approve_url(payload: Any) -> str:
    for raw in _iter_text_values(payload):
        text = str(raw or "").replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")
        try:
            text = unquote(text)
        except Exception:
            pass
        if is_paypal_ba_approve_url(text):
            token = dict(parse_qsl(urlsplit(text).query, keep_blank_values=True)).get("ba_token") or ""
            return paypal_ba_approve_url_from_token(unquote(token))
        for pattern in (PAYPAL_BA_APPROVE_RE, PAYPAL_BA_TOKEN_RE):
            match = pattern.search(text)
            if match:
                return paypal_ba_approve_url_from_token(unquote(match.group("token")))
    return ""


def find_redirect_url_string(payload: Any, preferred_hosts: tuple[str, ...] = ()) -> str:
    preferred = tuple(host.lower().lstrip(".") for host in preferred_hosts if host)

    def good_url(value: str) -> bool:
        if not value.startswith(("http://", "https://")):
            return False
        host = (urlsplit(value).netloc or "").lower()
        return not preferred or any(host == item or host.endswith(f".{item}") for item in preferred)

    if isinstance(payload, str):
        value = payload.strip()
        return value if good_url(value) else ""
    if isinstance(payload, dict):
        for key in ("url", "redirect_url", "return_url", "hosted_url"):
            found = find_redirect_url_string(payload.get(key), preferred_hosts)
            if found:
                return found
        for value in payload.values():
            found = find_redirect_url_string(value, preferred_hosts)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = find_redirect_url_string(value, preferred_hosts)
            if found:
                return found
    return ""


def extract_redirect_to_url(payload: Any) -> str:
    ba_approve_url = extract_paypal_ba_approve_url(payload)
    if ba_approve_url:
        return ba_approve_url
    if isinstance(payload, dict):
        next_action = payload.get("next_action")
        if isinstance(next_action, dict) and next_action.get("type") == "redirect_to_url":
            redirect_to_url = next_action.get("redirect_to_url") or {}
            if isinstance(redirect_to_url, dict) and str(redirect_to_url.get("url") or "").strip():
                return str(redirect_to_url.get("url") or "").strip()
        for key in ("setup_intent", "payment_intent", "submission_attempt", "latest_attempt", "session"):
            found = extract_redirect_to_url(payload.get(key))
            if found:
                return found
        nested_url = find_redirect_url_string(payload, ("pm-redirects.stripe.com", "paypal.com"))
        if nested_url and "docs/error-codes" not in nested_url:
            return nested_url
    return ""


def extract_paypal_result(payload: Any, cs_id: str = "") -> dict[str, str]:
    redirect_url = extract_redirect_to_url(payload)
    fields = {
        "paypal_link": "",
        "provider_redirect_url": "",
        "stripe_redirect_url": "",
        "ba_token": "",
        "cs_id": cs_id,
        "submission_state": "",
        "next_action_type": "",
        "setup_intent": "",
    }
    if is_paypal_ba_approve_url(redirect_url):
        fields["paypal_link"] = fields["provider_redirect_url"] = redirect_url
    elif redirect_url:
        fields["stripe_redirect_url"] = redirect_url
        if "pm-redirects.stripe.com" in redirect_url:
            fields["paypal_link"] = redirect_url
    token_match = re.search(r"BA-[A-Za-z0-9_-]+", fields["provider_redirect_url"] or fields["paypal_link"])
    if token_match:
        fields["ba_token"] = token_match.group(0)
    if isinstance(payload, dict):
        sub = find_submission_attempt(payload)
        fields["submission_state"] = str(sub.get("state") or "")
        setup_intent = payload.get("setup_intent")
        if isinstance(setup_intent, dict):
            fields["setup_intent"] = str(setup_intent.get("id") or "")
        next_action = payload.get("next_action")
        if isinstance(next_action, dict):
            fields["next_action_type"] = str(next_action.get("type") or "")
    return fields


def is_success(fields: dict[str, Any]) -> bool:
    link = str(fields.get("paypal_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or "")
    return link.startswith("https://pm-redirects.stripe.com/authorize/") or is_paypal_ba_approve_url(link)


def finalize_bound_paypal_result(
    stripe: requests.Session,
    fields: dict[str, Any],
    *,
    link_source: str,
) -> bool:
    """Resolve and accept only a PayPal BA redirect produced by this checkout.

    Stripe's standalone Express Billing Agreement endpoint can return a valid
    looking ``BA-*`` approval URL without taking the current OpenAI checkout
    session id. Those links are not sufficient evidence that the agreement is
    bound to ChatGPT/OpenAI billing. The accepted path here is narrower: a
    redirect must come from ``payment_pages/{cs_id}/confirm`` or from the
    subsequent ChatGPT approve + Stripe poll for the same ``cs_id``.
    """

    candidate = str(fields.get("paypal_link") or fields.get("provider_redirect_url") or fields.get("stripe_redirect_url") or "").strip()
    if not candidate:
        return False
    provider = resolve_external_redirect(stripe, candidate)
    if not provider:
        provider = candidate
    if not is_paypal_ba_approve_url(provider):
        return False
    fields["provider_redirect_url"] = provider
    fields["paypal_link"] = provider
    token_match = re.search(r"BA-[A-Za-z0-9_-]+", provider)
    fields["ba_token"] = token_match.group(0) if token_match else str(fields.get("ba_token") or "")
    fields["link_source"] = link_source
    fields["link_binding"] = "chatgpt_checkout_session"
    return True


def resolve_external_redirect(stripe: requests.Session, redirect_url: str, max_hops: int = 5) -> str:
    current = str(redirect_url or "").strip()
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        ba_approve_url = extract_paypal_ba_approve_url(current)
        if ba_approve_url:
            return ba_approve_url
        host = (urlsplit(current).netloc or "").lower()
        if host == "paypal.com" or host.endswith(".paypal.com"):
            return current
        try:
            response = stripe.get(current, allow_redirects=False, timeout=TIMEOUT)
        except Exception:
            return current
        ba_approve_url = extract_paypal_ba_approve_url({"url": current, "location": response.headers.get("Location", ""), "body": response.text})
        if ba_approve_url:
            return ba_approve_url
        if response.status_code not in (301, 302, 303, 307, 308):
            return current
        location = str(response.headers.get("Location") or "").strip()
        if not location:
            return current
        current = urljoin(current, location)
    return current


def paypal_return_url(cs_id: str, processor: str, hosted_url: str) -> str:
    base = to_openai_pay_url(hosted_url) or hosted_url or f"https://pay.openai.com/c/pay/{cs_id}"
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["redirect_pm_type"] = "paypal"
    query["lid"] = str(uuid.uuid4())
    query["ui_mode"] = "custom"
    return urlunsplit((parsed.scheme or "https", parsed.netloc or "pay.openai.com", parsed.path, urlencode(query), parsed.fragment))


def _walk_payload_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_payload_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_payload_dicts(nested)


def _nested_string(payload: Any, names: tuple[str, ...], *, prefixes: tuple[str, ...] = ()) -> str:
    for item in _walk_payload_dicts(payload):
        for name in names:
            value = item.get(name)
            if isinstance(value, str):
                text = value.strip()
                if text and (not prefixes or text.startswith(prefixes)):
                    return text
    return ""


def _minor_amount(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if re.fullmatch(r"[+-]?\d+(?:\.0+)?", text):
        return int(text.split(".", 1)[0])
    if isinstance(value, dict):
        for key in ("minorUnitsAmount", "minor_units_amount", "amount", "value"):
            parsed = _minor_amount(value.get(key))
            if parsed is not None:
                return parsed
    return None


def oaics_amount_observations(payload: Any) -> list[tuple[str, int]]:
    paths = (
        ("checkout_amount_minor",),
        ("total_summary", "due"),
        ("totalSummary", "due"),
        ("invoice", "amount_due"),
        ("invoice", "amountDue"),
        ("amount_due",),
        ("amountDue",),
        ("amount_total",),
        ("amountTotal",),
        ("total", "total"),
        ("total", "due"),
        ("total", "taxInclusive"),
        ("total", "taxInclusiveAmount"),
    )
    found: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in _walk_payload_dicts(payload):
        for path in paths:
            current: Any = item
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    current = None
                    break
                current = current.get(key)
            amount = _minor_amount(current)
            if amount is None:
                continue
            marker = (".".join(path), amount)
            if marker not in seen:
                seen.add(marker)
                found.append(marker)
    return found


def verify_oaics_zero_snapshot(payload: Any, *, cs_id: str, currency: str) -> int:
    observations = oaics_amount_observations(payload)
    if not observations:
        raise RuntimeError(f"OAICS 未返回可核验的应付金额: {cs_id}")
    nonzero = [(label, amount) for label, amount in observations if amount != 0]
    if nonzero:
        detail = ", ".join(f"{label}={amount}" for label, amount in nonzero)
        raise RuntimeError(f"PayPal 金额必须为 0: {detail} {str(currency or '').upper()}")
    return 0


def oaics_payment_method_types(payload: Any) -> list[str]:
    methods: list[str] = []
    seen: set[str] = set()
    for item in _walk_payload_dicts(payload):
        candidates = item.get("payment_method_types")
        if candidates is None:
            candidates = item.get("paymentMethodTypes")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("type")
            method = str(candidate or "").strip().lower()
            if method and method not in seen:
                seen.add(method)
                methods.append(method)
    return methods


def oaics_custom_payment_methods(payload: Any) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _walk_payload_dicts(payload):
        candidates = item.get("custom_payment_methods")
        if candidates is None:
            candidates = item.get("customPaymentMethods")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            method_id = str(candidate.get("id") or "").strip()
            if not method_id.startswith("cpmt_") or method_id in seen:
                continue
            seen.add(method_id)
            methods.append(candidate)
    methods.sort(key=lambda item: 0 if "paypal" in json.dumps(item, ensure_ascii=True).lower() else 1)
    return methods


def fetch_oaics_checkout_session(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    if not is_openai_custom_checkout_session_id(cs_id):
        raise RuntimeError(f"不是 oaics checkout: {cs_id}")
    checkout_url = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
    resp = chatgpt.get(
        f"https://chatgpt.com/backend-api/payments/checkout/{processor}/{cs_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": checkout_url,
            "x-openai-target-path": "/backend-api/payments/checkout/{processor_entity}/{checkout_session_id}",
            "x-openai-target-route": "/backend-api/payments/checkout/{processor_entity}/{checkout_session_id}",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or 'US').lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"读取 OAICS Checkout 失败 HTTP {resp.status_code}: {short(resp.text)}")
    return resp.json() or {}


def submit_oaics_checkout_taxes(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    *,
    billing: dict[str, str],
    country: str,
    currency: str,
    device_id: str,
) -> dict[str, Any]:
    checkout_url = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
    body = {
        "checkout_session_id": cs_id,
        "checkout_email": str(billing.get("email") or ""),
        "billing_country": str(country or billing.get("country") or "US").upper(),
        "billing_name": str(billing.get("name") or ""),
        "currency": str(currency or "").upper(),
        "tax_id": str(billing.get("tax_id") or "") or None,
        "processor_entity": processor,
        "billing_address": {
            "country": str(country or billing.get("country") or "US").upper(),
            "line1": str(billing.get("line1") or ""),
            "line2": str(billing.get("line2") or ""),
            "city": str(billing.get("city") or ""),
            "state": str(billing.get("state") or ""),
            "postal_code": str(billing.get("postal_code") or ""),
        },
    }
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/taxes",
        json=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": checkout_url,
            "x-openai-target-path": "/backend-api/payments/checkout/taxes",
            "x-openai-target-route": "/backend-api/payments/checkout/taxes",
            "oai-device-id": device_id,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS taxes failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def create_oaics_elements_session(
    stripe: requests.Session,
    state: dict[str, Any],
    *,
    country: str,
    currency: str,
) -> dict[str, Any]:
    publishable_key = str(state.get("publishable_key") or state.get("stripe_publishable_key") or state.get("public_key") or "").strip()
    customer_secret = str(state.get("customer_session_client_secret") or "").strip()
    if not publishable_key.startswith(("pk_live_", "pk_test_")):
        raise RuntimeError("OAICS PayPal 缺少 Stripe publishable_key")
    if not customer_secret:
        raise RuntimeError("OAICS PayPal 缺少 customer_session_client_secret")
    stripe_js_id = str(uuid.uuid4())
    params: dict[str, Any] = {
        "customer_session_client_secret": customer_secret,
        "client_betas[0]": "custom_checkout_server_updates_1",
        "client_betas[1]": "custom_checkout_manual_approval_1",
        "deferred_intent[mode]": "subscription",
        "deferred_intent[amount]": "0",
        "deferred_intent[currency]": str(currency or "").lower(),
        "deferred_intent[setup_future_usage]": "off_session",
        "currency": str(currency or "").lower(),
        "key": publishable_key,
        "_stripe_version": PAYPAL_STRIPE_VERSION,
        "elements_init_source": "stripe.elements",
        "referrer_host": "chatgpt.com",
        "stripe_js_id": stripe_js_id,
        "locale": "en-US",
        "type": "deferred_intent",
    }
    for index, method in enumerate(oaics_payment_method_types(state)):
        params[f"deferred_intent[payment_method_types][{index}]"] = method
    resp = stripe.get("https://api.stripe.com/v1/elements/sessions", params=params, timeout=TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS PayPal Elements Session 失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    payload["_oaics_publishable_key"] = publishable_key
    payload["_oaics_stripe_js_id"] = stripe_js_id
    payload["_oaics_payment_method_types"] = oaics_payment_method_types(state)
    return payload


def create_oaics_paypal_confirmation_token(
    stripe: requests.Session,
    elements: dict[str, Any],
    *,
    billing: dict[str, str],
    currency: str,
) -> str:
    pk = str(elements.get("_oaics_publishable_key") or "").strip()
    if not pk:
        raise RuntimeError("OAICS PayPal ConfirmationToken 缺少 publishable_key")
    address_country = str(billing.get("country") or "").upper()
    body: dict[str, Any] = {
        "payment_method_data[type]": "paypal",
        "payment_method_data[billing_details][name]": str(billing.get("name") or ""),
        "payment_method_data[billing_details][email]": str(billing.get("email") or ""),
        "payment_method_data[billing_details][address][country]": address_country,
        "payment_method_data[billing_details][address][line1]": str(billing.get("line1") or ""),
        "payment_method_data[billing_details][address][city]": str(billing.get("city") or ""),
        "payment_method_data[billing_details][address][postal_code]": str(billing.get("postal_code") or ""),
        "payment_method_data[referrer]": "https://chatgpt.com",
        "payment_method_data[time_on_page]": str(random.randint(25000, 55000)),
        "setup_future_usage": "off_session",
        "set_as_default_payment_method": "false",
        "mandate_data[customer_acceptance][type]": "online",
        "mandate_data[customer_acceptance][online][infer_from_client]": "true",
        "client_context[currency]": str(currency or "").lower(),
        "client_context[mode]": "subscription",
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "key": pk,
    }
    if billing.get("state"):
        body["payment_method_data[billing_details][address][state]"] = str(billing.get("state") or "")
    for index, method in enumerate(elements.get("_oaics_payment_method_types") or []):
        body[f"client_context[payment_method_types][{index}]"] = method
    for name, value in (
        ("elements_session_id", _nested_string(elements, ("session_id", "sessionId", "id"), prefixes=("elements_session_",))),
        ("elements_session_config_id", _nested_string(elements, ("config_id", "elements_session_config_id", "elementsSessionConfigId"))),
    ):
        if value:
            body[f"client_attribution_metadata[{name}]"] = value
            body[f"payment_method_data[client_attribution_metadata][{name}]"] = value
    customer = _nested_string(elements, ("customer", "customer_id", "customerId"), prefixes=("cus_",))
    if customer:
        body["client_context[customer]"] = customer
    resp = stripe.post(
        "https://api.stripe.com/v1/confirmation_tokens",
        data=body,
        headers={
            "Authorization": f"Bearer {pk}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": PAYPAL_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS PayPal ConfirmationToken 失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    token = str(payload.get("id") or payload.get("confirmation_token") or payload.get("confirmationToken") or "").strip()
    if not token.startswith(("ctoken_", "ct_")):
        raise RuntimeError("OAICS PayPal ConfirmationToken 响应缺少 token")
    return token


def confirm_oaics_standard_paypal(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    confirmation_token: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/confirm",
        json={
            "checkout_session_id": cs_id,
            "confirm_token": confirmation_token,
            "selected_payment_method_type": "paypal",
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/confirm",
            "x-openai-target-route": "/backend-api/payments/checkout/confirm",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or 'US').lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS PayPal confirm 失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    status = str(payload.get("status") or "").strip().lower()
    if status == "blocked":
        raise RuntimeError("OAICS PayPal confirm blocked")
    return payload


def confirm_oaics_paypal_intent(
    stripe: requests.Session,
    confirmation_token: str,
    app_confirm: dict[str, Any],
    elements: dict[str, Any],
) -> dict[str, Any]:
    pk = str(elements.get("_oaics_publishable_key") or "").strip()
    client_secret = str(app_confirm.get("client_secret") or "").strip()
    if "_secret_" not in client_secret:
        raise RuntimeError("OAICS PayPal confirm 未返回 Intent client_secret")
    intent_id = client_secret.split("_secret_", 1)[0]
    if intent_id.startswith("pi_"):
        collection = "payment_intents"
    elif intent_id.startswith("seti_"):
        collection = "setup_intents"
    else:
        raise RuntimeError("OAICS PayPal confirm 返回了未知 Intent")
    body = {
        "confirmation_token": confirmation_token,
        "client_secret": client_secret,
        "use_stripe_sdk": "true",
        "key": pk,
    }
    return_url = str(app_confirm.get("confirm_return_url") or "").strip()
    if return_url:
        body["return_url"] = return_url
    resp = stripe.post(
        f"https://api.stripe.com/v1/{collection}/{intent_id}/confirm",
        data=body,
        headers={
            "Authorization": f"Bearer {pk}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": PAYPAL_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OAICS PayPal Intent confirm 失败 HTTP {resp.status_code}: {short(resp.text)}")
    return resp.json() or {}


def confirm_oaics_custom_payment_method(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    custom_payment_method_id: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/confirm",
        json={
            "checkout_session_id": cs_id,
            "processor_entity": processor,
            "selected_payment_method_type": custom_payment_method_id,
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/confirm",
            "x-openai-target-route": "/backend-api/payments/checkout/confirm",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or 'US').lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"确认 OAICS PayPal 支付方式失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    status = str(payload.get("status") or "").strip().lower()
    if status == "blocked":
        raise RuntimeError("OAICS PayPal confirm blocked")
    if status and status != "success":
        raise RuntimeError(f"确认 OAICS PayPal 支付方式失败 status={status}")
    return payload


def start_oaics_custom_payment_method(
    chatgpt: requests.Session,
    access_token: str,
    cs_id: str,
    processor: str,
    custom_payment_method_id: str,
    *,
    country: str,
    device_id: str,
) -> dict[str, Any]:
    resp = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/custom_payment_method/start",
        json={
            "checkout_session_id": cs_id,
            "processor_entity": processor,
            "custom_payment_method_type_id": custom_payment_method_id,
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/custom_payment_method/start",
            "x-openai-target-route": "/backend-api/payments/checkout/custom_payment_method/start",
            "oai-device-id": device_id,
            "oai-language": f"{str(country or 'US').lower()}",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"启动 OAICS PayPal 支付失败 HTTP {resp.status_code}: {short(resp.text)}")
    payload = resp.json() or {}
    action = payload.get("next_action") if isinstance(payload.get("next_action"), dict) else {}
    if str(payload.get("status") or "").strip().lower() != "requires_action" or not str(action.get("url") or "").strip():
        raise RuntimeError("OAICS PayPal start 未返回跳转地址")
    return payload


def _finish_oaics_paypal_redirect(
    stripe: requests.Session,
    redirect: str,
    *,
    cs_id: str,
    billing: dict[str, str],
    methods: list[str],
    link_source: str,
    processor: str,
) -> dict[str, Any]:
    fields = extract_paypal_result({"next_action": {"redirect_to_url": {"url": redirect}}}, cs_id)
    if not is_success(fields) or not finalize_bound_paypal_result(stripe, fields, link_source=link_source):
        raise RuntimeError("OAICS PayPal 未返回 PayPal BA 链接")
    fields["amount"] = "0"
    fields["post_promo_payment_method_types"] = methods
    fields["post_promo_ordered_payment_method_types"] = methods
    fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
    fields["billing"] = billing
    fields["link_binding"] = "chatgpt_oaics_checkout_session"
    return {"ok": True, "amount": "0", "fields": fields, "billing": billing}


def generate_paypal_oaics_trial_experimental(
    *,
    access_token: str,
    cs_id: str,
    processor: str,
    proxy_url: str,
    device_id: str,
    billing: dict[str, str],
    country: str,
    currency: str,
    log: LogFn | None = None,
) -> dict[str, Any]:
    log = log or (lambda _m: None)
    chatgpt = build_chatgpt_session(access_token, proxy_url, device_id)
    stripe = build_stripe_session(proxy_url)
    state = fetch_oaics_checkout_session(chatgpt, access_token, cs_id, processor, country=country, device_id=device_id)
    taxes = submit_oaics_checkout_taxes(
        chatgpt,
        access_token,
        cs_id,
        processor,
        billing=billing,
        country=country,
        currency=currency,
        device_id=device_id,
    )
    merged_state = dict(state)
    merged_state.update(taxes)
    verify_oaics_zero_snapshot(merged_state, cs_id=cs_id, currency=currency)
    methods = oaics_payment_method_types(merged_state)
    log(f"[oaics] amount=0 payment_method_types={methods}")
    if "paypal" not in methods:
        cpmt = oaics_custom_payment_methods(merged_state)
        if not cpmt:
            raise RuntimeError(f"OAICS payment_method_types 未包含 paypal: methods={methods}")
        method_id = str(cpmt[0].get("id") or "")
        confirm_oaics_custom_payment_method(
            chatgpt,
            access_token,
            cs_id,
            processor,
            method_id,
            country=country,
            device_id=device_id,
        )
        started = start_oaics_custom_payment_method(
            chatgpt,
            access_token,
            cs_id,
            processor,
            method_id,
            country=country,
            device_id=device_id,
        )
        action = started.get("next_action") if isinstance(started.get("next_action"), dict) else {}
        redirect = str(action.get("url") or "").strip()
        return _finish_oaics_paypal_redirect(
            stripe,
            redirect,
            cs_id=cs_id,
            billing=billing,
            methods=[method_id],
            link_source="oaics_custom_payment_method_start",
            processor=processor,
        )
    elements = create_oaics_elements_session(stripe, merged_state, country=country, currency=currency)
    confirmation_token = create_oaics_paypal_confirmation_token(stripe, elements, billing=billing, currency=currency)
    app_confirm = confirm_oaics_standard_paypal(
        chatgpt,
        access_token,
        cs_id,
        processor,
        confirmation_token,
        country=country,
        device_id=device_id,
    )
    redirect = extract_redirect_to_url(app_confirm)
    if not redirect:
        intent_confirm = confirm_oaics_paypal_intent(stripe, confirmation_token, app_confirm, elements)
        redirect = extract_redirect_to_url(intent_confirm)
    return _finish_oaics_paypal_redirect(
        stripe,
        redirect,
        cs_id=cs_id,
        billing=billing,
        methods=methods,
        link_source="oaics_standard_paypal_intent_confirm",
        processor=processor,
    )


def chatgpt_approve(
    access_token: str,
    cs_id: str,
    processor: str,
    proxy_url: str,
    device_id: str,
    log: LogFn,
    *,
    country: str = "US",
) -> None:
    cg = build_chatgpt_session(access_token, proxy_url, device_id)
    warm_chatgpt_checkout_context(cg, country, log)
    last_err = ""
    for attempt in range(1, 4):
        try:
            resp = cg.post(
                "https://chatgpt.com/backend-api/payments/checkout/approve",
                json={"checkout_session_id": cs_id, "processor_entity": processor},
                headers={
                    "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
                    "x-openai-target-path": "/backend-api/payments/checkout/approve",
                    "x-openai-target-route": "/backend-api/payments/checkout/approve",
                },
                timeout=TIMEOUT,
            )
            log(f"approve attempt {attempt}: HTTP {resp.status_code} {short(resp.text, 120)}")
            if resp.status_code < 400:
                try:
                    result = (resp.json() or {}).get("result")
                except Exception:
                    result = ""
                if not result or result == "approved":
                    return
                last_err = f"unexpected result: {result!r}"
            else:
                last_err = short(resp.text)
        except Exception as exc:
            last_err = short(exc)
            log(f"approve attempt {attempt} error: {last_err}")
        time.sleep(1.0)
    raise RuntimeError(f"approve failed: {last_err}")


def chatgpt_update_trial_promo(
    access_token: str,
    *,
    cs_id: str,
    processor: str,
    proxy_url: str,
    device_id: str,
    country: str = "JP",
    currency: str = "JPY",
    log: LogFn | None = None,
) -> dict[str, Any]:
    cg = build_chatgpt_session(access_token, proxy_url, device_id)
    warm_chatgpt_checkout_context(cg, country, log)
    resp = cg.post(
        "https://chatgpt.com/backend-api/payments/checkout/update",
        json={
            "checkout_session_id": cs_id,
            "processor_entity": processor,
            "plan_name": "chatgptplusplan",
            "price_interval": "month",
            "seat_quantity": 1,
            "billing_details": {"country": country, "currency": currency},
            "promo_campaign": {"promo_campaign_id": "plus-1-month-free", "is_coupon_from_query_param": False},
        },
        headers={
            "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/update",
            "x-openai-target-route": "/backend-api/payments/checkout/update",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"update failed: HTTP {resp.status_code} {short(resp.text)}")
    try:
        return resp.json() or {}
    except Exception:
        return {}


def _confirm_paypal_inline(
    stripe: requests.Session,
    *,
    cs_id: str,
    stripe_pk: str,
    ctx: dict[str, str],
    billing: dict[str, str],
    amount: str,
    return_url: str,
) -> dict[str, Any]:
    body = {
        "guid": ctx["guid"],
        "muid": ctx["muid"],
        "sid": ctx["sid"],
        "payment_method_data[type]": "paypal",
        "init_checksum": ctx["init_checksum"],
        "version": PAYPAL_STRIPE_RUNTIME_VERSION,
        "expected_amount": amount,
        "expected_payment_method_type": "paypal",
        "return_url": return_url,
        "elements_session_client[session_id]": ctx["elements_session_id"],
        "elements_session_client[locale]": "en-US",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_session_id]": cs_id,
        "client_attribution_metadata[checkout_config_id]": ctx["config_id"],
        "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "custom",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "consent[terms_of_service]": "accepted",
        "key": stripe_pk,
        "_stripe_version": PAYPAL_STRIPE_VERSION,
    }
    body.update(
        {
            "payment_method_data[billing_details][name]": billing["name"],
            "payment_method_data[billing_details][email]": billing["email"],
            "payment_method_data[billing_details][address][country]": billing.get("country") or "US",
            "payment_method_data[billing_details][address][line1]": billing.get("line1") or "",
            "payment_method_data[billing_details][address][city]": billing.get("city") or "",
            "payment_method_data[billing_details][address][postal_code]": billing.get("postal_code") or "",
            "payment_method_data[billing_details][address][state]": billing.get("state") or "",
        }
    )
    resp = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=TIMEOUT)
    ba_approve_url = extract_paypal_ba_approve_url(resp.text)
    if ba_approve_url:
        return {"_ba_approve_url": ba_approve_url, "_raw_status": resp.status_code}
    if resp.status_code >= 400:
        raise RuntimeError(f"confirm failed: HTTP {resp.status_code} {short(resp.text)}")
    payload = resp.json() or {}
    ba_approve_url = extract_paypal_ba_approve_url(payload)
    if ba_approve_url:
        payload["_ba_approve_url"] = ba_approve_url
    return payload


def create_express_billing_agreement(
    stripe: requests.Session,
    *,
    stripe_pk: str,
    sdk_version: str = "v5",
) -> dict[str, str]:
    """Create a PayPal Billing Agreement token through Stripe Express Checkout.

    Diagnostic helper only. This endpoint does not take the current ChatGPT
    ``checkout_session_id`` and therefore its BA token must not be persisted as a
    ChatGPT/OpenAI billing link.
    """

    resp = stripe.post(
        "https://api.stripe.com/v1/elements/express_billing_agreement",
        data={
            "key": stripe_pk,
            "paypal_sdk_version": sdk_version,
            "_stripe_version": PAYPAL_STRIPE_VERSION,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"express BA failed: HTTP {resp.status_code} {short(resp.text)}")
    try:
        payload = resp.json() or {}
    except Exception as exc:
        raise RuntimeError(f"express BA invalid response: {short(resp.text)}") from exc
    token = str(payload.get("paypal_billing_agreement_token") or "").strip()
    if not token.startswith("BA-"):
        raise RuntimeError(f"express BA missing token: {short(payload)}")
    return {
        "paypal_link": paypal_ba_approve_url_from_token(token),
        "provider_redirect_url": paypal_ba_approve_url_from_token(token),
        "stripe_redirect_url": "",
        "ba_token": token,
        "link_source": "stripe_express_billing_agreement",
        "link_binding": "unbound_express",
        "paypal_sdk_version": sdk_version,
    }


def generate_paypal_trial(cfg: PaypalJobConfig, log: LogFn | None = None) -> dict[str, Any]:
    log = log or (lambda _m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：direct_proxies 或 Kookeey 用户名/密码")

    device_id = str(uuid.uuid4())
    checkout_region = normalize_paypal_country(cfg.region, "US")
    promo_region = normalize_paypal_country(cfg.promo_region, "JP")
    billing = paypal_billing(country=checkout_region)
    checkout_billing_country = billing.get("country") or checkout_region
    checkout_billing_details = paypal_checkout_billing_details_for_country(checkout_region)
    checkout_create_country = checkout_billing_details["country"]
    checkout_currency = checkout_billing_details["currency"]
    state_text = f"-{billing.get('state')}" if billing.get("state") else ""
    log(f"账单: {billing['name']} / {billing['city']}{state_text} / {billing['postal_code']} / {billing['country']}")

    dyn1, sid1 = build_paypal_dynamic_proxy(cfg, 0, checkout_region)
    front_promo_for_oaics = bool(cfg.only_oaics and cfg.apply_promo)
    log(f"[1/6] {checkout_region} 创建 checkout（{'前置 promo' if front_promo_for_oaics else '先不带 promo'}） sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        p1 = chain1.url
        cg = build_chatgpt_session(token, p1, device_id)
        warm_chatgpt_checkout_context(cg, checkout_create_country, log)
        checkout_body: dict[str, Any] = {
            "entry_point": "all_plans_pricing_modal",
            "plan_name": "chatgptplusplan",
            "billing_details": {"country": checkout_create_country, "currency": checkout_currency},
            "checkout_ui_mode": "custom",
        }
        if front_promo_for_oaics:
            checkout_body["promo_campaign"] = {
                "promo_campaign_id": "plus-1-month-free",
                "is_coupon_from_query_param": False,
            }
        resp = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json=checkout_body,
            headers={"x-openai-target-path": "/backend-api/payments/checkout", "x-openai-target-route": "/backend-api/payments/checkout"},
            timeout=TIMEOUT,
        )
        log(f"checkout HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise RuntimeError(f"checkout failed: {short(resp.text)}")
        data = resp.json() or {}
        cs_id = str(data.get("checkout_session_id") or data.get("session_id") or data.get("id") or "")
        if is_openai_custom_checkout_session_id(cs_id):
            processor = str(data.get("processor_entity") or "openai_llc")
            return generate_paypal_oaics_trial_experimental(
                access_token=token,
                cs_id=cs_id,
                processor=processor,
                proxy_url=p1,
                device_id=device_id,
                billing=billing,
                country=checkout_billing_country,
                currency=checkout_currency,
                log=log,
            )
        if not is_checkout_session_id(cs_id):
            raise RuntimeError(f"checkout missing cs_id: {short(data)}")
        if cfg.only_oaics:
            raise PaypalOnlyOaicsSkipped(f"非 OAICS checkout，已跳过: {cs_id}")
        pk = extract_pk(data) or DEFAULT_STRIPE_PK
        processor = str(data.get("processor_entity") or "openai_llc")

    dyn2, sid2 = build_paypal_dynamic_proxy(cfg, 1, checkout_region)
    log(f"[2/6] {checkout_region} Stripe init 预热 PayPal 支付方式 sid={sid2}")
    with pix_proxy_context(cfg.local_proxy, dyn2, log) as chain2:
        stripe_proxy = chain2.url
        stripe = build_stripe_session(stripe_proxy)
        ctx = _ctx()
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        amount = amount_info(init_payload)
        pmt, ordered, has_paypal = pmt_info(init_payload)
        pre_promo_amount = amount
        pre_promo_pmt = pmt
        pre_promo_ordered = ordered
        log(f"预热金额={amount} 支付方式={pmt} ordered={ordered} has_paypal={has_paypal}")
        if not has_paypal and not cfg.apply_promo:
            raise RuntimeError(f"未出现 PayPal，pmt={pmt}")

        if cfg.apply_promo:
            dyn3, sid3 = build_paypal_dynamic_proxy(cfg, 2, promo_region)
            log(f"[3/6] {promo_region} 后注入试用 promo sid={sid3}")
            with pix_proxy_context(cfg.local_proxy, dyn3, log) as chain3:
                update_payload = chatgpt_update_trial_promo(
                    token,
                    cs_id=cs_id,
                    processor=processor,
                    proxy_url=chain3.url,
                    device_id=device_id,
                    country=promo_region,
                    currency=promo_currency_for_region(promo_region),
                    log=log,
                )
                log(f"promo update success={bool(update_payload.get('success', True))} keys={sorted(update_payload.keys())[:6]}")

            dyn4, sid4 = build_paypal_dynamic_proxy(cfg, 3, checkout_region)
            log(f"[4/6] {checkout_region} Stripe re-init 验证 0 元 + PayPal sid={sid4}")
            with pix_proxy_context(cfg.local_proxy, dyn4, log) as chain4:
                stripe_proxy = chain4.url
                stripe = build_stripe_session(stripe_proxy)
                init_payload = stripe_init(stripe, cs_id, pk, ctx)
            amount = amount_info(init_payload)
            pmt, ordered, has_paypal = pmt_info(init_payload)
            log(f"后注入金额={amount} 支付方式={pmt} ordered={ordered} has_paypal={has_paypal}")
            if not has_paypal:
                raise RuntimeError(f"后注入 promo 后未出现 PayPal，pmt={pmt}")
        else:
            log("[3/6] 跳过 promo update")
            if not is_zero_amount(amount):
                raise RuntimeError(f"PayPal 金额必须为 0: {amount}")
            log(f"[4/6] 更新 {checkout_region} tax_region {billing.get('state') or '-'}")
            stripe_update_tax_region(stripe, cs_id, pk, billing)
            init_payload = stripe_init(stripe, cs_id, pk, ctx)
            amount = amount_info(init_payload)
            pmt, ordered, has_paypal = pmt_info(init_payload)
            log(f"tax_region 后金额={amount} 支付方式={pmt} ordered={ordered} has_paypal={has_paypal}")
            if not has_paypal:
                raise RuntimeError(f"未出现 PayPal，pmt={pmt}")

        if not is_zero_amount(amount):
            raise RuntimeError(f"PayPal 金额必须为 0: {amount}")
        hosted = str(init_payload.get("stripe_hosted_url") or "")

        log("[5/6] inline confirm PayPal（只接受绑定当前 checkout session 的 BA redirect）")
        confirm_payload = _confirm_paypal_inline(
            stripe,
            cs_id=cs_id,
            stripe_pk=pk,
            ctx=ctx,
            billing=billing,
            amount=amount,
            return_url=paypal_return_url(cs_id, processor, hosted),
        )
        fields = extract_paypal_result(confirm_payload, cs_id)
        sub = find_submission_attempt(confirm_payload)
        log(f"confirm submission={sub.get('state')} redirect={bool(fields.get('stripe_redirect_url') or fields.get('paypal_link'))}")
        if is_success(fields) and finalize_bound_paypal_result(stripe, fields, link_source="stripe_payment_pages_confirm"):
            fields["amount"] = amount
            fields["pre_promo_amount"] = pre_promo_amount
            fields["pre_promo_payment_method_types"] = pre_promo_pmt
            fields["pre_promo_ordered_payment_method_types"] = pre_promo_ordered
            fields["post_promo_payment_method_types"] = pmt
            fields["post_promo_ordered_payment_method_types"] = ordered
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log("[6/6] approve + poll PayPal")
        chatgpt_approve(token, cs_id, processor, p1, device_id, log, country=checkout_region)
        last_err: dict[str, Any] = {}
        for i in range(1, 11):
            page_data = page_get(stripe, cs_id, pk, ctx)
            fields = extract_paypal_result(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(f"poll {i}/10 sub={sub.get('state')} err={err.get('code') if err else '-'} success={is_success(fields)}")
            if is_success(fields) and finalize_bound_paypal_result(stripe, fields, link_source="stripe_checkout_approve_poll"):
                fields["amount"] = amount
                fields["pre_promo_amount"] = pre_promo_amount
                fields["pre_promo_payment_method_types"] = pre_promo_pmt
                fields["pre_promo_ordered_payment_method_types"] = pre_promo_ordered
                fields["post_promo_payment_method_types"] = pmt
                fields["post_promo_ordered_payment_method_types"] = ordered
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                last_err = err or {}
            time.sleep(1.0)
        if last_err.get("code"):
            raise RuntimeError(f"轮询超时，未拿到 PayPal 链接，最后错误: {last_err.get('code')}")
        raise RuntimeError("轮询超时，未拿到 PayPal 链接")
