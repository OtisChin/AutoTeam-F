#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
ORIGINAL_ROOT="$SCRIPT_DIR/original"
restore_file() {
  local rel="$1"
  local src="$ORIGINAL_ROOT/$rel"
  local dst="$TARGET_ROOT/$rel"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
}
restore_file "src/autotoken/api_routes/account_exports.py"
restore_file "src/autotoken/api_routes/account_management.py"
restore_file "web/src/components/Dashboard.vue"
python3 - "$TARGET_ROOT/tests/unit/test_account_import_export_2fa.py" "$TARGET_ROOT/web/scripts/test-dashboard-2fa-import-format.mjs" <<'PY'
import os
import sys

for path in sys.argv[1:]:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
PY
echo "rollback restored account import/export 2FA files under $TARGET_ROOT"
