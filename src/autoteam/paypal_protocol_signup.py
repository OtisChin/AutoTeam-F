from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from autoteam.gopay_executor import GoPayOTPCancelled, _poll_otp_from_sms_url

logger = logging.getLogger(__name__)

PP_ORIGIN = "https://www.paypal.com"
PAYPAL_PROTOCOL_OTP_TIMEOUT_SECONDS = 120
PAYPAL_PROTOCOL_OTP_RESEND_AFTER_SECONDS = 60
PAYPAL_PROTOCOL_OTP_MAX_RESEND_ATTEMPTS = 1
PAYPAL_CALLING_CODE_COUNTRIES = {
    "1": "US",
    "33": "FR",
    "34": "ES",
    "39": "IT",
    "44": "GB",
    "49": "DE",
    "52": "MX",
    "55": "BR",
    "60": "MY",
    "61": "AU",
    "62": "ID",
    "63": "PH",
    "65": "SG",
    "66": "TH",
    "81": "JP",
    "82": "KR",
    "84": "VN",
    "86": "CN",
    "852": "HK",
    "91": "IN",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

PHONE_REJECTED_HINTS = (
    "try a different phone number",
    "use a different phone number",
    "unable to complete your request",
    "we’re unable to complete your request",
    "we’re unable to complete your request",
    "リクエストを完了できません",
    "別の電話番号",
)
ACCOUNT_LIMITED_HINTS = (
    "your account is limited",
    "account is limited",
    "paypal account overview",
)
HUMAN_VERIFICATION_HINTS = (
    "confirm you’re human",
    "confirm you’re human",
    "move the slider all the way to the right",
    "security challenge",
    "human verification",
)
DATADOME_HINTS = (
    "datadome",
    "captcha_failed",
    "ct.ddc.paypal.com",
    "ddc.paypal.com",
    "geo.captcha-delivery.com",
    "geo.ddc.paypal.com",
    "dd.js",
    "interstitial",
    "please enable js and disable any ad blocker",
)
# captcha 单独作为 hint 误报率太高（很多正常 PayPal 页面包含这个词），移到更精确的检测
DATADOME_RESPONSE_HINTS = DATADOME_HINTS + ("captcha",)

Q_DEFERRED = """query DeferredFeature($channel: String!, $countryCodeAsString: String!, $isBaslAsString: String!, $isForcedGuest: String!, $token: String!, $integrationType: String!) {
  otpLoginContext(token: $token, integrationType: $integrationType) { __typename context }
  elmoExperiment(
    app: "checkoutuinodeweb"
    filters: [{key: "Country", value: $countryCodeAsString}, {key: "Channel", value: $channel}, {key: "IsBasl", value: $isBaslAsString}, {key: "IsGuestOnly", value: $isForcedGuest}]
    res: "weasley:deferredFeature:memberAsDefault"
  ) {
    __typename
    treatments { __typename experimentId experimentName treatmentId treatmentName }
  }
}"""

Q_GRIFFIN_METADATA = """query GriffinMetadataQuery($countryCode: CountryCodes!, $languageCode: CheckoutContentLanguageCode!, $shippingCountryCode: CountryCodes!) {
  localeMetadata {
    address(countryCode: $countryCode, languageCode: $languageCode) { __typename }
    shippingAddress: address(countryCode: $shippingCountryCode, languageCode: $languageCode) { __typename }
    currencyCode(countryCode: $countryCode)
    phone(countryCode: $countryCode) { __typename }
    __typename
  }
}"""

Q_CHECKOUT_SESSION = """query CheckoutSessionDataQuery($token: String!) {
  checkoutSession(token: $token) {
    checkoutSessionType
    merchant { country merchantId name __typename }
    __typename
  }
}"""

Q_INIT_OTP = """mutation InitiateRiskBasedTwoFactorPhoneConfirmationMutation($phoneNumber: String!, $locale: LocaleInput!, $phoneCountry: CountryCodes!, $token: String!) {
  initiateRiskBasedTwoFactorPhoneConfirmation(
    locale: $locale
    phoneCountry: $phoneCountry
    phoneNumber: $phoneNumber
    token: $token
  ) {
    authId
    challengeId
    state
    __typename
  }
}"""

Q_CONFIRM_OTP = """mutation ConfirmRiskBasedTwoFactorPhoneConfirmationMutation($pin: String!, $authId: String!, $challengeId: String!, $token: String!) {
  confirmRiskBasedTwoFactorPhoneConfirmation(
    pin: $pin
    authId: $authId
    challengeId: $challengeId
    token: $token
  ) {
    authId
    challengeId
    state
    __typename
  }
}"""

Q_SIGNUP = """mutation SignUpNewMemberMutation(
  $billingAddress: AddressInput
  $contentIdentifier: String
  $country: CountryCodes
  $crsData: CommonReportingStandardsInput
  $email: String!
  $firstName: String!
  $lastName: String!
  $marketingOptOut: Boolean
  $password: String
  $phone: PhoneInput!
  $shippingAddress: AddressInput
  $supportedThreeDsExperiences: [ThreeDSPaymentExperience]
  $token: String!
  $legalAgreements: LegalAgreementsInput
) {
  onboardAccount: signUpNewMember(
    billingAddress: $billingAddress
    contentIdentifier: $contentIdentifier
    country: $country
    crsData: $crsData
    email: $email
    firstName: $firstName
    lastName: $lastName
    marketingOptOut: $marketingOptOut
    password: $password
    phone: $phone
    shippingAddress: $shippingAddress
    supportedThreeDsExperiences: $supportedThreeDsExperiences
    token: $token
    legalAgreements: $legalAgreements
  ) {
    buyer {
      auth { accessToken __typename }
      userId
      __typename
    }
    __typename
  }
}"""

Q_AUTHORIZE = (
    "mutation authorize($billingAgreementId: String!, $addressId: String, "
    "$fundingPreference: billingFundingPreferenceInput, "
    "$legalAgreements: billingLegalAgreementsInput) { "
    "billing { authorize( billingAgreementId: $billingAgreementId "
    "addressId: $addressId fundingPreference: $fundingPreference "
    "legalAgreements: $legalAgreements ) { billingAgreementToken "
    "paymentAction returnURL { href __typename } buyer { userId __typename } "
    "__typename } __typename } }"
)


def _emit(on_progress: Callable[[dict[str, Any]], None] | None, stage: str, message: str = "", **extra: Any) -> None:
    if not callable(on_progress):
        return
    event = {"stage": stage}
    if message:
        event["message"] = message
    event.update(extra)
    on_progress(event)


def _safe_json(resp: Any, stage: str) -> dict[str, Any]:
    try:
        payload = resp.json()
    except Exception as exc:
        text = str(getattr(resp, "text", "") or "")
        failure_stage, message = _classify_error_text(text)
        if failure_stage != "paypal_protocol":
            raise RuntimeError(f"{failure_stage}|{message}") from exc
        raise RuntimeError(
            f"{stage} 返回非 JSON: HTTP {getattr(resp, 'status_code', '?')} "
            f"{text[:300]}"
        ) from exc
    return payload if isinstance(payload, dict) else {"_raw": payload}


def _classify_error_text(text: str) -> tuple[str, str]:
    lowered = str(text or "").lower()
    if any(hint in lowered for hint in PHONE_REJECTED_HINTS):
        return "paypal_phone_rejected", "PayPal 拒绝当前手机号，请更换手机号"
    if any(hint in lowered for hint in ACCOUNT_LIMITED_HINTS):
        return "paypal_account_limited", "PayPal 账号受限，无法继续协议注册"
    if any(hint in lowered for hint in HUMAN_VERIFICATION_HINTS):
        return "paypal_human_verification", "PayPal 返回人机验证页面，协议模式停止"
    if any(hint in lowered for hint in DATADOME_HINTS):
        return "paypal_human_verification", "PayPal 返回 DataDome 风控页面，协议模式停止"
    return "paypal_protocol", str(text or "").strip() or "协议模式失败"


def _is_datadome_blocked(resp: Any) -> bool:
    """检测响应是否为 DataDome 风控拦截页"""
    status = int(getattr(resp, "status_code", 0) or 0)
    text = str(getattr(resp, "text", "") or "").lower()
    # DataDome 通常返回 403 + JS challenge，或 200 + 拦截页面
    if status == 403:
        return True
    if any(hint in text for hint in DATADOME_RESPONSE_HINTS):
        # 排除包含正常 PayPal 内容的页面（如 signup form 中提到 captcha 的正常文本）
        if "EC-" in str(getattr(resp, "text", "") or "") or "checkoutweb" in text:
            return False
        return True
    return False


def _warmup_paypal_session(http: Any, *, timeout: int = 15) -> None:
    """预热 PayPal session，获取 DataDome 和基础 cookies"""
    try:
        http.get(
            f"{PP_ORIGIN}/",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
            timeout=timeout,
            allow_redirects=True,
        )
    except Exception as exc:
        logger.info("[paypal_protocol_signup] warmup paypal.com soft-failed: %s", exc)


_EC_RE = re.compile(r"\bEC-[A-Z0-9]{17,}\b")
_ONBOARD_RE = re.compile(r'onboardingLink"\s*:\s*"([^"]*?/agreements/approve\?[^"]+)')
_UL_ONBOARD_RE = re.compile(r'href=["\']([^"\']*?ulOnboardRedirect=true[^"\']*)["\']', re.I)


def _unescape_url(value: str) -> str:
    return (
        str(value or "")
        .replace("&amp;", "&")
        .replace("&#38;", "&")
        .replace("&#x26;", "&")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
    )


def _first_query_value(url: str, name: str) -> str:
    try:
        return (urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query).get(name) or [""])[0]
    except Exception:
        return ""


