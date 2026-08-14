import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import {
  successfulPayPalLinkAccounts,
  paypalAccountCountryOptions,
  resolveSelectedPayPalLinkAccount,
} from '../src/paypalAccountOptions.js'

const __dirname = dirname(fileURLToPath(import.meta.url))

const accounts = [
  { email: 'new-nl@example.com', paypal_status: 'success', paypal_country: 'NL', last_active_at: 300 },
  { email: 'old-us@example.com', paypal_status: 'success', paypal_country: 'US', last_active_at: 100 },
  { email: 'failed-nl@example.com', paypal_status: 'failed', paypal_country: 'NL', last_active_at: 400 },
  { email: 'pending-ca@example.com', paypal_status: 'pending', paypal_country: 'CA', last_active_at: 450 },
  { email: 'running-gb@example.com', paypal_status: 'running', paypal_country: 'GB', last_active_at: 460 },
  { email: 'paid-br@example.com', paypal_status: 'paid', paypal_country: 'BR', last_active_at: 500 },
  { email: 'fresh-th@example.com', paypal_status: 'success', paypal_country: 'TH', last_active_at: 700 },
  { email: 'expired-br@example.com', paypal_status: 'success', paypal_country: 'BR', last_active_at: 800 },
]
const nowMs = Date.parse('2026-08-09T05:00:00Z')
const links = [
  { id: 'link-us', account_email: 'old-us@example.com', country: 'US', paypal_link: 'https://paypal.test/us', updated_at: 200, created_at_ts: nowMs / 1000 - 600 },
  { id: 'link-nl', account_email: 'new-nl@example.com', country: 'NL', paypal_link: 'https://paypal.test/nl', updated_at: 350, created_at_ts: nowMs / 1000 - 1200 },
  { id: 'link-failed', account_email: 'failed-nl@example.com', country: 'NL', paypal_link: 'https://paypal.test/failed', updated_at: 450, created_at_ts: nowMs / 1000 - 700 },
  { id: 'link-pending', account_email: 'pending-ca@example.com', country: 'CA', paypal_link: 'https://paypal.test/pending', updated_at: 460, created_at_ts: nowMs / 1000 - 500 },
  { id: 'link-running', account_email: 'running-gb@example.com', country: 'GB', paypal_link: 'https://paypal.test/running', updated_at: 470, created_at_ts: nowMs / 1000 - 400 },
  { id: 'link-orphan', account_email: 'orphan@example.com', country: 'GB', paypal_link: 'https://paypal.test/gb', updated_at: 600, created_at_ts: nowMs / 1000 - 1800 },
  { id: 'link-paid', account_email: 'paid-br@example.com', target_country: 'BR', paypal_link: 'https://paypal.test/paid', updated_at: 650, created_at_ts: nowMs / 1000 - 900 },
  { id: 'link-th', account_email: 'fresh-th@example.com', target_country: 'TH', country: 'DE', billing: { country: 'DE' }, paypal_link: 'https://paypal.test/th', updated_at: 750, created_at_ts: nowMs / 1000 - 100 },
  { id: 'link-expired', account_email: 'expired-br@example.com', target_country: 'BR', paypal_link: 'https://paypal.test/expired', updated_at: 850, created_at_ts: nowMs / 1000 - (3 * 3600 + 1) },
]

function testSuccessfulAccountsJoinLatestLinkAndFilterByCountry() {
  assert.deepEqual(
    successfulPayPalLinkAccounts(accounts, links, 'NL', { nowMs }).map((item) => ({ email: item.email, country: item.country, link: item.paypalLink })),
    [
      { email: 'failed-nl@example.com', country: 'NL', link: 'https://paypal.test/failed' },
      { email: 'new-nl@example.com', country: 'NL', link: 'https://paypal.test/nl' },
    ],
  )
  assert.deepEqual(
    successfulPayPalLinkAccounts(accounts, links, 'all', { nowMs }).map((item) => item.email),
    ['fresh-th@example.com', 'running-gb@example.com', 'pending-ca@example.com', 'failed-nl@example.com', 'new-nl@example.com', 'old-us@example.com'],
  )
}

function testCountryOptionsComeFromSuccessfulLinkedAccounts() {
  assert.deepEqual(paypalAccountCountryOptions(accounts, links, { nowMs }), ['CA', 'GB', 'NL', 'TH', 'US'])
}

function testSelectedAccountPopulatesProtocolFormFields() {
  assert.deepEqual(resolveSelectedPayPalLinkAccount(accounts, links, 'new-nl@example.com', { nowMs }), {
    email: 'new-nl@example.com',
    country: 'NL',
    paypalLink: 'https://paypal.test/nl',
  })
}

function testUsesTargetCountryAndHidesPaidOrExpiredLinks() {
  assert.deepEqual(
    successfulPayPalLinkAccounts(accounts, links, 'TH', { nowMs }).map((item) => ({ email: item.email, country: item.country })),
    [{ email: 'fresh-th@example.com', country: 'TH' }],
  )
  assert.equal(successfulPayPalLinkAccounts(accounts, links, 'BR', { nowMs }).length, 0)
}

function testPaymentLinkAccountsCanFilterByStatusAndReverseOrder() {
  assert.deepEqual(
    successfulPayPalLinkAccounts(accounts, links, 'all', { nowMs, statusFilter: 'failed' }).map((item) => item.email),
    ['failed-nl@example.com'],
  )
  assert.deepEqual(
    successfulPayPalLinkAccounts(accounts, links, 'all', { nowMs, sortOrder: 'asc' }).map((item) => item.email),
    ['old-us@example.com', 'new-nl@example.com', 'failed-nl@example.com', 'pending-ca@example.com', 'running-gb@example.com', 'fresh-th@example.com'],
  )
}

function testUsPaypalPageSubmitsOnlyOaicsFlag() {
  const page = readFileSync(resolve(__dirname, '../src/components/UsPaypalPage.vue'), 'utf8')
  assert.match(page, /onlyOaics:\s*false/, 'PayPal form defaults onlyOaics to false')
  assert.match(page, /v-model="form\.onlyOaics"/, 'PayPal form exposes onlyOaics checkbox')
  assert.match(page, /onlyOaics:\s*form\.value\.onlyOaics/, 'PayPal batch payload includes onlyOaics')
  assert.match(page, /仅\s*OAICS|仅Oaics/, 'PayPal page labels the only OAICS option')
}

function testUsPaypalPageCanFilterNonOaicsAccounts() {
  const page = readFileSync(resolve(__dirname, '../src/components/UsPaypalPage.vue'), 'utf8')
  assert.match(page, /non_oaics:\s*['"]非Oaics['"]/, 'PayPal page maps non_oaics status text')
  assert.match(page, /<option value="non_oaics">非Oaics<\/option>/, 'PayPal account status filter includes non_oaics')
}

testSuccessfulAccountsJoinLatestLinkAndFilterByCountry()
testCountryOptionsComeFromSuccessfulLinkedAccounts()
testSelectedAccountPopulatesProtocolFormFields()
testUsesTargetCountryAndHidesPaidOrExpiredLinks()
testPaymentLinkAccountsCanFilterByStatusAndReverseOrder()
testUsPaypalPageSubmitsOnlyOaicsFlag()
testUsPaypalPageCanFilterNonOaicsAccounts()
console.log('paypal account option tests passed')
