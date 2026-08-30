import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const read = name => readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
const trade = read('TradeManagerPage.vue')
const cpa = read('CpaToSub2ApiPage.vue')
const logs = read('LogViewer.vue')
for (const primitive of ['UiPageHeader', 'UiMetricSummary', 'UiStatePanel', 'UiTableFrame', 'UiStatusBadge']) assert.match(trade, new RegExp(primitive))
for (const fn of ['getTradeSummary', 'getTradeCdks', 'createTradeCdk', 'revokeTradeCdk', 'downloadTradeCdkRedemptions']) assert.match(trade, new RegExp(fn))
assert.match(trade, /aria-label=.*密码|密码.*aria-label/s)
assert.match(trade, /revokeCdk/)
for (const primitive of ['UiPageHeader', 'UiMetricSummary', 'UiStatePanel', 'AccessibleModal']) assert.match(cpa, new RegExp(primitive))
for (const fn of ['validateCpaFileSelection', 'inspectCpaToSub2Api', 'convertCpaToSub2Api', 'openOutputDir']) assert.match(cpa, new RegExp(fn))
assert.match(logs, /log-console|log-workspace/)
// LogViewer owns a completion-scheduled poll loop rather than exposing the
// shared workflow lifecycle helper used by long-running payment pages.  Keep
// this route contract aligned with its public UI handlers and local lifecycle
// functions so a naming change cannot mask a broken polling guard.
for (const fn of ['fetchLogs', 'clearLogs', 'scheduleNextPoll', 'runPoll']) {
  assert.match(logs, new RegExp(`(?:function\\s+|@click=")${fn}`), `LogViewer should expose ${fn}`)
}
assert.match(logs, /let requestInFlight = false/)
assert.match(logs, /await fetchLogs\(\)[\s\S]*scheduleNextPoll\(\)/)
assert.doesNotMatch(logs, /setInterval\s*\(/)
assert.match(logs, /1000|KEEP|MAX_LOG/)
console.log('utility routes regression passed')
