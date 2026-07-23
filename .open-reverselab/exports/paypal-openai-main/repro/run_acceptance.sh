#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 "$ROOT/test_official_checkout_mock_e2e.py"
python3 "$ROOT/test_us_schema_patch_payload.py"
