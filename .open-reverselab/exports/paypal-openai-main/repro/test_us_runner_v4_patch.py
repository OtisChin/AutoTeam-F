#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path('/Users/mac/Downloads/openai-paypal-main')
PATCH = Path('/Users/mac/code/my/AutoTeam-F/.open-reverselab/patches/openai-paypal-main-us-runner-schema-weasley-otp-v4-draft.diff')
PYTHON = Path('/Users/mac/Downloads/openai-paypal-main/.venv/bin/python')
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

with tempfile.TemporaryDirectory(prefix='paypal-us-v4-') as td:
    dst = Path(td) / 'work'
    shutil.copytree(SOURCE, dst, ignore=shutil.ignore_patterns('.venv', '__pycache__', '.git', 'captures', 'debug'))
    subprocess.run(['patch', '-p1', '-i', str(PATCH)], cwd=dst, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run([str(PYTHON), '-m', 'py_compile', 'main.py', 'web.py', 'paypal/models.py', 'paypal/flow.py', 'paypal/session.py', 'paypal/graphql.py', 'paypal/country_profile.py'], cwd=dst, check=True)
    probe = r'''
import json
from paypal.models import generate_user, generate_address, generate_card
from paypal.flow import PayPalFlow
from paypal.proxy import ProxyConfig
import paypal.flow as flow_mod

flow_mod.send_weasley_log = lambda *args, **kwargs: None
user = generate_user('+18352891555', country='US')
addr = generate_address(country='US')
card = generate_card(country='US')
flow = PayPalFlow('BA-LOCALDRYRUN0000000', user, card, addr, proxy_config=ProxyConfig(False), fingerprint_source='random', datadome_mode='off', mtr_runtime='off', risk_signals_mode='off')
vars = flow._build_signup_variables('EC-LOCALDRYRUN0000000')
class ProbeFlow(PayPalFlow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.captured=[]; self.field_events=[]
    def _graphql_with_authchallenge_frontend_retry(self, operation_name, query, variables, signup_url):
        self.captured.append({'operation_name': operation_name, 'variables': variables})
        return {'data': {'initiateRiskBasedTwoFactorPhoneConfirmation': {'authId': 'AUTH-US', 'challengeId': 'CHAL-US', 'state': 'PENDING'}}}

probe_flow = ProbeFlow('BA-LOCALDRYRUN0000000', user, card, addr, proxy_config=ProxyConfig(False), fingerprint_source='random', datadome_mode='off', mtr_runtime='off', risk_signals_mode='off')
probe_flow._update_user_phone('+18352891555')
probe_flow._initiate_2fa_phone_confirmation('EC-LOCALDRYRUN0000000', 'https://www.paypal.com/checkoutweb/signup?country.x=US&locale.x=en_US')
otp_vars = probe_flow.captured[-1]['variables']
flow_py = open('paypal/flow.py', encoding='utf-8').read()
main_py = open('main.py', encoding='utf-8').read(); web_py = open('web.py', encoding='utf-8').read(); index_html = open('web_static/index.html', encoding='utf-8').read(); app_js = open('web_static/app.js', encoding='utf-8').read()
checks = {
  'cli_country_arg': '--country' in main_py and 'PAYPAL_COUNTRY' in main_py,
  'web_country_field': 'country: str = "BR"' in web_py and 'country=str(data.get("country"' in web_py,
  'ui_country_select': 'id="country"' in index_html and '美国 PayPal' in index_html,
  'js_country_submit': 'country: $("#country").value' in app_js,
  'us_user_phone': user.phone_country_code == '+1' and user.phone_local == '8352891555',
  'us_address': addr.country == 'US' and len(addr.state) == 2,
  'us_profile': flow._profile_country() == 'US' and flow._profile_locale() == 'en_US' and flow._profile_lang() == 'en-US',
  'us_signup_schema': vars.get('country') == 'US' and vars.get('phone', {}).get('countryCode') == '1' and 'identityDocument' not in vars and 'dateOfBirth' not in vars and 'productClass' not in vars.get('card', {}),
  'us_otp_locale': otp_vars.get('locale') == {'country': 'US', 'lang': 'en'} and otp_vars.get('phoneCountry') == 'US' and otp_vars.get('phoneNumber') == '8352891555',
  'griffin_language_profile': '"languageCode": get_country_profile(self.address.country).content_language' in flow_py,
  'us_field_events_conditional_kyc': 'signup_interaction_fields = [' in flow_py and 'country_profile.card_dob_required' in flow_py and 'IdentityDocumentNumber' in flow_py,
  'card_retry_preserves_country': 'generate_card(proxy_url=self.proxy_config.url, country=self.address.country)' in flow_py,
  'identity_retry_preserves_country': 'generate_user(current_phone, country=self.address.country)' in flow_py,
}
print(json.dumps({'ok': all(checks.values()), 'stage':'us_runner_v4_patch', 'checks':checks, 'otp_variables':otp_vars, 'signup_phone':vars.get('phone'), 'field_events_check':'static_conditional'}, ensure_ascii=False, indent=2))
'''
    result = subprocess.run([str(PYTHON), '-c', probe], cwd=dst, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = result.stdout; start = out.find('{')
    print(json.dumps(json.loads(out[start:]), ensure_ascii=False, indent=2))
