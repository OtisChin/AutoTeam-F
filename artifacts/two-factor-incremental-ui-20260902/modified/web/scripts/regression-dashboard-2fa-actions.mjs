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
assert.match(apiSource, /getAccountTwoFactorTotp:\s*\(email\).*\/accounts\/\$\{encodeURIComponent\(email\)\}\/2fa\/totp/)
assert.match(appSource, /'setup-2fa':\s*'协议设置2FA'/)
assert.match(appSource, /<Dashboard[\s\S]*:tasks=\"tasks\"/, 'Dashboard should receive the full task list so 2FA running rows are not hidden by another busy task')
assert.match(dashboardSource, /v-model="twoFactorFilter"/)
assert.match(dashboardSource, /全部2FA状态/)
assert.match(dashboardSource, /已设置[\s\S]*未设置/)
assert.match(dashboardSource, /@click="setupAccountTwoFactor\(acc\)"[\s\S]*设置/)
assert.match(dashboardSource, /@click="openTwoFactorTotpDialog\(acc\)"[\s\S]*已设置/)
assert.match(dashboardSource, /2FA 验证码/)
assert.match(dashboardSource, /复制密钥/)
assert.match(dashboardSource, /当前验证码/)
assert.match(dashboardSource, /@click="refreshTwoFactorTotpDialog"[\s\S]*刷新/)
assert.match(
  dashboardSource,
  /async function fetchTwoFactorTotp\(email[\s\S]*api\.getAccountTwoFactorTotp\(target\)/,
  'clicking 已设置 should fetch the latest TOTP secret/code from the backend',
)
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
  /const twoFactorTasks = computed\(\(\) => \{[\s\S]*?props\.tasks[\s\S]*?isActiveTwoFactorTask/,
  'Dashboard should detect all setup-2fa tasks from the full task list, not only the single highlighted running task',
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
  /const twoFactorCompletedEmails = ref\(new Set\(\)\)/,
  'successful account-level 2FA events should be tracked locally before the whole batch ends',
)
assert.match(
  dashboardSource,
  /const twoFactorFailedEmails = ref\(new Set\(\)\)/,
  'failed account-level 2FA events should be tracked locally before the whole batch ends',
)
assert.match(
  dashboardSource,
  /function applyTwoFactorTaskProgressEvents\(tasks\)[\s\S]*status === 'enabled'[\s\S]*completed\.add\(email\)[\s\S]*pending\.delete\(email\)[\s\S]*status === 'failed'[\s\S]*failed\.add\(email\)[\s\S]*pending\.delete\(email\)/,
  'Dashboard should turn each completed 2FA account into 已设置 and each failed account back into 设置 from task progress events',
)
assert.match(
  dashboardSource,
  /const twoFactorProgressTasks = computed\(\(\) => \{[\s\S]*task\?\.command === 'setup-2fa'[\s\S]*watch\(twoFactorProgressTasks, tasks => \{[\s\S]*applyTwoFactorTaskProgressEvents\(tasks\)/,
  'Dashboard should consume setup-2fa progress events even when a task snapshot is no longer running',
)
assert.match(
  dashboardSource,
  /function accountTwoFactorEnabled\(account\)[\s\S]*twoFactorCompletedEmails\.value\.has\(accountTwoFactorEmailKey\(account\)\)/,
  'successful 2FA progress should make the account row show 已设置 before the account list reloads',
)
const accountTwoFactorProgressFunction = dashboardSource.match(
  /function accountTwoFactorSetupInProgress\(account\) \{[\s\S]*?\n\}/,
)?.[0] || ''
assert.doesNotMatch(
  accountTwoFactorProgressFunction,
  /twoFactorSubmitting\.value|twoFactorTaskRunning\.value/,
  'a single-account 2FA task must not make every account row display 设置中...',
)
assert.match(
  dashboardSource,
  /v-memo="\[[^\"]*accountTwoFactorSetupInProgress\(acc\)[^\"]*\]"/,
  'the account row memo should include the row 2FA setup state so the per-account 设置 button repaints as 设置中...',
)
assert.match(
  dashboardSource,
  /v-memo="\[[^\"]*twoFactorSubmitting \|\| twoFactorTaskRunning[^\"]*\]"/,
  'the account row memo should include global 2FA busy state so non-target buttons repaint to disabled without changing their label',
)
assert.match(
  dashboardSource,
  /@click="setupAccountTwoFactor\(acc\)"[\s\S]*?:disabled="accountTwoFactorSetupInProgress\(acc\)"/,
  'only the per-account 2FA setup button already in progress should be disabled',
)
assert.match(
  dashboardSource,
  /@click="setupAccountTwoFactor\(acc\)"[\s\S]*?:class="accountTwoFactorSetupInProgress\(acc\)/,
  'only the account being processed should get the yellow wait style',
)
assert.match(
  dashboardSource,
  /twoFactorSubmittingEmails\.value = new Set\(\[[\s\S]*\.\.\.twoFactorSubmittingEmails\.value[\s\S]*\.\.\.emails\.map/,
  'new per-account 2FA submissions should be merged into the local submitting-account state',
)
assert.match(
  dashboardSource,
  /for \(const email of emails\) submitting\.delete\(email\.toLowerCase\(\)\)/,
  'finishing one per-account 2FA submission should only clear that account from local submitting state',
)
assert.match(
  dashboardSource,
  /const twoFactorTasks = computed\(\(\) => \{[\s\S]*?activeTasks\.filter\(isActiveTwoFactorTask\)/,
  'Dashboard should track all active setup-2fa tasks so multiple account rows can show their own progress',
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


