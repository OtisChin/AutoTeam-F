#!/usr/bin/env bash
set -euo pipefail
cd /Users/mac/Downloads/openai-paypal-main
export PAYPAL_FINGERPRINT_SOURCE=headless
export PAYPAL_DATADOME_MODE=headless
export PAYPAL_MTR_RUNTIME=headless
export PAYPAL_RISK_SIGNALS_MODE=headless
python .venv/bin/python main.py \
  --country US \
  --approval-path create-member-no-fi \
  --ba-token 'BA-REPLACE_WITH_FRESH_TOKEN' \
  --phone '+1XXXXXXXXXX' \
  --sms-record-url 'https://sms-provider.example/api/record?token=REDACTED' \
  --fingerprint-source headless \
  --datadome-mode headless \
  --mtr-runtime headless \
  --risk-signals-mode headless