def _build_signup_url(ba_token: str, ec_token: str, locale_country: str, locale_lang: str, source_url: str = "") -> str:
    params: list[tuple[str, str]] = []
    ssrt = _first_query_value(source_url, "ssrt")
    if ssrt:
        params.append(("ssrt", ssrt))
    params.extend(
        [
            ("ul", "1"),
            ("country.x", locale_country),
            ("locale.x", f"{locale_lang}_{locale_country}"),
            ("modxo_redirect_reason", "guest_user"),
            ("ba_token", ba_token),
            ("token", ec_token),
            ("rcache", "1"),
            ("cookieBannerVariant", "hidden"),
        ]
    )
    return f"{PP_ORIGIN}/checkoutweb/signup?{urllib.parse.urlencode(params)}"


def _build_onboard_url(ba_token: str, locale_country: str, locale_lang: str, source_url: str = "") -> str:
    params: list[tuple[str, str]] = []
    ssrt = _first_query_value(source_url, "ssrt")
    if ssrt:
        params.append(("ssrt", ssrt))
    params.extend(
        [
            ("ul", "1"),
            ("country.x", locale_country),
            ("locale.x", f"{locale_lang}_{locale_country}"),
            ("modxo_redirect_reason", "guest_user"),
            ("ulOnboardRedirect", "true"),
            ("ba_token", ba_token),
        ]
    )
    return f"{PP_ORIGIN}/agreements/approve?{urllib.parse.urlencode(params)}"


