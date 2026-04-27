
from pathlib import Path
from autoteam.api import BindLinkParams, post_bind_link

env_path = Path('data/.env')
token = None
for line in env_path.read_text(encoding='utf-8').splitlines():
    if line.startswith('AccessToken='):
        token = line.split('=', 1)[1].strip()
        break

cases = [
    ('plus', 'inline'),
    ('plus', 'hosted'),
    ('team', 'inline'),
    ('team', 'hosted'),
]

for plan_type, mode in cases:
    params = BindLinkParams(
        access_token=token,
        plan_name='chatgptplusplan' if plan_type == 'plus' else 'chatgptteamplan',
        promo_campaign={'promo_campaign_id': 'plus-1-month-free' if plan_type == 'plus' else 'team-1-month-free', 'is_coupon_from_query_param': False},
        billing_details={'country': 'US', 'currency': 'USD'},
        checkout_ui_mode=mode,
    )
    print('\nCASE', plan_type, mode)
    try:
        print(post_bind_link(params))
    except Exception as exc:
        print(type(exc).__name__, getattr(exc, 'status_code', None), getattr(exc, 'detail', str(exc)))
