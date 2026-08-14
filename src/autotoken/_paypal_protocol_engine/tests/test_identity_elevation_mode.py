import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paypal.elevation_flow import IdentityElevationPayPalFlow
from paypal.flow import PayPalFlow
from paypal.models import SessionState


class FakeSession:
    def __init__(self, checkout_type="BILLING_WITHOUT_PURCHASE"):
        self.checkout_type = checkout_type
        self.calls = []

    def graphql(self, operation_name, query, variables, **kwargs):
        self.calls.append((operation_name, variables, kwargs))
        return {
            "data": {
                "checkoutSession": {
                    "checkoutSessionType": self.checkout_type,
                }
            }
        }

    def set_euat_token(self, token):
        self.euat_token = token

    def get(self, url, **kwargs):
        self.calls.append(("GET", {"url": url}, kwargs))
        return SimpleNamespace(status_code=200, text="", content=b"", headers={}, url=url)


class IdentityElevationModeTests(unittest.TestCase):
    def test_checkout_context_accepts_billing_without_purchase(self):
        checkout = IdentityElevationPayPalFlow._require_checkout_session({
            "data": {
                "checkoutSession": {
                    "checkoutSessionType": "BILLING_WITHOUT_PURCHASE",
                }
            }
        })
        self.assertEqual(checkout["checkoutSessionType"], "BILLING_WITHOUT_PURCHASE")

    def test_checkout_context_rejects_other_type(self):
        with self.assertRaisesRegex(RuntimeError, "TYPE_MISMATCH"):
            IdentityElevationPayPalFlow._require_checkout_session({
                "data": {"checkoutSession": {"checkoutSessionType": "ONE_TIME_PURCHASE"}}
            })

    def test_protocol_elevation_requires_ec(self):
        flow = IdentityElevationPayPalFlow.__new__(IdentityElevationPayPalFlow)
        flow.ba_token = "BA-2FL838928F860610F"
        flow.locale = "th_TH"
        flow.address = SimpleNamespace(country="TH")
        flow.state = SessionState(
            ba_token="BA-2FL838928F860610F",
            euat_token="EUAT",
            signup_context_ready=True,
            signup_url="https://www.paypal.com/checkoutweb/signup",
        )
        flow.session = FakeSession()
        flow._load_review_context = lambda url, referer: None
        flow._query_elevated_context = lambda token, referer: {
            "buyer_ready": True,
            "token": token,
            "referer": referer,
            "funding_selected": True,
            "funding_available": True,
            "funding_available_count": 1,
            "funding_errors": [],
            "fatal_contingency": "",
        }
        result = flow._protocol_identity_elevation()
        self.assertTrue(result["buyer_ready"])
        self.assertEqual(result["token"], "BA-2FL838928F860610F")

    def test_protocol_elevation_requires_validated_signup_context(self):
        flow = IdentityElevationPayPalFlow.__new__(IdentityElevationPayPalFlow)
        flow.state = SessionState(
            ec_token="EC-ABC123456789",
            euat_token="EUAT",
            signup_context_ready=False,
        )
        with self.assertRaisesRegex(RuntimeError, "SIGNUP_CONTEXT_NOT_READY"):
            flow._protocol_identity_elevation()

    def test_phase2_accepts_ba_checkout_context_when_ec_is_missing(self):
        flow = IdentityElevationPayPalFlow.__new__(IdentityElevationPayPalFlow)
        flow.ba_token = "BA-2FL838928F860610F"
        flow.lang = "th"
        flow.address = SimpleNamespace(country="TH")
        flow.state = SessionState(
            ba_token="BA-2FL838928F860610F",
            signup_url="https://www.paypal.com/checkoutweb/signup",
            content_identifier="TH:th:compliance.signupTerms",
        )
        flow.session = FakeSession()
        with patch.object(PayPalFlow, "_phase2_create_account", lambda self: None):
            flow._phase2_create_account()
        self.assertTrue(flow.state.signup_context_ready)
        self.assertEqual(flow.session.calls[-1][1]["token"], "BA-2FL838928F860610F")


if __name__ == "__main__":
    unittest.main()