def _coerce_onboard_url(onboard_url: str, *, ba_token: str, locale_country: str, locale_lang: str) -> str:
    """Keep PayPal signup GraphQL referers on /agreements/approve, not Hermes fallback URLs."""
    url = _unescape_url(onboard_url)
    if url.startswith("/"):
        url = PP_ORIGIN + url
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        parsed = urllib.parse.urlparse("")
    if parsed.netloc and "paypal.com" in parsed.netloc and parsed.path == "/agreements/approve":
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        seen = {key for key, _ in params}

        def set_param(name: str, value: str) -> None:
            nonlocal params
            params = [(key, current) for key, current in params if key != name]
            params.append((name, value))

        if "ul" not in seen:
            params.append(("ul", "1"))
        set_param("country.x", locale_country)
        set_param("locale.x", f"{locale_lang}_{locale_country}")
        if "modxo_redirect_reason" not in seen:
            params.append(("modxo_redirect_reason", "guest_user"))
        set_param("ulOnboardRedirect", "true")
        set_param("ba_token", ba_token)
        return f"{PP_ORIGIN}/agreements/approve?{urllib.parse.urlencode(params)}"
    return _build_onboard_url(ba_token, locale_country, locale_lang, source_url=url)


def _paypal_pay_url(ba_token: str, *, onboard_url: str = "") -> str:
    ssrt = _first_query_value(onboard_url, "ssrt")
    if ssrt:
        return f"{PP_ORIGIN}/pay?ssrt={urllib.parse.quote(ssrt)}&token={urllib.parse.quote(ba_token)}&ul=1"
    return f"{PP_ORIGIN}/pay?token={urllib.parse.quote(ba_token)}&ul=1"


def _prime_checkout_signup(
    http: Any,
    *,
    signup_url: str,
    referer: str,
    locale_country: str,
    locale_lang: str,
    timeout: int,
) -> tuple[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": f"{locale_lang}-{locale_country},{locale_lang};q=0.9,en;q=0.8",
        "Referer": referer,
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-User": "?1",
    }
    try:
        resp = http.get(signup_url, headers=headers, timeout=timeout, allow_redirects=False)
    except Exception as exc:
        logger.info("[paypal_protocol_signup] prime signup soft-failed: %s", exc)
        return signup_url, ""
    text = str(getattr(resp, "text", "") or "")
    status = int(getattr(resp, "status_code", 0) or 0)
    location = (getattr(resp, "headers", {}) or {}).get("location") or (getattr(resp, "headers", {}) or {}).get("Location") or ""
    final_url = str(getattr(resp, "url", signup_url) or signup_url)
    if _is_datadome_blocked(resp):
        raise RuntimeError("paypal_human_verification|PayPal /checkoutweb/signup 被 DataDome 风控拦截")
    if location:
        location_abs = urllib.parse.urljoin(final_url, _unescape_url(location))
        if "/checkoutweb/signup" in location_abs:
            return location_abs, text
        logger.info(
            "[paypal_protocol_signup] signup prime redirected away: status=%s location=%s; keeping canonical signup referer",
            status,
            location_abs[:160],
        )
        return signup_url, text
    if "/checkoutweb/signup" in final_url:
        return final_url, text
    return signup_url, text


