#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE = Path('/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/live_create_member_no_fi_v8.py')
ns: dict[str, object] = {}
code = BASE.read_text()
# Load helpers but do not execute base main.
code = code.replace('if __name__ == "__main__":\n    main()\n', '')
exec(compile(code, str(BASE), 'exec'), ns)

logger = ns['logger']
sanitize_for_log = ns['sanitize_for_log']
PayPalFlow = ns['PayPalFlow']
generate_user = ns['generate_user']
generate_card = ns['generate_card']
generate_address = ns['generate_address']
build_proxy_config = ns['build_proxy_config']
FixedSmsccProvider = ns['FixedSmsccProvider']
load_ba_token = ns['load_ba_token']
prepare_pre_create_member = ns['prepare_pre_create_member']
build_create_member_variables = ns['build_create_member_variables']
consume_create_member = ns['consume_create_member']
CREATE_MEMBER_ACCOUNT_MUTATION = ns['CREATE_MEMBER_ACCOUNT_MUTATION']
build_signup_fn_sync_data = ns['build_signup_fn_sync_data']
send_analytics_ts = ns['send_analytics_ts']
graphql_errors = ns['graphql_errors']
APPROVE_MEMBER_PAYMENT_MUTATION = ns['APPROVE_MEMBER_PAYMENT_MUTATION']
APPROVE_ONBOARD_PAYMENT_MUTATION = ns['APPROVE_ONBOARD_PAYMENT_MUTATION']
redacted_token = ns['redacted_token']


def href_from_session_result(res, key):
    obj = res[0] if isinstance(res, list) and res else res
    data = obj.get('data') if isinstance(obj, dict) and isinstance(obj.get('data'), dict) else {}
    sess = data.get(key) if isinstance(data, dict) and isinstance(data.get(key), dict) else {}
    cart = sess.get('cart') if isinstance(sess, dict) and isinstance(sess.get('cart'), dict) else {}
    ret = cart.get('returnUrl') if isinstance(cart.get('returnUrl'), dict) else {}
    return str(ret.get('href') or '')


def follow_return(flow, return_url, referer):
    if not return_url:
        return {'followed': False, 'reason': 'missing_return_url'}
    final = ''
    statuses = []
    try:
        resp = flow.session.get(return_url, headers={
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': referer,
            'Upgrade-Insecure-Requests': '1',
        })
        statuses.append(int(getattr(resp,'status_code',0) or 0))
        final = str(getattr(resp, 'url', '') or '')
        for _ in range(8):
            if resp.status_code not in (301,302,303,307,308):
                break
            loc = resp.headers.get('Location','')
            if not loc: break
            final = urllib.parse.urljoin(str(resp.url), loc)
            resp = flow.session.get(final, headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': str(resp.url),
                'Upgrade-Insecure-Requests': '1',
            })
            statuses.append(int(getattr(resp,'status_code',0) or 0))
            final = str(getattr(resp, 'url', '') or final)
        parsed = urllib.parse.urlsplit(final)
        qs = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        return {
            'followed': True,
            'statuses': statuses,
            'final_host': parsed.netloc,
            'final_path': parsed.path,
            'redirect_status': qs.get('redirect_status') or qs.get('status'),
            'has_payment_intent': bool(qs.get('payment_intent')),
            'has_client_secret': bool(qs.get('payment_intent_client_secret')),
            'final_url_present': bool(final),
        }
    except Exception as exc:
        return {'followed': False, 'exception': str(exc)[:500], 'final_url_present': bool(final), 'statuses': statuses}


