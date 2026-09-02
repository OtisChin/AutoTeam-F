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
restore_file "web/src/components/Dashboard.vue"
restore_file "web/scripts/regression-dashboard-2fa-column.mjs"
python3 - "$TARGET_ROOT/web/scripts/test-dashboard-export-time-merge.mjs" <<'PY'
import os
import sys

try:
    os.unlink(sys.argv[1])
except FileNotFoundError:
    pass
PY
echo "rollback restored dashboard export time merge files under $TARGET_ROOT"
