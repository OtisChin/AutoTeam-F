import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { buildAccountSearchIndex, filterAccountSearchIndex } from '../src/accountSearchIndex.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const dashboardSource = readFileSync(path.resolve(here, '../src/components/Dashboard.vue'), 'utf8')
const apiSource = readFileSync(path.resolve(here, '../src/api.js'), 'utf8')
const appSource = readFileSync(path.resolve(here, '../src/App.vue'), 'utf8')

assert.match(apiSource, /setupAccountsTwoFactor:\s*\(emails\).*\/accounts\/2fa\/setup/)
assert.match(appSource, /'setup-2fa':\s*'协议设置2FA'/)
assert.match(appSource, /<Dashboard[\s\S]*:tasks=\"tasks\"/, 'Dashboard should receive the full task list so 2FA running rows are not hidden by another busy task')
assert.match(dashboardSource, /v-model="twoFactorFilter"/)
assert.match(dashboardSource, /全部2FA状态/)
assert.match(dashboardSource, /已设置[\s\S]*未设置/)
assert.match(dashboardSource, /@click="setupAccountTwoFactor\(acc\)"[\s\S]*设置/)
assert.match(dashboardSource, /@click="batchSetupAccountTwoFactor"[\s\S]*批量设置2FA/)
assert.doesNotMatch(dashboardSource, /accountTwoFactorEnabled\(acc\) \? '已设置' : '未设置'/)
assert.match(
  dashboardSource,
  /@click="setupAccountTwoFactor\(acc\)"[\s\S]*?border-yellow-500\/30[\s\S]*?text-yellow-300/,
  'the per-account 2FA setup button should use the yellow treatment',
)
assert.match(
  dashboardSource,
  /@click="batchSetupAccountTwoFactor"[\s\S]*?bg-yellow-600\/10[\s\S]*?text-yellow-300/,
  'the batch 2FA setup button should use the yellow treatment',
)
assert.match(
  dashboardSource,
  /function twoFactorButtonLabel\(account\)[\s\S]*?accountTwoFactorSetupInProgress\(account\) \? '设置中\.\.\.' : '设置'/,
  'the clicked account should immediately show 设置中 while its request is being submitted',
)
assert.match(dashboardSource, /const twoFactorSubmittingEmails = ref\(new Set\(\)\)/)
assert.match(dashboardSource, /const twoFactorPendingTaskEmails = ref\(new Set\(\)\)/)
assert.match(
  dashboardSource,
  /const twoFactorTask = computed\(\(\) => \{[\s\S]*?props\.tasks[\s\S]*?setup-2fa/,
  'Dashboard should detect setup-2fa from the full task list, not only the single highlighted running task',
)
assert.match(
  dashboardSource,
  /twoFactorPendingTaskEmails\.value = new Set\([\s\S]*?result\.task_id[\s\S]*?emit\('task-started'\)/,
  'submitted 2FA accounts should remain marked 设置中 after the API returns and before task polling catches up',
)
assert.match(
  dashboardSource,
  /function accountTwoFactorSetupInProgress\(account\)[\s\S]*?twoFactorPendingTaskEmails\.value\.has\(email\)/,
  'the 2FA button label should include locally pending task emails',
)
assert.match(
  dashboardSource,
  /v-memo="\[[^\"]*accountTwoFactorSetupInProgress\(acc\)[^\"]*\]"/,
  'the account row memo should include the row 2FA setup state so the per-account 设置 button repaints as 设置中...',
)
assert.match(
  dashboardSource,
  /twoFactorSubmittingEmails\.value = new Set\([\s\S]*?finally[\s\S]*?twoFactorSubmittingEmails\.value = new Set\(\)/,
  'the local submitting-account state should be populated and cleared around the request',
)

const accounts = [
  { email: 'enabled@example.com', two_factor_enabled: true },
  { email: 'status@example.com', totp_status: 'enabled' },
  { email: 'disabled@example.com', two_factor_enabled: false, totp_status: 'disabled' },
]
const index = buildAccountSearchIndex(accounts)
assert.deepEqual(
  filterAccountSearchIndex(index, { twoFactor: 'enabled' }).map(account => account.email),
  ['enabled@example.com', 'status@example.com'],
)
assert.deepEqual(
  filterAccountSearchIndex(index, { twoFactor: 'disabled' }).map(account => account.email),
  ['disabled@example.com'],
)

console.log('dashboard 2FA actions regression passed')


