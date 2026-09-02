#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${1:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
ORIGINAL_ROOT="$SCRIPT_DIR/original"
mkdir -p "$TARGET_ROOT/web/src/components"
cp "$ORIGINAL_ROOT/web/src/components/Dashboard.vue" "$TARGET_ROOT/web/src/components/Dashboard.vue"
rm -f "$TARGET_ROOT/web/scripts/test-dashboard-oauth-badge.mjs"
echo "rollback restored Dashboard.vue and removed test-dashboard-oauth-badge.mjs under $TARGET_ROOT"
