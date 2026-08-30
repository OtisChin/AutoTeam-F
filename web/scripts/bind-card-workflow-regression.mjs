import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const bind = await readFile(resolve(root, 'src/components/BindCard.vue'), 'utf8')
const pool = await readFile(resolve(root, 'src/components/BindCardPool.vue'), 'utf8')

const checks = [
  ['bind card uses shared segmented workflow control', bind.includes("import UiSegmentedControl") && bind.includes('<UiSegmentedControl')],
  ['all workflow modes are available', ['bind', 'kiro', 'generate', 'gopay'].every(value => bind.includes(`value: '${value}'`))],
  ['workflow has configuration progress result stages', ['configuration', 'progress', 'result'].every(stage => bind.includes(`data-workflow-stage="${stage}"`))],
  ['standalone forces GoPay and hides tabs', bind.includes("props.standalone ? 'gopay' : initialTab") && bind.includes('v-if="!standalone"')],
  ['business props and refresh emit are preserved', bind.includes('initialTab:') && bind.includes('standalone:') && bind.includes("defineEmits(['refresh'])")],
  ['business functions and storage keys are preserved', ['generateLink', 'generateAndOpenWithAuthSession', 'startBindCard', 'cancelBindTask', 'startGoPayBind', 'cancelGoPayTask', 'CHATGPT_BIND_FORM_STATE_KEY', 'GOPAY_FORM_STATE_KEY'].every(name => bind.includes(name))],
  ['card pool uses shared page and segmented primitives', pool.includes("import UiPageHeader") && pool.includes("import UiSegmentedControl") && pool.includes('<UiPageHeader') && pool.includes('<UiSegmentedControl')],
  ['card pool uses shared status and accessible modal primitives', pool.includes("import UiStatusBadge") && pool.includes('<UiStatusBadge') && pool.includes("import AccessibleModal") && pool.includes('<AccessibleModal')],
  ['card pool keeps core operations', ['loadPool', 'submitImport', 'redeemSelected', 'executeDelete', 'toggleStatus', 'fetchSmsCode'].every(name => pool.includes(`function ${name}`))],
]

const failures = checks.filter(([, ok]) => !ok)
for (const [label, ok] of checks) console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`)
if (failures.length) process.exit(1)
console.log(`bind-card workflow regression passed: ${checks.length}/${checks.length}`)
