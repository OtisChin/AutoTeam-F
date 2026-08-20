import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(__dirname, '..')
const page = readFileSync(resolve(webRoot, 'src/components/UsPaypalPage.vue'), 'utf8')

assert.match(page, /\{\s*value:\s*'BA',\s*label:\s*'BA · 波黑'\s*\}/, 'PayPal 提链目标国家下拉支持 BA 波黑')
assert.match(page, /const promoRegionOptions = \[[\s\S]*\{\s*value:\s*'TH',\s*label:\s*'TH · 泰国'\s*\}/, 'PayPal 提链优惠区支持 TH 泰国')
assert.match(page, /const promoRegionOptions = \[[\s\S]*\{\s*value:\s*'GB',\s*label:\s*'GB · 英国'\s*\}/, 'PayPal 提链优惠区支持 GB 英国')
assert.match(page, /const promoRegionOptions = \[[\s\S]*\{\s*value:\s*'US',\s*label:\s*'US · 美国'\s*\}/, 'PayPal 提链优惠区支持 US 美国')
assert.match(page, /Access Token 输入（优先于账号池）/, 'PayPal 提链页提供 access token 输入框')
assert.match(page, /const directAccessTokens = computed\(\(\) => parseAccessTokens\(form\.value\.accessTokens\)\)/, '前端会解析多行 access token')
assert.match(page, /const accountEmails = accessTokens\.length \? \[\] :/, '填写 access token 后运行会忽略账号池')
assert.match(page, /accessTokens,/, '提链请求会提交 accessTokens 字段')
assert.match(page, /persistLinkJobState/, '提链页会持久化任务状态、日志和结果快照')
assert.match(page, /restoreLinkJobState/, '提链页刷新页面后会恢复任务状态、日志和结果快照')
assert.match(page, /resumeLinkJobStateFromStorage/, '切回提链页会从本地快照恢复任务状态和日志')
assert.match(page, /watch\(activeTab[\s\S]*resumeLinkJobStateFromStorage/, '切换回提链页会恢复并续轮询提链任务')
assert.match(page, /persistLinkJobState\(\{ jobId \}\)/, '提链任务完成后仍保存结果快照，刷新后不丢成功数据')
assert.doesNotMatch(page, /localStorage\.removeItem\(JOB_STORAGE_KEY\)/, '提链任务结束或恢复失败时不删除本地结果快照')

console.log('paypal link UI tests passed')
