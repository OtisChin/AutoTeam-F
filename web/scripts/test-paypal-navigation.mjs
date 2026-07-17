import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(__dirname, '..')

const sidebar = readFileSync(resolve(webRoot, 'src/components/Sidebar.vue'), 'utf8')
const app = readFileSync(resolve(webRoot, 'src/App.vue'), 'utf8')

const gopayIndex = sidebar.indexOf("key: 'gopay'")
const paypalIndex = sidebar.indexOf("key: 'paypal'")

assert.ok(gopayIndex >= 0, 'Sidebar keeps the existing GoPay navigation item')
assert.ok(paypalIndex > gopayIndex, 'Sidebar shows PayPal after GoPay in the Payments group')
assert.match(sidebar, /\{\s*key: 'paypal',\s*group: 'Payments',\s*glyph: 'PP',\s*label: 'PayPal',\s*mobileLabel: 'PayPal'\s*\}/s)

assert.match(app, /PAGE_KEYS = new Set\(\[[^\]]*'paypal'/s, 'App accepts paypal as a persisted page key')
assert.match(app, /currentPage === 'paypal'/, 'App routes the PayPal page key')
assert.match(app, /功能待定/, 'PayPal page renders a pending-feature placeholder')

console.log('paypal navigation tests passed')
