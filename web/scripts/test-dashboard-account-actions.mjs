import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const api = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const dashboard = readFileSync(new URL('../src/components/Dashboard.vue', import.meta.url), 'utf8')

assert.match(api, /getAccountAccessToken:\s*\(email\)\s*=>\s*request\('GET',\s*`\/accounts\/\$\{encodeURIComponent\(email\)\}\/access-token`\)/, 'API exposes per-account access token route')
assert.match(api, /getAccountSubscription:\s*\(email\)\s*=>\s*request\('GET',\s*`\/accounts\/\$\{encodeURIComponent\(email\)\}\/subscription`\)/, 'API exposes per-account subscription route')

assert.match(dashboard, /@click="copyAccountAccessToken\(acc\.email\)"/, 'account row has 获取ac action')
assert.match(dashboard, /@click="queryAccountSubscription\(acc\.email\)"/, 'account row has 订阅查询 action')
assert.ok(
  dashboard.indexOf("{{ actionEmail === acc.email && actionType === 'subscription' ? '查询中...' : '订阅查询' }}")
    < dashboard.indexOf('缺认证'),
  '缺认证 badge is rendered after 订阅查询 action'
)
assert.match(dashboard, /subscriptionDialog/, 'dashboard renders subscription dialog state')
assert.match(dashboard, /accountActionBusy/, 'account actions share a global busy guard')
assert.match(dashboard, /accountActionRequestId/, 'account actions guard stale async responses')
assert.match(dashboard, /requestId !== accountActionRequestId\.value/, 'stale account action responses are ignored')
assert.match(dashboard, /订阅状态/, 'subscription dialog uses requested title')
assert.match(dashboard, /订阅生效中/, 'subscription dialog shows active status pill')
assert.match(dashboard, /自动续费/, 'subscription dialog shows auto-renew pill')
assert.match(dashboard, /JWT=/, 'subscription dialog shows JWT plan pill')
assert.match(dashboard, /席位/, 'subscription dialog shows seat summary')
assert.match(dashboard, /是否曾付费/, 'subscription dialog shows paid-before summary')
assert.match(dashboard, /已应用优惠/, 'subscription dialog shows applied discounts')
assert.match(dashboard, /查看原始 JSON/, 'subscription dialog includes raw JSON disclosure')
assert.match(dashboard, /网页 \(Web\)/, 'subscription dialog maps chatgpt_web channel label')
assert.match(dashboard, /subscriptionPlanKey/, 'subscription dialog can render raw ChatGPT plan keys')
assert.match(dashboard, /remaining_days/, 'subscription dialog renders remaining subscription days')
assert.doesNotMatch(dashboard, /if \(subscriptionDialog\.value\.loading\) return/, 'subscription dialog can be closed while loading')
