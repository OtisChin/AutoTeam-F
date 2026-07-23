#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
WORK=Path('/tmp/openai-paypal-main-protocol-work')
sys.path.insert(0,str(WORK))
from paypal.flow import PayPalFlow  # type: ignore
from paypal.graphql import ONBOARD_GUEST_MUTATION  # type: ignore
from paypal.models import BillingAddress, CardInfo, SessionState, UserInfo  # type: ignore

class FakeSession:
    def __init__(self): self.calls=[]
    def graphql(self, operation_name, query, variables, **kwargs):
        self.calls.append({'operation_name':operation_name,'query':query,'variables':variables,'kwargs':kwargs})
        assert operation_name == 'OnboardGuestMutation'
        assert 'onboardGuest' in query
        assert variables['country'] == 'US'
        assert variables['card']['cardNumber'] == '4111111111111111'
        return {'data': {'onboardAccount': {'buyer': {'userId':'BUYER-GUEST-ONBOARD-1','auth': {'accessToken':'EUAT-LOCAL'}}, 'fundingOptions': [{'fundingInstrument': {'id':'FI-ONBOARD-GUEST-1','lastDigits':'1111'}}]}}}
state=SessionState(ba_token='BA-ONBOARDGUESTLOCAL'); state.ec_token='EC-ONBOARDGUESTLOCAL'; state.signup_url='https://www.paypal.com/checkoutweb/signup?token=EC-ONBOARDGUESTLOCAL'
flow=object.__new__(PayPalFlow)
flow.ba_token=state.ba_token; flow.state=state
flow.user=UserInfo('Jane','Miller','jane.miller@example.com','+18352891555','8352891555','1','Aa123456789!','01/01/1990','')
flow.card=CardInfo('4111111111111111','12/2030','123','CREDIT')
flow.address=BillingAddress('1 Market St','','','San Francisco','CA','94105','US')
flow.session=FakeSession()
vars=flow._build_onboard_guest_variables(state.ec_token)
result=flow._phase_onboard_guest_probe()
checks={
 'mutation_exported': bool(ONBOARD_GUEST_MUTATION and 'onboardGuest' in ONBOARD_GUEST_MUTATION),
 'variables_us': vars['country']=='US' and vars['billingAddress']['country']=='US',
 'has_card': bool(vars['card']),
 'status_success': result.get('status')=='success',
 'buyer_set': state.user_id=='BUYER-GUEST-ONBOARD-1',
 'access_token_present': bool(state.euat_token),
 'instrument_set': state.instrument_id=='FI-ONBOARD-GUEST-1',
}
print(json.dumps({'ok':all(checks.values()),'stage':'onboard_guest_v7_patch','checks':checks,'variables_keys':sorted(vars.keys()),'result':{k:v for k,v in result.items() if k!='raw_response'}},ensure_ascii=False,indent=2))
if not all(checks.values()): raise SystemExit(1)
