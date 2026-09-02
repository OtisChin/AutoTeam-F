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
assert.match(dashboardSource, /v-model="twoFactorFilter"/)
assert.match(dashboardSource, /全部2FA状态/)
assert.match(dashboardSource, /已设置[\s\S]*未设置/)
assert.match(dashboardSource, /@click="setupAccountTwoFactor\(acc\)"[\s\S]*设置/)
assert.match(dashboardSource, /@click="batchSetupAccountTwoFactor"[\s\S]*批量设置2FA/)
assert.doesNotMatch(dashboardSource, /accountTwoFactorEnabled\(acc\) \? '已设置' : '未设置'/)

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
