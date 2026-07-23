#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path

WORK = Path('/tmp/openai-paypal-main-protocol-work')
sys.path.insert(0, str(WORK))

from paypal.flow import PayPalFlow  # type: ignore
from paypal.graphql import APPROVE_GUEST_PAYMENT_WITH_CREDIT_CARD_MUTATION  # type: ignore
from paypal.models import BillingAddress, CardInfo, SessionState, UserInfo  # type: ignore

class FakeResp:
    def __init__(self, url: str):
        self.url = url
        self.status_code = 200
        self.headers = {}
        self.text = 'ok'
        self.content = b'ok'

class FakeSession:
    def __init__(self, state: SessionState):
        self.state = state
        self.calls = []
        self.gets = []
    def graphql(self, operation_name, query, variables, **kwargs):
        self.calls.append({
            'operation_name': operation_name,
            'query': query,
            'variables': variables,
            'kwargs': kwargs,
        })
        assert operation_name == 'ApproveGuestPaymentWithCreditCardMutation'
        assert 'approveGuestPaymentWithCreditCard' in query
        assert variables['token'].startswith('EC-')
        assert variables['card']['cardNumber'] == '4111111111111111'
        assert variables['billingAddress']['country'] == 'US'
        return {
            'data': {
                'approveGuestPaymentWithCreditCard': {
                    'buyer': {'userId': 'BUYER-GUEST-1'},
                    'cart': {'returnUrl': {'href': 'https://merchant.example/return?status=success&token=EC-GUESTCARDLOCAL'}},
                    'completedPaymentInfo': {'transactionState': 'COMPLETED', 'transactionId': 'TXN-GUESTCARD-LOCAL'},
                    'fundingOptions': [{'fundingInstrument': {'id': 'FI-GUEST-CARD-1', 'lastDigits': '1111'}}],
                }
            }
        }
    def get(self, url, **kwargs):
        self.gets.append({'url': url, 'kwargs': kwargs})
        return FakeResp('https://merchant.example/return?status=success&redirect_pm_type=paypal')

state = SessionState(ba_token='BA-GUESTCARDLOCAL')
state.ec_token = 'EC-GUESTCARDLOCAL'
state.signup_url = 'https://www.paypal.com/checkoutweb/signup?token=EC-GUESTCARDLOCAL'
user = UserInfo('Jane', 'Miller', 'jane.miller@example.com', '+18352891555', '8352891555', '1', 'Aa123456789!', '01/01/1990', '')
card = CardInfo('4111111111111111', '12/2030', '123', 'CREDIT')
addr = BillingAddress('1 Market St', '', '', 'San Francisco', 'CA', '94105', 'US')
flow = object.__new__(PayPalFlow)
flow.ba_token = state.ba_token
flow.state = state
flow.user = user
flow.card = card
flow.address = addr
flow.session = FakeSession(state)

variables = flow._build_guest_card_approval_variables(state.ec_token)
result = flow._phase_guest_card_direct_approve()
checks = {
    'mutation_exported': bool(APPROVE_GUEST_PAYMENT_WITH_CREDIT_CARD_MUTATION and 'approveGuestPaymentWithCreditCard' in APPROVE_GUEST_PAYMENT_WITH_CREDIT_CARD_MUTATION),
    'variables_us': variables['billingAddress']['country'] == 'US',
    'variables_phone_string': variables['phoneNumber'] == '+18352891555',
    'status_success': result.get('status') == 'success',
    'completed': (result.get('completed_payment_info') or {}).get('transactionState') == 'COMPLETED',
    'return_followed': bool(flow.session.gets),
    'buyer_set': state.user_id == 'BUYER-GUEST-1',
    'instrument_set': state.instrument_id == 'FI-GUEST-CARD-1',
}
print(json.dumps({'ok': all(checks.values()), 'stage': 'guest_card_direct_v6_patch', 'checks': checks, 'variables_keys': sorted(variables.keys()), 'result': {k: v for k, v in result.items() if k != 'raw_response'}}, indent=2, ensure_ascii=False))
if not all(checks.values()):
    raise SystemExit(1)
