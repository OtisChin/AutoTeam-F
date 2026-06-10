from __future__ import annotations

import json
import html as html_lib
import logging
import os
import random
import re
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from autotoken.services import payment_errors as payment_errors_service
from autotoken.services import payment_form_fields as payment_form_fields_service
from autotoken.services import sms_otp as sms_otp_service

logger = logging.getLogger(__name__)

PP_ORIGIN = "https://www.paypal.com"
PAYPAL_PROTOCOL_OTP_TIMEOUT_SECONDS = 300
PAYPAL_PROTOCOL_OTP_RESEND_AFTER_SECONDS = 60
PAYPAL_PROTOCOL_OTP_MAX_RESEND_ATTEMPTS = 0
PAYPAL_PROTOCOL_OTP_CONFIRM_MAX_ATTEMPTS = 2
GoPayOTPCancelled = payment_errors_service.PaymentOTPCancelled
DEFAULT_PAYPAL_JP_BIRTH_DATE = "1985/01/15"
DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME = "太郎"
DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME = "山田"
DEFAULT_PAYPAL_JP_KANA_FIRST_NAME = "タロウ"
DEFAULT_PAYPAL_JP_KANA_LAST_NAME = "ヤマダ"
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
USER_AGENT = str(
    os.environ.get("PAYPAL_PROTOCOL_USER_AGENT")
    or "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) CriOS/147.0.7727.25 Mobile/15E148 Safari/537.36"
)
PAYPAL_PROTOCOL_ACCEPT_LANGUAGE = str(
    os.environ.get("PAYPAL_PROTOCOL_ACCEPT_LANGUAGE") or "en-US,en;q=0.9"
)
PAYPAL_PROTOCOL_NAV_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
    "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
)


def _poll_otp_from_sms_url(
    sms_url: str,
    *,
    timeout_seconds: int,
    initial_delay_seconds: float | None = None,
    resend_after_seconds: float | None = None,
    max_resend_attempts: int | None = None,
    is_cancelled=None,
    progress=None,
):
    return sms_otp_service.poll_otp_from_sms_url(
        sms_url,
        timeout_seconds=timeout_seconds,
        initial_delay_seconds=initial_delay_seconds,
        resend_after_seconds=resend_after_seconds,
        max_resend_attempts=max_resend_attempts,
        is_cancelled=is_cancelled,
        progress=progress,
        cancelled_error_factory=lambda message: GoPayOTPCancelled(message, stage="fetch_otp"),
        otp_label="PayPal OTP",
    )


def _snapshot_existing_sms_otps(sms_url: str) -> set[str]:
    url = str(sms_url or "").strip()
    if not url:
        return set()
    try:
        code = sms_otp_service.fetch_sms_code(url)
    except Exception as exc:
        logger.info("[paypal_protocol_signup] SMS pre-snapshot has no reusable code: %s", exc)
        return set()
    code = str(code or "").strip()
    return {code} if code else set()


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
DATADOME_INTERSTITIAL_HINTS = (
    "ads-dd-captcha",
    "adsddtoken",
    "adsddcaptcha",
    "ct.ddc.paypal.com/i.js",
    "geo.ddc.paypal.com",
    "please enable js and disable any ad blocker",
)

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
  $bank: BankAccountInput
  $billingAddress: AddressInput
  $card: CardInput
  $contentIdentifier: String
  $country: CountryCodes
  $countrySpecificFirstName: String
  $countrySpecificLastName: String
  $crsData: CommonReportingStandardsInput
  $currencyConversionType: CheckoutCurrencyConversionType
  $dateOfBirth: DateOfBirth
  $email: String!
  $firstName: String!
  $gender: Gender
  $identityDocument: IdentityDocumentInput
  $lastName: String!
  $middleName: String
  $marketingOptOut: Boolean
  $nationality: CountryCodes
  $occupation: Occupation
  $password: String
  $phone: PhoneInput!
  $placeOfBirth: CountryCodes
  $secondaryIdentityDocument: IdentityDocumentInput
  $selectedInstallmentOption: InstallmentsInput
  $shareAddressWithDonatee: Boolean
  $shippingAddress: AddressInput
  $supportedThreeDsExperiences: [ThreeDSPaymentExperience]
  $token: String!
  $residentialAddress: AddressInput
  $isSignupIncentiveOptIn: Boolean
  $isSignupIncentiveOptInStretch: Boolean
  $legalAgreements: LegalAgreementsInput
  $collectedConsents: [CollectedConsent]
) {
  onboardAccount: signUpNewMember(
    bank: $bank
    billingAddress: $billingAddress
    card: $card
    contentIdentifier: $contentIdentifier
    countrySpecificFirstName: $countrySpecificFirstName
    countrySpecificLastName: $countrySpecificLastName
    country: $country
    crsData: $crsData
    currencyConversionType: $currencyConversionType
    dateOfBirth: $dateOfBirth
    email: $email
    firstName: $firstName
    gender: $gender
    identityDocument: $identityDocument
    lastName: $lastName
    middleName: $middleName
    marketingOptOut: $marketingOptOut
    nationality: $nationality
    occupation: $occupation
    password: $password
    phone: $phone
    placeOfBirth: $placeOfBirth
    secondaryIdentityDocument: $secondaryIdentityDocument
    selectedInstallmentOption: $selectedInstallmentOption
    shareAddressWithDonatee: $shareAddressWithDonatee
    shippingAddress: $shippingAddress
    token: $token
    residentialAddress: $residentialAddress
    isSignupIncentiveOptIn: $isSignupIncentiveOptIn
    isSignupIncentiveOptInStretch: $isSignupIncentiveOptInStretch
    legalAgreements: $legalAgreements
    collectedConsents: $collectedConsents
  ) {
    ...buyer
    flags {
      is3DSecureRequired
      __typename
    }
    ...fundingOptions
    paymentContingencies {
      ...threeDomainSecure
      ...threeDSContingencyData
      __typename
    }
    __typename
  }
}

