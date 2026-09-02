#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${1:-$(pwd)}"
for relative in \
  "web/src/components/Dashboard.vue" \
  "web/scripts/regression-dashboard-2fa-actions.mjs"
do
  mkdir -p "$(dirname "$TARGET_ROOT/$relative")"
  cp "$SCRIPT_DIR/baseline/$relative" "$TARGET_ROOT/$relative"
done
echo "restored: $TARGET_ROOT"
echo "behavior: 2FA setup buttons return to green and the local submission label returns to task-only progress"
