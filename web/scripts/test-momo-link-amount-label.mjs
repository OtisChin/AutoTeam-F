import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const momoPage = readFileSync(new URL('../src/components/MomoPage.vue', import.meta.url), 'utf8')

assert.match(momoPage, /\{\{\s*momoLinkAmountLabel\(link\)\s*\}\}/, 'Momo page renders extracted-link amount through a dedicated formatter')
assert.match(momoPage, /function momoLinkAmountLabel\(link\)\s*\{/, 'Momo page defines an amount label formatter for extracted links')
assert.match(momoPage, /function momoLinkCurrency\(link\)\s*\{/, 'Momo page resolves display currency from link payloads')
assert.doesNotMatch(momoPage, /\{\{\s*link\.amount\s*\|\|\s*'-'\s*\}\}\s*KRW/, 'Momo page does not hardcode KRW in the extracted-link amount column')

console.log('momo link amount label tests passed')
