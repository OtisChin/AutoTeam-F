#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from types import MethodType
from pathlib import Path

ROOT = Path('/Users/mac/Downloads/openai-paypal-main')
sys.path.insert(0, str(ROOT))
os.environ['PAYPAL_ROXY_SIGNUP_CONTEXT_SUBPROCESS'] = 'auto'
os.environ['PAYPAL_RISK_SIGNALS_MODE'] = 'roxy'

from paypal.flow import PayPalFlow
from paypal.models import BillingAddress, CardInfo, UserInfo

user = UserInfo('John', 'Doe', 'john.doe.test@example.com', '+18352891555', '8352891555', '1', 'Aa123456789!', '01/01/1990', '')
card = CardInfo('4111111111111111', '12/2030', '123')
addr = BillingAddress('1 Market St', '', '', 'San Francisco', 'CA', '94105', 'US')
flow = PayPalFlow('BA-TESTSUBPROCESS123', user, card, addr, risk_signals_mode='roxy', fingerprint_source='random')

called = {'subprocess': 0}

def fail_sync_loop(self):
    raise RuntimeError('It looks like you are using Playwright Sync API inside the asyncio loop. Please use the Async API instead.')

def fake_subprocess(self, signup_url, token, *, seeded_signup_html='', seeded_signup_status=200):
    called['subprocess'] += 1
    return {
        'ok': True,
        'status': 200,
        'url': signup_url,
        'reason': 'ok',
        'observed': ['fraudnet_p1','fraudnet_p2','fraudnet_w','identity_di_log','tealeaf','datadog_rum','observability'],
        'observed_order': ['fraudnet_p1','fraudnet_p2','fraudnet_w','identity_di_log','tealeaf','datadog_rum','observability'],
        'missing': [],
        'required_missing': [],
        'counts': {'fraudnet_p1':1,'fraudnet_p2':1,'fraudnet_w':1,'identity_di_log':1,'tealeaf':1,'datadog_rum':1,'observability':1},
        'response_counts': {},
        'cookies': [{'name':'datadome','value':'x','domain':'.paypal.com','path':'/'}],
        'requests': [],
        'responses': [],
    }

flow._ensure_roxy_browser_for_datadome = MethodType(fail_sync_loop, flow)
flow._run_signup_context_risk_with_roxy_subprocess = MethodType(fake_subprocess, flow)

ok = flow._send_signup_context_risk_signals_with_roxy('https://www.paypal.com/checkoutweb/signup?token=EC-TEST', 'EC-TEST', force=True)
risk = flow.state.risk_signals_browser_result.get('signup_context', {})
result = {
    'ok': bool(ok),
    'subprocess_called': called['subprocess'],
    'runtime_source': flow.state.risk_signals_runtime_source,
    'missing': risk.get('missing'),
    'required_missing': risk.get('required_missing'),
    'cookie_imported': bool(flow.state.datadome_cookie),
}
print(json.dumps(result, ensure_ascii=False, indent=2))
assert result['ok'] is True
assert result['subprocess_called'] == 1
assert result['runtime_source'] == 'roxy'
assert result['required_missing'] == []