fragment buyer on CheckoutSession {
  buyer {
    auth {
      accessToken
      __typename
    }
    userId
    __typename
  }
  __typename
}

fragment fundingOptions on CheckoutSession {
  fundingOptions {
    allPlans {
      fundingSources {
        fundingInstrument {
          id
          __typename
        }
        amount {
          currencyCode
          currencyValue
          __typename
        }
        __typename
      }
      fundingContingencies {
        ... on OpenBankingContingency {
          encryptedId
          contingencyReasons
          contingencyType
          __typename
        }
        __typename
      }
      __typename
    }
    fundingInstrument {
      id
      lastDigits
      name
      nameDescription
      type
      __typename
    }
    __typename
  }
  __typename
}

fragment threeDomainSecure on PaymentContingencies {
  threeDomainSecure(experiences: $supportedThreeDsExperiences) {
    status
    redirectUrl {
      href
      __typename
    }
    method
    parameter
    experience
    requestParams {
      key
      value
      __typename
    }
    __typename
  }
  __typename
}

fragment threeDSContingencyData on PaymentContingencies {
  threeDSContingencyData {
    name
    causeName
    resolution {
      type
      resolutionName
      paymentCard {
        billingAddress {
          line1
          line2
          city
          state
          country
          postalCode
          __typename
        }
        expireYear
        expireMonth
        currencyCode
        cardProductClass
        id
        encryptedNumber
        type
        number
        bankIdentificationNumber
        __typename
      }
      contingencyContext {
        deviceDataCollectionUrl {
          href
          __typename
        }
        jwtSpecification {
          jwtDuration
          jwtIssuer
          jwtOrgUnitId
          type
          __typename
        }
        authenticationProvider
        cardBrandProcessed
        reason
        referenceId
        source
        __typename
      }
      __typename
    }
    __typename
  }
  __typename
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
        raise RuntimeError(f"{stage} 返回非 JSON: HTTP {getattr(resp, 'status_code', '?')} {text[:300]}") from exc
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
    if any(hint in text for hint in DATADOME_INTERSTITIAL_HINTS):
        return True
    if any(hint in text for hint in DATADOME_RESPONSE_HINTS):
        # 排除包含正常 PayPal 内容的页面（如 signup form 中提到 captcha 的正常文本）
        return not ("EC-" in str(getattr(resp, "text", "") or "") or "checkoutweb" in text)
    return False


def _warmup_paypal_session(
    http: Any,
    *,
    timeout: int = 15,
    locale_country: str = "US",
    locale_lang: str = "en",
) -> None:
    """预热 PayPal session，获取 DataDome 和基础 cookies"""
    country = str(locale_country or "US").strip().upper() or "US"
    lang = str(locale_lang or "en").strip().lower() or "en"
    path = "/jp/home" if country == "JP" and lang == "ja" else "/"
    try:
        http.get(
            f"{PP_ORIGIN}{path}",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": PAYPAL_PROTOCOL_NAV_ACCEPT,
                "Accept-Language": PAYPAL_PROTOCOL_ACCEPT_LANGUAGE,
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
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
        params = [(key, current) for key, current in params if key != "ulOnboardRedirect"]
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
        "Accept": PAYPAL_PROTOCOL_NAV_ACCEPT,
        "Accept-Language": PAYPAL_PROTOCOL_ACCEPT_LANGUAGE,
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    try:
        resp = http.get(signup_url, headers=headers, timeout=timeout, allow_redirects=False)
    except Exception as exc:
        logger.info("[paypal_protocol_signup] prime signup soft-failed: %s", exc)
        return signup_url, ""
    text = str(getattr(resp, "text", "") or "")
    status = int(getattr(resp, "status_code", 0) or 0)
    location = (
        (getattr(resp, "headers", {}) or {}).get("location")
        or (getattr(resp, "headers", {}) or {}).get("Location")
        or ""
    )
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


def _bootstrap(
    http: Any,
    ba_token: str,
    *,
    locale_country: str,
    locale_lang: str,
    timeout: int,
    approve_url: str = "",
) -> tuple[str, str, str]:
    if approve_url:
        url = _coerce_onboard_url(
            approve_url,
            ba_token=ba_token,
            locale_country=locale_country,
            locale_lang=locale_lang,
        )
    else:
        url = (
            f"{PP_ORIGIN}/agreements/approve?ba_token={urllib.parse.quote(ba_token)}"
            f"&country.x={urllib.parse.quote(locale_country)}"
            f"&locale.x={urllib.parse.quote(f'{locale_lang}_{locale_country}')}"
        )
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": PAYPAL_PROTOCOL_NAV_ACCEPT,
        "Accept-Language": PAYPAL_PROTOCOL_ACCEPT_LANGUAGE,
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }

    # 预热 — 提前访问 paypal.com 获取 DataDome 基础 cookies
    _warmup_paypal_session(
        http,
        timeout=min(timeout, 15),
        locale_country=locale_country,
        locale_lang=locale_lang,
    )
    time.sleep(random.uniform(0.5, 1.5))

    # DataDome 拦截不是同一 HTTP session 原地重试能稳定解决的问题；尽快返回给上层
    # 浏览器兜底，保留同一代理与真实页面上下文处理安全检查。
    resp = http.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if _is_datadome_blocked(resp):
        logger.info(
            "[paypal_protocol_signup] /agreements/approve DataDome blocked; switching to browser fallback",
        )
        raise RuntimeError(
            "paypal_human_verification|PayPal /agreements/approve 被 DataDome 风控拦截，已停止协议重试并降级浏览器处理"
        )
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
    onboard_source_url = ""
    onboard_url = _build_onboard_url(ba_token, locale_country, locale_lang, source_url=url)
    if onboarding_match:
        onboard_source_url = _unescape_url(onboarding_match.group(1))
        if onboard_source_url.startswith("/"):
            onboard_source_url = PP_ORIGIN + onboard_source_url
        onboard_url = onboard_source_url
    onboard_url = _coerce_onboard_url(
        onboard_url, ba_token=ba_token, locale_country=locale_country, locale_lang=locale_lang
    )
    signup_url = _build_signup_url(
        ba_token,
        ec_token,
        locale_country,
        locale_lang,
        source_url=onboard_source_url or onboard_url or url,
    )
    signup_url, signup_html = _prime_checkout_signup(
        http,
        signup_url=signup_url,
        referer=onboard_url,
        locale_country=locale_country,
        locale_lang=locale_lang,
        timeout=timeout,
    )
    match_ec2 = _EC_RE.search(f"{signup_url}\n{signup_html}")
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
            "Accept-Language": PAYPAL_PROTOCOL_ACCEPT_LANGUAGE,
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
            raise RuntimeError(
                f"paypal_human_verification|PayPal GraphQL {op_name} 被 DataDome 风控拦截 (HTTP {resp.status_code})"
            )
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


def _gql_with_retry(
    http: Any,
    op_name: str,
    variables: dict[str, Any],
    query: str,
    *,
    signup_url: str,
    timeout: int,
    locale_lang: str = "en",
    extra_body: dict[str, Any] | None = None,
    attempts: int = 2,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, max(1, int(attempts or 1)) + 1):
        try:
            return _gql(
                http,
                op_name,
                variables,
                query,
                signup_url=signup_url,
                timeout=timeout,
                locale_lang=locale_lang,
                extra_body=extra_body,
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= max(1, int(attempts or 1)):
                break
            message = str(exc)
            if "timeout" not in message.lower() and "request canceled" not in message.lower():
                break
            logger.info("[paypal_protocol_signup] GraphQL %s timed out, retrying %s/%s", op_name, attempt + 1, attempts)
            time.sleep(2.0)
    raise last_exc or RuntimeError(f"paypal_protocol|GraphQL {op_name} failed")


def _phone_split(phone: str, *, country: str = "") -> tuple[str, str]:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if str(phone or "").strip().startswith("+"):
        for code in sorted(PAYPAL_CALLING_CODE_COUNTRIES, key=len, reverse=True):
            if digits.startswith(code) and len(digits) - len(code) >= 7:
                return code, digits[len(code) :]
    normalized_country = str(country or "").strip().upper()
    if normalized_country == "JP":
        if digits.startswith("0081") and len(digits) >= 12:
            digits = digits[2:]
        if digits.startswith("81") and len(digits) - 2 >= 9:
            subscriber = digits[2:]
            return "81", subscriber[1:] if subscriber.startswith("0") else subscriber
        if digits.startswith("0") and len(digits) in {10, 11}:
            return "81", digits[1:]
        if len(digits) in {9, 10} and digits.startswith(("70", "80", "90")):
            return "81", digits
    if normalized_country == "US" and len(digits) == 11 and digits.startswith("1"):
        return "1", digits[1:]
    if len(digits) == 10:
        return "1", digits
    raise ValueError(f"unparseable phone: {phone}")


def _extract_content_identifier(html: str, locale_country: str, locale_lang: str) -> str:
    raw_html = str(html or "")
    decoded_html = urllib.parse.unquote(html_lib.unescape(raw_html))
    decoded_html = re.sub(
        r"\\+u003a",
        ":",
        decoded_html,
        flags=re.I,
    )
    for pattern in (
        r'"contentIdentifier"\s*:\s*"([^"]*signupTerms[^"]*)"',
        r'\\"contentIdentifier\\"\s*:\s*\\"([^"\\]*signupTerms[^"\\]*)\\"',
        r"([A-Z]{2}:[a-z]{2}:[0-9a-f]{16,64}:compliance\.signupTerms)",
    ):
        for candidate in (raw_html, decoded_html):
            match = re.search(pattern, candidate, re.I)
            if match:
                return match.group(1).replace("\\/", "/")
    if locale_country.upper() == "US" and locale_lang.lower() == "en":
        return "US:en:f411614ea3eaac38abc54763fcfca00e:compliance.signupTerms"
    if locale_country.upper() == "JP" and locale_lang.lower() == "ja":
        return "JP:ja:7b6ca42fbd7ddea17db0dcd181eeb3a4:compliance.signupTerms"
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


def _date_of_birth(value: Any, *, country: str) -> dict[str, str] | None:
    raw = str(value or "").strip()
    if not raw and str(country or "").strip().upper() == "JP":
        raw = DEFAULT_PAYPAL_JP_BIRTH_DATE
    digits = re.findall(r"\d+", raw)
    if len(digits) >= 3:
        year, month, day = digits[0], digits[1], digits[2]
        if len(year) == 4:
            return {"day": day.zfill(2), "month": month.zfill(2), "year": year}
        if len(digits[2]) == 4:
            return {"day": digits[0].zfill(2), "month": digits[1].zfill(2), "year": digits[2]}
    return None


def _card_type(card_number: str) -> str:
    digits = re.sub(r"\D+", "", str(card_number or ""))
    if digits.startswith(("34", "37")):
        return "AMEX"
    if digits.startswith("5") or (len(digits) >= 4 and 2221 <= int(digits[:4]) <= 2720):
        return "MASTER_CARD"
    return "VISA"


def _paypal_protocol_card(signup_profile: dict[str, Any]) -> dict[str, str]:
    card_number = payment_form_fields_service.normalize_or_generate_paypal_card_number(
        str(signup_profile.get("card_number") or "")
    )
    raw_expiry = str(signup_profile.get("card_expiry") or "").strip()
    if raw_expiry:
        expiry = payment_form_fields_service.normalize_paypal_card_expiry(raw_expiry)
    else:
        expiry = payment_form_fields_service.generate_paypal_card_expiry()
    expiry_digits = re.sub(r"\D+", "", expiry)
    if len(expiry_digits) == 4:
        expiry = f"{expiry_digits[:2]}/20{expiry_digits[2:]}"
    elif len(expiry_digits) == 6:
        expiry = f"{expiry_digits[:2]}/{expiry_digits[2:]}"
    cvv = re.sub(r"\D+", "", str(signup_profile.get("card_cvv") or ""))
    if not cvv:
        cvv = payment_form_fields_service.generate_paypal_card_cvv(card_number)
    return {
        "cardNumber": card_number,
        "expirationDate": expiry,
        "securityCode": cvv,
        "type": _card_type(card_number),
    }


def _contains_japanese_kana(value: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff]", str(value or "")))


def _signup_variables(
    *, signup_profile: dict[str, Any], ec_token: str, locale_country: str, locale_lang: str
) -> dict[str, Any]:
    country = str(signup_profile.get("country") or locale_country or "US").strip().upper() or "US"
    calling_code, subscriber = _phone_split(str(signup_profile.get("phone") or ""), country=country)
    first_name = str(signup_profile.get("first_name") or "").strip()
    last_name = str(signup_profile.get("last_name") or "").strip()
    if not first_name or not last_name:
        first_name, last_name = _split_name(signup_profile.get("name") or "")
    native_first_name = str(
        signup_profile.get("native_first_name") or signup_profile.get("nativeFirstName") or ""
    ).strip()
    native_last_name = str(
        signup_profile.get("native_last_name") or signup_profile.get("nativeLastName") or ""
    ).strip()
    if country == "JP":
        kana_first_name = first_name if _contains_japanese_kana(first_name) else DEFAULT_PAYPAL_JP_KANA_FIRST_NAME
        kana_last_name = last_name if _contains_japanese_kana(last_name) else DEFAULT_PAYPAL_JP_KANA_LAST_NAME
        first_name = native_first_name or (first_name if first_name and not _contains_japanese_kana(first_name) else "")
        last_name = native_last_name or (last_name if last_name and not _contains_japanese_kana(last_name) else "")
        first_name = first_name or DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME
        last_name = last_name or DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME
        native_first_name = kana_first_name
        native_last_name = kana_last_name
    address = {
        "line1": str(signup_profile.get("address1") or "").strip(),
        "postalCode": str(signup_profile.get("zip") or "").strip(),
        "accountQuality": {"autoCompleteType": "MANUAL", "isUserModified": True},
        "country": country,
        "familyName": last_name,
        "givenName": first_name,
    }
    city = str(signup_profile.get("city") or "").strip()
    if city:
        address["city"] = city
    state = _state_code(signup_profile.get("state") or "")
    if state:
        address["state"] = state
    shipping_address = {
        "line1": str(address.get("line1") or ""),
        "state": str(address.get("state") or ""),
        "postalCode": str(address.get("postalCode") or ""),
        "accountQuality": {"autoCompleteType": "MANUAL", "isUserModified": False},
        "country": country,
        "familyName": last_name,
        "givenName": first_name,
    }
    if country != "JP":
        shipping_address["city"] = str(address.get("city") or "")
    variables = {
        "card": _paypal_protocol_card(signup_profile),
        "country": locale_country,
        "email": str(signup_profile.get("email") or "").strip(),
        "firstName": first_name,
        "lastName": last_name,
        "phone": {"countryCode": calling_code, "number": subscriber, "type": "MOBILE"},
        "supportedThreeDsExperiences": ["IFRAME"],
        "token": ec_token,
        "billingAddress": address,
        "shippingAddress": shipping_address,
        "contentIdentifier": _extract_content_identifier(
            str(signup_profile.get("_signup_html") or ""), locale_country, locale_lang
        ),
        "marketingOptOut": False,
        "nationality": country,
        "password": str(signup_profile.get("password") or "").strip(),
        "crsData": None,
        "legalAgreements": {},
    }
    dob = _date_of_birth(signup_profile.get("birth_date") or signup_profile.get("birthDate"), country=country)
    if dob:
        variables["dateOfBirth"] = dob
    if country == "JP":
        variables["countrySpecificFirstName"] = native_first_name
        variables["countrySpecificLastName"] = native_last_name
    return variables


def _signup_response_parts(signup_payload: dict[str, Any]) -> dict[str, Any]:
    errors = signup_payload.get("errors") or []
    first_error = errors[0] if errors else {}
    raw_error_data = first_error.get("errorData") or {}
    first_error_data = raw_error_data if isinstance(raw_error_data, dict) else {}
    first_error_item = (
        raw_error_data[0]
        if isinstance(raw_error_data, list) and raw_error_data and isinstance(raw_error_data[0], dict)
        else {}
    )
    error_code = (
        (first_error_data.get("0") or {}).get("code")
        or first_error_item.get("code")
        or (first_error.get("checkpoints") or [""])[0]
        or first_error.get("message")
        or "UNKNOWN"
    )
    data = signup_payload.get("data") or {}
    onboard = data.get("signUpNewMember") or data.get("onboardAccount") or {}
    buyer = onboard.get("buyer") or {}
    error_metadata = _signup_error_metadata(first_error)
    return {
        "errors": errors,
        "first_error": first_error,
        "error_code": error_code,
        "error_metadata": error_metadata,
        "euat": ((buyer.get("auth") or {}).get("accessToken") or first_error_data.get("accessToken")),
        "user_id": buyer.get("userId"),
    }


def _signup_error_metadata(first_error: Any) -> dict[str, Any]:
    if not isinstance(first_error, dict):
        return {}
    allowed_scalar_keys = {
        "classification",
        "code",
        "correlationId",
        "correlationID",
        "debugId",
        "issue",
        "name",
        "status",
        "statusCode",
    }
    metadata: dict[str, Any] = {}
    for key in ("checkpoints", "path"):
        value = first_error.get(key)
        if isinstance(value, list):
            metadata[key] = [str(item)[:160] for item in value[:10] if isinstance(item, (str, int, float))]

    def visit(value: Any, *, depth: int = 0) -> None:
        if depth >= 4:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                name = str(key or "")
                if name in allowed_scalar_keys and isinstance(child, (str, int, float, bool)):
                    metadata.setdefault(name, str(child)[:200])
                elif name not in {"accessToken", "email", "password", "token"}:
                    visit(child, depth=depth + 1)
        elif isinstance(value, list):
            for child in value[:10]:
                visit(child, depth=depth + 1)

    visit(first_error)
    return metadata


def _classify_signup_error(signup_parts: dict[str, Any]) -> tuple[str, str]:
    first_error = signup_parts.get("first_error") or {}
    error_code = str(signup_parts.get("error_code") or "").strip()
    metadata = signup_parts.get("error_metadata") or {}
    checkpoints = {str(item or "") for item in metadata.get("checkpoints") or []}
    if error_code.upper() == "OAS_ERROR" and "createMemberAccount" in checkpoints:
        return (
            "paypal_browser_context_required",
            "PayPal 在 createMemberAccount 阶段拒绝纯协议请求，需要真实浏览器风险上下文",
        )
    raw_message = json.dumps(signup_parts.get("errors") or [], ensure_ascii=False)
    stage, message = _classify_error_text(raw_message)
    if stage != "paypal_protocol":
        return stage, message
    return "paypal_signup", str(first_error.get("message") or error_code or "PayPal 注册失败")


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
    approve_url: str = "",
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
            approve_url=approve_url,
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

        sms_url = str(signup_profile.get("sms_url") or "")
        ignored_otps = _snapshot_existing_sms_otps(sms_url)
        _emit(on_progress, "paypal_wait_signup_otp", phone=rejected_phone)
        calling_code, subscriber = _phone_split(rejected_phone, country=locale_country)
        init_payload = _gql_with_retry(
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
        if os.environ.get("AUTOTOKEN_PAYPAL_STOP_AFTER_OTP_INIT"):
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
            sms_url,
            timeout_seconds=PAYPAL_PROTOCOL_OTP_TIMEOUT_SECONDS,
            initial_delay_seconds=0,
            resend_after_seconds=PAYPAL_PROTOCOL_OTP_RESEND_AFTER_SECONDS,
            max_resend_attempts=PAYPAL_PROTOCOL_OTP_MAX_RESEND_ATTEMPTS,
            is_cancelled=is_cancelled,
            progress=_otp_progress,
        )
        if ignored_otps:
            otp_provider._gopay_ignored_otps = set(ignored_otps)

        def _resend_paypal_protocol_otp() -> None:
            nonlocal auth_id, challenge_id
            resend_payload = _gql_with_retry(
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
            resend_data = (resend_payload.get("data") or {}).get("initiateRiskBasedTwoFactorPhoneConfirmation") or {}
            next_auth_id = str(resend_data.get("authId") or "")
            next_challenge_id = str(resend_data.get("challengeId") or "")
            if not next_auth_id or not next_challenge_id:
                raise RuntimeError("PayPal OTP resend did not return auth/challenge id")
            auth_id = next_auth_id
            challenge_id = next_challenge_id
            _emit(on_progress, "paypal_otp_resend_clicked")

        otp_provider._gopay_resend_callback = _resend_paypal_protocol_otp
        confirm_state = ""
        for confirm_attempt in range(1, max(1, PAYPAL_PROTOCOL_OTP_CONFIRM_MAX_ATTEMPTS) + 1):
            code = otp_provider()
            _emit(on_progress, "paypal_otp_received", code=code, attempt=confirm_attempt)
            _emit(on_progress, "paypal_submit_otp", attempt=confirm_attempt)
            confirm_payload = _gql_with_retry(
                http,
                "ConfirmRiskBasedTwoFactorPhoneConfirmationMutation",
                {"authId": auth_id, "challengeId": challenge_id, "pin": code, "token": ec_token},
                Q_CONFIRM_OTP,
                signup_url=signup_url,
                timeout=timeout,
                locale_lang=locale_lang,
            )
            confirm_state = (
                (confirm_payload.get("data") or {}).get("confirmRiskBasedTwoFactorPhoneConfirmation") or {}
            ).get("state")
            if str(confirm_state or "").upper() == "CONFIRMED":
                break
            if str(confirm_state or "").upper() != "VALIDATION_FAILED" or confirm_attempt >= max(
                1, PAYPAL_PROTOCOL_OTP_CONFIRM_MAX_ATTEMPTS
            ):
                return {
                    "status": "failed",
                    "failure_stage": "paypal_signup",
                    "message": f"PayPal 短信验证码确认失败: {confirm_state or 'unknown'}",
                    "rejected_phone": rejected_phone,
                }
            ignored = set(getattr(otp_provider, "_gopay_ignored_otps", set()))
            ignored.add(str(code or "").strip())
            otp_provider._gopay_ignored_otps = ignored
            _emit(on_progress, "paypal_otp_invalid_retry", attempt=confirm_attempt)

        _emit(on_progress, "paypal_submit_signup")
        signup_payload = _gql_with_retry(
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
            attempts=2,
        )
        signup_parts = _signup_response_parts(signup_payload)
        if signup_parts["errors"] and not signup_parts["euat"]:
            stage, message = _classify_signup_error(signup_parts)
            return {
                "status": "failed",
                "failure_stage": stage,
                "message": message,
                "rejected_phone": rejected_phone,
                "ec_token": ec_token,
                "paypal_error": signup_parts["error_metadata"],
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
            "Accept-Language": PAYPAL_PROTOCOL_ACCEPT_LANGUAGE,
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
                        "fundingPreference": {"balancePreference": "OPT_IN"},
                        "legalAgreements": {},
                    },
                    "query": Q_AUTHORIZE,
                }
            ],
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Accept-Language": PAYPAL_PROTOCOL_ACCEPT_LANGUAGE,
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
            raise RuntimeError(f"paypal_protocol|PayPal authorize 返回非 JSON: HTTP {auth_resp.status_code}") from exc
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
