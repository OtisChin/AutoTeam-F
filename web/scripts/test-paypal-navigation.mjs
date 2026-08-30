import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(__dirname, '..')

const navigation = readFileSync(resolve(webRoot, 'src/navigation.js'), 'utf8')
const app = readFileSync(resolve(webRoot, 'src/App.vue'), 'utf8')

const gopayIndex = navigation.indexOf("key: 'gopay'")
const paypalIndex = navigation.indexOf("key: 'paypal'")

assert.ok(gopayIndex >= 0, 'Shared navigation keeps the existing GoPay item')
assert.ok(paypalIndex > gopayIndex, 'Shared navigation shows PayPal after GoPay in the payment group')
assert.match(navigation, /\{\s*key: 'paypal',\s*group: '支付',\s*icon: 'wallet',\s*label: 'PayPal',\s*description: 'PayPal 提链与协议支付'\s*\}/s)

assert.match(app, /import \{ NAV_ITEMS_BY_KEY, PAGE_KEYS \} from '\.\/navigation\.js'/, 'App uses the shared persisted-page key set')
assert.match(app, /paypal: \(\) => import\('\.\/components\/UsPaypalPage\.vue'\)/, 'App loads PayPal as an on-demand chunk')
assert.match(app, /currentPage === 'paypal'/, 'App routes the PayPal page key')
assert.doesNotMatch(app, /功能待定/, 'PayPal route no longer renders a pending-feature placeholder')

console.log('paypal navigation tests passed')
