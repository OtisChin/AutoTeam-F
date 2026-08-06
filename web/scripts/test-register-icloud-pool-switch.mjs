import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { accountPoolVisibleAccounts } from '../src/accountPoolStatus.js'

const api = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const page = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')

assert.match(api, /importICloudAccounts:\s*\(content,\s*filename\s*=\s*''\)\s*=>\s*request\('POST',\s*'\/config\/icloud-accounts\/import'/, 'API exposes iCloud import route')
assert.match(api, /getICloudAccountsStatus:\s*\(includeAll\s*=\s*false\)\s*=>\s*request\('GET',\s*`\/config\/icloud-accounts\/status\$\{includeAll\s*\?\s*'\?include_all=true'\s*:\s*''\}`\)/, 'API exposes lightweight iCloud status route with optional full list')
assert.match(api, /deleteICloudAccounts:\s*\(emails\)\s*=>\s*request\('POST',\s*'\/config\/icloud-accounts\/delete'/, 'API exposes iCloud delete route')

assert.match(page, /isICloudProvider\s*=\s*computed\(\(\)\s*=>\s*registerForm\.value\.mailProvider\s*===\s*'icloud'\)/, 'register page detects iCloud provider')
assert.match(page, /api\.getICloudAccountsStatus\(includeAll\)/, 'register page loads lightweight iCloud pool status unless full list is requested')
assert.match(page, /api\.importICloudAccounts\(/, 'register page imports iCloud pool accounts')
assert.match(page, /api\.deleteICloudAccounts\(/, 'register page deletes iCloud pool accounts')
assert.match(page, /outlookPoolStatusFilter\.value\s*=\s*isICloudProvider\.value\s*\?\s*'available'\s*:\s*'all'/, 'iCloud pool defaults to available filter')
assert.match(page, /resolveAccountPoolVisibleAccounts\(outlookPoolStatus\.value,\s*outlookPoolStatusFilter\.value/, 'register page resolves filtered pool lists through accountPoolStatus helper')
assert.match(page, /openOutlookPoolDialog[\s\S]*?loadOutlookPoolStatus\(\{\s*includeAll:\s*true\s*\}\)/, 'opening account pool management requests full iCloud status list')
assert.match(page, /loadOutlookPoolStatus\(options\s*=\s*\{\}\)[\s\S]*?const includeAll\s*=\s*Boolean\(options\.includeAll\s*\|\|\s*outlookPoolDialogOpen\.value\)/, 'pool status loader keeps default load lightweight and dialog load full')
assert.match(page, /function loadRegisterLogs\(\)\s*\{\s*if\s*\(logsLoading\.value\)\s*return/, 'register log polling avoids overlapping requests')
assert.match(page, /function loadRegisterStats\(\)\s*\{\s*if\s*\(statsLoading\)\s*return[\s\S]*?finally\s*\{\s*statsLoading\s*=\s*false\s*\}/, 'register stats polling avoids overlapping requests')
assert.match(page, /if\s*\(!mailProviderWatchReady\)\s*return/, 'initial saved mail provider restore does not synchronously load heavy pool data')
assert.match(page, /function startRegisterPolling\(\)[\s\S]*?setInterval\(loadRegisterStats,\s*REGISTER_POLL_INTERVAL_MS\)[\s\S]*?setInterval\(loadRegisterLogs,\s*REGISTER_POLL_INTERVAL_MS\)/, 'register page polls stats and logs only through guarded task polling')
assert.match(page, /if\s*\(props\.runningTask\)\s*startRegisterPolling\(\)/, 'register page restores live log polling when an active register task exists')
assert.match(page, /if\s*\(newId\)\s*\{[\s\S]*?loadRegisterLogs\(\)[\s\S]*?loadRegisterStats\(\)[\s\S]*?startRegisterPolling\(\)/, 'register page starts live refresh when a register task appears')
assert.doesNotMatch(page, /mailProviderWatchReady\s*=\s*true[\s\S]{0,120}loadOutlookPoolStatus\(\)/, 'register page does not automatically load account pool on entry')
assert.match(page, /api\.getRoxyBrowserWorkspaces\(\)/, 'register page preflights RoxyBrowser before submitting RoxyBrowser registration')
assert.match(page, /RoxyBrowser 未连接/, 'register page shows a friendly RoxyBrowser unavailable message')
assert.match(
  page,
  /watch\(\s*\(\)\s*=>\s*registerForm\.value\.mailProvider[\s\S]*?loadOutlookPoolStatus\(\)/,
  'switching between outlook and icloud providers reloads the account pool'
)

const icloudStatus = {
  total: 3705,
  available: 1,
  accounts: [{ email: 'fresh@icloud.com', status: 'available' }],
  all_accounts: [
    { email: 'dead1@icloud.com', status: 'unavailable' },
    { email: 'dead2@icloud.com', status: 'unavailable' },
  ],
  unavailable_accounts: [
    { email: 'dead1@icloud.com', status: 'unavailable' },
    { email: 'dead2@icloud.com', status: 'unavailable' },
  ],
}
assert.deepEqual(
  accountPoolVisibleAccounts(icloudStatus, 'available', { isICloudProvider: true }).map(item => item.email),
  ['fresh@icloud.com'],
  'iCloud available filter uses the available accounts bucket even when all_accounts page has no available rows',
)
