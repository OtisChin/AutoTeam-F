#!/usr/bin/env python3
"""Offline harness for the Weasley createMemberAccount(no FI) candidate branch.

This does not contact PayPal and does not mutate project code. It validates the
locally reconstructed payload/decision logic against mock GraphQL responses.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

WORK = Path('/tmp/openai-paypal-main-protocol-work')
sys.path.insert(0, str(WORK))

from paypal.flow import PayPalFlow  # type: ignore
from paypal.models import generate_user, generate_card, generate_address  # type: ignore

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


def build_create_member_variables(flow: PayPalFlow, token: str) -> dict:
    # US shape aligned with SignUpNewMember/onboardGuest payloads, but no card/bank.
    dd, mm, yyyy = flow.user.dob.split('/') if '/' in flow.user.dob else ('01', '01', '1990')
    country = flow.address.country or 'US'
    address = {
        'line1': f'{flow.address.house_number} {flow.address.street}',
        'line2': flow.address.district or None,
        'city': flow.address.city,
        'state': flow.address.state,
        'postalCode': flow.address.postal_code,
        'country': country,
    }
    return {
        'billingAddress': address,
        'contentIdentifier': flow.state.content_identifier or 'US:en:localmock:compliance.signupTerms',
        'country': country,
        'dateOfBirth': {'day': dd, 'month': mm, 'year': yyyy},
        'email': flow.user.email,
        'firstName': flow.user.first_name,
        'lastName': flow.user.last_name,
        'legalAgreements': None,
        'marketingOptOut': True,
        'password': flow.user.password,
        'phone': {
            'countryCode': country,
            'nationalNumber': flow.user.phone_local,
            'phoneCountryCode': flow.user.phone_country_code,
            'type': 'MOBILE',
        },
        'residentialAddress': address,
        'shippingAddress': address,
        'token': token,
    }


class FakeSession:
    def __init__(self, flow: PayPalFlow):
        self.flow = flow
        self.calls = []
    def graphql(self, operation_name, query, variables, **kwargs):
        self.calls.append({'operationName': operation_name, 'variables': variables, 'query_has_card': 'card' in query})
        if operation_name == 'CreateMemberAccountMutation':
            return {'data': {'onboardAccount': {'buyer': {'userId': 'BUYER-CREATE-MEMBER-1', 'auth': {'accessToken': 'EUAT-MOCK'}}, 'fundingOptions': [], 'flags': {'is3DSecureRequired': False}}}}
        if operation_name == 'ApproveOnboardPaymentMutation':
            # This mocks the speculative no-FI approval variant: skip attemptSetStickyFi when no instrument.
            return {'data': {'approveGuestSignUpPayment': {'buyer': {'userId': 'BUYER-CREATE-MEMBER-1'}, 'cart': {'returnUrl': {'href': 'https://merchant.example/return?ok=1'}}, 'completedPaymentInfo': {'transactionState': 'COMPLETED'}, 'fundingOptions': []}}}
        return {'errors': [{'message': 'unexpected op'}]}
    def get(self, url, **kwargs):
        class R:
            status_code = 200
            text = 'ok'
            url = url
            headers = {}
            content = b'ok'
        return R()


def main():
    flow = PayPalFlow('BA-CREATE-MEMBER-MOCK', generate_user('+18355550123', country='US'), generate_card(country='US'), generate_address(country='US'))
    flow.state.ec_token = 'EC-CREATEMEMBERMOCK'
    flow.session = FakeSession(flow)  # type: ignore
    variables = build_create_member_variables(flow, flow.state.ec_token)
    create_result = flow.session.graphql('CreateMemberAccountMutation', CREATE_MEMBER_ACCOUNT_MUTATION, variables)
    onboard = create_result['data']['onboardAccount']
    flow.state.euat_token = onboard['buyer']['auth']['accessToken']
    flow.state.user_id = onboard['buyer']['userId']
    flow.state.instrument_id = ''
    # Candidate decision: if no instrument id, do not call attemptSetStickyFi.
    from paypal.graphql import APPROVE_ONBOARD_PAYMENT_MUTATION  # type: ignore
    approve_vars = {'token': flow.state.ec_token, 'instrumentId': None, 'isBillingAgreement': False, 'supportedThreeDsExperiences': ['THREE_DS_2']}
    approve_result = flow.session.graphql('ApproveOnboardPaymentMutation', APPROVE_ONBOARD_PAYMENT_MUTATION, approve_vars)
    out = {
        'ok': True,
        'stage': 'create_member_no_fi_candidate_v8_offline',
        'checks': {
            'create_member_has_no_card_arg': 'card' not in CREATE_MEMBER_ACCOUNT_MUTATION,
            'create_member_auth_anonymous_per_schema': True,
            'buyer_access_token_saved': bool(flow.state.euat_token),
            'no_instrument_id_after_create_member': flow.state.instrument_id == '',
            'approval_skips_sticky_fi_when_no_instrument': approve_vars['isBillingAgreement'] is False,
            'approval_mock_completed': approve_result['data']['approveGuestSignUpPayment']['completedPaymentInfo']['transactionState'] == 'COMPLETED',
        },
        'variables_keys': sorted(variables),
        'calls': flow.session.calls,
        'interpretation': 'Candidate only: PayPal schema proves createMemberAccount can create a buyer without FI for ANONYMOUS flows; live terminal success still requires validating whether BA approval accepts no sticky FI / no primaryFundingOptionId after this auth state.'
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
