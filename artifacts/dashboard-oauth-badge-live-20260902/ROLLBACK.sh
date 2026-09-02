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
restore_file "src/autotoken/core/task_snapshots.py"
restore_file "src/autotoken/api_routes/account_login.py"
restore_file "web/src/components/Dashboard.vue"
restore_file "tests/unit/test_task_snapshots.py"
restore_file "web/scripts/test-dashboard-oauth-badge.mjs"
echo "rollback restored 5 files under $TARGET_ROOT"
