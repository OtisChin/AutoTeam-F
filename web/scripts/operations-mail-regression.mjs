import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/MailAccountsPage.vue', import.meta.url), 'utf8')
const template = source.split('<script setup>')[0]
for (const tag of [
  'UiPageHeader', 'UiMetricSummary', 'UiDataToolbar', 'UiBatchBar',
  'UiTableFrame', 'UiPagination', 'UiStatusBadge', 'UiStatePanel', 'AccessibleModal',
]) assert.match(source, new RegExp(`<${tag}\\b`), `MailAccounts should use ${tag}`)

assert.match(source, /createMessageClearScheduler/)
assert.match(source, /onBeforeUnmount\([\s\S]*messageClearScheduler\.dispose/)
assert.match(source, /const hasLoaded = ref\(false\)/)
assert.match(source, /const loadError = ref\(['"]['"]\)/)
assert.match(source, /v-for="\(row, index\) in pagedRows"/)
assert.match(source, /v-for="entry in pagedFetchedRows"/)
assert.match(source, /v-for="item in pagedPasswordResults"/)
assert.doesNotMatch(template, /\b(?:bg|border)-(?:gray|slate)-(?:950|900|800)\b/)
const row = source.match(/<tr v-for="\(row, index\) in pagedRows"[\s\S]*?<\/tr>/)?.[0] || ''
assert.ok(row, 'the bounded mail row should remain discoverable')
assert.ok((row.match(/<button\b/g) || []).length <= 3, 'one row should mount two password reveals and one action trigger at most')
console.log('operations mail UI contracts passed')
