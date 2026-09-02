#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${1:-$(pwd)}"
cd "$TARGET_ROOT"
copy_original() {
  local rel="$1"
  mkdir -p "$(dirname "$rel")"
  cp "$SCRIPT_DIR/original/$rel" "$rel"
}
copy_original "src/autotoken/services/account_two_factor.py"
copy_original "tests/unit/test_account_two_factor_service.py"
echo "rollback restored sequential 2FA setup implementation"
