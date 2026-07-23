#!/usr/bin/env python3
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
SOURCE=Path('/Users/mac/Downloads/openai-paypal-main')
PATCH=Path('/Users/mac/code/my/AutoTeam-F/.open-reverselab/patches/openai-paypal-main-us-runner-schema-weasley-member-v5-draft.diff')
PYTHON=Path('/Users/mac/Downloads/openai-paypal-main/.venv/bin/python')
if not PYTHON.exists(): PYTHON=Path(sys.executable)
with tempfile.TemporaryDirectory(prefix='paypal-v5-member-') as td:
    dst=Path(td)/'work'
    shutil.copytree(SOURCE,dst,ignore=shutil.ignore_patterns('.venv','__pycache__','.git','captures','debug'))
    subprocess.run(['patch','-p1','-i',str(PATCH)],cwd=dst,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    subprocess.run([str(PYTHON),'-m','py_compile','main.py','web.py','paypal/models.py','paypal/flow.py','paypal/session.py','paypal/graphql.py','paypal/country_profile.py'],cwd=dst,check=True)
    probe=r'''
import json
from paypal.models import generate_user, generate_address, generate_card
from paypal.flow import PayPalFlow
from paypal.proxy import ProxyConfig
from paypal.graphql import APPROVE_MEMBER_PAYMENT_MUTATION
class DummySession:
    def __init__(self): self.calls=[]
    def graphql(self, operation_name, query, variables, **kwargs):
        self.calls.append({'operation_name':operation_name,'query':query,'variables':variables,'kwargs':kwargs})
        return {'data': {'approveMemberPayment': {
            'state':'APPROVED',
            'buyer': {'userId':'BUYER-MEMBER-1'},
            'cart': {'returnUrl': {'href':'https://merchant.example/return?token=EC-LOCALDRYRUN0000000'}, 'cancelUrl': {'href':'https://merchant.example/cancel'}},
            'completedPaymentInfo': {'transactionState':'COMPLETED','transactionId':'TXN-MEMBER-LOCAL'},
            'fundingOptions': [{'fundingInstrument': {'id':'FI-MEMBER-123','lastDigits':'1111','type':'CARD'}}],
            'paymentContingencies': {},
        }}}
    def get(self, url, headers=None):
        class R:
            status_code=200; content=b''; text=''; url='https://merchant.example/return?done=1'
        return R()
user=generate_user('+18352891555', country='US'); addr=generate_address(country='US'); card=generate_card(country='US')
flow=PayPalFlow('BA-LOCALDRYRUN0000000', user, card, addr, proxy_config=ProxyConfig(False), fingerprint_source='random', datadome_mode='off', mtr_runtime='off', risk_signals_mode='off')
flow.session=DummySession(); flow.state.ec_token='EC-LOCALDRYRUN0000000'; flow.state.signup_url='https://www.paypal.com/checkoutweb/signup'
result=flow._phase4_member_approve_existing_buyer('FI-MEMBER-123')
call=flow.session.calls[-1]
checks={
 'mutation_exported': 'approveMemberPayment' in APPROVE_MEMBER_PAYMENT_MUTATION,
 'operation_name': call['operation_name']=='ApproveMemberPaymentMutation',
 'variables_token': call['variables'].get('token')=='EC-LOCALDRYRUN0000000',
 'variables_fi': call['variables'].get('primaryFundingOptionId')=='FI-MEMBER-123',
 'no_signup_mutation': 'signUpNewMember' not in call['query'],
 'status_success': result.get('status')=='success',
 'completed': result.get('completed_payment_info',{}).get('transactionState')=='COMPLETED',
 'return_followed': result.get('final_redirect_url')=='https://merchant.example/return?done=1',
 'buyer_set': flow.state.user_id=='BUYER-MEMBER-1',
 'instrument_set': flow.state.instrument_id=='FI-MEMBER-123',
}
print(json.dumps({'ok':all(checks.values()),'stage':'member_approve_v5_patch','checks':checks,'result':{k:result.get(k) for k in ['status','final_redirect_url','buyer_user_id','funding_instrument_present','completed_payment_info_present']}},ensure_ascii=False,indent=2))
'''
    r=subprocess.run([str(PYTHON),'-c',probe],cwd=dst,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    out=r.stdout; start=out.find('{')
    print(json.dumps(json.loads(out[start:]),ensure_ascii=False,indent=2))
