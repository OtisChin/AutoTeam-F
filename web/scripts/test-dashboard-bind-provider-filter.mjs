import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const root = path.resolve(import.meta.dirname, '..')
const file = path.join(root, 'src', 'components', 'Dashboard.vue')
const source = fs.readFileSync(file, 'utf8')

function assertContains(needle, message) {
  if (!source.includes(needle)) {
    throw new Error(message + `\nMissing: ${needle}`)
  }
}

assertContains('v-model="bindProviderFilter"', 'filter bar should expose a binding provider select')
assertContains('accountBindProviderFilterOptions', 'binding provider select should render counted options')
assertContains("const bindProviderFilter = ref('')", 'script should store binding provider filter state')
assertContains('bindProviderFilter,', 'watch list should reset pagination when binding provider changes')
assertContains("import { buildAccountSearchIndex, filterAccountSearchIndex } from '../accountSearchIndex.js'", 'dashboard should use the normalized account search index')
assertContains('bindProvider: bindProviderFilter.value', 'dashboard should pass the binding provider filter to the search index')
assertContains('bindProviderFilter.value = \'\'', 'clearFilters should reset binding provider filter')

const searchIndexUrl = pathToFileURL(path.join(root, 'src', 'accountSearchIndex.js')).href
const { buildAccountSearchIndex, filterAccountSearchIndex } = await import(searchIndexUrl)
const index = buildAccountSearchIndex([
  { email: 'kakao@example.com', last_bind_provider: ' KAKAO_PAY ' },
  { email: 'gcash@example.com', last_bind_provider: 'gcash_ph' },
  { email: 'none@example.com', last_bind_provider: '' },
])

assert.deepEqual(
  filterAccountSearchIndex(index, { bindProvider: 'kakao_pay' }).map(account => account.email),
  ['kakao@example.com'],
  'binding provider filtering should use normalized indexed values',
)
assert.deepEqual(
  filterAccountSearchIndex(index, { bindProvider: '__none__' }).map(account => account.email),
  ['none@example.com'],
  'empty providers should remain selectable through the __none__ facet',
)

console.log('dashboard binding provider filter wiring ok')