def _bootstrap(http: Any, ba_token: str, *, locale_country: str, locale_lang: str, timeout: int) -> tuple[str, str, str]:
    url = (
        f"{PP_ORIGIN}/agreements/approve?ba_token={urllib.parse.quote(ba_token)}"
        f"&country.x={urllib.parse.quote(locale_country)}"
        f"&locale.x={urllib.parse.quote(f'{locale_lang}_{locale_country}')}"
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": f"{locale_lang}-{locale_country},{locale_lang};q=0.9,en;q=0.8",
        "Referer": "https://chatgpt.com/",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-User": "?1",
    }

    # 预热 — 提前访问 paypal.com 获取 DataDome 基础 cookies
    _warmup_paypal_session(http, timeout=min(timeout, 15))
    time.sleep(random.uniform(0.5, 1.5))

    # DataDome 拦截不是同一 HTTP session 原地重试能稳定解决的问题；尽快返回给上层
    # 浏览器兜底，保留同一代理与真实页面上下文处理安全检查。
    resp = http.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if _is_datadome_blocked(resp):
        logger.info(
            "[paypal_protocol_signup] /agreements/approve DataDome blocked; switching to browser fallback",
        )
        raise RuntimeError("paypal_human_verification|PayPal /agreements/approve 被 DataDome 风控拦截，已停止协议重试并降级浏览器处理")
    html = str(resp.text or "")
    if resp.status_code != 200:
        stage, message = _classify_error_text(html)
        raise RuntimeError(f"{stage}|{message}")
    if _is_datadome_blocked(resp):
        raise RuntimeError("paypal_human_verification|PayPal /agreements/approve 被 DataDome 风控拦截")
    match_ec = _EC_RE.search(html)
    if not match_ec:
        raise RuntimeError("paypal_protocol|/agreements/approve 未返回 EC token")
    ec_token = match_ec.group(0)
    onboarding_match = _ONBOARD_RE.search(html) or _UL_ONBOARD_RE.search(html)
    onboard_url = _build_onboard_url(ba_token, locale_country, locale_lang, source_url=url)
    if onboarding_match:
        onboard_url = _unescape_url(onboarding_match.group(1))
        if onboard_url.startswith("/"):
            onboard_url = PP_ORIGIN + onboard_url
    onboard_url = _coerce_onboard_url(onboard_url, ba_token=ba_token, locale_country=locale_country, locale_lang=locale_lang)
    resp2 = http.get(
        onboard_url,
        headers={**headers, "Referer": _paypal_pay_url(ba_token, onboard_url=onboard_url), "Sec-Fetch-Site": "same-origin"},
        timeout=timeout,
        allow_redirects=False,
    )
    if resp2.status_code not in {200, 301, 302, 303, 307, 308}:
        raise RuntimeError(f"paypal_protocol|/checkoutweb/signup 跳转失败: HTTP {resp2.status_code}")
    location = resp2.headers.get("location") or resp2.headers.get("Location") or ""
    location = urllib.parse.urljoin(str(getattr(resp2, "url", onboard_url) or onboard_url), _unescape_url(location)) if location else ""
    signup_url = location if "/checkoutweb/signup" in location else _build_signup_url(ba_token, ec_token, locale_country, locale_lang, source_url=location or onboard_url)
    signup_url, signup_html = _prime_checkout_signup(
        http,
        signup_url=signup_url,
        referer=onboard_url,
        locale_country=locale_country,
        locale_lang=locale_lang,
        timeout=timeout,
    )
    match_ec2 = _EC_RE.search(f"{signup_url}\n{signup_html}\n{getattr(resp2, 'text', '') or ''}")
    if match_ec2:
        ec_token = match_ec2.group(0)
        signup_url = _build_signup_url(ba_token, ec_token, locale_country, locale_lang, source_url=signup_url)
    return ec_token, signup_url, signup_html


