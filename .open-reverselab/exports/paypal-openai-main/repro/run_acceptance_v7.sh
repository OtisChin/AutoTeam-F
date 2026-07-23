#!/usr/bin/env bash
set -euo pipefail
PY="/Users/mac/Downloads/openai-paypal-main/.venv/bin/python"
DIR="$(cd "$(dirname "$0")" && pwd)"
"$PY" "$DIR/test_onboard_guest_v7_patch.py"
"$PY" "$DIR/test_guest_card_direct_v6_patch.py"
"$PY" "$DIR/test_member_approve_v5_patch.py"
"$PY" "$DIR/test_official_checkout_mock_e2e.py"
