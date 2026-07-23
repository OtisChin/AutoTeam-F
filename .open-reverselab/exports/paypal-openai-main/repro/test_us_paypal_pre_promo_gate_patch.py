#!/usr/bin/env python3
"""Offline reproducer for us_paypal pre-promo PayPal funding gate.

No network: all HTTP/Stripe/ChatGPT functions are monkeypatched.
"""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path

SRC_ROOT = Path('/Users/mac/code/my/AutoTeam-F/src')
US_PAYPAL = SRC_ROOT / 'autotoken/payments/us_paypal.py'
sys.path.insert(0, str(SRC_ROOT))

import autotoken.payments.us_paypal as current

class DummyProxyCtx:
    url = ''
    def __enter__(self): return self
    def __exit__(self, *args): return False

class DummyResp:
    status_code = 200
    text = '{"checkout_session_id":"cs_test_local","publishable_key":"pk_test_local","processor_entity":"openai_llc"}'
    def json(self):
        return {"checkout_session_id":"cs_test_local","publishable_key":"pk_test_local","processor_entity":"openai_llc"}

class DummyChatGPTSession:
    def post(self, *args, **kwargs): return DummyResp()

def install_stubs(mod, events):
    mod.build_paypal_dynamic_proxy = lambda cfg, stage_index, region=None: ('', f'sid-{stage_index}-{region or cfg.region}')
    mod.pix_proxy_context = lambda local_proxy, dynamic_proxy, log=None: DummyProxyCtx()
    mod.build_chatgpt_session = lambda access_token, proxy_url='', device_id='': DummyChatGPTSession()
    mod.build_stripe_session = lambda proxy_url='': object()
    calls = {'stripe_init': 0, 'promo': 0}
    def fake_stripe_init(stripe, cs_id, stripe_pk, ctx):
        calls['stripe_init'] += 1
        if calls['stripe_init'] == 1:
            return {
                'amount_total': 2000,
                'payment_method_types': ['card'],
                'ordered_payment_method_types': ['card','apple_pay','google_pay'],
                'stripe_hosted_url': 'https://checkout.stripe.test/c/pay/cs_test_local',
            }
        return {
            'amount_total': 0,
            'payment_method_types': ['card','paypal'],
            'ordered_payment_method_types': ['card','paypal','apple_pay','google_pay'],
            'stripe_hosted_url': 'https://checkout.stripe.test/c/pay/cs_test_local',
        }
    def fake_update(*args, **kwargs):
        calls['promo'] += 1
        events.append('promo_called')
        return {'success': True}
    def fake_express(*args, **kwargs):
        return {
            'paypal_link': 'https://www.paypal.com/agreements/approve?ba_token=BA-TESTLOCAL',
            'provider_redirect_url': 'https://www.paypal.com/agreements/approve?ba_token=BA-TESTLOCAL',
            'ba_token': 'BA-TESTLOCAL',
            'link_source': 'stripe_express_billing_agreement',
        }
    mod.stripe_init = fake_stripe_init
    mod.chatgpt_update_trial_promo = fake_update
    mod.create_express_billing_agreement = fake_express
    return calls

def run_current():
    events = []
    calls = install_stubs(current, events)
    cfg = current.PaypalJobConfig(access_token='token', direct_proxies=['direct'], region='US', promo_region='JP', apply_promo=True)
    try:
        current.generate_paypal_trial(cfg, log=lambda m: events.append(str(m)))
        return {'ok': False, 'unexpected_success': True, 'events': events, 'calls': calls}
    except Exception as exc:
        return {'ok': True, 'error': str(exc), 'events': events, 'calls': calls}

def load_patched():
    source = US_PAYPAL.read_text(encoding='utf-8')
    old = '        if not has_paypal:\n            raise RuntimeError(f"未出现 PayPal，pmt={pmt}")\n\n        if cfg.apply_promo:'
    new = '        if not has_paypal and not cfg.apply_promo:\n            raise RuntimeError(f"未出现 PayPal，pmt={pmt}")\n\n        if cfg.apply_promo:'
    if old not in source:
        raise RuntimeError('expected early PayPal gate snippet not found')
    source = source.replace(old, new, 1)
    spec = importlib.util.spec_from_loader('patched_us_paypal_local', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(US_PAYPAL)
    sys.modules[spec.name] = mod
    exec(compile(source, str(US_PAYPAL), 'exec'), mod.__dict__)
    return mod

def run_patched():
    mod = load_patched()
    events = []
    calls = install_stubs(mod, events)
    cfg = mod.PaypalJobConfig(access_token='token', direct_proxies=['direct'], region='US', promo_region='JP', apply_promo=True)
    res = mod.generate_paypal_trial(cfg, log=lambda m: events.append(str(m)))
    fields = res.get('fields') or {}
    return {'ok': bool(res.get('ok') and fields.get('ba_token')), 'events': events, 'calls': calls, 'fields': {k: fields.get(k) for k in ['link_source','ba_token','pre_promo_payment_method_types','post_promo_payment_method_types']}}

if __name__ == '__main__':
    out = {'current': run_current(), 'patched': run_patched()}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not (out['current']['ok'] and out['current']['calls']['promo'] == 0 and out['patched']['ok'] and out['patched']['calls']['promo'] == 1):
        raise SystemExit(1)
