#!/usr/bin/env bash
set -euo pipefail
ROOT="/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro"
PY="/Users/mac/Downloads/openai-paypal-main/.venv/bin/python"
if [ ! -x "$PY" ]; then PY="python3"; fi
"$PY" "$ROOT/test_official_checkout_mock_e2e.py"
"$PY" "$ROOT/test_us_schema_patch_payload.py"
"$PY" "$ROOT/test_weasley_approve_patch.py"
"$PY" "$ROOT/test_us_schema_weasley_approve_patch_payload.py"
"$PY" "$ROOT/test_us_runner_v3_patch.py"
