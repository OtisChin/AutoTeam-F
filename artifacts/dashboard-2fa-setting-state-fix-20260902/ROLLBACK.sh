#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$(pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
git apply -R "$SCRIPT_DIR/DIFF_FILE.patch"
rm -f tests/unit/test_task_snapshots.py
