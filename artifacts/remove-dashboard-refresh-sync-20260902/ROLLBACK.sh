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
copy_original "web/src/components/Dashboard.vue"
copy_original "web/src/api.js"
echo "rollback restored dashboard refresh/sync button files"
