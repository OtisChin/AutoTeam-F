import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(__dirname, '..')
const page = readFileSync(resolve(webRoot, 'src/components/UsPaypalPage.vue'), 'utf8')

assert.match(page, /\{\s*value:\s*'BA',\s*label:\s*'BA · 波黑'\s*\}/, 'PayPal 提链目标国家下拉支持 BA 波黑')
assert.match(page, /const promoRegionOptions = \[[\s\S]*\{\s*value:\s*'TH',\s*label:\s*'TH · 泰国'\s*\}/, 'PayPal 提链优惠区支持 TH 泰国')

console.log('paypal link UI tests passed')
