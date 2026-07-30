import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const api = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const page = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')

assert.match(api, /importICloudAccounts:\s*\(content,\s*filename\s*=\s*''\)\s*=>\s*request\('POST',\s*'\/config\/icloud-accounts\/import'/, 'API exposes iCloud import route')
assert.match(api, /getICloudAccountsStatus:\s*\(\)\s*=>\s*request\('GET',\s*'\/config\/icloud-accounts\/status'\)/, 'API exposes iCloud status route')
assert.match(api, /deleteICloudAccounts:\s*\(emails\)\s*=>\s*request\('POST',\s*'\/config\/icloud-accounts\/delete'/, 'API exposes iCloud delete route')

assert.match(page, /isICloudProvider\s*=\s*computed\(\(\)\s*=>\s*registerForm\.value\.mailProvider\s*===\s*'icloud'\)/, 'register page detects iCloud provider')
assert.match(page, /api\.getICloudAccountsStatus\(\)/, 'register page loads iCloud pool status')
assert.match(page, /api\.importICloudAccounts\(/, 'register page imports iCloud pool accounts')
assert.match(page, /api\.deleteICloudAccounts\(/, 'register page deletes iCloud pool accounts')
assert.match(
  page,
  /watch\(\s*\(\)\s*=>\s*registerForm\.value\.mailProvider[\s\S]*?loadOutlookPoolStatus\(\)/,
  'switching between outlook and icloud providers reloads the account pool'
)
