import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const dashboardSource = readFileSync(path.resolve(here, '../src/components/Dashboard.vue'), 'utf8')

assert.match(
  dashboardSource,
  /<th class="[^"]*font-medium[^"]*">2FA<\/th>/,
  'the account table should include a 2FA column',
)
assert.match(
  dashboardSource,
  /function accountTwoFactorEnabled\(account\)[\s\S]*?two_factor_enabled[\s\S]*?totp_status[\s\S]*?enabled/,
  '2FA state should support both the boolean flag and enabled TOTP status',
)
assert.match(
  dashboardSource,
  /v-if="accountTwoFactorEnabled\(acc\)"[\s\S]*?已设置[\s\S]*?@click="setupAccountTwoFactor\(acc\)"/,
  'each account row should display its enabled state or a setup action',
)
assert.match(
  dashboardSource,
  /colspan="14">没有匹配的账号/,
  'the empty account row should span all 14 columns',
)

const helperBody = dashboardSource.match(
  /function accountTwoFactorEnabled\(account\) \{([\s\S]*?)\n\}/,
)?.[1]
assert.ok(helperBody, 'the 2FA state helper should be executable in isolation')
const twoFactorCompletedEmails = { value: new Set(['local@example.com']) }
const accountTwoFactorEmailKey = account => String(account?.email || '').trim().toLowerCase()
const accountTwoFactorEnabled = new Function('account', 'twoFactorCompletedEmails', 'accountTwoFactorEmailKey', helperBody)
const enabled = account => accountTwoFactorEnabled(account, twoFactorCompletedEmails, accountTwoFactorEmailKey)
assert.equal(enabled({ two_factor_enabled: true }), true)
assert.equal(enabled({ totp_status: 'enabled' }), true)
assert.equal(enabled({ email: 'local@example.com' }), true)
assert.equal(enabled({ totp_status: 'disabled' }), false)
assert.equal(enabled({}), false)

console.log('dashboard 2FA column regression passed')
