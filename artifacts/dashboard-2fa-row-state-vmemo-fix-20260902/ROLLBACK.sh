#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"`ncd "$ROOT_DIR"`npython - <<'PY'
from pathlib import Path
root = Path.cwd()
replacements = {
  'web/src/components/Dashboard.vue': [
    ("v-memo=\"[acc, accountPageStartIndex, isSelected(acc.email), accountActionBusy && actionEmail === acc.email, accountTwoFactorSetupInProgress(acc)]\"",
     "v-memo=\"[acc, accountPageStartIndex, isSelected(acc.email), accountActionBusy && actionEmail === acc.email]\""),
  ],
  'web/scripts/regression-dashboard-2fa-actions.mjs': [
    ("""assert.match(\n  dashboardSource,\n  /v-memo=\"\\[[^\\\"]*accountTwoFactorSetupInProgress\\(acc\\)[^\\\"]*\\]\"/,\n  'the account row memo should include the row 2FA setup state so the per-account 设置 button repaints as 设置中...',\n)\n""", ""),
  ],
  'src/autotoken/api_routes/task_actions.py': [
    ("task_logger.info(\"[2FA] {}\", message)", "task_logger.info(\"[2FA] %s\", message)"),
  ],
  'tests/unit/test_account_two_factor_service.py': [
    ("""    log_messages = []\n\n    class FakeLogger:\n        def info(self, message, *args):\n            log_messages.append(message.format(*args))\n\n""", ""),
    ("""        logger=FakeLogger(),\n""", ""),
    ("""    assert \"[2FA] 单测进度\" in log_messages\n""", ""),
  ],
}
for rel, reps in replacements.items():
    path = root / rel
    text = path.read_text(encoding='utf-8')
    for old, new in reps:
        if old not in text:
            raise SystemExit(f'rollback target not found: {rel}')
        text = text.replace(old, new, 1)
    path.write_text(text, encoding='utf-8', newline='')
PY
