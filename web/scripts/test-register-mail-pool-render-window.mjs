import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `${name} should be implemented in RegisterAccountPage.vue`)
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

const pageSizeMatch = source.match(/const MAIL_COM_POOL_PAGE_SIZE = (\d+)/)
assert.ok(pageSizeMatch, 'mail.com pool management should define a fixed render page size')
const pageSize = Number(pageSizeMatch[1])
assert.equal(pageSize, 100, 'mail.com pool management should mount 100 rows by default')
assert.ok(pageSize <= 500, 'mail.com pool management must never mount more than 500 rows per page')

const helpers = new Function(`
  const MAIL_COM_POOL_PAGE_SIZE = ${pageSize}
  ${extractFunction('clampMailComPoolPage')}
  ${extractFunction('pageMailComPoolItems')}
  return { clampMailComPoolPage, pageMailComPoolItems }
`)()

assert.equal(helpers.clampMailComPoolPage(-3, 200), 1)
assert.equal(helpers.clampMailComPoolPage(999, 200), 200)

const items = Array.from({ length: 20_000 }, (_, index) => ({ email: `pool-${index}@mail.com` }))
const firstPage = helpers.pageMailComPoolItems(items, 1)
const lastPage = helpers.pageMailComPoolItems(items, 999)
assert.equal(firstPage.length, 100, 'the initial 20k pool paint should mount only 100 rows')
assert.equal(firstPage.at(-1).email, 'pool-99@mail.com')
assert.equal(lastPage.length, 100)
assert.equal(lastPage[0].email, 'pool-19900@mail.com', 'stale pages should clamp to the refreshed pool tail')
assert.deepEqual(helpers.pageMailComPoolItems([], 50), [], 'an empty refresh should render no stale rows')

assert.match(source, /import \{[^}]*shallowRef[^}]*\} from 'vue'/, 'the 20k immutable pool snapshot should avoid deep reactive conversion')
assert.match(source, /const mailComPoolStatus = shallowRef\(null\)/)
assert.match(source, /const mailComPoolPage = ref\(1\)/)
assert.match(source, /const mailComPoolPagedItems = computed\(\(\) => pageMailComPoolItems\(mailComPoolItems\.value, mailComPoolPage\.value\)\)/)
assert.match(source, /v-for="item in mailComPoolPagedItems"/, 'the dialog should render only the current mail.com page')
assert.doesNotMatch(source, /v-for="item in mailComPoolItems"/, 'the dialog must not mount the complete mail.com pool')
assert.doesNotMatch(source, /v-for="item in mailComPool(?:Filtered|Visible)Items"/, 'the dialog must not mount a complete filtered pool')

assert.match(source, /const mailComPoolVisibleEmails = computed\(\(\) => mailComPoolItems\.value\.map/, 'bulk selection should still target the complete filtered pool')
assert.match(source, /for \(const email of mailComPoolVisibleEmails\.value\)/, 'select-all should continue iterating every filtered email')
assert.match(source, /const mailComPoolSelectedSet = computed\(\(\) => new Set\(mailComPoolSelectedEmails\.value\)\)/, 'row and select-all membership checks should stay linear rather than quadratic')
assert.match(source, /:checked="mailComPoolSelectedSet\.has\(normalizeMailComEmail\(item\.email\)\)"/, 'mounted rows should use constant-time selection membership')

assert.match(source, /watch\(mailComPoolTotalPages, value => \{[\s\S]{0,180}?mailComPoolPage\.value = clampMailComPoolPage\(mailComPoolPage\.value, value\)/, 'pool refresh/filter changes should clamp stale pages')
assert.match(source, /function openMailComPoolDialog\(\) \{[\s\S]{0,100}?mailComPoolPage\.value = 1[\s\S]{0,100}?loadMailComPoolStatus\(\)/, 'opening the dialog should reset the initial render window')

console.log('register mail.com pool render-window tests passed: rows=20000 default=100 max=100 selection=full')
