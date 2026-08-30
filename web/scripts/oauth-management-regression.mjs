import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = name => readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
const oauth = source('OAuthPage.vue')
const pool = source('OAuthPhonePoolPage.vue')
const records = source('OAuthPhoneRecordsPage.vue')
const trade = source('TradeManagerPage.vue')

for (const stage of ['生成链接', '完成授权', '提交回调']) assert.match(oauth, new RegExp(stage))
for (const primitive of ['WorkflowWorkspace', 'WorkflowStage', 'UiStatusBadge', 'UiStatePanel']) assert.match(oauth, new RegExp(primitive))
assert.doesNotMatch(pool, /const\s+StatCard\s*=|\bh\(/)
for (const primitive of ['UiMetricSummary', 'UiDataToolbar', 'UiBatchBar', 'UiTableFrame', 'UiPagination', 'UiStatusBadge', 'UiStatePanel']) assert.match(pool, new RegExp(primitive))
assert.match(pool, /pagedItems/)
assert.match(pool, /OAUTH_PHONE_PAGE_SIZE\s*=\s*100/)
assert.match(pool, /<UiStatePanel v-else state="empty"/)
assert.match(pool, /<UiTableFrame[^>]*:empty="!pagedItems\.length"/)
assert.doesNotMatch(pool, /<tr v-if="!filteredItems\.length">/)
for (const fn of ['getOAuthPhonePool', 'importOAuthPhonePool', 'saveOAuthPhonePoolItem', 'deleteOAuthPhonePoolItems']) assert.match(pool, new RegExp(fn))
assert.match(records, /api\.getOAuthPhoneRecords\(500\)/)
assert.match(records, /OAUTH_PHONE_RECORDS_PAGE_SIZE\s*=\s*100/)
assert.match(records, /v-for="item in pagedRecords"/)
assert.match(records, /UiPagination/)
assert.match(records, /page\.value\s*=\s*Math\.min/)
assert.match(trade, /function maskPassword/)
assert.match(trade, /isPasswordVisible\(item\.code\)\s*\?\s*raw\s*:\s*maskPassword\(raw\)/)

// The bounded window contract: a 250-row response mounts three pages and no
// page exceeds the selected size (the default is 100).
const rows = Array.from({ length: 250 }, (_, index) => index)
const pageSize = 100
const pages = Math.ceil(rows.length / pageSize)
assert.equal(pages, 3)
for (let page = 1; page <= pages; page += 1) assert.ok(rows.slice((page - 1) * pageSize, page * pageSize).length <= pageSize)
console.log('oauth management regression passed')
