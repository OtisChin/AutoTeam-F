#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${1:-$(pwd)}"
for relative in \
  "src/autotoken/api_routes/account_overview.py" \
  "tests/unit/test_account_two_factor_service.py"
do
  mkdir -p "$(dirname "$TARGET_ROOT/$relative")"
  cp "$SCRIPT_DIR/baseline/$relative" "$TARGET_ROOT/$relative"
done
echo "restored: $TARGET_ROOT"
echo "behavior: dashboard compact accounts omit two_factor_enabled and totp_status again"
