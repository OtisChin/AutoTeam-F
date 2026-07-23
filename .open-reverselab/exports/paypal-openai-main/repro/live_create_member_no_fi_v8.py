#!/usr/bin/env python3
"""Live v8 probe: createMemberAccount(no FI) then no-FI BA approval variants.

Writes only sanitized JSON/log output. Secrets are read from environment/private files:
  FRESH_BA_SECRET_JSON=/private/tmp/fresh_paypal_ba_secret.json
  SMSCC_RECORD_URL=<fixed phone SMS record API URL>
  PROXY=<proxy URL or host:port:user:pass>
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORK = Path(os.getenv("PAYPAL_WORKDIR", "/tmp/openai-paypal-main-protocol-work"))
sys.path.insert(0, str(WORK))
os.chdir(str(WORK))

from loguru import logger  # type: ignore
from paypal.flow import PayPalFlow  # type: ignore
from paypal.models import generate_user, generate_card, generate_address  # type: ignore
from paypal.proxy import build_proxy_config  # type: ignore
from paypal.session import sanitize_for_log  # type: ignore
from paypal.graphql import APPROVE_MEMBER_PAYMENT_MUTATION, APPROVE_ONBOARD_PAYMENT_MUTATION  # type: ignore
from paypal.analytics import send_analytics_ts, send_weasley_log  # type: ignore
from paypal.fingerprint import send_device_fingerprint, build_signup_fn_sync_data  # type: ignore
from paypal.country_profile import get_country_profile  # type: ignore

CREATE_MEMBER_ACCOUNT_MUTATION = """
mutation CreateMemberAccountMutation($billingAddress: AddressInput, $contentIdentifier: String, $country: CountryCodes!, $crsData: CommonReportingStandardsInput, $dateOfBirth: DateOfBirth, $email: String!, $firstName: String!, $gender: Gender, $identityDocument: IdentityDocumentInput, $lastName: String!, $marketingOptOut: Boolean, $nationality: CountryCodes, $occupation: Occupation, $password: String, $phone: PhoneInput!, $placeOfBirth: CountryCodes, $secondaryIdentityDocument: IdentityDocumentInput, $shippingAddress: AddressInput, $token: String!, $residentialAddress: AddressInput, $legalAgreements: LegalAgreementsInput) {
  onboardAccount: createMemberAccount(
    billingAddress: $billingAddress
    contentIdentifier: $contentIdentifier
    country: $country
    crsData: $crsData
    dateOfBirth: $dateOfBirth
    email: $email
    firstName: $firstName
    gender: $gender
    identityDocument: $identityDocument
    lastName: $lastName
    marketingOptOut: $marketingOptOut
    nationality: $nationality
    occupation: $occupation
    password: $password
    phone: $phone
    placeOfBirth: $placeOfBirth
    secondaryIdentityDocument: $secondaryIdentityDocument
    shippingAddress: $shippingAddress
    token: $token
    residentialAddress: $residentialAddress
    legalAgreements: $legalAgreements
  ) {
    buyer { auth { accessToken __typename } userId __typename }
    __typename
  }
}
"""


def redacted_token(v: str) -> str:
    if not v:
        return ""
    return re.sub(r"([A-Z]{2,4}-)[A-Z0-9]+", r"\1<redacted>", str(v))


def load_ba_token() -> str:
    p = Path(os.getenv("FRESH_BA_SECRET_JSON", "/private/tmp/fresh_paypal_ba_secret.json"))
    data = json.loads(p.read_text())
    fields = ((data.get("result") or {}).get("fields") or {}) if isinstance(data, dict) else {}
    ba = fields.get("ba_token") or data.get("ba_token") or ""
    if not ba:
        raise SystemExit("no ba_token in fresh secret json")
    return str(ba)


@dataclass
class FixedActivation:
    phone_number: str
    provider_id: str = "smscc-fixed"
    reused: bool = True


class FixedSmsccProvider:
    max_attempts = 1
    wait_seconds = float(os.getenv("SMSCC_WAIT_SECONDS", "120"))
    poll_interval = float(os.getenv("SMSCC_POLL_INTERVAL", "5"))

    def __init__(self, phone: str, record_url: str):
        self.phone = phone
        self.record_url = record_url
        self._seen_codes: set[str] = set()
        self._sent_at = time.time()

    def reserve_number(self) -> FixedActivation:
        return FixedActivation(self.phone)

    def mark_sms_sent(self, activation: FixedActivation) -> None:
        self._sent_at = time.time()

    def abandon(self, activation: FixedActivation, reason: str) -> None:
        logger.warning("SMS provider abandon reason={}", reason)

    def register_confirmation_result(self, activation: FixedActivation, confirmed: bool) -> None:
        logger.info("SMS provider confirmation result={}", confirmed)

    @staticmethod
    def _extract_codes(text: str) -> list[str]:
        # PayPal OTPs are 6 digits. Prefer strings near PayPal markers, but keep generic fallback.
        candidates: list[str] = []
        lowered = text.lower()
        for m in re.finditer(r"\b(\d{6})\b", text or ""):
            win = lowered[max(0, m.start()-120):m.end()+120]
            score = 0 if any(x in win for x in ("paypal", "pay pal", "verification", "code")) else 1
            candidates.append((score, m.group(1), m.start()))  # type: ignore[arg-type]
        candidates.sort(key=lambda x: (x[0], -x[2]))
        out: list[str] = []
        for _, code, _pos in candidates:
            if code not in out:
                out.append(code)
        return out

    def wait_for_code(self, activation: FixedActivation, timeout_seconds: float | None = None) -> str | None:
        import urllib.request
        deadline = time.time() + float(timeout_seconds or self.wait_seconds)
        while time.time() < deadline:
            try:
                req = urllib.request.Request(self.record_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                for code in self._extract_codes(raw):
                    if code not in self._seen_codes:
                        self._seen_codes.add(code)
                        return code
            except Exception as exc:
                logger.debug("SMS poll soft-failed: {}", exc)
            time.sleep(self.poll_interval)
        return None


def graphql_errors(result: Any) -> list[dict[str, Any]]:
    obj = result[0] if isinstance(result, list) and result else result
    if isinstance(obj, dict):
        return [x for x in (obj.get("errors") or []) if isinstance(x, dict)]
    return []


def build_create_member_variables(flow: PayPalFlow, token: str) -> dict[str, Any]:
    # Reuse the project's current SignUpNewMember serializer, then project it down
    # to the exact createMemberAccount GraphQL source-map argument set.
    base = flow._build_signup_variables(token)  # noqa: SLF001
    return {
        "billingAddress": base.get("billingAddress"),
        "contentIdentifier": base.get("contentIdentifier"),
        "country": base.get("country") or flow.address.country,
        "crsData": base.get("crsData"),
        "dateOfBirth": base.get("dateOfBirth"),
        "email": base.get("email"),
        "firstName": base.get("firstName"),
        "gender": base.get("gender"),
        "identityDocument": base.get("identityDocument"),
        "lastName": base.get("lastName"),
        "marketingOptOut": base.get("marketingOptOut"),
        "nationality": base.get("nationality"),
        "occupation": base.get("occupation"),
        "password": base.get("password"),
        "phone": base.get("phone"),
        "placeOfBirth": base.get("placeOfBirth"),
        "secondaryIdentityDocument": base.get("secondaryIdentityDocument"),
        "shippingAddress": base.get("shippingAddress"),
        "token": token,
        "residentialAddress": base.get("billingAddress"),
        "legalAgreements": base.get("legalAgreements") or {},
    }


def prepare_pre_create_member(flow: PayPalFlow, token: str, signup_url: str) -> None:
    flow._send_tealeaf_data(flow.session, signup_url)  # noqa: SLF001
    flow._send_idapps_get_otp_challenge(token, signup_url)  # noqa: SLF001
    flow._confirm_phone_with_retry(token, signup_url)  # noqa: SLF001

    fields = ["email", "phone", "password", "firstName", "lastName", "billingLine1", "billingCity", "billingPostalCode", "billingState"]
    country_profile = get_country_profile(flow.address.country)
    if country_profile.card_dob_required or "DateOfBirth" in country_profile.kyc_fields:
        fields.append("dateOfBirth")
    flow._send_tealeaf_form_interaction_batch(signup_url, fields)  # noqa: SLF001
    flow._send_datadog_rum_action(flow.session, "create_member_no_fi_form_fill", signup_url)  # noqa: SLF001

    flow._ensure_live_signup_content_manifest(referer=signup_url)  # noqa: SLF001
    if flow._content_metadata_is_unresolved():  # noqa: SLF001
        flow._refresh_signup_content_metadata(referer=signup_url)  # noqa: SLF001
    if flow._content_metadata_is_unresolved() and flow.state.content_hash:  # noqa: SLF001
        flow.state.content_identifier = flow._resolved_content_identifier()  # noqa: SLF001
    if flow._content_metadata_is_unresolved():  # noqa: SLF001
        flow._apply_configured_or_cached_signup_content_metadata()  # noqa: SLF001

    if not getattr(flow, "_signup_billing_address_prepared", False):
        flow._send_address_autocomplete(token)  # noqa: SLF001
        flow._signup_billing_address_prepared = True  # noqa: SLF001

    risk_mode = flow._signup_context_risk_mode()  # noqa: SLF001
    if risk_mode == "headless":
        flow._send_signup_context_risk_signals_with_headless(signup_url, token)  # noqa: SLF001
    elif risk_mode in {"roxy", "auto"} or flow._roxy_risk_runtime_active():  # noqa: SLF001
        sent = flow._send_signup_context_risk_signals_with_roxy(signup_url, token)  # noqa: SLF001
        if not sent and flow._signup_context_risk_mode() == "headless":  # noqa: SLF001
            flow._send_signup_context_risk_signals_with_headless(signup_url, token)  # noqa: SLF001
    flow._strict_signup_preflight_or_raise()  # noqa: SLF001

    send_weasley_log(
        flow.session,
        flow.state.ec_token,
        signup_url,
        ["weasley_create_member_no_fi_submit", "weasley_api_request_create_member_account_mutation"],
        country=flow.address.country,
        lang=get_country_profile(flow.address.country).content_language,
    )


def consume_create_member(flow: PayPalFlow, result: Any) -> dict[str, Any]:
    obj = result[0] if isinstance(result, list) and result else result
    if not isinstance(obj, dict):
        return {"ok": False, "reason": "non_object"}
    onboard = ((obj.get("data") or {}).get("onboardAccount") or {}) if isinstance(obj.get("data"), dict) else {}
    if isinstance(onboard, dict) and onboard:
        buyer = onboard.get("buyer") or {}
        auth = buyer.get("auth") or {}
        flow.state.user_id = str(buyer.get("userId") or "")
        flow.state.euat_token = str(auth.get("accessToken") or flow.state.euat_token or "")
        flow.state.instrument_id = ""
        return {"ok": bool(flow.state.euat_token), "user_id_present": bool(flow.state.user_id), "euat_present": bool(flow.state.euat_token)}
    return {"ok": False, "errors": graphql_errors(result)}


def approve_variants(flow: PayPalFlow, token: str) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    # Variant A: approveGuestSignUpPayment with attemptSetStickyFi skipped.
    try:
        res = flow.session.graphql(
            "ApproveOnboardPaymentMutation",
            APPROVE_ONBOARD_PAYMENT_MUTATION,
            {"token": token, "instrumentId": None, "isBillingAgreement": False, "supportedThreeDsExperiences": ["IFRAME"]},
        )
        variants.append({"name": "approveGuestSignUpPayment_skipSticky", "result": sanitize_for_log(res), "errors": sanitize_for_log(graphql_errors(res))})
    except Exception as exc:
        variants.append({"name": "approveGuestSignUpPayment_skipSticky", "exception": str(exc)[:500]})

    # Variant B: approveMemberPayment without primary FI. This tests whether BA no-backup flag relaxes FI.
    try:
        res = flow.session.graphql(
            "ApproveMemberPaymentMutation",
            APPROVE_MEMBER_PAYMENT_MUTATION,
            {"token": token, "primaryFundingOptionId": None, "setStickyFiRequired": False, "preAuthorizationRequired": False, "supportedThreeDsExperiences": ["IFRAME"]},
        )
        variants.append({"name": "approveMemberPayment_noPrimaryFI", "result": sanitize_for_log(res), "errors": sanitize_for_log(graphql_errors(res))})
    except Exception as exc:
        variants.append({"name": "approveMemberPayment_noPrimaryFI", "exception": str(exc)[:500]})
    return variants


def extract_success(variants: list[dict[str, Any]]) -> dict[str, Any]:
    for v in variants:
        res = v.get("result")
        if not isinstance(res, dict):
            continue
        data = res.get("data") if isinstance(res.get("data"), dict) else {}
        for key in ("approveGuestSignUpPayment", "approveMemberPayment"):
            sess = data.get(key) if isinstance(data, dict) else None
            if not isinstance(sess, dict):
                continue
            state = str(sess.get("state") or "")
            cpi = sess.get("completedPaymentInfo") if isinstance(sess.get("completedPaymentInfo"), dict) else {}
            tx_state = str(cpi.get("transactionState") or "") if isinstance(cpi, dict) else ""
            return_url = (((sess.get("cart") or {}).get("returnUrl") or {}).get("href") if isinstance(sess.get("cart"), dict) else "") or ""
            if state == "APPROVED" or tx_state in {"COMPLETED", "APPROVED"} or return_url:
                return {"success": True, "variant": v.get("name"), "state": state, "transactionState": tx_state, "returnUrl_present": bool(return_url)}
    return {"success": False}


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))
    ba = load_ba_token()
    phone = os.getenv("PAYPAL_TEST_PHONE", "+18352891555")
    sms_url = os.getenv("SMSCC_RECORD_URL", "")
    if not sms_url:
        raise SystemExit("SMSCC_RECORD_URL is required for non-interactive live probe")

    for k, v in {
        "PAYPAL_FINGERPRINT_SOURCE": os.getenv("PAYPAL_FINGERPRINT_SOURCE", "headless"),
        "PAYPAL_DATADOME_MODE": os.getenv("PAYPAL_DATADOME_MODE", "headless"),
        "PAYPAL_MTR_RUNTIME": os.getenv("PAYPAL_MTR_RUNTIME", "headless"),
        "PAYPAL_RISK_SIGNALS_MODE": os.getenv("PAYPAL_RISK_SIGNALS_MODE", "headless"),
    }.items():
        os.environ[k] = v

    proxy_raw = os.getenv("PROXY", "").strip()
    proxy_config = build_proxy_config(enabled=bool(proxy_raw), proxy_url=proxy_raw)
    flow = PayPalFlow(
        ba_token=ba,
        user=generate_user(phone, country="US"),
        card=generate_card(proxy_url=proxy_config.url, country="US"),
        address=generate_address(proxy_url=proxy_config.url, country="US"),
        proxy_config=proxy_config,
        fingerprint_source=os.environ["PAYPAL_FINGERPRINT_SOURCE"],
        datadome_mode=os.environ["PAYPAL_DATADOME_MODE"],
        mtr_runtime=os.environ["PAYPAL_MTR_RUNTIME"],
        risk_signals_mode=os.environ["PAYPAL_RISK_SIGNALS_MODE"],
        sms_provider=FixedSmsccProvider(phone, sms_url),
    )
    out: dict[str, Any] = {"stage": "live_create_member_no_fi_v8", "ba_present": True, "proxy": proxy_config.label}
    try:
        logger.info("v8 live probe BA={} phone={} proxy={}", redacted_token(ba), flow._masked_phone(), proxy_config.label)  # noqa: SLF001
        flow._phase0_initial_load()  # noqa: SLF001
        flow._phase2_create_account()  # noqa: SLF001
        token = flow.state.ec_token or flow.ba_token
        signup_url = flow.state.signup_url or "https://www.paypal.com/checkoutweb/signup"
        out["phase0_2"] = {"ec_present": bool(flow.state.ec_token), "signup_url_present": bool(flow.state.signup_url)}
        prepare_pre_create_member(flow, token, signup_url)
        variables = build_create_member_variables(flow, token)
        create_res = flow._graphql_with_authchallenge_frontend_retry(  # noqa: SLF001
            "CreateMemberAccountMutation",
            CREATE_MEMBER_ACCOUNT_MUTATION,
            variables,
            signup_url,
            extra_body={"fn_sync_data": build_signup_fn_sync_data(token, session=flow.session)},
        )
        out["createMemberAccount"] = {"result": sanitize_for_log(create_res), "consume": consume_create_member(flow, create_res)}
        if flow.state.euat_token:
            flow._ensure_euat_cookie()  # noqa: SLF001
        send_analytics_ts(flow.session, "main:billing:hagrid:billingwithoutpurchase:member:review", flow.ba_token, ec_token=flow.state.ec_token, user_id=flow.state.user_id)
        variants = approve_variants(flow, token)
        out["approve_variants"] = variants
        out["terminal"] = extract_success(variants)
    except Exception as exc:
        out["exception"] = str(exc)[:1200]
    finally:
        try:
            flow.close()
        except Exception:
            pass
    print(json.dumps(sanitize_for_log(out), ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("terminal", {}).get("success") else 2)

if __name__ == "__main__":
    main()
