import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/components/Dashboard.vue', import.meta.url), 'utf8')
const template = source.split('<script setup>')[0]
for (const tag of [
  'UiPageHeader', 'UiMetricSummary', 'UiDataToolbar', 'UiBatchBar',
  'UiTableFrame', 'UiPagination', 'UiStatusBadge', 'UiStatePanel',
]) assert.match(source, new RegExp(`<${tag}\\b`), `Dashboard should use ${tag}`)
assert.match(source, /<UiSegmentedControl\b/)
assert.match(source, /v-for="\(acc, i\) in paginatedAccounts"/)
assert.match(source, /v-memo=/)
assert.match(source, /buildAccountSearchIndex\(allAccounts\.value\)/)
assert.match(source, /buildAccountSelectionIndex\(filteredAccounts\.value\)/)
assert.match(source, /selectAccountsFromIndex\(accountSelectionIndex\.value, selectedSet\.value\)/)
assert.match(source, /state="partial"/)
assert.match(source, /@action="retryAccounts"|@action="emit\('retry-accounts'\)"/)
assert.doesNotMatch(template, /\b(?:bg|border)-(?:gray|slate)-(?:950|900|800)\b/)
assert.doesNotMatch(template, /transition-all/)
assert.match(source, /credentialExportPresentation\(acc\?\.credentials_exported\)/)
assert.match(source, /accountHubSyncPresentation\(acc\?\.account_hub_synced\)/)

assert.match(source, /<AccessibleModal v-if=\"accountActionMenuAccount\"/)
assert.match(source, /<AccessibleModal v-if=\"subscriptionDialog.open\"/)
assert.match(source, /<AccessibleModal v-if=\"latestMailDialog.open\"/)
const row = source.match(/<tr v-for="\(acc, i\) in paginatedAccounts"[\s\S]*?<\/tr>/)?.[0] || ''
assert.ok(row, 'the bounded account row should remain discoverable')
assert.ok((row.match(/<button\b/g) || []).length <= 1, 'each account row should retain one action trigger')
console.log('operations dashboard UI contracts passed')
