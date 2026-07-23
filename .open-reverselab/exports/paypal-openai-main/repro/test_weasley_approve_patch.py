#!/usr/bin/env python3
"""Offline verification for the Weasley ApproveOnboardPayment protocol patch.

No PayPal network calls and no real tokens are used.  This verifies the local
control-flow expected after a successful SignUpNewMember response:

1. extract fundingInstrument.id from both BILLING_WITHOUT_PURCHASE and purchase
   funding option shapes;
2. call ApproveOnboardPaymentMutation with token/instrumentId;
3. parse buyer, returnUrl and completedPaymentInfo from the response.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path('/tmp/openai-paypal-main-us-work')
sys.path.insert(0, str(ROOT))

from paypal.flow import PayPalFlow  # type: ignore
from paypal.models import BillingAddress, CardInfo, UserInfo  # type: ignore
from paypal.graphql import APPROVE_ONBOARD_PAYMENT_MUTATION  # type: ignore


class FakeResponse:
    status_code = 200
    text = 'OK'
    content = b'OK'
    url = 'https://merchant.example/return?status=success'
    headers = {}


class FakeSession:
    def __init__(self):
        self.calls = []

    def graphql(self, operation_name, query, variables, **kwargs):
        self.calls.append({
            'operation_name': operation_name,
            'query_contains_attemptSetStickyFi': 'attemptSetStickyFi' in query,
            'query_contains_approveGuestSignUpPayment': 'approveGuestSignUpPayment' in query,
            'variables': variables,
            'kwargs': kwargs,
        })
        assert operation_name == 'ApproveOnboardPaymentMutation'
        assert query == APPROVE_ONBOARD_PAYMENT_MUTATION
        assert variables['token'] == 'EC-LOCALDRYRUN0000000'
        assert variables['instrumentId'] == 'FI-BILLING-WITHOUT-PURCHASE'
        assert variables['isBillingAgreement'] is True
        return {
            'data': {
                'attemptSetStickyFi': {'buyer': {'userId': 'BUYER123'}},
                'approveGuestSignUpPayment': {
                    'buyer': {'userId': 'BUYER123'},
                    'cart': {
                        'returnUrl': {'href': 'https://merchant.example/return?status=success&token=EC-LOCALDRYRUN0000000'},
                    },
                    'completedPaymentInfo': {'transactionState': 'COMPLETED', 'transactionId': 'TXN-LOCAL'},
                    'fundingOptions': [
                        {'fundingInstrument': {'id': 'FI-BILLING-WITHOUT-PURCHASE', 'lastDigits': '1111'}}
                    ],
                },
            }
        }

    def get(self, url, headers=None):
        self.calls.append({'method': 'GET', 'url': url, 'headers': headers or {}})
        return FakeResponse()


def make_flow():
    user = UserInfo('John', 'Doe', 'dryrun@example.invalid', '+18352891555', '8352891555', '+1', 'Xx_Test_12345', '01/01/1990', '')
    card = CardInfo('4111111111111111', '12/2030', '123', 'CREDIT')
    addr = BillingAddress('1201 N Market Street', '', '', 'Wilmington', 'DE', '19801', 'US')
    flow = PayPalFlow('BA-LOCALDRYRUN0000000', user, card, addr, fingerprint_source='random', datadome_mode='off', mtr_runtime='off', risk_signals_mode='off')
    flow.state.ec_token = 'EC-LOCALDRYRUN0000000'
    flow.state.signup_url = 'https://www.paypal.com/checkoutweb/signup?token=EC-LOCALDRYRUN0000000&country.x=US&locale.x=en_US'
    flow.state.euat_token = 'EUAT-LOCALDRYRUN'
    flow.state.instrument_id = 'FI-BILLING-WITHOUT-PURCHASE'
    flow.session = FakeSession()
    return flow


def main():
    billing_without_purchase = {
        'fundingOptions': [
            {'fundingInstrument': {'id': 'FI-BILLING-WITHOUT-PURCHASE'}}
        ]
    }
    purchase_shape = {
        'fundingOptions': [
            {'allPlans': [{'fundingSources': [{'fundingInstrument': {'id': 'FI-PURCHASE-SOURCE'}}]}]}
        ]
    }
    checks = {
        'approve_mutation_has_attemptSetStickyFi': 'attemptSetStickyFi' in APPROVE_ONBOARD_PAYMENT_MUTATION,
        'approve_mutation_has_approveGuestSignUpPayment': 'approveGuestSignUpPayment' in APPROVE_ONBOARD_PAYMENT_MUTATION,
        'extract_billing_without_purchase': PayPalFlow._find_funding_instrument_id(billing_without_purchase) == 'FI-BILLING-WITHOUT-PURCHASE',
        'extract_purchase_shape': PayPalFlow._find_funding_instrument_id(purchase_shape) == 'FI-PURCHASE-SOURCE',
    }
    flow = make_flow()
    result = flow._phase4_weasley_approve()
    checks.update({
        'phase4_status_success': result.get('status') == 'success',
        'phase4_return_url_has_ba_token': 'ba_token=BA-LOCALDRYRUN0000000' in result.get('return_url', ''),
        'phase4_completed_payment_info': bool(result.get('completed_payment_info_present')),
        'phase4_graphql_called': bool(flow.session.calls and flow.session.calls[0]['operation_name'] == 'ApproveOnboardPaymentMutation'),
    })
    print(json.dumps({'ok': all(checks.values()), 'checks': checks, 'result': {k: v for k, v in result.items() if k != 'raw_response'}}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
