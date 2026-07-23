#!/usr/bin/env python3
"""Local PayPal existing-buyer approve harness for openai-paypal-main v5 draft.

No third-party wrapper. It expects a v5-patched openai-paypal-main checkout session
and either a valid PayPal EUAT cookie value or a browser storage_state containing
PayPal logged-in/remembered cookies. Without those, PayPal returns ANONYMOUS auth.

Required live env:
  PAYPAL_BA_TOKEN=BA-...
  PAYPAL_MEMBER_FUNDING_OPTION_ID=<buyer wallet funding option id>
Optional live env:
  PROXY=socks5h://...
  PAYPAL_EUAT_TOKEN=<existing buyer EUAT>
  PAYPAL_STORAGE_STATE=/path/to/playwright_storage_state.json
"""
from __future__ import annotations

import argparse, json, os, re, sys
from pathlib import Path

WORK = Path(os.environ.get('OPENAI_PAYPAL_MAIN_WORK', '/tmp/openai-paypal-main-us-work'))
sys.path.insert(0, str(WORK))

from paypal.models import generate_user, generate_card, generate_address  # noqa:E402
from paypal.flow import PayPalFlow  # noqa:E402
from paypal.proxy import build_proxy_config  # noqa:E402

OUT_DEFAULT = Path('/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/existing_buyer_member_approve_live_summary.json')


def sanitize(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    text = re.sub(r'BA-[A-Za-z0-9_-]+', 'BA-<redacted>', text)
    text = re.sub(r'EC-[A-Za-z0-9_-]+', 'EC-<redacted>', text)
    text = re.sub(r'("(?:value|accessToken|euat|token|PAYPAL_EUAT_TOKEN)"\s*:\s*")[^"]+', r'\1<redacted>', text, flags=re.I)
    return json.loads(text)


def import_storage_state_cookies(flow: PayPalFlow, path: str) -> int:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(str(p))
    data = json.loads(p.read_text(encoding='utf-8'))
    cookies = data.get('cookies') if isinstance(data, dict) else []
    count = 0
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        domain = str(c.get('domain') or '')
        name = str(c.get('name') or '')
        if 'paypal.com' not in domain or not name:
            continue
        flow.session.client.cookies.set(name, str(c.get('value') or ''), domain=domain, path=str(c.get('path') or '/'))
        count += 1
    return count


def build_flow(ba: str, proxy: str = '') -> PayPalFlow:
    proxy_config = build_proxy_config(enabled=bool(proxy), proxy_url=proxy)
    user = generate_user('+18352891555', country='US')
    card = generate_card(country='US', proxy_url=proxy_config.url)
    addr = generate_address(country='US', proxy_url=proxy_config.url)
    return PayPalFlow(ba, user, card, addr, proxy_config=proxy_config, fingerprint_source='random', datadome_mode='off', mtr_runtime='off', risk_signals_mode='off', max_flow_attempts=1, max_card_attempts=1, max_authorize_attempts=1)


def run_live(args):
    ba = args.ba_token or os.environ.get('PAYPAL_BA_TOKEN', '')
    fi = args.funding_option_id or os.environ.get('PAYPAL_MEMBER_FUNDING_OPTION_ID', '')
    if not ba.startswith('BA-'):
        raise SystemExit('PAYPAL_BA_TOKEN is required')
    if not fi:
        raise SystemExit('PAYPAL_MEMBER_FUNDING_OPTION_ID is required')
    flow = build_flow(ba, args.proxy or os.environ.get('PROXY', ''))
    imported_cookies = 0
    storage_state = args.storage_state or os.environ.get('PAYPAL_STORAGE_STATE', '')
    if storage_state:
        imported_cookies = import_storage_state_cookies(flow, storage_state)
    euat = args.euat or os.environ.get('PAYPAL_EUAT_TOKEN', '')
    if euat:
        flow.state.euat_token = euat
        flow._ensure_euat_cookie()
    flow._phase0_initial_load()
    flow._phase2_create_account()
    result = flow._phase4_member_approve_existing_buyer(fi)
    summary = {
        'ok': result.get('status') == 'success',
        'status': result.get('status'),
        'ec_present': bool(flow.state.ec_token),
        'imported_paypal_cookies': imported_cookies,
        'euat_present': bool(flow.state.euat_token),
        'result': result,
    }
    args.out.write_text(json.dumps(sanitize(summary), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(sanitize({k: summary[k] for k in ['ok','status','ec_present','imported_paypal_cookies','euat_present']}), ensure_ascii=False, indent=2))
    return 0 if summary['ok'] else 2


def run_mock(args):
    flow = build_flow('BA-LOCALDRYRUN0000000')
    class DummySession:
        def __init__(self): self.calls=[]
        def graphql(self, operation_name, query, variables, **kwargs):
            self.calls.append({'operation_name': operation_name, 'variables': variables, 'query_has_signup': 'signUpNewMember' in query})
            return {'data': {'approveMemberPayment': {'state':'APPROVED','buyer': {'userId':'BUYER-MOCK'}, 'cart': {'returnUrl': {'href':'https://merchant.example/return?token=EC-LOCAL'}}, 'completedPaymentInfo': {'transactionState':'COMPLETED'}, 'fundingOptions': [{'fundingInstrument': {'id':'FI-MOCK'}}]}}}
        def get(self, url, headers=None):
            class R: url='https://merchant.example/return?ok=1'; content=b''; status_code=200; text=''
            return R()
    flow.session = DummySession(); flow.state.ec_token = 'EC-LOCALDRYRUN0000000'
    result = flow._phase4_member_approve_existing_buyer('FI-MOCK')
    checks = {'status_success': result.get('status') == 'success', 'no_signup': flow.session.calls[-1]['query_has_signup'] is False, 'fi': flow.state.instrument_id == 'FI-MOCK'}
    print(json.dumps({'ok': all(checks.values()), 'stage':'existing_buyer_harness_mock', 'checks':checks}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mock', action='store_true')
    ap.add_argument('--ba-token', default='')
    ap.add_argument('--funding-option-id', default='')
    ap.add_argument('--proxy', default='')
    ap.add_argument('--euat', default='')
    ap.add_argument('--storage-state', default='')
    ap.add_argument('--out', type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()
    return run_mock(args) if args.mock else run_live(args)

if __name__ == '__main__':
    raise SystemExit(main())
