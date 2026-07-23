#!/usr/bin/env python3
import json, sys
from pathlib import Path
WORK=Path('/tmp/openai-paypal-main-protocol-work')
sys.path.insert(0,str(WORK))
from paypal.flow import PayPalFlow
from paypal.models import generate_user, generate_card, generate_address
from paypal.proxy import build_proxy_config

class MockSession:
    def __init__(self):
        self.calls=[]
        self.client=type('C',(),{'cookies':type('K',(),{'set':lambda *a,**k:None})()})()
    def graphql(self, operation, query, variables, **kwargs):
        self.calls.append({'operation':operation,'variables':variables,'query':query})
        if operation=='CreateMemberAccountMutation':
            return {'data':{'onboardAccount':{'buyer':{'userId':'BUYER-NOFI-1','auth':{'accessToken':'EUAT-MOCK','__typename':'Auth'},'__typename':'User'},'__typename':'CheckoutSession'}}}
        if operation=='ApproveMemberPaymentMutation':
            return {'data':{'approveMemberPayment':{'state':'APPROVED','buyer':{'userId':'BUYER-NOFI-1','__typename':'User'},'cart':{'returnUrl':{'href':'https://merchant.example/return?status=success&token=EC-MOCK&ba_token=BA-MOCK','pathname':'/return','__typename':'GenericURL'},'cancelUrl':{'href':'https://merchant.example/cancel','pathname':'/cancel','__typename':'GenericURL'},'__typename':'Cart'},'completedPaymentInfo':None,'__typename':'CheckoutSession'}}}
        raise AssertionError(operation)
    def get(self, url, **kwargs):
        self.calls.append({'operation':'GET','url':url})
        return type('R',(),{'status_code':200,'url':'https://merchant.example/final?redirect_status=succeeded','headers':{},'content':b'ok','text':'ok'})()

flow=PayPalFlow('BA-MOCK', generate_user('+18355550123', country='US'), generate_card(country='US'), generate_address(country='US'), proxy_config=build_proxy_config(enabled=False), fingerprint_source='random', datadome_mode='off', mtr_runtime='off', risk_signals_mode='off')
flow.session=MockSession()
flow.state.ec_token='EC-MOCK'; flow.state.signup_url='https://www.paypal.com/checkoutweb/signup?token=EC-MOCK'; flow.state.content_identifier='US:en:mock:compliance.signupTerms'
flow._phase3_create_member_no_fi('EC-MOCK', flow.state.signup_url)
phase4=flow._phase4_member_approve_no_primary_fi()
create_call=flow.session.calls[0]
approve_call=[c for c in flow.session.calls if c.get('operation')=='ApproveMemberPaymentMutation'][0]
out={'ok': True, 'checks': {
 'no_fi_enabled_us_auto': flow._create_member_no_fi_enabled() is True,
 'create_query_has_no_card': 'card:' not in create_call['query'] and '$card' not in create_call['query'],
 'create_saved_euat': flow.state.euat_token=='EUAT-MOCK',
 'create_no_instrument': flow.state.instrument_id=='',
 'approve_primary_fi_null': approve_call['variables'].get('primaryFundingOptionId') is None,
 'approve_state_success': phase4.get('status')=='success' and phase4.get('state')=='APPROVED',
 'return_followed': bool(phase4.get('final_redirect_url')),
}, 'phase4': {k:v for k,v in phase4.items() if k not in {'raw_response','return_url','final_redirect_url'}}}
out['ok']=all(out['checks'].values())
print(json.dumps(out,ensure_ascii=False,indent=2))
sys.exit(0 if out['ok'] else 1)