def _gql(
    http: Any,
    op_name: str,
    variables: dict[str, Any],
    query: str,
    *,
    signup_url: str,
    timeout: int,
    locale_lang: str = "en",
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {"operationName": op_name, "variables": variables, "query": query}
    if extra_body:
        body.update(extra_body)
    token = str(variables.get("token") or variables.get("billingAgreementId") or "")
    country = str(
        variables.get("country")
        or variables.get("countryCodeAsString")
        or (variables.get("locale") or {}).get("country")
        or "US"
    )
    resp = http.post(
        f"{PP_ORIGIN}/graphql?{op_name}",
        json=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": f"{locale_lang}-{country.upper()},{locale_lang};q=0.9,en;q=0.8",
            "Origin": PP_ORIGIN,
            "Referer": signup_url,
            "X-Requested-With": "fetch",
            "X-App-Name": "checkoutuinodeweb_weasley",
            "PayPal-Client-Context": token,
            "PayPal-Client-Metadata-Id": token,
            "X-Country": country,
            "X-Locale": f"{locale_lang}_{country.upper()}",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        if _is_datadome_blocked(resp):
            raise RuntimeError(f"paypal_human_verification|PayPal GraphQL {op_name} 被 DataDome 风控拦截 (HTTP {resp.status_code})")
        stage, message = _classify_error_text(resp.text or "")
        raise RuntimeError(f"{stage}|{message}")
    payload = _safe_json(resp, op_name)
    errors = payload.get("errors") or []
    if errors:
        raw_message = json.dumps(errors, ensure_ascii=False)
        stage, message = _classify_error_text(raw_message)
        if stage != "paypal_protocol":
            raise RuntimeError(f"{stage}|{message}")
    return payload


def _phone_split(phone: str) -> tuple[str, str]:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if str(phone or "").strip().startswith("+"):
        for code in sorted(PAYPAL_CALLING_CODE_COUNTRIES, key=len, reverse=True):
            if digits.startswith(code) and len(digits) - len(code) >= 7:
                return code, digits[len(code) :]
    if len(digits) == 10:
        return "1", digits
    raise ValueError(f"unparseable phone: {phone}")


def _extract_content_identifier(html: str, locale_country: str, locale_lang: str) -> str:
    for pattern in (
        r'"contentIdentifier"\s*:\s*"([^"]*signupTerms[^"]*)"',
        r'\\"contentIdentifier\\"\s*:\s*\\"([^"\\]*signupTerms[^"\\]*)\\"',
        r'([A-Z]{2}:[a-z]{2}:[0-9a-f]{16,64}:compliance\.signupTerms)',
    ):
        match = re.search(pattern, html or "", re.I)
        if match:
            return match.group(1).replace("\\/", "/")
    if locale_country.upper() == "US" and locale_lang.lower() == "en":
        return "US:en:f411614ea3eaac38abc54763fcfca00e:compliance.signupTerms"
    return f"{locale_country}:{locale_lang}:compliance.signupTerms"


def _split_name(value: str) -> tuple[str, str]:
    parts = [item for item in re.split(r"\s+", str(value or "").strip()) if item]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    if parts:
        return parts[0], "Smith"
    return "James", "Smith"


def _state_code(value: str) -> str:
    raw = str(value or "").strip()
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    mapping = {"california": "CA", "florida": "FL", "new york": "NY", "texas": "TX", "washington": "WA"}
    return mapping.get(raw.lower(), raw)


def _signup_variables(*, signup_profile: dict[str, Any], ec_token: str, locale_country: str, locale_lang: str) -> dict[str, Any]:
    calling_code, subscriber = _phone_split(str(signup_profile.get("phone") or ""))
    first_name = str(signup_profile.get("first_name") or "").strip()
    last_name = str(signup_profile.get("last_name") or "").strip()
    if not first_name or not last_name:
        first_name, last_name = _split_name(signup_profile.get("name") or "")
    country = str(signup_profile.get("country") or locale_country or "US").strip().upper() or "US"
    address = {
        "line1": str(signup_profile.get("address1") or "").strip(),
        "city": str(signup_profile.get("city") or "").strip(),
        "postalCode": str(signup_profile.get("zip") or "").strip(),
        "accountQuality": {"autoCompleteType": "MANUAL", "isUserModified": False},
        "country": country,
        "familyName": last_name,
        "givenName": first_name,
    }
    state = _state_code(signup_profile.get("state") or "")
    if country == "US" and state:
        address["state"] = state
    return {
        "country": locale_country,
        "email": str(signup_profile.get("email") or "").strip(),
        "firstName": first_name,
        "lastName": last_name,
        "phone": {"countryCode": calling_code, "number": subscriber, "type": "MOBILE"},
        "supportedThreeDsExperiences": ["IFRAME"],
        "token": ec_token,
        "billingAddress": address,
        "shippingAddress": {
            "line1": "",
            "city": "",
            "state": "",
            "postalCode": "",
            "accountQuality": {"autoCompleteType": "MANUAL", "isUserModified": False},
            "country": country,
            "familyName": last_name,
            "givenName": first_name,
        },
        "contentIdentifier": _extract_content_identifier(str(signup_profile.get("_signup_html") or ""), locale_country, locale_lang),
        "marketingOptOut": False,
        "password": str(signup_profile.get("password") or "").strip(),
        "crsData": None,
        "legalAgreements": {},
    }


def _signup_response_parts(signup_payload: dict[str, Any]) -> dict[str, Any]:
    errors = signup_payload.get("errors") or []
    first_error = errors[0] if errors else {}
    raw_error_data = first_error.get("errorData") or {}
    first_error_data = raw_error_data if isinstance(raw_error_data, dict) else {}
    first_error_item = raw_error_data[0] if isinstance(raw_error_data, list) and raw_error_data and isinstance(raw_error_data[0], dict) else {}
    error_code = (
        (first_error_data.get("0") or {}).get("code")
        or first_error_item.get("code")
        or (first_error.get("checkpoints") or [""])[0]
        or first_error.get("message")
        or "UNKNOWN"
    )
    onboard = (signup_payload.get("data") or {}).get("onboardAccount") or {}
    buyer = onboard.get("buyer") or {}
    return {
        "errors": errors,
        "first_error": first_error,
        "error_code": error_code,
        "euat": ((buyer.get("auth") or {}).get("accessToken") or first_error_data.get("accessToken")),
        "user_id": buyer.get("userId"),
    }


def _paypal_fn_sync_data(ec_token: str) -> str:
    payload = {
        "SC_VERSION": "2.0.4",
        "syncStatus": "data",
        "f": ec_token,
        "s": "IWC_LOGIN_APP",
        "dc": json.dumps(
            {
                "screen": {
                    "colorDepth": 24,
                    "pixelDepth": 24,
                    "height": 900,
                    "width": 1440,
                    "availHeight": 820,
                    "availWidth": 1440,
                },
                "ua": USER_AGENT,
            },
            separators=(",", ":"),
        ),
        "wv": False,
        "web_integration_type": "WEB_REDIRECT",
        "cookie_enabled": True,
    }
    return urllib.parse.quote(json.dumps(payload, separators=(",", ":")))


def run_paypal_no_card_protocol_signup(
    http: Any,
    *,
    ba_token: str,
    signup_profile: dict[str, Any],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    locale_country: str = "US",
    locale_lang: str = "en",
) -> dict[str, Any]:
    timeout = max(20, min(int(timeout_seconds or 180), 300))
    locale_country = str(locale_country or "US").strip().upper() or "US"
    locale_lang = str(locale_lang or "en").strip().lower() or "en"
    rejected_phone = str(signup_profile.get("phone") or "")
    try:
        if callable(is_cancelled) and is_cancelled():
            return {"status": "failed", "failure_stage": "paypal_protocol", "message": "任务已取消"}
        _emit(on_progress, "paypal_create_account", "协议模式：开始 PayPal 无卡注册")
        ec_token, signup_url, signup_html = _bootstrap(
            http,
            ba_token,
            locale_country=locale_country,
            locale_lang=locale_lang,
            timeout=timeout,
        )
        _emit(on_progress, "paypal_wait_signup_form", signup_url=signup_url)
        signup_profile = dict(signup_profile or {})
        signup_profile["_signup_html"] = signup_html

        for op_name, variables, query in (
            (
                "DeferredFeature",
                {
                    "channel": "WEB",
                    "countryCodeAsString": locale_country,
                    "integrationType": "XoSignupAuth",
                    "isBaslAsString": "false",
                    "isForcedGuest": "false",
                    "token": ec_token,
                },
                Q_DEFERRED,
            ),
            (
                "GriffinMetadataQuery",
                {"countryCode": locale_country, "languageCode": locale_lang, "shippingCountryCode": locale_country},
                Q_GRIFFIN_METADATA,
            ),
            ("CheckoutSessionDataQuery", {"token": ec_token}, Q_CHECKOUT_SESSION),
        ):
            try:
                _gql(http, op_name, variables, query, signup_url=signup_url, timeout=timeout, locale_lang=locale_lang)
            except Exception as exc:
                logger.info("[paypal_protocol_signup] warmup %s soft-failed: %s", op_name, exc)

        _emit(on_progress, "paypal_wait_signup_otp", phone=rejected_phone)
        calling_code, subscriber = _phone_split(rejected_phone)
        init_payload = _gql(
            http,
            "InitiateRiskBasedTwoFactorPhoneConfirmationMutation",
            {
                "locale": {"country": locale_country, "lang": locale_lang},
                "phoneCountry": PAYPAL_CALLING_CODE_COUNTRIES.get(calling_code, locale_country),
                "phoneNumber": subscriber,
                "token": ec_token,
            },
            Q_INIT_OTP,
            signup_url=signup_url,
            timeout=timeout,
            locale_lang=locale_lang,
        )
        init_data = (init_payload.get("data") or {}).get("initiateRiskBasedTwoFactorPhoneConfirmation") or {}
        auth_id = str(init_data.get("authId") or "")
        challenge_id = str(init_data.get("challengeId") or "")
        if not auth_id or not challenge_id:
            return {
                "status": "failed",
                "failure_stage": "paypal_phone_rejected",
                "message": "PayPal 拒绝当前手机号，请更换手机号",
                "rejected_phone": rejected_phone,
            }
        if os.environ.get("AUTOTEAM_PAYPAL_STOP_AFTER_OTP_INIT"):
            _emit(on_progress, "paypal_wait_sms_otp_window", phone=rejected_phone)
            return {
                "status": "needs_review",
                "failure_stage": "paypal_wait_signup_otp",
                "message": "PayPal 已发起手机号验证码，按调试开关停止，未拉取或提交验证码",
                "rejected_phone": rejected_phone,
            }

        def _otp_progress(stage: str, **extra: Any) -> None:
            stage_map = {
                "wait_sms_otp_window": "paypal_wait_sms_otp_window",
                "fetch_otp": "paypal_fetch_otp",
                "sms_otp_resend_due": "paypal_sms_otp_resend_due",
                "sms_provider_resend_triggered": "paypal_sms_provider_resend_triggered",
            }
            mapped = stage_map.get(stage)
            if mapped:
                _emit(on_progress, mapped, **extra)

        otp_provider = _poll_otp_from_sms_url(
            str(signup_profile.get("sms_url") or ""),
            timeout_seconds=PAYPAL_PROTOCOL_OTP_TIMEOUT_SECONDS,
            initial_delay_seconds=0,
            resend_after_seconds=PAYPAL_PROTOCOL_OTP_RESEND_AFTER_SECONDS,
            max_resend_attempts=PAYPAL_PROTOCOL_OTP_MAX_RESEND_ATTEMPTS,
            is_cancelled=is_cancelled,
            progress=_otp_progress,
        )
        code = otp_provider()
        _emit(on_progress, "paypal_otp_received", code=code)
        _emit(on_progress, "paypal_submit_otp")
        confirm_payload = _gql(
            http,
            "ConfirmRiskBasedTwoFactorPhoneConfirmationMutation",
            {"authId": auth_id, "challengeId": challenge_id, "pin": code, "token": ec_token},
            Q_CONFIRM_OTP,
            signup_url=signup_url,
            timeout=timeout,
            locale_lang=locale_lang,
        )
        confirm_state = ((confirm_payload.get("data") or {}).get("confirmRiskBasedTwoFactorPhoneConfirmation") or {}).get("state")
        if str(confirm_state or "").upper() != "CONFIRMED":
            return {
                "status": "failed",
                "failure_stage": "paypal_signup",
                "message": f"PayPal 短信验证码确认失败: {confirm_state or 'unknown'}",
                "rejected_phone": rejected_phone,
            }

        _emit(on_progress, "paypal_submit_signup")
        signup_payload = _gql(
            http,
            "SignUpNewMemberMutation",
            _signup_variables(
                signup_profile=signup_profile,
                ec_token=ec_token,
                locale_country=locale_country,
                locale_lang=locale_lang,
            ),
            Q_SIGNUP,
            signup_url=signup_url,
            timeout=timeout,
            locale_lang=locale_lang,
            extra_body={"fn_sync_data": _paypal_fn_sync_data(ec_token)},
        )
        signup_parts = _signup_response_parts(signup_payload)
        if signup_parts["errors"] and not signup_parts["euat"]:
            raw_message = json.dumps(signup_parts["errors"], ensure_ascii=False)
            stage, message = _classify_error_text(raw_message)
            return {
                "status": "failed",
                "failure_stage": stage if stage != "paypal_protocol" else "paypal_signup",
                "message": message if stage != "paypal_protocol" else str(signup_parts["first_error"].get("message") or signup_parts["error_code"]),
                "rejected_phone": rejected_phone,
                "ec_token": ec_token,
            }
        euat = str(signup_parts["euat"] or "")
        if not euat:
            return {
                "status": "failed",
                "failure_stage": "paypal_signup",
                "message": "PayPal 注册未返回 accessToken",
                "rejected_phone": rejected_phone,
                "ec_token": ec_token,
            }

        _emit(on_progress, "paypal_approve_clicked", "协议模式：正在提交 PayPal authorize")
        headers_html = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,*/*;q=0.8",
            "Referer": signup_url,
            "X-PayPal-Internal-EUAT": euat,
        }
        try:
            http.get(f"{PP_ORIGIN}/checkoutweb/drop", headers=headers_html, timeout=timeout)
        except Exception as exc:
            logger.info("[paypal_protocol_signup] checkoutweb/drop soft-failed: %s", exc)
        try:
            signup_qs = urllib.parse.parse_qs(urllib.parse.urlparse(signup_url).query)
        except Exception:
            signup_qs = {}
        hermes_params: list[tuple[str, str]] = []
        ssrt = (signup_qs.get("ssrt") or [""])[0]
        if ssrt:
            hermes_params.append(("ssrt", ssrt))
        hermes_params.extend(
            [
                ("ul", "1"),
                ("country.x", locale_country),
                ("locale.x", f"{locale_lang}_{locale_country}"),
                ("modxo_redirect_reason", "guest_user"),
                ("ba_token", ba_token),
                ("token", ec_token),
                ("rcache", "1"),
                ("cookieBannerVariant", "hidden"),
                ("fromSignupLite", "true"),
            ]
        )
        hermes_url = f"{PP_ORIGIN}/webapps/hermes?{urllib.parse.urlencode(hermes_params)}"
        try:
            http.get(hermes_url, headers=headers_html, timeout=timeout)
        except Exception as exc:
            logger.info("[paypal_protocol_signup] webapps/hermes soft-failed: %s", exc)
        auth_resp = http.post(
            f"{PP_ORIGIN}/graphql/",
            json=[
                {
                    "operationName": "authorize",
                    "variables": {
                        "billingAgreementId": ec_token,
                        "fundingPreference": {"balancePreference": "OPT_OUT"},
                        "legalAgreements": {},
                    },
                    "query": Q_AUTHORIZE,
                }
            ],
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Origin": PP_ORIGIN,
                "Referer": hermes_url,
                "X-Requested-With": "fetch",
                "X-App-Name": "checkoutuinodeweb",
                "X-PayPal-Internal-EUAT": euat,
            },
            timeout=timeout,
        )
        try:
            auth_json = auth_resp.json()
        except Exception as exc:
            stage, message = _classify_error_text(str(auth_resp.text or ""))
            if stage != "paypal_protocol":
                raise RuntimeError(f"{stage}|{message}") from exc
            raise RuntimeError(
                f"paypal_protocol|PayPal authorize 返回非 JSON: HTTP {auth_resp.status_code}"
            ) from exc
        auth_payload = auth_json[0] if isinstance(auth_json, list) and auth_json else {}
        authorize = ((auth_payload.get("data") or {}).get("billing") or {}).get("authorize") or {}
        return_url = str((authorize.get("returnURL") or {}).get("href") or "")
        if not return_url:
            return {
                "status": "needs_review",
                "failure_stage": "paypal_protocol_authorize",
                "message": "PayPal authorize 未返回跳转链接，需要人工确认",
                "ec_token": ec_token,
                "euat": euat,
                "paypal_user_id": (authorize.get("buyer") or {}).get("userId") or signup_parts["user_id"],
                "ba_token": str(authorize.get("billingAgreementToken") or ba_token),
            }
        return {
            "status": "success",
            "failure_stage": "",
            "message": "PayPal 协议注册与 authorize 已完成",
            "return_url": return_url,
            "ec_token": ec_token,
            "euat": euat,
            "paypal_user_id": (authorize.get("buyer") or {}).get("userId") or signup_parts["user_id"],
            "ba_token": str(authorize.get("billingAgreementToken") or ba_token),
        }
    except GoPayOTPCancelled as exc:
        return {
            "status": "failed",
            "failure_stage": "fetch_otp",
            "message": str(exc),
            "rejected_phone": rejected_phone,
            "ba_token": ba_token,
        }
    except Exception as exc:
        raw_message = str(exc)
        if "|" in raw_message:
            stage, message = raw_message.split("|", 1)
            return {
                "status": "failed" if stage != "paypal_human_verification" else "needs_review",
                "failure_stage": stage,
                "message": message,
                "rejected_phone": rejected_phone,
                "ba_token": ba_token,
            }
        stage, message = _classify_error_text(raw_message)
        return {
            "status": "failed" if stage != "paypal_human_verification" else "needs_review",
            "failure_stage": stage,
            "message": message,
            "rejected_phone": rejected_phone,
            "ba_token": ba_token,
        }
