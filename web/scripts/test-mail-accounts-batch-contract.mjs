import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../src/components/MailAccountsPage.vue', import.meta.url), 'utf8')
const accountLoginRoute = readFileSync(new URL('../../src/autotoken/api_routes/account_login.py', import.meta.url), 'utf8')
const mailAccountsRoute = readFileSync(new URL('../../src/autotoken/api_routes/mail_accounts.py', import.meta.url), 'utf8')

function numericConstant(source, name) {
  const match = source.match(new RegExp(`(?:const )?${name} = ([\\d_]+)`))
  assert.ok(match, `${name} should be defined`)
  return Number(match[1].replaceAll('_', ''))
}

function extractFunction(name) {
  const start = page.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `${name} should be implemented in MailAccountsPage.vue`)
  const bodyStart = page.indexOf('{', start)
  assert.notEqual(bodyStart, -1, `${name} should have a function body`)
  let depth = 0
  for (let index = bodyStart; index < page.length; index += 1) {
    if (page[index] === '{') depth += 1
    if (page[index] === '}') depth -= 1
    if (depth === 0) return page.slice(start, index + 1)
  }
  assert.fail(`${name} should have a complete function body`)
}

function section(start, end) {
  const from = page.indexOf(start)
  const to = page.indexOf(end, from + start.length)
  assert.ok(from >= 0, `missing section start: ${start}`)
  assert.ok(to > from, `missing section end: ${end}`)
  return page.slice(from, to)
}

const backendAuthLimit = numericConstant(accountLoginRoute, 'ACCOUNT_LOGIN_BATCH_MAX_EMAILS')
const backendBatchLimit = numericConstant(mailAccountsRoute, 'MAIL_ACCOUNTS_BATCH_MAX_ITEMS')
assert.equal(backendAuthLimit, 1_000, 'the auth-session task API accepts at most 1000 emails')
assert.equal(backendBatchLimit, 2_000, 'mail account batch routes accept at most 2000 emails')
assert.equal(numericConstant(mailAccountsRoute, 'MAIL_ACCOUNTS_IMPORT_MAX_LINES'), 20_000, 'one import may legitimately exceed the auth-session task limit')

const frontendAuthLimit = numericConstant(page, 'MAIL_AUTH_SESSION_BATCH_MAX_ITEMS')
const frontendBatchLimit = numericConstant(page, 'MAIL_ACCOUNT_BATCH_MAX_ITEMS')
assert.equal(frontendAuthLimit, backendAuthLimit, 'the import follow-up cap should match the backend auth-session contract')
assert.equal(frontendBatchLimit, backendBatchLimit, 'the UI batch guard should match the backend mail-account contract')

const helpers = new Function(`
  const MAIL_AUTH_SESSION_BATCH_MAX_ITEMS = ${frontendAuthLimit}
  const MAIL_ACCOUNT_BATCH_MAX_ITEMS = ${frontendBatchLimit}
  ${extractFunction('planMailAuthSessionLogin')}
  ${extractFunction('mailAccountBatchLimitError')}
  ${extractFunction('formatMailImportOutcome')}
  return { planMailAuthSessionLogin, mailAccountBatchLimitError, formatMailImportOutcome }
`)()

const importedEmails = Array.from({ length: 20_000 }, (_, index) => `import-${index}@mail.com`)
const loginPlan = helpers.planMailAuthSessionLogin(importedEmails)
assert.equal(loginPlan.total, 20_000)
assert.equal(loginPlan.emails.length, 1_000, 'the UI should submit only one supported auth-session batch')
assert.equal(loginPlan.deferred, 19_000, 'the UI should report every imported account not started automatically')
assert.equal(loginPlan.emails.at(-1), 'import-999@mail.com')

const partialMessage = helpers.formatMailImportOutcome({ imported: 20_000, skipped: 0 }, loginPlan)
assert.match(partialMessage, /导入 20000 条/)
assert.match(partialMessage, /仅启动前 1000 个/)
assert.match(partialMessage, /剩余 19000 个未启动/)

const followupFailureMessage = helpers.formatMailImportOutcome(
  { imported: 20_000, skipped: 0 },
  loginPlan,
  '任务队列忙',
)
assert.match(followupFailureMessage, /导入 20000 条/)
assert.match(followupFailureMessage, /导入已完成/)
assert.match(followupFailureMessage, /后续 auth_session 登录启动失败：任务队列忙/)

assert.equal(helpers.mailAccountBatchLimitError(Array.from({ length: 2_000 })), '', 'exactly 2000 selected accounts should be accepted')
const overLimitError = helpers.mailAccountBatchLimitError(Array.from({ length: 2_001 }))
assert.match(overLimitError, /已选择 2001 个/)
assert.match(overLimitError, /单次最多支持 2000 个/)

const submitDialog = section('async function submitDialog()', 'async function checkRows')
assert.match(submitDialog, /const dialogBatchEmails = currentMailAccountDialogBatchEmails\(\)[\s\S]{0,180}?ensureMailAccountBatchWithinLimit\(dialogBatchEmails\)/, 'password/status/note requests should share the preflight batch guard')
assert.ok(submitDialog.indexOf('ensureMailAccountBatchWithinLimit(dialogBatchEmails)') < submitDialog.indexOf('busy.value = true'), 'dialog batch guard should run before entering request state')
assert.match(submitDialog, /const loginPlan = planMailAuthSessionLogin\(loginEmails\)/)
assert.match(submitDialog, /api\.loginMailAccountsAuthSession\(loginPlan\.emails\)/, 'import follow-up should send only the supported auth-session slice')
assert.doesNotMatch(submitDialog, /api\.loginMailAccountsAuthSession\(loginEmails\)/, 'import follow-up must not submit all 20k emails')
assert.match(submitDialog, /catch \(loginError\) \{[\s\S]{0,180}?formatMailImportOutcome\(result, loginPlan, loginError\.message\)/, 'follow-up failure should be converted into an import-success outcome')

for (const [name, end] of [
  ['async function checkRows', 'async function fetchRows'],
  ['async function fetchRows', 'async function deleteRows'],
  ['async function deleteRows', 'async function clearRows'],
]) {
  const body = section(name, end)
  assert.match(body, /ensureMailAccountBatchWithinLimit\(emails\)/, `${name} should reject oversized batches before its API request`)
  assert.ok(body.indexOf('ensureMailAccountBatchWithinLimit(emails)') < body.indexOf('await api.'), `${name} should guard before calling the API`)
}

console.log('mail account batch contract tests passed: import=20000 auth=1000 batch=2000 boundary=2000/2001')