def main():
    logger.remove(); logger.add(sys.stderr, level=os.getenv('LOG_LEVEL','INFO'))
    for k, default in {
        'PAYPAL_FINGERPRINT_SOURCE':'headless','PAYPAL_DATADOME_MODE':'headless','PAYPAL_MTR_RUNTIME':'headless','PAYPAL_RISK_SIGNALS_MODE':'headless'
    }.items(): os.environ[k]=os.getenv(k, default)
    ba=load_ba_token(); phone=os.getenv('PAYPAL_TEST_PHONE','+18352891555'); sms=os.getenv('SMSCC_RECORD_URL','')
    if not sms: raise SystemExit('SMSCC_RECORD_URL is required')
    proxy_raw=os.getenv('PROXY','').strip(); proxy_config=build_proxy_config(enabled=bool(proxy_raw), proxy_url=proxy_raw)
    flow=PayPalFlow(ba_token=ba,user=generate_user(phone,country='US'),card=generate_card(proxy_url=proxy_config.url,country='US'),address=generate_address(proxy_url=proxy_config.url,country='US'),proxy_config=proxy_config,fingerprint_source=os.environ['PAYPAL_FINGERPRINT_SOURCE'],datadome_mode=os.environ['PAYPAL_DATADOME_MODE'],mtr_runtime=os.environ['PAYPAL_MTR_RUNTIME'],risk_signals_mode=os.environ['PAYPAL_RISK_SIGNALS_MODE'],sms_provider=FixedSmsccProvider(phone,sms))
    out={'stage':'live_create_member_no_fi_v8_follow_return','ba_present':True,'proxy':proxy_config.label}
    try:
        logger.info('v8 follow-return probe BA={} phone={} proxy={}', redacted_token(ba), flow._masked_phone(), proxy_config.label)
        flow._phase0_initial_load(); flow._phase2_create_account()
        token=flow.state.ec_token or flow.ba_token; signup_url=flow.state.signup_url or 'https://www.paypal.com/checkoutweb/signup'
        out['phase0_2']={'ec_present':bool(flow.state.ec_token),'signup_url_present':bool(flow.state.signup_url)}
        prepare_pre_create_member(flow, token, signup_url)
        create_res=flow._graphql_with_authchallenge_frontend_retry('CreateMemberAccountMutation', CREATE_MEMBER_ACCOUNT_MUTATION, build_create_member_variables(flow, token), signup_url, extra_body={'fn_sync_data': build_signup_fn_sync_data(token, session=flow.session)})
        out['createMemberAccount']={'result':sanitize_for_log(create_res),'consume':consume_create_member(flow, create_res)}
        if flow.state.euat_token: flow._ensure_euat_cookie()
        send_analytics_ts(flow.session, 'main:billing:hagrid:billingwithoutpurchase:member:review', flow.ba_token, ec_token=flow.state.ec_token, user_id=flow.state.user_id)
        variants=[]
        res_guest=flow.session.graphql('ApproveOnboardPaymentMutation', APPROVE_ONBOARD_PAYMENT_MUTATION, {'token':token,'instrumentId':None,'isBillingAgreement':False,'supportedThreeDsExperiences':['IFRAME']}, graphql_error_level='WARNING')
        variants.append({'name':'approveGuestSignUpPayment_skipSticky','result':sanitize_for_log(res_guest),'errors':sanitize_for_log(graphql_errors(res_guest))})
        res_member=flow.session.graphql('ApproveMemberPaymentMutation', APPROVE_MEMBER_PAYMENT_MUTATION, {'token':token,'primaryFundingOptionId':None,'setStickyFiRequired':False,'preAuthorizationRequired':False,'supportedThreeDsExperiences':['IFRAME']}, graphql_error_level='WARNING')
        href=href_from_session_result(res_member,'approveMemberPayment')
        follow=follow_return(flow, href, signup_url)
        variants.append({'name':'approveMemberPayment_noPrimaryFI','result':sanitize_for_log(res_member),'errors':sanitize_for_log(graphql_errors(res_member)),'return_follow':sanitize_for_log(follow)})
        out['approve_variants']=variants
        obj=res_member[0] if isinstance(res_member,list) and res_member else res_member
        sess=((obj.get('data') or {}).get('approveMemberPayment') or {}) if isinstance(obj,dict) else {}
        out['terminal']={'success':str(sess.get('state') or '')=='APPROVED' and bool(href),'variant':'approveMemberPayment_noPrimaryFI','state':sess.get('state'),'returnUrl_present':bool(href),'return_follow':sanitize_for_log(follow)}
    except Exception as exc:
        out['exception']=str(exc)[:1200]
    finally:
        try: flow.close()
        except Exception: pass
    print(json.dumps(sanitize_for_log(out), ensure_ascii=False, indent=2))
    sys.exit(0 if out.get('terminal',{}).get('success') else 2)
if __name__ == '__main__': main()
