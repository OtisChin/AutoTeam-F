import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/MailAccountsPage.vue', import.meta.url), 'utf8')

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `${name} should be implemented in MailAccountsPage.vue`)

  const bodyStart = source.indexOf('{', start)
  assert.notEqual(bodyStart, -1, `${name} should have a function body`)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') depth -= 1
    if (depth === 0) return source.slice(start, index + 1)
  }
  assert.fail(`${name} should have a complete function body`)
}

const defaultSizeMatch = source.match(/const DEFAULT_MAIL_PAGE_SIZE = (\d+)/)
assert.ok(defaultSizeMatch, 'mail account pagination should define a bounded default page size')
assert.equal(Number(defaultSizeMatch[1]), 100, 'mail account tables should mount 100 rows by default')

const sizeOptionsMatch = source.match(/const MAIL_PAGE_SIZE_OPTIONS = Object\.freeze\(\[([^\]]+)]\)/)
assert.ok(sizeOptionsMatch, 'mail account pagination should expose a finite page-size allowlist')
const sizeOptions = sizeOptionsMatch[1].split(',').map(value => Number(value.trim()))
assert.deepEqual(sizeOptions, [50, 100, 200, 500])
assert.ok(Math.max(...sizeOptions) <= 500, 'mail account page sizes must never exceed 500 rows')

const helpers = new Function(`
  const DEFAULT_MAIL_PAGE_SIZE = ${Number(defaultSizeMatch[1])}
  const MAIL_PAGE_SIZE_OPTIONS = Object.freeze(${JSON.stringify(sizeOptions)})
  ${extractFunction('normalizeMailPageSize')}
  ${extractFunction('clampPage')}
  ${extractFunction('pageRows')}
  ${extractFunction('buildFetchedPage')}
  return { normalizeMailPageSize, clampPage, pageRows, buildFetchedPage }
`)()

assert.equal(helpers.normalizeMailPageSize(null), 100)
assert.equal(helpers.normalizeMailPageSize(0), 100, 'legacy all-row values should fall back to 100')
assert.equal(helpers.normalizeMailPageSize(500), 500)
assert.equal(helpers.normalizeMailPageSize(501), 100, 'values above the allowlist must stay bounded')
assert.equal(helpers.clampPage(999, 4), 4)
assert.equal(helpers.clampPage(-5, 4), 1)

const accounts = Array.from({ length: 20_000 }, (_, index) => ({ email: `mail-${index}@example.com` }))
assert.equal(helpers.pageRows(accounts, 1, 100).length, 100, 'the first account paint should mount 100 rows')
assert.equal(helpers.pageRows(accounts, 40, 500).length, 500)
assert.equal(helpers.pageRows(accounts, 999, 500)[0].email, 'mail-19500@example.com', 'out-of-range pages should clamp to the final page')

const oneLargeMailbox = [{
  email: 'large@example.com',
  status: 'ok',
  messages: Array.from({ length: 20_000 }, (_, index) => ({ id: `message-${index}` })),
}]
const firstFetchedPage = helpers.buildFetchedPage(oneLargeMailbox, 1, 100)
assert.equal(firstFetchedPage.totalRows, 20_000)
assert.equal(firstFetchedPage.rows.length, 100, 'one large mailbox should still mount only one page of messages')
assert.equal(firstFetchedPage.rows.at(-1).message.id, 'message-99')
const lastFetchedPage = helpers.buildFetchedPage(oneLargeMailbox, 999, 100)
assert.equal(lastFetchedPage.page, 200, 'fetched-result pages should clamp after data replacement')
assert.equal(lastFetchedPage.rows[0].message.id, 'message-19900')

const manyMailboxes = Array.from({ length: 20_000 }, (_, index) => ({
  email: `result-${index}@example.com`,
  status: index % 2 ? 'ok' : 'error',
  error: index % 2 ? '' : 'failed',
  messages: [],
}))
assert.equal(
  helpers.buildFetchedPage(manyMailboxes, 1, 100).rows.length,
  100,
  'many empty/error mailbox results should share the same global render budget',
)

assert.match(source, /const filteredEmails = computed\(\(\) => filteredRows\.value\.map\(row => row\.email\)\)/, 'bulk selection should keep using every filtered row')
assert.match(source, /v-for="\(row, index\) in pagedRows"/, 'the account table should render only its current page')
assert.doesNotMatch(source, /v-for="\(row, index\) in filteredRows"/, 'the account table must not mount all filtered rows')
assert.match(source, /watch\(\[checkFilter, statusFilter, emailQuery, noteQuery, accountPageSize\], \(\) => \{[\s\S]{0,120}?accountPage\.value = 1/, 'filter and page-size changes should reset the account page')
assert.match(source, /watch\(accountTotalPages, value => \{[\s\S]{0,160}?accountPage\.value = clampPage\(accountPage\.value, value\)/, 'data changes should clamp the account page')

assert.match(source, /v-for="entry in pagedFetchedRows"/, 'fetched results should render only their global page window')
assert.doesNotMatch(source, /v-for="result in fetchedResults"/, 'fetched results must not mount every mailbox')
assert.doesNotMatch(source, /v-for="message in result\.messages"/, 'one mailbox must not mount every fetched message')
assert.match(source, /fetchedPage\.value = 1[\s\S]{0,200}?fetchedResults\.value = result\.results \|\| \[\]/, 'new fetch data should reset the fetched-result page')
assert.match(source, /watch\(fetchedTotalPages, value => \{[\s\S]{0,160}?fetchedPage\.value = clampPage\(fetchedPage\.value, value\)/, 'fetched-result replacement should clamp stale pages')

const passwordResults = Array.from({ length: 2_000 }, (_, index) => ({ email: `password-${index}@example.com` }))
assert.equal(helpers.pageRows(passwordResults, 1, 100).length, 100, 'password-result modal should share the bounded render window')
assert.match(source, /v-for="item in pagedPasswordResults"/, 'password results should render only their current page')
assert.doesNotMatch(source, /v-for="item in passwordResults"/, 'password results must not mount the full 2,000-item backend batch')
assert.match(source, /passwordPage\.value = 1[\s\S]{0,160}?passwordResults\.value = result\.results \|\| \[\]/, 'new password results should reset their page')
assert.match(source, /watch\(passwordTotalPages, value => \{[\s\S]{0,160}?passwordPage\.value = clampPage\(passwordPage\.value, value\)/, 'password-result replacement should clamp stale pages')

console.log('mail account render-window tests passed: accounts=20000 default=100 max=500 fetched=20000 password=2000')
