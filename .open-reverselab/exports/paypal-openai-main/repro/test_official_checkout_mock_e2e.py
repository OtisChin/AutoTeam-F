#!/usr/bin/env python3
from __future__ import annotations
import os, subprocess, sys, time, urllib.request, re, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
mock=subprocess.Popen([sys.executable,str(ROOT/'paypal_official_mock_server.py'),'--port','18765'])
try:
    time.sleep(0.3)
    env=os.environ.copy(); env.update({
        'PAYPAL_CLIENT_ID':'mock-client-id',
        'PAYPAL_CLIENT_SECRET':'mock-secret',
        'PAYPAL_API_BASE_OVERRIDE':'http://127.0.0.1:18765',
        'PAYPAL_AUTO_WAIT':'1',
        'PAYPAL_WAIT_TIMEOUT':'5',
        'PAYPAL_CALLBACK_PORT':'18766',
    })
    p=subprocess.Popen([sys.executable,str(ROOT/'paypal_official_local_checkout_v2.py')], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    output=[]; approval=''; deadline=time.time()+10
    while time.time()<deadline:
        line=p.stdout.readline() if p.stdout else ''
        if line:
            output.append(line)
            joined=''.join(output)
            m=re.search(r'http://127\.0\.0\.1:18766/return\?token=MOCK-ORDER-12345&PayerID=MOCKPAYER', joined)
            if m and not approval:
                approval=m.group(0)
                urllib.request.urlopen(approval, timeout=2).read()
        if p.poll() is not None:
            break
        time.sleep(0.05)
    if p.poll() is None:
        p.terminate(); p.wait(2)
    out=''.join(output) + (p.stdout.read() if p.stdout else '')
    ok='"stage": "created_approved_captured"' in out and '"capture_status": "COMPLETED"' in out and p.returncode == 0
    result={'ok':ok,'approval_clicked':bool(approval),'client_exit':p.returncode,'output_tail':out[-3000:]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)
finally:
    mock.terminate()
    try: mock.wait(2)
    except subprocess.TimeoutExpired: mock.kill()
