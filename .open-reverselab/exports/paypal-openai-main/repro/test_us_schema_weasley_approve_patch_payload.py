#!/usr/bin/env python3
from __future__ import annotations
import json, shutil, subprocess, sys
from pathlib import Path

SRC=Path('/Users/mac/Downloads/openai-paypal-main')
PATCH=Path('/Users/mac/code/my/AutoTeam-F/.open-reverselab/patches/openai-paypal-main-us-schema-weasley-approve-applyable.diff')
WORK=Path('/tmp/openai-paypal-main-us-weasley-acceptance')
PYTHON=SRC/'.venv/bin/python'

def copy_clean():
    if WORK.exists(): shutil.rmtree(WORK)
    def ignore(_dir, names):
        return {n for n in names if n in {'.venv','__pycache__','.git','var','cache','.DS_Store'}}
    shutil.copytree(SRC, WORK, ignore=ignore)

def run(cmd, **kw):
    return subprocess.run(cmd, cwd=kw.pop('cwd', WORK), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)

def main():
    copy_clean()
    r=run(['patch','-p1','--batch','--forward','-i',str(PATCH)])
    if r.returncode not in (0,1):
        print(json.dumps({'ok':False,'stage':'patch','returncode':r.returncode,'output':r.stdout[-3000:]}, indent=2)); return 1
    r=run([str(PYTHON),'-m','py_compile','paypal/country_profile.py','paypal/models.py','paypal/graphql.py','paypal/flow.py','paypal/session.py'])
    if r.returncode != 0:
        print(json.dumps({'ok':False,'stage':'compile','output':r.stdout[-5000:]}, indent=2)); return 1
    probe=WORK/'_probe_us_weasley.py'
    probe.write_text('''
import json
from paypal.models import UserInfo, CardInfo, BillingAddress
from paypal.flow import PayPalFlow
from paypal.graphql import APPROVE_ONBOARD_PAYMENT_MUTATION
user=UserInfo('John','Doe','local-us-schema@example.invalid','+18352891555','8352891555','+1','Passw0rd!LocalOnly','01/01/1990','')
card=CardInfo('4111111111111111','12/2030','123','CREDIT')
addr=BillingAddress('1201 N Market Street','','','Wilmington','DE','19801','US')
flow=PayPalFlow('BA-LOCALDRYRUN0000000', user, card, addr, proxy_enabled=False, fingerprint_source='random', datadome_mode='off', mtr_runtime='off', risk_signals_mode='off')
flow.state.content_hash='d24460aee36e4b7d4579aea096ec5056'
flow.state.content_identifier='US:en:d24460aee36e4b7d4579aea096ec5056:compliance.signupTerms'
v=flow._build_signup_variables('EC-LOCALDRYRUN0000000')
billing_shape={'fundingOptions':[{'fundingInstrument':{'id':'FI-BILLING-WITHOUT-PURCHASE'}}]}
purchase_shape={'fundingOptions':[{'allPlans':[{'fundingSources':[{'fundingInstrument':{'id':'FI-PURCHASE'}}]}]}]}
print(json.dumps({
 'profile_country':flow._profile_country(),
 'profile_locale':flow._profile_locale(),
 'profile_lang':flow._profile_lang(),
 'signup_url':flow._build_signup_url(),
 'has_identityDocument':'identityDocument' in v,
 'has_dateOfBirth':'dateOfBirth' in v,
 'has_card_productClass':'productClass' in v.get('card',{}),
 'billing_line1':(v.get('billingAddress') or {}).get('line1'),
 'phone':v.get('phone'),
 'approve_mutation_has_attemptSetStickyFi':'attemptSetStickyFi' in APPROVE_ONBOARD_PAYMENT_MUTATION,
 'approve_mutation_has_approveGuestSignUpPayment':'approveGuestSignUpPayment' in APPROVE_ONBOARD_PAYMENT_MUTATION,
 'extract_billing_without_purchase':PayPalFlow._find_funding_instrument_id(billing_shape),
 'extract_purchase_shape':PayPalFlow._find_funding_instrument_id(purchase_shape),
}, indent=2))
''')
    r=run([str(PYTHON),str(probe)])
    if r.returncode != 0:
        print(json.dumps({'ok':False,'stage':'probe','output':r.stdout[-5000:]}, indent=2)); return 1
    text=r.stdout; data=json.loads(text[text.find('{'):])
    checks={
      'country_us': data['profile_country']=='US',
      'locale_us': data['profile_locale']=='en_US',
      'lang_us': data['profile_lang']=='en-US',
      'url_us': 'country.x=US' in data['signup_url'] and 'locale.x=en_US' in data['signup_url'],
      'no_identityDocument': data['has_identityDocument'] is False,
      'no_dateOfBirth': data['has_dateOfBirth'] is False,
      'no_productClass': data['has_card_productClass'] is False,
      'line1_no_tail_comma': data['billing_line1']=='1201 N Market Street',
      'phone_us': data['phone']=={'countryCode':'1','number':'8352891555','type':'MOBILE'},
      'approve_mutation_has_attemptSetStickyFi': data['approve_mutation_has_attemptSetStickyFi'] is True,
      'approve_mutation_has_approveGuestSignUpPayment': data['approve_mutation_has_approveGuestSignUpPayment'] is True,
      'extract_billing_without_purchase': data['extract_billing_without_purchase']=='FI-BILLING-WITHOUT-PURCHASE',
      'extract_purchase_shape': data['extract_purchase_shape']=='FI-PURCHASE',
    }
    ok=all(checks.values())
    print(json.dumps({'ok':ok,'stage':'us_schema_weasley_approve_patch','checks':checks,'probe':data}, ensure_ascii=False, indent=2))
    return 0 if ok else 1

if __name__ == '__main__':
    raise SystemExit(main())
