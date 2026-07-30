import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const momoPage = readFileSync(new URL('../src/components/MomoPage.vue', import.meta.url), 'utf8')

assert.match(momoPage, /function isOaicsUnsupportedMomoError\(message\)\s*\{/, 'Momo page defines oaics unsupported error detector')
assert.match(momoPage, /if\s*\(\s*status === 'failed'\s*&&\s*isOaicsUnsupportedMomoError\(accountStatusError\(account\)\)\s*\)\s*return '提链失败（oaics 当前不支持）'/, 'Momo page renders dedicated failed status text for oaics unsupported accounts')
assert.match(momoPage, /function recentResultErrorText\(item\)\s*\{[\s\S]*提链失败（oaics 当前不支持）/, 'Momo page maps oaics unsupported errors in recent result list')

console.log('momo status text tests passed')
